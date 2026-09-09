"""Review screen: modern PREMIUM styled dialog for approving LLM output.

Displays extracted JSON fields inside RoundedCards and lets the user edit
before approval. Highlights NON_SPECIFICATO entries with a warm warning
accent and shows a LIVE counter of missing fields in the gradient header.

Feature-upgrade extras (FR6, FR7, FR14, FR17):
  - Top quality banner green/yellow/red based on quality_score 0-100.
  - Enum Comboboxes augmented with the user's last-5 historical entries.
  - Tooltip on every field label showing the schema description.
  - LabelFrame "Note revisore" (5 rows) → saved to reports.review_notes via
    the `__review_notes__` key in the approved result dict.
"""

from __future__ import annotations

import json
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from .theme import (
    COLORS,
    FONTS,
    FONT_FAMILY,
    GradientCanvas,
    RoundedCard,
    ModernTheme,
    apply_theme,
    bind_tooltip,
    center_window,
    make_scrollable_frame,
)
from ..llm.quality_scorer import quality_band, score as quality_score, quality_text


def _labelize(key: str) -> str:
    return key.replace("_", " ").strip().title()


def _looks_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and (
        value.strip() == "" or value.strip().upper() == "NON_SPECIFICATO"
    ):
        return True
    if isinstance(value, (list, dict)) and len(value) == 0:
        return True
    return False


def _entry_style(**overrides):
    base = ModernTheme.text_widget_kwargs(multiline=False)
    base.update(overrides)
    return base


def _text_style(**overrides):
    base = ModernTheme.text_widget_kwargs(multiline=True)
    base.update(overrides)
    return base


def _detect_dpi_scale(master: tk.Misc) -> float:
    scale = 1.0
    try:
        if sys.platform != "win32":
            try:
                _fb = master.winfo_fpixels("1i") / 72.0
                return max(_fb, 1.0)
            except Exception:
                return 1.0
    except Exception:
        pass
    try:
        import ctypes
        try:
            _shcore = ctypes.windll.shcore
            _monitor = _shcore.MonitorFromWindow(
                ctypes.windll.user32.GetDesktopWindow(), 0)
            _sf = ctypes.c_uint()
            if _shcore.GetScaleFactorForMonitor(
                    _monitor, ctypes.byref(_sf)) == 0:
                scale = _sf.value / 100.0
        except Exception:
            try:
                _hdc = ctypes.windll.user32.GetDC(0)
                _dpi = ctypes.windll.gdi32.GetDeviceCaps(_hdc, 88)
                ctypes.windll.user32.ReleaseDC(0, _hdc)
                if _dpi and _dpi > 0:
                    scale = _dpi / 96.0
            except Exception:
                pass
    except Exception:
        pass
    try:
        _fb = master.winfo_fpixels("1i") / 72.0
        scale = max(scale, _fb)
    except Exception:
        pass
    return max(scale, 1.0)


class ReviewDialog(tk.Toplevel):
    def __init__(self, master: tk.Misc, schema: Dict[str, Any],
                 draft_data: Dict[str, Any], title: str = "Revisione bozza",
                 *,
                 module_slug: Optional[str] = None,
                 db: Any = None,
                 initial_review_notes: str = ""):
        super().__init__(master)
        self.title(title)
        self.configure(bg=COLORS["white"])
        self.schema = schema
        self._data: Dict[str, Any] = json.loads(json.dumps(draft_data))
        self.result: Optional[Dict[str, Any]] = None
        self._widgets: Dict[str, Tuple[str, Any, Any]] = {}
        self._field_cards: Dict[str, RoundedCard] = {}
        self._field_missing_labels: Dict[str, tk.Label] = {}
        self._field_inner_frames: Dict[str, tk.Frame] = {}
        self._module_slug = module_slug
        self._db = db
        self._review_notes_initial = initial_review_notes or ""
        self._quality_score: int = max(0, min(100, int(quality_score(self._data, schema) or 0)))

        self._dpi_scale = _detect_dpi_scale(self)
        try:
            _tk_scale = self.tk.call("tk", "scaling")
            if _tk_scale and float(_tk_scale) < self._dpi_scale * 0.9:
                try:
                    self.tk.call("tk", "scaling", self._dpi_scale)
                except Exception:
                    pass
        except Exception:
            pass

        def _wp(base_px: int) -> int:
            return max(int(round(base_px * self._dpi_scale)), base_px)
        self._wp = _wp

        try:
            apply_theme(self)
        except Exception:
            pass

        base_w = 1100
        base_h = 760
        width = int(round(base_w * min(self._dpi_scale, 1.25)))
        height = int(round(base_h * min(self._dpi_scale, 1.25)))
        self.geometry(f"{width}x{height}")
        self.minsize(
            int(round(920 * min(self._dpi_scale, 1.15))),
            int(round(640 * min(self._dpi_scale, 1.15))),
        )
        center_window(self, width, height)
        self.transient(master)
        self.grab_set()

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.after(120, self._refresh_live)

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        _wp = self._wp

        head = GradientCanvas(self, COLORS["primary_800"], COLORS["slate_900"],
                              height=108, direction="horizontal")
        head.pack(fill="x")
        header_inner = tk.Frame(self, bg=COLORS["primary_800"])
        head.create_window((26, 18), anchor="nw", window=header_inner,
                           tags="hdr")
        def _hr(_e=None):
            try:
                w = head.winfo_width() - 52
                if w < 500: w = 500
                header_inner.configure(width=w)
            except Exception: pass
        head.bind("<Configure>", _hr, add="+")

        left = tk.Frame(header_inner, bg=COLORS["primary_800"])
        left.pack(side="left", fill="y")
        icon_wrap = tk.Frame(left, bg=COLORS["white"], bd=0, highlightthickness=0)
        icon_wrap.pack(side="left")
        tk.Label(icon_wrap, text="✓",
                 bg=COLORS["white"], fg=COLORS["primary_600"],
                 font=(FONT_FAMILY, 22, "bold"),
                 padx=14, pady=10).pack()
        titles = tk.Frame(left, bg=COLORS["primary_800"])
        titles.pack(side="left", padx=(16, 0), fill="both", expand=True)
        tk.Label(titles, text="REVISIONE DATI ESTRATTI",
                 bg=COLORS["primary_800"], fg=COLORS["white"],
                 font=FONTS["h2"]).pack(anchor="w")
        tk.Label(titles,
                 text="Conferma o correggi i campi prima di approvare. I dati mancanti sono evidenziati in arancio e aggiornati in tempo reale.",
                 bg=COLORS["primary_800"], fg=COLORS["slate_300"],
                 wraplength=_wp(900), justify="left",
                 font=FONTS["body_sm"]).pack(anchor="w", pady=(3, 0))

        right = tk.Frame(header_inner, bg=COLORS["primary_800"])
        right.pack(side="right")
        self._missing_count_lbl = tk.Label(right, text="",
                                           bg=COLORS["warning_500"],
                                           fg=COLORS["white"],
                                           font=(FONT_FAMILY, 11, "bold"),
                                           padx=14, pady=7, bd=0)
        self._missing_count_lbl.pack(anchor="e")
        self._missing_sub_lbl = tk.Label(right,
                                         text="",
                                         bg=COLORS["primary_800"],
                                         fg=COLORS["slate_300"],
                                         font=FONTS["body_sm"])
        self._missing_sub_lbl.pack(anchor="e", pady=(4, 0))

        wrap = tk.Frame(self, bg=COLORS["white"])
        wrap.pack(fill="both", expand=True, padx=26, pady=(8, 22))

        # ---- FR14 quality banner (green/yellow/red) ---------------------
        qband = quality_band(self._quality_score)
        _banner = {
            "green":  (COLORS["success_500"], COLORS["success_50"],
                       COLORS["success_900"]),
            "yellow": (COLORS["warning_500"], COLORS["warning_50"],
                       COLORS["warning_900"]),
            "red":    (COLORS["danger_500"],  COLORS["danger_50"],
                       COLORS["danger_900"]),
        }
        _icon = {"green": "✅", "yellow": "🟡", "red": "🔴"}[qband]
        accent, bg, fg = _banner.get(qband, _banner["red"])
        quality_card = tk.Frame(wrap, bg=bg, highlightthickness=1,
                                highlightbackground=accent)
        quality_card.pack(fill="x", pady=(0, 14))
        qleft = tk.Frame(quality_card, bg=bg)
        qleft.pack(side="left", fill="both", expand=True, padx=14, pady=10)
        tk.Label(qleft,
                 text=f"{_icon}  Qualità AI: {self._quality_score}/100  ·  {quality_text(qband, self._quality_score)}",
                 bg=bg, fg=fg, font=(FONT_FAMILY, 10, "bold"),
                 anchor="w").pack(anchor="w")
        sub = ("I campi verdi NON_SPECIFICATO sono a rischio. "
               "Verifica manualmente i valori incerti prima di approvare.")
        tk.Label(qleft, text=sub, bg=bg, fg=fg,
                 font=FONTS["body_sm"], wraplength=self._wp(900),
                 justify="left", anchor="w").pack(anchor="w", pady=(2, 0))
        tk.Label(quality_card, text=f" {self._quality_score} ",
                 bg=accent, fg=COLORS["white"],
                 font=(FONT_FAMILY, 14, "bold"),
                 padx=10, pady=4).pack(side="right", padx=12)

        sf = make_scrollable_frame(wrap, bg=COLORS["white"],
                                   show_scrollbars="always",
                                   min_inner_width=_wp(800))
        sf.outer.pack(fill="both", expand=True)
        inner = sf.inner

        props = self.schema.get("properties", {}) or {}
        required = set(self.schema.get("required", []) or [])
        self._required = required

        for key in list(props.keys()):
            spec = props[key]
            typ = spec.get("type", "")
            value = self._data.get(key)
            label = _labelize(key)
            if key in required:
                label += " *"

            accent = (COLORS["warning_500"] if _looks_missing(value)
                      else COLORS["primary_200"])
            card_bg = (COLORS["warning_50"] if _looks_missing(value)
                       else COLORS["white"])
            card = RoundedCard(inner, accent=accent, bg=card_bg)
            card.pack(fill="x", pady=(0, 10))
            self._field_cards[key] = card

            body_inner = tk.Frame(card.content, bg=card_bg)
            body_inner.pack(fill="both", expand=True, padx=16, pady=14)
            self._field_inner_frames[key] = body_inner

            body_inner.columnconfigure(1, weight=1)

            lbl_frame = tk.Frame(body_inner, bg=card_bg)
            lbl_frame.grid(row=0, column=0, sticky="nw", padx=(0, 20), pady=(2, 6))
            title_label = tk.Label(lbl_frame, text=label,
                                   bg=card_bg, fg=COLORS["slate_800"],
                                   font=FONTS["body_bold"])
            title_label.pack(anchor="w")
            desc = spec.get("description")
            if desc:
                tk.Label(lbl_frame, text=desc,
                         bg=card_bg, fg=COLORS["slate_500"],
                         wraplength=_wp(380), justify="left",
                         font=FONTS["body_sm"]).pack(anchor="w", pady=(3, 0))
            # FR7: Tooltip su ogni label, trigger description
            try:
                tooltip_txt = desc or f"Campo {key} — tipo {typ or 'string'}"
                bind_tooltip(title_label, tooltip_txt, delay=450)
                bind_tooltip(lbl_frame, tooltip_txt, delay=450)
            except Exception:  # noqa: BLE001
                pass
            miss_lbl = tk.Label(lbl_frame, text="",
                                bg=card_bg, fg=COLORS["warning_700"],
                                font=(FONT_FAMILY, 8, "bold"))
            miss_lbl.pack(anchor="w", pady=(6, 0))
            self._field_missing_labels[key] = miss_lbl

            wframe = tk.Frame(body_inner, bg=card_bg)
            wframe.grid(row=0, column=1, sticky="nsew", pady=(2, 6))
            self._build_widget(wframe, key, typ, spec, value, card_bg)

        btns = tk.Frame(wrap, bg=COLORS["white"])
        btns.pack(fill="x", pady=(14, 0))

        # FR17: Note revisore LabelFrame 5 rows
        notes_wrap = tk.LabelFrame(wrap, text=" Note revisore ",
                                   bg=COLORS["white"], fg=COLORS["slate_700"],
                                   bd=1, relief="groove",
                                   padx=10, pady=8,
                                   font=(FONT_FAMILY, 9, "bold"))
        notes_wrap.pack(fill="x", pady=(0, 12), before=btns)
        self._review_notes_text = tk.Text(notes_wrap, height=5,
                                          **_text_style(
                                              background=COLORS["white"],
                                              highlightthickness=1,
                                              bd=0))
        self._review_notes_text.pack(fill="both", expand=True)
        try:
            self._review_notes_text.insert("1.0", self._review_notes_initial)
        except Exception:  # noqa: BLE001
            pass
        try:
            bind_tooltip(notes_wrap,
                         "Note libere: vengono salvate nella colonna review_notes "
                         "del rapporto e stampate in calce al PDF. "
                         "DOCX/XLSX da template non vengono alterati.",
                         delay=500)
        except Exception:  # noqa: BLE001
            pass

        ttk.Button(btns, text="Annulla",
                   style="Subtle.TButton",
                   command=self._cancel).pack(side="right", padx=(8, 0))
        ttk.Button(btns, text="Salva modifiche (continua)",
                   style="Success.TButton",
                   command=self._collect_soft).pack(side="right", padx=(0, 8))
        ttk.Button(btns, text="✓ Approva e genera report",
                   style="Accent.TButton",
                   command=self._approve).pack(side="right")

    # ------------------------------------------------------------------
    def _build_widget(self, parent: ttk.Frame, key: str, typ: str,
                      spec: Dict[str, Any], value: Any,
                      card_bg: str) -> None:
        missing = _looks_missing(value)

        enum = spec.get("enum")
        if enum:
            base_values = [str(e) for e in enum]
            # FR6: fetch enum_history DB last-5 entries → uniqued on top
            try:
                extra: List[str] = []
                if (self._db is not None
                        and self._module_slug
                        and hasattr(self._db, "get_setting")):
                    try:
                        k = f"enum_history.{self._module_slug}.{key}"
                        raw = self._db.get_setting(k) or "[]"
                        parsed = json.loads(raw) if raw and raw.startswith("[") else []
                        if isinstance(parsed, list):
                            extra = [str(x) for x in parsed[:5] if x is not None]
                    except Exception:  # noqa: BLE001
                        extra = []
                merged: List[str] = []
                seen = set()
                for vv in list(extra) + list(base_values):
                    if vv in seen:
                        continue
                    seen.add(vv)
                    merged.append(vv)
                if not merged:
                    merged = base_values
            except Exception:  # noqa: BLE001
                merged = base_values
            current = "" if value is None else str(value)
            if current not in merged and len(merged):
                current = merged[0]
            var = tk.StringVar(value=current)
            wrap = tk.Frame(parent, bg=COLORS["white"],
                            highlightthickness=1,
                            highlightbackground=(COLORS["warning_400"]
                                                 if missing else COLORS["slate_200"]))
            wrap.pack(fill="x")
            cb = ttk.Combobox(wrap, values=merged,
                              textvariable=var, state="readonly")
            cb.pack(fill="x", padx=2, pady=2)
            cb.bind("<<ComboboxSelected>>",
                    lambda e: self.after(80, self._refresh_live), add="+")
            # Save last selected value to DB for future history
            def _save_enum_history(*_a, _k=key, _v=var, _merged=merged) -> None:
                if self._db is None or not self._module_slug:
                    return
                try:
                    cur = _v.get()
                    if not cur:
                        return
                    kk = f"enum_history.{self._module_slug}.{_k}"
                    try:
                        prev_raw = self._db.get_setting(kk) or "[]"
                        prev = json.loads(prev_raw) if prev_raw.startswith("[") else []
                    except Exception:  # noqa: BLE001
                        prev = []
                    new_list: List[str] = [cur]
                    for x in prev:
                        xs = str(x)
                        if xs != cur and xs not in new_list:
                            new_list.append(xs)
                        if len(new_list) >= 8:
                            break
                    self._db.set_setting(kk, json.dumps(new_list[:8], ensure_ascii=False))
                except Exception:  # noqa: BLE001
                    pass
            cb.bind("<<ComboboxSelected>>", _save_enum_history, add="+")
            self._widgets[key] = ("enum", var, wrap)
            if missing:
                tk.Label(parent,
                         text="⚠ NON_SPECIFICATO — seleziona un valore dall'elenco",
                         bg=card_bg, fg=COLORS["warning_700"],
                         font=(FONT_FAMILY, 8, "bold")).pack(anchor="w", pady=(6, 0))
            return

        if typ == "array":
            text_value = self._array_to_text(value)
            self._add_text_widget(parent, key, text_value,
                                  multiline=True, missing=missing,
                                  card_bg=card_bg)
            tk.Label(parent,
                     text="Array: un elemento per riga. Per oggetti usa 'key1=val ; key2=val2' su ogni riga.",
                     bg=card_bg, fg=COLORS["slate_500"],
                     wraplength=self._wp(560), justify="left",
                     font=FONTS["body_sm"]).pack(anchor="w", pady=(6, 0))
            return

        if typ == "object":
            text_value = json.dumps(value or {}, ensure_ascii=False, indent=2)
            self._add_text_widget(parent, key, text_value,
                                  multiline=True, missing=missing,
                                  card_bg=card_bg)
            tk.Label(parent,
                     text="Oggetto JSON — mantieni la sintassi valida (virgolette, parentesi graffe, virgole).",
                     bg=card_bg, fg=COLORS["slate_500"],
                     wraplength=self._wp(560), justify="left",
                     font=FONTS["body_sm"]).pack(anchor="w", pady=(6, 0))
            return

        text_value = "" if value is None else str(value)
        long_keys = ("note", "descrizione_segnalata", "guasto_segnalato",
                     "diagnosi", "causa_probabile", "descrizione",
                     "attivita_eseguite", "intervento", "note_finali",
                     "osservazioni")
        if len(text_value) > 120 or key in long_keys:
            self._add_text_widget(parent, key, text_value,
                                  multiline=True, missing=missing,
                                  card_bg=card_bg)
        else:
            var = tk.StringVar(value=text_value)
            entry_wrap = tk.Frame(parent, bg=COLORS["white"],
                                  highlightthickness=1,
                                  highlightbackground=(COLORS["warning_400"]
                                                       if missing else COLORS["slate_200"]))
            entry_wrap.pack(fill="x")
            e = tk.Entry(entry_wrap, textvariable=var,
                         **_entry_style(background=COLORS["white"],
                                        readonlybackground=COLORS["white"],
                                        highlightthickness=0, bd=0))
            e.pack(fill="x", padx=3, pady=3)
            var.trace_add("write",
                          lambda *a: self.after(120, self._refresh_live))
            self._widgets[key] = ("string", var, entry_wrap)
            if missing:
                tk.Label(parent,
                         text="⚠ NON_SPECIFICATO o vuoto — inserisci un valore o lascia invariato.",
                         bg=card_bg, fg=COLORS["warning_700"],
                         wraplength=self._wp(500), justify="left",
                         font=(FONT_FAMILY, 8, "bold")).pack(anchor="w", pady=(4, 0))

    def _add_text_widget(self, parent, key, initial, *, multiline, missing,
                         card_bg=COLORS["white"]):
        entry_wrap = tk.Frame(parent, bg=COLORS["white"],
                              highlightthickness=1,
                              highlightbackground=(COLORS["warning_400"]
                                                   if missing else COLORS["slate_200"]))
        entry_wrap.pack(fill="x")
        txt = tk.Text(entry_wrap, height=4 if multiline else 1,
                      **_text_style(background=COLORS["white"],
                                    highlightthickness=0, bd=0))
        txt.pack(fill="both", expand=True, padx=3, pady=3)
        txt.insert("1.0", initial or "")
        txt.bind("<KeyRelease>",
                 lambda e: self.after(150, self._refresh_live), add="+")
        self._widgets[key] = ("text", txt, entry_wrap)
        if missing:
            tk.Label(parent,
                     text="⚠ NON_SPECIFICATO o vuoto — compila se l'informazione è disponibile.",
                     bg=card_bg, fg=COLORS["warning_700"],
                     wraplength=self._wp(500), justify="left",
                     font=(FONT_FAMILY, 8, "bold")).pack(anchor="w", pady=(4, 0))

    # ------------------------------------------------------------------
    def _array_to_text(self, value: Any) -> str:
        if not isinstance(value, list) or not value:
            return ""
        lines = []
        for item in value:
            if isinstance(item, dict):
                lines.append(" ; ".join(f"{k}={v}" for k, v in item.items()))
            else:
                lines.append(str(item))
        return "\n".join(lines)

    def _text_to_array(self, text: str, spec: Dict[str, Any]) -> list:
        items_spec = spec.get("items", {}) if isinstance(spec, dict) else {}
        items_type = items_spec.get("type") if isinstance(items_spec, dict) else None
        items_props = items_spec.get("properties", {}) if isinstance(items_spec, dict) else {}
        result = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line:
                continue
            if items_type == "object" and items_props:
                obj: Dict[str, Any] = {}
                for chunk in [c.strip() for c in line.split(";") if c.strip()]:
                    if "=" in chunk:
                        k, v = chunk.split("=", 1)
                        obj[k.strip()] = v.strip()
                result.append(obj)
            else:
                result.append(line)
        return result

    # ---------- Live validation ----------
    def _peek_value(self, key: str, spec: Dict[str, Any]) -> Any:
        if key not in self._widgets:
            return self._data.get(key)
        kind, widget, _ = self._widgets[key]
        if kind == "enum":
            return widget.get()
        if kind == "string":
            return widget.get()
        if kind == "text":
            raw = widget.get("1.0", "end").rstrip("\n")
            typ = spec.get("type", "")
            if typ == "array":
                return self._text_to_array(raw, spec)
            if typ == "object":
                try:
                    parsed = json.loads(raw) if raw.strip() else {}
                except Exception:
                    return raw
                return parsed
            return raw
        return None

    def _refresh_live(self) -> None:
        props = self.schema.get("properties", {}) or {}
        missing_list: List[str] = []
        for key, spec in props.items():
            val = self._peek_value(key, spec)
            miss = _looks_missing(val)
            card = self._field_cards.get(key)
            miss_lbl = self._field_missing_labels.get(key)
            inner_frame = self._field_inner_frames.get(key)
            _, _, wrap = self._widgets.get(key, (None, None, None))

            if card:
                accent = COLORS["warning_500"] if miss else COLORS["primary_200"]
                card_bg = COLORS["warning_50"] if miss else COLORS["white"]
                try:
                    card.set_accent(accent)
                    card.set_background(card_bg)
                except Exception:
                    pass
                if inner_frame:
                    try:
                        inner_frame.configure(bg=card_bg)
                        for child in inner_frame.winfo_children():
                            try:
                                child.configure(bg=card_bg)
                            except Exception:
                                pass
                    except Exception:
                        pass
            if miss_lbl:
                miss_lbl.configure(text=("⚠ Mancante / NON_SPECIFICATO"
                                         if miss else ""))

            if wrap is not None:
                try:
                    wrap.configure(highlightbackground=(
                        COLORS["warning_400"] if miss else COLORS["slate_200"]))
                except Exception:
                    pass
            if miss:
                missing_list.append(key)

        n = len(missing_list)
        if n == 0:
            self._missing_count_lbl.configure(
                text="✓ Tutti i campi compilati",
                bg=COLORS["success_500"], fg=COLORS["white"])
            self._missing_sub_lbl.configure(
                text="Nessun campo vuoto o NON_SPECIFICATO. Pronto per l'approvazione.",
                fg=COLORS["slate_200"])
        else:
            self._missing_count_lbl.configure(
                text=f"⚠ {n} campi da controllare",
                bg=COLORS["warning_500"], fg=COLORS["white"])
            shown = ", ".join(missing_list[:8])
            shown += " …" if len(missing_list) > 8 else ""
            self._missing_sub_lbl.configure(
                text=f"Campi: {shown}",
                fg=COLORS["slate_300"])

    # ------------------------------------------------------------------
    def _collect_soft(self) -> Dict[str, Any]:
        try:
            data = self._collect()
        except Exception:
            return {}
        messagebox.showinfo("Modifiche salvate",
                            "Le modifiche sono state memorizzate. Puoi continuare a modificare o approvare.")
        return data

    def _collect(self) -> Dict[str, Any]:
        props = self.schema.get("properties", {}) or {}
        for key, spec in props.items():
            if key not in self._widgets:
                continue
            kind, widget, _ = self._widgets[key]
            if kind == "enum":
                val = widget.get()
                enum = spec.get("enum") or []
                if enum and isinstance(enum[0], (int, float)):
                    try:
                        val = type(enum[0])(val)
                    except Exception:
                        pass
                self._data[key] = val
            elif kind == "string":
                self._data[key] = widget.get()
            elif kind == "text":
                raw = widget.get("1.0", "end").rstrip("\n")
                typ = spec.get("type", "")
                if typ == "array":
                    self._data[key] = self._text_to_array(raw, spec)
                elif typ == "object":
                    try:
                        parsed = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError as exc:
                        messagebox.showerror("JSON non valido",
                                             f"Campo {key}: {exc}")
                        raise
                    if not isinstance(parsed, dict):
                        parsed = {}
                    self._data[key] = parsed
                else:
                    self._data[key] = raw
        return self._data

    def _approve(self) -> None:
        try:
            data = self._collect()
        except Exception:
            return
        try:
            import jsonschema
            jsonschema.validate(data, self.schema)
        except jsonschema.ValidationError as exc:
            messagebox.showwarning(
                "Validazione fallita",
                f"Il campo {list(exc.absolute_path) or 'root'}: {exc.message}",
            )
            return
        try:
            notes = self._review_notes_text.get("1.0", "end").rstrip("\n")
        except Exception:  # noqa: BLE001
            notes = ""
        data["__review_notes__"] = notes
        self.result = data
        self.destroy()

    def _cancel(self) -> None:
        self.result = None
        self.destroy()


def run_review(master, schema, draft_data, *,
               module_slug: Optional[str] = None,
               db: Any = None,
               initial_review_notes: str = "",
               title: str = "Revisione bozza") -> Optional[Dict[str, Any]]:
    dlg = ReviewDialog(master, schema, draft_data, title=title,
                       module_slug=module_slug, db=db,
                       initial_review_notes=initial_review_notes)
    master.wait_window(dlg)
    return dlg.result
