"""Creazione di un nuovo modulo: da template DOCX/XLSX oppure vuoto."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Any, Optional

import customtkinter as ctk

from ..design import C, font
from ..i18n import t
from ..icons import icon
from ..widgets import button, label
from .base import Dialog


class NewModuleDialog(Dialog):
    def __init__(self, win: Any):
        super().__init__(win.root, t("Nuovo modulo"), width=760, height=600, icon_name="file-plus",
                         subtitle=t("Un modulo è un modello di rapporto: l'AI ne compila i campi "
                                    "{{come_questo}} partendo dalla descrizione dell'intervento."))
        self.win = win
        self.template: Optional[Path] = None
        self.mode = ctk.StringVar(value="template")

        label(self.body, t("Come vuoi crearlo?"), kind="h4").pack(anchor="w")
        modes = ctk.CTkFrame(self.body, fg_color="transparent")
        modes.pack(fill="x", pady=(6, 14))
        modes.columnconfigure((0, 1), weight=1, uniform="m")
        self._cards = {}
        for col, (key, ic, title, desc) in enumerate((
                ("template", "layout-template", t("Da un mio file (DOCX/XLSX)"),
                 t("Usa un rapporto esistente con i campi {{nome_campo}}: schema e mappatura vengono creati da soli.")),
                ("empty", "file-plus", t("Modulo vuoto"),
                 t("Parti da zero con uno schema minimo; potrai aggiungere template e campi dopo.")))):
            card = ctk.CTkFrame(modes, fg_color=C["surface"], border_width=2, border_color=C["border"],
                                corner_radius=12, cursor="hand2")
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0))
            ctk.CTkLabel(card, text="", image=icon(ic, 26, "primary")).pack(anchor="w", padx=14, pady=(14, 4))
            ctk.CTkLabel(card, text=title, font=font("body_b"), text_color=C["text"], anchor="w").pack(
                fill="x", padx=14)
            ctk.CTkLabel(card, text=desc, font=font("small"), text_color=C["text_muted"], anchor="w",
                         justify="left", wraplength=300).pack(fill="x", padx=14, pady=(2, 14))
            for w in [card, *card.winfo_children()]:
                w.bind("<Button-1>", lambda e, k=key: self._choose(k), add="+")
            self._cards[key] = card

        form = ctk.CTkFrame(self.body, fg_color="transparent")
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.file_row = ctk.CTkFrame(form, fg_color="transparent")
        self.file_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        button(self.file_row, t("Scegli file…"), self._pick, icon_name="folder-open").pack(side="left")
        self.file_lbl = label(self.file_row, t("Nessun file selezionato"), muted=True)
        self.file_lbl.pack(side="left", padx=10)

        label(form, t("Nome *"), kind="body_b").grid(row=1, column=0, sticky="w", padx=(0, 12), pady=6)
        self.name = ctk.CTkEntry(form, height=34, placeholder_text=t("es. Rapporto intervento compressori"))
        self.name.grid(row=1, column=1, sticky="ew", pady=6)
        label(form, t("Descrizione"), kind="body_b").grid(row=2, column=0, sticky="nw", padx=(0, 12), pady=6)
        self.desc = ctk.CTkTextbox(form, height=80, border_width=1, border_color=C["border"])
        self.desc.grid(row=2, column=1, sticky="ew", pady=6)
        label(form, t("Codice (opzionale)"), kind="body_b").grid(row=3, column=0, sticky="w", padx=(0, 12), pady=6)
        self.slug = ctk.CTkEntry(form, height=34, placeholder_text=t("generato dal nome se vuoto"))
        self.slug.grid(row=3, column=1, sticky="ew", pady=6)

        self.create_btn = button(self.footer, t("Crea modulo"), self._create, kind="primary", icon_name="check")
        self.create_btn.pack(side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Annulla"), self.cancel).pack(side="right", pady=12)
        self.bind("<Return>", lambda e: self._create())
        self._choose("template")
        self.after(200, self.name.focus_set)

    def _choose(self, key: str) -> None:
        self.mode.set(key)
        for k, card in self._cards.items():
            card.configure(border_color=C["primary"] if k == key else C["border"],
                           fg_color=C["primary_soft"] if k == key else C["surface"])
        if key == "template":
            self.file_row.grid()
        else:
            self.file_row.grid_remove()

    def _pick(self) -> None:
        f = filedialog.askopenfilename(parent=self, title=t("Scegli il template"),
                                       filetypes=[(t("Template DOCX/XLSX"), "*.docx *.xlsx")])
        if not f:
            return
        self.template = Path(f)
        self.file_lbl.configure(text=self.template.name)
        if not self.name.get().strip():
            self.name.insert(0, self.template.stem.replace("_", " ").strip().capitalize())

    def _create(self) -> None:
        name = self.name.get().strip()
        if not name:
            self.win.toast(t("Inserisci un nome per il modulo."), "warning")
            self.name.focus_set()
            return
        if self.mode.get() == "template" and self.template is None:
            self.win.toast(t("Scegli un file DOCX o XLSX come template."), "warning")
            return
        slug = self.slug.get().strip() or None
        desc = self.desc.get("1.0", "end").strip() or None
        self.create_btn.configure(state="disabled")
        try:
            if self.mode.get() == "template":
                mod = self.win.mm.create_module_from_template(
                    name=name, template_file=self.template, slug=slug, description=desc)
            else:
                mod = self.win.mm.create_module(name=name, template_type="docx", slug=slug, description=desc)
        except Exception as exc:  # noqa: BLE001
            self.create_btn.configure(state="normal")
            self.win.toast(t("Creazione non riuscita: {e}", e=exc), "error")
            return
        try:
            self.win.app.rules_manager.ensure_module_rules_exist(mod.folder_path)
        except Exception:  # noqa: BLE001
            pass
        self.close()
        self.win.refresh_modules(quiet=True)
        self.win.select_module(mod.slug)
        self.win.show_page("module")
        self.win.toast(t("Modulo creato: {name}", name=mod.name), "success",
                       action=(t("Nuovo rapporto"), lambda: self.win.show_page("report")))
