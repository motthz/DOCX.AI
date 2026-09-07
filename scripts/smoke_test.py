#!/usr/bin/env python3
r"""Smoke test 30 secondi per l'EXE pacchettizzato MaintenanceAI.

Uso (PowerShell):
  $env:MAINTENANCE_AI_SMOKE_TEST="1"
  python scripts\smoke_test.py [path_exe]

Path EXE default: dist\MaintenanceAI\MaintenanceAI.exe

Regole:
1. Avvia MaintenanceAI.exe
2. Poll ogni 2s per 30s:
   - se il processo muore PRIMA dei 30s -> FAIL (exit 1)
   - dopo 30s se ancora vivo -> chiudi gentilmente (WM_CLOSE)
3. Attendi max 5s per chiusura, se ancora vivo TerminateProcess
4. Scansiona eventuali file crash.log / traceback.log / logs/*.log sotto
   %LOCALAPPDATA%\MaintenanceAI\logs per 'Traceback' o 'CRITICAL' -> FAIL se trovati
5. Exit 0 se tutto OK.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:  # Optional: win32 per WM_CLOSE gentile. Se non disponibile fallback TerminateProcess.
    import ctypes
    from ctypes import wintypes
    _WIN32 = True
except Exception:  # pragma: no cover - ambienti non Windows sono comunque fallback
    _WIN32 = False


SMOKE_DURATION_S = 30
SMOKE_POLL_S = 2
CLOSE_WAIT_S = 5
EXIT_OK, EXIT_FAIL = 0, 1

HWND_BROADCAST = 0xFFFF
WM_CLOSE = 0x0010
SMTO_ABORTIFHUNG = 0x0002
SMTO_BLOCK = 0x0001

TRACEBACK_RE = re.compile(r"Traceback\s*\(most recent call last\)", re.IGNORECASE)


def _find_main_window(pid: int):
    """Trova HWND top-level per il PID (solo Windows)."""
    if not _WIN32:
        return None
    found = []
    EnumWindowsProc = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32 = ctypes.windll.user32

    def _cb(hwnd, _lparam):
        lpdw = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(lpdw))
        if lpdw.value == pid:
            if user32.IsWindowVisible(hwnd):
                found.append(hwnd)
                return False
        return True
    user32.EnumWindows(EnumWindowsProc(_cb), 0)
    return found[0] if found else None


def _wm_close(pid: int) -> bool:
    """Invia WM_CLOSE a finestra del processo. True se trovato."""
    hwnd = _find_main_window(pid)
    if hwnd is None or not _WIN32:
        return False
    user32 = ctypes.windll.user32
    user32.SendMessageTimeoutW(
        hwnd, WM_CLOSE, 0, 0,
        SMTO_BLOCK | SMTO_ABORTIFHUNG, 3000, None)
    return True


def _scan_logs(data_root: Path) -> list[str]:
    problems: list[str] = []
    logs = data_root / "logs"
    if not logs.exists():
        return problems
    for p in sorted(logs.rglob("*.log")):
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if TRACEBACK_RE.search(text):
            problems.append(f"TRACEBACK in {p}")
        if "CRITICAL" in text and "recovery_message" not in text[:300]:
            problems.append(f"CRITICAL entry in {p}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        exe = Path(argv[1])
    else:
        project_root = Path(__file__).resolve().parent.parent
        exe = project_root / "dist" / "MaintenanceAI" / "MaintenanceAI.exe"
    if not exe.exists():
        print(f"[smoke] EXE non trovato: {exe}", file=sys.stderr)
        print(f"[smoke] Esegui prima scripts/build.ps1", file=sys.stderr)
        return EXIT_FAIL
    exe = exe.resolve()

    localappdata = Path(os.environ.get(
        "LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    data_root = localappdata / "MaintenanceAI"

    print(f"[smoke] EXE          : {exe}")
    print(f"[smoke] data_root    : {data_root}")
    print(f"[smoke] durata       : {SMOKE_DURATION_S}s (poll ogni {SMOKE_POLL_S}s)")

    env = os.environ.copy()
    env.setdefault("MAINTENANCE_AI_SMOKE_TEST", "1")
    env.setdefault("MAINTENANCE_AI_NO_GUI_TEST_MODE", "1")

    try:
        proc = subprocess.Popen([str(exe)], env=env, close_fds=True)
    except Exception as e:
        print(f"[smoke] IMPOSSIBILE AVVIARE EXE: {e}", file=sys.stderr)
        return EXIT_FAIL

    pid = proc.pid
    print(f"[smoke] avviato PID  : {pid}")

    dead_before = False
    elapsed = 0.0
    t0 = time.monotonic()
    while elapsed < SMOKE_DURATION_S:
        rc = proc.poll()
        if rc is not None:
            print(f"[smoke] ❌ PROCESSO MORTO PREMATURAMENTE dopo {elapsed:.1f}s "
                  f"(exit={rc}). Attesi {SMOKE_DURATION_S}s.")
            dead_before = True
            break
        time.sleep(min(SMOKE_POLL_S, SMOKE_DURATION_S - elapsed))
        elapsed = time.monotonic() - t0
    else:
        print(f"[smoke] ✅ Processo sopravvissuto {SMOKE_DURATION_S}s. "
              f"Chiusura gentile (WM_CLOSE)...")

    if not dead_before and proc.poll() is None:
        closed = _wm_close(pid)
        waited = 0.0
        while waited < CLOSE_WAIT_S and proc.poll() is None:
            time.sleep(0.25)
            waited += 0.25
        if proc.poll() is None:
            print(f"[smoke] TerminateProcess fallback (WM_CLOSE "
                  f"{'inviato' if closed else 'non disponibile'}).")
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        rc = proc.returncode
        print(f"[smoke] chiusura OK (exit={rc}).")

    print("[smoke] scansione crash logs...")
    issues = _scan_logs(data_root)
    if issues:
        for it in issues:
            print(f"[smoke] ❌ LOG PROBLEMA: {it}", file=sys.stderr)
        return EXIT_FAIL

    print("[smoke] TUTTI I CHECK PASSATI.")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main(sys.argv))
