"""Documenti AI: strumenti di creazione, modifica, audit e compilazione da documenti."""

from __future__ import annotations

import logging
from typing import Any

import customtkinter as ctk

from ..design import C, GAP, font
from ..i18n import t
from ..icons import icon
from ..widgets import Card, button, label, scrollable

LOG = logging.getLogger(__name__)


class DocumentsPage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        page = scrollable(self)
        page.pack(fill="both", expand=True)
        label(page, t("Documenti AI"), kind="h2").pack(anchor="w")
        label(page, t("Strumenti sui documenti con l'AI locale. Gli originali non vengono mai modificati: "
                      "ogni risultato è una nuova versione da confermare."), muted=True, wraplength=900).pack(
            fill="x", pady=(2, 14))
        grid = ctk.CTkFrame(page, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.columnconfigure((0, 1), weight=1, uniform="d")
        tools = [
            ("file-plus", t("Crea documento"), t("Procedure, istruzioni o relazioni a partire dai documenti di riferimento."),
             self.create),
            ("pencil", t("Modifica documento"), t("Carica DOCX, PDF o scansioni e descrivi le modifiche: nasce una nuova versione."),
             self.edit),
            ("file-search", t("Audit documenti"), t("Cerca contraddizioni, date incoerenti, dati mancanti e revisioni non allineate."),
             self.audit),
            ("puzzle", t("Compila da documenti"), t("Compila un modulo leggendo i dati da altri documenti, tabelle e scansioni."),
             self.smart_fill),
            ("scan-text", t("Testo da scansione (OCR)"), t("Estrai il testo da foto o PDF scansionati con l'OCR di Windows."),
             self.ocr),
            ("shield-check", t("Regole AI"), t("Istruzioni permanenti per l'AI, per funzione o per singolo modulo."),
             self.rules),
        ]
        for i, (ic, title, desc, cmd) in enumerate(tools):
            card = Card(grid)
            card.grid(row=i // 2, column=i % 2, sticky="nsew", padx=(0 if i % 2 == 0 else GAP // 2,
                                                                    GAP // 2 if i % 2 == 0 else 0), pady=GAP // 2)
            top = ctk.CTkFrame(card.body, fg_color="transparent")
            top.pack(fill="x")
            ctk.CTkLabel(top, text="", image=icon(ic, 24, "primary"), width=48, height=48, corner_radius=24,
                         fg_color=C["primary_soft"]).pack(side="left")
            box = ctk.CTkFrame(top, fg_color="transparent")
            box.pack(side="left", fill="x", expand=True, padx=12)
            ctk.CTkLabel(box, text=title, font=font("h4"), text_color=C["text"], anchor="w").pack(fill="x")
            ctk.CTkLabel(box, text=desc, font=font("small"), text_color=C["text_muted"], anchor="w",
                         justify="left", wraplength=360).pack(fill="x")
            button(card.body, t("Apri"), cmd, kind="primary", icon_name="arrow-right", height=30).pack(
                anchor="e", pady=(10, 0))

    def _open(self, factory) -> None:
        try:
            factory()
        except Exception as exc:  # noqa: BLE001
            LOG.exception("strumento documenti")
            self.win.toast(t("Errore: {e}", e=exc), "error")

    def create(self) -> None:
        from ..document_dialogs import DocumentCreationDialog
        a = self.win.app
        self._open(lambda: DocumentCreationDialog(self.win.root, a.doc_generator, a.rules_manager,
                                                  a.config.exports_root(), a.module_manager))

    def edit(self) -> None:
        from ..document_dialogs import DocumentModificationDialog
        a = self.win.app
        self._open(lambda: DocumentModificationDialog(self.win.root, a.doc_modifier, a.doc_loader,
                                                      a.config.exports_root()))

    def audit(self) -> None:
        from ..document_dialogs import AuditDialog
        a = self.win.app
        self._open(lambda: AuditDialog(self.win.root, a.audit_engine, a.config.exports_root()))

    def smart_fill(self) -> None:
        from ..document_dialogs import SmartFillDialog
        a = self.win.app

        def _mk():
            dlg = SmartFillDialog(self.win.root, a.smart_fill_engine, a.rules_manager, a.module_manager,
                                  a.config.exports_root())
            if self.win.selected:
                dlg.preload([], self.win.selected.slug)
        self._open(_mk)

    def ocr(self) -> None:
        from ..dialogs.ocr_tool import OcrDialog
        self._open(lambda: OcrDialog(self.win))

    def rules(self) -> None:
        from ..dialogs.rules_picker import RulesPicker
        self._open(lambda: RulesPicker(self.win))
