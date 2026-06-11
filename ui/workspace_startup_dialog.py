import customtkinter as ctk

from workspace_startups import DEFAULT_STARTUP_ID
from ui.components import apply_app_icon
from ui.theme import *


class WorkspaceStartupDialog(ctk.CTkToplevel):
    def __init__(self, parent, manager, workspace_id, startup_config=None, on_save=None):
        super().__init__(parent)

        self.parent = parent
        self.manager = manager
        self.workspace_id = workspace_id
        self.startup_config = startup_config or {}
        self.on_save = on_save
        self.service_rows = []

        self.is_edit = bool(self.startup_config.get("id"))

        self.title("Editar Inicio" if self.is_edit else "Nuevo Inicio")
        apply_app_icon(self)
        self.geometry("620x560")
        self.minsize(560, 460)
        self.configure(fg_color=BG_CARD)
        self.transient(parent)
        self.grab_set()
        self.focus_force()

        self.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + (parent_width // 2) - (620 // 2)
        y = parent_y + (parent_height // 2) - (560 // 2)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        self.create_widgets()

    def create_widgets(self):
        title = "Editar Inicio del Workspace" if self.is_edit else "Nuevo Inicio del Workspace"
        ctk.CTkLabel(self, text=title, font=FONT_TITLE, text_color=COLOR_PRIMARY).pack(padx=20, pady=(15, 8), anchor="w")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=20, pady=(0, 10))

        ctk.CTkLabel(body, text="Nombre del inicio:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.name_entry = ctk.CTkEntry(
            body,
            placeholder_text="Ej: Inicio de construcción",
            height=32,
            fg_color=BG_MAIN,
            border_color=BORDER_COLOR,
        )
        self.name_entry.pack(fill="x", pady=(0, 12))
        self.name_entry.insert(0, self.startup_config.get("name", ""))

        ctk.CTkLabel(body, text="Flujo seleccionado por servicio:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 6))

        rows_container = ctk.CTkScrollableFrame(body, fg_color=BG_MAIN, border_width=1, border_color=BORDER_COLOR, corner_radius=8)
        rows_container.pack(fill="both", expand=True, pady=(0, 12))

        mapping = self.startup_config.get("service_profiles") or {}
        for service in self.manager.workspace_services.get(self.workspace_id, []):
            row = ctk.CTkFrame(rows_container, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=6)

            ctk.CTkLabel(
                row,
                text=service.name,
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color="white",
                width=170,
                anchor="w",
            ).pack(side="left", padx=(0, 8))

            profile_options = service.get_deploy_profile_options()
            labels = [label for label, _ in profile_options] or ["Predeterminado"]
            selected_id = mapping.get(service.id, service.selected_deploy_profile_id)
            selected_label = next((label for label, profile_id in profile_options if profile_id == selected_id), None)
            if not selected_label:
                selected_label = service.get_selected_deploy_profile_label()
            if selected_label not in labels:
                selected_label = labels[0]

            var = ctk.StringVar(value=selected_label)
            menu = ctk.CTkOptionMenu(
                row,
                values=labels,
                variable=var,
                height=30,
                fg_color=BG_CARD,
                button_color=BORDER_COLOR,
                button_hover_color=BG_CARD_HOVER,
                dropdown_fg_color=BG_CARD,
                dropdown_hover_color=BG_CARD_HOVER,
                dropdown_text_color="white",
                text_color="white",
            )
            menu.pack(side="left", fill="x", expand=True)
            self.service_rows.append({"service": service, "var": var})

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.pack(fill="x", padx=20, pady=(0, 15))

        btn_cancel = ctk.CTkButton(
            button_frame,
            text="Cancelar",
            height=34,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color="white",
            hover_color=BG_CARD_HOVER,
            command=self.destroy,
        )
        btn_cancel.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_save = ctk.CTkButton(
            button_frame,
            text="Guardar",
            height=34,
            fg_color=COLOR_PRIMARY,
            hover_color="#059669",
            text_color="white",
            command=self.save,
        )
        btn_save.pack(side="right", fill="x", expand=True)

    def save(self):
        name = self.name_entry.get().strip()
        if not name:
            self.name_entry.configure(border_color=COLOR_DANGER)
            return

        service_profiles = {}
        for row in self.service_rows:
            service = row["service"]
            profile_id = service.get_profile_id_from_label(row["var"].get())
            if profile_id:
                service_profiles[service.id] = profile_id

        config = {
            "id": self.startup_config.get("id") if self.startup_config.get("id") != DEFAULT_STARTUP_ID else None,
            "name": name,
            "service_profiles": service_profiles,
        }

        if self.on_save:
            self.on_save(config)

        self.destroy()
