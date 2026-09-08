"""
MaintenanceAI - Launcher EXE (ENTRY POINT per utente che clona la repo).

Questo e' il codice sorgente che viene compilato in ``MaintenanceAI.exe``
nella root del progetto (VERO file PE, non un .bat rinominato).

Cosa fa:
  1. Individua la cartella progetto (dove vive questo exe / sorgente).
  2. Verifica se esiste gia' ``.venv\Scripts\python.exe`` + runtime.
  3. - se MANCA .venv / manca llama-server.exe / manca il modello GGUF
       --> avvia ``INSTALLA_E_AVVIA.bat`` in una finestra cmd persistente
     - se CI SONO tutti
       --> avvia ``AVVIA_APP.bat`` in una finestra cmd.

Per compilare l'exe da sorgente (dopo setup_dev.ps1):

    .venv\\Scripts\\pyinstaller.exe --onefile --noconfirm --clean ^
        --name MaintenanceAI ^
        --collect-submodules=_bootlocale ^
        packaging\\launcher\\MaintenanceAI_launcher.py

Il prodotto sara' ``dist\\MaintenanceAI.exe``, da copiare nella root.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def get_project_dir() -> Path:
    """
    Folder dove vivono i .bat e le sottocartelle src/scripts.
    - se siamo compilati (sys.frozen) -> folder dell'exe
    - altrimenti -> folder di questo sorgente, andando su 2 livelli
      per arrivare alla root (packaging/launcher/ -> root).
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    # packaging/launcher/M_launcher.py -> torna alla root del progetto
    if here.parts[-2:] == ("packaging", "launcher"):
        return here.parent.parent
    return here.parent


def find_first_existing(project_dir: Path, candidates) -> Path | None:
    for rel in candidates:
        p = project_dir / rel
        if p.exists():
            return p
    return None


def run_detached_bat(bat_path: Path) -> int:
    """Avvia il .bat con una finestra cmd che rimane aperta dopo la fine."""
    cwd = str(bat_path.parent)
    # cmd /K => la finestra non si chiude quando il .bat finisce, utile
    # per leggere messaggi di errore o log di download.
    cmd = f'cmd.exe /K ""{bat_path}""'
    # DETACHED_PROCESS + CREATE_NEW_CONSOLE => finestra separata.
    DETACHED = 0x00000008
    NEW_CONSOLE = 0x00000010
    CREATE_NO_WINDOW = 0x08000000  # noqa: F841
    creationflags = NEW_CONSOLE | DETACHED
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    try:
        p = subprocess.Popen(
            cmd,
            cwd=cwd,
            shell=True,
            creationflags=creationflags,
        )
        return 0
    except OSError as exc:
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "MaintenanceAI - Errore avvio",
                f"Non sono riuscito ad avviare:\n{bat_path}\n\nErrore: {exc}",
            )
            root.destroy()
        except Exception:
            pass
        return 1


def main() -> int:
    project_dir = get_project_dir()

    # Decidi se siamo in "primo avvio" o "avvio normale"
    venv_py = project_dir / ".venv" / "Scripts" / "python.exe"
    llama_exe = project_dir / "runtime" / "llama" / "llama-server.exe"
    models_dir = project_dir / "models"
    modello_exists = False
    if models_dir.is_dir():
        for _ in models_dir.glob("*.gguf"):
            modello_exists = True
            break

    primo_avvio = not venv_py.is_file() or not llama_exe.is_file() or not modello_exists

    if primo_avvio:
        bat = project_dir / "INSTALLA_E_AVVIA.bat"
        if not bat.is_file():
            try:
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror(
                    "MaintenanceAI - File mancante",
                    "Nella cartella del progetto manca INSTALLA_E_AVVIA.bat.\n"
                    "Riscarica l'archivio o clona nuovamente la repository.",
                )
                root.destroy()
            except Exception:
                pass
            return 2
        return run_detached_bat(bat)

    bat = project_dir / "AVVIA_APP.bat"
    if not bat.is_file():
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "MaintenanceAI - File mancante",
                "Nella cartella del progetto manca AVVIA_APP.bat.\n"
                "Riscarica l'archivio o clona nuovamente la repository.",
            )
            root.destroy()
        except Exception:
            pass
        return 2
    return run_detached_bat(bat)


if __name__ == "__main__":
    raise SystemExit(main())
