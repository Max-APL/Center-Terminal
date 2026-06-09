import os
import sys
import subprocess
import customtkinter as ctk
from datetime import datetime
from ui.theme import *
from ui.components import ToolTip

class AuditView(ctk.CTkFrame):
    def __init__(self, parent, manager):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.manager = manager
        self.selected_service_id = None
        self.search_visible = False
        
        self.service_buttons = {}  # service_id -> button widget
        
        self.create_widgets()
        
    def create_widgets(self):
        # 1. Cabecera (Header)
        self.header_frame = ctk.CTkFrame(self, fg_color=BG_CARD, height=80, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        self.header_frame.pack_propagate(False)
        
        # Izquierda: Info de Nombre y Recursos
        info_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", padx=15, pady=8)
        
        lbl_ws_name = ctk.CTkLabel(info_frame, text="Auditoría de Logs", font=FONT_TITLE, text_color="white")
        lbl_ws_name.pack(anchor="w")
        
        lbl_ws_stats = ctk.CTkLabel(info_frame, text="Historial completo registrado automáticamente con marcas de tiempo", font=FONT_MUTED, text_color=COLOR_MUTED)
        lbl_ws_stats.pack(anchor="w", pady=(1, 0))

        # Derecha: Botones de Gestión
        actions_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        actions_frame.pack(side="right", fill="y", padx=15, pady=12)

        # Botón Abrir Carpeta
        self.btn_open_folder = ctk.CTkButton(
            actions_frame, text="📂 Abrir Carpeta", width=120, height=32,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            font=ctk.CTkFont(size=12),
            command=self.open_logs_folder
        )
        self.btn_open_folder.pack(side="left", padx=3)
        self.tip_open_folder = ToolTip(self.btn_open_folder, "Abrir carpeta física de logs en el Explorador")

        # Botón Limpiar Historial (Archivo)
        self.btn_clear_history = ctk.CTkButton(
            actions_frame, text="🗑 Limpiar Archivo", width=120, height=32,
            fg_color="transparent", border_width=1, border_color=COLOR_DANGER,
            text_color=COLOR_DANGER, hover_color="#450a0a",
            font=ctk.CTkFont(size=12),
            command=self.clear_selected_log_file
        )
        self.btn_clear_history.pack(side="left", padx=3)
        self.tip_clear_history = ToolTip(self.btn_clear_history, "Borrar el archivo físico de logs del servicio seleccionado")
        
        # 2. Área Principal (Dos columnas)
        main_split = ctk.CTkFrame(self, fg_color="transparent")
        main_split.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        
        # Columna Izquierda: Selector de servicios (Frame de 250px)
        self.left_sidebar = ctk.CTkFrame(main_split, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12, width=250)
        self.left_sidebar.pack(side="left", fill="y", padx=(0, 10))
        self.left_sidebar.pack_propagate(False)
        
        sidebar_title = ctk.CTkLabel(self.left_sidebar, text="SERVICIOS", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLOR_MUTED)
        sidebar_title.pack(anchor="w", padx=15, pady=(15, 10))
        
        self.services_scroll = ctk.CTkScrollableFrame(self.left_sidebar, fg_color="transparent")
        self.services_scroll.pack(fill="both", expand=True, padx=5, pady=5)
        
        # Columna Derecha: Visor de Logs
        self.right_viewer = ctk.CTkFrame(main_split, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
        self.right_viewer.pack(side="right", fill="both", expand=True)
        
        # Placeholder por defecto
        self.placeholder_frame = ctk.CTkFrame(self.right_viewer, fg_color="transparent")
        self.placeholder_frame.pack(fill="both", expand=True)
        
        empty_container = ctk.CTkFrame(self.placeholder_frame, fg_color="transparent")
        empty_container.pack(expand=True)
        
        icon_lbl = ctk.CTkLabel(empty_container, text="📜", font=ctk.CTkFont(size=48))
        icon_lbl.pack(pady=(0, 10))
        
        title_lbl = ctk.CTkLabel(empty_container, text="Historial de Auditoría de Logs", font=ctk.CTkFont(size=16, weight="bold"), text_color="white")
        title_lbl.pack(pady=(0, 5))
        
        placeholder_lbl = ctk.CTkLabel(
            empty_container, 
            text="Selecciona un servicio a la izquierda para explorar su historial de logs registrado.", 
            font=FONT_MUTED, text_color=COLOR_MUTED,
            justify="center"
        )
        placeholder_lbl.pack()
        
        # Elementos de logs (ocultos inicialmente)
        self.viewer_content = ctk.CTkFrame(self.right_viewer, fg_color="transparent")
        
        # Barra superior del visor (Búsqueda y Filtro rápido)
        self.viewer_header = ctk.CTkFrame(self.viewer_content, fg_color="transparent", height=40)
        self.viewer_header.pack(fill="x", padx=10, pady=(10, 5))
        self.viewer_header.pack_propagate(False)
        
        search_icon = ctk.CTkLabel(self.viewer_header, text=" 🔍 ", font=FONT_BODY, text_color=COLOR_MUTED)
        search_icon.pack(side="left", padx=5)
        
        self.search_entry = ctk.CTkEntry(
            self.viewer_header, placeholder_text="Buscar en el historial de logs...",
            height=28, fg_color=BG_MAIN, border_color=BORDER_COLOR,
            font=FONT_BODY
        )
        self.search_entry.pack(side="left", fill="x", expand=True, padx=5)
        self.search_entry.bind("<KeyRelease>", self.perform_search)
        
        btn_refresh = ctk.CTkButton(
            self.viewer_header, text="↻ Refrescar", width=80, height=28,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            font=ctk.CTkFont(size=11), command=self.load_selected_logs
        )
        btn_refresh.pack(side="right", padx=5)
        
        # Consola del visor
        self.console_container = ctk.CTkFrame(self.viewer_content, fg_color=TERMINAL_BG, border_width=1, border_color=BORDER_COLOR, corner_radius=8)
        self.console_container.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        
        self.console_text = ctk.CTkTextbox(
            self.console_container, 
            fg_color=TERMINAL_BG, 
            text_color=TERMINAL_FG,
            font=FONT_MONO,
            corner_radius=8,
            wrap="word",
            border_width=0
        )
        self.console_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.console_text.configure(state="disabled")
        
    def refresh(self):
        """Recarga la lista de servicios del manager y refresca la vista."""
        # Limpiar botones
        for btn in list(self.service_buttons.values()):
            btn.destroy()
        self.service_buttons.clear()
        
        services = self.manager.services
        
        if not services:
            no_svc_lbl = ctk.CTkLabel(self.services_scroll, text="No hay servicios registrados", font=FONT_MUTED, text_color=COLOR_MUTED, justify="center")
            no_svc_lbl.pack(pady=40, padx=10)
            self.service_buttons["_empty"] = no_svc_lbl
            self.show_placeholder()
            return
            
        # Reconstruir lista de servicios
        for s_id, srv in services.items():
            btn = ctk.CTkButton(
                self.services_scroll, text=srv.name, height=36,
                fg_color="transparent", hover_color=BG_CARD_HOVER,
                text_color=COLOR_MUTED, anchor="w",
                font=ctk.CTkFont(size=12),
                command=lambda sid=s_id: self.select_service(sid)
            )
            btn.pack(fill="x", pady=2)
            self.service_buttons[s_id] = btn
            
        # Resaltar el seleccionado
        if self.selected_service_id and self.selected_service_id in services:
            self.select_service(self.selected_service_id)
        else:
            self.selected_service_id = None
            self.show_placeholder()
            
    def select_service(self, service_id):
        self.selected_service_id = service_id
        
        # Limpiar colores
        for sid, btn in self.service_buttons.items():
            if sid != "_empty":
                if sid == service_id:
                    btn.configure(fg_color=BG_CARD_HOVER, text_color="white")
                else:
                    btn.configure(fg_color="transparent", text_color=COLOR_MUTED)
                    
        self.placeholder_frame.pack_forget()
        self.viewer_content.pack(fill="both", expand=True)
        
        self.load_selected_logs()
        
    def show_placeholder(self):
        self.viewer_content.pack_forget()
        self.placeholder_frame.pack(fill="both", expand=True)
        self.btn_clear_history.configure(state="disabled")
        
    def get_log_file_path(self, service):
        if not service:
            return None
        from config import get_base_dir
        base_dir = get_base_dir()
        logs_dir = os.path.join(base_dir, "logs")
        
        sanitized_name = "".join(c for c in service.name if c.isalnum() or c in (' ', '_', '-')).strip()
        sanitized_name = sanitized_name.replace(' ', '_')
        return os.path.join(logs_dir, f"{sanitized_name}_{service.id}.txt")
        
    def load_selected_logs(self):
        if not self.selected_service_id:
            return
            
        service = self.manager.services.get(self.selected_service_id)
        if not service:
            self.show_placeholder()
            return
            
        self.btn_clear_history.configure(state="normal")
        
        file_path = self.get_log_file_path(service)
        
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        
        if file_path and os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
                self.console_text.insert("end", content)
                self.console_text.see("end")
            except Exception as e:
                self.console_text.insert("end", f"Error al leer archivo de logs de auditoría: {e}")
        else:
            self.console_text.insert("end", "--- Aún no hay registros de auditoría para este servicio ---\nLos logs se guardarán automáticamente aquí a medida que el servicio se ejecute.")
            
        self.console_text.configure(state="disabled")
        self.perform_search() # Reaplica el filtro si hay texto de búsqueda
        
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
            
    def open_logs_folder(self):
        try:
            from config import get_base_dir
            base_dir = get_base_dir()
            logs_dir = os.path.join(base_dir, "logs")
            os.makedirs(logs_dir, exist_ok=True)
            
            if os.name == 'nt':
                os.startfile(logs_dir)
            elif sys.platform == 'darwin':
                subprocess.Popen(['open', logs_dir])
            else:
                subprocess.Popen(['xdg-open', logs_dir])
        except Exception as e:
            pass

    def clear_selected_log_file(self):
        if not self.selected_service_id:
            return
            
        service = self.manager.services.get(self.selected_service_id)
        if not service:
            return
            
        from tkinter import messagebox
        if messagebox.askyesno("Confirmar eliminación", f"¿Estás seguro de que deseas eliminar permanentemente el archivo físico de logs del servicio '{service.name}'?"):
            file_path = self.get_log_file_path(service)
            try:
                if file_path and os.path.exists(file_path):
                    os.remove(file_path)
                self.load_selected_logs()
            except Exception as e:
                messagebox.showerror("Error", f"No se pudo eliminar el archivo: {e}")
