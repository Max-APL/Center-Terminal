import subprocess
import os
import sys
import time
import threading
import collections
import psutil
import shutil
import tempfile
import uuid
from datetime import datetime
from shell_profiles import get_default_shell_id, get_shell_label, get_shell_profile
from workspace_startups import (
    DEFAULT_STARTUP_ID,
    get_startup_by_id,
    get_startup_id_from_label,
    get_startup_label,
    get_startup_options,
    normalize_workspace_startups,
    serialize_workspace_startups,
)
from deploy_profiles import (
    get_profile_by_id,
    get_profile_id_from_label,
    get_profile_label,
    get_profile_options,
    legacy_fields_from_profile,
    normalize_service_profiles,
    serialize_profiles,
)

class ServiceProcess:
    def __init__(self, config, workspace_id, on_state_change=None, on_log_received=None):
        self.id = config.get("id")
        self.workspace_id = workspace_id
        self.name = config.get("name", "Unnamed Service")
        self.command = config.get("command", "")
        self.cwd = config.get("cwd", "")
        self.auto_restart = config.get("auto_restart", False)
        self.restart_delay = config.get("restart_delay", 2)
        self.env = config.get("env", {})
        self.shell_type = config.get("shell") or get_default_shell_id()
        self.shell_native = config.get("shell_native", False)
        self.deploy_profiles, self.default_deploy_profile_id = normalize_service_profiles(config)
        self.selected_deploy_profile_id = self.default_deploy_profile_id
        self.pre_command = config.get("pre_command", "")
        self._sync_legacy_fields()

        # Callbacks
        self.on_state_change = on_state_change
        self.on_log_received = on_log_received

        # Runtime state
        self.status = "stopped"  # stopped, starting, running, error
        self.process = None
        self.start_time = None
        self.cpu_usage = 0.0
        self.mem_usage = 0  # in bytes
        self.exit_code = None

        # Logs buffer (thread-safe circular buffer)
        self.logs = collections.deque(maxlen=1000)  # Reducido de 2000 a 1000 para optimizar rendimiento en rejilla
        self.lock = threading.Lock()

        # Cache for psutil processes to calculate CPU delta correctly
        self._psutil_cache = {}

        # Internal control flags
        self._should_stop = False
        self._read_thread = None
        self._restart_timer = None
        self._last_execution_mode = None
        self._last_hidden = False

    def change_status(self, new_status):
        with self.lock:
            self.status = new_status
        if self.on_state_change:
            self.on_state_change(self.id, new_status)

    def _sync_legacy_fields(self):
        profile = self.get_selected_deploy_profile() or self.get_default_deploy_profile()
        pre_command, command = legacy_fields_from_profile(profile)
        self.pre_command = pre_command
        self.command = command
        if profile and profile.get("shell"):
            self.shell_type = profile.get("shell")

    def get_default_deploy_profile(self):
        return get_profile_by_id(self.deploy_profiles, self.default_deploy_profile_id)

    def get_selected_deploy_profile(self):
        return get_profile_by_id(self.deploy_profiles, self.selected_deploy_profile_id)

    def get_deploy_profile_options(self):
        return get_profile_options(self.deploy_profiles)

    def get_selected_deploy_profile_label(self):
        return get_profile_label(self.deploy_profiles, self.selected_deploy_profile_id)

    def get_profile_id_from_label(self, label):
        return get_profile_id_from_label(self.deploy_profiles, label)

    def select_deploy_profile(self, profile_id):
        if not get_profile_by_id(self.deploy_profiles, profile_id):
            return False
        self.selected_deploy_profile_id = profile_id
        self._sync_legacy_fields()
        return True

    def get_selected_shell_type(self):
        profile = self.get_selected_deploy_profile() or self.get_default_deploy_profile()
        return (profile or {}).get("shell") or self.shell_type or get_default_shell_id()

    def to_config(self):
        default_profile = self.get_default_deploy_profile()
        pre_command, command = legacy_fields_from_profile(default_profile)
        shell_type = (default_profile or {}).get("shell") or self.shell_type
        return {
            "id": self.id,
            "name": self.name,
            "pre_command": pre_command,
            "command": command,
            "cwd": self.cwd,
            "shell": shell_type,
            "shell_native": getattr(self, "shell_native", False),
            "auto_restart": self.auto_restart,
            "restart_delay": self.restart_delay,
            "env": self.env,
            "deploy_profiles": serialize_profiles(self.deploy_profiles),
            "default_deploy_profile_id": self.default_deploy_profile_id,
        }

    def _shell_display_name(self, shell_id):
        return get_shell_label(shell_id)

    def _escape_ps_message(self, text):
        return str(text).replace("'", "''")

    def _quote_sh(self, text):
        return "'" + str(text).replace("'", "'\"'\"'") + "'"

    def _bash_accessible_path(self, path, wsl=False):
        normalized = os.path.abspath(path).replace("\\", "/")
        if wsl and len(normalized) > 2 and normalized[1] == ":":
            drive = normalized[0].lower()
            return f"/mnt/{drive}{normalized[2:]}"
        return normalized

    def _new_status_path(self):
        fd, path = tempfile.mkstemp(prefix="central-terminal-status-", suffix=".txt", text=True)
        os.close(fd)
        try:
            os.remove(path)
        except OSError:
            pass
        return path

    def _powershell_command(self, command, cwd_dir=None):
        command = str(command or "").strip()
        if not command:
            return command

        cleaned = command
        if cleaned.startswith("& "):
            cleaned = cleaned[2:].strip()

        bare_path = cleaned.strip("'\"")
        if bare_path.lower().endswith("activate.ps1"):
            candidate = bare_path
            if cwd_dir and not os.path.isabs(candidate):
                candidate = os.path.join(cwd_dir, candidate)
            if os.path.exists(candidate):
                quoted = self._escape_ps_message(os.path.normpath(candidate))
                return f". '{quoted}'"
            return f". {cleaned}"

        return command

    def _profile_steps(self, profile):
        return [
            {
                "name": str(step.get("name") or f"Paso {index + 1}").strip(),
                "command": str(step.get("command") or "").strip(),
            }
            for index, step in enumerate((profile or {}).get("steps", []))
            if str(step.get("command") or "").strip()
        ]

    def _step_label(self, step, index, total):
        raw_name = step.get("name") or ""
        default_name = "Comando final" if index == total - 1 else f"Paso {index + 1}"
        return raw_name.strip() or default_name

    def _build_powershell_script(self, cwd_dir=None, profile=None, status_path=None, keep_open=False):
        lines = [
            "$ErrorActionPreference = 'Continue'",
            "if (Get-Variable PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {",
            "    $PSNativeCommandUseErrorActionPreference = $false",
            "}",
            "try {",
            "    if ($PROFILE -and (Test-Path $PROFILE)) { . $PROFILE }",
            "} catch {",
            "    Write-Host \"--- Aviso: no se pudo cargar el perfil de PowerShell: $($_.Exception.Message) ---\"",
            "}",
        ]
        if cwd_dir:
            cwd_literal = self._escape_ps_message(cwd_dir)
            lines.append(f"Set-Location -LiteralPath '{cwd_literal}'")

        steps = self._profile_steps(profile)
        total_steps = len(steps)
        for index, step in enumerate(steps):
            label = self._escape_ps_message(self._step_label(step, index, total_steps))
            command = self._powershell_command(step["command"], cwd_dir)
            is_last = index == total_steps - 1
            lines.extend([
                f"Write-Host '--- [Paso {index + 1}/{total_steps}] Ejecutando: {label} ---'",
                "$global:LASTEXITCODE = $null",
                command,
                "$__ct_step_code = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } elseif (-not $?) { 1 } else { 0 }",
                "if ($__ct_step_code -ne 0) {",
                "    Write-Host ''",
                f"    Write-Host \"--- [FALLO] {label} termino con error (Codigo: $__ct_step_code) ---\"",
            ])
            if status_path:
                quoted_status_path = self._escape_ps_message(status_path)
                lines.append(f"    Set-Content -LiteralPath '{quoted_status_path}' -Value $__ct_step_code -Encoding ASCII")
            lines.append("    return" if keep_open else "    exit $__ct_step_code")
            lines.append("}")
            if not is_last:
                lines.extend([
                    "Write-Host ''",
                    f"Write-Host '--- [EXITO] {label} completado. Continuando... ---'",
                    "Write-Host ''",
                ])

        if status_path:
            quoted_status_path = self._escape_ps_message(status_path)
            lines.append(f"Set-Content -LiteralPath '{quoted_status_path}' -Value $__ct_step_code -Encoding ASCII")

        if keep_open:
            lines.extend([
                "Write-Host ''",
                "Write-Host \"--- Proceso terminado con codigo de salida: $__ct_step_code ---\"",
                "$global:LASTEXITCODE = $__ct_step_code",
            ])
        else:
            lines.append("exit $__ct_step_code")
        return "\n".join(lines)

    def _build_cmd_script(self, profile=None, status_path=None, keep_open=False):
        lines = [
            "@echo off",
            "setlocal EnableExtensions",
        ]

        steps = self._profile_steps(profile)
        total_steps = len(steps)
        for index, step in enumerate(steps):
            label = self._step_label(step, index, total_steps)
            is_last = index == total_steps - 1
            lines.extend([
                f"echo --- [Paso {index + 1}/{total_steps}] Ejecutando: {label} ---",
                f"call {step['command']}",
                "set \"CT_STEP_CODE=%ERRORLEVEL%\"",
                "if not \"%CT_STEP_CODE%\"==\"0\" goto ct_step_failed",
            ])
            if not is_last:
                lines.extend([
                    "echo.",
                    f"echo --- [EXITO] {label} completado. Continuando... ---",
                    "echo.",
                ])

        if status_path:
            lines.append(f"> \"{status_path}\" echo %CT_STEP_CODE%")

        if keep_open:
            lines.extend([
                "echo.",
                "echo --- Proceso terminado con codigo de salida: %CT_STEP_CODE% ---",
                "goto ct_end",
            ])
        else:
            lines.append("exit /b %CT_STEP_CODE%")

        lines.extend([
            ":ct_step_failed",
            "echo.",
            "echo --- [FALLO] El flujo termino con error Codigo: %CT_STEP_CODE% ---",
        ])
        if status_path:
            lines.append(f"> \"{status_path}\" echo %CT_STEP_CODE%")
        lines.append("goto ct_end" if keep_open else "exit /b %CT_STEP_CODE%")

        if keep_open:
            lines.extend([
                ":ct_end",
                "endlocal",
            ])

        return "\r\n".join(lines) + "\r\n"

    def _build_bash_script(self, profile=None, status_path=None, wsl=False, keep_open=False):
        lines = ["set +e"]
        steps = self._profile_steps(profile)
        total_steps = len(steps)
        quoted_status_path = None
        if status_path:
            quoted_status_path = self._quote_sh(self._bash_accessible_path(status_path, wsl=wsl))

        for index, step in enumerate(steps):
            label = self._step_label(step, index, total_steps)
            is_last = index == total_steps - 1
            lines.extend([
                f"echo {self._quote_sh(f'--- [Paso {index + 1}/{total_steps}] Ejecutando: {label} ---')}",
                step["command"],
                "ct_step_code=$?",
                "if [ \"$ct_step_code\" -ne 0 ]; then",
                "  echo",
                f"  echo {self._quote_sh(f'--- [FALLO] {label} termino con error ---')}",
                f"  echo \"$ct_step_code\" > {quoted_status_path}" if quoted_status_path else "  :",
                "  exec bash -i" if keep_open else "  exit \"$ct_step_code\"",
                "fi",
            ])
            if not is_last:
                lines.extend([
                    "echo",
                    f"echo {self._quote_sh(f'--- [EXITO] {label} completado. Continuando... ---')}",
                    "echo",
                ])

        if quoted_status_path:
            lines.append(f"echo \"$ct_step_code\" > {quoted_status_path}")
        if keep_open:
            lines.extend([
                "echo",
                "echo \"--- Proceso terminado con codigo de salida: $ct_step_code ---\"",
                "exec bash -i",
            ])
        else:
            lines.append("exit \"$ct_step_code\"")
        return "\n".join(lines)

    def _build_generic_chain(self, profile=None, separator=" && "):
        commands = [step["command"] for step in self._profile_steps(profile)]
        return separator.join(commands)

    def _build_powershell_terminal_script(self, cwd_dir=None, status_path=None, profile=None):
        return self._build_powershell_script(cwd_dir, profile=profile, status_path=status_path, keep_open=True)

    def _build_cmd_terminal_script(self, status_path=None, profile=None):
        return self._build_cmd_script(profile=profile, status_path=status_path, keep_open=True)

    def _build_bash_terminal_script(self, status_path=None, wsl=False, profile=None):
        return self._build_bash_script(profile=profile, status_path=status_path, wsl=wsl, keep_open=True)

    def _build_native_terminal_args(self, shell_id, cwd_dir=None, flow_profile=None):
        shell_profile = get_shell_profile(shell_id)
        executable = shell_profile.executable
        prefix = ["conhost.exe"] if sys.platform == "win32" and shutil.which("conhost.exe") else []
        status_path = self._new_status_path()

        if shell_profile.kind == "powershell":
            script_path = self._write_temp_script(
                ".ps1",
                self._build_powershell_terminal_script(cwd_dir, status_path=status_path, profile=flow_profile),
                encoding="utf-8-sig",
            )
            args = [executable, *shell_profile.args, "-NoLogo", "-NoExit"]
            if os.path.basename(executable).lower().startswith("powershell"):
                args.extend(["-ExecutionPolicy", "Bypass"])
            args.extend(["-File", script_path])
            return prefix + args, script_path, status_path

        if shell_profile.kind == "cmd":
            script_path = self._write_temp_script(".cmd", self._build_cmd_terminal_script(status_path=status_path, profile=flow_profile))
            return prefix + [executable, *shell_profile.args, "/d", "/s", "/k", script_path], script_path, status_path

        if shell_profile.kind == "posix":
            return prefix + [executable, *shell_profile.args, "-c", self._build_bash_terminal_script(status_path=status_path, profile=flow_profile)], None, status_path

        if shell_profile.kind == "wsl":
            return prefix + [
                executable,
                *shell_profile.args,
                "--exec",
                "bash",
                "-lc",
                self._build_bash_terminal_script(status_path=status_path, wsl=True, profile=flow_profile),
            ], None, status_path

        if shell_profile.kind == "fish":
            fish_command = self._build_generic_chain(flow_profile, separator="; and ")
            fish_status_path = self._bash_accessible_path(status_path)
            return prefix + [
                executable,
                *shell_profile.args,
                "-c",
                f"{fish_command}; set ct_main_code $status; echo; echo \"--- Proceso terminado con codigo de salida: $ct_main_code ---\"; echo $ct_main_code > {self._quote_sh(fish_status_path)}; exec fish",
            ], None, status_path

        if shell_profile.kind == "nushell":
            nu_command = self._build_generic_chain(flow_profile, separator="; ")
            return prefix + [
                executable,
                *shell_profile.args,
                "-c",
                f"{nu_command}; print ''; print '--- Proceso terminado ---'",
            ], None, None

        generic_command = self._build_generic_chain(flow_profile, separator=" && ")
        return prefix + [executable, *shell_profile.args, "-c", generic_command], None, None

    def _build_captured_shell_args(self, shell_id, cwd_dir=None, flow_profile=None):
        profile = get_shell_profile(shell_id)

        if profile.kind == "powershell":
            executable = profile.executable
            script_path = self._write_temp_script(".ps1", self._build_powershell_script(cwd_dir, profile=flow_profile), encoding="utf-8-sig")
            if os.path.basename(executable).lower().startswith("powershell"):
                return [executable, "-NoLogo", "-ExecutionPolicy", "Bypass", "-File", script_path]
            return [executable, "-NoLogo", "-File", script_path]

        if profile.kind == "cmd":
            script_path = self._write_temp_script(".cmd", self._build_cmd_script(profile=flow_profile))
            return [profile.executable, *profile.args, "/d", "/s", "/c", script_path]

        if profile.kind == "posix":
            return [profile.executable, *profile.args, "-c", self._build_bash_script(profile=flow_profile)]

        if profile.kind == "wsl":
            return [profile.executable, *profile.args, "--exec", "bash", "-lc", self._build_bash_script(profile=flow_profile, wsl=True)]

        if profile.kind == "fish":
            fish_command = self._build_generic_chain(flow_profile, separator="; and ")
            return [profile.executable, *profile.args, "-c", fish_command]

        if profile.kind == "nushell":
            nu_command = self._build_generic_chain(flow_profile, separator="; ")
            return [profile.executable, *profile.args, "-c", nu_command]

        generic_command = self._build_generic_chain(flow_profile, separator=" && ")
        return [profile.executable, *profile.args, "-c", generic_command]

    def _write_temp_script(self, suffix, content, encoding=None):
        fd, path = tempfile.mkstemp(prefix="central-terminal-", suffix=suffix, text=True)
        encoding = encoding or ("mbcs" if sys.platform == "win32" else "utf-8")
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
        return path

    def _cleanup_temp_script(self, path):
        if not path:
            return
        try:
            os.remove(path)
        except OSError:
            pass

    def _wait_for_native_completion(self, status_path, process):
        while not self._should_stop:
            if status_path and os.path.exists(status_path):
                try:
                    with open(status_path, "r", encoding="ascii", errors="ignore") as f:
                        raw_code = f.read().strip()
                    if raw_code:
                        return int(raw_code.splitlines()[-1].strip())
                except (OSError, ValueError):
                    return 1

            if process and process.poll() is not None:
                return process.returncode if process.returncode is not None else 0

            time.sleep(0.2)

        return -1

    def _stream_process_output(self, process):
        if not process or not process.stdout:
            return process.wait() if process else -1

        for line in iter(process.stdout.readline, b''):
            if self._should_stop:
                break
            try:
                decoded = line.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    decoded = line.decode('cp1252')
                except UnicodeDecodeError:
                    decoded = line.decode('latin-1', errors='replace')
            self._add_log(decoded)

        process.stdout.close()
        return process.wait()

    def start(self, execution_mode=None, hidden=False):
        if self.status in ["running", "starting"]:
            return

        if self.process and self.process.poll() is None:
            self._kill_process_tree(self.process.pid)
            self.process = None
            if hasattr(self, "console_hwnd"):
                self.console_hwnd = None

        self._last_execution_mode = execution_mode
        self._last_hidden = hidden
        self._should_stop = False
        self.change_status("starting")
        self.exit_code = None
        
        # Clear logs on start
        with self.lock:
            self.logs.clear()
        
        # Prepare environment
        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        def run():
            temp_script_path = None
            status_path = None
            try:
                cwd_dir = self.cwd if self.cwd and os.path.exists(self.cwd) else None
                creationflags = 0
                flow_profile = self.get_selected_deploy_profile() or self.get_default_deploy_profile()
                flow_steps = self._profile_steps(flow_profile)
                flow_name = (flow_profile or {}).get("name", "Predeterminado")
                shell_id = (flow_profile or {}).get("shell") or self.shell_type
                mode = execution_mode or "captured"

                if not flow_steps:
                    self.exit_code = -1
                    self.change_status("error")
                    self._add_log(f"--- [FALLO] El flujo '{flow_name}' no tiene pasos configurados ---\n")
                    return

                # 1. Consola nativa: externa o lista para embeber en el workspace.
                if mode in ("native_external", "native_terminal"):
                    if sys.platform == "win32":
                        creationflags = subprocess.CREATE_NEW_CONSOLE

                    if self._should_stop:
                        self.change_status("stopped")
                        return

                    cmd_args, temp_script_path, status_path = self._build_native_terminal_args(shell_id, cwd_dir, flow_profile=flow_profile)
                    startupinfo = None
                    if hidden and sys.platform == "win32":
                        startupinfo = subprocess.STARTUPINFO()
                        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                        startupinfo.wShowWindow = 0

                    native_label = "terminal nativa embebida" if mode == "native_terminal" else "consola nativa externa"
                    msg = f"--- Ejecutando flujo '{flow_name}' en {native_label} ({self._shell_display_name(shell_id)}) ---\n"
                    msg += f"Directorio: {cwd_dir or 'Predeterminado'}\n\n"
                    if mode == "native_external":
                        msg += "El proceso se esta ejecutando en una ventana de consola externa independiente.\n"
                        msg += "Usa esa ventana externa para ver los logs e interactuar.\n"
                    else:
                        msg += "El proceso se esta ejecutando como terminal normal dentro del workspace.\n"
                    msg += "Al detener el servicio desde Central Terminal, la consola se cerrara automaticamente.\n"
                    self._add_log(msg)

                    self.process = subprocess.Popen(
                        cmd_args,
                        shell=False,
                        cwd=cwd_dir,
                        env=run_env,
                        stdout=None,
                        stderr=None,
                        creationflags=creationflags,
                        startupinfo=startupinfo,
                    )
                    self.start_time = time.time()
                    self.change_status("running")

                    try:
                        exit_code = self._wait_for_native_completion(status_path, self.process)
                    finally:
                        self._cleanup_temp_script(temp_script_path)
                        self._cleanup_temp_script(status_path)
                        temp_script_path = None
                        status_path = None
                    self.exit_code = exit_code

                # 2. Consola capturada: mantiene compatibilidad para auditoria/logs.
                else:
                    if sys.platform == "win32":
                        creationflags = subprocess.CREATE_NO_WINDOW

                    if self._should_stop:
                        self.change_status("stopped")
                        return

                    self._add_log(f"--- Ejecutando flujo '{flow_name}' ({self._shell_display_name(shell_id)}) ---\n")
                    cmd_args = self._build_captured_shell_args(shell_id, cwd_dir, flow_profile=flow_profile)
                    use_shell = not isinstance(cmd_args, list)
                    profile = get_shell_profile(shell_id)
                    if profile.kind in ("cmd", "powershell") and isinstance(cmd_args, list):
                        temp_script_path = cmd_args[-1]
                    self.process = subprocess.Popen(
                        cmd_args,
                        shell=use_shell,
                        cwd=cwd_dir,
                        env=run_env,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        creationflags=creationflags
                    )
                    
                    self.start_time = time.time()
                    self.change_status("running")

                    try:
                        exit_code = self._stream_process_output(self.process)
                    finally:
                        self._cleanup_temp_script(temp_script_path)
                        temp_script_path = None
                    self.exit_code = exit_code

                # 3. Mapear resultados finales de la ejecución
                if not self._should_stop:
                    if exit_code == 0:
                        self.change_status("stopped")
                    else:
                        self.change_status("error")
                        
                    log_msg = f"\n--- Proceso terminado con código de salida: {exit_code} ---\n"
                    self._add_log(log_msg)

                    if self.auto_restart and not self._should_stop:
                        self._trigger_auto_restart()
                else:
                    self.change_status("stopped")
                    self._add_log("\n--- Servicio detenido por el usuario ---\n")

            except Exception as e:
                self._cleanup_temp_script(temp_script_path)
                self._cleanup_temp_script(status_path)
                self.exit_code = -1
                self.change_status("error")
                err_msg = f"Error al iniciar el servicio: {str(e)}\n"
                self._add_log(err_msg)

        threading.Thread(target=run, daemon=True).start()

    def _read_stdout(self):
        process = self.process
        if not process or not process.stdout:
            return

        for line in iter(process.stdout.readline, b''):
            try:
                decoded = line.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    decoded = line.decode('cp1252')
                except UnicodeDecodeError:
                    decoded = line.decode('latin-1', errors='replace')
            
            self._add_log(decoded)
            
        process.stdout.close()

    def _add_log(self, text):
        with self.lock:
            self.logs.append(text)
        if self.on_log_received:
            self.on_log_received(self.id, text)

        # Escribir automáticamente en archivo de auditoría local
        try:
            import re
            from config import get_base_dir
            base_dir = get_base_dir()
            logs_dir = os.path.join(base_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            
            sanitized_name = "".join(c for c in self.name if c.isalnum() or c in (' ', '_', '-')).strip()
            sanitized_name = sanitized_name.replace(' ', '_')
            file_path = os.path.join(logs_dir, f"{sanitized_name}_{self.id}.txt")
            
            # Limpiar secuencias de escape ANSI del texto antes de guardarlo
            ansi_escape = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]')
            clean_text = ansi_escape.sub('', text)
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            lines = clean_text.splitlines(keepends=False)
            formatted = []
            for line in lines:
                # Omitir el prefijo si es una línea completamente vacía
                if line.strip():
                    formatted.append(f"[{timestamp}] {line}\n")
                else:
                    formatted.append(f"{line}\n")
            
            with open(file_path, "a", encoding="utf-8") as f:
                f.writelines(formatted)
        except Exception as e:
            sys.stderr.write(f"Error escribiendo log automático del servicio {self.name}: {e}\n")

    def _trigger_auto_restart(self):
        if self._should_stop:
            return
        
        self._add_log(f"Reiniciando automáticamente en {self.restart_delay} segundos...\n")
        
        def delayed_start():
            slept = 0.0
            while slept < self.restart_delay:
                if self._should_stop:
                    return
                time.sleep(0.5)
                slept += 0.5
            
            if not self._should_stop:
                self.start(execution_mode=self._last_execution_mode, hidden=self._last_hidden)

        self._restart_timer = threading.Thread(target=delayed_start, daemon=True)
        self._restart_timer.start()

    def stop(self):
        self._should_stop = True
        self.change_status("stopped")
        
        if self.process:
            pid = self.process.pid
            self._kill_process_tree(pid)
            self.process = None
        if hasattr(self, "console_hwnd"):
            self.console_hwnd = None

        self.cpu_usage = 0.0
        self.mem_usage = 0
        self.start_time = None

    def _kill_process_tree(self, parent_pid):
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            
            # Intentar primero una detención controlada/graciosa (SIGTERM)
            for child in children:
                try:
                    child.terminate()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            try:
                parent.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
                
            # Esperar brevemente (máximo 1 segundo) a que finalicen limpiamente
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            
            # Si todavía quedan procesos vivos, forzar su detención inmediata (SIGKILL)
            for p in alive:
                try:
                    p.kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    def update_resource_usage(self):
        if not self.process or self.process.poll() is not None:
            self.cpu_usage = 0.0
            self.mem_usage = 0
            return

        try:
            parent_pid = self.process.pid
            
            if parent_pid not in self._psutil_cache:
                try:
                    self._psutil_cache[parent_pid] = psutil.Process(parent_pid)
                except psutil.NoSuchProcess:
                    self.cpu_usage = 0.0
                    self.mem_usage = 0
                    return

            parent_proc = self._psutil_cache[parent_pid]
            
            try:
                children = parent_proc.children(recursive=True)
            except Exception:
                children = []

            total_cpu = 0.0
            total_mem = 0

            try:
                total_cpu += parent_proc.cpu_percent(interval=None)
                total_mem += parent_proc.memory_info().rss
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            for child in children:
                pid = child.pid
                if pid not in self._psutil_cache:
                    self._psutil_cache[pid] = child
                
                proc = self._psutil_cache[pid]
                try:
                    total_cpu += proc.cpu_percent(interval=None)
                    total_mem += proc.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            active_pids = {parent_pid} | {c.pid for c in children}
            self._psutil_cache = {pid: proc for pid, proc in self._psutil_cache.items() if pid in active_pids}

            num_cores = psutil.cpu_count() or 1
            self.cpu_usage = min(100.0, total_cpu / num_cores)
            self.mem_usage = total_mem

        except Exception:
            self.cpu_usage = 0.0
            self.mem_usage = 0

    def get_uptime(self):
        if not self.start_time or self.status != "running":
            return "0s"
        
        elapsed = int(time.time() - self.start_time)
        hours, remainder = divmod(elapsed, 3600)
        minutes, seconds = divmod(remainder, 60)
        
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def get_logs(self):
        with self.lock:
            return "".join(self.logs)

    def get_log_entries(self):
        with self.lock:
            return list(self.logs)


class ServiceManager:
    def __init__(self, workspaces_config, on_state_change=None, on_log_received=None):
        self.on_state_change = on_state_change
        self.on_log_received = on_log_received
        
        # Mapeos principales
        self.workspaces = {}          # workspace_id -> nombre
        self.services = {}            # service_id -> ServiceProcess
        self.workspace_services = {}  # workspace_id -> lista de ServiceProcess
        self.workspace_startups = {}  # workspace_id -> lista de inicios
        self.workspace_selected_startups = {}  # workspace_id -> inicio seleccionado en sesión
        
        # Cargar configuración estructurada
        for ws_cfg in workspaces_config.get("workspaces", []):
            ws_id = ws_cfg.get("id")
            ws_name = ws_cfg.get("name")
            self.workspaces[ws_id] = ws_name
            self.workspace_services[ws_id] = []
            
            for svc_cfg in ws_cfg.get("services", []):
                service = ServiceProcess(
                    svc_cfg, 
                    workspace_id=ws_id,
                    on_state_change=self._handle_state_change, 
                    on_log_received=self._handle_log_received
                )
                self.services[service.id] = service
                self.workspace_services[ws_id].append(service)

            self.workspace_startups[ws_id] = normalize_workspace_startups(ws_cfg, self.workspace_services[ws_id])
            self.workspace_selected_startups[ws_id] = DEFAULT_STARTUP_ID

        # Hilo de monitoreo
        self._monitoring_active = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def _handle_state_change(self, service_id, status):
        if self.on_state_change:
            self.on_state_change(service_id, status)

    def _handle_log_received(self, service_id, text):
        if self.on_log_received:
            self.on_log_received(service_id, text)

    def _monitor_loop(self):
        while self._monitoring_active:
            for service in list(self.services.values()):
                if service.status == "running":
                    service.update_resource_usage()
                else:
                    service.cpu_usage = 0.0
                    service.mem_usage = 0
            time.sleep(1.0)

    # --- Acciones sobre Espacios de Trabajo ---
    def add_workspace(self, workspace_id, name):
        self.workspaces[workspace_id] = name
        self.workspace_services[workspace_id] = []
        self.workspace_startups[workspace_id] = normalize_workspace_startups({}, [])
        self.workspace_selected_startups[workspace_id] = DEFAULT_STARTUP_ID

    def remove_workspace(self, workspace_id):
        # Detener y eliminar todos los servicios de ese workspace
        if workspace_id in self.workspace_services:
            for service in list(self.workspace_services[workspace_id]):
                self.remove_service(service.id)
            del self.workspace_services[workspace_id]
            
        if workspace_id in self.workspaces:
            del self.workspaces[workspace_id]
        self.workspace_startups.pop(workspace_id, None)
        self.workspace_selected_startups.pop(workspace_id, None)

    def refresh_workspace_startups(self, workspace_id):
        services = self.workspace_services.get(workspace_id, [])
        current = self.workspace_startups.get(workspace_id, [])
        custom = serialize_workspace_startups(current)
        self.workspace_startups[workspace_id] = normalize_workspace_startups({"startup_profiles": custom}, services)
        if not get_startup_by_id(self.workspace_startups[workspace_id], self.workspace_selected_startups.get(workspace_id)):
            self.workspace_selected_startups[workspace_id] = DEFAULT_STARTUP_ID

    def get_workspace_startup_options(self, workspace_id):
        self.refresh_workspace_startups(workspace_id)
        return get_startup_options(self.workspace_startups.get(workspace_id, []))

    def get_selected_workspace_startup_label(self, workspace_id):
        self.refresh_workspace_startups(workspace_id)
        return get_startup_label(
            self.workspace_startups.get(workspace_id, []),
            self.workspace_selected_startups.get(workspace_id, DEFAULT_STARTUP_ID),
        )

    def get_workspace_startup_id_from_label(self, workspace_id, label):
        self.refresh_workspace_startups(workspace_id)
        return get_startup_id_from_label(self.workspace_startups.get(workspace_id, []), label)

    def select_workspace_startup(self, workspace_id, startup_id):
        self.refresh_workspace_startups(workspace_id)
        startup = get_startup_by_id(self.workspace_startups.get(workspace_id, []), startup_id)
        if not startup:
            return False

        services = self.workspace_services.get(workspace_id, [])
        mapping = startup.get("service_profiles") or {}
        for service in services:
            profile_id = mapping.get(service.id, service.default_deploy_profile_id)
            if not service.select_deploy_profile(profile_id):
                service.select_deploy_profile(service.default_deploy_profile_id)

        self.workspace_selected_startups[workspace_id] = startup["id"]
        return True

    def save_workspace_startup(self, workspace_id, startup_config):
        self.refresh_workspace_startups(workspace_id)
        startup_id = startup_config.get("id")
        if startup_id == DEFAULT_STARTUP_ID:
            return None

        startup = {
            "id": startup_id or str(uuid.uuid4()),
            "name": startup_config.get("name", "Inicio"),
            "service_profiles": startup_config.get("service_profiles", {}),
        }

        startups = self.workspace_startups.get(workspace_id, [])
        for index, existing in enumerate(startups):
            if existing.get("id") == startup["id"]:
                startups[index] = startup
                break
        else:
            startups.append(startup)

        self.refresh_workspace_startups(workspace_id)
        self.workspace_selected_startups[workspace_id] = startup["id"]
        self.select_workspace_startup(workspace_id, startup["id"])
        return startup

    def remove_workspace_startup(self, workspace_id, startup_id):
        if startup_id == DEFAULT_STARTUP_ID:
            return False

        startups = self.workspace_startups.get(workspace_id, [])
        self.workspace_startups[workspace_id] = [startup for startup in startups if startup.get("id") != startup_id]
        if self.workspace_selected_startups.get(workspace_id) == startup_id:
            self.workspace_selected_startups[workspace_id] = DEFAULT_STARTUP_ID
            self.select_workspace_startup(workspace_id, DEFAULT_STARTUP_ID)
        self.refresh_workspace_startups(workspace_id)
        return True

    def get_workspace_startup_config(self, workspace_id, startup_id):
        self.refresh_workspace_startups(workspace_id)
        startup = get_startup_by_id(self.workspace_startups.get(workspace_id, []), startup_id)
        if not startup:
            return None
        return {
            "id": startup.get("id"),
            "name": startup.get("name"),
            "service_profiles": dict(startup.get("service_profiles") or {}),
        }

    def get_workspace_startups_config(self, workspace_id):
        self.refresh_workspace_startups(workspace_id)
        return serialize_workspace_startups(self.workspace_startups.get(workspace_id, []))

    def start_workspace(self, workspace_id, execution_mode=None, hidden=False):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.start(execution_mode=execution_mode, hidden=hidden)

    def stop_workspace(self, workspace_id):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.stop()

    def restart_workspace(self, workspace_id, execution_mode=None, hidden=False):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.stop()
            time.sleep(0.5)
            for service in self.workspace_services[workspace_id]:
                service.start(execution_mode=execution_mode, hidden=hidden)

    def get_workspace_stats(self, workspace_id):
        total_cpu = 0.0
        total_mem = 0
        running_count = 0
        services = self.workspace_services.get(workspace_id, [])
        
        for service in services:
            if service.status == "running":
                total_cpu += service.cpu_usage
                total_mem += service.mem_usage
                running_count += 1
                
        return {
            "total_cpu": min(100.0, total_cpu),
            "total_mem": total_mem,
            "running_count": running_count,
            "total_count": len(services)
        }

    # --- Acciones sobre Servicios ---
    def add_service(self, workspace_id, config):
        if workspace_id not in self.workspace_services:
            self.add_workspace(workspace_id, "Espacio Nuevo")
            
        service = ServiceProcess(
            config,
            workspace_id=workspace_id,
            on_state_change=self._handle_state_change,
            on_log_received=self._handle_log_received
        )
        self.services[service.id] = service
        self.workspace_services[workspace_id].append(service)
        self.refresh_workspace_startups(workspace_id)
        return service

    def update_service(self, service_id, config):
        if service_id not in self.services:
            return None
        
        service = self.services[service_id]
        is_running = service.status in ["running", "starting"]
        if is_running:
            service.stop()

        service.name = config.get("name", service.name)
        service.cwd = config.get("cwd", service.cwd)
        service.shell_native = config.get("shell_native", service.shell_native)
        service.auto_restart = config.get("auto_restart", service.auto_restart)
        service.restart_delay = config.get("restart_delay", service.restart_delay)
        service.env = config.get("env", service.env)
        service.deploy_profiles, service.default_deploy_profile_id = normalize_service_profiles(config)
        if not get_profile_by_id(service.deploy_profiles, service.selected_deploy_profile_id):
            service.selected_deploy_profile_id = service.default_deploy_profile_id
        service._sync_legacy_fields()
        self.refresh_workspace_startups(service.workspace_id)

        if is_running:
            service.start(execution_mode=service._last_execution_mode, hidden=service._last_hidden)
            
        return service

    def remove_service(self, service_id):
        if service_id in self.services:
            service = self.services[service_id]
            service.stop()
            
            # Quitar de la lista del workspace
            ws_id = service.workspace_id
            if ws_id in self.workspace_services and service in self.workspace_services[ws_id]:
                self.workspace_services[ws_id].remove(service)
                
            del self.services[service_id]
            self.refresh_workspace_startups(ws_id)
            return True
        return False

    def start_service(self, service_id, execution_mode=None, hidden=False):
        if service_id in self.services:
            self.services[service_id].start(execution_mode=execution_mode, hidden=hidden)

    def stop_service(self, service_id):
        if service_id in self.services:
            self.services[service_id].stop()

    def restart_service(self, service_id, execution_mode=None, hidden=False):
        if service_id in self.services:
            self.services[service_id].stop()
            time.sleep(0.5)
            self.services[service_id].start(execution_mode=execution_mode, hidden=hidden)

    # --- Estadísticas Globales ---
    def get_global_stats(self):
        total_cpu = 0.0
        total_mem = 0
        running_count = 0
        
        for service in self.services.values():
            if service.status == "running":
                total_cpu += service.cpu_usage
                total_mem += service.mem_usage
                running_count += 1
                
        return {
            "total_cpu": min(100.0, total_cpu),
            "total_mem": total_mem,
            "running_count": running_count,
            "total_count": len(self.services),
            "workspaces_count": len(self.workspaces)
        }

    def shutdown(self):
        self._monitoring_active = False
        for service in list(self.services.values()):
            service.stop()
