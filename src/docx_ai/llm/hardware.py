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
    kv = int(context_size * 0.11 * 1024 * 1024 / 1024 * 1.0)  # ~0.11 MB per token (modelli <2B)
    return int(size * 1.1) + kv + 300 * 1024 * 1024


@dataclass
class Hardware:
    ram_total: int = 0
    ram_available: int = 0
    cpu_cores: int = 1
    gpus: List[str] = field(default_factory=list)
    vulkan: bool = False

    @property
    def ram_total_gb(self) -> float:
        return round(self.ram_total / GB, 1)

    @property
    def ram_available_gb(self) -> float:
        return round(self.ram_available / GB, 1)

    def recommended_model(self) -> str:
        """Modello consigliato in base alla RAM disponibile."""
        if self.ram_total and self.ram_total < 6 * GB:
            return "Qwen3-0.6B-Q8_0.gguf"
        return "Qwen3-1.7B-Q8_0.gguf"

    def summary(self) -> str:
        gpu = ", ".join(self.gpus) if self.gpus else "nessuna rilevata"
        return (f"RAM {self.ram_available_gb} GB libera su {self.ram_total_gb} GB · "
                f"CPU {self.cpu_cores} core · GPU: {gpu}"
                + (" (Vulkan)" if self.vulkan else ""))


def _gpu_names() -> List[str]:
    if sys.platform != "win32":
        return []
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name"],
            capture_output=True, text=True, timeout=15, creationflags=0x08000000)
        names = [n.strip() for n in out.stdout.splitlines() if n.strip()]
        skip = ("basic display", "remote", "virtual", "parsec", "dameware")
        return [n for n in names if not any(s in n.lower() for s in skip)]
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
    return Hardware(ram_total=total, ram_available=avail, cpu_cores=os.cpu_count() or 1,
                    gpus=_gpu_names(), vulkan=_has_vulkan())


def refresh_memory(hw: Optional[Hardware] = None) -> Hardware:
    hw = hw or detect()
    hw.ram_total, hw.ram_available = memory()
    return hw
