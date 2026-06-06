import os
import json

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "services.json")

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
