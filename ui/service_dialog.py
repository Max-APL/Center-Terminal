import copy
import os
import uuid
import customtkinter as ctk
from tkinter import filedialog

from deploy_profiles import (
    DEFAULT_PROFILE_NAME,
    legacy_fields_from_profile,
    new_profile,
    new_step,
    normalize_service_profiles,
    serialize_profiles,
)
from shell_profiles import get_shell_options, shell_id_from_label, shell_label_from_id
from ui.components import apply_app_icon
from ui.theme import *


class ServiceDialog(ctk.CTkToplevel):
    def __init__(self, parent, service_config=None, on_save=None):
        super().__init__(parent)

        self.parent = parent
        self.service_config = service_config or {}
        self.on_save = on_save
        self.is_edit = bool(service_config)
        self.shell_options = get_shell_options(include_default=True)
        self.deploy_profiles, self.default_deploy_profile_id = normalize_service_profiles(
            self.service_config,
            keep_empty_steps=True,
        )
        self.current_profile_index = 0
        self.step_rows = []

        self.title("Editar Servicio" if self.is_edit else "Añadir Servicio")
        apply_app_icon(self)
        self.geometry("760x760")
        self.minsize(720, 680)
        self.configure(fg_color=BG_CARD)

        self.transient(parent)
        self.grab_set()
        self.focus_force()

        self.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        x = parent_x + (parent_width // 2) - (760 // 2)
        y = parent_y + (parent_height // 2) - (760 // 2)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        self.create_widgets()
        self.load_profile(0)

    def create_widgets(self):
        title_text = "Editar Configuración" if self.is_edit else "Nuevo Servicio"
        title_label = ctk.CTkLabel(self, text=title_text, font=FONT_TITLE, text_color=COLOR_PRIMARY)
        title_label.pack(pady=(15, 8), padx=20, anchor="w")

        form_frame = ctk.CTkScrollableFrame(self, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=20, pady=(0, 8))

        ctk.CTkLabel(form_frame, text="Nombre del Servicio:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.name_entry = ctk.CTkEntry(
            form_frame,
            placeholder_text="Ej: Frontend App",
            height=32,
            fg_color=BG_MAIN,
            border_color=BORDER_COLOR,
        )
        self.name_entry.pack(fill="x", pady=(0, 8))
        self.name_entry.insert(0, self.service_config.get("name", ""))

        ctk.CTkLabel(form_frame, text="Directorio de Trabajo (CWD):", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        cwd_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        cwd_frame.pack(fill="x", pady=(0, 10))

        self.cwd_entry = ctk.CTkEntry(
            cwd_frame,
            placeholder_text="Ej: C:\\Projects\\MyWebApp",
            height=32,
            fg_color=BG_MAIN,
            border_color=BORDER_COLOR,
        )
        self.cwd_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.cwd_entry.insert(0, self.service_config.get("cwd", ""))

        btn_browse = ctk.CTkButton(
            cwd_frame,
            text="Buscar...",
            width=90,
            height=32,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            text_color="white",
            command=self.browse_directory,
        )
        btn_browse.pack(side="right")

        self.profile_frame = ctk.CTkFrame(form_frame, fg_color=BG_MAIN, border_width=1, border_color=BORDER_COLOR, corner_radius=8)
        self.profile_frame.pack(fill="x", pady=(4, 10))

        profile_header = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        profile_header.pack(fill="x", padx=12, pady=(12, 8))

        ctk.CTkLabel(profile_header, text="Flujos de Deploy", font=FONT_SUBTITLE, text_color="white").pack(side="left")

        self.btn_add_profile = ctk.CTkButton(
            profile_header,
            text="+",
            width=28,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color="#059669",
            command=self.add_profile,
        )
        self.btn_add_profile.pack(side="right", padx=(4, 0))

        self.btn_duplicate_profile = ctk.CTkButton(
            profile_header,
            text="⧉",
            width=28,
            height=28,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            command=self.duplicate_profile,
        )
        self.btn_duplicate_profile.pack(side="right", padx=(4, 0))

        self.btn_delete_profile = ctk.CTkButton(
            profile_header,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            border_width=1,
            border_color=COLOR_DANGER,
            text_color=COLOR_DANGER,
            hover_color="#450a0a",
            command=self.delete_profile,
        )
        self.btn_delete_profile.pack(side="right", padx=(4, 0))

        profile_select_row = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        profile_select_row.pack(fill="x", padx=12, pady=(0, 8))

        self.profile_var = ctk.StringVar(value="")
        self.profile_menu = ctk.CTkOptionMenu(
            profile_select_row,
            values=self.profile_labels(),
            variable=self.profile_var,
            height=32,
            fg_color=BG_CARD,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white",
            command=self.change_profile,
        )
        self.profile_menu.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.btn_default_profile = ctk.CTkButton(
            profile_select_row,
            text="Predeterminado",
            width=130,
            height=32,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            text_color="white",
            command=self.set_current_as_default,
        )
        self.btn_default_profile.pack(side="right")

        profile_name_row = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        profile_name_row.pack(fill="x", padx=12, pady=(0, 8))

        self.profile_name_entry = ctk.CTkEntry(
            profile_name_row,
            placeholder_text="Nombre del flujo",
            height=32,
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
        )
        self.profile_name_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))

        shell_labels = [label for label, _ in self.shell_options]
        self.shell_var = ctk.StringVar(value=shell_labels[0] if shell_labels else "")
        self.shell_menu = ctk.CTkOptionMenu(
            profile_name_row,
            values=shell_labels,
            variable=self.shell_var,
            width=210,
            height=32,
            fg_color=BG_CARD,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white",
        )
        self.shell_menu.pack(side="right")

        steps_header = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        steps_header.pack(fill="x", padx=12, pady=(4, 6))
        ctk.CTkLabel(steps_header, text="Pasos", font=FONT_BODY, text_color="white").pack(side="left")
        self.btn_add_step = ctk.CTkButton(
            steps_header,
            text="+ Añadir Paso",
            width=110,
            height=28,
            fg_color=COLOR_PRIMARY,
            hover_color="#059669",
            command=self.add_step,
        )
        self.btn_add_step.pack(side="right")

        self.steps_container = ctk.CTkFrame(self.profile_frame, fg_color="transparent")
        self.steps_container.pack(fill="x", padx=12, pady=(0, 12))

        settings_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        settings_frame.pack(fill="x", pady=(4, 10))

        self.auto_restart_var = ctk.BooleanVar(value=self.service_config.get("auto_restart", False))
        self.chk_restart = ctk.CTkCheckBox(
            settings_frame,
            text="Reinicio Automático",
            font=FONT_BODY,
            variable=self.auto_restart_var,
            text_color="white",
            fg_color=COLOR_PRIMARY,
            hover_color=COLOR_PRIMARY,
            command=self.toggle_restart_delay,
        )
        self.chk_restart.pack(side="left")

        self.delay_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        self.delay_frame.pack(side="right")
        ctk.CTkLabel(self.delay_frame, text="Espera (s):", font=FONT_BODY, text_color="white").pack(side="left", padx=(0, 5))
        self.delay_entry = ctk.CTkEntry(
            self.delay_frame,
            width=60,
            height=28,
            fg_color=BG_MAIN,
            border_color=BORDER_COLOR,
            justify="center",
        )
        self.delay_entry.pack(side="left")
        self.delay_entry.insert(0, str(self.service_config.get("restart_delay", 2)))
        self.toggle_restart_delay()

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

    def profile_labels(self):
        return [self.profile_label(profile) for profile in self.deploy_profiles]

    def profile_label(self, profile):
        label = profile.get("name") or DEFAULT_PROFILE_NAME
        if profile.get("id") == self.default_deploy_profile_id:
            return f"{label} *"
        return label

    def refresh_profile_menu(self):
        labels = self.profile_labels()
        self.profile_menu.configure(values=labels)
        self.profile_var.set(labels[self.current_profile_index])

    def current_profile(self):
        return self.deploy_profiles[self.current_profile_index]

    def load_profile(self, index):
        self.current_profile_index = max(0, min(index, len(self.deploy_profiles) - 1))
        profile = self.current_profile()

        self.refresh_profile_menu()
        self.profile_name_entry.delete(0, "end")
        self.profile_name_entry.insert(0, profile.get("name", DEFAULT_PROFILE_NAME))

        selected_shell_label = shell_label_from_id(profile.get("shell", "default"), include_default=True)
        shell_labels = [label for label, _ in self.shell_options]
        if selected_shell_label not in shell_labels and shell_labels:
            selected_shell_label = shell_labels[0]
        self.shell_var.set(selected_shell_label)

        self.render_steps()
        self.update_default_button()

    def sync_current_profile(self):
        if not self.deploy_profiles:
            return

        profile = self.current_profile()
        name = self.profile_name_entry.get().strip() or DEFAULT_PROFILE_NAME
        profile["name"] = name
        profile["shell"] = shell_id_from_label(self.shell_var.get(), include_default=True)

        steps = []
        for index, row in enumerate(self.step_rows):
            command = row["entry"].get().strip()
            step = row["step"]
            step["command"] = command
            step["name"] = "Comando final" if index == len(self.step_rows) - 1 else f"Paso {index + 1}"
            steps.append(step)
        profile["steps"] = steps

    def change_profile(self, selected_label):
        self.sync_current_profile()
        clean_label = selected_label.rstrip(" *")
        for index, profile in enumerate(self.deploy_profiles):
            if profile.get("name") == clean_label or self.profile_label(profile) == selected_label:
                self.load_profile(index)
                return

    def update_default_button(self):
        is_default = self.current_profile().get("id") == self.default_deploy_profile_id
        color = COLOR_PRIMARY if is_default else BORDER_COLOR
        self.btn_default_profile.configure(fg_color=color)

    def set_current_as_default(self):
        self.sync_current_profile()
        self.default_deploy_profile_id = self.current_profile().get("id")
        self.refresh_profile_menu()
        self.update_default_button()

    def add_profile(self):
        self.sync_current_profile()
        shell_type = shell_id_from_label(self.shell_var.get(), include_default=True)
        profile = new_profile(
            name=f"Flujo {len(self.deploy_profiles) + 1}",
            shell=shell_type,
            steps=[new_step("", "Paso previo"), new_step("", "Comando final")],
        )
        self.deploy_profiles.append(profile)
        self.load_profile(len(self.deploy_profiles) - 1)

    def duplicate_profile(self):
        self.sync_current_profile()
        profile = copy.deepcopy(self.current_profile())
        profile["id"] = str(uuid.uuid4())
        profile["name"] = f"{profile.get('name', DEFAULT_PROFILE_NAME)} copia"
        for step in profile.get("steps", []):
            step["id"] = str(uuid.uuid4())
        self.deploy_profiles.append(profile)
        self.load_profile(len(self.deploy_profiles) - 1)

    def delete_profile(self):
        if len(self.deploy_profiles) <= 1:
            return
        profile = self.current_profile()
        removed_id = profile.get("id")
        del self.deploy_profiles[self.current_profile_index]
        if self.default_deploy_profile_id == removed_id:
            self.default_deploy_profile_id = self.deploy_profiles[0].get("id")
        self.load_profile(min(self.current_profile_index, len(self.deploy_profiles) - 1))

    def render_steps(self):
        for row in self.step_rows:
            row["frame"].destroy()
        self.step_rows.clear()

        profile = self.current_profile()
        steps = profile.get("steps") or [new_step("", "Comando final")]
        profile["steps"] = steps

        for index, step in enumerate(steps):
            self.add_step_row(step, index)

    def add_step_row(self, step, index):
        frame = ctk.CTkFrame(self.steps_container, fg_color="transparent")
        frame.pack(fill="x", pady=3)

        step_label = "Final" if index == len(self.current_profile().get("steps", [])) - 1 else str(index + 1)
        ctk.CTkLabel(frame, text=step_label, width=42, font=FONT_MUTED, text_color=COLOR_MUTED).pack(side="left")

        entry = ctk.CTkEntry(
            frame,
            placeholder_text="Comando",
            height=32,
            fg_color=BG_CARD,
            border_color=BORDER_COLOR,
        )
        entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        entry.insert(0, step.get("command", ""))

        btn_up = ctk.CTkButton(
            frame,
            text="↑",
            width=28,
            height=28,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            command=lambda s=step: self.move_step(s, -1),
        )
        btn_up.pack(side="left", padx=2)

        btn_down = ctk.CTkButton(
            frame,
            text="↓",
            width=28,
            height=28,
            fg_color=BORDER_COLOR,
            hover_color=BG_CARD_HOVER,
            command=lambda s=step: self.move_step(s, 1),
        )
        btn_down.pack(side="left", padx=2)

        btn_delete = ctk.CTkButton(
            frame,
            text="✕",
            width=28,
            height=28,
            fg_color="transparent",
            border_width=1,
            border_color=BORDER_COLOR,
            text_color=COLOR_MUTED,
            hover_color=COLOR_DANGER,
            command=lambda s=step: self.delete_step(s),
        )
        btn_delete.pack(side="left", padx=2)

        self.step_rows.append({"frame": frame, "entry": entry, "step": step})

    def add_step(self):
        self.sync_current_profile()
        self.current_profile().setdefault("steps", []).append(new_step("", "Comando final"))
        self.render_steps()

    def move_step(self, step, delta):
        self.sync_current_profile()
        steps = self.current_profile().get("steps", [])
        index = next((i for i, item in enumerate(steps) if item.get("id") == step.get("id")), -1)
        new_index = index + delta
        if index < 0 or new_index < 0 or new_index >= len(steps):
            return
        steps[index], steps[new_index] = steps[new_index], steps[index]
        self.render_steps()

    def delete_step(self, step):
        self.sync_current_profile()
        steps = self.current_profile().get("steps", [])
        if len(steps) <= 1:
            return
        self.current_profile()["steps"] = [item for item in steps if item.get("id") != step.get("id")]
        self.render_steps()

    def browse_directory(self):
        initial_dir = self.cwd_entry.get()
        if not initial_dir or not os.path.exists(initial_dir):
            initial_dir = os.path.expanduser("~")

        dir_selected = filedialog.askdirectory(parent=self, initialdir=initial_dir, title="Seleccionar Carpeta de Proyecto")
        if dir_selected:
            self.cwd_entry.delete(0, "end")
            self.cwd_entry.insert(0, os.path.normpath(dir_selected))

    def toggle_restart_delay(self):
        if self.auto_restart_var.get():
            self.delay_entry.configure(state="normal", text_color="white")
        else:
            self.delay_entry.configure(state="disabled", text_color=COLOR_MUTED)

    def validate_profiles(self, profiles):
        for profile in profiles:
            if not (profile.get("name") or "").strip():
                return False
            if not any((step.get("command") or "").strip() for step in profile.get("steps", [])):
                return False
        return True

    def save(self):
        self.sync_current_profile()

        name = self.name_entry.get().strip()
        cwd = self.cwd_entry.get().strip()
        if not name:
            self.name_entry.configure(border_color=COLOR_DANGER)
            return
        self.name_entry.configure(border_color=BORDER_COLOR)

        profiles = serialize_profiles(self.deploy_profiles)
        if not self.validate_profiles(profiles):
            self.profile_frame.configure(border_color=COLOR_DANGER)
            return
        self.profile_frame.configure(border_color=BORDER_COLOR)

        if self.default_deploy_profile_id not in {profile["id"] for profile in profiles}:
            self.default_deploy_profile_id = profiles[0]["id"]

        default_profile = next((profile for profile in profiles if profile["id"] == self.default_deploy_profile_id), profiles[0])
        pre_command, command = legacy_fields_from_profile(default_profile)

        try:
            delay = int(self.delay_entry.get())
            if delay < 1:
                delay = 1
        except ValueError:
            delay = 2

        new_config = {
            "id": self.service_config.get("id", str(uuid.uuid4())),
            "name": name,
            "pre_command": pre_command,
            "command": command,
            "cwd": cwd,
            "shell": default_profile.get("shell"),
            "shell_native": False,
            "auto_restart": self.auto_restart_var.get(),
            "restart_delay": delay,
            "env": self.service_config.get("env", {}),
            "deploy_profiles": profiles,
            "default_deploy_profile_id": self.default_deploy_profile_id,
        }

        if self.on_save:
            self.on_save(new_config)

        self.destroy()
