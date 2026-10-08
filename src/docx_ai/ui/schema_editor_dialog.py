"""JSON schema editor dialog: Treeview guided for Draft-07-ish simple schemas.

Creates/edits a module's schema.json with fields: Field / Type / Required? / Description.
Supports add string / number / integer / boolean / enum / array<string> / object (empty stub).
Before saving, prevalidates via jsonschema Draft7Validator.check_schema.
"""

from __future__ import annotations

import copy
import re
import tkinter as tk
from tkinter import messagebox, simpledialog
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
        self.top.geometry("940x560")
        self.top.minsize(820, 400)
        self.top.transient(master)
        self.top.grab_set()
        self._build()

    # --------------------------------------------------------------
    def _build(self) -> None:
        pad = {"padx": 10, "pady": 6}
        ttk.Label(self.top, text="Campi del modulo — doppio clic su una riga per modificarla:",
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

    @staticmethod
    def _type_str(spec: Dict[str, Any]) -> str:
        if isinstance(spec.get("enum"), list):
            return "enum"
        t = spec.get("type", "string")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), "string")
        if t == "array":
            # elenco di righe con piu' colonne (azioni: attivita/responsabile/scadenza)
            items = spec.get("items") if isinstance(spec.get("items"), dict) else {}
            return "array<object>" if items.get("type") == "object" else "array<string>"
        if t == "string" and spec.get("format") in ("date", "date-time"):
            return "string (data)"
        return t if t in ALLOWED_TYPES else "string"

    def _row_values(self, name: str, spec: Dict[str, Any], required: bool) -> tuple:
        desc = spec.get("description", self._descriptions.get(name, ""))
        if isinstance(spec.get("enum"), list):
            desc = (desc + "  " if desc else "") + "[" + ", ".join(str(v) for v in spec["enum"]) + "]"
        return (name, self._type_str(spec), "✓" if required else "", desc)

    def _load_from_schema(self) -> None:
        # Ogni riga conserva la definizione completa del campo (formato data, valori
        # dell'elenco, titolo...): salvare senza modifiche non deve perdere nulla.
        props = (self._schema or {}).get("properties", {}) or {}
        req = set((self._schema or {}).get("required", []) or [])
        self._specs: Dict[str, Dict[str, Any]] = {}
        self._orig_names: Dict[str, str] = {}
        for field, spec in props.items():
            spec = copy.deepcopy(spec if isinstance(spec, dict) else {})
            iid = self._tv.insert("", "end", values=self._row_values(field, spec, field in req))
            self._specs[iid] = spec
            self._orig_names[iid] = field

    def _ask_enum(self, initial: str = "") -> Optional[List[str]]:
        vals = simpledialog.askstring("Valori ammessi",
                                      "Valori separati da virgola (es. Sì, No, Non specificato):",
                                      initialvalue=initial, parent=self.top)
        if vals is None:
            return None
        return [v.strip() for v in vals.split(",") if v.strip()]

    def _valid_name(self, name: str) -> bool:
        if re.fullmatch(r"[^\W\d]\w*", name):
            return True
        messagebox.showwarning("Attenzione", "Il nome può contenere solo lettere, numeri e _ "
                               "(niente spazi) e non può iniziare con un numero.", parent=self.top)
        return False

    def _add_row(self, type_str: str) -> None:
        name = simpledialog.askstring("Nuovo campo", "Nome campo (lettere/numeri/_):", parent=self.top)
        if not name or not name.strip():
            return
        name = name.strip()
        if not self._valid_name(name):
            return
        existing = set(self._tv.set(r, "field") for r in self._tv.get_children(""))
        if name in existing:
            messagebox.showwarning("Attenzione", f"Campo '{name}' già esistente.", parent=self.top)
            return
        if type_str == "enum":
            vals = self._ask_enum()
            if not vals:
                return
            spec: Dict[str, Any] = {"type": "string", "enum": vals}
        elif type_str == "array<string>":
            spec = {"type": "array", "items": {"type": "string"}}
        else:
            spec = {"type": type_str}
        iid = self._tv.insert("", "end", values=self._row_values(name, spec, False))
        self._specs[iid] = spec

    def _delete_selected(self) -> None:
        for iid in self._tv.selection():
            self._tv.delete(iid)
            self._specs.pop(iid, None)

    def _on_double(self, _evt=None) -> None:
        sel = self._tv.selection()
        if not sel:
            return
        iid = sel[0]
        field = str(self._tv.item(iid, "values")[0])
        spec = self._specs.setdefault(iid, {"type": "string"})
        new_name = simpledialog.askstring("Modifica nome", "Nome campo:", initialvalue=field, parent=self.top)
        if new_name is None:
            return
        new_name = new_name.strip() or field
        if not self._valid_name(new_name):
            return
        new_desc = simpledialog.askstring("Descrizione", "Descrizione per l'AI (cosa inserire nel campo):",
                                          initialvalue=spec.get("description", ""), parent=self.top)
        if new_desc is None:
            return
        if isinstance(spec.get("enum"), list):
            vals = self._ask_enum(", ".join(str(v) for v in spec["enum"]))
            if vals is None:
                return
            if vals:
                spec["enum"] = vals
        req_val = messagebox.askyesno("Obbligatorio?", f"Il campo '{new_name}' è obbligatorio?",
                                      parent=self.top)
        if new_desc.strip():
            spec["description"] = new_desc.strip()
        else:
            spec.pop("description", None)
        old = self._orig_names.get(iid)
        if old and new_name != old:
            messagebox.showinfo("Campo rinominato",
                                "Ricorda di rinominare anche il segnaposto {{" + old + "}} in {{" + new_name
                                + "}} nel template, altrimenti il campo non verrà compilato.", parent=self.top)
        self._tv.item(iid, values=self._row_values(new_name, spec, req_val))

    # --------------------------------------------------------------
    def _collect_schema(self) -> Dict[str, Any]:
        properties: Dict[str, Any] = {}
        required: List[str] = []
        for iid in self._tv.get_children(""):
            field, _type_str, req, _desc = self._tv.item(iid, "values")
            field = str(field).strip()
            if not field:
                continue
            properties[field] = copy.deepcopy(self._specs.get(iid) or {"type": "string"})
            if "✓" in str(req):
                required.append(field)
        out: Dict[str, Any] = dict(self._schema or {})  # conserva $schema, title e altre chiavi
        out.setdefault("$schema", "https://json-schema.org/draft/2020-12/schema")
        out.setdefault("title", "Modulo")
        out.update({"type": "object", "additionalProperties": False, "properties": properties,
                    "required": required})
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
            messagebox.showerror("Schema non valido",
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
