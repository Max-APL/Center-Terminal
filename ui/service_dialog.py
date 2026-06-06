import customtkinter as ctk
from tkinter import filedialog
import os
import uuid
from ui.theme import *

class ServiceDialog(ctk.CTkToplevel):
    def __init__(self, parent, service_config=None, on_save=None):
        super().__init__(parent)
        
        self.parent = parent
        self.service_config = service_config or {}
        self.on_save = on_save
        self.is_edit = bool(service_config)

        # Configuración de ventana modal
        self.title("Editar Servicio" if self.is_edit else "Añadir Servicio")
        self.geometry("520x570")
        self.resizable(False, False)
        self.configure(fg_color=BG_CARD)
        
        # Estilo transitorio y modal en Windows
        self.transient(parent)
        self.grab_set()
        self.focus_force()

        # Centrar la ventana respecto al padre
        self.update_idletasks()
        parent_x = parent.winfo_x()
        parent_y = parent.winfo_y()
        parent_width = parent.winfo_width()
        parent_height = parent.winfo_height()
        
        x = parent_x + (parent_width // 2) - (520 // 2)
        y = parent_y + (parent_height // 2) - (570 // 2)
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

        self.create_widgets()

    def create_widgets(self):
        # Título
        title_text = "Editar Configuración" if self.is_edit else "Nuevo Servicio"
        title_label = ctk.CTkLabel(
            self, text=title_text, 
            font=FONT_TITLE, text_color=COLOR_PRIMARY
        )
        title_label.pack(pady=(15, 10), padx=20, anchor="w")

        # Contenedor de formulario
        form_frame = ctk.CTkFrame(self, fg_color="transparent")
        form_frame.pack(fill="both", expand=True, padx=20, pady=0)

        # 1. Nombre del Servicio
        ctk.CTkLabel(form_frame, text="Nombre del Servicio:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.name_entry = ctk.CTkEntry(
            form_frame, placeholder_text="Ej: Frontend App", 
            width=480, height=32, fg_color=BG_MAIN, border_color=BORDER_COLOR
        )
        self.name_entry.pack(anchor="w", pady=(0, 8))
        if self.is_edit:
            self.name_entry.insert(0, self.service_config.get("name", ""))

        # 2. Comando de Pre-inicio (opcional)
        ctk.CTkLabel(form_frame, text="Comando de Pre-inicio (opcional):", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.pre_command_entry = ctk.CTkEntry(
            form_frame, placeholder_text="Ej: npm run build  o  pip install -r requirements.txt", 
            width=480, height=32, fg_color=BG_MAIN, border_color=BORDER_COLOR
        )
        self.pre_command_entry.pack(anchor="w", pady=(0, 8))
        if self.is_edit:
            self.pre_command_entry.insert(0, self.service_config.get("pre_command", ""))

        # 3. Comando Principal
        ctk.CTkLabel(form_frame, text="Comando Principal a ejecutar:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.command_entry = ctk.CTkEntry(
            form_frame, placeholder_text="Ej: npm run dev  o  python app.py", 
            width=480, height=32, fg_color=BG_MAIN, border_color=BORDER_COLOR
        )
        self.command_entry.pack(anchor="w", pady=(0, 8))
        if self.is_edit:
            self.command_entry.insert(0, self.service_config.get("command", ""))

        # 4. Directorio de Trabajo (CWD)
        ctk.CTkLabel(form_frame, text="Directorio de Trabajo (CWD):", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        cwd_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        cwd_frame.pack(fill="x", pady=(0, 8))
        
        self.cwd_entry = ctk.CTkEntry(
            cwd_frame, placeholder_text="Ej: C:\\Projects\\MyWebApp", 
            height=32, fg_color=BG_MAIN, border_color=BORDER_COLOR
        )
        self.cwd_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        if self.is_edit:
            self.cwd_entry.insert(0, self.service_config.get("cwd", ""))

        btn_browse = ctk.CTkButton(
            cwd_frame, text="Buscar...", width=80, height=32,
            fg_color=BORDER_COLOR, hover_color=BG_CARD_HOVER, text_color="white",
            command=self.browse_directory
        )
        btn_browse.pack(side="right")

        # 5. Intérprete / Shell
        ctk.CTkLabel(form_frame, text="Intérprete / Shell:", font=FONT_BODY, text_color="white").pack(anchor="w", pady=(3, 1))
        self.shell_var = ctk.StringVar(value="Default (CMD)")
        self.shell_menu = ctk.CTkOptionMenu(
            form_frame, values=["Default (CMD)", "PowerShell 7 (pwsh)", "Windows PowerShell (powershell)", "CMD", "Git Bash"],
            variable=self.shell_var, width=480, height=32,
            fg_color=BG_MAIN, button_color=BORDER_COLOR, button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD, dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white", text_color="white"
        )
        self.shell_menu.pack(anchor="w", pady=(0, 8))
        if self.is_edit:
            shell_val = self.service_config.get("shell", "default")
            shell_map_inv = {
                "default": "Default (CMD)",
                "pwsh": "PowerShell 7 (pwsh)",
                "powershell": "Windows PowerShell (powershell)",
                "cmd": "CMD",
                "bash": "Git Bash"
            }
            self.shell_var.set(shell_map_inv.get(shell_val, "Default (CMD)"))

        # 6. Ajustes extras (Auto-restart, etc.)
        settings_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        settings_frame.pack(fill="x", pady=(3, 3))

        # Checkbox Auto-restart
        self.auto_restart_var = ctk.BooleanVar(value=self.service_config.get("auto_restart", False))
        self.chk_restart = ctk.CTkCheckBox(
            settings_frame, text="Reinicio Automático", font=FONT_BODY,
            variable=self.auto_restart_var, text_color="white",
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY,
            command=self.toggle_restart_delay
        )
        self.chk_restart.pack(side="left")

        # Delay del reinicio
        self.delay_frame = ctk.CTkFrame(settings_frame, fg_color="transparent")
        self.delay_frame.pack(side="right")
        
        ctk.CTkLabel(self.delay_frame, text="Espera (s):", font=FONT_BODY, text_color="white").pack(side="left", padx=(0, 5))
        self.delay_entry = ctk.CTkEntry(
            self.delay_frame, width=50, height=28, 
            fg_color=BG_MAIN, border_color=BORDER_COLOR, justify="center"
        )
        self.delay_entry.pack(side="left")
        self.delay_entry.insert(0, str(self.service_config.get("restart_delay", 2)))

        self.toggle_restart_delay()

        # Checkbox Consola Nativa Externa
        native_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        native_frame.pack(fill="x", pady=(3, 8))

        self.shell_native_var = ctk.BooleanVar(value=self.service_config.get("shell_native", False))
        self.chk_native = ctk.CTkCheckBox(
            native_frame, text="Ejecutar en Consola Nativa Externa (nueva ventana)", font=FONT_BODY,
            variable=self.shell_native_var, text_color="white",
            fg_color=COLOR_PRIMARY, hover_color=COLOR_PRIMARY
        )
        self.chk_native.pack(side="left")

        # Separador / Espacio
        ctk.CTkFrame(form_frame, height=2, fg_color=BORDER_COLOR).pack(fill="x", pady=10)

        # Botones inferiores (Guardar / Cancelar)
        button_frame = ctk.CTkFrame(form_frame, fg_color="transparent")
        button_frame.pack(fill="x", pady=(0, 8))

        btn_cancel = ctk.CTkButton(
            button_frame, text="Cancelar", height=34,
            fg_color="transparent", border_width=1, border_color=BORDER_COLOR,
            text_color="white", hover_color=BG_CARD_HOVER,
            command=self.destroy
        )
        btn_cancel.pack(side="left", fill="x", expand=True, padx=(0, 10))

        btn_save = ctk.CTkButton(
            button_frame, text="Guardar", height=34,
            fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white",
            command=self.save
        )
        btn_save.pack(side="right", fill="x", expand=True)

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

    def save(self):
        name = self.name_entry.get().strip()
        pre_command = self.pre_command_entry.get().strip()
        command = self.command_entry.get().strip()
        cwd = self.cwd_entry.get().strip()

        # Validación simple
        if not name:
            self.name_entry.configure(border_color=COLOR_DANGER)
            return
        self.name_entry.configure(border_color=BORDER_COLOR)

        if not command:
            self.command_entry.configure(border_color=COLOR_DANGER)
            return
        self.command_entry.configure(border_color=BORDER_COLOR)

        # Sanitizar delay
        try:
            delay = int(self.delay_entry.get())
            if delay < 1:
                delay = 1
        except ValueError:
            delay = 2

        # Mapear intérprete
        shell_map = {
            "Default (CMD)": "default",
            "PowerShell 7 (pwsh)": "pwsh",
            "Windows PowerShell (powershell)": "powershell",
            "CMD": "cmd",
            "Git Bash": "bash"
        }
        shell_type = shell_map.get(self.shell_var.get(), "default")

        new_config = {
            "id": self.service_config.get("id", str(uuid.uuid4())),
            "name": name,
            "pre_command": pre_command,
            "command": command,
            "cwd": cwd,
            "shell": shell_type,
            "shell_native": self.shell_native_var.get(),
            "auto_restart": self.auto_restart_var.get(),
            "restart_delay": delay,
            "env": self.service_config.get("env", {})
        }

        if self.on_save:
            self.on_save(new_config)

        self.destroy()
