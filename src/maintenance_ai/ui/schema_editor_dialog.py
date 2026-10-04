"""JSON schema editor dialog: Treeview guided for Draft-07-ish simple schemas.

Creates/edits a module's schema.json with fields: Field / Type / Required? / Description.
Supports add string / number / integer / boolean / enum / array<string> / object (empty stub).
Before saving, prevalidates via jsonschema Draft7Validator.check_schema.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Dict, List, Optional

try:
    from tkinter import ttk
except Exception:  # noqa: BLE001
    ttk = None  # type: ignore


ALLOWED_TYPES = ("string", "integer", "number", "boolean", "array<string>", "enum")


class SchemaEditorDialog:
    """Modal dialog. Call `.run()` returns (accepted: bool, new_schema_dict)."""

    def __init__(self, master, schema: Dict[str, Any], *, title: str = "Modifica schema JSON",
                 initial_descriptions: Optional[Dict[str, str]] = None):
        self.result = False
        self.new_schema: Dict[str, Any] = {}
        self._schema = dict(schema or {})
        self._descriptions = dict(initial_descriptions or {})
        self.top = tk.Toplevel(master)
        self.top.title(title)
        self.top.geometry("820x560")
        self.top.transient(master)
        self.top.grab_set()
        self._build()

    # --------------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        ttk.Label(self.top, text="Schema JSON per il modulo — modifica i campi strutturali:",
                  style="Title.H4.TLabel").pack(anchor="w", **pad)
        frame = ttk.Frame(self.top)
        frame.pack(fill="both", expand=True, **pad)
        cols = ("field", "type", "required", "description")
        tv = ttk.Treeview(frame, columns=cols, show="headings")
        for c, label, w in (("field", "Campo", 160), ("type", "Tipo", 130),
                            ("required", "Obbl.", 60), ("description", "Descrizione", 420)):
            tv.heading(c, text=label)
            tv.column(c, width=w, anchor="w")
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tv = tv
        tv.bind("<Double-1>", self._on_double)

        # Control buttons
        btns = ttk.Frame(self.top)
        btns.pack(fill="x", padx=10, pady=(0, 6))
        for (lbl, cmd, accent) in [
            ("Stringa", lambda: self._add_row("string"), False),
            ("Numero intero", lambda: self._add_row("integer"), False),
            ("Numero dec.", lambda: self._add_row("number"), False),
            ("Booleano", lambda: self._add_row("boolean"), False),
            ("Enum", lambda: self._add_row("enum"), False),
            ("Lista str.", lambda: self._add_row("array<string>"), False),
            ("Elimina", self._delete_selected, False),
            ("Salva", self._on_save, True),
            ("Annulla", self._on_cancel, False),
        ]:
            b = ttk.Button(btns, text=lbl, command=cmd,
                           style="Accent.TButton" if accent else "TButton")
            b.pack(side="left", padx=4, pady=2)
        self._load_from_schema()

    def _load_from_schema(self) -> None:
        props = (self._schema or {}).get("properties", {}) or {}
        req = set((self._schema or {}).get("required", []) or [])
        for field, spec in props.items():
            t = spec.get("type", "string")
            if t == "array":
                items = spec.get("items", {})
                if isinstance(items, dict) and items.get("type") == "string":
                    type_str = "array<string>"
                else:
                    type_str = "array<string>"
            else:
                type_str = t if t in ALLOWED_TYPES else "string"
            if isinstance(spec.get("enum"), list):
                type_str = "enum"
            desc = spec.get("description", self._descriptions.get(field, ""))
            values = (field, type_str, "✓" if field in req else "", desc)
            self._tv.insert("", "end", values=values)

    def _add_row(self, type_str: str) -> None:
        name = tk.simpledialog.askstring("Nuovo campo", "Nome campo (lettere/numeri/_):",
                                         parent=self.top)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        existing = set(self._tv.set(r, "field") for r in self._tv.get_children(""))
        if name in existing:
            tk.messagebox.showwarning("Attenzione", f"Campo '{name}' già esistente.", parent=self.top)
            return
        desc = ""
        if type_str == "enum":
            vals = tk.simpledialog.askstring("Enum values",
                                             "Valori separati da virgola (es. Sì,No,Non specificato):",
                                             parent=self.top)
            if not vals:
                return
            desc = f"VALORI_AMMESSI: {vals}"
        self._tv.insert("", "end", values=(name, type_str, "", desc))

    def _delete_selected(self) -> None:
        for iid in self._tv.selection():
            self._tv.delete(iid)

    def _on_double(self, _evt=None) -> None:
        sel = self._tv.selection()
        if not sel:
            return
        iid = sel[0]
        field, type_str, req, desc = self._tv.item(iid, "values")
        new_name = tk.simpledialog.askstring("Modifica nome", "Nome campo:",
                                             initialvalue=field, parent=self.top)
        if new_name is None:
            return
        new_desc = tk.simpledialog.askstring("Descrizione / Note",
                                             "Descrizione (o VALORI_AMMESSI: A,B,C per enum):",
                                             initialvalue=desc, parent=self.top)
        if new_desc is None:
            return
        req_val = tk.messagebox.askyesno("Obbligatorio?", f"Il campo '{new_name}' è obbligatorio?",
                                         parent=self.top)
        self._tv.item(iid, values=(new_name.strip() or field, type_str,
                                   "✓" if req_val else "", new_desc or ""))

    # --------------------------------------------------------------
    def _collect_schema(self) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for iid in self._tv.get_children(""):
            field, type_str, req, desc = self._tv.item(iid, "values")
            field = str(field).strip()
            if not field:
                continue
            spec: Dict[str, Any] = {}
            if desc:
                spec["description"] = str(desc)
            t = str(type_str)
            if t == "enum" or (desc and desc.startswith("VALORI_AMMESSI:")):
                vals: List[str] = []
                if desc and desc.startswith("VALORI_AMMESSI:"):
                    vs = str(desc)[len("VALORI_AMMESSI:"):].strip()
                    vals = [v.strip() for v in vs.split(",") if v.strip()]
                if vals:
                    spec["enum"] = vals
                    spec["type"] = "string"
                else:
                    spec["type"] = "string"
            elif t == "array<string>":
                spec["type"] = "array"
                spec["items"] = {"type": "string"}
            elif t in ("string", "integer", "number", "boolean"):
                spec["type"] = t
            else:
                spec["type"] = "string"
            properties[field] = spec
            if "✓" in str(req):
                required.append(field)
        out: Dict[str, Any] = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": (self._schema or {}).get("title", "Modulo"),
            "type": "object",
            "additionalProperties": False,
            "properties": properties,
            "required": required,
        }
        return out

    def _on_save(self) -> None:
        sch = self._collect_schema()
        try:
            import jsonschema
            try:
                jsonschema.Draft7Validator.check_schema(sch)
            except Exception:  # noqa: BLE001
                try:
                    jsonschema.validators.validator_for(sch).check_schema(sch)
                except Exception as ve2:  # noqa: BLE001
                    raise ve2
        except Exception as exc:  # noqa: BLE001
            tk.messagebox.showerror("Schema non valido",
                                    f"Lo schema prodotto non è valido per jsonschema Draft-07:\n{exc}",
                                    parent=self.top)
            return
        self.new_schema = sch
        self.result = True
        self.top.destroy()

    def _on_cancel(self) -> None:
        self.result = False
        self.new_schema = {}
        self.top.destroy()

    def run(self) -> tuple:
        self.top.wait_window()
        return (self.result, self.new_schema)
