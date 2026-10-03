"""Access to bundled image assets (logo, window icon).

Works from source (``src/maintenance_ai/assets``) and from the PyInstaller
build (``<_MEIPASS>/maintenance_ai/assets``).
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from typing import Dict, Optional

_CACHE: Dict[tuple, tk.PhotoImage] = {}


def asset_path(name: str) -> Path:
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "maintenance_ai" / "assets" / name)
    candidates.append(Path(__file__).resolve().parent.parent / "assets" / name)
    for c in candidates:
        if c.is_file():
            return c
    return candidates[-1]


def logo_image(master: tk.Misc, size: int = 64) -> Optional[tk.PhotoImage]:
    """Return the logo as a PhotoImage scaled down to roughly ``size`` px.

    Images are cached per (interpreter, size) so Tk does not garbage-collect them.
    """
    key = (str(master.tk), size)
    if key in _CACHE:
        return _CACHE[key]
    src = asset_path("logo_64.png" if size <= 64 else "logo.png")
    try:
        img = tk.PhotoImage(master=master, file=str(src))
        factor = max(1, round(img.width() / max(size, 1)))
        if factor > 1:
            img = img.subsample(factor, factor)
    except Exception:  # noqa: BLE001
        return None
    _CACHE[key] = img
    return img


def apply_window_icon(root: tk.Tk) -> None:
    """Set the taskbar/titlebar icon for the root and all future Toplevels."""
    ico = asset_path("app.ico")
    try:
        if sys.platform == "win32" and ico.is_file():
            root.iconbitmap(default=str(ico))
            return
    except Exception:  # noqa: BLE001
        pass
    img = logo_image(root, 64)
    if img is not None:
        try:
            root.iconphoto(True, img)
        except Exception:  # noqa: BLE001
            pass
