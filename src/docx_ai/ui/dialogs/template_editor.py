"""Editor visuale del template DOCX.

- Anteprima del documento (paragrafi e tabelle) con i campi {{...}} evidenziati.
- Seleziona del testo nell'anteprima e trasformalo in un campo (nuovo o esistente).
- Aggiungi campi allo schema (nome, tipo, descrizione) senza toccare il JSON.
- "Anteprima con dati": compila il template con i dati dell'ultimo rapporto.
- Il salvataggio conserva una copia del template precedente in _versions.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
import tkinter as tk
from pathlib import Path
from typing import Any, Dict, List, Tuple

import customtkinter as ctk

from ...parsers.docx_parser import _PLACEHOLDER_RE, _iter_all_paragraphs, _iter_block_items
from ..design import C, col
from ..i18n import t
from ..widgets import Chip, button, label
from .base import Dialog

TYPES = {"testo": "string", "numero": "number", "sì/no": "boolean", "data": "date", "elenco righe": "array"}


def replace_span(paragraph, start: int, end: int, text: str) -> None:
    """Sostituisce i caratteri [start, end) del paragrafo mantenendo lo stile del primo run."""
    spans: List[Tuple[Any, int, int]] = []
    cur = 0
    for run in paragraph.runs:
        spans.append((run, cur, cur + len(run.text)))
        cur += len(run.text)
    touched = [i for i, (_r, rs, re_) in enumerate(spans) if not (re_ <= start or rs >= end)]
    if not touched:
        return
    first, last = touched[0], touched[-1]
    fr, frs, _ = spans[first]
    lr, lrs, _ = spans[last]
    pre = fr.text[: max(0, start - frs)]
    post = lr.text[max(0, end - lrs):]
    fr.text = pre + text + post
    for i in range(first + 1, last + 1):
        spans[i][0].text = ""


class TemplateEditor(Dialog):
    def __init__(self, win: Any, mod):
        super().__init__(win.root, t("Editor template · {name}", name=mod.name), width=1180, height=820,
                         icon_name="layout-template",
                         subtitle=t("Seleziona del testo nell'anteprima e trasformalo in un campo che l'AI compilerà."))
        import docx
        self.win = win
        self.mod = mod
        self.path = Path(mod.template_path)
        self.doc = docx.Document(str(self.path))
        self.schema: Dict[str, Any] = dict(mod.schema or {"type": "object", "properties": {}})
        self.schema.setdefault("properties", {})
        self.dirty = False
        self.para_index: List[Tuple[str, Any]] = []  # (indice riga Text "start", paragraph)

        self.body.columnconfigure(0, weight=3)
        self.body.columnconfigure(1, weight=2)
        self.body.rowconfigure(1, weight=1)
        self.view_mode = ctk.CTkSegmentedButton(self.body, values=[t("Modello"), t("Anteprima con dati")],
                                                command=lambda v: self.render())
        self.view_mode.set(t("Modello"))
        self.view_mode.grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.text = tk.Text(self.body, wrap="word", relief="flat", bd=0, padx=24, pady=20,
                            font=("Calibri", 11), bg=col("surface"), fg=col("text"), highlightthickness=1,
                            highlightbackground=col("border"), insertbackground=col("text"))
        self.text.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self.text.tag_configure("ph", background=col("primary_soft"), foreground=col("primary"),
                                font=("Calibri", 11, "bold"))
        self.text.tag_configure("cell", foreground=col("text_muted"))
        self.text.bind("<Key>", lambda e: "break" if e.keysym not in ("Left", "Right", "Up", "Down", "c") else None)

        side = ctk.CTkScrollableFrame(self.body, fg_color=C["surface"], corner_radius=10, border_width=1,
                                      border_color=C["border"])
        side.grid(row=1, column=1, sticky="nsew")
        add = ctk.CTkFrame(side, fg_color="transparent")
        add.pack(fill="x", padx=12, pady=(12, 8))
        label(add, t("Selezione → campo"), kind="small_b").pack(anchor="w")
        self.field_name = ctk.CTkComboBox(add, values=self._field_names(), height=30)
        self.field_name.set("")
        self.field_name.pack(fill="x", pady=(4, 4))
        row = ctk.CTkFrame(add, fg_color="transparent")
        row.pack(fill="x")
        self.field_type = ctk.CTkOptionMenu(row, values=list(TYPES), width=130, height=30)
        self.field_type.pack(side="left")
        self.field_req = ctk.CTkCheckBox(row, text=t("obbligatorio"))
        self.field_req.pack(side="left", padx=8)
        self.field_desc = ctk.CTkEntry(add, height=30, placeholder_text=t("Descrizione per l'AI (cosa inserire)"))
        self.field_desc.pack(fill="x", pady=4)
        button(add, t("Trasforma la selezione in campo"), self.make_field, kind="primary",
               icon_name="wand-sparkles").pack(fill="x", pady=(4, 0))
        button(add, t("Aggiungi solo allo schema"), lambda: self.make_field(schema_only=True)).pack(
            fill="x", pady=(6, 0))
        self.info = label(add, "", kind="caption", muted=True, wraplength=320)
        self.info.pack(fill="x", pady=(6, 0))
        self.sync_btn = button(add, t("Aggiungi allo schema i campi mancanti"), self.add_missing,
                               icon_name="plus")
        label(side, t("Campi del modulo"), kind="h4").pack(anchor="w", padx=12, pady=(8, 4))
        self.fields_box = ctk.CTkFrame(side, fg_color="transparent")
        self.fields_box.pack(fill="both", expand=True, padx=6)

        button(self.footer, t("Salva template"), self.save, kind="primary", icon_name="save").pack(
            side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Anteprima in Word"), self.open_word, icon_name="external-link").pack(side="right", pady=12)
        button(self.footer, t("Chiudi"), self.cancel, kind="ghost").pack(side="right", padx=8, pady=12)
        self.render()
        self._render_fields()

    # ------------------------------------------------------------------
    def _field_names(self) -> List[str]:
        return list(self.schema.get("properties", {}))

    def _used(self) -> set:
        """Campi presenti nel template, anche in intestazioni, pie' di pagina e caselle di testo."""
        used = set()
        for p in _iter_all_paragraphs(self.doc):
            used.update(m.group(1) for m in _PLACEHOLDER_RE.finditer(p.text))
        return used

    def add_missing(self) -> None:
        """Campi {{...}} scritti nel template (es. modificandolo in Word) ma assenti dallo schema:
        senza questo passaggio resterebbero come testo nel documento esportato."""
        props = self.schema.setdefault("properties", {})
        missing = [n for n in sorted(self._used()) if n not in props]
        for name in missing:
            props[name] = {"type": "string"}
            self.schema.setdefault("required", []).append(name)
        if missing:
            self.dirty = True
            self._render_fields()
            self.win.toast(t("Aggiunti {n} campi allo schema.", n=len(missing)), "success")

    @staticmethod
    def _all_paragraphs(doc):
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        for block in _iter_block_items(doc):
            if isinstance(block, Paragraph):
                yield "p", block
            elif isinstance(block, Table):
                for r in block.rows:
                    seen = set()
                    for cell in r.cells:
                        if id(cell._tc) in seen:
                            continue
                        seen.add(id(cell._tc))
                        for p in cell.paragraphs:
                            yield "c", p

    def _render_fields(self) -> None:
        for w in self.fields_box.winfo_children():
            w.destroy()
        used = self._used()
        required = set(self.schema.get("required", []))
        for name, spec in self.schema.get("properties", {}).items():
            r = ctk.CTkFrame(self.fields_box, fg_color="transparent")
            r.pack(fill="x", pady=1)
            label(r, name + (" *" if name in required else "")).pack(side="left")
            Chip(r, t("nel template") if name in used else t("non usato"),
                 "success" if name in used else "warning").pack(side="right")
            r.bind("<Button-1>", lambda e, n=name: self.field_name.set(n), add="+")
        self.field_name.configure(values=self._field_names())
        missing = used - set(self.schema.get("properties", {}))
        self.info.configure(text=t("Campi nel template ma non nello schema: {f}", f=", ".join(sorted(missing)))
                            if missing else "")
        if missing:
            self.sync_btn.pack(fill="x", pady=(6, 0))
        else:
            self.sync_btn.pack_forget()

    def _sample_values(self) -> Dict[str, Any]:
        rows, _n = self.win.db.search_reports(module_id=self.mod.id, limit=1)
        if rows:
            import json
            try:
                return json.loads(rows[0].get("final_json") or rows[0].get("draft_json") or "{}")
            except ValueError:
                pass
        return {k: f"«{k}»" for k in self.schema.get("properties", {})}

    def render(self) -> None:
        doc = self.doc
        if self.view_mode.get() == t("Anteprima con dati"):
            from ...parsers.docx_parser import apply_placeholders
            import docx
            tmp = Path(tempfile.mkdtemp(prefix="mai_tpl_")) / "preview.docx"
            self.doc.save(str(tmp))
            doc = docx.Document(str(tmp))
            apply_placeholders(doc, self._sample_values())
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.para_index.clear()
        for kind, p in self._all_paragraphs(doc):
            start = self.text.index("end-1c")
            prefix = "    │ " if kind == "c" else ""
            self.text.insert("end", prefix + p.text + "\n", "cell" if kind == "c" else ())
            self.para_index.append((f"{start}+{len(prefix)}c", p))
        for m in _PLACEHOLDER_RE.finditer(self.text.get("1.0", "end")):
            self.text.tag_add("ph", f"1.0+{m.start()}c", f"1.0+{m.end()}c")
        if doc is not self.doc:
            self.para_index.clear()  # in anteprima la selezione non modifica il modello

    def make_field(self, schema_only: bool = False) -> None:
        name = re.sub(r"[^a-z0-9_]", "_", self.field_name.get().strip().lower()).strip("_")
        if not name or not re.match(r"^[a-z_]", name):
            self.win.toast(t("Scrivi un nome di campo (lettere, numeri, _)."), "warning")
            return
        props = self.schema.setdefault("properties", {})
        if name not in props:
            typ = TYPES[self.field_type.get()]
            spec: Dict[str, Any] = {"type": "string", "format": "date"} if typ == "date" else (
                {"type": "array", "items": {"type": "string"}} if typ == "array" else {"type": typ})
            if self.field_desc.get().strip():
                spec["description"] = self.field_desc.get().strip()
            props[name] = spec
            if self.field_req.get():
                self.schema.setdefault("required", []).append(name)
        if not schema_only:
            try:
                s_idx, e_idx = self.text.index("sel.first"), self.text.index("sel.last")
            except tk.TclError:
                self.win.toast(t("Seleziona prima il testo da sostituire nell'anteprima del modello."), "warning")
                return
            target = None
            for i, (start, p) in enumerate(self.para_index):
                end = self.para_index[i + 1][0] if i + 1 < len(self.para_index) else "end"
                if self.text.compare(s_idx, ">=", start) and self.text.compare(s_idx, "<", end):
                    target = (start, p)
                    break
            if target is None:
                self.win.toast(t("Selezione non valida (usa la vista Modello)."), "warning")
                return
            start, p = target
            a = len(self.text.get(start, s_idx))
            b = a + len(self.text.get(s_idx, e_idx).split("\n")[0])
            replace_span(p, a, min(b, len(p.text)), "{{" + name + "}}")
        self.dirty = True
        self.render()
        self._render_fields()
        self.win.toast(t("Campo «{n}» aggiunto.", n=name), "success")

    def save(self) -> None:
        if not self.dirty:
            self.close()
            return
        backup_dir = self.mod.folder_path / "_versions"
        backup_dir.mkdir(exist_ok=True)
        shutil.copy2(self.path, backup_dir / f"template_{time.strftime('%Y%m%d_%H%M%S')}{self.path.suffix}")
        self.doc.save(str(self.path))
        if self.schema != (self.mod.schema or {}):
            self.win.mm.bump_version(self.mod.slug, new_schema=self.schema)
        self.win.refresh_modules(quiet=True)
        self.win.toast(t("Template salvato (copia precedente in _versions)."), "success")
        self.close()

    def open_word(self) -> None:
        """Apre in Word una COPIA del template con le modifiche correnti (solo da consultare:
        per cambiare il modello usa "Salva template" o modifica il file nella cartella del modulo)."""
        tmp = Path(tempfile.mkdtemp(prefix="mai_tpl_")) / self.path.name
        self.doc.save(str(tmp))
        os.startfile(str(tmp))  # type: ignore[attr-defined]
        self.win.toast(t("Aperta una copia di consultazione: le modifiche fatte in Word non vengono salvate nel "
                         "modulo."), "info")

    def cancel(self) -> None:
        if self.dirty:
            from tkinter import messagebox
            if not messagebox.askyesno(t("Modifiche non salvate"), t("Chiudere senza salvare il template?"),
                                       parent=self):
                return
        super().cancel()
