"""Import di interventi da CSV/Excel: scelta file, associazione colonne -> campi, conferma."""

from __future__ import annotations

from pathlib import Path
from tkinter import filedialog
from typing import Any, Dict, Optional

import customtkinter as ctk

from ...services import import_service
from ..design import C
from ..i18n import t
from ..widgets import button, label
from .base import Dialog

NONE = "—"


class TableImportDialog(Dialog):
    def __init__(self, win: Any, mod):
        super().__init__(win.root, t("Importa da tabella · {name}", name=mod.name), width=820, height=700,
                         icon_name="file-input",
                         subtitle=t("Ogni riga del file diventa un documento. Associa le colonne ai campi del modulo."))
        self.win = win
        self.mod = mod
        self.table: Optional[import_service.Table] = None
        self.menus: Dict[str, ctk.CTkOptionMenu] = {}

        top = ctk.CTkFrame(self.body, fg_color="transparent")
        top.pack(fill="x")
        button(top, t("Scegli file CSV o Excel…"), self.pick, kind="primary", icon_name="folder-open").pack(side="left")
        self.file_lbl = label(top, t("Nessun file"), muted=True)
        self.file_lbl.pack(side="left", padx=10)
        opts = ctk.CTkFrame(self.body, fg_color="transparent")
        opts.pack(fill="x", pady=(10, 6))
        label(opts, t("Importa come"), kind="small_b").pack(side="left")
        self.status = ctk.CTkSegmentedButton(opts, values=[t("Bozze da revisionare"), t("Documenti approvati")])
        self.status.set(t("Bozze da revisionare"))
        self.status.pack(side="left", padx=10)
        label(opts, t("Colonna descrizione"), kind="small_b").pack(side="left", padx=(16, 6))
        self.desc_col = ctk.CTkOptionMenu(opts, values=[NONE], width=180)
        self.desc_col.pack(side="left")
        self.grid_box = ctk.CTkScrollableFrame(self.body, fg_color=C["surface"])
        self.grid_box.pack(fill="both", expand=True, pady=(6, 0))
        label(self.grid_box, t("Scegli un file per vedere le colonne."), muted=True).pack(pady=20)
        self.go = button(self.footer, t("Importa"), self.run, kind="primary", icon_name="check")
        self.go.pack(side="right", padx=(8, 20), pady=12)
        self.go.configure(state="disabled")
        button(self.footer, t("Annulla"), self.cancel).pack(side="right", pady=12)
        self.info = label(self.footer, "", kind="small", muted=True)
        self.info.pack(side="left", padx=20)

    def pick(self) -> None:
        f = filedialog.askopenfilename(parent=self, filetypes=[(t("Tabelle"), "*.csv *.xlsx *.txt")])
        if not f:
            return
        try:
            self.table = import_service.read_table(Path(f))
        except Exception as exc:  # noqa: BLE001
            self.win.toast(t("File non leggibile: {e}", e=exc), "error")
            return
        self.file_lbl.configure(text=t("{name} · {n} righe", name=Path(f).name, n=len(self.table.rows)))
        self._render()

    def _render(self) -> None:
        for w in self.grid_box.winfo_children():
            w.destroy()
        assert self.table is not None
        mapping = import_service.suggest_mapping(self.table.headers, self.mod.schema or {})
        choices = [NONE] + self.table.headers
        self.desc_col.configure(values=choices)
        guess = next((h for h in self.table.headers if any(k in h.lower() for k in ("descr", "attivit", "lavor"))),
                     NONE)
        self.desc_col.set(guess)
        self.grid_box.columnconfigure(1, weight=1)
        label(self.grid_box, t("Campo del modulo"), kind="small_b").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        label(self.grid_box, t("Colonna del file"), kind="small_b").grid(row=0, column=1, sticky="w", padx=8)
        for i, (field, col_name) in enumerate(mapping.items(), 1):
            label(self.grid_box, field.replace("_", " ").capitalize()).grid(row=i, column=0, sticky="w", padx=8, pady=3)
            m = ctk.CTkOptionMenu(self.grid_box, values=choices, height=28)
            m.set(col_name or NONE)
            m.grid(row=i, column=1, sticky="ew", padx=8, pady=3)
            self.menus[field] = m
        n_map = sum(1 for v in mapping.values() if v)
        self.info.configure(text=t("{n} campi associati automaticamente su {tot}", n=n_map, tot=len(mapping)))
        self.go.configure(state="normal")

    def run(self) -> None:
        if self.table is None:
            return
        mapping = {f: (m.get() if m.get() != NONE else None) for f, m in self.menus.items()}
        status = "approved" if self.status.get() == t("Documenti approvati") else "draft"
        desc = self.desc_col.get()
        ids = import_service.import_rows(self.win.db, self.mod, self.table, mapping, status=status,
                                         description_column=None if desc == NONE else desc)
        self.win.emit("reports")
        self.win.toast(t("Importati {n} documenti.", n=len(ids)), "success")
        self.close()
