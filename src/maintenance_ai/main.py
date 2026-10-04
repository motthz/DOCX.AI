"""Command-line entrypoint for MaintenanceAI.

Usage:
  python -m maintenance_ai.main                # Launch GUI
  python src/maintenance_ai/main.py            # Launch GUI
  MaintenanceAI.exe                            # Launch GUI (packaged)
  <any above> --self-test                      # Run smoke tests, exit code !=0 on failure
  <any above> --config PATH                    # Use alternate config file
"""

from __future__ import annotations

import argparse
import os as _os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional


def _install_crash_logger() -> Optional[Path]:
    """Redirect stderr/stdout to a persistent crash.log BEFORE any app code runs.

    When the PyInstaller bootloader uses ``runw.exe`` (console=False), both
    streams are detached from any terminal and exceptions during Tk bootstrap
    are invisible. By appending to ``logs/crash.log`` under the app data dir
    we guarantee that every crash leaves a readable traceback even if no
    messagebox pops up.
    """
    # Try to mirror Config resolution: %LOCALAPPDATA%/MaintenanceAI
    data_dir: Optional[Path] = None
    try:
        import os as _os
        local = _os.environ.get("LOCALAPPDATA")
        if local:
            data_dir = Path(local) / "MaintenanceAI"
        else:
            # Frozen fallback: exe grandparent (dist root)
            if getattr(sys, "frozen", False):
                data_dir = Path(sys.executable).parent
    except Exception:
        pass
    if data_dir is None:
        return None
    logs_dir = data_dir / "logs"
    try:
        logs_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return None
    log_file = logs_dir / "crash.log"
    _attach_parent_console()
    fh = None
    try:
        fh = open(log_file, "a", encoding="utf-8")
        stamp = datetime.now().isoformat(timespec="seconds")
        fh.write(f"\n===== MaintenanceAI start {stamp} =====\n")
        fh.flush()
        class _FlushingWriter:
            def __init__(self, _fh, _orig):
                self._fh = _fh
                self._orig = _orig
                self._closed = False
            def write(self, s):
                if self._closed:
                    return
                try:
                    self._fh.write(s)
                    self._fh.flush()
                except Exception:
                    pass
                try:
                    if self._orig is not None:
                        self._orig.write(s)
                        try: self._orig.flush()
                        except Exception: pass
                except Exception:
                    pass
            def flush(self):
                try: self._fh.flush()
                except Exception: pass
                try:
                    if self._orig is not None: self._orig.flush()
                except Exception: pass
            def close(self):
                if self._closed:
                    return
                self._closed = True
                self.flush()
                try:
                    self._fh.close()
                except Exception:
                    pass
            def isatty(self): return False
            def fileno(self): raise OSError()
            def __getattr__(self, item): return getattr(self._orig, item)
        sys.stdout = _FlushingWriter(fh, sys.stdout)
        sys.stderr = _FlushingWriter(fh, sys.stderr)
        print(f"sys.argv = {sys.argv}")
        print(f"sys.frozen = {getattr(sys, 'frozen', False)}")
        return log_file
    except Exception:
        if fh is not None:
            try: fh.close()
            except Exception: pass
        return None


def _attach_parent_console() -> None:
    """Windowed (no-console) build launched from a terminal with CLI flags:
    reattach to the parent console so --self-test/--version print there."""
    if not getattr(sys, "frozen", False) or sys.stdout is not None:
        return
    if not any(a in sys.argv for a in ("--self-test", "--version", "--help", "-h")):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):  # ATTACH_PARENT_PROCESS
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
            sys.stderr = sys.stdout
    except Exception:
        pass


_DPI_SUCCESS = False


def _enable_dpi_awareness() -> None:
    """Enable Windows Per-Monitor v2 DPI awareness BEFORE creating any Tk widget.

    Returns: sets global _DPI_SUCCESS True on any success, False on total failure.
    """
    global _DPI_SUCCESS
    try:
        import os as _os
        if _os.name != "nt":
            _DPI_SUCCESS = True
            return
    except Exception:
        return
    try:
        # Own taskbar identity: shows the app icon instead of the Python one.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MaintenanceAI.Desktop")
    except Exception:
        pass
    try:
        import ctypes
        user32 = ctypes.windll.user32
        shcore = ctypes.windll.shcore
        try:
            if user32.SetProcessDpiAwarenessContext(-4) == 0:
                _DPI_SUCCESS = True
                return
        except Exception:
            pass
        try:
            if shcore.SetProcessDpiAwareness(2) == 0:
                _DPI_SUCCESS = True
                return
        except Exception:
            pass
        try:
            if shcore.SetProcessDpiAwareness(1) == 0:
                _DPI_SUCCESS = True
                return
        except Exception:
            pass
        try:
            if user32.SetProcessDPIAware() != 0:
                _DPI_SUCCESS = True
                return
        except Exception:
            pass
    except Exception:
        pass


def _mutex_and_focus_existing() -> bool:
    """Single instance mutex + focus of existing MainWindow.

    Returns False se dobbiamo uscire (istanza già attiva e già portata in foreground),
    True se possiamo proseguire con l'avvio dell'istanza corrente.
    """
    try:
        import os as _os
        if _os.name != "nt":
            return True
    except Exception:
        return True
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        user32 = ctypes.windll.user32
        localapp = _os.environ.get("LOCALAPPDATA", _os.getcwd())
        import hashlib
        unique = hashlib.sha256(localapp.encode("utf-8", errors="replace")).hexdigest()[0:16]
        mutex_name = f"Global\\MaintenanceAI-{unique}"
        ERROR_ALREADY_EXISTS = 183
        kernel32.GetLastError.restype = wintypes.DWORD
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if handle == 0:
            return True
        last_err = kernel32.GetLastError()
        if last_err != ERROR_ALREADY_EXISTS:
            return True
        # Istanza già attiva: tenta di trovare e portare in primo piano la finestra
        SW_RESTORE = 9
        EnumWindowsProc = ctypes.WINFUNCTYPE(
            wintypes.BOOL, wintypes.HWND, wintypes.LPARAM
        )
        found = {"hwnd": None}

        def _enum_cb(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value
                if title.startswith("MaintenanceAI") or "MaintenanceAI" in title:
                    is_visible = user32.IsWindowVisible(hwnd)
                    if is_visible:
                        found["hwnd"] = hwnd
                        return False
            return True

        proc = EnumWindowsProc(_enum_cb)
        try:
            user32.EnumWindows(proc, 0)
        except Exception:
            pass
        hwnd = found["hwnd"]
        if hwnd is not None:
            try:
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                user32.SetFocus(hwnd)
            except Exception:
                pass
            return False
        # Mutex esistente ma nessuna finestra trovata (crash precedente senza cleanup)
        # → rilasciamo il mutex vecchio e proseguiamo
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        return True
    except Exception:
        return True


# Install crash logger FIRST, before any imports of our own code.
# (non nei processi figli usati per l'export PDF)
import multiprocessing as _mp  # noqa: E402

_IS_CHILD = _mp.parent_process() is not None
_crash_log = None if _IS_CHILD else _install_crash_logger()

# Enable DPI awareness early, before any tkinter import happens (or just
# before, no harm calling before load since it's a kernel32/user32/shcore
# process-wide flag).
_enable_dpi_awareness()


def _project_root_for_src_run() -> None:
    """Ensure imports work when file is invoked directly as a script
    OR via ``python -m maintenance_ai.main`` from any CWD."""
    try:
        here = Path(__file__).resolve().parent
    except NameError:
        return
    src_dir = here.parent
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    root = src_dir.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if getattr(sys, "frozen", False):
        return
    try:
        cwd_src = Path.cwd() / "src"
        if cwd_src.is_dir() and str(cwd_src) not in sys.path:
            sys.path.insert(0, str(cwd_src))
        cwd = Path.cwd()
        if (cwd / "config" / "default.json").is_file() and str(cwd) not in sys.path:
            sys.path.insert(0, str(cwd))
    except Exception:
        pass


_project_root_for_src_run()


from maintenance_ai.app import App  # noqa: E402


def _acquire_data_lock():
    """Lock della cartella dati (utile se condivisa in rete tra piu' PC).

    Ritorna il lock, None se non applicabile, False se l'utente rinuncia.
    """
    try:
        from maintenance_ai.config import _default_data_dir
        from maintenance_ai.datadir import DataDirLock, DataDirLocked
        root = _default_data_dir("MaintenanceAI")
        root.mkdir(parents=True, exist_ok=True)
        lock = DataDirLock(root)
    except Exception:  # noqa: BLE001
        return None
    try:
        lock.acquire()
        return lock
    except DataDirLocked as exc:
        info = exc.info
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk()
            r.withdraw()
            go = messagebox.askyesno(
                "MaintenanceAI - cartella dati in uso",
                f"La cartella dati\n{root}\nrisulta aperta su un altro PC:\n\n"
                f"   {info.host} (utente {info.user}), ultimo segnale {int(info.age_s)} s fa.\n\n"
                "Aprirla contemporaneamente da due PC può danneggiare il database.\n"
                "Aprire comunque (solo se sei sicuro che l'altro PC l'abbia chiusa)?",
                icon="warning")
            r.destroy()
        except Exception:  # noqa: BLE001
            go = False
        if not go:
            return False
        lock.acquire(force=True)
        return lock
    except OSError:
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="MaintenanceAI")
    parser.add_argument("--self-test", action="store_true",
                        help="Esegui self-test delle componenti core e termina")
    parser.add_argument("--config", type=Path, default=None,
                        help="Percorso alternativo per config/default.json")
    parser.add_argument("--verbose", action="store_true",
                        help="Aggiungi output verboso (per self-test)")
    parser.add_argument("--debug-llm", action="store_true",
                        help="Dump prompt/schema/raw-output LLM in logs/llm_debug")
    parser.add_argument("--no-gui-test-mode", action="store_true",
                        help=argparse.SUPPRESS)
    parser.add_argument("--version", action="store_true",
                        help="Stampa la versione e termina")
    args = parser.parse_args(argv)
    if args.version:
        from maintenance_ai import __version__
        print(f"MaintenanceAI {__version__}")
        return 0

    # 0) Single instance mutex: se già attivo, focus + exit 0
    # (il self-test non apre finestre: non deve essere bloccato da un'istanza GUI aperta)
    if not args.self_test and not _mutex_and_focus_existing():
        return 0
    # Env var per smoke test
    if _os.environ.get("MAINTENANCE_AI_SMOKE_TEST") == "1":
        args.no_gui_test_mode = True
    if _os.environ.get("MAINTENANCE_AI_DEBUG_LLM") == "1":
        args.debug_llm = True

    data_lock = None if args.self_test else _acquire_data_lock()
    if data_lock is False:
        return 0

    try:
        if args.self_test or args.no_gui_test_mode:
            app = App.bootstrap(config_path=args.config, verbose=args.verbose)
        else:
            from maintenance_ai.ui.splash import run_with_splash
            app = run_with_splash(lambda: App.bootstrap(config_path=args.config, verbose=args.verbose))
        # Avvisa DPI awareness fallito (logging pronto dopo bootstrap)
        if not _DPI_SUCCESS:
            import logging as _lg
            _lg.getLogger(__name__).warning(
                "DPI awareness: nessun metodo disponibile, finestre potrebbero apparire sgranate su display ad alta risoluzione."
            )
        if args.debug_llm:
            import logging as _lg2
            _lg2.getLogger(__name__).info("LLM debug dump mode attivo.")
    except Exception as exc:  # noqa: BLE001
        msg = f"Errore durante l'inizializzazione: {type(exc).__name__}: {exc}"
        print(msg, file=sys.stderr)
        try:
            import traceback
            traceback.print_exc(file=sys.stderr)
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("MaintenanceAI - Errore avvio", msg)
            try:
                root.destroy()
            except Exception:
                pass
        except Exception:
            pass
        return 1
    try:
        if args.self_test:
            return app.run_self_test()
        try:
            from maintenance_ai.ui.shell import MainWindow
        except Exception as exc:  # noqa: BLE001
            msg = f"Impossibile caricare l'interfaccia grafica: {type(exc).__name__}: {exc}"
            print(msg, file=sys.stderr)
            try:
                import traceback
                traceback.print_exc(file=sys.stderr)
            except Exception:
                pass
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror("MaintenanceAI - Errore UI", msg)
                try:
                    root.destroy()
                except Exception:
                    pass
            except Exception:
                pass
            return 1
        restart_cmd = None
        try:
            win = MainWindow(app)
            win.show()
            if getattr(win, "_restart", False):
                restart_cmd = win.relaunch_command()
        finally:
            try:
                app.shutdown()
            except Exception:  # noqa: BLE001
                pass
        if restart_cmd:
            if data_lock:
                data_lock.release()
                data_lock = None
            import subprocess
            subprocess.Popen(restart_cmd, close_fds=True)
        return 0
    finally:
        if data_lock:
            data_lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
