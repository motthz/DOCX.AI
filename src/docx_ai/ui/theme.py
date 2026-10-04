from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

if sys.version_info >= (3, 9):
    pass
else:
    pass

try:
    from tkinter import ttk
except Exception:
    import ttk  # type: ignore


def _detect_dpi_scale(master: tk.Misc) -> float:
    scale = 1.0
    try:
        if sys.platform != "win32":
            try:
                _fb = master.winfo_fpixels("1i") / 72.0
                return max(_fb, 1.0)
            except Exception:
                return 1.0
    except Exception:
        pass
    try:
        import ctypes
        try:
            _shcore = ctypes.windll.shcore
            _monitor = _shcore.MonitorFromWindow(
                ctypes.windll.user32.GetDesktopWindow(), 0)
            _sf = ctypes.c_uint()
            if _shcore.GetScaleFactorForMonitor(
                    _monitor, ctypes.byref(_sf)) == 0:
                scale = _sf.value / 100.0
        except Exception:
            try:
                _hdc = ctypes.windll.user32.GetDC(0)
                _dpi = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, _hdc)
                if _dpi and _dpi > 0:
                    scale = _dpi / 96.0
            except Exception:
                pass
    except Exception:
        pass
    try:
        _fb = master.winfo_fpixels("1i") / 72.0
        scale = max(scale, _fb)
    except Exception:
        pass
    return max(scale, 1.0)


COLORS: Dict[str, str] = {
    "primary_50":  "#eff6ff",
    "primary_100": "#dbeafe",
    "primary_200": "#bfdbfe",
    "primary_300": "#93c5fd",
    "primary_400": "#60a5fa",
    "primary_500": "#3b82f6",
    "primary_600": "#2563eb",
    "primary_700": "#1d4ed8",
    "primary_800": "#1e40af",
    "primary_900": "#1e3a8a",

    "success_400": "#34d399",
    "success_500": "#10b981",
    "success_600": "#059669",
    "success_50":  "#ecfdf5",
    "success_700": "#047857",

    "warning_300": "#fcd34d",
    "warning_400": "#fbbf24",
    "warning_500": "#f59e0b",
    "warning_600": "#d97706",
    "warning_50":  "#fffbeb",
    "warning_100": "#fef3c7",
    "warning_700": "#b45309",

    "danger_400":  "#f87171",
    "danger_500":  "#ef4444",
    "danger_600":  "#dc2626",
    "danger_50":   "#fef2f2",
    "danger_700":  "#b91c1c",
    "danger_300":  "#fca5a5",
    "danger_800":  "#991b1b",

    "slate_50":  "#f8fafc",
    "slate_100": "#f1f5f9",
    "slate_200": "#e2e8f0",
    "slate_300": "#cbd5e1",
    "slate_400": "#94a3b8",
    "slate_500": "#64748b",
    "slate_600": "#475569",
    "slate_700": "#334155",
    "slate_800": "#1e293b",
    "slate_900": "#0f172a",
    "slate_950": "#020617",

    "indigo_500": "#6366f1",
    "indigo_600": "#4f46e5",
    "violet_500": "#8b5cf6",
    "violet_600": "#7c3aed",
    "pink_500":   "#ec4899",
    "amber_400":  "#fbbf24",

    "white":      "#ffffff",
    "black":      "#000000",

    "text":              "#1e293b",
    "muted":             "#64748b",
    "bg":                "#f8fafc",
    "card_bg":           "#ffffff",
    "header_start":      "#0f172a",
    "header_end":        "#1e40af",
    "text_white_muted":  "#dbeafe",
}

DARK_COLORS: Dict[str, str] = {
    **COLORS,  # default: ereditiamo tonalità non-semantiche, sovrascriviamo UI-base
    "text":              "#e2e8f0",
    "muted":             "#94a3b8",
    "bg":                "#0b1020",
    "card_bg":           "#111827",
    "header_start":      "#020617",
    "header_end":        "#1e3a8a",
    "text_white_muted":  "#93c5fd",
    "slate_50":  "#0f172a",
    "slate_100": "#111827",
    "slate_200": "#1f2937",
    "slate_300": "#334155",
    "slate_400": "#475569",
    "slate_500": "#64748b",
    "slate_600": "#94a3b8",
    "slate_700": "#cbd5e1",
    "slate_800": "#e2e8f0",
    "slate_900": "#f1f5f9",
    "slate_950": "#f8fafc",
}


FONT_FAMILY = "Segoe UI Variable" if sys.platform == "win32" else "Segoe UI"
FONT_FAMILY_MONO = "Consolas"

FONTS = {
    "display":      (FONT_FAMILY, 26, "bold"),
    "h1":           (FONT_FAMILY, 22, "bold"),
    "h2":           (FONT_FAMILY, 18, "bold"),
    "h3":           (FONT_FAMILY, 14, "bold"),
    "h4":           (FONT_FAMILY, 12, "bold"),
    "body":         (FONT_FAMILY, 10),
    "body_sm":      (FONT_FAMILY, 9),
    "body_bold":    (FONT_FAMILY, 10, "bold"),
    "body_sm_bold": (FONT_FAMILY, 9, "bold"),
    "mono":         (FONT_FAMILY_MONO, 9),
    "btn":          (FONT_FAMILY, 10, "bold"),
    "btn_lg":       (FONT_FAMILY, 11, "bold"),
    "badge":        (FONT_FAMILY, 8, "bold"),
    "title_bar":    (FONT_FAMILY, 13, "bold"),
}


def _hex_to_rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _rgb_to_hex(rgb: Tuple[float, float, float]) -> str:
    r, g, b = [max(0, min(255, int(round(v)))) for v in rgb]
    return f"#{r:02x}{g:02x}{b:02x}"


def mix_colors(c1: str, c2: str, t: float) -> str:
    a = _hex_to_rgb(c1)
    b = _hex_to_rgb(c2)
    return _rgb_to_hex((a[i] * (1 - t) + b[i] * t for i in range(3)))


def lighten(c: str, pct: float) -> str:
    """pct in 0..1 toward white"""
    return mix_colors(c, COLORS["white"], pct)


def darken(c: str, pct: float) -> str:
    """pct in 0..1 toward black"""
    return mix_colors(c, COLORS["black"], pct)


# ============================================================
# GRADIENT CANVAS — sfondo header/scrim
# ============================================================

class GradientCanvas(tk.Canvas):
    """Canvas that paints a horizontal or vertical gradient background."""

    def __init__(self, master,
                 color_a: str, color_b: str,
                 direction: str = "horizontal",
                 **kwargs):
        kwargs.setdefault("highlightthickness", 0)
        kwargs.setdefault("bd", 0)
        kwargs.setdefault("bg", color_a)
        super().__init__(master, **kwargs)
        self._ca = color_a
        self._cb = color_b
        self._dir = direction
        self._rect_id = None
        self.bind("<Configure>", self._redraw, add="+")
        self.after_idle(self._redraw)

    def set_colors(self, a: str, b: str) -> None:
        self._ca, self._cb = a, b
        self._redraw()

    def _redraw(self, *_args) -> None:
        try:
            w = max(self.winfo_width(), 1)
            h = max(self.winfo_height(), 1)
            if self._rect_id is not None:
                self.delete(self._rect_id)
            self._rect_id = self.create_rectangle(
                -2, -2, w + 2, h + 2, outline="", tags="bg")
            self.delete("band")
            # 96 bands are visually smooth; one rectangle per pixel made every
            # window resize redraw thousands of canvas items.
            steps = max(2, min(96, w if self._dir == "horizontal" else h))
            step_w = w / steps if self._dir == "horizontal" else w
            step_h = h / steps if self._dir == "vertical" else h
            for i in range(steps):
                t = i / max(steps - 1, 1)
                col = mix_colors(self._ca, self._cb, t)
                if self._dir == "horizontal":
                    x0 = i * step_w
                    self.create_rectangle(x0, 0, x0 + step_w + 1, h,
                                          outline="", fill=col, tags="band")
                else:
                    y0 = i * step_h
                    self.create_rectangle(0, y0, w, y0 + step_h + 1,
                                          outline="", fill=col, tags="band")
            self.tag_lower("bg")
        except tk.TclError:
            pass


# ============================================================
# ROUNDED CARD — ombra + angoli arrotondati via Canvas
# ============================================================

class RoundedCard(tk.Frame):
    """A card with soft shadow and rounded corners drawn via inner Canvas."""

    def __init__(self, master,
                 padding: int = 18,
                 radius: int = 14,
                 shadow: bool = True,
                 bg: Optional[str] = None,
                 border: Optional[str] = None,
                 accent: Optional[str] = None,
                 **kwargs):
        self._outer_bg = master.winfo_reqwidth()  # placeholder
        self._card_bg = bg or COLORS["white"]
        self._border = border or COLORS["slate_200"]
        self._accent = accent
        self._radius = radius
        self._shadow = shadow
        self._pad = padding

        outer_bg = None
        try:
            outer_bg = master.cget("background")
        except Exception:
            pass
        if outer_bg is None or outer_bg == "":
            outer_bg = COLORS["slate_100"]
        kwargs["bg"] = outer_bg
        kwargs["highlightthickness"] = 0
        kwargs["bd"] = 0
        super().__init__(master, **kwargs)

        self._outer_bg = outer_bg

        self._shadow_offset = 7 if shadow else 0
        self._shadow_blur_color = lighten(COLORS["slate_700"], 0.93)
        self._shadow_blur_color2 = lighten(COLORS["slate_700"], 0.86)
        self._shadow_blur_color3 = lighten(COLORS["slate_700"], 0.78)

        # The default Tk canvas size (~380x270) is only a starting point:
        # _on_content_grow then fits the card to its content (grow AND shrink).
        self.canvas = tk.Canvas(self, bg=outer_bg,
                                highlightthickness=0, bd=0,
                                highlightbackground=outer_bg)
        self.canvas.pack(fill="both", expand=True)

        self.inner = tk.Frame(self.canvas, bg=self._card_bg,
                              highlightthickness=0, bd=0)

        self.canvas.bind("<Configure>", self._redraw, add="+")
        self.after_idle(self._redraw)

        self.content = tk.Frame(self.inner, bg=self._card_bg,
                                padx=padding, pady=padding)
        self.content.pack(fill="both", expand=True)

        # Whenever the natural size of the user-provided content grows
        # (children packed), grow the Canvas so nothing is clipped.
        # The outer ScrollFrame will then provide scrolling if the card
        # grows beyond the visible viewport.
        self.content.bind("<Configure>", self._on_content_grow, add="+")

    def _on_content_grow(self, _e=None):
        try:
            pad_total = self._pad * 2
            shadow_off = self._shadow_offset
            needed_h = (self.content.winfo_reqheight() + pad_total
                        + shadow_off)
            # This is the *requested* size: the geometry manager may still
            # stretch the card (sticky/fill), but never below its content.
            if int(self.canvas.cget("height")) != needed_h:
                self.canvas.config(height=needed_h)
            needed_w = (self.content.winfo_reqwidth() + pad_total
                        + shadow_off + (14 if self._accent else 0))
            if int(self.canvas.cget("width")) != needed_w:
                self.canvas.config(width=needed_w)
        except Exception:
            pass

    def _draw_round_rect(self, c, x1, y1, x2, y2, r, fill, outline="", width=1):
        # Draw rounded rectangle as 4 arcs + 2 rects + 2 polys
        try:
            r = max(1, min(r, (x2 - x1) // 2 - 1, (y2 - y1) // 2 - 1))
            points = [
                x1 + r, y1, x2 - r, y1,
                x2, y1, x2, y1 + r,
                x2, y2 - r, x2, y2,
                x2 - r, y2, x1 + r, y2,
                x1, y2, x1, y2 - r,
                x1, y1 + r, x1, y1,
            ]
            return c.create_polygon(points, smooth=True, fill=fill,
                                    outline=outline, width=width)
        except Exception:
            return c.create_rectangle(x1, y1, x2, y2, fill=fill,
                                      outline=outline, width=width)

    def _redraw(self, *_e):
        try:
            c = self.canvas
            w = max(c.winfo_width(), 1)
            h = max(c.winfo_height(), 1)
            c.delete("all")

            off = self._shadow_offset
            r = self._radius
            # Soft shadow layers (3 concentric rounded rects, faded)
            if self._shadow:
                for i, (shrink, col) in enumerate(
                    [(0, self._shadow_blur_color),
                     (1, self._shadow_blur_color2),
                     (2, self._shadow_blur_color3)]):
                    sx1, sy1 = off - i + 2, off - i + 2
                    sx2, sy2 = w - shrink - 1, h - shrink - off + i
                    self._draw_round_rect(c, sx1, sy1, sx2, sy2, r, col, "")
            # Main card body
            bx1, by1 = 0, 0
            bx2, by2 = w - off - 1, h - off - 1
            self._draw_round_rect(c, bx1, by1, bx2, by2, r,
                                  self._card_bg, self._border, 1)
            # Accent stripe (left 4px rounded)
            if self._accent:
                stripe_h = by2 - by1 - r
                stripe_y1 = by1 + r // 2
                stripe_y2 = by1 + r // 2 + stripe_h
                self._draw_round_rect(c,
                                      bx1 + 6, stripe_y1,
                                      bx1 + 12, stripe_y2,
                                      r // 2, self._accent, "")
            # Place inner frame on canvas as window — never truncate the
            # natural content height; use the larger of allocated canvas
            # space vs content's requested size so widgets are never clipped
            # silently inside the card.
            avail_w = bx2 - bx1 - self._pad - (14 if self._accent else 0)
            avail_h = by2 - by1 - self._pad
            try:
                target_w = max(avail_w, self.inner.winfo_reqwidth())
                target_h = max(avail_h, self.inner.winfo_reqheight())
            except Exception:
                target_w = avail_w
                target_h = avail_h
            self.canvas.create_window(
                (bx1 + self._pad // 2 + (14 if self._accent else 0),
                 by1 + self._pad // 2),
                anchor="nw",
                window=self.inner,
                width=target_w,
                height=target_h,
            )
        except tk.TclError:
            pass

    def bind_click(self, callback: Callable, cursor: str = "hand2") -> None:
        for w in (self, self.canvas, self.inner, self.content):
            try:
                w.bind("<Button-1>", callback, add="+")
                w.config(cursor=cursor)
            except Exception:
                pass
        for child in self.content.winfo_children():
            try:
                child.bind("<Button-1>", callback, add="+")
                child.config(cursor=cursor)
            except Exception:
                pass

    def set_accent(self, accent: Optional[str]) -> None:
        self._accent = accent
        try:
            self._redraw()
        except Exception:
            pass

    def set_background(self, bg: str) -> None:
        self._card_bg = bg or COLORS["white"]
        try:
            self.inner.configure(bg=self._card_bg)
            self.content.configure(bg=self._card_bg)
        except Exception:
            pass
        try:
            self._redraw()
        except Exception:
            pass


# ============================================================
# HOVER ANIMATOR — stepwise color transition
# ============================================================

class HoverAnimator:
    """Applies smooth stepwise background / foreground transitions on hover."""

    STEP_MS = 25
    STEPS = 8

    def __init__(self):
        self._widgets: Dict[int, dict] = {}
        self._after_ids: Dict[int, Optional[str]] = {}

    def register(self, widget,
                 bg_idle: str, bg_hover: str,
                 fg_idle: Optional[str] = None, fg_hover: Optional[str] = None,
                 border_idle: Optional[str] = None, border_hover: Optional[str] = None,
                 cursor: str = "hand2") -> None:
        w_id = widget.winfo_id()
        info = {
            "widget": widget,
            "bg_idle": bg_idle, "bg_hover": bg_hover,
            "fg_idle": fg_idle, "fg_hover": fg_hover,
            "border_idle": border_idle, "border_hover": border_hover,
        }
        self._widgets[w_id] = info
        self._after_ids[w_id] = None
        widget.bind("<Enter>", lambda e, w=widget: self._start(w, True), add="+")
        widget.bind("<Leave>", lambda e, w=widget: self._start(w, False), add="+")
        try:
            widget.config(cursor=cursor)
        except Exception:
            pass
        try:
            widget.configure(background=bg_idle)
        except Exception:
            pass
        if fg_idle:
            try: widget.configure(foreground=fg_idle)
            except Exception: pass
        if border_idle:
            try: widget.configure(highlightbackground=border_idle)
            except Exception: pass

    def _cancel(self, w_id: int):
        old = self._after_ids.get(w_id)
        if old:
            try:
                self._widgets[w_id]["widget"].after_cancel(old)
            except Exception:
                pass
        self._after_ids[w_id] = None

    def _start(self, widget, to_hover: bool):
        w_id = widget.winfo_id()
        info = self._widgets.get(w_id)
        if not info:
            return
        self._cancel(w_id)
        info["step"] = 0
        info["to_hover"] = to_hover
        self._tick(w_id)

    def _tick(self, w_id: int):
        info = self._widgets.get(w_id)
        if not info:
            return
        info["step"] = info.get("step", 0) + 1
        t = info["step"] / self.STEPS
        if not info["to_hover"]:
            t = 1.0 - t
        t = max(0.0, min(1.0, t))
        w = info["widget"]
        try:
            w.configure(
                background=mix_colors(info["bg_idle"], info["bg_hover"], t))
        except Exception:
            pass
        if info["fg_idle"] and info["fg_hover"]:
            try:
                w.configure(
                    foreground=mix_colors(info["fg_idle"], info["fg_hover"], t))
            except Exception:
                pass
        if info["border_idle"] and info["border_hover"]:
            try:
                w.configure(highlightbackground=mix_colors(
                    info["border_idle"], info["border_hover"], t))
            except Exception:
                pass
        if info["step"] < self.STEPS:
            self._after_ids[w_id] = w.after(self.STEP_MS, lambda: self._tick(w_id))
        else:
            self._after_ids[w_id] = None

    def attach_circle(self, widget, accent: str) -> None:
        """Smooth hover effect for accent-colored icon circles (darken on hover)."""
        try:
            self.register(
                widget,
                bg_idle=accent,
                bg_hover=darken(accent, 0.12),
                cursor="hand2",
            )
        except Exception:
            pass

    def attach_card(self, widget, idle_bg: str, hover_bg: Optional[str] = None,
                    idle_border: Optional[str] = None,
                    hover_border: Optional[str] = None) -> None:
        """Smooth hover effect for cards (lighter bg + optionally darker border)."""
        try:
            self.register(
                widget,
                bg_idle=idle_bg,
                bg_hover=hover_bg if hover_bg is not None else lighten(idle_bg, 0.08),
                border_idle=idle_border,
                border_hover=hover_border,
                cursor="hand2",
            )
        except Exception:
            pass


# ============================================================
# TOAST MANAGER
# ============================================================

class ToastManager:
    """Shows brief notifications in the bottom-right corner."""

    DURATION_MS = 3000
    FADE_STEPS = 14
    STEP_MS = 30

    def __init__(self, root):
        self._root = root
        self._toasts: List[dict] = []
        self._container: Optional[tk.Frame] = None
        self._last_y: Dict[str, int] = {}
        try:
            self._dpi_scale = _detect_dpi_scale(root)
        except Exception:
            self._dpi_scale = 1.0

    def _wp(self, base_px: int) -> int:
        return max(int(round(base_px * self._dpi_scale)), base_px)

    def _ensure_container(self):
        if self._container is None or not self._container.winfo_exists():
            self._container = tk.Frame(self._root, bg=COLORS["white"],
                                       highlightthickness=0, bd=0)
        return self._container

    def show(self, message: str, kind: str = "info", icon: str = "ℹ️") -> None:
        kinds = {
            "info":    (COLORS["white"], COLORS["primary_600"], COLORS["slate_200"]),
            "success": (COLORS["success_50"], COLORS["success_600"], COLORS["success_500"]),
            "warning": (COLORS["warning_50"], COLORS["warning_600"], COLORS["warning_500"]),
            "error":   (COLORS["danger_50"],  COLORS["danger_600"],  COLORS["danger_500"]),
        }
        bg, accent, border = kinds.get(kind, kinds["info"])

        root = self._root
        try:
            root.update_idletasks()
        except Exception:
            pass
        rh = max(root.winfo_height(), 600)
        rw = max(root.winfo_width(), 900)

        outer = tk.Frame(root, bg=COLORS["white"], highlightthickness=0, bd=0)
        card = tk.Frame(outer, bg=bg,
                        highlightthickness=1,
                        highlightbackground=border, bd=0)
        card.pack(padx=10, pady=0, fill="x")

        left = tk.Frame(card, bg=accent, width=6, bd=0,
                        highlightthickness=0)
        left.pack(side="left", fill="y")

        lbl_icon = tk.Label(card, text=icon, bg=bg,
                            fg=accent,
                            font=(FONT_FAMILY, 14, "bold"),
                            padx=10, pady=10, bd=0,
                            highlightthickness=0)
        lbl_icon.pack(side="left", fill="y")

        lbl_msg = tk.Label(card, text=message, bg=bg,
                           fg=COLORS["slate_800"],
                           font=FONTS["body"],
                           justify="left", bd=0,
                           highlightthickness=0, anchor="w",
                           wraplength=self._wp(380), pady=10)
        lbl_msg.pack(side="left", fill="both", expand=True, padx=(0, 14))

        data = {
            "frame": outer, "card": card, "step": 0, "fading": False,
            "toplevel": None,
        }
        self._toasts.append(data)

        def lift_place():
            try:
                root.update_idletasks()
                outer.update_idletasks()
                w = outer.winfo_reqwidth() + 4
                h = outer.winfo_reqheight() + 4
                # Stack vertically: bottom-most first, new one on top
                idx = len(self._toasts) - self._toasts.index(data) - 1
                offset_y = 20 + idx * (h + 8)
                x = rw - w - 20
                y = rh - offset_y - 20
                outer.place(x=x, y=y, width=w - 10, anchor="nw")
                outer.tkraise()
            except Exception:
                pass
        lift_place()

        # Fade in via opacity workaround (win32): use color mixing repeatedly
        data["step"] = 0
        def fade_in_tick():
            try:
                data["step"] += 1
                if data["step"] < self.FADE_STEPS:
                    data["card"].after(self.STEP_MS, fade_in_tick)
                else:
                    data["card"].after(self.DURATION_MS, start_fade_out)
            except Exception:
                pass
        def start_fade_out():
            data["fading"] = True
            data["step"] = 0
            fade_out_tick()
        def fade_out_tick():
            try:
                data["step"] += 1
                t = data["step"] / self.FADE_STEPS
                # Visual fade-out: mix card bg toward root's (approx transparent)
                try:
                    root_bg = root.cget("background")
                except Exception:
                    root_bg = COLORS["white"]
                try:
                    card.configure(background=mix_colors(bg, root_bg, t))
                    left.configure(background=mix_colors(accent, root_bg, t))
                    lbl_icon.configure(background=mix_colors(bg, root_bg, t))
                    lbl_msg.configure(background=mix_colors(bg, root_bg, t))
                    lbl_msg.configure(foreground=mix_colors(
                        COLORS["slate_800"], root_bg, t))
                except Exception:
                    pass
                if data["step"] < self.FADE_STEPS:
                    data["card"].after(self.STEP_MS, fade_out_tick)
                else:
                    try:
                        outer.destroy()
                    except Exception:
                        pass
                    if data in self._toasts:
                        self._toasts.remove(data)
                    # Re-layout remaining
                    for t_ in self._toasts:
                        try: lift_place_single(t_)
                        except Exception: pass
            except Exception:
                try: outer.destroy()
                except Exception: pass
                if data in self._toasts: self._toasts.remove(data)

        def lift_place_single(d):
            try:
                root.update_idletasks()
                w = d["frame"].winfo_reqwidth() + 4
                h = d["frame"].winfo_reqheight() + 4
                idx = len(self._toasts) - self._toasts.index(d) - 1
                offset_y = 20 + idx * (h + 8)
                x = rw - w - 20
                y = rh - offset_y - 20
                d["frame"].place_configure(x=x, y=y)
            except Exception:
                pass
        fade_in_tick()


# ============================================================
# THEME — ttk Style configure
# ============================================================

@dataclass
class ThemeContext:
    style: ttk.Style
    hover: HoverAnimator
    toasts: ToastManager
    root: "tk.Misc"


class ModernTheme:
    def __init__(self, root, *, theme_name: str = "light"):
        self.root = root
        self.theme_name = "dark" if theme_name and theme_name.lower() == "dark" else "light"
        self.style = ttk.Style(root)
        try:
            self.style.theme_use("clam")
        except Exception:
            pass
        self.hover = HoverAnimator()
        self.toasts = ToastManager(root)
        self._configure_styles()

    # ------------------------------------------------------------------
    def current_colors(self) -> Dict[str, str]:
        return DARK_COLORS if self.theme_name == "dark" else COLORS

    def set_theme(self, theme_name: str, *, persist_db: Any = None) -> None:
        new = "dark" if theme_name and theme_name.lower() == "dark" else "light"
        if new == self.theme_name:
            return
        self.theme_name = new
        self._configure_styles()
        try:
            if persist_db is not None and hasattr(persist_db, "set_setting"):
                persist_db.set_setting("ui.theme", new)
        except Exception:  # noqa: BLE001
            pass
        # Propagate root bg / top-level defaults (best effort)
        try:
            c = self.current_colors()
            self.root.configure(bg=c["bg"])
        except Exception:  # noqa: BLE001
            pass

    def toggle_theme(self, *, persist_db: Any = None) -> str:
        other = "light" if self.theme_name == "dark" else "dark"
        self.set_theme(other, persist_db=persist_db)
        return self.theme_name

    # ------------------------------------------------------------------
    def _configure_styles(self):
        s = self.style
        c = self.current_colors()
        # FR13 sticky scrollbars: width=14 arrowsize=14
        try:
            s.configure("TScrollbar", arrowsize=14, width=14, gripcount=0)
            s.configure("Vertical.TScrollbar", width=14, arrowsize=14)
            s.configure("Horizontal.TScrollbar", arrowsize=14)
        except Exception:  # noqa: BLE001
            pass

        s.configure(".",
                    background=c["white"],
                    foreground=c["slate_800"],
                    font=FONTS["body"],
                    fieldbackground=c["white"],
                    borderwidth=0)

        # Root TFrame, TLabel defaults
        s.configure("TFrame", background=c["white"])
        s.configure("Card.TFrame", background=c["white"], relief="flat")
        s.configure("Sidebar.TFrame", background=c["slate_50"])
        s.configure("Subtle.TFrame", background=c["slate_100"])
        s.configure("Invisible.TFrame", background=c["slate_900"])

        s.configure("TLabel", background=c["white"],
                    foreground=c["slate_700"], font=FONTS["body"])

        # Title styles
        s.configure("Title.H1.TLabel", background=c["white"],
                    foreground=c["slate_900"], font=FONTS["h1"])
        s.configure("Title.H2.TLabel", background=c["white"],
                    foreground=c["slate_900"], font=FONTS["h2"])
        s.configure("Title.H3.TLabel", background=c["white"],
                    foreground=c["slate_900"], font=FONTS["h3"])
        s.configure("Title.H4.TLabel", background=c["white"],
                    foreground=c["slate_800"], font=FONTS["h4"])
        s.configure("Subtitle.TLabel", background=c["white"],
                    foreground=c["slate_500"], font=FONTS["body"])
        s.configure("Small.TLabel", background=c["white"],
                    foreground=c["slate_500"], font=FONTS["body_sm"])

        # On-dark labels
        s.configure("OnDark.TLabel", background=c["slate_900"],
                    foreground=c["slate_100"], font=FONTS["body"])
        s.configure("OnDark.Title.TLabel", background=c["slate_900"],
                    foreground=c["white"], font=FONTS["title_bar"])
        s.configure("OnDark.Small.TLabel", background=c["slate_900"],
                    foreground=c["slate_400"], font=FONTS["body_sm"])
        s.configure("OnDark.Badge.TLabel", background=c["slate_800"],
                    foreground=c["slate_200"], font=FONTS["badge"],
                    padding=(10, 4))

        # Hero button
        s.configure("Hero.TButton",
                    background=c["primary_600"],
                    foreground=c["white"],
                    font=FONTS["btn_lg"],
                    padding=(28, 16),
                    relief="flat",
                    borderwidth=0,
                    focusthickness=0)
        s.map("Hero.TButton",
              background=[("pressed", c["primary_800"]),
                          ("disabled", c["slate_300"])])

        # Accent standard
        s.configure("Accent.TButton",
                    background=c["primary_600"],
                    foreground=c["white"],
                    font=FONTS["btn"],
                    padding=(16, 9),
                    relief="flat",
                    borderwidth=0,
                    focusthickness=0)
        s.map("Accent.TButton",
              background=[("active", c["primary_700"]),
                          ("pressed", c["primary_800"]),
                          ("disabled", c["slate_300"])])

        # Success button
        s.configure("Success.TButton",
                    background=c["success_600"],
                    foreground=c["white"],
                    font=FONTS["btn"],
                    padding=(16, 9), relief="flat", borderwidth=0)
        s.map("Success.TButton",
              background=[("active", c["success_700"]),
                          ("disabled", c["slate_300"])])

        # Danger button
        s.configure("Danger.TButton",
                    background=c["danger_600"],
                    foreground=c["white"],
                    font=FONTS["btn"],
                    padding=(16, 9), relief="flat", borderwidth=0)
        s.map("Danger.TButton",
              background=[("active", c["danger_700"]),
                          ("disabled", c["slate_300"])])

        # Subtle / ghost button
        s.configure("Subtle.TButton",
                    background=c["white"],
                    foreground=c["slate_700"],
                    font=FONTS["btn"],
                    padding=(14, 8), relief="flat", borderwidth=0)
        s.map("Subtle.TButton",
              background=[("active", c["slate_100"]),
                          ("disabled", c["white"])])

        # Link button
        s.configure("Link.TButton",
                    background=c["white"],
                    foreground=c["primary_600"],
                    font=(FONT_FAMILY, 10, "underline"),
                    padding=(0, 0), relief="flat", borderwidth=0)
        s.map("Link.TButton",
              background=[("active", c["primary_50"])])

        # Entry
        s.configure("TEntry",
                    fieldbackground=c["white"],
                    foreground=c["slate_900"],
                    background=c["white"],
                    padding=(10, 8),
                    bordercolor=c["slate_300"],
                    lightcolor=c["slate_300"],
                    darkcolor=c["slate_300"],
                    focusthickness=2,
                    focuscolor=c["primary_500"],
                    arrowcolor=c["slate_600"],
                    font=FONTS["body"],
                    relief="flat",
                    borderwidth=1)

        # Combobox
        s.configure("TCombobox",
                    fieldbackground=c["white"],
                    background=c["white"],
                    foreground=c["slate_900"],
                    arrowcolor=c["slate_600"],
                    padding=(10, 8),
                    borderwidth=1,
                    relief="flat",
                    focusthickness=2,
                    focuscolor=c["primary_500"],
                    font=FONTS["body"])
        s.map("TCombobox",
              fieldbackground=[("readonly", c["white"]),
                               ("disabled", c["slate_100"])])

        # Labelframe
        s.configure("Card.TLabelframe",
                    background=c["white"],
                    foreground=c["slate_700"],
                    borderwidth=1,
                    relief="solid",
                    padding=14)
        s.configure("Card.TLabelframe.Label",
                    background=c["white"],
                    foreground=c["slate_700"],
                    font=FONTS["h4"])

        s.configure("TLabelframe",
                    background=c["white"],
                    foreground=c["slate_700"],
                    borderwidth=1,
                    relief="solid",
                    padding=10)
        s.configure("TLabelframe.Label",
                    background=c["white"],
                    foreground=c["slate_700"],
                    font=FONTS["h4"])

        # Checkbutton / Radiobutton
        s.configure("TCheckbutton",
                    background=c["white"],
                    foreground=c["slate_800"],
                    font=FONTS["body"],
                    padding=(2, 2))
        s.map("TCheckbutton",
              background=[("active", c["white"])],
              foreground=[("disabled", c["slate_400"])])
        s.configure("TRadiobutton",
                    background=c["white"],
                    foreground=c["slate_800"],
                    font=FONTS["body"],
                    padding=(2, 2))

        # Notebook (tabs)
        s.configure("TNotebook",
                    background=c["slate_100"],
                    borderwidth=0,
                    tabmargins=(0, 0, 0, 0))
        s.configure("TNotebook.Tab",
                    background=c["slate_100"],
                    foreground=c["slate_600"],
                    font=(FONT_FAMILY, 10, "bold"),
                    padding=(24, 12),
                    borderwidth=0)
        s.map("TNotebook.Tab",
              background=[("selected", c["white"]),
                          ("active", c["slate_200"]),
                          ("disabled", c["slate_100"])],
              foreground=[("selected", c["primary_600"]),
                          ("active", c["slate_800"])])

        s.configure("TNotebook.Tab.selected",
                    background=c["white"],
                    foreground=c["primary_600"])

        s.configure("Card.TNotebook",
                    background=c["white"],
                    borderwidth=0,
                    tabmargins=(0, 0, 0, 0))
        s.configure("Card.TNotebook.Tab",
                    background=c["slate_50"],
                    foreground=c["slate_500"],
                    font=(FONT_FAMILY, 10, "bold"),
                    padding=(20, 10),
                    borderwidth=0)
        s.map("Card.TNotebook.Tab",
              background=[("selected", c["white"]),
                          ("active", c["primary_50"])],
              foreground=[("selected", c["primary_600"])])

        # Progressbar
        s.configure("TProgressbar",
                    troughcolor=c["slate_200"],
                    background=c["primary_600"],
                    borderwidth=0,
                    thickness=10,
                    relief="flat")
        s.configure("Success.Horizontal.TProgressbar",
                    troughcolor=c["slate_200"],
                    background=c["success_500"],
                    thickness=10, borderwidth=0, relief="flat")

        # Separator
        s.configure("TSeparator", background=c["slate_200"])
        s.configure("OnDark.TSeparator", background=c["slate_800"])

        # Scrollbar — slim
        s.configure("Vertical.TScrollbar",
                    background=c["slate_200"],
                    troughcolor=c["slate_100"],
                    arrowcolor=c["slate_400"],
                    borderwidth=0, relief="flat",
                    width=10, arrowsize=10)
        s.map("Vertical.TScrollbar",
              background=[("active", c["primary_400"])])
        s.configure("Horizontal.TScrollbar",
                    background=c["slate_200"],
                    troughcolor=c["slate_100"],
                    arrowcolor=c["slate_400"],
                    borderwidth=0, relief="flat",
                    height=10, arrowsize=10)

        # Treeview — moduli / storico
        s.configure("Treeview",
                    background=c["white"],
                    fieldbackground=c["white"],
                    foreground=c["slate_800"],
                    font=FONTS["body"],
                    rowheight=30,
                    borderwidth=0,
                    relief="flat")
        s.configure("Treeview.Heading",
                    background=c["slate_100"],
                    foreground=c["slate_700"],
                    font=(FONT_FAMILY, 9, "bold"),
                    padding=(10, 8),
                    borderwidth=0,
                    relief="flat")
        s.map("Treeview",
              background=[("selected", c["primary_100"])],
              foreground=[("selected", c["primary_900"])])
        s.map("Treeview.Heading",
              background=[("active", c["slate_200"])])

        # Badge styles (to be used with ttk.Label framed look-alike via tk.Label)
        s.configure("Badge.Success.TLabel",
                    background=c["success_50"],
                    foreground=c["success_700"],
                    font=FONTS["badge"],
                    padding=(8, 4))
        s.configure("Badge.Warning.TLabel",
                    background=c["warning_50"],
                    foreground=c["warning_700"],
                    font=FONTS["badge"],
                    padding=(8, 4))
        s.configure("Badge.Danger.TLabel",
                    background=c["danger_50"],
                    foreground=c["danger_700"],
                    font=FONTS["badge"],
                    padding=(8, 4))
        s.configure("Badge.Info.TLabel",
                    background=c["primary_50"],
                    foreground=c["primary_700"],
                    font=FONTS["badge"],
                    padding=(8, 4))
        s.configure("Badge.Neutral.TLabel",
                    background=c["slate_100"],
                    foreground=c["slate_700"],
                    font=FONTS["badge"],
                    padding=(8, 4))

        # Sizegrip
        s.configure("TSizegrip", background=c["white"])

    # ------------------------------------------------------------------
    @staticmethod
    def text_widget_kwargs(multiline: bool = False,
                           background: Optional[str] = None,
                           ) -> dict:
        """ONLY constructor options accepted by tk.Entry / tk.Text.

        Geometry manager options like padx/pady must be passed to
        ``pack`` or ``grid`` separately — they cause TclError otherwise.
        """
        c = COLORS
        base = {
            "bg": background or c["white"],
            "fg": c["slate_900"],
            "font": FONTS["mono"] if multiline else FONTS["body"],
            "bd": 0,
            "highlightthickness": 1,
            "highlightbackground": c["slate_300"],
            "highlightcolor": c["primary_500"],
            "insertbackground": c["slate_900"],
            "selectbackground": c["primary_100"],
            "selectforeground": c["primary_900"],
            "relief": "flat",
        }
        if multiline:
            base["wrap"] = "word"
        return base

    @staticmethod
    def canvas_kwargs(background: Optional[str] = None) -> dict:
        return {
            "bg": background or COLORS["white"],
            "highlightthickness": 0,
            "bd": 0,
        }

    # ------------------------------------------------------------------
    def toast(self, msg: str, kind: str = "info", icon: str = "ℹ️"):
        try:
            self.root.update_idletasks()
        except Exception:
            pass
        self.toasts.show(msg, kind=kind, icon=icon)


# ============================================================
# Always-scrollable frame wrapper (module level)
# ============================================================

@dataclass
class ScrollFrame:
    outer: tk.Frame
    inner: tk.Frame
    canvas: tk.Canvas
    vsb: Optional[ttk.Scrollbar]
    hsb: Optional[ttk.Scrollbar]


def make_scrollable_frame(
    parent: tk.Misc,
    *,
    bg: str = COLORS["white"],
    horizontal: bool = False,
    vertical: bool = True,
    show_scrollbars: str = "auto",  # "auto" | "always" | "never"
    min_inner_width: int = 0,
) -> ScrollFrame:
    """Create a frame that is ALWAYS scrollable with a visible vertical bar.

    ``show_scrollbars``:
      - ``always``  → vertical scrollbar is always rendered (user request)
      - ``auto``    → shown only if inner larger than viewport (Tk default)
      - ``never``   → hidden (but MouseWheel still works via canvas binding)
    """
    outer = tk.Frame(parent, bg=bg, highlightthickness=0, bd=0)

    canvas = tk.Canvas(outer, bg=bg, highlightthickness=0, bd=0,
                       borderwidth=0)
    vsb = None
    hsb = None

    if vertical:
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
    if horizontal:
        hsb = ttk.Scrollbar(outer, orient="horizontal", command=canvas.xview)
        canvas.configure(xscrollcommand=hsb.set)

    # Always render vertical bar on the right side, regardless of need.
    if show_scrollbars == "always":
        if vsb is not None:
            vsb.pack(side="right", fill="y")
    elif show_scrollbars == "never":
        vsb = None

    canvas.pack(side="left", fill="both", expand=True)
    if show_scrollbars == "auto":
        if vsb is not None:
            vsb.pack(side="right", fill="y")
    if hsb is not None:
        hsb.pack(side="bottom", fill="x")

    inner = tk.Frame(canvas, bg=bg, highlightthickness=0, bd=0)
    inner_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _wheel(e):
        try:
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")
        except Exception:
            pass

    def _bind_mousewheel_recursive(widget):
        try:
            widget.bind("<MouseWheel>", _wheel, add="+")
        except Exception:
            pass
        for child in widget.winfo_children():
            try:
                child.bind("<MouseWheel>", _wheel, add="+")
            except Exception:
                pass
            _bind_mousewheel_recursive(child)

    _bind_mousewheel_recursive(outer)

    def _resize_inner(_e=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
        try:
            w = canvas.winfo_width()
            if w < 1:
                return
            target = w
            if min_inner_width and target < min_inner_width:
                target = min_inner_width
            canvas.itemconfigure(inner_id, width=target)
        except Exception:
            pass
        # New widgets may have been packed since the last bind pass
        # (e.g. cards, buttons, Text added AFTER make_scrollable_frame
        # returned).  Re-run the recursive wheel bind so every widget
        # inside .inner is covered.
        try:
            _bind_mousewheel_recursive(inner)
        except Exception:
            pass

    canvas.bind("<Configure>", _resize_inner, add="+")
    inner.bind(
        "<Configure>",
        lambda _e: _resize_inner(),
        add="+",
    )

    return ScrollFrame(outer=outer, inner=inner, canvas=canvas, vsb=vsb, hsb=hsb)


# ============================================================
# module-level apply_theme
# ============================================================

_INSTANCE: Optional[ModernTheme] = None


def apply_theme(root) -> ModernTheme:
    global _INSTANCE
    _INSTANCE = ModernTheme(root)
    return _INSTANCE


def get_theme() -> Optional[ModernTheme]:
    return _INSTANCE


# ============================================================
# Tooltip (hover popup) — lightweight, no extra windows if empty
# ============================================================

class Tooltip:
    """Mostra un piccolo popup giallo quando il mouse passa su un widget.

    Usage::

        Tooltip(btn, "Crea un nuovo modulo (Ctrl+N)")
        Tooltip(entry, "Cerca per nome o slug del modulo", delay=400)
    """

    def __init__(self,
                 widget: tk.Misc,
                 text: str,
                 delay: int = 500,
                 *,
                 bg: str = "#fff9c4",
                 fg: str = "#2b2b2b",
                 font: Tuple = ("Segoe UI", 9),
                 wraplength: int = 320):
        self.widget = widget
        self.text = text
        self.delay = max(100, int(delay))
        self._bg = bg
        self._fg = fg
        self._font = font
        self._wraplength = wraplength
        self._after_id: Optional[str] = None
        self._tip: Optional[tk.Toplevel] = None
        try:
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
            widget.bind("<ButtonPress>", self._on_leave, add="+")
        except Exception:
            pass

    def _on_enter(self, _e=None):
        self._cancel()
        self._after_id = self.widget.after(self.delay, self._show)

    def _on_leave(self, _e=None):
        self._cancel()

    def _cancel(self):
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
        if self._tip is not None:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self):
        try:
            w = self.widget
            x = w.winfo_rootx() + 14
            y = w.winfo_rooty() + w.winfo_height() + 6
            tip = tk.Toplevel(w)
            tip.wm_overrideredirect(True)
            try:
                tip.wm_attributes("-topmost", 1)
            except Exception:
                pass
            tip.configure(bg=self._bg)
            lab = tk.Label(tip, text=self.text, justify="left",
                           bg=self._bg, fg=self._fg, font=self._font,
                           padx=8, pady=4, bd=0,
                           wraplength=self._wraplength,
                           highlightthickness=1,
                           highlightbackground="#e8d95a")
            lab.pack()
            tip.update_idletasks()
            tw = tip.winfo_width()
            th = tip.winfo_height()
            sw = tip.winfo_screenwidth()
            sh = tip.winfo_screenheight()
            if x + tw + 8 > sw:
                x = sw - tw - 8
            if y + th + 8 > sh:
                y = w.winfo_rooty() - th - 6
            tip.geometry(f"+{max(4, x)}+{max(4, y)}")
            self._tip = tip
        except Exception:
            pass


# ============================================================
# center_window — centra un Toplevel sullo schermo principale
# ============================================================

def center_window(win: tk.Misc,
                  w: Optional[int] = None,
                  h: Optional[int] = None,
                  *,
                  max_w_ratio: float = 0.92,
                  max_h_ratio: float = 0.88) -> None:
    """Centra ``win`` sullo schermo; se w/h non dati usa richiesta naturale.

    Blocca anche la dimensione massima a ~90% dello schermo per evitare
    che dialoghi troppo alti escano fuori dal basso.
    """
    try:
        win.update_idletasks()
    except Exception:
        pass
    try:
        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
    except Exception:
        return
    if w is None:
        try:
            w = win.winfo_reqwidth()
        except Exception:
            w = 720
    if h is None:
        try:
            h = win.winfo_reqheight()
        except Exception:
            h = 520
    mw = int(max(360, sw * max_w_ratio))
    mh = int(max(260, sh * max_h_ratio))
    w = min(w, mw)
    h = min(h, mh)
    try:
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2 - 18)
        win.geometry(f"{int(w)}x{int(h)}+{int(x)}+{int(y)}")
    except Exception:
        pass


def bind_tooltip(widget: tk.Misc, text: str, **kwargs) -> Tooltip:
    """Alias compatto per Tooltip(...) → istanza creata con 1 riga."""
    return Tooltip(widget, text, **kwargs)

