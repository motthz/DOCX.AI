"""Dettagli del modulo: riepilogo, campi, cartelle, strumenti di modifica."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

import customtkinter as ctk

from ..design import C, GAP, font
from ..i18n import t
from ..icons import icon
from ..widgets import Card, Chip, EmptyState, button, label, scrollable


class ModulePage(ctk.CTkFrame):
    def __init__(self, parent, win: Any):
        super().__init__(parent, fg_color="transparent")
        self.win = win
        self.page = scrollable(self)
        self.page.pack(fill="both", expand=True)
        win.on("module_selected", lambda m: self.render())
        win.on("modules", self.render)
        self.render()

    def on_show(self) -> None:
        self.render()

    def render(self) -> None:
        for w in self.page.winfo_children():
            w.destroy()
        mod = self.win.selected
        if mod is None:
            EmptyState(self.page, "package", t("Nessun modulo selezionato"),
                       t("Seleziona un modulo nella barra laterale oppure creane uno nuovo."),
                       action=(t("Nuovo modulo"), self.win.sidebar.new_module)).pack(fill="x", pady=40)
            return
        head = ctk.CTkFrame(self.page, fg_color="transparent")
        head.pack(fill="x")
        label(head, mod.name, kind="h1").pack(side="left")
        Chip(head, f"v{mod.version}", "info").pack(side="left", padx=10, pady=(6, 0))
        label(self.page, mod.description or t("Nessuna descrizione."), muted=True, wraplength=900).pack(
            fill="x", pady=(2, 12))

        counts = self.win.db.count_reports_by_module().get(mod.id or -1, {})
        tpl_ok = bool(mod.template_path) and Path(mod.template_path).exists()
        chips = ctk.CTkFrame(self.page, fg_color="transparent")
        chips.pack(fill="x", pady=(0, 14))
        Chip(chips, t("{n} bozze", n=counts.get("draft", 0)), "warning").pack(side="left", padx=(0, 6))
        Chip(chips, t("{n} completati", n=counts.get("exported", 0) + counts.get("approved", 0)),
             "success").pack(side="left", padx=(0, 6))
        Chip(chips, t("Template {ext}", ext=mod.template_type.upper()) if tpl_ok else t("Template mancante"),
             "info" if tpl_ok else "danger").pack(side="left", padx=(0, 6))
        n_fields = len((mod.schema or {}).get("properties", {}))
        Chip(chips, t("{n} campi", n=n_fields), "neutral").pack(side="left")

        grid = ctk.CTkFrame(self.page, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.columnconfigure(0, weight=3, uniform="g")
        grid.columnconfigure(1, weight=2, uniform="g")

        fields = Card(grid)
        fields.grid(row=0, column=0, sticky="nsew", padx=(0, GAP // 2))
        label(fields.body, t("Campi compilati dall'AI"), kind="h4").pack(anchor="w")
        req = set((mod.schema or {}).get("required", []))
        for name, spec in (mod.schema or {}).get("properties", {}).items():
            r = ctk.CTkFrame(fields.body, fg_color="transparent")
            r.pack(fill="x", pady=2)
            label(r, (spec or {}).get("title") or name.replace("_", " ").capitalize(), kind="body_b").pack(
                side="left")
            typ = (spec or {}).get("type", "string")
            Chip(r, ("elenco" if (spec or {}).get("enum") else str(typ)) + (" · " + t("obbligatorio") if name in req else ""),
                 "neutral").pack(side="right")
            if (spec or {}).get("description"):
                label(fields.body, spec["description"], kind="caption", muted=True, wraplength=520).pack(
                    fill="x", padx=(2, 0))

        tools = Card(grid)
        tools.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        tb = tools.body
        label(tb, t("Strumenti"), kind="h4").pack(anchor="w", pady=(0, 6))
        items = [
            ("layout-template", t("Editor template"), self.edit_template),
            ("table", t("Campi (schema)"), self.edit_schema),
            ("list", t("Mappatura celle Excel"), self.edit_mapping),
            ("shield-check", t("Regole AI del modulo"), self.edit_rules),
            ("upload", t("Esporta modulo (ZIP)"), self.export_zip),
            ("copy", t("Duplica modulo"), self.duplicate),
        ]
        for ic, text, cmd in items:
            if ic == "list" and mod.template_type != "xlsx":
                continue
            button(tb, text, cmd, icon_name=ic, kind="secondary", anchor="w").pack(fill="x", pady=3)
        label(tb, t("Cartelle"), kind="h4").pack(anchor="w", pady=(14, 6))
        for text, path in ((t("Cartella del modulo"), mod.folder_path),
                           (t("Documenti di riferimento"), mod.reference_folder()),
                           (t("Storico rapporti"), mod.history_folder())):
            button(tb, text, lambda p=path: self._open(p), icon_name="folder-open", kind="ghost",
                   anchor="w").pack(fill="x", pady=1)
        button(tb, t("Archivia modulo"), self.archive, icon_name="archive", kind="ghost",
               text_color=C["danger"], anchor="w").pack(fill="x", pady=(14, 0))

    # ------------------------------------------------------------------
    def _open(self, p: Path) -> None:
        Path(p).mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))  # type: ignore[attr-defined]

    def edit_template(self) -> None:
        mod = self.win.selected
        if mod.template_type != "docx" or not Path(mod.template_path).exists():
            self.win.toast(t("L'editor visuale è disponibile per i template DOCX. Per Excel usa la mappatura celle."),
                           "info")
            return
        from ..dialogs.template_editor import TemplateEditor
        TemplateEditor(self.win, mod)

    def edit_schema(self) -> None:
        mod = self.win.selected
        from ..schema_editor_dialog import SchemaEditorDialog
        ok, new_schema = SchemaEditorDialog(self.win.root, mod.schema or {},
                                            title=t("Campi del modulo · {n}", n=mod.name)).run()
        if ok:
            v = self.win.mm.bump_version(mod.slug, new_schema=new_schema)
            self.win.refresh_modules(quiet=True)
            self.win.toast(t("Schema aggiornato (versione {v}).", v=v), "success")

    def edit_mapping(self) -> None:
        mod = self.win.selected
        from ..mapping_editor_dialog import MappingEditorDialog
        ok, new_map = MappingEditorDialog(self.win.root, mod.template_path, mod.mapping or {}, mod.schema).run()
        if ok:
            v = self.win.mm.bump_version(mod.slug, new_mapping=new_map)
            self.win.refresh_modules(quiet=True)
            self.win.toast(t("Mappatura aggiornata (versione {v}).", v=v), "success")

    def edit_rules(self) -> None:
        mod = self.win.selected
        from ..rules_dialog import RulesEditorDialog
        RulesEditorDialog(self.win.root, self.win.app.rules_manager, module_name=mod.name,
                          module_folder=mod.folder_path)

    def export_zip(self) -> None:
        mod = self.win.selected
        dest = filedialog.asksaveasfilename(parent=self.win.root, defaultextension=".zip",
                                            initialfile=f"{mod.slug}.zip", filetypes=[("ZIP", "*.zip")])
        if dest:
            self.win.mm.export_module_zip(mod.slug, Path(dest))
            self.win.toast(t("Modulo esportato."), "success")

    def duplicate(self) -> None:
        mod = self.win.mm.duplicate_module(self.win.selected.slug)
        self.win.refresh_modules(quiet=True)
        self.win.select_module(mod.slug)
        self.win.toast(t("Creata la copia «{n}».", n=mod.name), "success")

    def archive(self) -> None:
        mod = self.win.selected
        if messagebox.askyesno(t("Archivia modulo"), t("Archiviare «{n}»? Non comparirà più nell'elenco; i rapporti "
                                                       "restano nello storico.", n=mod.name), parent=self.win.root):
            self.win.mm.archive_module(mod.slug)
            self.win.selected = None
            self.win.refresh_modules(quiet=True)


__all__ = ["ModulePage", "icon", "font"]
