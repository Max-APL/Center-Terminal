import os
import sys
import subprocess
import threading
import time
import math
import queue
import ctypes
import customtkinter as ctk
from ui.theme import *
from ui.components import ToolTip
from shell_profiles import (
    get_default_shell_id,
    get_shell_options,
    get_shell_profile,
    shell_id_from_label,
    shell_label_from_id,
)

# Prototipos de la API de Windows (Ctypes)
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Configurar firmas de funciones para evitar truncamientos de handles en Windows de 64 bits
user32.GetForegroundWindow.argtypes = []
user32.GetForegroundWindow.restype = ctypes.c_void_p

user32.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
user32.GetWindowThreadProcessId.restype = ctypes.c_ulong

user32.AttachThreadInput.argtypes = [ctypes.c_ulong, ctypes.c_ulong, ctypes.c_bool]
user32.AttachThreadInput.restype = ctypes.c_bool

user32.SetFocus.argtypes = [ctypes.c_void_p]
user32.SetFocus.restype = ctypes.c_void_p

user32.GetFocus.argtypes = []
user32.GetFocus.restype = ctypes.c_void_p

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = ctypes.c_bool

user32.WindowFromPoint.argtypes = [POINT]
user32.WindowFromPoint.restype = ctypes.c_void_p

user32.GetGUIThreadInfo.argtypes = [ctypes.c_ulong, ctypes.c_void_p]
user32.GetGUIThreadInfo.restype = ctypes.c_bool

user32.IsChild.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.IsChild.restype = ctypes.c_bool

user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.SetParent.restype = ctypes.c_void_p

user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool

user32.UpdateWindow.argtypes = [ctypes.c_void_p]
user32.UpdateWindow.restype = ctypes.c_bool

user32.MoveWindow.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
user32.MoveWindow.restype = ctypes.c_bool

user32.GetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long

user32.SetWindowLongW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long

user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint]
user32.SetWindowPos.restype = ctypes.c_bool

kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = ctypes.c_ulong

kernel32.GetCurrentProcessId.argtypes = []
kernel32.GetCurrentProcessId.restype = ctypes.c_ulong

GWL_STYLE = -16
WS_CHILD = 0x40000000
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000
WS_MINIMIZEBOX = 0x00020000
WS_MAXIMIZEBOX = 0x00010000
WS_BORDER = 0x00800000
WS_CLIPCHILDREN = 0x02000000

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.c_ulong * 4) # RECT (16 bytes)
    ]

class QuickTerminalPanel(ctk.CTkFrame):
    def __init__(self, parent, shell_type, terminal_id, on_close):
        super().__init__(parent, fg_color=BG_CARD, border_width=2, border_color=BORDER_COLOR, corner_radius=12)
        self.shell_type = shell_type
        self.terminal_id = terminal_id
        self.on_close = on_close
        self.shell_options = get_shell_options(include_default=False)
        
        self.active = False
        self.process = None
        self.child_hwnd = None
        self.console_container = None
        self.terminal_name = f"Terminal {self.terminal_id}"
        self.entry_rename = None
        
        self.create_widgets()
        
        # Registrar evento de mapeado
        self.bind("<Map>", self.on_map)
        
    def create_widgets(self):
        # 1. Cabecera (Header)
        self.header = ctk.CTkFrame(self, fg_color="transparent", height=35)
        self.header.pack(fill="x", padx=10, pady=(8, 4))
        self.header.pack_propagate(False)
        
        # Contenedor del título para permitir inline rename
        self.title_container = ctk.CTkFrame(self.header, fg_color="transparent")
        self.title_container.pack(side="left", fill="y")
        
        icon = "🐚"
        self.lbl_title = ctk.CTkLabel(
            self.title_container, text=f"{icon} {self.terminal_name}",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="white",
            cursor="hand2"
        )
        self.lbl_title.pack(side="left", anchor="center")
        
        # Botón lápiz discreto para renombrar
        self.btn_edit_title = ctk.CTkButton(
            self.title_container, text="✏️", width=18, height=18,
            fg_color="transparent", text_color=COLOR_MUTED, hover_color=BG_CARD_HOVER,
            font=ctk.CTkFont(size=10),
            command=self.start_rename
        )
        self.btn_edit_title.pack(side="left", padx=(4, 0), anchor="center")
        self.tip_edit_title = ToolTip(self.btn_edit_title, "Renombrar terminal")
        
        # Binds para doble clic y hover
        self.lbl_title.bind("<Double-Button-1>", lambda e: self.start_rename())
        self.lbl_title.bind("<Enter>", lambda e: self.btn_edit_title.configure(text_color="white"))
        self.lbl_title.bind("<Leave>", lambda e: self.btn_edit_title.configure(text_color=COLOR_MUTED))
        
        # Botón Cerrar (Extremo derecho)
        self.btn_close = ctk.CTkButton(
            self.header, text="✗", width=24, height=24,
            fg_color="transparent", hover_color=COLOR_DANGER, text_color=COLOR_MUTED,
            font=ctk.CTkFont(size=10, weight="bold"),
            command=self.close
        )
        self.btn_close.pack(side="right", padx=2)
        self.btn_close.bind("<Enter>", lambda e: self.btn_close.configure(text_color="white"))
        self.btn_close.bind("<Leave>", lambda e: self.btn_close.configure(text_color=COLOR_MUTED))
        self.tip_close = ToolTip(self.btn_close, "Cerrar terminal")
        
        # Dropdown para elegir/cambiar intérprete independientemente
        shell_labels = [label for label, _ in self.shell_options]
        if not shell_labels:
            self.shell_options = get_shell_options(include_default=True)
            shell_labels = [label for label, _ in self.shell_options]

        shell_val_inv = shell_label_from_id(self.shell_type)
        if shell_val_inv not in shell_labels and shell_labels:
            shell_val_inv = shell_labels[0]
        
        self.shell_var = ctk.StringVar(value=shell_val_inv)
        self.shell_dropdown = ctk.CTkOptionMenu(
            self.header,
            values=shell_labels,
            variable=self.shell_var,
            width=140, height=24,
            fg_color=BG_MAIN,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white",
            font=ctk.CTkFont(size=11),
            command=self.change_shell
        )
        self.shell_dropdown.pack(side="right", padx=10)
        self.tip_shell = ToolTip(self.shell_dropdown, "Cambiar intérprete de esta terminal")

        # 2. Contenedor estándar de Tkinter para la consola nativa (evita conflictos de renderizado con el Canvas de CustomTkinter)
        import tkinter as tk
        self.console_container = tk.Frame(self, bg="#0c0c0c", takefocus=1)
        self.console_container.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        
        # Vincular eventos de redirección de foco y clic
        self.console_container.bind("<Configure>", self.on_resize)
        self.console_container.bind("<FocusIn>", self.focus_child)
        self.console_container.bind("<Button-1>", self.focus_child)
        self.bind("<Button-1>", self.focus_child)
        self.header.bind("<Button-1>", self.focus_child)
        self.title_container.bind("<Button-1>", self.focus_child)
        self.lbl_title.bind("<Button-1>", self.focus_child)

    def focus_child(self, event=None):
        # Si se está renombrando la terminal, no transferir el foco a la consola conhost
        if hasattr(self, "entry_rename") and self.entry_rename is not None:
            return
            
        if self.child_hwnd:
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd:
                current_pid = kernel32.GetCurrentProcessId()
                fg_pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
                # Solo redirigir el foco si nuestra aplicación de Tkinter es la ventana activa en primer plano
                if fg_pid.value == current_pid:
                    try:
                        user32.SetFocus(self.child_hwnd)
                    except Exception as e:
                        pass

    def start_rename(self):
        if self.entry_rename:
            return
            
        # Ocultar temporalmente el título y el lápiz
        self.lbl_title.pack_forget()
        self.btn_edit_title.pack_forget()
        
        # Crear entrada inline
        self.entry_rename = ctk.CTkEntry(
            self.title_container,
            width=140, height=22,
            fg_color=BG_MAIN, border_color=COLOR_PRIMARY,
            text_color="white",
            font=ctk.CTkFont(size=11, weight="bold")
        )
        self.entry_rename.pack(side="left", anchor="center", padx=(2, 0))
        self.entry_rename.insert(0, self.terminal_name)
        
        # Sincronizar foco interno de Tkinter
        self.entry_rename.focus_set()
        self.entry_rename.select_range(0, "end")
        
        # Forzar el foco de teclado del sistema operativo (Win32) hacia el entry de Tkinter
        # para quitarle la entrada de teclado a conhost
        try:
            self.update_idletasks() # Asegurar que el entry tenga un HWND válido asignado
            user32.SetFocus(self.entry_rename._entry.winfo_id())
        except Exception as e:
            pass
        
        # Vincular teclas de confirmación y cancelación
        self.entry_rename.bind("<Return>", lambda e: self.finish_rename(save=True))
        self.entry_rename.bind("<Escape>", lambda e: self.finish_rename(save=False))
        self.entry_rename.bind("<FocusOut>", lambda e: self.finish_rename(save=True))

    def finish_rename(self, save=True):
        if not self.entry_rename:
            return
            
        if save:
            new_name = self.entry_rename.get().strip()
            if new_name:
                self.terminal_name = new_name
                
        try:
            self.entry_rename.destroy()
        except:
            pass
        self.entry_rename = None
        
        # Restaurar widgets del título con el nuevo nombre
        icon = "🐚"
        self.lbl_title.configure(text=f"{icon} {self.terminal_name}")
        self.lbl_title.pack(side="left", anchor="center")
        self.btn_edit_title.pack(side="left", padx=(4, 0), anchor="center")
        
        # Devolver el foco de teclado del sistema operativo (Win32) a la consola conhost
        if self.child_hwnd:
            try:
                user32.SetFocus(self.child_hwnd)
            except:
                pass

    def find_hwnd_by_pid(self, target_pid):
        hwnd_found = [0]
        child_pids = set()
        try:
            import psutil
            parent_proc = psutil.Process(target_pid)
            for child in parent_proc.children(recursive=True):
                child_pids.add(child.pid)
        except:
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
                    return False  # Detener enumeración
            return True  # Continuar

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        callback = WNDENUMPROC(enum_callback)
        user32.EnumWindows(callback, 0)
        return hwnd_found[0]

    def start_shell(self):
        self.active = True
        
        # Arrancar mediante conhost.exe sin alterar el título nativo del proceso
        # para que se aplique la configuración del registro de cada shell (fuentes, colores, etc)
        profile = get_shell_profile(self.shell_type)
        shell_cmd = ["conhost.exe", profile.executable, *profile.args]
            
        try:
            # Configurar para arrancar de forma invisible y evitar robos de foco o parpadeos
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE
            
            self.process = subprocess.Popen(
                shell_cmd,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
                startupinfo=startupinfo
            )
            
            # Buscar el HWND del terminal recién creado por su PID y los PIDs de sus hijos
            hwnd = 0
            for _ in range(60): # Esperar hasta 3 segundos
                hwnd = self.find_hwnd_by_pid(self.process.pid)
                if hwnd:
                    break
                time.sleep(0.05)
                
            if not hwnd:
                sys.stderr.write(f"No se pudo encontrar la ventana de consola para el PID: {self.process.pid}\n")
                return
                
            self.child_hwnd = hwnd
            
            # Obtener el HWND de nuestro propio panel contenedor de Tkinter (console_container)
            parent_hwnd = self.console_container.winfo_id()
            
            # Aplicar WS_CLIPCHILDREN al parent_hwnd para evitar que Tkinter dibuje encima del terminal embebido
            parent_style = user32.GetWindowLongW(parent_hwnd, GWL_STYLE)
            parent_style |= WS_CLIPCHILDREN
            user32.SetWindowLongW(parent_hwnd, GWL_STYLE, parent_style)
            user32.SetWindowPos(parent_hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002) # SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
            
            # Quitar barra de título, bordes y controles de la ventana nativa
            style = user32.GetWindowLongW(self.child_hwnd, GWL_STYLE)
            style &= ~WS_POPUP
            style &= ~WS_CAPTION
            style &= ~WS_THICKFRAME
            style &= ~WS_MINIMIZEBOX
            style &= ~WS_MAXIMIZEBOX
            style &= ~WS_BORDER
            style |= WS_CHILD
            user32.SetWindowLongW(self.child_hwnd, GWL_STYLE, style)
            
            # Emparentar la consola nativa dentro de nuestro Frame contenedor
            user32.SetParent(self.child_hwnd, parent_hwnd)
            
            # Asegurar que sea visible como ventana hija sin activar foco para evitar enviar la app al fondo (Z-order)
            user32.ShowWindow(self.child_hwnd, 8) # SW_SHOWNA
            user32.UpdateWindow(self.child_hwnd)
            
            # Vincular permanentemente las colas de mensajes del hilo Tkinter y conhost
            try:
                child_thread = user32.GetWindowThreadProcessId(self.child_hwnd, None)
                current_thread = kernel32.GetCurrentThreadId()
                if child_thread != current_thread:
                    user32.AttachThreadInput(current_thread, child_thread, True)
            except Exception as e:
                sys.stderr.write(f"Error attaching thread input: {e}\n")

            # Ajustar el tamaño inicial
            self.update_idletasks()
            self.on_resize()
            
        except Exception as e:
            sys.stderr.write(f"Error emparentando consola nativa: {e}\n")

    def change_shell(self, new_shell_value):
        target_shell = shell_id_from_label(new_shell_value)
        if target_shell == self.shell_type:
            return
            
        # 1. Detener el proceso actual y des-emparentar
        self.active = False
        if self.child_hwnd:
            try:
                # Desvincular colas de mensajes antes de des-emparentar
                child_thread = user32.GetWindowThreadProcessId(self.child_hwnd, None)
                current_thread = kernel32.GetCurrentThreadId()
                if child_thread != current_thread:
                    user32.AttachThreadInput(current_thread, child_thread, False)
            except:
                pass
            try:
                user32.SetParent(self.child_hwnd, 0)
            except:
                pass
            self.child_hwnd = None
            
        if self.process:
            try:
                pid = self.process.pid
                self._kill_process_tree(pid)
            except:
                pass
            self.process = None
            
        # 2. Actualizar variables e iniciar el nuevo shell
        self.shell_type = target_shell
        self.start_shell()

    def on_resize(self, event=None):
        if self.child_hwnd and self.console_container:
            w = self.console_container.winfo_width()
            h = self.console_container.winfo_height()
            if w > 1 and h > 1:
                user32.MoveWindow(self.child_hwnd, 0, 0, w, h, True)
                user32.ShowWindow(self.child_hwnd, 8) # SW_SHOWNA
                # Forzar redibujado de marcos
                user32.SetWindowPos(self.child_hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002) # SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
                user32.UpdateWindow(self.child_hwnd)
            else:
                # Si el contenedor aún no tiene dimensiones válidas de Grid, reprogramamos el redimensionado
                if self.winfo_exists():
                    self.resize_after_id = self.after(50, self.on_resize)

    def on_map(self, event=None):
        if self.child_hwnd and self.console_container:
            try:
                parent_hwnd = self.console_container.winfo_id()
                
                # Re-confirmar el estilo de clipping del contenedor padre
                parent_style = user32.GetWindowLongW(parent_hwnd, GWL_STYLE)
                parent_style |= WS_CLIPCHILDREN
                user32.SetWindowLongW(parent_hwnd, GWL_STYLE, parent_style)
                user32.SetWindowPos(parent_hwnd, 0, 0, 0, 0, 0, 0x0020 | 0x0001 | 0x0002) # SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE
                
                user32.SetParent(self.child_hwnd, parent_hwnd)
                user32.ShowWindow(self.child_hwnd, 8) # SW_SHOWNA
                user32.UpdateWindow(self.child_hwnd)
                self.on_resize()
            except Exception as e:
                sys.stderr.write(f"Error re-emparentando consola en on_map: {e}\n")

    def close(self):
        self.active = False
        if self.child_hwnd:
            try:
                # Desvincular colas de mensajes antes de des-emparentar
                child_thread = user32.GetWindowThreadProcessId(self.child_hwnd, None)
                current_thread = kernel32.GetCurrentThreadId()
                if child_thread != current_thread:
                    user32.AttachThreadInput(current_thread, child_thread, False)
            except:
                pass
            try:
                user32.SetParent(self.child_hwnd, 0)
            except:
                pass
            self.child_hwnd = None
            
        if self.process:
            try:
                pid = self.process.pid
                self._kill_process_tree(pid)
            except:
                pass
            self.process = None
            
        if self.on_close:
            self.on_close(self)
            
    def _kill_process_tree(self, parent_pid):
        import psutil
        try:
            parent = psutil.Process(parent_pid)
            children = parent.children(recursive=True)
            
            # Intentar primero una detención controlada/graciosa (SIGTERM)
            for child in children:
                try:
                    child.terminate()
                except:
                    pass
            try:
                parent.terminate()
            except:
                pass
                
            # Esperar brevemente (máximo 1 segundo) a que finalicen limpiamente
            gone, alive = psutil.wait_procs(children + [parent], timeout=1.0)
            
            # Si todavía quedan procesos vivos, forzar su detención inmediata (SIGKILL)
            for p in alive:
                try:
                    p.kill()
                except:
                    pass
        except:
            pass

    def destroy(self):
        if hasattr(self, "resize_after_id") and self.resize_after_id:
            try:
                self.after_cancel(self.resize_after_id)
            except:
                pass
        super().destroy()


class FreeQuickView(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color=BG_MAIN, corner_radius=0)
        self.terminals = []  # list of QuickTerminalPanel
        self.terminal_counter = 0
        self.active_panel = None
        self.shell_options = get_shell_options(include_default=False)
        
        self.create_widgets()
        self.rebuild_grid()
        self.focus_loop()
        
    def create_widgets(self):
        # 1. Cabecera (Header)
        self.header_frame = ctk.CTkFrame(self, fg_color=BG_CARD, height=80, corner_radius=12, border_width=1, border_color=BORDER_COLOR)
        self.header_frame.pack(fill="x", padx=15, pady=(15, 10))
        self.header_frame.pack_propagate(False)
        
        info_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        info_frame.pack(side="left", fill="both", padx=15, pady=8)
        
        lbl_ws_name = ctk.CTkLabel(info_frame, text="Entorno Libre (Dev Sandbox)", font=FONT_TITLE, text_color="white")
        lbl_ws_name.pack(anchor="w")
        
        lbl_ws_stats = ctk.CTkLabel(info_frame, text="Espacio interactivo para realizar pruebas y comandos rápidos sin alterar espacios definidos", font=FONT_MUTED, text_color=COLOR_MUTED)
        lbl_ws_stats.pack(anchor="w", pady=(1, 0))

        # Derecha: Controles
        actions_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        actions_frame.pack(side="right", fill="y", padx=15, pady=12)

        # Dropdown para elegir intérprete predeterminado para nuevas terminales
        shell_labels = [label for label, _ in self.shell_options]
        if not shell_labels:
            self.shell_options = get_shell_options(include_default=True)
            shell_labels = [label for label, _ in self.shell_options]
        default_label = shell_label_from_id(get_default_shell_id())
        if default_label not in shell_labels and shell_labels:
            default_label = shell_labels[0]

        self.shell_var = ctk.StringVar(value=default_label)
        self.shell_dropdown = ctk.CTkOptionMenu(
            actions_frame, 
            values=shell_labels,
            variable=self.shell_var,
            width=150, height=32,
            fg_color=BG_MAIN,
            button_color=BORDER_COLOR,
            button_hover_color=BG_CARD_HOVER,
            dropdown_fg_color=BG_CARD,
            dropdown_hover_color=BG_CARD_HOVER,
            dropdown_text_color="white",
            text_color="white"
        )
        self.shell_dropdown.pack(side="left", padx=5)

        # Botón Añadir Terminal
        self.btn_add = ctk.CTkButton(
            actions_frame, text="+ Nueva Terminal", width=130, height=32,
            fg_color=COLOR_PRIMARY, hover_color="#059669", text_color="white",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.add_terminal
        )
        self.btn_add.pack(side="left", padx=3)
        self.tip_add = ToolTip(self.btn_add, "Agregar una terminal interactiva al sandbox (usando el shell seleccionado)")

        # Botón Limpiar Todo
        self.btn_clear_all = ctk.CTkButton(
            actions_frame, text="🗑 Limpiar Todo", width=110, height=32,
            fg_color="transparent", border_width=1, border_color=COLOR_DANGER,
            text_color=COLOR_DANGER, hover_color="#450a0a",
            font=ctk.CTkFont(size=12),
            command=self.clear_all_terminals
        )
        self.btn_clear_all.pack(side="left", padx=3)
        self.tip_clear_all = ToolTip(self.btn_clear_all, "Cerrar y limpiar todas las terminales del sandbox")
        
        # 2. Contenedor de la Rejilla (Scrollable Frame para admitir scroll)
        self.main_area = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.main_area.pack(fill="both", expand=True, padx=15, pady=(0, 15))

    def add_terminal(self):
        self.terminal_counter += 1
        selected_shell = shell_id_from_label(self.shell_var.get())
        
        panel = QuickTerminalPanel(
            parent=self.main_area,
            shell_type=selected_shell,
            terminal_id=self.terminal_counter,
            on_close=self.remove_terminal
        )
        self.terminals.append(panel)
        self.rebuild_grid()

    def remove_terminal(self, panel):
        if panel in self.terminals:
            self.terminals.remove(panel)
            try:
                panel.grid_forget()
            except:
                pass
            panel.destroy()
            self.rebuild_grid()

    def clear_all_terminals(self):
        from tkinter import messagebox
        if messagebox.askyesno("Confirmar acción", "¿Estás seguro de que deseas cerrar todas las terminales del sandbox?"):
            for panel in list(self.terminals):
                panel.close()
            self.terminals.clear()
            self.rebuild_grid()

    def rebuild_grid(self):
        # Si no hay terminales, mostrar placeholder
        if not self.terminals:
            if hasattr(self, "placeholder_card"):
                try:
                    self.placeholder_card.destroy()
                except:
                    pass
                delattr(self, "placeholder_card")
                
            self.main_area.pack_forget()
            
            self.placeholder_card = ctk.CTkFrame(self, fg_color=BG_CARD, border_width=1, border_color=BORDER_COLOR, corner_radius=12)
            self.placeholder_card.pack(fill="both", expand=True, padx=15, pady=(0, 15))
            
            empty_container = ctk.CTkFrame(self.placeholder_card, fg_color="transparent")
            empty_container.pack(expand=True)
            
            icon_lbl = ctk.CTkLabel(
                empty_container,
                text="🐚",
                font=ctk.CTkFont(size=48)
            )
            icon_lbl.pack(pady=(0, 10))
            
            title_lbl = ctk.CTkLabel(
                empty_container,
                text="Sandbox Libre de Terminales",
                font=ctk.CTkFont(size=16, weight="bold"),
                text_color="white"
            )
            title_lbl.pack(pady=(0, 5))
            
            placeholder_lbl = ctk.CTkLabel(
                empty_container, 
                text="No hay terminales libres activas.\nSelecciona el intérprete arriba y haz clic en '+ Nueva Terminal' para empezar.", 
                font=FONT_MUTED, text_color=COLOR_MUTED,
                justify="center"
            )
            placeholder_lbl.pack()
            self.btn_clear_all.configure(state="disabled")
            return
            
        # Ocultar placeholder si existía
        if hasattr(self, "placeholder_card"):
            try:
                self.placeholder_card.destroy()
            except:
                pass
            delattr(self, "placeholder_card")
            
        self.main_area.pack(fill="both", expand=True, padx=15, pady=(0, 15))
        self.btn_clear_all.configure(state="normal")
        
        num_terminals = len(self.terminals)
        
        # Limpiar filas del grid anterior para evitar filas residuales vacías
        for r in range(50):
            self.main_area.grid_rowconfigure(r, weight=0, minsize=0)
            
        if num_terminals == 1:
            # Una sola terminal: Grid completo ocupando 2 columnas
            self.main_area.grid_columnconfigure(0, weight=1, uniform="equal")
            self.main_area.grid_columnconfigure(1, weight=0, uniform="")
            self.main_area.grid_rowconfigure(0, weight=1, minsize=450)
            self.terminals[0].grid(row=0, column=0, columnspan=2, padx=4, pady=4, sticky="nsew")
        else:
            cols = 2
            for c in range(cols):
                self.main_area.grid_columnconfigure(c, weight=1, uniform="equal")
                
            for idx, panel in enumerate(self.terminals):
                r = idx // cols
                c = idx % cols
                # Las terminales se distribuyen uniformemente en celdas de 1 columna.
                # Se especifica columnspan=1 de forma explícita para evitar que Tkinter retenga
                # un columnspan=2 previo si este panel era el único terminal del grid.
                panel.grid(row=r, column=c, columnspan=1, padx=6, pady=6, sticky="nsew")
                self.main_area.grid_rowconfigure(r, minsize=320)
                
        # Forzar actualización de tamaño y arranque para ajustar las consolas empotradas
        self.update()
        for panel in self.terminals:
            if not panel.process:
                panel.start_shell()
            else:
                panel.on_resize()

    def set_active_panel(self, panel):
        if self.active_panel == panel:
            return
            
        # Desactivar borde del panel activo previo
        if self.active_panel:
            try:
                self.active_panel.configure(border_color=BORDER_COLOR)
            except:
                pass
                
        # Activar borde del nuevo panel activo
        self.active_panel = panel
        if self.active_panel:
            try:
                self.active_panel.configure(border_color=COLOR_PRIMARY)
            except:
                pass

    def focus_loop(self):
        try:
            if not self.winfo_exists():
                return
        except:
            return
            
        try:
            found_panel = None

            # 0. Comprobar si el botón izquierdo del ratón está presionado (detección de clic en consola nativa)
            is_click = False
            try:
                # 0x01 es VK_LBUTTON
                is_click = (user32.GetAsyncKeyState(0x01) & 0x8000) != 0
            except:
                pass

            if is_click:
                try:
                    # Comprobar si la ventana activa pertenece a nuestro proceso de Tkinter o de conhost
                    fg_hwnd = user32.GetForegroundWindow()
                    current_pid = kernel32.GetCurrentProcessId()
                    fg_pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
                    
                    is_ours = (fg_pid.value == current_pid)
                    if not is_ours:
                        for panel in self.terminals:
                            if panel.process and fg_pid.value == panel.process.pid:
                                is_ours = True
                                break
                    
                    if is_ours:
                        pt = POINT()
                        if user32.GetCursorPos(ctypes.byref(pt)):
                            hwnd_under = user32.WindowFromPoint(pt)
                            if hwnd_under:
                                for panel in self.terminals:
                                    if panel.child_hwnd and (hwnd_under == panel.child_hwnd or user32.IsChild(panel.child_hwnd, hwnd_under)):
                                        # El usuario hizo clic en esta consola, le transferimos el foco y lo marcamos activo
                                        user32.SetFocus(panel.child_hwnd)
                                        found_panel = panel
                                        break
                except:
                    pass
            
            # 0.5. Comprobar si la ventana en primer plano (GetForegroundWindow) es directamente la consola de algún panel (fallback pasivo)
            if not found_panel:
                try:
                    fg_hwnd = user32.GetForegroundWindow()
                    if fg_hwnd:
                        for panel in self.terminals:
                            if panel.child_hwnd and (fg_hwnd == panel.child_hwnd or user32.IsChild(panel.child_hwnd, fg_hwnd)):
                                found_panel = panel
                                break
                except:
                    pass

            # 1. Comprobar de forma directa usando GetFocus local (gracias al vínculo permanente con AttachThreadInput)
            if not found_panel:
                try:
                    focus_hwnd = user32.GetFocus()
                    if focus_hwnd:
                        for panel in self.terminals:
                            try:
                                # Comprobar si el foco está en la consola embebida
                                is_conhost = (panel.child_hwnd and (focus_hwnd == panel.child_hwnd or user32.IsChild(panel.child_hwnd, focus_hwnd)))
                                # Comprobar si el foco está en el contenedor de Tkinter
                                panel_hwnd = panel.winfo_id()
                                is_tkinter = (focus_hwnd == panel_hwnd or user32.IsChild(panel_hwnd, focus_hwnd))
                                if is_conhost or is_tkinter:
                                    found_panel = panel
                                    break
                            except:
                                pass
                except:
                    pass
                
            # 2. Comprobar mediante GetGUIThreadInfo en el hilo de cada consola embebida (conhost)
            if not found_panel:
                for panel in self.terminals:
                    if panel.child_hwnd:
                        try:
                            child_thread = user32.GetWindowThreadProcessId(panel.child_hwnd, None)
                            info = GUITHREADINFO()
                            info.cbSize = ctypes.sizeof(GUITHREADINFO)
                            if user32.GetGUIThreadInfo(child_thread, ctypes.byref(info)):
                                focus_hwnd = info.hwndFocus
                                if focus_hwnd:
                                    if focus_hwnd == panel.child_hwnd or user32.IsChild(panel.child_hwnd, focus_hwnd):
                                        found_panel = panel
                                        break
                        except:
                            pass
            
            # 3. Comprobar si el foco está en un widget de Tkinter o consola mediante el hilo en primer plano
            if not found_panel:
                try:
                    info = GUITHREADINFO()
                    info.cbSize = ctypes.sizeof(GUITHREADINFO)
                    if user32.GetGUIThreadInfo(0, ctypes.byref(info)):
                        focus_hwnd = info.hwndFocus
                        if focus_hwnd:
                            for panel in self.terminals:
                                try:
                                    is_conhost = (panel.child_hwnd and (focus_hwnd == panel.child_hwnd or user32.IsChild(panel.child_hwnd, focus_hwnd)))
                                    panel_hwnd = panel.winfo_id()
                                    is_tkinter = (focus_hwnd == panel_hwnd or user32.IsChild(panel_hwnd, focus_hwnd))
                                    if is_conhost or is_tkinter:
                                        found_panel = panel
                                        break
                                except:
                                    pass
                except:
                    pass
            
            # 4. Aplicar el panel activo encontrado
            if found_panel:
                self.set_active_panel(found_panel)
            else:
                # Si el foco no está en ninguna de nuestras terminales ni widgets,
                # verificar si el usuario cambió de aplicación (primer plano)
                fg_hwnd = user32.GetForegroundWindow()
                if fg_hwnd:
                    current_pid = kernel32.GetCurrentProcessId()
                    fg_pid = ctypes.c_ulong()
                    user32.GetWindowThreadProcessId(fg_hwnd, ctypes.byref(fg_pid))
                    
                    is_our_process = (fg_pid.value == current_pid)
                    if not is_our_process:
                        # Comprobar si el proceso de primer plano es el de alguna de las consolas
                        for panel in self.terminals:
                            if panel.process and fg_pid.value == panel.process.pid:
                                is_our_process = True
                                break
                    
                    if not is_our_process:
                        # Quitar borde verde si la app no está en primer plano
                        self.set_active_panel(None)
        except Exception as e:
            pass
            
        # Re-programar en 50ms para una detección de clics sumamente responsiva y fluida
        try:
            self.focus_loop_id = self.after(50, self.focus_loop)
        except:
            pass

    def destroy(self):
        # Cancelar bucle de foco antes de destruir
        if hasattr(self, "focus_loop_id") and self.focus_loop_id:
            try:
                self.after_cancel(self.focus_loop_id)
            except:
                pass
        # Limpieza activa de todos los procesos al salir de la vista o destruir la app
        for panel in self.terminals:
            try:
                panel.on_close = None  # Prevenir llamadas de reconstrucción del grid durante la destrucción
                panel.close()
            except:
                pass
        super().destroy()
