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


# tipi JSON dello schema mostrati con nomi comprensibili
TYPE_LABELS = {"string": "testo", "number": "numero", "integer": "numero intero", "boolean": "sì/no",
               "array": "lista", "object": "gruppo di campi"}


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
            fill="x", pady=(2, 4))
        dt = ctk.CTkFrame(self.page, fg_color="transparent")
        dt.pack(fill="x", pady=(0, 12))
        label(dt, t("Tipo di documento: {t}", t=mod.document_type or t("non indicato")), kind="small",
              muted=True).pack(side="left")
        button(dt, t("Cambia"), self.edit_doc_type, kind="ghost", height=26).pack(side="left", padx=6)

        counts = self.win.db.count_reports_by_module().get(mod.id or -1, {})
        tpl_ok = bool(mod.template_path) and Path(mod.template_path).exists()
        chips = ctk.CTkFrame(self.page, fg_color="transparent")
        chips.pack(fill="x", pady=(0, 14))
        n_draft = counts.get("draft", 0)
        n_done = counts.get("exported", 0) + counts.get("approved", 0)
        Chip(chips, t("{n} bozza", n=1) if n_draft == 1 else t("{n} bozze", n=n_draft), "warning").pack(
            side="left", padx=(0, 6))
        Chip(chips, t("{n} completato", n=1) if n_done == 1 else t("{n} completati", n=n_done),
             "success").pack(side="left", padx=(0, 6))
        Chip(chips, t("Template {ext}", ext=mod.template_type.upper()) if tpl_ok else t("Template mancante"),
             "info" if tpl_ok else "danger").pack(side="left", padx=(0, 6))
        n_fields = len((mod.schema or {}).get("properties", {}))
        Chip(chips, t("{n} campi", n=n_fields), "neutral").pack(side="left")
        if n_fields == 0 and tpl_ok:
            hint = Card(self.page, soft=True)
            hint.pack(fill="x", pady=(0, 14))
            label(hint.body, t("Questo modulo non ha ancora campi da compilare."), kind="body_b").pack(anchor="w")
            label(hint.body, t("Apri l'editor visuale e trascina i campi nei punti del documento che l'AI deve "
                               "compilare."), muted=True).pack(anchor="w", pady=(2, 8))
            button(hint.body, t("Apri l'editor visuale"), self.edit_template, kind="primary",
                   icon_name="mouse-pointer-click").pack(anchor="w")

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
            kind = t("elenco") if (spec or {}).get("enum") else t(TYPE_LABELS.get(str(typ), str(typ)))
            Chip(r, kind + (" · " + t("obbligatorio") if name in req else ""), "neutral").pack(side="right")
            if (spec or {}).get("description"):
                label(fields.body, spec["description"], kind="caption", muted=True, wraplength=520).pack(
                    fill="x", padx=(2, 0))

        tools = Card(grid)
        tools.grid(row=0, column=1, sticky="nsew", padx=(GAP // 2, 0))
        tb = tools.body
        label(tb, t("Strumenti"), kind="h4").pack(anchor="w", pady=(0, 6))
        button(tb, t("Editor visuale: trascina i campi"), self.edit_template, icon_name="mouse-pointer-click",
               kind="primary", anchor="w", height=40).pack(fill="x", pady=(0, 2))
        label(tb, t("Metti i campi da compilare direttamente nel documento, trascinandoli."), kind="caption",
              muted=True, wraplength=300).pack(anchor="w", pady=(0, 8))
        items = [
            ("table", t("Elenco campi (avanzato)"), self.edit_schema),
            ("list", t("Mappatura celle Excel (avanzato)"), self.edit_mapping),
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
                           (t("Storico documenti"), mod.history_folder())):
            button(tb, text, lambda p=path: self._open(p), icon_name="folder-open", kind="ghost",
                   anchor="w").pack(fill="x", pady=1)
        button(tb, t("Archivia modulo"), self.archive, icon_name="archive", kind="ghost",
               text_color=C["danger"], anchor="w").pack(fill="x", pady=(14, 0))

    # ------------------------------------------------------------------
    def _open(self, p: Path) -> None:
        Path(p).mkdir(parents=True, exist_ok=True)
        os.startfile(str(p))  # type: ignore[attr-defined]

    def edit_doc_type(self) -> None:
        mod = self.win.selected
        dlg = ctk.CTkInputDialog(title=t("Tipo di documento"),
                                 text=t("Che documento compila questo modulo? (es. verbale di riunione, "
                                        "richiesta d'acquisto). L'AI lo usa come contesto."))
        value = dlg.get_input()
        if value is not None:
            self.win.mm.set_document_type(mod.slug, value)
            self.win.refresh_modules(quiet=True)

    def edit_template(self) -> None:
        from ..dialogs.template_editor import open_visual_editor
        open_visual_editor(self.win, self.win.selected)

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
            try:
                self.win.mm.export_module_zip(mod.slug, Path(dest))
            except Exception as exc:  # noqa: BLE001
                self.win.toast(t("Esportazione non riuscita: {e}", e=exc), "error")
                return
            self.win.toast(t("Modulo esportato."), "success")

    def duplicate(self) -> None:
        mod = self.win.mm.duplicate_module(self.win.selected.slug)
        self.win.refresh_modules(quiet=True)
        self.win.select_module(mod.slug)
        self.win.toast(t("Creata la copia «{n}».", n=mod.name), "success")

    def archive(self) -> None:
        mod = self.win.selected
        if messagebox.askyesno(t("Archivia modulo"), t("Archiviare «{n}»? Non comparirà più nell'elenco; i documenti "
                                                       "restano nello storico. Puoi ripristinarlo da Impostazioni → "
                                                       "Dati e backup.", n=mod.name), parent=self.win.root):
            self.win.mm.archive_module(mod.slug)
            self.win.selected = None
            self.win.refresh_modules(quiet=True)


__all__ = ["ModulePage", "icon", "font"]
