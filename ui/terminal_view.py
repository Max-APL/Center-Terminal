import customtkinter as ctk
import queue
from ui.theme import *
from ui.components import ToolTip

class TerminalView(ctk.CTkFrame):
    def __init__(self, parent, on_action=None):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        
        self.service = None
        self.on_action = on_action
        self.auto_scroll = True
        self.search_visible = False
        
        # Cola de logs para comunicación entre hilos de forma segura
        self.log_queue = queue.Queue()
        
        self.create_widgets()
        
        # Bucle periódico en la UI para procesar nuevos logs sin colgar el hilo principal
        self.check_logs_loop()

    def create_widgets(self):
        # 1. Cabecera (Header)
        self.header_frame = ctk.CTkFrame(self, fg_color=BG_CARD, height=90, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        self.header_frame.pack_propagate(False)

        # Info del Servicio (Izquierda)
        self.info_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.info_frame.pack(side="left", fill="both", padx=15, pady=10)

        # Nombre del servicio + Badge de estado
        self.title_container = ctk.CTkFrame(self.info_frame, fg_color="transparent")
        self.title_container.pack(anchor="w")

        self.lbl_title = ctk.CTkLabel(
            self.title_container, text="Selecciona un servicio", 
            font=FONT_TITLE, text_color="white"
        )
        self.lbl_title.pack(side="left")

        self.status_badge = ctk.CTkFrame(self.title_container, width=12, height=12, corner_radius=6, fg_color=COLOR_MUTED)
        self.status_badge.pack(side="left", padx=(10, 0), pady=8)
        self.status_badge.pack_propagate(False)

        # Estadísticas en tiempo real (Uptime, PID, CPU, Memoria)
        self.stats_label = ctk.CTkLabel(
            self.info_frame, text="PID: N/A  |  Uptime: N/A  |  CPU: 0.0%  |  Mem: 0 MB",
            font=FONT_MUTED, text_color=COLOR_MUTED
        )
        self.stats_label.pack(anchor="w", pady=(2, 0))

        # Botonera de Acciones (Derecha)
        self.actions_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.actions_frame.pack(side="right", fill="y", padx=15, pady=15)

        # Iniciar (Play)
        self.btn_start = ctk.CTkButton(
            self.actions_frame, text="Iniciar", width=70, height=32,
            fg_color=COLOR_SUCCESS, hover_color="#059669", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.trigger_action("start")
        )
        self.btn_start.pack(side="left", padx=3)

        # Detener (Stop)
        self.btn_stop = ctk.CTkButton(
            self.actions_frame, text="Detener", width=70, height=32,
            fg_color=COLOR_DANGER, hover_color="#dc2626", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=lambda: self.trigger_action("stop")
        )
        self.btn_stop.pack(side="left", padx=3)

        # Reiniciar (Restart)
        self.btn_restart = ctk.CTkButton(
            self.actions_frame, text="Reiniciar", width=80, height=32,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            font=ctk.CTkFont(size=12),
            command=lambda: self.trigger_action("restart")
        )
        self.btn_restart.pack(side="left", padx=3)

        # Auto-scroll Toggle
        self.btn_autoscroll = ctk.CTkButton(
            self.actions_frame, text="↓ Scroll", width=75, height=32,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.toggle_autoscroll
        )
        self.btn_autoscroll.pack(side="left", padx=3)
        self.tip_autoscroll = ToolTip(self.btn_autoscroll, "Auto-scroll: Activo")

        # Copiar Logs
        self.btn_copy = ctk.CTkButton(
            self.actions_frame, text="📋 Copiar", width=80, height=32,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.copy_logs
        )
        self.btn_copy.pack(side="left", padx=3)
        self.tip_copy = ToolTip(self.btn_copy, "Copiar logs al portapapeles")


        # Buscar Logs
        self.btn_search = ctk.CTkButton(
            self.actions_frame, text="🔍 Buscar", width=80, height=32,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.toggle_search_bar
        )
        self.btn_search.pack(side="left", padx=3)
        self.tip_search = ToolTip(self.btn_search, "Buscar en logs")

        # Limpiar Terminal
        self.btn_clear = ctk.CTkButton(
            self.actions_frame, text="Limpiar", width=70, height=32,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            command=self.clear_terminal
        )
        self.btn_clear.pack(side="left", padx=3)

        # Ajustes (Config)
        self.btn_edit = ctk.CTkButton(
            self.actions_frame, text="Editar", width=70, height=32,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=12),
            command=lambda: self.trigger_action("edit")
        )
        self.btn_edit.pack(side="left", padx=3)

        # 2. Barra de Búsqueda (Oculta por defecto)
        self.search_frame = ctk.CTkFrame(self, fg_color="transparent", height=35)
        search_icon = ctk.CTkLabel(self.search_frame, text="  🔍  ", font=FONT_TITLE, text_color=COLOR_MUTED)
        search_icon.pack(side="left", padx=5)
        self.search_entry = ctk.CTkEntry(
            self.search_frame, placeholder_text="Buscar en logs...",
            height=30, fg_color=TERMINAL_BG, border_color=BORDER_COLOR,
            font=FONT_BODY
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.search_entry.bind("<KeyRelease>", self.perform_search)
        
        btn_close_search = ctk.CTkButton(
            self.search_frame, text="✗", width=24, height=24,
            fg_color="transparent", text_color=COLOR_MUTED, hover_color=COLOR_DANGER,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.toggle_search_bar
        )
        btn_close_search.pack(side="right", padx=15)

        # 3. Consola de Logs (Terminal)
        self.console_container = ctk.CTkFrame(self, fg_color=TERMINAL_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.console_container.pack(fill="both", expand=True, padx=15, pady=(0, 15))

        self.console_text = ctk.CTkTextbox(
            self.console_container, 
            fg_color=TERMINAL_BG, 
            text_color=TERMINAL_FG,
            font=FONT_MONO,
            corner_radius=12,
            wrap="word",
            border_width=0
        )
        self.console_text.pack(fill="both", expand=True, padx=8, pady=8)
        
        # Deshabilitar edición directa por el usuario
        self.console_text.configure(state="disabled")

    def set_service(self, service):
        """Asocia el panel a un servicio específico y carga sus datos."""
        self.service = service
        if not service:
            self.lbl_title.configure(text="Selecciona un servicio")
            self.stats_label.configure(text="PID: N/A  |  Uptime: N/A  |  CPU: 0.0%  |  Mem: 0 MB")
            self.status_badge.configure(fg_color=COLOR_MUTED)
            self.console_text.configure(state="normal")
            self.console_text.delete("1.0", "end")
            self.console_text.configure(state="disabled")
            self.disable_buttons()
            return

        self.lbl_title.configure(text=service.name)
        self.enable_buttons()
        self.update_status_ui()
        
        # Vaciar y repoblar la terminal con los logs existentes
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        
        existing_logs = service.get_logs()
        if existing_logs:
            self.console_text.insert("end", existing_logs)
            self.console_text.see("end")
            
        self.console_text.configure(state="disabled")
        
        # Vaciar cualquier log residual en cola
        while not self.log_queue.empty():
            try:
                self.log_queue.get_nowait()
            except queue.Empty:
                break

    def append_log(self, text):
        """Método seguro para hilos para programar logs en la UI."""
        self.log_queue.put(text)

    def check_logs_loop(self):
        """Lee logs de la cola y los introduce en el CTkTextbox (corre en el hilo principal)."""
        if not self.winfo_exists():
            return
            
        has_new_logs = False
        
        self.console_text.configure(state="normal")
        while not self.log_queue.empty():
            try:
                text = self.log_queue.get_nowait()
                self.console_text.insert("end", text)
                has_new_logs = True
            except queue.Empty:
                break
        
        if has_new_logs:
            # Mantener terminal auto-scrolleado al fondo
            if self.auto_scroll:
                self.console_text.see("end")
            
        self.console_text.configure(state="disabled")
        
        # Volver a programar
        if self.winfo_exists():
            self.check_logs_loop_id = self.after(50, self.check_logs_loop)

    def toggle_search_bar(self):
        self.search_visible = not self.search_visible
        if self.search_visible:
            self.search_frame.pack(fill="x", padx=15, pady=(0, 10), before=self.console_container)
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
        self.btn_copy.configure(text="✓ Copiado")
        self.tip_copy.update_text("Copiado con éxito")
        self.restore_copy_button_id = self.after(1500, self.restore_copy_button)
        
    def restore_copy_button(self):
        self.btn_copy.configure(text="📋 Copiar")
        self.tip_copy.update_text("Copiar logs al portapapeles")

    def toggle_autoscroll(self):
        self.auto_scroll = not self.auto_scroll
        if self.auto_scroll:
            self.btn_autoscroll.configure(text="↓ Scroll", fg_color="transparent", text_color="white")
            self.tip_autoscroll.update_text("Auto-scroll: Activo")
            self.console_text.see("end")
        else:
            self.btn_autoscroll.configure(text="⏸ Scroll", fg_color=BORDER_COLOR, text_color=COLOR_MUTED)
            self.tip_autoscroll.update_text("Auto-scroll: Congelado (Pausado)")

    def update_status_ui(self):
        """Actualiza el estado de la UI (botones activos, badges) y recursos."""
        if not self.service:
            return

        # Badge y colores según el estado
        status = self.service.status
        if status == "running":
            self.status_badge.configure(fg_color=COLOR_SUCCESS)
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_restart.configure(state="normal")
        elif status == "starting":
            self.status_badge.configure(fg_color=COLOR_WARNING)
            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.btn_restart.configure(state="disabled")
        elif status == "error":
            self.status_badge.configure(fg_color=COLOR_DANGER)
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_restart.configure(state="disabled")
        else: # stopped
            self.status_badge.configure(fg_color=COLOR_MUTED)
            self.btn_start.configure(state="normal")
            self.btn_stop.configure(state="disabled")
            self.btn_restart.configure(state="disabled")

        # Texto de estadísticas de recursos
        pid = self.service.process.pid if (self.service.process and self.service.status == "running") else "N/A"
        uptime = self.service.get_uptime()
        
        # Formatear memoria
        mem_mb = self.service.mem_usage / (1024 * 1024)
        mem_str = f"{mem_mb:.1f} MB" if mem_mb < 1024 else f"{mem_mb/1024:.2f} GB"
        
        # Formatear CPU
        cpu_str = f"{self.service.cpu_usage:.1f}%"
        
        self.stats_label.configure(
            text=f"PID: {pid}  |  Uptime: {uptime}  |  CPU: {cpu_str}  |  Mem: {mem_str}",
            text_color="white" if status == "running" else COLOR_MUTED
        )

    def clear_terminal(self):
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")

    def trigger_action(self, action_name):
        if self.service and self.on_action:
            self.on_action(self.service.id, action_name)

    def disable_buttons(self):
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="disabled")
        self.btn_restart.configure(state="disabled")
        self.btn_clear.configure(state="disabled")
        self.btn_edit.configure(state="disabled")

    def enable_buttons(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="normal")
        self.btn_restart.configure(state="normal")
        self.btn_clear.configure(state="normal")
        self.btn_edit.configure(state="normal")

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
