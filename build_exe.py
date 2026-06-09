import sys
import subprocess
import os

def check_and_install_pyinstaller():
    try:
        import PyInstaller
        print("[+] PyInstaller ya está instalado.")
    except ImportError:
        print("[-] PyInstaller no encontrado. Instalándolo ahora...")
        try:
            # Usar el intérprete de python actual para instalar en el mismo entorno virtual
            subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)
            print("[+] PyInstaller instalado con éxito.")
        except subprocess.CalledProcessError as e:
            print(f"[!] Error al instalar PyInstaller: {e}")
            sys.exit(1)

def build_executable():
    print("[*] Iniciando la compilación del ejecutable...")
    
    # Parámetros del comando de PyInstaller
    cmd = [
        "pyinstaller",
        "--onefile",
        "--noconsole",
        "--collect-all", "customtkinter",
        "--name", "Central Terminal",
        "main.py"
    ]
    
    # En Windows, podemos usar el script pyinstaller.exe dentro de la carpeta Scripts del entorno virtual
    # o ejecutarlo como un módulo de python para garantizar que se ejecute en el entorno correcto
    pyinstaller_run_args = [sys.executable, "-m", "PyInstaller"] + cmd[1:]
    
    print(f"[*] Ejecutando: {' '.join(pyinstaller_run_args)}")
    try:
        subprocess.run(pyinstaller_run_args, check=True)
        print("\n" + "="*50)
        print("[+] ¡Compilación completada con éxito!")
        print(f"[+] El archivo ejecutable se encuentra en: {os.path.abspath('dist/Central Terminal.exe')}")
        print("="*50)
    except subprocess.CalledProcessError as e:
        print(f"\n[!] Error durante la compilación: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_and_install_pyinstaller()
    build_executable()
