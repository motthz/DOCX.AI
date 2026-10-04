"""Anteprima PDF dentro l'app (pypdfium2): pagine, zoom, stampa, apertura esterna."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, List

import customtkinter as ctk

from ..design import C
from ..i18n import t
from ..widgets import button, label
from .base import Dialog


class PdfPreview(Dialog):
    def __init__(self, master, pdf_path: Path, *, win: Any = None):
        super().__init__(master, t("Anteprima · {name}", name=Path(pdf_path).name), width=900, height=920,
                         icon_name="eye", modal=False)
        self.path = Path(pdf_path)
        self.win = win
        self.zoom = 1.0
        self._images: List[ctk.CTkImage] = []
        try:
            import pypdfium2 as pdfium
            self.doc = pdfium.PdfDocument(str(self.path))
        except Exception as exc:  # noqa: BLE001
            self.doc = None
            label(self.body, t("Impossibile aprire il PDF: {e}", e=exc), text_color=C["danger"]).pack()
        self.page_idx = 0
        bar = ctk.CTkFrame(self.body, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        button(bar, "", self.prev, icon_name="chevron-left", width=36).pack(side="left")
        self.pg_lbl = label(bar, "", kind="small_b")
        self.pg_lbl.pack(side="left", padx=10)
        button(bar, "", self.next, icon_name="chevron-right", width=36).pack(side="left")
        button(bar, "−", lambda: self.set_zoom(self.zoom / 1.2), width=36).pack(side="left", padx=(16, 4))
        button(bar, "+", lambda: self.set_zoom(self.zoom * 1.2), width=36).pack(side="left")
        button(bar, t("Apri con il lettore PDF"), self.open_external, icon_name="external-link").pack(side="right")
        button(bar, t("Stampa"), self.print_pdf, icon_name="printer").pack(side="right", padx=6)
        self.canvas = ctk.CTkScrollableFrame(self.body, fg_color=C["surface_alt"])
        self.canvas.pack(fill="both", expand=True)
        self.img_lbl = ctk.CTkLabel(self.canvas, text="")
        self.img_lbl.pack(pady=10)
        button(self.footer, t("Chiudi"), self.close).pack(side="right", padx=20, pady=12)
        self.bind("<Left>", lambda e: self.prev())
        self.bind("<Right>", lambda e: self.next())
        self.bind("<Prior>", lambda e: self.prev())
        self.bind("<Next>", lambda e: self.next())
        self.after(50, self.render)

    def render(self) -> None:
        if self.doc is None:
            return
        page = self.doc[self.page_idx]
        w, h = page.get_size()
        target_w = 760 * self.zoom
        scale = target_w / w
        pil = page.render(scale=scale * 1.5).to_pil()  # supercampionato: testo nitido
        img = ctk.CTkImage(pil, size=(int(w * scale), int(h * scale)))
        self._images = [img]
        self.img_lbl.configure(image=img)
        self.pg_lbl.configure(text=t("Pagina {i} di {n}", i=self.page_idx + 1, n=len(self.doc)))

    def prev(self) -> None:
        if self.doc is not None and self.page_idx > 0:
            self.page_idx -= 1
            self.render()

    def next(self) -> None:
        if self.doc is not None and self.page_idx < len(self.doc) - 1:
            self.page_idx += 1
            self.render()

    def set_zoom(self, z: float) -> None:
        self.zoom = max(0.5, min(2.5, z))
        self.render()

    def open_external(self) -> None:
        if sys.platform == "win32":
            os.startfile(str(self.path))  # type: ignore[attr-defined]

    def print_pdf(self) -> None:
        try:
            if sys.platform == "win32":
                os.startfile(str(self.path), "print")  # type: ignore[attr-defined]
        except OSError:
            self.open_external()

    def close(self) -> None:
        try:
            if self.doc is not None:
                self.doc.close()
        except Exception:  # noqa: BLE001
            pass
        super().close()
