"""Trascinamento: tessere interne all'app (DragController) e file da Esplora risorse.

DragController gestisce il "trascina e rilascia" tra widget della stessa finestra:
- una sorgente avvia il trascinamento dopo qualche pixel di movimento (un clic
  semplice resta un clic);
- durante il trascinamento un'etichetta segue il puntatore;
- il bersaglio sotto il puntatore riceve hover / leave / drop con le coordinate
  dello schermo, cosi' puo' evidenziare il punto esatto di rilascio.

I file trascinati da Esplora risorse usano tkinterdnd2 (facoltativo: se manca,
le zone di rilascio restano pulsanti "Scegli file…").
"""

from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import customtkinter as ctk

from .design import col, font

DRAG_THRESHOLD = 6


class DragController:
    def __init__(self, toplevel: tk.Misc):
        self.top = toplevel
        self.targets: List[Dict[str, Any]] = []
        self._pending: Optional[Dict[str, Any]] = None
        self._ghost: Optional[tk.Toplevel] = None
        self._hover: Optional[Dict[str, Any]] = None
        self.dragging = False
        toplevel.bind("<Escape>", self._escape, add="+")

    # ------------------------------------------------------------ registrazione
    def add_target(self, widget: tk.Misc, *, hover: Callable[[int, int, Any], bool],
                   drop: Callable[[int, int, Any], None], leave: Optional[Callable[[], None]] = None) -> None:
        self.targets.append({"w": widget, "hover": hover, "drop": drop, "leave": leave})

    def add_source(self, widget: tk.Misc, payload: Any, ghost_text: str, *,
                   on_click: Optional[Callable[[], None]] = None) -> None:
        """Rende trascinabile ``widget`` (e i suoi figli: i widget CTk sono composti)."""
        for w in [widget, *_descendants(widget)]:
            try:
                w.bind("<ButtonPress-1>", lambda e: self.press(e, payload, ghost_text, on_click), add="+")
                w.bind("<B1-Motion>", self.motion, add="+")
                w.bind("<ButtonRelease-1>", self.release, add="+")
                w.configure(cursor="hand2")
            except (tk.TclError, ValueError, NotImplementedError):
                pass

    # ------------------------------------------------------------ ciclo di trascinamento
    def press(self, event, payload: Any, ghost_text: str, on_click: Optional[Callable[[], None]] = None) -> None:
        self._pending = {"x": event.x_root, "y": event.y_root, "payload": payload, "text": ghost_text,
                         "click": on_click}

    def motion(self, event) -> Optional[str]:
        p = self._pending
        if p is None:
            return None
        if not self.dragging:
            if abs(event.x_root - p["x"]) + abs(event.y_root - p["y"]) < DRAG_THRESHOLD:
                return "break"
            self.dragging = True
            self._make_ghost(p["text"])
        self._move_ghost(event.x_root, event.y_root)
        target = self._target_at(event.x_root, event.y_root)
        if self._hover is not None and self._hover is not target and self._hover["leave"]:
            self._hover["leave"]()
        self._hover = target
        ok = bool(target and target["hover"](event.x_root, event.y_root, p["payload"]))
        self._style_ghost(ok)
        return "break"

    def release(self, event) -> Optional[str]:
        p, was_dragging = self._pending, self.dragging
        self._pending = None
        self.dragging = False
        self._destroy_ghost()
        target, self._hover = self._hover, None
        if p is None:
            return None
        if not was_dragging:
            if p["click"]:
                p["click"]()
            return None
        if target is not None and target["leave"]:
            target["leave"]()
        target = self._target_at(event.x_root, event.y_root)
        if target is not None:
            target["drop"](event.x_root, event.y_root, p["payload"])
        return "break"

    def cancel(self) -> None:
        if self._hover is not None and self._hover["leave"]:
            self._hover["leave"]()
        self._hover = None
        self._pending = None
        self.dragging = False
        self._destroy_ghost()

    def _escape(self, _e=None) -> Optional[str]:
        if self.dragging:
            self.cancel()
            return "break"
        return None

    def _target_at(self, x: int, y: int) -> Optional[Dict[str, Any]]:
        try:
            under = self.top.winfo_containing(x, y)
        except (tk.TclError, KeyError):
            return None
        if under is None:
            return None
        path = str(under)
        best = None
        for t in self.targets:
            try:
                wp = str(t["w"])
                if not t["w"].winfo_exists():
                    continue
            except tk.TclError:
                continue
            if path == wp or path.startswith(wp + "."):
                if best is None or len(wp) > len(str(best["w"])):
                    best = t
        return best

    # ------------------------------------------------------------ etichetta che segue il puntatore
    def _make_ghost(self, text: str) -> None:
        g = tk.Toplevel(self.top)
        g.overrideredirect(True)
        try:
            g.attributes("-topmost", True)
            g.attributes("-alpha", 0.92)
        except tk.TclError:
            pass
        lbl = tk.Label(g, text="  " + text + "  ", font=font("body_b"), bg=col("primary"), fg="#ffffff",
                       padx=8, pady=5, bd=0)
        lbl.pack()
        self._ghost = g
        self._ghost_lbl = lbl

    def _style_ghost(self, ok: bool) -> None:
        if self._ghost is not None:
            self._ghost_lbl.configure(bg=col("primary") if ok else col("text_faint"))

    def _move_ghost(self, x: int, y: int) -> None:
        if self._ghost is not None:
            self._ghost.geometry(f"+{x + 14}+{y + 12}")

    def _destroy_ghost(self) -> None:
        if self._ghost is not None:
            try:
                self._ghost.destroy()
            except tk.TclError:
                pass
            self._ghost = None


def _descendants(w: tk.Misc) -> List[tk.Misc]:
    out: List[tk.Misc] = []
    for c in w.winfo_children():
        out.append(c)
        out.extend(_descendants(c))
    return out


# ---------------------------------------------------------------- file da Esplora risorse
_DND_READY: Optional[bool] = None


def file_drop_available(root: tk.Misc) -> bool:
    """True se e' possibile trascinare file da Esplora risorse nella finestra."""
    global _DND_READY
    if _DND_READY is None:
        try:
            from tkinterdnd2 import TkinterDnD
            TkinterDnD._require(root.winfo_toplevel())
            _DND_READY = True
        except Exception:  # noqa: BLE001 - libreria o estensione Tcl assente: si usa "Scegli file…"
            _DND_READY = False
    return _DND_READY


def split_dropped(data: str) -> List[Path]:
    """Percorsi dall'evento di rilascio di tkdnd ("{C:/con spazi/a.docx} C:/b.xlsx")."""
    items = re.findall(r"\{([^}]*)\}|(\S+)", data or "")
    return [Path(a or b) for a, b in items if (a or b)]


def enable_file_drop(widget: tk.Misc, on_files: Callable[[List[Path]], None], *,
                     on_enter: Optional[Callable[[], None]] = None,
                     on_leave: Optional[Callable[[], None]] = None) -> bool:
    """Accetta file trascinati da Esplora risorse su ``widget``. False se non disponibile."""
    if not file_drop_available(widget):
        return False
    try:
        from tkinterdnd2 import COPY, DND_FILES
        widget.drop_target_register(DND_FILES)  # type: ignore[attr-defined]

        def _drop(e):
            if on_leave:
                on_leave()
            files = split_dropped(e.data)
            if files:
                widget.after(10, lambda: on_files(files))
            return COPY

        def _enter(e):
            if on_enter:
                on_enter()
            return COPY

        def _leave(e):
            if on_leave:
                on_leave()

        widget.dnd_bind("<<Drop>>", _drop)  # type: ignore[attr-defined]
        widget.dnd_bind("<<DropEnter>>", _enter)  # type: ignore[attr-defined]
        widget.dnd_bind("<<DropLeave>>", _leave)  # type: ignore[attr-defined]
        return True
    except Exception:  # noqa: BLE001
        return False


class FileDropZone(ctk.CTkFrame):
    """Riquadro "Trascina qui il file, oppure Scegli file…"."""

    def __init__(self, parent, text: str, hint: str, button_text: str, on_files: Callable[[List[Path]], None],
                 on_pick: Callable[[], None], icon_name: str = "upload", height: int = 150):
        from .design import C
        from .icons import icon
        from .widgets import button
        super().__init__(parent, fg_color=C["surface_alt"], border_width=2, border_color=C["border"],
                         corner_radius=12, height=height)
        self._C = C
        inner = ctk.CTkFrame(self, fg_color="transparent")
        inner.place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(inner, text="", image=icon(icon_name, 30, "primary")).pack()
        self.title = ctk.CTkLabel(inner, text=text, font=font("body_b"), text_color=C["text"])
        self.title.pack(pady=(4, 0))
        self.hint = ctk.CTkLabel(inner, text=hint, font=font("small"), text_color=C["text_muted"])
        self.hint.pack()
        button(inner, button_text, on_pick, icon_name="folder-open", height=30).pack(pady=(8, 0))
        self.drop_enabled = enable_file_drop(self, on_files, on_enter=lambda: self.highlight(True),
                                             on_leave=lambda: self.highlight(False))
        for w in (inner, *inner.winfo_children()):
            if self.drop_enabled:
                enable_file_drop(w, on_files, on_enter=lambda: self.highlight(True),
                                 on_leave=lambda: self.highlight(False))

    def highlight(self, on: bool) -> None:
        C = self._C
        self.configure(border_color=C["primary"] if on else C["border"],
                       fg_color=C["primary_soft"] if on else C["surface_alt"])
