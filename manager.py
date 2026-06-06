import subprocess
import os
import sys
import time
import threading
import collections
import psutil
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

                    # A. Ejecutar Pre-comando si existe
                    if self.pre_command:
                        self._add_log(f"--- [Paso 1/2] Ejecutando pre-comando: {self.pre_command} ---\n")
                        
                        if shell_lower == "cmd":
                            pre_args = ["cmd.exe", "/c", self.pre_command]
                            pre_use_shell = False
                        elif shell_lower == "pwsh":
                            pre_args = ["pwsh.exe", "-Command", self.pre_command]
                            pre_use_shell = False
                        elif shell_lower == "powershell":
                            pre_args = ["powershell.exe", "-Command", self.pre_command]
                            pre_use_shell = False
                        elif shell_lower == "bash":
                            pre_args = ["bash.exe", "-c", self.pre_command]
                            pre_use_shell = False
                        else:
                            pre_args = self.pre_command
                            pre_use_shell = True

                        pre_proc = subprocess.Popen(
                            pre_args,
                            shell=pre_use_shell,
                            cwd=cwd_dir,
                            env=run_env,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            creationflags=creationflags
                        )
                        self.process = pre_proc  # Registrar para permitir detener si el usuario cancela

                        for line in iter(pre_proc.stdout.readline, b''):
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

                        pre_proc.stdout.close()
                        pre_exit = pre_proc.wait()

                        if self._should_stop:
                            self.change_status("stopped")
                            self._add_log("\n--- Detenido por el usuario durante el pre-inicio ---\n")
                            return

                        if pre_exit != 0:
                            self.exit_code = pre_exit
                            self.change_status("error")
                            self._add_log(f"\n--- [FALLO] El pre-comando terminó con error (Código: {pre_exit}) ---\n")
                            return

                        self._add_log("\n--- [ÉXITO] Pre-comando completado. Iniciando comando principal... ---\n\n")

                    # B. Ejecutar Comando Principal
                    if shell_lower == "cmd":
                        cmd_args = ["cmd.exe", "/c", self.command]
                        use_shell = False
                    elif shell_lower == "pwsh":
                        cmd_args = ["pwsh.exe", "-Command", self.command]
                        use_shell = False
                    elif shell_lower == "powershell":
                        cmd_args = ["powershell.exe", "-Command", self.command]
                        use_shell = False
                    elif shell_lower == "bash":
                        cmd_args = ["bash.exe", "-c", self.command]
                        use_shell = False
                    else:
                        cmd_args = self.command
                        use_shell = True

                    if self._should_stop:
                        self.change_status("stopped")
                        return

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

                    self._read_thread = threading.Thread(target=self._read_stdout, daemon=True)
                    self._read_thread.start()

                    exit_code = self.process.wait()
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
            base_dir = os.path.dirname(os.path.abspath(__file__))
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
