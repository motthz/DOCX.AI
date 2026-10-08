"""Revisione della bozza AI, affiancata alle fonti.

- sinistra: descrizione dell'operatore (e documenti), con evidenziato il valore
  del campo selezionato
- destra: campi dello schema con controllo per tipo (interruttore, elenco,
  numero, testo), stato di verifica sulle fonti e "Migliora testo"
- salvataggio automatico della bozza ogni 20 secondi
"""

from __future__ import annotations

import json
import re
import threading
import time
import tkinter as tk
from typing import Any, Dict, List, Optional, Tuple

import customtkinter as ctk

from ...llm.grounding import FieldCheck, GroundingChecker, summarize
from ...llm.quality_scorer import score as quality_score
from ...module_manager import LoadedModule
from ..design import C, col, font
from ..i18n import t
from ..widgets import Chip, button, label
from .base import Dialog

LONG_KEYS = ("note", "descrizione", "diagnosi", "causa", "attivita", "intervento", "osservazioni", "anomalia",
             "argoment", "decision", "motivazion", "sintesi", "riassunto", "commento", "dettagli", "lavori",
             "relazione", "esito_descr", "conclusion", "ordine_del_giorno", "discussion")
STATUS_CHIP = {"ok": ("Trovato nelle fonti", "success"), "missing": ("Da verificare", "danger"),
               "inferred": ("Dedotto", "neutral"), "empty": ("Mancante", "warning")}
AUTOSAVE_S = 20


def _labelize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _missing(v: Any) -> bool:
    return v is None or (isinstance(v, str) and v.strip().upper() in ("", "NON_SPECIFICATO")) or \
        (isinstance(v, (list, dict)) and not v)


class ReviewDialog(Dialog):
    def __init__(self, win: Any, mod: LoadedModule, report_id: int, data: Dict[str, Any], *,
                 description: str = "", sources: Optional[List[str]] = None, grounding: bool = True,
                 notes: str = "", title: Optional[str] = None, approve_text: Optional[str] = None,
                 evidence: Optional[Dict[str, str]] = None):
        super().__init__(win.root, title or t("Revisione · {name}", name=mod.name), width=1240, height=840,
                         icon_name="list-checks",
                         subtitle=t("Controlla e correggi i campi: niente viene esportato senza la tua approvazione."))
        self.win = win
        self.mod = mod
        self.report_id = report_id
        self.schema = mod.schema or {}
        self.props: Dict[str, Any] = self.schema.get("properties", {}) or {}
        self.data = json.loads(json.dumps(data or {}))
        self.widgets: Dict[str, Tuple[str, Any]] = {}
        self.chips: Dict[str, Chip] = {}
        self.rows: Dict[str, ctk.CTkFrame] = {}
        self._dirty = False
        self._saved_at: Optional[str] = None
        self.sources = list(sources or [description])
        self.evidence = {k: v for k, v in (evidence or {}).items() if isinstance(v, str) and v.strip()}
        self.checker = GroundingChecker(sources or [description]) if grounding else None
        self.checks: Dict[str, FieldCheck] = {}

        paned = tk.PanedWindow(self.body, orient="horizontal", sashwidth=6, bd=0, bg=col("border"))
        paned.pack(fill="both", expand=True)

        # ----------------------------------------------------------- fonti
        left = ctk.CTkFrame(paned, fg_color=C["surface"], corner_radius=10, border_width=1,
                            border_color=C["border"])
        label(left, t("Fonti"), kind="h4").pack(anchor="w", padx=14, pady=(12, 0))
        label(left, t("Clicca un campo a destra per evidenziarne il valore qui."), kind="caption",
              muted=True).pack(anchor="w", padx=14)
        self.src = tk.Text(left, wrap="word", relief="flat", bd=0, padx=12, pady=10,
                           font=("Segoe UI", 10), bg=col("surface"), fg=col("text"),
                           insertbackground=col("text"), highlightthickness=0)
        self.src.pack(fill="both", expand=True, padx=2, pady=(6, 2))
        srcs = sources or [description]
        self.src.insert("end", t("INFORMAZIONI FORNITE") + "\n", "h")
        self.src.insert("end", (description or t("(nessuna)")) + "\n")
        for i, s in enumerate(srcs[1:], 1):
            self.src.insert("end", "\n" + t("DOCUMENTO DI RIFERIMENTO {n}", n=i) + "\n", "h")
            self.src.insert("end", s[:6000] + ("…" if len(s) > 6000 else "") + "\n")
        self.src.tag_configure("h", font=("Segoe UI", 9, "bold"), foreground=col("text_muted"))
        self.src.tag_configure("hit", background=col("warning_soft"), foreground=col("text"))
        self.src.configure(state="disabled")

        # ----------------------------------------------------------- campi
        right = ctk.CTkFrame(paned, fg_color="transparent")
        stats = ctk.CTkFrame(right, fg_color="transparent")
        stats.pack(fill="x", pady=(0, 8))
        self.q_chip = Chip(stats, "", "info")
        self.q_chip.pack(side="left")
        self.miss_chip = Chip(stats, "", "warning")
        self.miss_chip.pack(side="left", padx=6)
        self.ground_chip = Chip(stats, "", "danger")
        self.ground_chip.pack(side="left")
        form = ctk.CTkScrollableFrame(right, fg_color="transparent")
        form.pack(fill="both", expand=True)
        required = set(self.schema.get("required", []) or [])
        for key, spec in self.props.items():
            self._field(form, key, spec or {}, key in required)

        nbox = ctk.CTkFrame(right, fg_color="transparent")
        nbox.pack(fill="x", pady=(8, 0))
        label(nbox, t("Note del revisore (stampate nel PDF)"), kind="small_b").pack(anchor="w")
        self.notes = ctk.CTkTextbox(nbox, height=60, border_width=1, border_color=C["border"])
        self.notes.pack(fill="x")
        self.notes.insert("1.0", notes or "")
        self.notes.bind("<KeyRelease>", lambda e: self._changed(), add="+")

        paned.add(left, minsize=260, width=420)
        paned.add(right, minsize=520)

        # ----------------------------------------------------------- footer
        self.saved_lbl = label(self.footer, "", kind="caption", muted=True)
        self.saved_lbl.pack(side="left", padx=20)
        button(self.footer, approve_text or t("Approva e genera il documento"), self._approve, kind="primary",
               icon_name="check").pack(side="right", padx=(8, 20), pady=12)
        button(self.footer, t("Salva bozza"), lambda: self._autosave(force=True), icon_name="save").pack(
            side="right", pady=12)
        button(self.footer, t("Chiudi"), self.cancel, kind="ghost").pack(side="right", padx=8, pady=12)

        self._refresh()
        # parte dal primo campo (il focus su un campo puo' far scorrere il modulo a meta')
        self.after(350, lambda: form._parent_canvas.yview_moveto(0))
        self.after(AUTOSAVE_S * 1000, self._autosave_loop)

    # ------------------------------------------------------------------ campi
    def _field(self, parent, key: str, spec: Dict[str, Any], required: bool) -> None:
        row = ctk.CTkFrame(parent, fg_color=C["surface"], corner_radius=10, border_width=1,
                           border_color=C["border"])
        row.pack(fill="x", pady=4, padx=(0, 6))
        self.rows[key] = row
        head = ctk.CTkFrame(row, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(10, 4))
        title = spec.get("title") or _labelize(key)
        ctk.CTkLabel(head, text=title + (" *" if required else ""), font=font("body_b"),
                     text_color=C["text"]).pack(side="left")
        chip = Chip(head, "", "neutral")
        chip.pack(side="right")
        self.chips[key] = chip
        if spec.get("description"):
            label(row, spec["description"], kind="caption", muted=True, wraplength=560).pack(
                fill="x", padx=12)
        holder = ctk.CTkFrame(row, fg_color="transparent")
        holder.pack(fill="x", padx=12, pady=(4, 12))
        value = self.data.get(key)
        # il segnaposto interno "NON_SPECIFICATO" non va mostrato: il campo resta vuoto (chip "Mancante")
        if isinstance(value, str) and value.strip().upper() == "NON_SPECIFICATO" and not spec.get("enum"):
            value = ""
        elif spec.get("enum") and value not in spec["enum"]:
            value = ""  # l'AI non ha trovato il valore: scelta lasciata all'utente
        elif isinstance(value, list):
            value = [v for v in value if not (isinstance(v, str) and v.strip().upper() == "NON_SPECIFICATO")]
        typ = spec.get("type")
        if isinstance(typ, list):
            typ = next((x for x in typ if x != "null"), "string")
        if spec.get("enum"):
            vals = self._enum_values(key, spec["enum"])
            var = ctk.StringVar(value="" if value is None else str(value))
            w = ctk.CTkComboBox(holder, values=vals, variable=var, state="readonly", height=32,
                                command=lambda v: self._changed())
            w.pack(fill="x")
            self.widgets[key] = ("enum", var)
        elif typ == "boolean":
            var = ctk.BooleanVar(value=bool(value) if not isinstance(value, str)
                                 else value.strip().lower() in ("true", "si", "sì", "1", "x"))
            ctk.CTkSwitch(holder, text=t("Sì"), variable=var, command=self._changed).pack(anchor="w")
            self.widgets[key] = ("bool", var)
        elif typ in ("number", "integer"):
            var = ctk.StringVar(value="" if value in (None, "NON_SPECIFICATO") else str(value))
            e = ctk.CTkEntry(holder, textvariable=var, height=32)
            e.pack(fill="x")
            var.trace_add("write", lambda *a: self._changed())
            self.widgets[key] = ("number" if typ == "number" else "integer", var)
        elif typ in ("array", "object"):
            box = ctk.CTkTextbox(holder, height=90, border_width=1, border_color=C["border"], font=font("small"))
            box.pack(fill="x")
            box.insert("1.0", self._array_to_text(value) if typ == "array"
                       else json.dumps(value or {}, ensure_ascii=False, indent=2))
            box.bind("<KeyRelease>", lambda e: self._changed(), add="+")
            hint = (t("Un elemento per riga; per gli oggetti: chiave=valore ; chiave2=valore2")
                    if typ == "array" else t("Oggetto JSON"))
            label(holder, hint, kind="caption", muted=True).pack(anchor="w")
            self.widgets[key] = (typ, box)
        else:
            text = "" if value is None else str(value)
            if len(text) > 80 or any(k in key.lower() for k in LONG_KEYS) \
                    or "descri" in str(spec.get("description") or "").lower():
                box = ctk.CTkTextbox(holder, height=80, wrap="word", border_width=1, border_color=C["border"])
                box.pack(fill="x")
                box.insert("1.0", text)
                box.bind("<KeyRelease>", lambda e: self._changed(), add="+")
                imp = button(holder, t("Migliora testo"), lambda: None, kind="ghost",
                             icon_name="wand-sparkles", height=28)
                imp.configure(command=lambda k=key, b=box, btn=imp: self._improve(k, b, btn))
                imp.pack(anchor="e", pady=(4, 0))
                from ..tooltip import bind as tip
                tip(imp, t("Corregge forma e grammatica senza aggiungere dati. Se il campo è vuoto, "
                           "l'AI lo scrive dalle informazioni fornite."))
                self.widgets[key] = ("text", box)
            else:
                var = ctk.StringVar(value=text)
                ctk.CTkEntry(holder, textvariable=var, height=32).pack(fill="x")
                var.trace_add("write", lambda *a: self._changed())
                self.widgets[key] = ("string", var)
        for w in (row, head, holder):
            w.bind("<Button-1>", lambda e, k=key: self._highlight_source(k), add="+")

    def _enum_values(self, key: str, enum: List[Any]) -> List[str]:
        base = [str(e) for e in enum]
        try:
            raw = self.win.db.get_setting(f"enum_history.{self.mod.slug}.{key}") or "[]"
            recent = [str(x) for x in json.loads(raw)][:5]
        except ValueError:
            recent = []
        return list(dict.fromkeys([r for r in recent if r in base] + base))

    @staticmethod
    def _array_to_text(value: Any) -> str:
        if not isinstance(value, list):
            return ""
        return "\n".join(" ; ".join(f"{k}={v}" for k, v in item.items()) if isinstance(item, dict) else str(item)
                         for item in value)

    def _text_to_array(self, raw: str, spec: Dict[str, Any]) -> list:
        items = (spec.get("items") or {}) if isinstance(spec, dict) else {}
        out: list = []
        for line in (ln.strip() for ln in raw.splitlines()):
            if not line:
                continue
            if items.get("type") == "object":
                obj = {}
                for part in (p.strip() for p in line.split(";") if p.strip()):
                    if "=" in part:
                        k, v = part.split("=", 1)
                        obj[k.strip()] = v.strip()
                out.append(obj)
            else:
                out.append(line)
        return out

    # ------------------------------------------------------------------ dati
    def _value(self, key: str, strict: bool = False) -> Any:
        kind, w = self.widgets[key]
        spec = self.props.get(key) or {}
        if kind in ("enum", "string"):
            return w.get()
        if kind == "bool":
            return bool(w.get())
        if kind in ("number", "integer"):
            raw = w.get().strip().replace(" ", "")
            if "," in raw:  # formato italiano: 1.234,50
                raw = raw.replace(".", "").replace(",", ".")
            if not raw:
                return None
            try:
                return int(float(raw)) if kind == "integer" else float(raw)
            except ValueError:
                if strict:
                    raise ValueError(t("{field}: numero non valido", field=_labelize(key)))
                return raw
        raw = w.get("1.0", "end").rstrip("\n")
        if kind == "array":
            return self._text_to_array(raw, spec)
        if kind == "object":
            try:
                return json.loads(raw) if raw.strip() else {}
            except ValueError:
                if strict:
                    raise ValueError(t("{field}: JSON non valido", field=_labelize(key)))
                return raw
        return raw

    def collect(self, strict: bool = False) -> Dict[str, Any]:
        out = dict(self.data)
        for key in self.widgets:
            out[key] = self._value(key, strict)
        return out

    def _changed(self) -> None:
        self._dirty = True
        if getattr(self, "_refresh_after", None):
            self.after_cancel(self._refresh_after)
        self._refresh_after = self.after(250, self._refresh)

    def _refresh(self) -> None:
        data = self.collect()
        if self.checker is not None:
            self.checks = self.checker.check(data, self.schema)
        n_missing = 0
        for key in self.widgets:
            v = data.get(key)
            check = self.checks.get(key)
            if _missing(v):
                status = "empty"
            elif check is not None:
                status = check.status
            else:
                status = "inferred"
            n_missing += status == "empty"
            text, tone = STATUS_CHIP[status]
            chip = self.chips[key]
            chip.set(t(text), tone)
            from ..tooltip import bind as tip
            if not getattr(chip, "_tip", False) and (status == "missing" or self.evidence.get(key)):
                tip(chip, lambda k=key: self._chip_tip(k))
                chip._tip = True  # type: ignore[attr-defined]
            self.rows[key].configure(border_color=C["danger"] if status == "missing"
                                     else C["warning"] if status == "empty" else C["border"])
        q = max(0, min(100, int(quality_score(data, self.schema) or 0)))
        self.q_chip.set(t("Qualità {q}/100", q=q), "success" if q >= 75 else "warning" if q >= 45 else "danger")
        self.miss_chip.set((t("1 campo mancante") if n_missing == 1 else t("{n} campi mancanti", n=n_missing))
                           if n_missing else t("Tutti i campi compilati"),
                           "warning" if n_missing else "success")
        if self.checker is not None:
            n_bad = summarize(self.checks)["missing"]
            self.ground_chip.set((t("1 valore da verificare") if n_bad == 1 else t("{n} valori da verificare", n=n_bad))
                                 if n_bad else t("Valori trovati nelle fonti"),
                                 "danger" if n_bad else "success")
        else:
            self.ground_chip.pack_forget()

    def _chip_tip(self, key: str) -> str:
        parts = []
        check = self.checks.get(key)
        if check is not None and check.status == "missing":
            parts.append(check.message)
        if self.evidence.get(key):
            parts.append(t("Preso dal testo: «{q}»", q=self.evidence[key]))
        return "\n".join(parts)

    def _highlight_source(self, key: str) -> None:
        v = self.collect().get(key)
        self.src.tag_remove("hit", "1.0", "end")
        terms = []
        if self.evidence.get(key) and not _missing(v):
            terms.append(self.evidence[key])  # frase da cui l'AI ha preso il valore
        if isinstance(v, str) and not _missing(v):
            terms += [v] + re.findall(r"[\w\-/.]*\d[\w\-/.]*|[A-ZÀ-Ý][a-zà-ÿ]{2,}", v)
        first = None
        for term in terms:
            if len(term) < 2:
                continue
            start = "1.0"
            while True:
                pos = self.src.search(term, start, stopindex="end", nocase=True)
                if not pos:
                    break
                end = f"{pos}+{len(term)}c"
                self.src.tag_add("hit", pos, end)
                first = first or pos
                start = end
        if first:
            self.src.see(first)

    # ------------------------------------------------------------------ AI
    def _improve(self, key: str, box: ctk.CTkTextbox, btn: Any = None) -> None:
        if getattr(self, "_improving", False):
            return
        text = box.get("1.0", "end").strip()
        spec = self.props.get(key) or {}
        title = spec.get("title") or _labelize(key)
        sources = [s for s in (self.sources or []) if s and s.strip()]
        if len(text) < 5 and not sources:
            self.win.toast(t("Il campo è vuoto: scrivi prima il testo da migliorare."), "info")
            return
        self._improving = True
        box.configure(state="disabled")
        if btn is not None:
            btn.configure(state="disabled", text=t("Riscrittura in corso…"))

        def restore():
            self._improving = False
            try:
                box.configure(state="normal")
                if btn is not None:
                    btn.configure(state="normal", text=t("Migliora testo"))
            except tk.TclError:
                pass  # finestra chiusa nel frattempo

        def work():
            try:
                out, warnings = self.win.ai.improve_text_checked(
                    text, title, document=self.mod.ai_context(), sources=sources,
                    field_description=str(spec.get("description") or ""))
                self.after(0, lambda: (restore(), self._improved(box, text, out, warnings)))
            except Exception as exc:  # noqa: BLE001
                self.after(0, lambda e=exc: (restore(), self.win.toast(t("Migliora testo: {e}", e=e), "warning")))
        self.win.toast(t("L'AI sta scrivendo il testo…") if len(text) < 5 else t("L'AI sta riscrivendo il testo…"),
                       "info")
        threading.Thread(target=work, daemon=True, name="improve").start()

    def _improved(self, box, before: str, after: str, warnings: Optional[List[str]] = None) -> None:
        try:
            box.delete("1.0", "end")
            box.insert("1.0", after)
        except tk.TclError:
            return
        self._changed()
        undo = (t("Annulla"), lambda: (box.delete("1.0", "end"), box.insert("1.0", before), self._changed()))
        if warnings:
            self.win.toast(t("Testo riscritto, ma controllalo: {w}", w="; ".join(warnings)), "warning", action=undo)
        else:
            self.win.toast(t("Testo riscritto. Controlla che non manchi nulla."), "success", action=undo)

    # ------------------------------------------------------------------ salvataggio
    def _autosave(self, force: bool = False) -> None:
        if not (self._dirty or force) or self.report_id is None:
            return
        try:
            data = self.collect()
            self.win.reports.revise_draft(self.report_id, data)
            self.win.db.update_report(self.report_id, review_notes=self.notes.get("1.0", "end").strip())
            self._dirty = False
            self._saved_at = time.strftime("%H:%M:%S")
            self.saved_lbl.configure(text=t("Bozza salvata alle {ts}", ts=self._saved_at))
            if force:
                self.win.toast(t("Bozza salvata."), "success")
        except Exception as exc:  # noqa: BLE001
            self.saved_lbl.configure(text=t("Salvataggio non riuscito: {e}", e=exc))

    def _autosave_loop(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._autosave()
        self.after(AUTOSAVE_S * 1000, self._autosave_loop)

    def _remember_enums(self, data: Dict[str, Any]) -> None:
        for key, spec in self.props.items():
            if (spec or {}).get("enum") and data.get(key):
                k = f"enum_history.{self.mod.slug}.{key}"
                try:
                    prev = json.loads(self.win.db.get_setting(k) or "[]")
                except ValueError:
                    prev = []
                cur = str(data[key])
                self.win.db.set_setting(k, json.dumps(([cur] + [p for p in prev if p != cur])[:8]))

    def _approve(self) -> None:
        try:
            data = self.collect(strict=True)
        except ValueError as exc:
            self.win.toast(str(exc), "error")
            return
        required = set(self.schema.get("required") or [])
        for key, spec in self.props.items():  # campi numerici/scelte vuoti -> rimossi se non obbligatori
            if data.get(key) is None and (spec or {}).get("type") in ("number", "integer"):
                data.pop(key, None)
            elif data.get(key) == "" and (spec or {}).get("enum") and key not in required:
                data.pop(key, None)
        try:
            import jsonschema
            jsonschema.validate(data, self.schema)
        except Exception as exc:  # noqa: BLE001
            path = "/".join(str(p) for p in getattr(exc, "absolute_path", [])) or ""
            self.win.toast(t("Dato non valido {field}: {msg}", field=path, msg=getattr(exc, "message", exc)),
                           "error")
            return
        n_bad = summarize(self.checks)["missing"] if self.checks else 0
        if n_bad:
            from tkinter import messagebox
            if not messagebox.askyesno(
                    t("Valori da verificare"),
                    t("1 valore non compare nelle fonti e potrebbe essere stato inventato dall'AI.\n\n"
                      "L'hai controllato e vuoi approvare comunque?") if n_bad == 1 else
                    t("{n} valori non compaiono nelle fonti e potrebbero essere stati inventati dall'AI.\n\n"
                      "Li hai controllati e vuoi approvare comunque?", n=n_bad), parent=self):
                return
        self._remember_enums(data)
        data["__review_notes__"] = self.notes.get("1.0", "end").strip()
        self.result = data
        self.close()

    def cancel(self) -> None:
        self._autosave()
        super().cancel()
