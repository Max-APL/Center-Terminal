import customtkinter as ctk
import sys
import uuid
from tkinter import messagebox
from ui.theme import *
from ui.dashboard import DashboardView
from ui.workspace_view import WorkspaceView
from ui.audit_view import AuditView
from ui.quick_view import FreeQuickView
from ui.service_dialog import ServiceDialog
from config import save_workspaces
from ui.components import ToolTip

class CentralTerminalApp(ctk.CTk):
    def __init__(self, manager):
        super().__init__()
        
        self.manager = manager
        
        # Configurar Ventana Principal
        self.title("Central Terminal - Workspaces")
        self.geometry("1024x660")
        self.minimum_size = (950, 600)
        self.minsize(self.minimum_size[0], self.minimum_size[1])
        
        # Tema Oscuro
        ctk.set_appearance_mode(THEME_MODE)
        self.configure(fg_color=BG_MAIN)
        
        # Estado de la UI
        self.selected_workspace_id = None
        self.sidebar_widgets = {}  # Cache de widgets del sidebar
        self.current_view = "dashboard"  # dashboard | workspace
        
        self.create_layout()
        
        # Carga Inicial
        self.rebuild_ui()
        self.show_view("dashboard")
        
        # Bucle periódico de refresco
        self.update_loop()
        
        # Manejador de cierre de ventana
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def create_layout(self):
        # 1. Barra Lateral (Sidebar)
        self.sidebar_frame = ctk.CTkFrame(self, width=260, fg_color=BG_SIDEBAR, corner_radius=0)
        self.sidebar_frame.pack(side="left", fill="y")
        self.sidebar_frame.pack_propagate(False)

        # Logotipo / Nombre
        logo_label = ctk.CTkLabel(
            self.sidebar_frame, text="Central Terminal", 
            font=ctk.CTkFont(size=22, weight="bold"), text_color="white"
        )
        logo_label.pack(pady=(25, 5), padx=20, anchor="w")
        
        sub_label = ctk.CTkLabel(
            self.sidebar_frame, text="Orquestador de procesos", 
            font=FONT_MUTED, text_color=COLOR_MUTED
        )
        sub_label.pack(pady=(0, 20), padx=20, anchor="w")

        # Botón Dashboard Global
        self.btn_dashboard = ctk.CTkButton(
            self.sidebar_frame, text="Panel de Control", height=40,
            fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white",
            anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("dashboard")
        )
        self.btn_dashboard.pack(fill="x", padx=15, pady=5)
        self.tip_dashboard = ToolTip(self.btn_dashboard, "Ver panel de control global")

        self.btn_audit = ctk.CTkButton(
            self.sidebar_frame, text="Auditoría de Logs", height=40,
            fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED,
            anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("audit")
        )
        self.btn_audit.pack(fill="x", padx=15, pady=5)
        self.tip_audit = ToolTip(self.btn_audit, "Ver historial de auditoría de logs")

        # Botón Terminal Libre (Sandbox)
        self.btn_quick = ctk.CTkButton(
            self.sidebar_frame, text="Terminal Libre (Sandbox)", height=40,
            fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED,
            anchor="w", font=ctk.CTkFont(size=13, weight="bold"),
            command=lambda: self.show_view("quick")
        )
        self.btn_quick.pack(fill="x", padx=15, pady=5)
        self.tip_quick = ToolTip(self.btn_quick, "Consolas interactivas libres de prueba")

        # Separador
        ctk.CTkFrame(self.sidebar_frame, height=1, fg_color=BORDER_COLOR).pack(fill="x", padx=15, pady=12)

        # Cabecera Espacios de Trabajo
        ws_header = ctk.CTkFrame(self.sidebar_frame, fg_color="transparent")
        ws_header.pack(fill="x", padx=15, pady=(0, 5))
        
        ctk.CTkLabel(ws_header, text="ESPACIOS DE TRABAJO", font=FONT_MUTED, text_color=COLOR_MUTED).pack(side="left")
        
        # Botón Añadir Espacio de Trabajo ("+")
        btn_add_ws = ctk.CTkButton(
            ws_header, text="+", width=22, height=22,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.open_create_workspace_dialog
        )
        btn_add_ws.pack(side="right")
        self.tip_add_ws = ToolTip(btn_add_ws, "Crear nuevo espacio de trabajo")

        # Lista de Espacios de Trabajo (Sidebar Scrollable)
        self.sidebar_scroll = ctk.CTkScrollableFrame(self.sidebar_frame, fg_color="transparent")
        self.sidebar_scroll.pack(fill="both", expand=True, padx=5, pady=5)

        # Recursos Globales al Fondo
        self.resources_frame = ctk.CTkFrame(self.sidebar_frame, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=8)
        self.resources_frame.pack(fill="x", padx=15, pady=15)
        
        self.lbl_global_cpu = ctk.CTkLabel(self.resources_frame, text="CPU Total: 0.0%", font=FONT_MUTED, text_color="white")
        self.lbl_global_cpu.pack(anchor="w", padx=12, pady=(10, 2))
        
        self.lbl_global_mem = ctk.CTkLabel(self.resources_frame, text="Mem Total: 0 MB", font=FONT_MUTED, text_color="white")
        self.lbl_global_mem.pack(anchor="w", padx=12, pady=(0, 10))

        # 2. Contenedor Principal (Derecha)
        self.main_content = ctk.CTkFrame(self, fg_color=BG_MAIN, corner_radius=0)
        self.main_content.pack(side="right", fill="both", expand=True)

        # Instanciar Dashboard y Workspace Grid
        self.dashboard_view = DashboardView(
            self.main_content,
            on_action=self.handle_service_action,
            on_select_service=self.jump_to_service_workspace
        )
        
        self.workspace_view = WorkspaceView(
            self.main_content,
            self.manager,
            on_action=self.handle_service_action,
            on_delete_workspace=self.confirm_delete_workspace,
            on_add_service=self.open_add_service_dialog
        )
        
        self.audit_view = AuditView(
            self.main_content,
            self.manager
        )

        self.quick_view = FreeQuickView(
            self.main_content
        )

    def rebuild_ui(self):
        """Redibuja el listado de workspaces del sidebar y regenera los grids de ser necesario."""
        # 1. Limpiar lista de Sidebar
        for widget_dict in list(self.sidebar_widgets.values()):
            widget_dict["frame"].destroy()
        self.sidebar_widgets.clear()

        # 2. Reconstruir lista de Workspaces en Sidebar
        for ws_id, ws_name in self.manager.workspaces.items():
            row_frame = ctk.CTkFrame(self.sidebar_scroll, fg_color="transparent", height=36)
            row_frame.pack(fill="x", pady=2)
            row_frame.pack_propagate(False)

            # Dot Badge indicador (verde si hay algún proceso activo en el workspace)
            badge = ctk.CTkFrame(row_frame, width=8, height=8, corner_radius=4, fg_color=COLOR_MUTED)
            badge.pack(side="left", padx=(10, 8), pady=14)
            badge.pack_propagate(False)

            is_selected = (ws_id == self.selected_workspace_id and self.current_view == "workspace")
            bg_color = BG_CARD if is_selected else "transparent"

            btn = ctk.CTkButton(
                row_frame, text=ws_name, height=36,
                fg_color=bg_color, hover_color=BG_CARD_HOVER,
                text_color="white" if is_selected else COLOR_MUTED,
                anchor="w", font=ctk.CTkFont(size=12),
                command=lambda w_id=ws_id: self.select_workspace_by_id(w_id)
            )
            btn.pack(side="left", fill="both", expand=True)

            self.sidebar_widgets[ws_id] = {
                "frame": row_frame,
                "badge": badge,
                "button": btn
            }

        # 3. Reconstruir Dashboard Grid
        self.dashboard_view.rebuild_grid(self.manager.services)
        
        # 4. Forzar actualización de badges en sidebar
        self.update_sidebar_badges()

        # 5. Refrescar Audit View
        self.audit_view.refresh()

    def show_view(self, view_name):
        self.current_view = view_name
        if view_name == "dashboard":
            self.workspace_view.pack_forget()
            self.audit_view.pack_forget()
            self.quick_view.pack_forget()
            self.dashboard_view.pack(fill="both", expand=True)
            self.btn_dashboard.configure(fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white")
            self.btn_audit.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_quick.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.selected_workspace_id = None
            self.clear_sidebar_selection()
        elif view_name == "workspace":
            self.dashboard_view.pack_forget()
            self.audit_view.pack_forget()
            self.quick_view.pack_forget()
            self.workspace_view.pack(fill="both", expand=True)
            self.btn_dashboard.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_audit.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_quick.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.highlight_selected_sidebar_item()
        elif view_name == "audit":
            self.dashboard_view.pack_forget()
            self.workspace_view.pack_forget()
            self.quick_view.pack_forget()
            self.audit_view.pack(fill="both", expand=True)
            self.btn_dashboard.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_audit.configure(fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white")
            self.btn_quick.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.selected_workspace_id = None
            self.clear_sidebar_selection()
            self.audit_view.refresh()
        elif view_name == "quick":
            self.dashboard_view.pack_forget()
            self.workspace_view.pack_forget()
            self.audit_view.pack_forget()
            self.quick_view.pack(fill="both", expand=True)
            self.btn_dashboard.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_audit.configure(fg_color="transparent", hover_color=BG_CARD_HOVER, text_color=COLOR_MUTED)
            self.btn_quick.configure(fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white")
            self.selected_workspace_id = None
            self.clear_sidebar_selection()

    def select_workspace_by_id(self, workspace_id):
        self.selected_workspace_id = workspace_id
        if workspace_id in self.manager.workspaces:
            self.workspace_view.set_workspace(workspace_id)
            self.show_view("workspace")

    def jump_to_service_workspace(self, service_id):
        """Permite saltar directamente al workspace de un servicio específico (ej: desde Dashboard)."""
        service = self.manager.services.get(service_id)
        if service:
            self.select_workspace_by_id(service.workspace_id)

    def highlight_selected_sidebar_item(self):
        self.clear_sidebar_selection()
        widget_dict = self.sidebar_widgets.get(self.selected_workspace_id)
        if widget_dict:
            widget_dict["button"].configure(fg_color=BG_CARD, text_color="white")

    def clear_sidebar_selection(self):
        for widget_dict in self.sidebar_widgets.values():
            widget_dict["button"].configure(fg_color="transparent", text_color=COLOR_MUTED)

    # --- Acciones sobre Workspaces ---
    def open_create_workspace_dialog(self):
        dialog = ctk.CTkInputDialog(text="Introduce el nombre del nuevo Espacio de Trabajo:", title="Nuevo Espacio")
        # El método get_input bloquea hasta recibir respuesta
        name = dialog.get_input()
        if name and name.strip():
            ws_id = str(uuid.uuid4())
            self.manager.add_workspace(ws_id, name.strip())
            self.persist_workspaces()
            self.rebuild_ui()
            self.select_workspace_by_id(ws_id)

    def confirm_delete_workspace(self, workspace_id):
        ws_name = self.manager.workspaces.get(workspace_id, "Desconocido")
        if messagebox.askyesno(
            "Eliminar Espacio de Trabajo", 
            f"¿Estás seguro de que deseas eliminar el espacio '{ws_name}'?\nSe detendrán y eliminarán todos sus servicios asociados."
        ):
            self.manager.remove_workspace(workspace_id)
            self.persist_workspaces()
            self.rebuild_ui()
            self.show_view("dashboard")

    # --- Acciones sobre Servicios ---
    def open_add_service_dialog(self, workspace_id):
        dialog = ServiceDialog(self, on_save=lambda cfg: self.save_new_service(workspace_id, cfg))

    def save_new_service(self, workspace_id, config):
        self.manager.add_service(workspace_id, config)
        self.persist_workspaces()
        self.rebuild_ui()
        # Refrescar grid de la vista activa
        if self.selected_workspace_id == workspace_id:
            self.workspace_view.rebuild_grid()

    def save_edited_service(self, config):
        service_id = config.get("id")
        service = self.manager.services.get(service_id)
        if not service:
            return
            
        workspace_id = service.workspace_id
        self.manager.update_service(service_id, config)
        self.persist_workspaces()
        self.rebuild_ui()
        
        # Refrescar grid
        if self.selected_workspace_id == workspace_id:
            self.workspace_view.rebuild_grid()

    def delete_service(self, service_id):
        service = self.manager.services.get(service_id)
        if not service:
            return
            
        workspace_id = service.workspace_id
        if messagebox.askyesno("Eliminar Servicio", f"¿Estás seguro de eliminar el servicio '{service.name}'?"):
            self.manager.remove_service(service_id)
            self.persist_workspaces()
            self.rebuild_ui()
            
            # Refrescar grid del workspace
            if self.selected_workspace_id == workspace_id:
                self.workspace_view.rebuild_grid()

    def handle_service_action(self, service_id, action):
        """Procesa las acciones enviadas desde las vistas secundarias."""
        if action == "start":
            self.manager.start_service(service_id)
        elif action == "stop":
            self.manager.stop_service(service_id)
        elif action == "restart":
            self.manager.restart_service(service_id)
        elif action == "edit":
            # Obtener config actual y abrir diálogo
            service = self.manager.services.get(service_id)
            if service:
                cfg = {
                    "id": service.id,
                    "name": service.name,
                    "pre_command": getattr(service, "pre_command", ""),
                    "command": service.command,
                    "cwd": service.cwd,
                    "shell": service.shell_type,
                    "shell_native": getattr(service, "shell_native", False),
                    "auto_restart": service.auto_restart,
                    "restart_delay": service.restart_delay,
                    "env": service.env
                }
                dialog = ServiceDialog(self, service_config=cfg, on_save=self.save_edited_service)
        elif action == "delete":
            self.delete_service(service_id)

    # --- Persistencia ---
    def persist_workspaces(self):
        data = {"workspaces": []}
        for ws_id, ws_name in self.manager.workspaces.items():
            services_list = []
            for service in self.manager.workspace_services.get(ws_id, []):
                services_list.append({
                    "id": service.id,
                    "name": service.name,
                    "pre_command": getattr(service, "pre_command", ""),
                    "command": service.command,
                    "cwd": service.cwd,
                    "shell": service.shell_type,
                    "shell_native": getattr(service, "shell_native", False),
                    "auto_restart": service.auto_restart,
                    "restart_delay": service.restart_delay,
                    "env": service.env
                })
            data["workspaces"].append({
                "id": ws_id,
                "name": ws_name,
                "services": services_list
            })
        save_workspaces(data)

    # --- Loops de Actualización e Interfaz ---
    def update_sidebar_badges(self):
        """Refresca rápidamente el badge de estado de cada Workspace."""
        for ws_id, services in self.manager.workspace_services.items():
            widget_dict = self.sidebar_widgets.get(ws_id)
            if not widget_dict:
                continue
            
            # Buscar si hay algún servicio corriendo
            has_running = any(s.status in ["running", "starting"] for s in services)
            
            if has_running:
                widget_dict["badge"].configure(fg_color=COLOR_SUCCESS)
            else:
                # Comprobar si hay errores
                has_error = any(s.status == "error" for s in services)
                if has_error:
                    widget_dict["badge"].configure(fg_color=COLOR_DANGER)
                else:
                    widget_dict["badge"].configure(fg_color=COLOR_MUTED)

    def update_loop(self):
        try:
            if not self.winfo_exists():
                return
        except:
            return
            
        try:
            # 1. Obtener estadísticas globales y actualizar
            global_stats = self.manager.get_global_stats()
            mem_mb = global_stats["total_mem"] / (1024 * 1024)
            mem_str = f"{mem_mb:.1f} MB" if mem_mb < 1024 else f"{mem_mb/1024:.2f} GB"
            
            self.lbl_global_cpu.configure(text=f"CPU Total: {global_stats['total_cpu']:.1f}%")
            self.lbl_global_mem.configure(text=f"Mem Total: {mem_str}")
    
            # 2. Actualizar la vista activa
            if self.current_view == "dashboard":
                # Calcular estadísticas por cada workspace para pasarlas al gráfico
                ws_stats = {
                    ws_id: self.manager.get_workspace_stats(ws_id)
                    for ws_id in self.manager.workspaces.keys()
                }
                self.dashboard_view.update_stats(self.manager.services, global_stats, ws_stats, self.manager.workspaces)
            elif self.current_view == "workspace" and self.selected_workspace_id:
                self.workspace_view.update_stats()
    
            # 3. Mantener actualizados los badges del Sidebar
            self.update_sidebar_badges()
        except Exception as e:
            # Si ocurre algún TclError porque se está destruyendo la interfaz, salir silenciosamente
            return
            
        # Re-programar en 1 segundo
        try:
            self.update_loop_id = self.after(1000, self.update_loop)
        except:
            pass

    def on_log_received_handler(self, service_id, text):
        """Fired whenever a service writes output. Lo redirige al WorkspaceView."""
        # Se redirige directamente al workspace_view, que comprobará si ese panel está en pantalla
        self.workspace_view.append_log_to_service(service_id, text)

    def on_closing(self):
        """Muestra una ventana de confirmación al cerrar la aplicación, listando los servicios activos."""
        active_services = [s.name for s in self.manager.services.values() if s.status in ["running", "starting"]]
        
        if active_services:
            services_list = "\n".join(f"• {name}" for name in active_services)
            msg = (
                f"Hay servicios activos en ejecución que se detendrán al salir:\n\n"
                f"{services_list}\n\n"
                f"¿Estás seguro de que deseas cerrar la aplicación?"
            )
        else:
            msg = "¿Estás seguro de que deseas salir de Central Terminal?"
            
        if messagebox.askyesno("Confirmar salida", msg):
            self.destroy()

    def destroy(self):
        # Cancelar loop de actualizaciones antes de destruir
        if hasattr(self, "update_loop_id") and self.update_loop_id:
            try:
                self.after_cancel(self.update_loop_id)
            except:
                pass
        self.manager.shutdown()
        super().destroy()
        sys.exit(0)
