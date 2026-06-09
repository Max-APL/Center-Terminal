import subprocess
import os
import sys
import time
import threading
import collections
import psutil
import shutil
import tempfile
from datetime import datetime

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
        self.shell_type = config.get("shell", "default")
        self.shell_native = config.get("shell_native", False)
        self.pre_command = config.get("pre_command", "")

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

    def change_status(self, new_status):
        with self.lock:
            self.status = new_status
        if self.on_state_change:
            self.on_state_change(self.id, new_status)

    def _shell_executable(self, shell_lower):
        if shell_lower == "cmd" or shell_lower == "default":
            return "cmd.exe"
        if shell_lower == "pwsh":
            return "pwsh.exe"
        if shell_lower == "powershell":
            return "powershell.exe"
        if shell_lower == "bash":
            return "bash.exe"
        return "cmd.exe" if sys.platform == "win32" else "/bin/sh"

    def _shell_display_name(self, shell_lower):
        return {
            "cmd": "Command Prompt (CMD)",
            "default": "Command Prompt (CMD)",
            "pwsh": "PowerShell 7 (pwsh)",
            "powershell": "Windows PowerShell (powershell)",
            "bash": "Git Bash (Bash)"
        }.get(shell_lower, "Shell del sistema")

    def _escape_ps_message(self, text):
        return str(text).replace("'", "''")

    def _powershell_pre_command(self, cwd_dir=None):
        command = self.pre_command.strip()
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

        return self.pre_command

    def _powershell_diagnostic_lines(self, label="Diagnostico del entorno"):
        label = self._escape_ps_message(label)
        return [
            f"Write-Host '--- {label} ---'",
            "Write-Host \"PWD: $(Get-Location)\"",
            "Write-Host \"PowerShell: $($PSVersionTable.PSVersion)\"",
            "$__ct_node = Get-Command node -ErrorAction SilentlyContinue",
            "$__ct_npm = Get-Command npm -ErrorAction SilentlyContinue",
            "$__ct_python = Get-Command python -ErrorAction SilentlyContinue",
            "$__ct_pip = Get-Command pip -ErrorAction SilentlyContinue",
            "$__ct_uvicorn = Get-Command uvicorn -ErrorAction SilentlyContinue",
            "Write-Host \"Node: $(if ($__ct_node) { $__ct_node.Source } else { 'NO ENCONTRADO' })\"",
            "Write-Host \"NPM: $(if ($__ct_npm) { $__ct_npm.Source } else { 'NO ENCONTRADO' })\"",
            "Write-Host \"Python: $(if ($__ct_python) { $__ct_python.Source } else { 'NO ENCONTRADO' })\"",
            "Write-Host \"Pip: $(if ($__ct_pip) { $__ct_pip.Source } else { 'NO ENCONTRADO' })\"",
            "Write-Host \"Uvicorn: $(if ($__ct_uvicorn) { $__ct_uvicorn.Source } else { 'NO ENCONTRADO' })\"",
            "if ($__ct_node) { Write-Host \"Node version: $(node --version)\" }",
            "if ($__ct_npm) { Write-Host \"NPM version: $(npm --version)\" }",
            "if ($__ct_python) { Write-Host \"Python version: $(python --version)\" }",
            "if ($__ct_pip) { Write-Host \"Pip version: $(pip --version)\" }",
            "Write-Host ''",
        ]

    def _build_powershell_script(self, cwd_dir=None):
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

        lines.extend(self._powershell_diagnostic_lines())

        if self.pre_command:
            pre_label = self._escape_ps_message(self.pre_command)
            pre_command = self._powershell_pre_command(cwd_dir)
            lines.extend([
                f"Write-Host '--- [Paso 1/2] Ejecutando pre-comando: {pre_label} ---'",
                "$global:LASTEXITCODE = $null",
                pre_command,
                "$__ct_pre_code = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } elseif (-not $?) { 1 } else { 0 }",
                "if ($__ct_pre_code -ne 0) {",
                "    Write-Host ''",
                "    Write-Host \"--- [FALLO] El pre-comando termino con error (Codigo: $__ct_pre_code) ---\"",
                "    exit $__ct_pre_code",
                "}",
                "Write-Host ''",
                "Write-Host '--- [EXITO] Pre-comando completado. Iniciando comando principal... ---'",
                "Write-Host ''",
            ])
            lines.extend(self._powershell_diagnostic_lines("Diagnostico despues del pre-comando"))

        lines.extend([
            "$global:LASTEXITCODE = $null",
            self.command,
            "$__ct_main_code = if ($LASTEXITCODE -ne $null) { [int]$LASTEXITCODE } elseif (-not $?) { 1 } else { 0 }",
            "exit $__ct_main_code",
        ])
        return "\n".join(lines)

    def _build_cmd_script(self):
        lines = [
            "@echo off",
            "setlocal EnableExtensions",
        ]
        if self.pre_command:
            lines.extend([
                f"echo --- [Paso 1/2] Ejecutando pre-comando: {self.pre_command} ---",
                f"call {self.pre_command}",
                "set \"CT_PRE_CODE=%ERRORLEVEL%\"",
                "if not \"%CT_PRE_CODE%\"==\"0\" goto ct_pre_failed",
                "echo.",
                "echo --- [EXITO] Pre-comando completado. Iniciando comando principal... ---",
                "echo.",
            ])

        lines.extend([
            f"call {self.command}",
            "set \"CT_MAIN_CODE=%ERRORLEVEL%\"",
            "exit /b %CT_MAIN_CODE%",
        ])

        if self.pre_command:
            lines.extend([
                ":ct_pre_failed",
                "echo.",
                "echo --- [FALLO] El pre-comando termino con error Codigo: %CT_PRE_CODE% ---",
                "exit /b %CT_PRE_CODE%",
            ])

        return "\r\n".join(lines) + "\r\n"

    def _build_bash_script(self):
        if self.pre_command:
            return (
                f"echo '--- [Paso 1/2] Ejecutando pre-comando: {self.pre_command} ---'\n"
                f"{self.pre_command}\n"
                "ct_pre_code=$?\n"
                "if [ \"$ct_pre_code\" -ne 0 ]; then\n"
                "  echo\n"
                "  echo \"--- [FALLO] El pre-comando termino con error (Codigo: $ct_pre_code) ---\"\n"
                "  exit \"$ct_pre_code\"\n"
                "fi\n"
                "echo\n"
                "echo '--- [EXITO] Pre-comando completado. Iniciando comando principal... ---'\n"
                "echo\n"
                f"{self.command}\n"
            )
        return self.command

    def _build_captured_shell_args(self, shell_lower, cwd_dir=None):
        if shell_lower in ("pwsh", "powershell"):
            executable = self._shell_executable(shell_lower)
            script_path = self._write_temp_script(".ps1", self._build_powershell_script(cwd_dir), encoding="utf-8-sig")
            if shell_lower == "powershell":
                return [executable, "-NoLogo", "-ExecutionPolicy", "Bypass", "-File", script_path]
            return [executable, "-NoLogo", "-File", script_path]

        if shell_lower in ("cmd", "default"):
            script_path = self._write_temp_script(".cmd", self._build_cmd_script())
            return ["cmd.exe", "/d", "/s", "/c", script_path]

        if shell_lower == "bash":
            return ["bash.exe", "-c", self._build_bash_script()]

        return self.command

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

    def _log_execution_context(self, cwd_dir, shell_lower, captured=True):
        executable = self._shell_executable(shell_lower)
        resolved = shutil.which(executable) or executable
        mode = "terminal capturada interna" if captured else "consola nativa externa"
        self._add_log(
            f"--- Contexto de ejecucion ---\n"
            f"Modo: {mode}\n"
            f"Shell: {self._shell_display_name(shell_lower)}\n"
            f"Ejecutable: {resolved}\n"
            f"Directorio: {cwd_dir or 'Predeterminado'}\n\n"
        )

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

    def start(self):
        if self.status in ["running", "starting"]:
            return

        self._should_stop = False
        self.change_status("starting")
        self.exit_code = None
        
        # Clear logs on start
        with self.lock:
            self.logs.clear()
        
        if self.on_log_received:
            self.on_log_received(self.id, "--- Iniciando servicio ---\n")

        # Prepare environment
        run_env = os.environ.copy()
        if self.env:
            run_env.update(self.env)

        def run():
            temp_script_path = None
            try:
                cwd_dir = self.cwd if self.cwd and os.path.exists(self.cwd) else None
                creationflags = 0
                shell_lower = self.shell_type.lower()

                # 1. SI ES CONSOLA NATIVA EXTERNA (Chained in a single console window)
                if self.shell_native:
                    if sys.platform == "win32":
                        creationflags = subprocess.CREATE_NEW_CONSOLE
                    else:
                        creationflags = 0
                    
                    if self.pre_command:
                        if shell_lower == "cmd":
                            chained_cmd = f"{self.pre_command} && {self.command}"
                            cmd_args = ["cmd.exe", "/k", chained_cmd]
                        elif shell_lower == "pwsh":
                            chained_cmd = f"{self.pre_command}; if ($?) {{ {self.command} }}"
                            cmd_args = ["pwsh.exe", "-NoExit", "-Command", chained_cmd]
                        elif shell_lower == "powershell":
                            chained_cmd = f"{self.pre_command}; if ($?) {{ {self.command} }}"
                            cmd_args = ["powershell.exe", "-NoExit", "-Command", chained_cmd]
                        elif shell_lower == "bash":
                            chained_cmd = f"{self.pre_command} && {self.command}"
                            cmd_args = ["bash.exe", "-c", f"{chained_cmd}; exec bash"]
                        else:
                            chained_cmd = f"{self.pre_command} && {self.command}"
                            cmd_args = ["cmd.exe", "/k", chained_cmd]
                    else:
                        if shell_lower == "cmd":
                            cmd_args = ["cmd.exe", "/k", self.command]
                        elif shell_lower == "pwsh":
                            cmd_args = ["pwsh.exe", "-NoExit", "-Command", self.command]
                        elif shell_lower == "powershell":
                            cmd_args = ["powershell.exe", "-NoExit", "-Command", self.command]
                        elif shell_lower == "bash":
                            cmd_args = ["bash.exe", "-c", f"{self.command}; exec bash"]
                        else:
                            cmd_args = ["cmd.exe", "/k", self.command]
                    
                    use_shell = False

                    # Agregar log informativo si es consola nativa externa
                    shell_title = {
                        "cmd": "Command Prompt (CMD)",
                        "pwsh": "PowerShell 7 (pwsh)",
                        "powershell": "Windows PowerShell (powershell)",
                        "bash": "Git Bash (Bash)"
                    }.get(shell_lower, "Consola Nativa")
                    
                    msg = f"--- Ejecutando en consola nativa externa ({shell_title}) ---\n"
                    if self.pre_command:
                        msg += f"Pre-comando: {self.pre_command}\n"
                    msg += f"Comando principal: {self.command}\n"
                    msg += f"Directorio: {cwd_dir or 'Predeterminado'}\n\n"
                    msg += f"El proceso se está ejecutando en una ventana de consola externa independiente.\n"
                    msg += f"Usa esa ventana externa para ver los logs e interactuar.\n"
                    msg += f"Al detener el servicio desde aquí, la ventana se cerrará automáticamente.\n"
                    self._add_log(msg)

                    self.process = subprocess.Popen(
                        cmd_args,
                        shell=use_shell,
                        cwd=cwd_dir,
                        env=run_env,
                        stdout=None,
                        stderr=None,
                        creationflags=creationflags
                    )
                    self.start_time = time.time()
                    self.change_status("running")

                    exit_code = self.process.wait()
                    self.exit_code = exit_code

                # 2. SI ES CONSOLA INTERNA (CAPTURADA) (Run sequentially in background thread)
                else:
                    if sys.platform == "win32":
                        creationflags = subprocess.CREATE_NO_WINDOW
                    else:
                        creationflags = 0

                    if self._should_stop:
                        self.change_status("stopped")
                        return

                    cmd_args = self._build_captured_shell_args(shell_lower, cwd_dir)
                    use_shell = not isinstance(cmd_args, list)
                    if shell_lower in ("cmd", "default", "pwsh", "powershell") and isinstance(cmd_args, list):
                        temp_script_path = cmd_args[-1]
                    self._log_execution_context(cwd_dir, shell_lower, captured=True)

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
                self.start()

        self._restart_timer = threading.Thread(target=delayed_start, daemon=True)
        self._restart_timer.start()

    def stop(self):
        self._should_stop = True
        self.change_status("stopped")
        
        if self.process:
            pid = self.process.pid
            self._kill_process_tree(pid)
            self.process = None

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


class ServiceManager:
    def __init__(self, workspaces_config, on_state_change=None, on_log_received=None):
        self.on_state_change = on_state_change
        self.on_log_received = on_log_received
        
        # Mapeos principales
        self.workspaces = {}          # workspace_id -> nombre
        self.services = {}            # service_id -> ServiceProcess
        self.workspace_services = {}  # workspace_id -> lista de ServiceProcess
        
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

    def remove_workspace(self, workspace_id):
        # Detener y eliminar todos los servicios de ese workspace
        if workspace_id in self.workspace_services:
            for service in list(self.workspace_services[workspace_id]):
                self.remove_service(service.id)
            del self.workspace_services[workspace_id]
            
        if workspace_id in self.workspaces:
            del self.workspaces[workspace_id]

    def start_workspace(self, workspace_id):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.start()

    def stop_workspace(self, workspace_id):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.stop()

    def restart_workspace(self, workspace_id):
        if workspace_id in self.workspace_services:
            for service in self.workspace_services[workspace_id]:
                service.stop()
            time.sleep(0.5)
            for service in self.workspace_services[workspace_id]:
                service.start()

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
        return service

    def update_service(self, service_id, config):
        if service_id not in self.services:
            return None
        
        service = self.services[service_id]
        is_running = service.status in ["running", "starting"]
        if is_running:
            service.stop()

        service.name = config.get("name", service.name)
        service.command = config.get("command", service.command)
        service.pre_command = config.get("pre_command", service.pre_command)
        service.cwd = config.get("cwd", service.cwd)
        service.shell_type = config.get("shell", service.shell_type)
        service.shell_native = config.get("shell_native", service.shell_native)
        service.auto_restart = config.get("auto_restart", service.auto_restart)
        service.restart_delay = config.get("restart_delay", service.restart_delay)
        service.env = config.get("env", service.env)

        if is_running:
            service.start()
            
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
            return True
        return False

    def start_service(self, service_id):
        if service_id in self.services:
            self.services[service_id].start()

    def stop_service(self, service_id):
        if service_id in self.services:
            self.services[service_id].stop()

    def restart_service(self, service_id):
        if service_id in self.services:
            self.services[service_id].stop()
            time.sleep(0.5)
            self.services[service_id].start()

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
