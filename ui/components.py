import os
import sys
import tkinter as tk
import customtkinter as ctk


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base_path, relative_path)


def asset_path(*parts):
    return resource_path(os.path.join("assets", *parts))


def apply_app_icon(window):
    icon_path = asset_path("central_terminal.ico")
    if not os.path.exists(icon_path):
        return

    try:
        window.iconbitmap(icon_path)
    except Exception:
        pass

class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        self.id = None
        
        # Vincular eventos de cursor
        self.widget.bind("<Enter>", self.enter)
        self.widget.bind("<Leave>", self.leave)

    def enter(self, event=None):
        self.schedule()

    def leave(self, event=None):
        self.unschedule()
        self.hide()

    def schedule(self):
        self.unschedule()
        # Espera 350ms antes de mostrar para evitar molestar si pasa rápido el mouse
        self.id = self.widget.after(350, self.show)

    def unschedule(self):
        if self.id:
            self.widget.after_cancel(self.id)
            self.id = None

    def show(self):
        if not self.text:
            return
        
        # Calcular posición inicial (abajo y centrado horizontalmente al botón)
        x = self.widget.winfo_rootx() + (self.widget.winfo_width() // 2)
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        
        # Contenedor con borde para efecto moderno
        from ui.theme import BORDER_COLOR, BG_CARD, TERMINAL_FG
        border_frame = tk.Frame(tw, background=BORDER_COLOR, bd=1)
        border_frame.pack()
        
        # Etiqueta con el texto del tooltip
        label = tk.Label(
            border_frame, text=self.text, justify='left',
            background=BG_CARD, foreground=TERMINAL_FG,
            font=("Segoe UI", 11), relief="flat",
            padx=10, pady=6
        )
        label.pack()
        
        # Ajustar posición centrada tras render
        tw.update_idletasks()
        tw_width = tw.winfo_width()
        x = x - (tw_width // 2)
        tw.wm_geometry(f"+{x}+{y}")

    def update_text(self, new_text):
        """Permite cambiar el texto del tooltip dinámicamente."""
        self.text = new_text

    def hide(self):
        tw = self.tip_window
        self.tip_window = None
        if tw:
            tw.destroy()
