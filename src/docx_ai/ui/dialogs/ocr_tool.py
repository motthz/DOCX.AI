"""Estrazione testo da foto/PDF scansionati con l'OCR integrato di Windows."""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any

import customtkinter as ctk

from ..design import C, font
from ..i18n import t
from ..widgets import button, label
from .base import Dialog


class OcrDialog(Dialog):
    def __init__(self, win: Any):
        super().__init__(win.root, t("Testo da scansione (OCR)"), width=860, height=660, icon_name="scan-text",
                         subtitle=t("Usa il motore OCR di Windows (nessun download). Le pagine storte vengono raddrizzate."))
        self.win = win
        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x")
        button(top, t("Scegli immagini o PDF…"), self.pick, kind="primary", icon_name="images").pack(side="left")
        self.status = label(top, "", muted=True)
        self.status.pack(side="left", padx=10)
        self.out = ctk.CTkTextbox(self.body, wrap="word", font=font("body"), border_width=1,
                                  border_color=C["border"])
        self.out.pack(fill="both", expand=True, pady=(10, 0))
        button(self.footer, t("Copia testo"), self.copy, icon_name="copy").pack(side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Usa come informazioni del documento"), self.to_report, icon_name="file-text").pack(
            side="right", pady=12)
        button(self.footer, t("Chiudi"), self.close, kind="ghost").pack(side="right", padx=8, pady=12)

    def pick(self) -> None:
        files = filedialog.askopenfilenames(parent=self, filetypes=[(t("Immagini e PDF"), "*.png *.jpg *.jpeg *.pdf")])
        if not files:
            return
        self.status.configure(text=t("Riconoscimento in corso…"))
        threading.Thread(target=self._work, args=([Path(f) for f in files],), daemon=True).start()

    def _work(self, files) -> None:
        loader = self.win.app.doc_loader
        parts = []
        for f in files:
            try:
                doc = loader.load_file(f, run_ocr=True)
                text = getattr(doc, "full_text", "") or getattr(doc, "text", "")
            except Exception as exc:  # noqa: BLE001
                text = t("[errore: {e}]", e=exc)
            parts.append(f"=== {f.name} ===\n{text.strip()}\n")
        self.after(0, lambda: self._done("\n".join(parts)))

    def _done(self, text: str) -> None:
        self.status.configure(text=t("Completato"))
        self.out.delete("1.0", "end")
        self.out.insert("1.0", text)

    def copy(self) -> None:
        self.clipboard_clear()
        self.clipboard_append(self.out.get("1.0", "end"))
        self.win.toast(t("Testo copiato."), "success")

    def to_report(self) -> None:
        page = self.win.page("report")
        page._hide_placeholder()
        page.desc.delete("1.0", "end")
        page.desc.insert("1.0", self.out.get("1.0", "end").strip())
        page._update_quality()
        self.close()
        self.win.show_page("report")
