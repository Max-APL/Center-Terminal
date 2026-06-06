import customtkinter as ctk
import queue
import math
import re
from ui.theme import *
from ui.components import ToolTip

# Regex para detectar secuencias de escape ANSI
ANSI_ESCAPE = re.compile(r'\x1b\[([0-9;]*)([a-zA-Z])')

# Mapeo de códigos de colores ANSI a hexadecimales modernos
ANSI_COLORS = {
    "30": "#1c1c1c", # Black
    "31": "#ef4444", # Red
    "32": "#22c55e", # Green
    "33": "#eab308", # Yellow
    "34": "#3b82f6", # Blue
    "35": "#a855f7", # Magenta
    "36": "#06b6d4", # Cyan
    "37": "#f4f4f5", # White
    "90": "#71717a", # Gray (Bright Black)
    "91": "#f87171", # Bright Red
    "92": "#4ade80", # Bright Green
    "93": "#facc15", # Bright Yellow
    "94": "#60a5fa", # Bright Blue
    "95": "#c084fc", # Bright Magenta
    "96": "#22d3ee", # Bright Cyan
    "97": "#ffffff"  # Bright White
}

class MiniTerminalPanel(ctk.CTkFrame):
    def __init__(self, parent, service, on_action=None, is_maximized=False):
        super().__init__(parent, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        
        self.service = service
        self.on_action = on_action
        self.is_maximized = is_maximized
        self.auto_scroll = True
        self.search_visible = False
        self.log_queue = queue.Queue()
        
        self.create_widgets()
        
        # Cargar logs iniciales
        existing_logs = service.get_logs()
        if existing_logs:
            self.insert_ansi_text(existing_logs)
        
        # Bucle de procesamiento de logs
        self.check_logs_loop()

    def create_widgets(self):
        # 1. Cabecera del Servicio
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=35)
        self.header.pack(fill="x", padx=10, pady=(8, 4))
        self.header.pack_propagate(False)

        # Info de Estado (Badge + Nombre)
        self.info_container = ctk.CTkFrame(self.header, fg_color="transparent")
        self.info_container.pack(side="left", fill="y")

        self.status_badge = ctk.CTkFrame(self.info_container, width=8, height=8, corner_radius=4, fg_color=COLOR_MUTED)
        self.status_badge.pack(side="left", padx=(2, 6), pady=13)
        self.status_badge.pack_propagate(False)

        self.lbl_name = ctk.CTkLabel(
            self.info_container, text=self.service.name, 
            font=ctk.CTkFont(size=12, weight="bold"), text_color="white"
        )
        self.lbl_name.pack(side="left")

        # Métricas (CPU/RAM)
        self.lbl_stats = ctk.CTkLabel(
            self.header, text="0.0% | 0 MB", 
            font=FONT_MUTED, text_color=COLOR_MUTED
        )
        self.lbl_stats.pack(side="left", padx=10, pady=4)

        # Botonera
        self.btn_container = ctk.CTkFrame(self.header, fg_color="transparent")
        self.btn_container.pack(side="right", fill="y")

        # Botón Iniciar/Detener Toggle
        self.btn_toggle = ctk.CTkButton(
            self.btn_container, text="▶", width=24, height=24,
            fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="white",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.toggle_state
        )
        self.btn_toggle.pack(side="left", padx=2)

        # Botón Reiniciar
        self.btn_restart = ctk.CTkButton(
            self.btn_container, text="↻", width=24, height=24,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            font=ctk.CTkFont(size=12),
            command=lambda: self.trigger_action("restart")
        )
        self.btn_restart.pack(side="left", padx=2)

        # Botón Auto-scroll
        self.btn_autoscroll = ctk.CTkButton(
            self.btn_container, text="↓", width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.toggle_autoscroll
        )
        self.btn_autoscroll.pack(side="left", padx=2)

        # Botón Copiar
        self.btn_copy = ctk.CTkButton(
            self.btn_container, text="📋", width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=self.copy_logs
        )
        self.btn_copy.pack(side="left", padx=2)


        # Botón Búsqueda
        self.btn_search = ctk.CTkButton(
            self.btn_container, text="🔍", width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=self.toggle_search_bar
        )
        self.btn_search.pack(side="left", padx=2)

        # Botón Limpiar Terminal
        self.btn_clear = ctk.CTkButton(
            self.btn_container, text="🗑", width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=self.clear_console
        )
        self.btn_clear.pack(side="left", padx=2)

        # Botón Editar
        self.btn_edit = ctk.CTkButton(
            self.btn_container, text="⚙", width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=lambda: self.trigger_action("edit")
        )
        self.btn_edit.pack(side="left", padx=2)

        # Botón Maximizar/Restaurar
        max_icon = "⧉" if self.is_maximized else "⛶"
        self.btn_maximize = ctk.CTkButton(
            self.btn_container, text=max_icon, width=24, height=24,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=lambda: self.trigger_action("maximize")
        )
        self.btn_maximize.pack(side="left", padx=2)

        # Botón Eliminar
        self.btn_delete = ctk.CTkButton(
            self.btn_container, text="✗", width=24, height=24,
            fg_color="transparent", hover_color=COLOR_DANGER, text_color=COLOR_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=lambda: self.trigger_action("delete")
        )
        self.btn_delete.pack(side="left", padx=2)
        # Cambiar color de hover de la cruz
        self.btn_delete.bind("<Enter>", lambda e: self.btn_delete.configure(text_color="white"))
        self.btn_delete.bind("<Leave>", lambda e: self.btn_delete.configure(text_color=COLOR_MUTED))

        # Inicializar Tooltips
        self.tip_toggle = ToolTip(self.btn_toggle, "Iniciar servicio")
        self.tip_restart = ToolTip(self.btn_restart, "Reiniciar servicio")
        self.tip_autoscroll = ToolTip(self.btn_autoscroll, "Auto-scroll: Activo")
        self.tip_copy = ToolTip(self.btn_copy, "Copiar logs al portapapeles")
        self.tip_search = ToolTip(self.btn_search, "Buscar en logs")
        self.tip_clear = ToolTip(self.btn_clear, "Limpiar terminal")
        self.tip_edit = ToolTip(self.btn_edit, "Editar configuración")
        self.tip_maximize = ToolTip(self.btn_maximize, "Restaurar rejilla" if self.is_maximized else "Maximizar terminal")
        self.tip_delete = ToolTip(self.btn_delete, "Eliminar servicio")

        # 2. Barra de Búsqueda (Oculta por defecto)
        self.search_frame = ctk.CTkFrame(self, fg_color="transparent", height=28)
        search_icon = ctk.CTkLabel(self.search_frame, text=" 🔍 ", font=FONT_BODY, text_color=COLOR_MUTED)
        search_icon.pack(side="left", padx=5)
        self.search_entry = ctk.CTkEntry(
            self.search_frame, placeholder_text="Buscar en logs...",
            height=24, fg_color=TERMINAL_BG, border_color=BORDER_COLOR,
            font=FONT_MUTED
        )
        self.search_entry.pack(side="left", fill="x", expand=True)
        self.search_entry.bind("<KeyRelease>", self.perform_search)
        
        btn_close_search = ctk.CTkButton(
            self.search_frame, text="✗", width=20, height=20,
            fg_color="transparent", text_color=COLOR_MUTED, hover_color=COLOR_DANGER,
            font=ctk.CTkFont(size=9, weight="bold"),
            command=self.toggle_search_bar
        )
        btn_close_search.pack(side="right", padx=5)

        # 3. Textbox de Consola
        self.console_text = ctk.CTkTextbox(
            self, fg_color=TERMINAL_BG, text_color=TERMINAL_FG,
            font=FONT_MONO, corner_radius=6, border_width=1, border_color=BORDER_COLOR,
            wrap="word"
        )
        self.console_text.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.console_text.configure(state="disabled")
        
        # Aplicar colores del intérprete (CMD, PowerShell, Bash)
        self.apply_shell_style()

    def toggle_state(self):
        if self.service.status in ["running", "starting"]:
            self.trigger_action("stop")
        else:
            self.trigger_action("start")

    def trigger_action(self, action):
        if self.on_action:
            self.on_action(self.service.id, action)

    def clear_console(self):
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")

    def append_log(self, text):
        self.log_queue.put(text)

    def insert_ansi_text(self, text):
        """Introduce texto en la consola analizando colores ANSI en tiempo real."""
        self.console_text.configure(state="normal")
        parts = ANSI_ESCAPE.split(text)
        current_tags = []
        
        i = 0
        while i < len(parts):
            part_text = parts[i]
            if part_text:
                self.console_text.insert("end", part_text, tuple(current_tags))
                
            if i + 1 < len(parts):
                code_str = parts[i+1]
                code_type = parts[i+2]
                
                if code_type == 'm':
                    codes = code_str.split(';')
                    for code in codes:
                        if code == '0' or not code:
                            current_tags = []
                        elif code in ANSI_COLORS:
                            tag_name = f"ansi_{code}"
                            self.console_text.tag_config(tag_name, foreground=ANSI_COLORS[code])
                            current_tags = [tag_name]
                i += 3
            else:
                i += 1

        # Control de memoria: limitar a las últimas 1000 líneas
        total_lines = int(float(self.console_text.index("end-1c")))
        if total_lines > 1000:
            self.console_text.delete("1.0", "200.0")
            
        if self.auto_scroll:
            self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def toggle_search_bar(self):
        self.search_visible = not self.search_visible
        if self.search_visible:
            self.search_frame.pack(fill="x", padx=10, pady=(0, 4), before=self.console_text)
            self.search_entry.focus_set()
            self.btn_search.configure(fg_color=COLOR_PRIMARY)
        else:
            self.search_frame.pack_forget()
            self.search_entry.delete(0, "end")
            self.console_text.tag_remove("search_highlight", "1.0", "end")
            self.btn_search.configure(fg_color="transparent")

    def perform_search(self, event=None):
        self.console_text.tag_remove("search_highlight", "1.0", "end")
        query = self.search_entry.get().strip()
        if not query:
            return
        
        start_pos = "1.0"
        while True:
            pos = self.console_text.search(query, start_pos, stopindex="end", nocase=True)
            if not pos:
                break
            end_pos = f"{pos}+{len(query)}c"
            self.console_text.tag_config("search_highlight", background="#facc15", foreground="#000000")
            self.console_text.tag_add("search_highlight", pos, end_pos)
            start_pos = end_pos

    def copy_logs(self):
        logs = self.console_text.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(logs)
        self.btn_copy.configure(text="✓")
        self.tip_copy.update_text("Copiado con éxito")
        self.restore_copy_button_id = self.after(1500, self.restore_copy_button)
        
    def restore_copy_button(self):
        self.btn_copy.configure(text="📋")
        self.tip_copy.update_text("Copiar logs al portapapeles")


    def toggle_autoscroll(self):
        self.auto_scroll = not self.auto_scroll
        if self.auto_scroll:
            self.btn_autoscroll.configure(text="↓", fg_color="transparent", text_color="white")
            self.tip_autoscroll.update_text("Auto-scroll: Activo")
            self.console_text.see("end")
        else:
            self.btn_autoscroll.configure(text="⏸", fg_color=BORDER_COLOR, text_color=COLOR_MUTED)
            self.tip_autoscroll.update_text("Auto-scroll: Congelado (Pausado)")

    def apply_shell_style(self):
        """Aplica la identidad visual del intérprete a la consola."""
        shell = self.service.shell_type.lower() if hasattr(self.service, "shell_type") else "default"
        if shell == "pwsh":
            self.console_text.configure(fg_color="#1f232a", text_color="#f1f1f1")
        elif shell == "powershell":
            self.console_text.configure(fg_color="#0c1b33", text_color="#f1f1f1")
        elif shell == "cmd":
            self.console_text.configure(fg_color="#0c0c0c", text_color="#cccccc")
        elif shell == "bash":
            self.console_text.configure(fg_color="#0c0f17", text_color="#4ade80")
        else: # default
            self.console_text.configure(fg_color=TERMINAL_BG, text_color=TERMINAL_FG)

    def check_logs_loop(self):
        if not self.winfo_exists():
            return
            
        has_new_logs = False
        while not self.log_queue.empty():
            try:
                text = self.log_queue.get_nowait()
                self.insert_ansi_text(text)
                has_new_logs = True
            except queue.Empty:
                break

        if self.winfo_exists():
            self.check_logs_loop_id = self.after(100, self.check_logs_loop)

    def update_status_ui(self):
        status = self.service.status
        
        # Actualizar colores de botón play/stop e indicador
        if status == "running":
            self.status_badge.configure(fg_color=COLOR_SUCCESS)
            self.btn_toggle.configure(text="■", fg_color=COLOR_DANGER, hover_color="#dc2626")
            self.btn_restart.configure(state="normal")
            self.tip_toggle.update_text("Detener servicio")
        elif status == "starting":
            self.status_badge.configure(fg_color=COLOR_WARNING)
            self.btn_toggle.configure(text="■", fg_color=COLOR_DANGER, hover_color="#dc2626")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Detener servicio")
        elif status == "error":
            self.status_badge.configure(fg_color=COLOR_DANGER)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Iniciar servicio")
        else: # stopped
            self.status_badge.configure(fg_color=COLOR_MUTED)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Iniciar servicio")

        # Métricas de consumo
        if status == "running":
            cpu_val = self.service.cpu_usage
            mem_mb = self.service.mem_usage / (1024 * 1024)
            mem_str = f"{mem_mb:.0f}MB" if mem_mb < 1024 else f"{mem_mb/1024:.1f}GB"
            self.lbl_stats.configure(text=f"{cpu_val:.1f}% | {mem_str}", text_color="white")
        else:
            self.lbl_stats.configure(text="Offline", text_color=COLOR_MUTED)

    def destroy(self):
        if hasattr(self, "check_logs_loop_id") and self.check_logs_loop_id:
            try:
                self.after_cancel(self.check_logs_loop_id)
            except:
                pass
        if hasattr(self, "restore_copy_button_id") and self.restore_copy_button_id:
            try:
                self.after_cancel(self.restore_copy_button_id)
            except:
                pass
        super().destroy()


class WorkspaceView(ctk.CTkFrame):
    def __init__(self, parent, manager, on_action=None, on_delete_workspace=None, on_add_service=None):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        
        self.manager = manager
        self.workspace_id = None
        self.on_action = on_action
        self.on_delete_workspace = on_delete_workspace
        self.on_add_service = on_add_service
        self.maximized_service_id = None
        
        self.panels = {}  # service_id -> MiniTerminalPanel
        self.grid_container = None
        
        self.create_widgets()

    def create_widgets(self):
        # 1. Cabecera del Workspace (Herramientas y Estadísticas)
        self.header_frame = ctk.CTkFrame(self, fg_color=BG_CARD, height=75, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        self.header_frame.pack_propagate(False)

        # Izquierda: Info de Nombre y Recursos
        self.info_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.info_frame.pack(side="left", fill="both", padx=15, pady=8)
        
        self.lbl_ws_name = ctk.CTkLabel(self.info_frame, text="Espacio de Trabajo", font=FONT_TITLE, text_color="white")
        self.lbl_ws_name.pack(anchor="w")
        
        self.lbl_ws_stats = ctk.CTkLabel(self.info_frame, text="0 Servicios  |  CPU: 0.0%  |  Mem: 0 MB", font=FONT_MUTED, text_color=COLOR_MUTED)
        self.lbl_ws_stats.pack(anchor="w", pady=(1, 0))

        # Derecha: Botones de Gestión Colectiva
        self.actions_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.actions_frame.pack(side="right", fill="y", padx=15, pady=12)

        # Iniciar Todo
        self.btn_start_all = ctk.CTkButton(
            self.actions_frame, text="Iniciar Todo", width=95, height=32,
            fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.start_all_services
        )
        self.btn_start_all.pack(side="left", padx=3)

        # Detener Todo
        self.btn_stop_all = ctk.CTkButton(
            self.actions_frame, text="Detener Todo", width=95, height=32,
            fg_color=COLOR_DANGER, hover_color="#dc2626", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.stop_all_services
        )
        self.btn_stop_all.pack(side="left", padx=3)

        # Añadir Servicio
        self.btn_add_service = ctk.CTkButton(
            self.actions_frame, text="+ Añadir Servicio", width=120, height=32,
            fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.add_service_click
        )
        self.btn_add_service.pack(side="left", padx=3)

        # Eliminar Workspace
        self.btn_delete_ws = ctk.CTkButton(
            self.actions_frame, text="Eliminar Espacio", width=110, height=32,
            fg_color="transparent", border_width=1, border_color=COLOR_DANGER,
            text_color=COLOR_DANGER, hover_color="#fef2f2",
            font=ctk.CTkFont(size=12),
            command=self.delete_workspace_click
        )
        self.btn_delete_ws.pack(side="left", padx=3)
        self.btn_delete_ws.bind("<Enter>", lambda e: self.btn_delete_ws.configure(text_color=COLOR_DANGER, fg_color="#450a0a"))
        self.btn_delete_ws.bind("<Leave>", lambda e: self.btn_delete_ws.configure(text_color=COLOR_DANGER, fg_color="transparent"))

        # Inicializar Tooltips de Workspace
        self.tip_start_all = ToolTip(self.btn_start_all, "Iniciar todos los servicios del espacio")
        self.tip_stop_all = ToolTip(self.btn_stop_all, "Detener todos los servicios del espacio")
        self.tip_add_service = ToolTip(self.btn_add_service, "Añadir nuevo servicio a este espacio")
        self.tip_delete_ws = ToolTip(self.btn_delete_ws, "Eliminar este espacio de trabajo por completo")

        # 2. Contenedor de la Rejilla de Terminales
        # Se instanciará dinámicamente como normal Frame o Scrollable Frame según el número de servicios
        self.main_area = ctk.CTkFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def set_workspace(self, workspace_id):
        self.workspace_id = workspace_id
        self.maximized_service_id = None # Resetear maximizado al cambiar de espacio
        ws_name = self.manager.workspaces.get(workspace_id, "Espacio de Trabajo")
        self.lbl_ws_name.configure(text=ws_name)
        
        self.rebuild_grid()
        self.update_stats()

    def handle_panel_action(self, service_id, action):
        if action == "maximize":
            self.toggle_maximize(service_id)
        else:
            if self.on_action:
                self.on_action(service_id, action)

    def toggle_maximize(self, service_id):
        if self.maximized_service_id == service_id:
            self.maximized_service_id = None
        else:
            self.maximized_service_id = service_id
        self.rebuild_grid()

    def rebuild_grid(self):
        """Reconstruye el grid de terminales en pantalla basado en los servicios del workspace."""
        if not self.workspace_id:
            return

        # Limpiar paneles anteriores
        if self.grid_container:
            if hasattr(self.grid_container, "_parent_frame"):
                self.grid_container._parent_frame.destroy()
            else:
                self.grid_container.destroy()
            self.grid_container = None
        self.panels.clear()

        services = self.manager.workspace_services.get(self.workspace_id, [])

        # Caso 0: No hay servicios
        if not services:
            self.grid_container = ctk.CTkFrame(self.main_area, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
            self.grid_container.pack(fill="both", expand=True)
            
            placeholder_lbl = ctk.CTkLabel(
                self.grid_container, 
                text="Este espacio de trabajo está vacío.\n\nHaz clic en '+ Añadir Servicio' arriba para configurar tu primera ejecución.", 
                font=FONT_SUBTITLE, text_color=COLOR_MUTED
            )
            placeholder_lbl.pack(expand=True)
            
            self.btn_start_all.configure(state="disabled")
            self.btn_stop_all.configure(state="disabled")
            self.maximized_service_id = None # Resetear si se vacía
            return

        self.btn_start_all.configure(state="normal")
        self.btn_stop_all.configure(state="normal")

        # Caso Maximizado: Si hay un servicio maximizado y pertenece al workspace activo
        if self.maximized_service_id:
            maximized_service = next((s for s in services if s.id == self.maximized_service_id), None)
            if maximized_service:
                self.grid_container = ctk.CTkFrame(self.main_area, fg_color="transparent")
                self.grid_container.pack(fill="both", expand=True)
                
                panel = MiniTerminalPanel(self.grid_container, maximized_service, on_action=self.handle_panel_action, is_maximized=True)
                panel.pack(fill="both", expand=True)
                self.panels[maximized_service.id] = panel
                return
            else:
                self.maximized_service_id = None # Si ya no existe, restablecer

        # Decidir estructura del contenedor
        num_services = len(services)
        
        if num_services == 1:
            # 1 Servicio: Se expande por completo en un contenedor estático para máxima visibilidad
            self.grid_container = ctk.CTkFrame(self.main_area, fg_color="transparent")
            self.grid_container.pack(fill="both", expand=True)
            
            panel = MiniTerminalPanel(self.grid_container, services[0], on_action=self.handle_panel_action)
            panel.pack(fill="both", expand=True)
            self.panels[services[0].id] = panel
            
        elif num_services <= 4:
            # 2 a 4 Servicios: Contenedor estático que distribuye el espacio disponible
            self.grid_container = ctk.CTkFrame(self.main_area, fg_color="transparent")
            self.grid_container.pack(fill="both", expand=True)

            cols = 2
            rows = math.ceil(num_services / cols)
            
            for col in range(cols):
                self.grid_container.grid_columnconfigure(col, weight=1, uniform="equal")

            for idx, service in enumerate(services):
                r = idx // cols
                c = idx % cols
                is_last_odd = (idx == num_services - 1) and (num_services % 2 != 0)
                
                panel = MiniTerminalPanel(self.grid_container, service, on_action=self.handle_panel_action)
                if is_last_odd:
                    panel.grid(row=r, column=0, columnspan=2, padx=4, pady=4, sticky="nsew")
                else:
                    panel.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
                
                # Expandir las filas al 100% del contenedor visible
                self.grid_container.grid_rowconfigure(r, weight=1)
                self.panels[service.id] = panel
                
        else:
            # Más de 4 Servicios: Rejilla dentro de un Scrollable Frame
            self.grid_container = ctk.CTkScrollableFrame(self.main_area, fg_color="transparent")
            self.grid_container.pack(fill="both", expand=True)

            cols = 2
            rows = math.ceil(num_services / cols)
            
            for col in range(cols):
                self.grid_container.grid_columnconfigure(col, weight=1, uniform="equal")

            for idx, service in enumerate(services):
                r = idx // cols
                c = idx % cols
                
                is_last_odd = (idx == num_services - 1) and (num_services % 2 != 0)
                
                panel = MiniTerminalPanel(self.grid_container, service, on_action=self.handle_panel_action)
                
                if is_last_odd:
                    panel.grid(row=r, column=0, columnspan=2, padx=4, pady=4, sticky="nsew")
                else:
                    panel.grid(row=r, column=c, padx=4, pady=4, sticky="nsew")
                
                # Ajustar el alto fijo en el scroll
                self.grid_container.grid_rowconfigure(r, minsize=290)
                
                self.panels[service.id] = panel

    def update_stats(self):
        """Actualiza el estado de las métricas agregadas del workspace y sus terminales."""
        if not self.workspace_id:
            return

        # 1. Cabecera agregada
        stats = self.manager.get_workspace_stats(self.workspace_id)
        mem_mb = stats["total_mem"] / (1024 * 1024)
        mem_str = f"{mem_mb:.1f} MB" if mem_mb < 1024 else f"{mem_mb/1024:.2f} GB"
        
        self.lbl_ws_stats.configure(
            text=f"{stats['total_count']} Servicios ({stats['running_count']} activos)  |  CPU: {stats['total_cpu']:.1f}%  |  Mem: {mem_str}"
        )

        # 2. Actualizar paneles individuales
        for panel in self.panels.values():
            panel.update_status_ui()

    def append_log_to_service(self, service_id, text):
        """Redirige logs entrantes a la mini-terminal correcta si está en pantalla."""
        panel = self.panels.get(service_id)
        if panel:
            panel.append_log(text)

    def start_all_services(self):
        self.manager.start_workspace(self.workspace_id)
        self.update_stats()

    def stop_all_services(self):
        self.manager.stop_workspace(self.workspace_id)
        self.update_stats()

    def add_service_click(self):
        if self.on_add_service and self.workspace_id:
            self.on_add_service(self.workspace_id)

    def delete_workspace_click(self):
        if self.on_delete_workspace and self.workspace_id:
            self.on_delete_workspace(self.workspace_id)
