import customtkinter as ctk
import tkinter as tk
import subprocess
import time
import ctypes
import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("flags", ctypes.c_ulong),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMenuState", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", ctypes.c_ulong * 4)
    ]

def get_window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.geometry("600x400")
        
        self.panel = ctk.CTkFrame(self, border_width=3, border_color="grey")
        self.panel.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.container = tk.Frame(self.panel, bg="#0c0c0c")
        self.container.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.update()
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE
        self.proc = subprocess.Popen(
            ["conhost.exe", "powershell.exe"],
            creationflags=subprocess.CREATE_NEW_CONSOLE,
            startupinfo=startupinfo
        )
        
        self.child_hwnd = 0
        for _ in range(40):
            self.child_hwnd = self.find_hwnd(self.proc.pid)
            if self.child_hwnd:
                break
            time.sleep(0.05)
            
        if self.child_hwnd:
            parent_hwnd = self.container.winfo_id()
            user32.SetParent(self.child_hwnd, parent_hwnd)
            user32.ShowWindow(self.child_hwnd, 5)
            
            style = user32.GetWindowLongW(self.child_hwnd, -16)
            style = (style & ~0x00C00000 & ~0x80000000 & ~0x00040000 & ~0x00800000) | 0x40000000 # WS_CHILD
            user32.SetWindowLongW(self.child_hwnd, -16, style)
            
            w = self.container.winfo_width()
            h = self.container.winfo_height()
            user32.MoveWindow(self.child_hwnd, 0, 0, w, h, True)
            
        # Bind header click simulation
        self.btn = ctk.CTkButton(self, text="Focus child (sim click header)", command=self.focus_child)
        self.btn.pack(pady=10)
        
        self.focus_loop()
        
    def find_hwnd(self, pid):
        hwnd_found = [0]
        def cb(hwnd, lParam):
            wpid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            if wpid.value == pid:
                if get_window_class(hwnd) == "ConsoleWindowClass":
                    hwnd_found[0] = hwnd
                    return False
            return True
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return hwnd_found[0]

    def focus_child(self):
        if self.child_hwnd:
            child_thread = user32.GetWindowThreadProcessId(self.child_hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(current_thread, child_thread, True)
            user32.SetFocus(self.child_hwnd)
            user32.AttachThreadInput(current_thread, child_thread, False)

    def focus_loop(self):
        info = GUITHREADINFO()
        info.cbSize = ctypes.sizeof(GUITHREADINFO)
        
        # Test GetGUIThreadInfo with 0 (foreground thread)
        focus_fg = 0
        if user32.GetGUIThreadInfo(0, ctypes.byref(info)):
            focus_fg = info.hwndFocus
            
        # Test GetFocus directly
        focus_local = user32.GetFocus()
        
        # Get active window
        active_hwnd = user32.GetActiveWindow()
        
        print(f"Child HWND: {self.child_hwnd} | Focus FG: {focus_fg} ({get_window_class(focus_fg) if focus_fg else 'None'}) | Focus Local: {focus_local} ({get_window_class(focus_local) if focus_local else 'None'}) | Active: {active_hwnd}", flush=True)
        
        if focus_fg == self.child_hwnd:
            self.panel.configure(border_color="#10b981")
        else:
            self.panel.configure(border_color="grey")
            
        self.after(500, self.focus_loop)

if __name__ == "__main__":
    app = App()
    app.mainloop()
    if app.proc:
        app.proc.kill()
