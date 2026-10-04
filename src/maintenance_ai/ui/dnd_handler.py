"""Drag-and-drop handler for document upload.

- Try optional tkinterdnd2 (pip dependency — if missing, silent fallback)
- Fallback: clickable area with label "Trascina file qui o clicca per sfogliare"
- Filters extensions against config.allowed_extensions_input + blocked_extensions
- Rejects blocked extensions with messagebox showwarning
- Emits `on_file_received(paths: List[Path])` callback

Integrated in MainWindow "Documenti" tab.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Callable, List, Optional, Set

try:
    from tkinter import ttk
except Exception:  # noqa: BLE001
    ttk = None  # type: ignore

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore
    _DND_AVAILABLE = True
except Exception:  # noqa: BLE001
    _DND_AVAILABLE = False
    DND_FILES = None  # type: ignore
    TkinterDnD = None  # type: ignore


class DragDropHandlerFrame(ttk.Frame if ttk else tk.Frame):
    """Drop zone + fallback click-to-browse."""

    def __init__(self, master, *,
                 allowed_extensions: Optional[Set[str]] = None,
                 blocked_extensions: Optional[Set[str]] = None,
                 on_file_received: Optional[Callable[[List[Path]], None]] = None,
                 title: str = "Documenti di riferimento",
                 prompt: str = "Trascina i file (.docx / .xlsx) qui, oppure clicca per sfogliare…"):
        super().__init__(master, relief="ridge", borderwidth=2)
        self._allowed = set(allowed_extensions or {".docx", ".xlsx"})
        self._blocked = set(blocked_extensions or set())
        self._callback = on_file_received
        # Title label
        if ttk is not None:
            ttk.Label(self, text=title, style="Title.H4.TLabel").pack(anchor="w", padx=12, pady=(8, 2))
        else:
            tk.Label(self, text=title, font=("Segoe UI", 11, "bold")).pack(anchor="w", padx=12, pady=(8, 2))
        # Drop area
        self._drop = tk.Frame(self, bg="#eff6ff", highlightthickness=2,
                              highlightbackground="#93c5fd", cursor="hand2")
        self._drop.pack(fill="x", padx=12, pady=(0, 12))
        self._drop_lbl = tk.Label(self._drop, text=prompt, bg="#eff6ff",
                                  fg="#1e40af", font=("Segoe UI", 10, "bold"),
                                  pady=18, padx=10, wraplength=720, justify="center")
        self._drop_lbl.pack(fill="x")
        self._drop.bind("<Button-1>", self._on_click)
        self._drop_lbl.bind("<Button-1>", self._on_click)
        # Drop handlers if tkinterdnd2 is available
        if _DND_AVAILABLE:
            for w in (self, self._drop, self._drop_lbl):
                try:
                    w.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
                    w.dnd_bind("<<Drop>>", self._on_dnd_drop)  # type: ignore[attr-defined]
                except Exception:  # noqa: BLE001
                    pass
            if hasattr(self, "drop_target_register"):
                try:
                    self.drop_target_register(DND_FILES)
                    self.dnd_bind("<<Drop>>", self._on_dnd_drop)
                except Exception:  # noqa: BLE001
                    pass
        else:
            # If tkinterdnd2 unavailable, change prompt slightly to mention click
            alt = (prompt +
                   "\n\n(note: il drag&drop nativo è disponibile installando `pip install tkinterdnd2`, "
                   "altrimenti usa il tasto clicca qui.)")
            self._drop_lbl.configure(text=alt)
        # Small helper: list of recently added filenames
        self._recent = ttk.Frame(self) if ttk is not None else tk.Frame(self)
        self._recent.pack(fill="x", padx=12, pady=(0, 12))
        self._recent_lbl = (ttk.Label(self._recent, text="Nessun file importato in questa sessione.",
                                      style="Subtle.TLabel")
                            if ttk else tk.Label(self._recent, text="Nessun file importato."))
        self._recent_lbl.pack(anchor="w")

    # --------------------------------------------------------------
    @property
    def dnd_available(self) -> bool:
        return _DND_AVAILABLE

    # --------------------------------------------------------------
    def _on_click(self, _evt=None):
        try:
            from tkinter import filedialog
        except Exception:  # noqa: BLE001
            return
        allowed = []
        for e in self._allowed:
            upper = e.lstrip(".").upper()
            allowed.append((f"{upper} documents", f"*{e}"))
        allowed.append(("Tutti i file supportati",
                        " ".join(f"*{e}" for e in sorted(self._allowed))))
        files = filedialog.askopenfilenames(parent=self.winfo_toplevel(),
                                            title="Seleziona documenti di riferimento",
                                            filetypes=allowed)
        if files:
            paths = [Path(f) for f in files]
            self._handle_paths(paths)

    def _on_dnd_drop(self, event) -> None:
        data = getattr(event, "data", "") or ""
        # tkinterdnd2 path list uses braced-space-sep format
        try:
            import tkinterdnd2  # type: ignore
            paths = list(tkinterdnd2.tkdnd.splitlist(data))  # type: ignore
        except Exception:  # noqa: BLE001
            # Manual parse
            import re as _re
            tokens = _re.findall(r"\{([^}]*)\}|(\S+)", data)
            paths = [a or b for a, b in tokens]
        if not paths:
            return
        self._handle_paths([Path(p) for p in paths])

    # --------------------------------------------------------------
    def _handle_paths(self, paths: List[Path]) -> None:
        ok: List[Path] = []
        blocked_msgs: List[str] = []
        for p in paths:
            ext = p.suffix.lower()
            if not ext:
                continue
            if ext in self._blocked:
                blocked_msgs.append(f"{p.name} (estensione bloccata: {ext})")
                continue
            if ext not in self._allowed:
                blocked_msgs.append(f"{p.name} (estensione non permessa: {ext})")
                continue
            if not p.is_file():
                continue
            ok.append(p)
        if blocked_msgs:
            try:
                from tkinter import messagebox
                messagebox.showwarning(
                    "Alcuni file sono stati scartati",
                    "I seguenti file non sono stati accettati:\n\n" + "\n".join(blocked_msgs),
                    parent=self.winfo_toplevel(),
                )
            except Exception:  # noqa: BLE001
                pass
        if ok and self._callback:
            try:
                self._callback(ok)
            except Exception as exc:  # noqa: BLE001
                try:
                    from tkinter import messagebox
                    messagebox.showerror("Errore importazione", str(exc),
                                         parent=self.winfo_toplevel())
                except Exception:  # noqa: BLE001
                    pass
        # Feedback label
        if ok:
            names = "  ·  ".join(p.name for p in ok[:8])
            extra = "" if len(ok) <= 8 else f"  + altri {len(ok) - 8}"
            self._recent_lbl.configure(text=f"Importati: {names}{extra}")
