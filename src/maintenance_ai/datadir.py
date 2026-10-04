"""Cartella dati configurabile (anche su rete/NAS) e lock tra postazioni.

La scelta della cartella e' salvata in un file "puntatore" sempre locale:
``%LOCALAPPDATA%\\MaintenanceAI\\location.json``. Se la cartella e' condivisa,
un file di lock con heartbeat impedisce che due PC scrivano lo stesso database
SQLite contemporaneamente (SQLite su SMB non e' sicuro in scrittura concorrente).
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

APP_NAME = "MaintenanceAI"
LOCK_NAME = ".maintenanceai.lock"
HEARTBEAT_S = 30
STALE_AFTER_S = 120


def local_app_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def pointer_file() -> Path:
    return local_app_dir() / "location.json"


def configured_data_dir() -> Optional[Path]:
    """Cartella dati scelta dall'utente nelle Impostazioni (None = predefinita)."""
    try:
        raw = json.loads(pointer_file().read_text(encoding="utf-8"))
        val = raw.get("data_dir")
        return Path(val) if val else None
    except (OSError, ValueError):
        return None


def set_configured_data_dir(path: Optional[Path]) -> None:
    pf = pointer_file()
    pf.parent.mkdir(parents=True, exist_ok=True)
    pf.write_text(json.dumps({"data_dir": str(path) if path else None}, indent=2), encoding="utf-8")


def is_network_path(path: Path) -> bool:
    """True per percorsi UNC (\\\\server\\share) o unita' di rete mappate."""
    p = str(path)
    if p.startswith("\\\\") or p.startswith("//"):
        return True
    if os.name != "nt" or len(p) < 2 or p[1] != ":":
        return False
    try:
        import ctypes
        DRIVE_REMOTE = 4
        return ctypes.windll.kernel32.GetDriveTypeW(f"{p[0]}:\\") == DRIVE_REMOTE
    except Exception:  # noqa: BLE001
        return False


@dataclass
class LockInfo:
    host: str
    user: str
    pid: int
    heartbeat: float

    @property
    def age_s(self) -> float:
        return time.time() - self.heartbeat


class DataDirLocked(Exception):
    def __init__(self, info: LockInfo):
        super().__init__(f"Cartella dati in uso su {info.host} ({info.user})")
        self.info = info


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class DataDirLock:
    def __init__(self, data_root: Path):
        self.path = Path(data_root) / LOCK_NAME
        self.me = LockInfo(socket.gethostname(), os.environ.get("USERNAME", "?"), os.getpid(), time.time())
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def read(self) -> Optional[LockInfo]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            return LockInfo(d["host"], d.get("user", "?"), int(d["pid"]), float(d["heartbeat"]))
        except (OSError, ValueError, KeyError):
            return None

    def _holder_active(self, info: LockInfo) -> bool:
        if info.host == self.me.host:
            return info.pid != self.me.pid and _pid_alive(info.pid)
        return info.age_s < STALE_AFTER_S

    def acquire(self, *, force: bool = False) -> None:
        info = self.read()
        if info and not force and self._holder_active(info):
            raise DataDirLocked(info)
        self._write()
        self._thread = threading.Thread(target=self._beat, daemon=True, name="datadir-lock")
        self._thread.start()

    def _write(self) -> None:
        self.me.heartbeat = time.time()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.me.__dict__), encoding="utf-8")
        tmp.replace(self.path)

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_S):
            try:
                self._write()
            except OSError:
                pass

    def release(self) -> None:
        self._stop.set()
        info = self.read()
        if info and info.host == self.me.host and info.pid == self.me.pid:
            try:
                self.path.unlink()
            except OSError:
                pass
