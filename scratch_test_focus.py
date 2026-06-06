import tkinter as tk
import subprocess
import time
import ctypes
import psutil

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

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

user32.SetParent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.SetParent.restype = ctypes.c_void_p

user32.ShowWindow.argtypes = [ctypes.c_void_p, ctypes.c_int]
user32.ShowWindow.restype = ctypes.c_bool

def get_window_class(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value

def find_hwnd(target_pid):
    hwnd_found = [0]
    child_pids = set()
    try:
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
            if get_window_class(hwnd) == "ConsoleWindowClass":
                hwnd_found[0] = hwnd
                return False
        return True
        
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    callback = WNDENUMPROC(enum_callback)
    user32.EnumWindows(callback, 0)
    return hwnd_found[0]

def main():
    root = tk.Tk()
    root.geometry("400x300")
    
    container = tk.Frame(root, bg="black")
    container.pack(fill="both", expand=True, padx=20, pady=20)
    
    root.update()
    
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startupinfo.wShowWindow = 0 # SW_HIDE
    
    proc = subprocess.Popen(
        ["conhost.exe", "powershell.exe"],
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        startupinfo=startupinfo
    )
    
    child_hwnd = 0
    for _ in range(40):
        child_hwnd = find_hwnd(proc.pid)
        if child_hwnd:
            break
        time.sleep(0.05)
        
    print(f"Child HWND: {child_hwnd}", flush=True)
    if child_hwnd:
        parent_hwnd = container.winfo_id()
        user32.SetParent(child_hwnd, parent_hwnd)
        user32.ShowWindow(child_hwnd, 8) # SW_SHOWNA
        
        # Attach thread input permanently
        child_thread = user32.GetWindowThreadProcessId(child_hwnd, None)
        current_thread = kernel32.GetCurrentThreadId()
        attached = user32.AttachThreadInput(current_thread, child_thread, True)
        print(f"Attached thread input: {attached}", flush=True)
        user32.SetFocus(child_hwnd)
        
    def check():
        if child_hwnd:
            focus = user32.GetFocus()
            print(f"GetFocus: {focus} (matches child: {focus == child_hwnd})", flush=True)
            
        root.after(500, check)
        
    root.after(500, check)
    root.after(4000, root.destroy)
    root.mainloop()
    
    # Detach before process is killed (important to prevent hangs/resource leaks)
    if child_hwnd:
        try:
            child_thread = user32.GetWindowThreadProcessId(child_hwnd, None)
            current_thread = kernel32.GetCurrentThreadId()
            user32.AttachThreadInput(current_thread, child_thread, False)
        except:
            pass
    proc.kill()

if __name__ == "__main__":
    main()
