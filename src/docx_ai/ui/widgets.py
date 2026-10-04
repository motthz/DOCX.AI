"""Componenti riutilizzabili dell'interfaccia (CustomTkinter)."""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import customtkinter as ctk

from .design import C, GAP, PAD, RADIUS, col, font
from .icons import icon
from .i18n import t

# ---------------------------------------------------------------- pulsanti
_BTN = {
    "primary":   dict(fg_color=C["primary"], hover_color=C["primary_hover"], text_color=C["on_primary"],
                      border_width=0),
    "secondary": dict(fg_color=C["surface"], hover_color=C["surface_alt"], text_color=C["text"],
                      border_width=1, border_color=C["border"]),
    "ghost":     dict(fg_color="transparent", hover_color=C["selection"], text_color=C["text"],
                      border_width=0),
    "danger":    dict(fg_color=C["danger"], hover_color=("#991b1b", "#ef4444"), text_color=("#ffffff", "#1a0606"),
                      text_color_disabled=("#fca5a5", "#7f1d1d"), border_width=0),
    "success":   dict(fg_color=C["success"], hover_color=("#065f46", "#10b981"), text_color=("#ffffff", "#04210f"),
                      border_width=0),
}


def button(parent, text: str, command: Optional[Callable] = None, *, kind: str = "secondary",
           icon_name: Optional[str] = None, height: int = 34, width: int = 0, **kw) -> ctk.CTkButton:
    style = dict(_BTN[kind])
    style.update(kw)
    img = None
    if icon_name:
        img = icon(icon_name, 16, "white" if kind in ("primary", "danger", "success") else "auto")
    return ctk.CTkButton(parent, text=text, command=command, image=img, height=height,
                         width=width or 0, corner_radius=8, font=font("body_b"), **style)


# ---------------------------------------------------------------- card
class Card(ctk.CTkFrame):
    def __init__(self, parent, *, padding: int = PAD, soft: bool = False, **kw):
        kw.setdefault("fg_color", C["surface_alt"] if soft else C["surface"])
        kw.setdefault("border_color", C["border"])
        kw.setdefault("border_width", 1)
        kw.setdefault("corner_radius", RADIUS)
        super().__init__(parent, **kw)
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        self.body.pack(fill="both", expand=True, padx=padding, pady=padding)


def title(parent, text: str, subtitle: str = "", *, size: str = "h1") -> ctk.CTkFrame:
    box = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(box, text=text, font=font(size), text_color=C["text"], anchor="w").pack(anchor="w")
    if subtitle:
        lbl = ctk.CTkLabel(box, text=subtitle, font=font("body"), text_color=C["text_muted"],
                           anchor="w", justify="left", wraplength=900)
        lbl.pack(anchor="w", pady=(2, 0), fill="x")
        _autowrap(lbl, box)
    return box


def _autowrap(label: ctk.CTkLabel, container: tk.Misc, margin: int = 8) -> None:
    def _on(e):
        w = max(e.width - margin, 120)
        try:
            label.configure(wraplength=w)
        except tk.TclError:
            pass
    container.bind("<Configure>", _on, add="+")


def label(parent, text: str = "", *, kind: str = "body", muted: bool = False, **kw) -> ctk.CTkLabel:
    kw.setdefault("anchor", "w")
    kw.setdefault("justify", "left")
    kw.setdefault("text_color", C["text_muted"] if muted else C["text"])
    return ctk.CTkLabel(parent, text=text, font=font(kind), **kw)


class Chip(ctk.CTkLabel):
    TONES = {
        "neutral": (C["surface_alt"], C["text_muted"]),
        "info":    (C["info_soft"], C["link"]),
        "success": (C["success_soft"], C["success"]),
        "warning": (C["warning_soft"], C["warning"]),
        "danger":  (C["danger_soft"], C["danger"]),
    }

    def __init__(self, parent, text: str, tone: str = "neutral", **kw):
        bg, fg = self.TONES.get(tone, self.TONES["neutral"])
        super().__init__(parent, text=f" {text} ", fg_color=bg, text_color=fg, corner_radius=10,
                         font=font("small_b"), height=24, **kw)

    def set(self, text: str, tone: str) -> None:
        bg, fg = self.TONES.get(tone, self.TONES["neutral"])
        self.configure(text=f" {text} ", fg_color=bg, text_color=fg)


# ---------------------------------------------------------------- statistiche
class StatCard(Card):
    def __init__(self, parent, icon_name: str, caption: str, accent: Tuple[str, str], **kw):
        super().__init__(parent, padding=14, **kw)
        row = ctk.CTkFrame(self.body, fg_color="transparent")
        row.pack(fill="x")
        badge = ctk.CTkLabel(row, text="", image=icon(icon_name, 22, "auto"), width=44, height=44,
                             corner_radius=22, fg_color=C["primary_soft"])
        badge.pack(side="left")
        col_ = ctk.CTkFrame(row, fg_color="transparent")
        col_.pack(side="left", padx=(12, 0), fill="x", expand=True)
        self.value = ctk.CTkLabel(col_, text="—", font=font("h2"), text_color=accent, anchor="w")
        self.value.pack(anchor="w")
        ctk.CTkLabel(col_, text=caption, font=font("small"), text_color=C["text_muted"],
                     anchor="w").pack(anchor="w")

    def set(self, value: str) -> None:
        self.value.configure(text=value)


# ---------------------------------------------------------------- stato vuoto
class EmptyState(ctk.CTkFrame):
    def __init__(self, parent, icon_name: str, heading: str, text: str,
                 action: Optional[Tuple[str, Callable]] = None, **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        circle = ctk.CTkLabel(self, text="", image=icon(icon_name, 40, "primary"), width=88, height=88,
                              corner_radius=44, fg_color=C["primary_soft"])
        circle.pack(pady=(24, 12))
        ctk.CTkLabel(self, text=heading, font=font("h3"), text_color=C["text"]).pack()
        ctk.CTkLabel(self, text=text, font=font("body"), text_color=C["text_muted"],
                     wraplength=420, justify="center").pack(pady=(4, 12))
        if action:
            button(self, action[0], action[1], kind="primary", icon_name="plus").pack(pady=(0, 24))


# ---------------------------------------------------------------- barra schede
class TabBar(ctk.CTkFrame):
    """Schede con indicatore sottolineato che scorre (animato) sotto quella attiva."""

    def __init__(self, parent, items: Sequence[Tuple[str, str, str]],
                 on_select: Callable[[str], None], **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._on_select = on_select
        self._buttons: Dict[str, ctk.CTkButton] = {}
        self.current: Optional[str] = None
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x")
        for key, text, icon_name in items:
            b = ctk.CTkButton(row, text=text, image=icon(icon_name, 16), compound="left",
                              fg_color="transparent", hover_color=C["selection"], text_color=C["text_muted"],
                              font=font("body_b"), height=38, corner_radius=8, width=0,
                              command=lambda k=key: self.select(k))
            b.pack(side="left", padx=(0, 4))
            b.bind("<Configure>", lambda e: self._place_bar(animate=False), add="+")
            self._buttons[key] = b
        self._track = tk.Canvas(self, height=3, highlightthickness=0, bd=0, bg=col("bg"))
        self._track.pack(fill="x")
        self._bar = self._track.create_rectangle(0, 0, 0, 3, width=0, fill=col("primary"))
        self._anim: Optional[str] = None
        self.bind("<Configure>", lambda e: self._place_bar(animate=False), add="+")

    def keys(self) -> List[str]:
        return list(self._buttons)

    def select(self, key: str, *, notify: bool = True) -> None:
        if key not in self._buttons:
            return
        self.current = key
        for k, b in self._buttons.items():
            b.configure(text_color=C["link"] if k == key else C["text_muted"])
        self._place_bar(animate=True)
        if notify:
            self._on_select(key)

    def refresh_colors(self) -> None:
        self._track.configure(bg=col("bg"))
        self._track.itemconfigure(self._bar, fill=col("primary"))

    def _target(self) -> Tuple[int, int]:
        b = self._buttons.get(self.current or "")
        if b is None:
            return 0, 0
        x = b.winfo_x() + b.master.winfo_x()
        return x + 6, x + b.winfo_width() - 6

    def _place_bar(self, animate: bool) -> None:
        x1, x2 = self._target()
        if self._anim:
            self.after_cancel(self._anim)
            self._anim = None
        if not animate:
            self._track.coords(self._bar, x1, 0, x2, 3)
            return
        sx1, _, sx2, _ = self._track.coords(self._bar)
        if sx2 - sx1 < 2:  # primo posizionamento: nessuna animazione da zero
            self._track.coords(self._bar, x1, 0, x2, 3)
            return

        def step(i: int = 1, n: int = 8):
            k = 1 - (1 - i / n) ** 3  # ease-out
            self._track.coords(self._bar, sx1 + (x1 - sx1) * k, 0, sx2 + (x2 - sx2) * k, 3)
            if i < n:
                self._anim = self.after(16, lambda: step(i + 1, n))
            else:
                self._anim = None
        step()


# ---------------------------------------------------------------- stepper fasi
class Stepper(ctk.CTkFrame):
    """Indicatore di avanzamento per fasi (in attesa / in corso / ok / errore)."""

    STATE_ICON = {"todo": "circle-dot", "run": "loader-circle", "ok": "circle-check", "err": "circle-x"}
    STATE_COLOR = {"todo": C["text_faint"], "run": C["link"], "ok": C["success"], "err": C["danger"]}

    def __init__(self, parent, steps: Sequence[str], **kw):
        kw.setdefault("fg_color", "transparent")
        super().__init__(parent, **kw)
        self._items: List[Tuple[ctk.CTkLabel, ctk.CTkLabel]] = []
        for i, name in enumerate(steps):
            if i:
                ctk.CTkFrame(self, height=2, width=24, fg_color=C["border"]).pack(side="left", padx=4)
            ic = ctk.CTkLabel(self, text="", image=icon("circle-dot", 16), width=18)
            ic.pack(side="left")
            lb = ctk.CTkLabel(self, text=name, font=font("small_b"), text_color=C["text_faint"])
            lb.pack(side="left", padx=(4, 0))
            self._items.append((ic, lb))

    def set(self, index: int, state: str) -> None:
        ic, lb = self._items[index]
        tone = {"ok": "auto", "err": "auto", "run": "primary"}.get(state, "auto")
        ic.configure(image=icon(self.STATE_ICON[state], 16, tone))
        lb.configure(text_color=self.STATE_COLOR[state])

    def reset(self) -> None:
        for i in range(len(self._items)):
            self.set(i, "todo")


# ---------------------------------------------------------------- toast
class Toasts:
    """Notifiche in basso a destra, con dissolvenza e azione opzionale."""

    KIND_ICON = {"info": "info", "success": "circle-check", "warning": "triangle-alert", "error": "circle-x"}
    KIND_COLOR = {"info": C["primary"], "success": C["success"], "warning": C["warning"], "error": C["danger"]}

    def __init__(self, root: tk.Misc):
        self.root = root
        self._stack: List[ctk.CTkToplevel] = []

    def show(self, message: str, kind: str = "info", *_legacy, action: Optional[Tuple[str, Callable]] = None,
             duration_ms: int = 4200) -> None:
        try:
            top = ctk.CTkToplevel(self.root)
        except tk.TclError:
            return
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-alpha", 0.0)
        except tk.TclError:
            pass
        frame = ctk.CTkFrame(top, fg_color=C["surface"], border_color=self.KIND_COLOR.get(kind, C["primary"]),
                             border_width=2, corner_radius=10)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text="", image=icon(self.KIND_ICON.get(kind, "info"), 18)).pack(
            side="left", padx=(12, 6), pady=10)
        ctk.CTkLabel(frame, text=message, font=font("body"), text_color=C["text"], wraplength=320,
                     justify="left").pack(side="left", padx=(0, 10), pady=10)
        if action:
            def _act():
                self._close(top)
                action[1]()
            ctk.CTkButton(frame, text=action[0], command=_act, width=0, height=28, font=font("small_b"),
                          fg_color=C["primary_soft"], text_color=C["link"], hover_color=C["selection"]
                          ).pack(side="left", padx=(0, 10))
            duration_ms = max(duration_ms, 7000)
        top.bind("<Button-1>", lambda e: self._close(top))
        self._stack.append(top)
        self._layout()
        self._fade(top, 0.0, 0.97, 0.12)
        top.after(duration_ms, lambda: self._fade(top, 0.97, 0.0, -0.12, then=lambda: self._close(top)))

    def _fade(self, top, a, end, stepv, then=None):
        try:
            if not top.winfo_exists():
                return
            a = max(0.0, min(1.0, a + stepv))
            top.attributes("-alpha", a)
            if (stepv > 0 and a < end) or (stepv < 0 and a > end):
                top.after(16, lambda: self._fade(top, a, end, stepv, then))
            elif then:
                then()
        except tk.TclError:
            pass

    def _close(self, top) -> None:
        if top in self._stack:
            self._stack.remove(top)
        try:
            top.destroy()
        except tk.TclError:
            pass
        self._layout()

    def _layout(self) -> None:
        try:
            self.root.update_idletasks()
            rx = self.root.winfo_rootx() + self.root.winfo_width()
            ry = self.root.winfo_rooty() + self.root.winfo_height()
        except tk.TclError:
            return
        y = ry - 48
        for top in reversed(self._stack):
            try:
                top.update_idletasks()
                w, h = top.winfo_reqwidth(), top.winfo_reqheight()
                y -= h + 8
                top.geometry(f"+{rx - w - 24}+{y}")
            except tk.TclError:
                pass


def scrollable(parent, **kw) -> ctk.CTkScrollableFrame:
    kw.setdefault("fg_color", "transparent")
    return ctk.CTkScrollableFrame(parent, **kw)


def separator(parent) -> ctk.CTkFrame:
    return ctk.CTkFrame(parent, height=1, fg_color=C["border"])


def section(parent, heading: str, sub: str = "") -> ctk.CTkFrame:
    f = ctk.CTkFrame(parent, fg_color="transparent")
    ctk.CTkLabel(f, text=heading, font=font("h4"), text_color=C["text"], anchor="w").pack(anchor="w")
    if sub:
        ctk.CTkLabel(f, text=sub, font=font("small"), text_color=C["text_muted"], anchor="w",
                     justify="left", wraplength=560).pack(anchor="w")
    return f


__all__ = ["button", "Card", "title", "label", "Chip", "StatCard", "EmptyState", "TabBar", "Stepper",
           "Toasts", "scrollable", "separator", "section", "t", "GAP", "PAD"]
