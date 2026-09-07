"""Tooltip: simple hover widget for Tkinter ttk widgets.

Shows a wrapped text label after <Enter> with 500ms delay, destroys on <Leave>.
"""

from __future__ import annotations

import tkinter as tk
from typing import Optional

try:
    from tkinter import ttk  # noqa: F401
except Exception:  # noqa: BLE001
    ttk = None  # type: ignore


class Tooltip:
    """Attach to a widget with a string or callable(→str) text."""

    def __init__(self, master: tk.Misc, widget: tk.Misc, text, *,
                 delay_ms: int = 500,
                 wrap_length: int = 320,
                 bg: str = "#ffffcc",
                 fg: str = "#000000",
                 justify: str = "left"):
        self.widget = widget
        self.text_source = text
        self.delay_ms = int(delay_ms)
        self.wrap_length = int(wrap_length)
        self.bg = bg
        self.fg = fg
        self.justify = justify
        self._tip_window: Optional[tk.Toplevel] = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<ButtonPress>", self._on_leave, add="+")
        widget.bind("<Motion>", self._on_motion, add="+")

    # -- public --
    def show_now(self, x: int, y: int) -> None:
        self._cancel_after()
        self._create_tip(x, y)

    def hide(self) -> None:
        self._cancel_after()
        self._destroy_tip()

    # -- internals --
    def _resolve_text(self) -> str:
        if callable(self.text_source):
            try:
                return str(self.text_source())
            except Exception:  # noqa: BLE001
                return ""
        return "" if self.text_source is None else str(self.text_source)

    def _on_enter(self, _evt=None):
        self._cancel_after()
        self._after_id = self.widget.after(self.delay_ms, self._schedule_show)

    def _schedule_show(self):
        try:
            x = self.widget.winfo_pointerx() + 14
            y = self.widget.winfo_pointery() + 14
            self._create_tip(x, y)
        except Exception:  # noqa: BLE001
            pass

    def _on_leave(self, _evt=None):
        self.hide()

    def _on_motion(self, evt=None):
        if self._tip_window is not None and evt is not None:
            try:
                self._tip_window.geometry(f"+{evt.x_root + 14}+{evt.y_root + 14}")
            except Exception:  # noqa: BLE001
                pass

    def _cancel_after(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001
                pass
            self._after_id = None

    def _create_tip(self, x: int, y: int) -> None:
        self._destroy_tip()
        text = self._resolve_text()
        if not text:
            return
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:  # noqa: BLE001
            pass
        try:
            tw.tk.call("tk", "scaling", tw.winfo_fpixels("1i") / 72.0)
        except Exception:  # noqa: BLE001
            pass
        label = tk.Label(tw, text=text, justify=self.justify,
                         bg=self.bg, fg=self.fg, relief="solid", borderwidth=1,
                         wraplength=self.wrap_length, padx=6, pady=4)
        label.pack(ipadx=1)
        tw.update_idletasks()
        w = tw.winfo_width()
        h = tw.winfo_height()
        sw = tw.winfo_screenwidth()
        sh = tw.winfo_screenheight()
        x2 = x
        y2 = y
        if x2 + w > sw - 10:
            x2 = sw - w - 10
        if y2 + h > sh - 10:
            y2 = sh - h - 10
        tw.geometry(f"+{x2}+{y2}")
        self._tip_window = tw

    def _destroy_tip(self):
        if self._tip_window is not None:
            try:
                self._tip_window.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._tip_window = None
