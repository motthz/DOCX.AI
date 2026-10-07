"""Rilevamento hardware per scegliere modello e accelerazione.

- RAM totale/libera (GlobalMemoryStatusEx)
- core CPU
- GPU compatibile Vulkan (driver presente: vulkan-1.dll) e nome delle schede video
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List, Optional

GB = 1024 ** 3


class _MemStatus(ctypes.Structure):
    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]


def memory() -> tuple[int, int]:
    """(totale, disponibile) in byte. (0, 0) se non rilevabile."""
    if sys.platform != "win32":
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            avail = os.sysconf("SC_AVPHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            return pages * size, avail * size
        except (ValueError, OSError, AttributeError):
            return 0, 0
    st = _MemStatus()
    st.dwLength = ctypes.sizeof(_MemStatus)
    if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
        return int(st.ullTotalPhys), int(st.ullAvailPhys)
    return 0, 0


def model_ram_need(model_path: Path, context_size: int = 4096) -> int:
    """RAM stimata per caricare un modello GGUF: file + KV cache + margine."""
    try:
        size = Path(model_path).stat().st_size
    except OSError:
        return 0
    # KV cache: ~0.11 MB per token per i modelli <2B, ~0.15 MB per il 4B
    per_token = 0.15 if size > 2 * GB else 0.11
    kv = int(context_size * per_token * 1024 * 1024)
    return int(size * 1.1) + kv + 300 * 1024 * 1024


@dataclass
class Hardware:
    ram_total: int = 0
    ram_available: int = 0
    cpu_cores: int = 1
    gpus: List[str] = field(default_factory=list)
    vulkan: bool = False
    # memoria della scheda video piu' capiente (0 = sconosciuta o solo integrata)
    vram: int = 0

    @property
    def ram_total_gb(self) -> float:
        return round(self.ram_total / GB, 1)

    @property
    def ram_available_gb(self) -> float:
        return round(self.ram_available / GB, 1)

    @property
    def gpu_accel(self) -> bool:
        """Scheda video dedicata (>= 4 GB) utilizzabile da llama.cpp via Vulkan."""
        return self.vulkan and self.vram >= 4 * GB

    def recommended_model(self) -> str:
        """Modello consigliato per questo PC.

        - 4B Instruct (il piu' preciso) con una scheda video dedicata, oppure con
          almeno 8 GB di RAM e 8 thread CPU: su una CPU datata e' 2-3 volte piu'
          lento dell'1.7B e una bozza richiederebbe diversi minuti;
        - 1.7B a 4 bit (veloce) negli altri casi;
        - 0.6B solo sotto i 4 GB di RAM: sbaglia troppo per i moduli reali."""
        if self.gpu_accel:
            return "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        if self.ram_total and self.ram_total < 4 * GB:
            return "Qwen3-0.6B-Q8_0.gguf"
        if self.ram_total >= 8 * GB and self.cpu_cores >= 8:
            return "Qwen3-4B-Instruct-2507-Q4_K_M.gguf"
        return "Qwen3-1.7B-Q4_K_M.gguf"

    def summary(self) -> str:
        gpu = ", ".join(self.gpus) if self.gpus else "nessuna rilevata"
        return (f"RAM {self.ram_available_gb} GB libera su {self.ram_total_gb} GB · "
                f"CPU {self.cpu_cores} core · GPU: {gpu}"
                + (" (Vulkan)" if self.vulkan else ""))


_GPU_SKIP = ("basic display", "remote", "virtual", "parsec", "dameware")
_DISPLAY_CLASS = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"


def _gpu_registry() -> List[tuple]:
    """(nome, memoria video in byte) delle schede video dal registro: pochi ms,
    contro ~2 s di PowerShell che bloccava l'apertura delle Impostazioni."""
    import winreg
    out: List[tuple] = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, _DISPLAY_CLASS) as cls:
        for i in range(winreg.QueryInfoKey(cls)[0]):
            sub = winreg.EnumKey(cls, i)
            if not sub.isdigit():
                continue
            try:
                with winreg.OpenKey(cls, sub) as key:
                    name = str(winreg.QueryValueEx(key, "DriverDesc")[0]).strip()
                    mem = 0
                    for value in ("HardwareInformation.qwMemorySize", "HardwareInformation.MemorySize"):
                        try:
                            raw = winreg.QueryValueEx(key, value)[0]
                            mem = int.from_bytes(raw, "little") if isinstance(raw, bytes) else int(raw)
                            break
                        except (OSError, ValueError, TypeError):
                            continue
            except OSError:
                continue
            if name and not any(s in name.lower() for s in _GPU_SKIP):
                out.append((name, mem))
    return out


def _gpus() -> List[tuple]:
    """(nome, memoria video) delle schede video; memoria 0 se non nota."""
    if sys.platform != "win32":
        return []
    try:
        found = _gpu_registry()
        if found:
            return found
    except OSError:
        pass
    return [(n, 0) for n in _gpu_names_powershell()]


def _gpu_names() -> List[str]:
    return [n for n, _m in _gpus()]


def _gpu_names_powershell() -> List[str]:
    try:
        from .. import winshell
        out = winshell.run("Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
                           timeout=15)
        names = [n.strip() for n in out.stdout.splitlines() if n.strip()]
        return [n for n in names if not any(s in n.lower() for s in _GPU_SKIP)]
    except (OSError, subprocess.SubprocessError):
        return []


def _has_vulkan() -> bool:
    if sys.platform != "win32":
        return False
    sysroot = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    return (sysroot / "System32" / "vulkan-1.dll").is_file()


@lru_cache(maxsize=1)
def detect() -> Hardware:
    total, avail = memory()
    gpus = _gpus()
    return Hardware(ram_total=total, ram_available=avail, cpu_cores=os.cpu_count() or 1,
                    gpus=[n for n, _m in gpus], vulkan=_has_vulkan(),
                    vram=max((m for _n, m in gpus), default=0))


def refresh_memory(hw: Optional[Hardware] = None) -> Hardware:
    hw = hw or detect()
    hw.ram_total, hw.ram_available = memory()
    return hw
