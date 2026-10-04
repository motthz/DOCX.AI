"""Esito dell'esportazione: file prodotti e azioni rapide."""

from __future__ import annotations

import os
import urllib.parse
import webbrowser
from pathlib import Path
from typing import Any, Callable, Optional

import customtkinter as ctk

from ..design import C, font
from ..i18n import t
from ..icons import icon
from ..widgets import button, label
from .base import Dialog


class ExportDoneDialog(Dialog):
    def __init__(self, win: Any, mod, json_p: Path, doc_p: Optional[Path], pdf_p: Path,
                 on_new: Optional[Callable] = None):
        super().__init__(win.root, t("Documento esportato"), width=680, height=500, icon_name="circle-check",
                         subtitle=f"{mod.name} · {Path(json_p).parent.name}")
        self.win = win
        self.folder = Path(json_p).parent
        rows = [(t("PDF del documento"), pdf_p, "file-down"),
                (t("Documento da template"), doc_p, "file-spreadsheet" if doc_p and doc_p.suffix == ".xlsx"
                 else "file-text"),
                (t("Dati approvati (JSON)"), json_p, "file-json")]
        for title, path, ic in rows:
            if not path:
                continue
            r = ctk.CTkFrame(self.body, fg_color=C["surface"], corner_radius=10, border_width=1,
                             border_color=C["border"])
            r.pack(fill="x", pady=4)
            ctk.CTkLabel(r, text="", image=icon(ic, 22, "primary")).pack(side="left", padx=12, pady=10)
            box = ctk.CTkFrame(r, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True)
            label(box, title, kind="body_b").pack(fill="x")
            label(box, Path(path).name, kind="caption", muted=True).pack(fill="x")
            button(r, t("Apri"), lambda p=path: os.startfile(str(p)), height=30).pack(side="right", padx=10)
        acts = ctk.CTkFrame(self.body, fg_color="transparent")
        acts.pack(fill="x", pady=(12, 0))
        button(acts, t("Anteprima PDF"), lambda: self._preview(pdf_p), icon_name="eye").pack(side="left")
        button(acts, t("Invia per email"), lambda: self._mail(mod, pdf_p), icon_name="mail").pack(
            side="left", padx=8)
        button(acts, t("Apri cartella"), lambda: os.startfile(str(self.folder)), icon_name="folder-open").pack(
            side="left")
        label(self.body, t("Il PDF include le eventuali foto allegate; il JSON è la fonte ufficiale dei dati."),
              kind="caption", muted=True).pack(anchor="w", pady=(14, 0))

        button(self.footer, t("Nuovo documento"), lambda: (self.close(), on_new and on_new()),
               kind="primary", icon_name="plus").pack(side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Chiudi"), self.close).pack(side="right", pady=12)
        win.toast(t("Documento esportato."), "success", action=(t("Apri PDF"), lambda: os.startfile(str(pdf_p))))

    def _preview(self, pdf_p: Path) -> None:
        from .pdf_preview import PdfPreview
        self.close()
        PdfPreview(self.win.root, pdf_p, win=self.win)

    def _mail(self, mod, pdf_p: Path) -> None:
        """Apre il client di posta con oggetto e testo; il PDF va allegato dalla cartella aperta."""
        subject = urllib.parse.quote(mod.name)
        body = urllib.parse.quote(t("In allegato il documento.\nFile: {f}", f=Path(pdf_p).name))
        webbrowser.open(f"mailto:?subject={subject}&body={body}")
        os.startfile(str(self.folder))
        self.win.toast(t("Trascina il PDF dalla cartella nella nuova email."), "info")


__all__ = ["ExportDoneDialog", "font"]
