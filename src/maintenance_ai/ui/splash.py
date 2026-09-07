"""Splash screen: 400x300 override-redirect centered, hides after MainWindow ready.

Guarantees minimum 1s display (prevents flicker when start is too fast).
"""

from __future__ import annotations

import time
import tkinter as tk
from typing import Callable, Optional

try:
    from tkinter import ttk
except Exception:  # noqa: BLE001
    ttk = None  # type: ignore


class SplashScreen:
    def __init__(self, root: tk.Misc, *, title: str = "MaintenanceAI",
                 subtitle: str = "Caricamento…",
                 min_display_ms: int = 1000):
        self.min_display_ms = int(min_display_ms)
        self._start = time.monotonic()
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.withdraw()
        w, h = 420, 260
        self.top.geometry(f"{w}x{h}")
        self.top.configure(bg="#1a2236")
        # Center
        self.top.update_idletasks()
        sw = self.top.winfo_screenwidth()
        sh = self.top.winfo_screenheight()
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.top.geometry(f"{w}x{h}+{x}+{y}")
        self.top.attributes("-topmost", True)
        try:
            self.top.attributes("-alpha", 0.96)
        except Exception:  # noqa: BLE001
            pass
        tk.Label(self.top, text=title, font=("Segoe UI", 20, "bold"),
                 bg="#1a2236", fg="#ffffff").pack(pady=(36, 4))
        tk.Label(self.top, text=subtitle, font=("Segoe UI", 11),
                 bg="#1a2236", fg="#c8d4ff").pack(pady=(0, 20))
        if ttk is not None:
            style = ttk.Style(self.top)
            try:
                style.theme_use("clam")
            except Exception:  # noqa: BLE001
                pass
            try:
                style.configure("Splash.Horizontal.TProgressbar",
                                background="#6ea8ff", troughcolor="#2a3860",
                                borderwidth=0, thickness=8)
            except Exception:  # noqa: BLE001
                pass
            self.progress = ttk.Progressbar(self.top, mode="indeterminate",
                                            length=260, style="Splash.Horizontal.TProgressbar")
        else:
            self.progress = None  # type: ignore
        if self.progress is not None:
            self.progress.pack(pady=4)
            self.progress.start(10)
        tk.Label(self.top,
                 text="Portable offline maintenance report generator",
                 font=("Segoe UI", 9), bg="#1a2236", fg="#7f8db0").pack(side="bottom", pady=16)

    def show(self) -> None:
        try:
            self.top.deiconify()
            self.top.lift()
        except Exception:  # noqa: BLE001
            pass

    def dismiss(self, callback: Optional[Callable[[], None]] = None) -> None:
        elapsed_ms = int((time.monotonic() - self._start) * 1000)
        remaining = max(0, self.min_display_ms - elapsed_ms)

        def _finish():
            try:
                if self.progress is not None:
                    self.progress.stop()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.top.destroy()
            except Exception:  # noqa: BLE001
                pass
            if callback:
                try:
                    callback()
                except Exception:  # noqa: BLE001
                    pass

        if remaining <= 0:
            _finish()
        else:
            self.top.after(remaining, _finish)
