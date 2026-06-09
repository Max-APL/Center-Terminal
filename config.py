import os
import json
import sys

def get_base_dir():
    """Retorna el directorio base correcto para el almacenamiento de configuraciones y logs.
    Si se ejecuta como compilado, usa el directorio del ejecutable .exe.
    Si se ejecuta como script, usa el directorio del propio script config.py (raíz del proyecto).
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    else:
        return os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(get_base_dir(), "services.json")

def load_workspaces():
    """Carga los espacios de trabajo y sus servicios desde el archivo JSON de configuración.
    Soporta migración del formato antiguo (lista plana de servicios).
    """
    if not os.path.exists(CONFIG_FILE):
        return {"workspaces": []}
        
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        # Caso 1: Formato antiguo (Lista plana de servicios)
        if isinstance(data, list):
            print("Detectado formato antiguo en services.json. Migrando a Espacios de Trabajo...")
            migrated_data = {
                "workspaces": [
                    {
                        "id": "default-workspace",
                        "name": "General",
                        "services": data
                    }
                ]
            }
            save_workspaces(migrated_data)
            return migrated_data
            
        # Caso 2: Formato nuevo
        if isinstance(data, dict) and "workspaces" in data:
            return data
            
        return {"workspaces": []}
        
    except Exception as e:
        print(f"Error cargando la configuración: {e}")
        return {"workspaces": []}

def save_workspaces(data):
    """Guarda la estructura de espacios de trabajo en el archivo JSON de configuración."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"Error guardando la configuración: {e}")
        return False
