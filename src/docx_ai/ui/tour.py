"""Tour guidato al primo utilizzo: oscura la finestra ed evidenzia un controllo alla volta."""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, List, Optional, Tuple

import customtkinter as ctk

from .design import C, font
from .i18n import t
from .widgets import button

HOLE = "#ff00fe"  # colore reso trasparente nell'overlay


class Tour:
    def __init__(self, win: Any):
        self.win = win
        self.i = 0
        self.overlay: Optional[tk.Toplevel] = None
        self.box: Optional[ctk.CTkToplevel] = None
        tb = win.tabbar._buttons
        self.steps: List[Tuple[Callable[[], tk.Misc], str, str]] = [
            (lambda: win.sidebar, t("I tuoi moduli"),
             t("Qui trovi i modelli dei tuoi documenti. Un modulo nasce da un tuo DOCX/XLSX con i campi {{nome_campo}}.")),
            (lambda: tb["report"], t("Nuovo documento"),
             t("Scrivi le informazioni a parole tue (anche con foto o documenti): l'AI compila i campi del modulo.")),
            (lambda: win._ai_btn, t("Motore AI locale"),
             t("Lo stato dell'AI. Al primo uso clicca qui per scaricare il modello: poi funziona offline.")),
            (lambda: tb["history"], t("Storico"),
             t("Cerca, filtra, duplica, confronta versioni ed esporta in Excel tutti i documenti.")),
            (lambda: tb["settings"], t("Impostazioni"),
             t("Tema, lingua, dimensione del testo, backup, cartella dati condivisa e opzioni AI.")),
            (lambda: win._theme_btn, t("Tutto pronto!"),
             t("Puoi rivedere questo tour da Impostazioni → Aiuto. Premi F1 per la guida completa.")),
        ]

    def start(self) -> None:
        root = self.win.root
        root.update_idletasks()
        self.overlay = tk.Toplevel(root)
        self.overlay.overrideredirect(True)
        try:
            self.overlay.attributes("-alpha", 0.55)
            self.overlay.attributes("-transparentcolor", HOLE)
        except tk.TclError:
            pass
        self.canvas = tk.Canvas(self.overlay, highlightthickness=0, bd=0, bg="#020617")
        self.canvas.pack(fill="both", expand=True)
        self.overlay.bind("<Escape>", lambda e: self.end())
        self._bind_id = root.bind("<Configure>", self._follow, add="+")
        self.show()

    def _follow(self, _e=None) -> None:
        try:
            alive = self.overlay is not None and bool(self.overlay.winfo_exists())
        except tk.TclError:
            alive = False
        if alive:
            self.show(reposition_only=True)
        elif self.overlay is not None:
            self.end()

    def show(self, reposition_only: bool = False) -> None:
        root = self.win.root
        x, y, w, h = root.winfo_rootx(), root.winfo_rooty(), root.winfo_width(), root.winfo_height()
        assert self.overlay is not None
        self.overlay.geometry(f"{w}x{h}+{x}+{y}")
        get, title, text = self.steps[self.i]
        target = get()
        tx, ty = target.winfo_rootx() - x, target.winfo_rooty() - y
        tw, th = target.winfo_width(), target.winfo_height()
        pad = 6
        self.canvas.delete("all")
        self.canvas.create_rectangle(0, 0, w, h, fill="#020617", width=0)
        self.canvas.create_rectangle(tx - pad, ty - pad, tx + tw + pad, ty + th + pad, fill=HOLE, width=0)
        self.overlay.lift()
        if reposition_only:
            # <Configure> arriva anche mentre il riquadro viene creato (CTkToplevel aggiorna la
            # finestra): crearne un altro qui lasciava riquadri "1/6" orfani sempre in primo piano
            if self.box is not None:
                self._place_box(tx + x, ty + y, tw, th)
            return
        if self.box is not None:
            self.box.destroy()
        self.box = ctk.CTkToplevel(root)
        self.box.overrideredirect(True)
        self.box.attributes("-topmost", True)
        frame = ctk.CTkFrame(self.box, fg_color=C["surface"], border_color=C["primary"], border_width=2,
                             corner_radius=12)
        frame.pack(fill="both", expand=True)
        ctk.CTkLabel(frame, text=f"{self.i + 1}/{len(self.steps)}  ·  {title}", font=font("h4"),
                     text_color=C["text"]).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(frame, text=text, font=font("body"), text_color=C["text_muted"], wraplength=340,
                     justify="left").pack(anchor="w", padx=16)
        row = ctk.CTkFrame(frame, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=14)
        last = self.i == len(self.steps) - 1
        button(row, t("Fine") if last else t("Avanti"), self.next, kind="primary", height=30).pack(side="right")
        if not last:
            button(row, t("Salta il tour"), self.end, kind="ghost", height=30).pack(side="right", padx=6)
        self.box.bind("<Return>", lambda e: self.next())
        self.box.bind("<Escape>", lambda e: self.end())
        self._place_box(tx + x, ty + y, tw, th)
        self.box.focus_force()

    def _place_box(self, ax: int, ay: int, aw: int, ah: int) -> None:
        assert self.box is not None
        self.box.update_idletasks()
        bw, bh = self.box.winfo_reqwidth(), self.box.winfo_reqheight()
        sw, sh = self.box.winfo_screenwidth(), self.box.winfo_screenheight()
        x = ax + aw + 16 if ax + aw + 16 + bw < sw else max(8, ax - bw - 16)
        y = min(max(8, ay), sh - bh - 40)
        if aw > sw * 0.5:  # bersaglio molto largo: sotto
            x, y = ax + 20, ay + ah + 12
        self.box.geometry(f"+{int(x)}+{int(y)}")
        self.box.lift()

    def next(self) -> None:
        if self.overlay is None:  # tour gia' chiuso
            return
        self.i += 1
        if self.i >= len(self.steps):
            self.end()
        else:
            self.show()

    def end(self) -> None:
        self.win.settings.set("ui.tour_done", True)
        try:
            self.win.root.unbind("<Configure>", self._bind_id)
        except (tk.TclError, AttributeError):
            pass
        for w in (self.box, self.overlay):
            try:
                if w is not None:
                    w.destroy()
            except tk.TclError:
                pass
        self.box = self.overlay = None
