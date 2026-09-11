# -*- coding: utf-8 -*-
r"""
MaintenanceAI Launcher - STANDALONE ONE-FILE
Nessuna dipendenza da .bat / .cmd / PowerShell.
Ordine di avvio intelligente:
  1. dist\MaintenanceAI\MaintenanceAI.exe  (versione onedir PyInstaller, NO Python richiesto)
  2. .venv\Scripts\python.exe -m maintenance_ai.main  (ambiente virtuale locale)
  3. python (nel PATH) -m maintenance_ai.main  (Python globale)
Se nessuno funziona -> MessageBox con istruzioni chiare in italiano.
"""
import os
import sys
import subprocess
import ctypes
from pathlib import Path


MB_ICONERROR = 0x10
MB_ICONWARNING = 0x30
MB_ICONINFORMATION = 0x40
MB_OK = 0x0


def msgbox(text, title="MaintenanceAI", flags=MB_ICONERROR | MB_OK):
    try:
        ctypes.windll.user32.MessageBoxW(0, text, title, flags)
    except Exception:
        print(f"[{title}] {text}", file=sys.stderr)


def find_launcher_base():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def try_launch(exe_path, cwd, extra_env=None, args=None):
    exe = Path(exe_path)
    if not exe.exists():
        return False, f"Non trovato: {exe}"
    env = os.environ.copy()
    if extra_env:
        env.update(extra_env)
    cmd = [str(exe)]
    if args:
        cmd.extend(args)
    try:
        subprocess.Popen(cmd, cwd=str(cwd), env=env)
        return True, "OK"
    except Exception as e:
        return False, f"Errore avvio {exe.name}: {e}"


def launch_dist(base):
    target = base / "dist" / "MaintenanceAI" / "MaintenanceAI.exe"
    cwd = base / "dist" / "MaintenanceAI"
    ok, info = try_launch(target, cwd, args=sys.argv[1:])
    return ok, info, str(target)


def launch_venv(base):
    py = base / ".venv" / "Scripts" / "python.exe"
    if not py.exists():
        return False, f"Non trovato: {py}", str(py)
    env = {"PYTHONPATH": f"{base / 'src'};{base}"}
    ok, info = try_launch(py, base, extra_env=env,
                          args=["-m", "maintenance_ai.main"] + sys.argv[1:])
    return ok, info, str(py)


def launch_global_python(base):
    try:
        which = subprocess.run(
            ["where", "python"],
            capture_output=True, text=True, timeout=10
        )
        if which.returncode != 0 or not which.stdout.strip():
            return False, "Python non trovato nel PATH", "python"
        py = which.stdout.splitlines()[0].strip()
        if not py or not Path(py).exists():
            return False, f"Python non valido: {py}", "python"
        env = {"PYTHONPATH": f"{base / 'src'};{base}"}
        ok, info = try_launch(
            py, base, extra_env=env,
            args=["-m", "maintenance_ai.main"] + sys.argv[1:]
        )
        return ok, info, py
    except Exception as e:
        return False, f"Ricerca python fallita: {e}", "python"


def main():
    base = find_launcher_base()

    strategies = [
        ("Build PyInstaller (nessun Python richiesto)", launch_dist),
        ("Ambiente virtuale .venv locale", launch_venv),
        ("Python installato nel sistema", launch_global_python),
    ]

    errors = []
    for label, fn in strategies:
        ok, info, path = fn(base)
        if ok:
            return 0
        errors.append(f"- {label} -> {info}")

    text = (
        "IMPOSSIBILE AVVIARE MaintenanceAI.\r\n\r\n"
        "Nessuno dei metodi disponibili ha funzionato:\r\n"
        + "\r\n".join(errors)
        + "\r\n\r\n"
        "SOLUZIONI (in ordine di preferenza):\r\n"
        "1) Assicurati che la cartella 'dist\\MaintenanceAI\\' sia presente\r\n"
        "   (deve essere scaricata dalla release GitHub insieme a questo exe).\r\n"
        "2) Oppure apri PowerShell nella cartella progetto e scrivi:\r\n"
        "     powershell -ExecutionPolicy Bypass -File scripts\\build.ps1\r\n"
        "   per creare la build.\r\n"
        "3) Oppure lancia INSTALLA_E_AVVIA.bat la prima volta per creare .venv\r\n"
        "   e scaricare runtime e modello (richiede Internet).\r\n\r\n"
        "Cartella rilevata launcher:\r\n" + str(base)
    )
    msgbox(text, "MaintenanceAI - Impossibile avviare")
    return 1


if __name__ == "__main__":
    sys.exit(main())
