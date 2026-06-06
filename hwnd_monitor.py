import customtkinter as ctk
import tkinter as tk
import sys
import time

sys.path.append(r"c:\Users\maxpa\Desktop\Max-Pasten\Projects\Central-Terminal")

class HWNDMonitorPanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent, fg_color="red", width=200, height=200)
        
        self.console_container = tk.Frame(self, bg="black")
        self.console_container.pack(fill="both", expand=True)
        
        print(f"[Panel Init] console_container HWND: {self.console_container.winfo_id()}")
        
        self.bind("<Map>", self.on_map)
        self.console_container.bind("<Configure>", self.on_resize)
        
    def on_map(self, event=None):
        print(f"[Panel Map] console_container HWND: {self.console_container.winfo_id()}")
        
    def on_resize(self, event=None):
        print(f"[Panel Resize] console_container HWND: {self.console_container.winfo_id()}")

class TestApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.geometry("400x400")
        
        # We will add it and then pack it after a delay
        self.panel = HWNDMonitorPanel(self)
        self.after(500, self.pack_panel)
        self.after(1500, self.close_app)
        
    def pack_panel(self):
        print("Packing panel...")
        self.panel.pack(fill="both", expand=True, padx=20, pady=20)
        self.update()
        
    def close_app(self):
        self.destroy()

if __name__ == "__main__":
    app = TestApp()
    app.mainloop()
