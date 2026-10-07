"""Avvio di PowerShell senza i segnali che gli antivirus considerano sospetti.

Gli antivirus (Defender, e piu' ancora i prodotti aziendali/EDR) segnalano come
probabile malware un programma che avvia PowerShell con ``-EncodedCommand`` (script
in base64, tecnica tipica dei malware per nascondere il codice), con
``-ExecutionPolicy Bypass`` o cercando ``powershell`` nel PATH (dirottabile). Qui
PowerShell viene avviato dal percorso di sistema, con lo script in chiaro passato a
``-Command`` (i criteri di esecuzione degli script non si applicano a -Command,
quindi Bypass non serve) e senza finestra.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List

CREATE_NO_WINDOW = 0x08000000


def powershell_exe() -> str:
    root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    exe = root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    return str(exe) if exe.is_file() else "powershell.exe"


def powershell_args(script: str) -> List[str]:
    """Riga di comando per eseguire ``script`` (in chiaro). Lo script non deve contenere
    virgolette doppie: sulla riga di comando PowerShell 5.1 le interpreta in modo
    incoerente (usare le virgolette singole)."""
    if '"' in script:
        raise ValueError("script PowerShell con virgolette doppie: usare le virgolette singole")
    return [powershell_exe(), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script.strip()]


def run(script: str, *, timeout: float, **kw: Any) -> "subprocess.CompletedProcess[str]":
    kw.setdefault("capture_output", True)
    kw.setdefault("text", True)
    kw.setdefault("encoding", "utf-8")
    kw.setdefault("errors", "replace")
    kw.setdefault("stdin", subprocess.DEVNULL)
    return subprocess.run(powershell_args(script), timeout=timeout,
                          creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0, **kw)


def popen(script: str, **kw: Any) -> subprocess.Popen:
    return subprocess.Popen(powershell_args(script),
                            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0, **kw)
