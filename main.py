import sys
import os
from config import load_workspaces
from manager import ServiceManager
from ui.app import CentralTerminalApp

def main():
    # Cargar la configuración guardada de espacios de trabajo y servicios
    workspaces_config = load_workspaces()

    # Inicializar el administrador de procesos
    manager = ServiceManager(workspaces_config)

    # Inicializar la aplicación de CustomTkinter
    app = CentralTerminalApp(manager)

    # Conectar el callback de recepción de logs del gestor a la UI
    manager.on_log_received = app.on_log_received_handler

    # Configurar el cierre seguro de la aplicación (Detener procesos)
    app.protocol("WM_DELETE_WINDOW", app.on_closing)

    # Arrancar el mainloop de Tkinter
    try:
        app.mainloop()
    except KeyboardInterrupt:
        # Apagado limpio en caso de interrupción en terminal
        app.destroy()

if __name__ == "__main__":
    main()
