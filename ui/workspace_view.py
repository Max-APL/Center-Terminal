import customtkinter as ctk
import queue
import math
import re
import ctypes
from tkinter import messagebox
from ui.theme import *
from ui.components import ToolTip
from ui.workspace_startup_dialog import WorkspaceStartupDialog
from workspace_startups import DEFAULT_STARTUP_ID
from ui.quick_view import (
    GWL_STYLE,
    WS_BORDER,
    WS_CAPTION,
    WS_CHILD,
    WS_CLIPCHILDREN,
    WS_MAXIMIZEBOX,
    WS_MINIMIZEBOX,
    WS_POPUP,
    WS_THICKFRAME,
    kernel32,
    user32,
)
from shell_profiles import get_shell_profile

WS_DISABLED = 0x08000000
user32.EnableWindow.argtypes = [ctypes.c_void_p, ctypes.c_bool]
user32.EnableWindow.restype = ctypes.c_bool

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
        self.scroll_idle_id = None
        self.scroll_after_id = None
        
        self.create_widgets()
        
        # Cargar los logs iniciales en los mismos bloques en que llegaron en vivo.
        # Asi el render de ANSI no cambia al salir y volver al workspace.
        if hasattr(service, "get_log_entries"):
            existing_entries = service.get_log_entries()
        else:
            existing_logs = service.get_logs()
            existing_entries = [existing_logs] if existing_logs else []
        if existing_entries:
            for entry in existing_entries:
                self.insert_ansi_text(entry)
            self.schedule_scroll_to_end()
        
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

        profile_options = self.service.get_deploy_profile_options() if hasattr(self.service, "get_deploy_profile_options") else []
        profile_labels = [label for label, _ in profile_options] or ["Predeterminado"]
        selected_profile = self.service.get_selected_deploy_profile_label() if hasattr(self.service, "get_selected_deploy_profile_label") else profile_labels[0]
        if selected_profile not in profile_labels:
            selected_profile = profile_labels[0]

        self.profile_var = ctk.StringVar(value=selected_profile)
        self.profile_menu = ctk.CTkOptionMenu(
            self.header,
            values=profile_labels,
            variable=self.profile_var,
            width=150,
            height=24,
            fg_color=BG_MAIN,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white",
            font=ctk.CTkFont(size=11),
            command=self.change_deploy_profile,
        )
        self.profile_menu.pack(side="left", padx=(0, 8), pady=4)

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
        self.tip_profile = ToolTip(self.profile_menu, "Flujo de deploy")
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
        self.console_text.bind("<Map>", lambda event: self.schedule_scroll_to_end())
        self.console_text.bind("<Configure>", lambda event: self.schedule_scroll_to_end())
        
        # Aplicar colores del intérprete detectado
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

    def change_deploy_profile(self, profile_label):
        if self.service.status in ["running", "starting"]:
            return
        if hasattr(self.service, "get_profile_id_from_label"):
            profile_id = self.service.get_profile_id_from_label(profile_label)
            if profile_id and self.service.select_deploy_profile(profile_id):
                self.apply_shell_style()

    def schedule_scroll_to_end(self):
        if not self.auto_scroll:
            return
        try:
            if self.scroll_idle_id:
                self.after_cancel(self.scroll_idle_id)
            if self.scroll_after_id:
                self.after_cancel(self.scroll_after_id)
            self.scroll_idle_id = self.after_idle(lambda: self.run_scheduled_scroll("scroll_idle_id"))
            self.scroll_after_id = self.after(120, lambda: self.run_scheduled_scroll("scroll_after_id"))
        except:
            pass

    def run_scheduled_scroll(self, attr_name):
        setattr(self, attr_name, None)
        self.scroll_to_end()

    def scroll_to_end(self):
        if not self.winfo_exists():
            return
        try:
            self.console_text.update_idletasks()
            self.console_text.see("end-1c")
            self.console_text.yview_moveto(1.0)
            native_textbox = getattr(self.console_text, "_textbox", None)
            if native_textbox:
                native_textbox.see("end-1c")
                native_textbox.yview_moveto(1.0)
        except:
            pass

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
            self.schedule_scroll_to_end()
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
        shell_type = self.service.get_selected_shell_type() if hasattr(self.service, "get_selected_shell_type") else getattr(self.service, "shell_type", None)
        profile = get_shell_profile(shell_type)
        executable = profile.executable.lower()
        if executable.endswith("powershell.exe"):
            self.console_text.configure(fg_color="#0c1b33", text_color="#f1f1f1")
        elif executable.endswith("pwsh.exe"):
            self.console_text.configure(fg_color="#0c0c0c", text_color="#f1f1f1")
        elif profile.kind == "cmd":
            self.console_text.configure(fg_color="#0c0c0c", text_color="#cccccc")
        elif profile.kind in ("posix", "wsl", "fish"):
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
            self.profile_menu.configure(state="disabled")
            self.tip_toggle.update_text("Detener servicio")
        elif status == "starting":
            self.status_badge.configure(fg_color=COLOR_WARNING)
            self.btn_toggle.configure(text="■", fg_color=COLOR_DANGER, hover_color="#dc2626")
            self.btn_restart.configure(state="disabled")
            self.profile_menu.configure(state="disabled")
            self.tip_toggle.update_text("Detener servicio")
        elif status == "error":
            self.status_badge.configure(fg_color=COLOR_DANGER)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.profile_menu.configure(state="normal")
            self.tip_toggle.update_text("Iniciar servicio")
        else: # stopped
            self.status_badge.configure(fg_color=COLOR_MUTED)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.profile_menu.configure(state="normal")
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
        for attr in ("scroll_idle_id", "scroll_after_id"):
            after_id = getattr(self, attr, None)
            if after_id:
                try:
                    self.after_cancel(after_id)
                except:
                    pass
        super().destroy()


class NativeServiceTerminalPanel(ctk.CTkFrame):
    def __init__(self, parent, service, on_action=None, is_maximized=False):
        super().__init__(parent, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)

        self.service = service
        self.on_action = on_action
        self.is_maximized = is_maximized
        self.child_hwnd = getattr(service, "console_hwnd", None)
        self.embed_after_id = None
        self.resize_after_id = None
        self.embed_attempts = 0

        self.create_widgets()
        self.bind("<Map>", self.on_map)

        if self.service.status in ("running", "starting"):
            self.schedule_embed()

    def create_widgets(self):
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=35)
        self.header.pack(fill="x", padx=10, pady=(8, 4))
        self.header.pack_propagate(False)

        self.info_container = ctk.CTkFrame(self.header, fg_color="transparent")
        self.info_container.pack(side="left", fill="y")

        self.status_badge = ctk.CTkFrame(self.info_container, width=8, height=8, corner_radius=4, fg_color=COLOR_MUTED)
        self.status_badge.pack(side="left", padx=(2, 6), pady=13)
        self.status_badge.pack_propagate(False)

        self.lbl_name = ctk.CTkLabel(
            self.info_container,
            text=self.service.name,
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="white",
        )
        self.lbl_name.pack(side="left")

        self.lbl_stats = ctk.CTkLabel(
            self.header,
            text="Offline",
            font=FONT_MUTED,
            text_color=COLOR_MUTED,
        )
        self.lbl_stats.pack(side="left", padx=10, pady=4)

        self.btn_container = ctk.CTkFrame(self.header, fg_color="transparent")
        self.btn_container.pack(side="right", fill="y")

        self.btn_toggle = ctk.CTkButton(
            self.btn_container,
            text="▶",
            width=24,
            height=24,
            fg_color=COLOR_SUCCESS,
            hover_color="#059669",
            text_color="white",
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.toggle_state,
        )
        self.btn_toggle.pack(side="left", padx=2)

        self.btn_restart = ctk.CTkButton(
            self.btn_container,
            text="↻",
            width=24,
            height=24,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=12),
            command=self.restart_terminal,
        )
        self.btn_restart.pack(side="left", padx=2)

        self.btn_copy = ctk.CTkButton(
            self.btn_container,
            text="📋",
            width=24,
            height=24,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color="white",
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=self.copy_logs,
        )
        self.btn_copy.pack(side="left", padx=2)

        self.btn_audit = ctk.CTkButton(
            self.btn_container,
            text="📜",
            width=24,
            height=24,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color="white",
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=lambda: self.trigger_action("audit"),
        )
        self.btn_audit.pack(side="left", padx=2)

        self.btn_edit = ctk.CTkButton(
            self.btn_container,
            text="⚙",
            width=24,
            height=24,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color="white",
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=lambda: self.trigger_action("edit"),
        )
        self.btn_edit.pack(side="left", padx=2)

        max_icon = "⧉" if self.is_maximized else "⛶"
        self.btn_maximize = ctk.CTkButton(
            self.btn_container,
            text=max_icon,
            width=24,
            height=24,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color="white",
            hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=lambda: self.trigger_action("maximize"),
        )
        self.btn_maximize.pack(side="left", padx=2)

        self.btn_delete = ctk.CTkButton(
            self.btn_container,
            text="✗",
            width=24,
            height=24,
            fg_color="transparent",
            hover_color=COLOR_DANGER,
            text_color=COLOR_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=lambda: self.trigger_action("delete"),
        )
        self.btn_delete.pack(side="left", padx=2)
        self.btn_delete.bind("<Enter>", lambda e: self.btn_delete.configure(text_color="white"))
        self.btn_delete.bind("<Leave>", lambda e: self.btn_delete.configure(text_color=COLOR_MUTED))

        self.tip_toggle = ToolTip(self.btn_toggle, "Iniciar terminal")
        self.tip_restart = ToolTip(self.btn_restart, "Reiniciar terminal")
        self.tip_copy = ToolTip(self.btn_copy, "Copiar logs registrados")
        self.tip_audit = ToolTip(self.btn_audit, "Ver auditoría de logs")
        self.tip_edit = ToolTip(self.btn_edit, "Editar configuración")
        self.tip_maximize = ToolTip(self.btn_maximize, "Restaurar rejilla" if self.is_maximized else "Maximizar terminal")
        self.tip_delete = ToolTip(self.btn_delete, "Eliminar servicio")

        import tkinter as tk

        self.console_container = tk.Frame(self, bg="#0c0c0c", takefocus=1)
        self.console_container.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.console_container.bind("<Configure>", self.on_resize)

        self.update_status_ui()

    def trigger_action(self, action):
        if self.on_action:
            self.on_action(self.service.id, action)

    def copy_logs(self):
        logs = self.service.get_logs()
        if not logs:
            logs = "--- No hay logs registrados para este servicio ---"
        self.clipboard_clear()
        self.clipboard_append(logs)
        self.btn_copy.configure(text="✓")
        self.tip_copy.update_text("Copiado con éxito")
        self.restore_copy_button_id = self.after(1500, self.restore_copy_button)

    def restore_copy_button(self):
        self.btn_copy.configure(text="📋")
        self.tip_copy.update_text("Copiar logs registrados")

    def toggle_state(self):
        if self.service.status in ("running", "starting"):
            self.stop_terminal()
        else:
            self.start_terminal()

    def start_terminal(self):
        if self.service.status in ("running", "starting"):
            self.schedule_embed()
            return

        self.child_hwnd = None
        setattr(self.service, "console_hwnd", None)
        self.service.start(execution_mode="native_terminal", hidden=True)
        self.embed_attempts = 0
        self.schedule_embed()

    def stop_terminal(self):
        self.detach_child(clear_service_hwnd=True)
        self.service.stop()
        self.update_status_ui()

    def restart_terminal(self):
        self.stop_terminal()
        self.after(500, self.start_terminal)

    def schedule_embed(self):
        if self.embed_after_id:
            try:
                self.after_cancel(self.embed_after_id)
            except Exception:
                pass
        self.embed_after_id = self.after(50, self.try_embed_console)

    def try_embed_console(self):
        self.embed_after_id = None
        if not self.winfo_exists():
            return

        hwnd = self.child_hwnd or getattr(self.service, "console_hwnd", None)
        if not hwnd and self.service.process:
            hwnd = self.find_hwnd_by_pid(self.service.process.pid)

        if hwnd:
            self.embed_hwnd(hwnd)
            return

        self.embed_attempts += 1
        if self.service.status in ("starting", "running") and self.embed_attempts < 100:
            self.schedule_embed()

    def find_hwnd_by_pid(self, target_pid):
        hwnd_found = [0]
        child_pids = set()
        try:
            import psutil

            parent_proc = psutil.Process(target_pid)
            for child in parent_proc.children(recursive=True):
                child_pids.add(child.pid)
        except Exception:
            pass

        def enum_callback(hwnd, lParam):
            window_pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(window_pid))
            wpid = window_pid.value

            if wpid == target_pid or wpid in child_pids:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == "ConsoleWindowClass":
                    hwnd_found[0] = hwnd
                    return False
            return True

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)
        return hwnd_found[0]

    def embed_hwnd(self, hwnd):
        if not hwnd or not self.console_container:
            return

        self.child_hwnd = hwnd
        setattr(self.service, "console_hwnd", hwnd)

        parent_hwnd = self.console_container.winfo_id()
        parent_style = user32.GetWindowLongW(parent_hwnd, GWL_STYLE)
        parent_style |= WS_CLIPCHILDREN
        user32.SetWindowLongW(parent_hwnd, GWL_STYLE, parent_style)
        user32.SetWindowPos(parent_hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002)

        style = user32.GetWindowLongW(self.child_hwnd, GWL_STYLE)
        style &= ~WS_POPUP
        style &= ~WS_CAPTION
        style &= ~WS_THICKFRAME
        style &= ~WS_MINIMIZEBOX
        style &= ~WS_MAXIMIZEBOX
        style &= ~WS_BORDER
        style |= WS_CHILD
        style |= WS_DISABLED
        user32.SetWindowLongW(self.child_hwnd, GWL_STYLE, style)
        user32.SetParent(self.child_hwnd, parent_hwnd)
        user32.EnableWindow(self.child_hwnd, False)
        user32.ShowWindow(self.child_hwnd, 8)
        user32.UpdateWindow(self.child_hwnd)

        self.update_idletasks()
        self.on_resize()

    def detach_child(self, clear_service_hwnd=False):
        if not self.child_hwnd:
            return

        try:
            child_thread = user32.GetWindowThreadProcessId(self.child_hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            if child_thread != current_thread:
                user32.AttachThreadInput(current_thread, child_thread, False)
        except Exception:
            pass

        try:
            user32.ShowWindow(self.child_hwnd, 0)
            user32.SetParent(self.child_hwnd, 0)
        except Exception:
            pass

        if clear_service_hwnd:
            setattr(self.service, "console_hwnd", None)
        self.child_hwnd = None

    def on_resize(self, event=None):
        if self.child_hwnd and self.console_container:
            w = self.console_container.winfo_width()
            h = self.console_container.winfo_height()
            if w > 1 and h > 1:
                user32.MoveWindow(self.child_hwnd, 0, 0, w, h, True)
                user32.ShowWindow(self.child_hwnd, 8)
                user32.SetWindowPos(self.child_hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002)
                user32.UpdateWindow(self.child_hwnd)
            elif self.winfo_exists():
                self.resize_after_id = self.after(50, self.on_resize)

    def on_map(self, event=None):
        if self.service.status in ("running", "starting"):
            self.schedule_embed()

    def update_status_ui(self):
        status = self.service.status

        if status == "running":
            self.status_badge.configure(fg_color=COLOR_SUCCESS)
            self.btn_toggle.configure(text="■", fg_color=COLOR_DANGER, hover_color="#dc2626")
            self.btn_restart.configure(state="normal")
            self.tip_toggle.update_text("Detener terminal")
            if not self.child_hwnd:
                self.schedule_embed()
        elif status == "starting":
            self.status_badge.configure(fg_color=COLOR_WARNING)
            self.btn_toggle.configure(text="■", fg_color=COLOR_DANGER, hover_color="#dc2626")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Detener terminal")
            if not self.child_hwnd:
                self.schedule_embed()
        elif status == "error":
            self.status_badge.configure(fg_color=COLOR_DANGER)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Iniciar terminal")
        else:
            self.status_badge.configure(fg_color=COLOR_MUTED)
            self.btn_toggle.configure(text="▶", fg_color=COLOR_SUCCESS, hover_color="#059669")
            self.btn_restart.configure(state="disabled")
            self.tip_toggle.update_text("Iniciar terminal")

        if status == "running":
            cpu_val = self.service.cpu_usage
            mem_mb = self.service.mem_usage / (1024 * 1024)
            mem_str = f"{mem_mb:.0f}MB" if mem_mb < 1024 else f"{mem_mb/1024:.1f}GB"
            self.lbl_stats.configure(text=f"{cpu_val:.1f}% | {mem_str}", text_color="white")
        else:
            self.lbl_stats.configure(text="Offline", text_color=COLOR_MUTED)

    def destroy(self):
        for attr in ("embed_after_id", "resize_after_id"):
            after_id = getattr(self, attr, None)
            if after_id:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        if hasattr(self, "restore_copy_button_id") and self.restore_copy_button_id:
            try:
                self.after_cancel(self.restore_copy_button_id)
            except Exception:
                pass
        self.detach_child(clear_service_hwnd=False)
        super().destroy()


class WorkspaceView(ctk.CTkFrame):
    def __init__(self, parent, manager, on_action=None, on_delete_workspace=None, on_add_service=None, on_workspace_startups_changed=None):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        
        self.manager = manager
        self.workspace_id = None
        self.on_action = on_action
        self.on_delete_workspace = on_delete_workspace
        self.on_add_service = on_add_service
        self.on_workspace_startups_changed = on_workspace_startups_changed
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

        self.startup_var = ctk.StringVar(value="Inicio predeterminado")
        self.startup_menu = ctk.CTkOptionMenu(
            self.actions_frame,
            values=["Inicio predeterminado"],
            variable=self.startup_var,
            width=165,
            height=32,
            fg_color=BG_MAIN,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white",
            command=self.change_workspace_startup,
        )
        self.startup_menu.pack(side="left", padx=3)

        self.btn_add_startup = ctk.CTkButton(
            self.actions_frame,
            text="+",
            width=30,
            height=32,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=13, weight="bold"),
            command=self.open_add_startup_dialog,
        )
        self.btn_add_startup.pack(side="left", padx=2)

        self.btn_edit_startup = ctk.CTkButton(
            self.actions_frame,
            text="⚙",
            width=30,
            height=32,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            text_color="white",
            font=ctk.CTkFont(size=11),
            command=self.open_edit_startup_dialog,
        )
        self.btn_edit_startup.pack(side="left", padx=2)

        self.btn_delete_startup = ctk.CTkButton(
            self.actions_frame,
            text="✕",
            width=30,
            height=32,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color=COLOR_MUTED,
            hover_color=COLOR_DANGER,
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.delete_selected_startup,
        )
        self.btn_delete_startup.pack(side="left", padx=(2, 8))

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
        self.tip_startup = ToolTip(self.startup_menu, "Inicio del espacio: selecciona flujos por servicio")
        self.tip_add_startup = ToolTip(self.btn_add_startup, "Crear inicio desde la selección actual")
        self.tip_edit_startup = ToolTip(self.btn_edit_startup, "Editar inicio seleccionado")
        self.tip_delete_startup = ToolTip(self.btn_delete_startup, "Eliminar inicio seleccionado")
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
        
        self.refresh_startup_menu()
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

    def schedule_panels_scroll_to_end(self):
        def scroll_all():
            for panel in list(self.panels.values()):
                panel.schedule_scroll_to_end()

        try:
            self.after_idle(scroll_all)
            self.after(150, scroll_all)
            self.after(400, scroll_all)
        except:
            pass

    def refresh_startup_menu(self):
        if not self.workspace_id:
            return

        options = self.manager.get_workspace_startup_options(self.workspace_id)
        labels = [label for label, _ in options] or ["Inicio predeterminado"]
        selected_label = self.manager.get_selected_workspace_startup_label(self.workspace_id)
        if selected_label not in labels:
            selected_label = labels[0]

        self.startup_menu.configure(values=labels)
        self.startup_var.set(selected_label)
        self.update_startup_buttons()

    def selected_startup_id(self):
        if not self.workspace_id:
            return DEFAULT_STARTUP_ID
        return self.manager.get_workspace_startup_id_from_label(self.workspace_id, self.startup_var.get())

    def update_startup_buttons(self):
        startup_id = self.selected_startup_id()
        services = self.manager.workspace_services.get(self.workspace_id, []) if self.workspace_id else []
        state = "disabled" if startup_id == DEFAULT_STARTUP_ID else "normal"
        add_state = "normal" if services else "disabled"
        self.btn_add_startup.configure(state=add_state)
        self.btn_edit_startup.configure(state=state)
        self.btn_delete_startup.configure(state=state)

    def change_workspace_startup(self, startup_label):
        if not self.workspace_id:
            return

        services = self.manager.workspace_services.get(self.workspace_id, [])
        if any(service.status in ["running", "starting"] for service in services):
            self.refresh_startup_menu()
            return

        startup_id = self.manager.get_workspace_startup_id_from_label(self.workspace_id, startup_label)
        if startup_id and self.manager.select_workspace_startup(self.workspace_id, startup_id):
            self.refresh_startup_menu()
            self.rebuild_grid()
            self.update_stats()

    def open_add_startup_dialog(self):
        if not self.workspace_id:
            return

        services = self.manager.workspace_services.get(self.workspace_id, [])
        service_profiles = {service.id: service.selected_deploy_profile_id for service in services}
        startup_config = {
            "name": "",
            "service_profiles": service_profiles,
        }
        WorkspaceStartupDialog(
            self,
            self.manager,
            self.workspace_id,
            startup_config=startup_config,
            on_save=self.save_workspace_startup,
        )

    def open_edit_startup_dialog(self):
        if not self.workspace_id:
            return
        startup_id = self.selected_startup_id()
        if startup_id == DEFAULT_STARTUP_ID:
            return

        startup_config = self.manager.get_workspace_startup_config(self.workspace_id, startup_id)
        if not startup_config:
            return

        WorkspaceStartupDialog(
            self,
            self.manager,
            self.workspace_id,
            startup_config=startup_config,
            on_save=self.save_workspace_startup,
        )

    def save_workspace_startup(self, startup_config):
        if not self.workspace_id:
            return

        self.manager.save_workspace_startup(self.workspace_id, startup_config)
        self.refresh_startup_menu()
        self.rebuild_grid()
        self.update_stats()
        if self.on_workspace_startups_changed:
            self.on_workspace_startups_changed()

    def delete_selected_startup(self):
        if not self.workspace_id:
            return
        startup_id = self.selected_startup_id()
        if startup_id == DEFAULT_STARTUP_ID:
            return

        startup_label = self.startup_var.get()
        if not messagebox.askyesno("Eliminar Inicio", f"¿Eliminar el inicio '{startup_label}'?"):
            return

        self.manager.remove_workspace_startup(self.workspace_id, startup_id)
        self.refresh_startup_menu()
        self.rebuild_grid()
        self.update_stats()
        if self.on_workspace_startups_changed:
            self.on_workspace_startups_changed()

    def rebuild_grid(self):
        """Reconstruye el grid de terminales en pantalla basado en los servicios del workspace."""
        if not self.workspace_id:
            return
        self.refresh_startup_menu()

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
            self.main_area.pack_forget()
            
            self.grid_container = ctk.CTkFrame(self, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
            self.grid_container.pack(fill="both", expand=True, padx=15, pady=(0, 15))
            
            empty_container = ctk.CTkFrame(self.grid_container, fg_color="transparent")
            empty_container.pack(expand=True)
            
            icon_lbl = ctk.CTkLabel(
                empty_container,
                text="📂",
                font=ctk.CTkFont(size=48)
            )
            icon_lbl.pack(pady=(0, 10))
            
            title_lbl = ctk.CTkLabel(
                empty_container,
                text="Espacio de Trabajo Vacío",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="white"
            )
            title_lbl.pack(pady=(0, 5))
            
            placeholder_lbl = ctk.CTkLabel(
                empty_container, 
                text="Haz clic en '+ Añadir Servicio' arriba para configurar tu primera ejecución.", 
                font=FONT_MUTED, text_color=COLOR_MUTED,
                justify="center"
            )
            placeholder_lbl.pack()
            
            self.btn_start_all.configure(state="disabled")
            self.btn_stop_all.configure(state="disabled")
            self.maximized_service_id = None # Resetear si se vacía
            return

        self.main_area.pack(fill="both", expand=True, padx=15, pady=(0, 15))
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
                self.schedule_panels_scroll_to_end()
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
            self.schedule_panels_scroll_to_end()
            
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
            self.schedule_panels_scroll_to_end()
                
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
            self.schedule_panels_scroll_to_end()

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
        self.manager.start_workspace(self.workspace_id, execution_mode="captured")
        self.update_stats()

    def stop_all_services(self):
        self.manager.stop_workspace(self.workspace_id)
        self.update_stats()

    def start_service_terminal(self, service_id):
        self.manager.start_service(service_id, execution_mode="captured")

    def add_service_click(self):
        if self.on_add_service and self.workspace_id:
            self.on_add_service(self.workspace_id)

    def delete_workspace_click(self):
        if self.on_delete_workspace and self.workspace_id:
            self.on_delete_workspace(self.workspace_id)
