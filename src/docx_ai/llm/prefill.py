"""Campi compilati dal programma, senza AI, prima della compilazione AI.

Sul PC lento ogni gruppo di campi chiesto al modello costa decine di secondi. Qui si
ricavano i valori che non richiedono di "capire" il testo, e quei campi non vengono
chiesti all'AI (meno gruppi, prompt piu' corti; se il programma li trova tutti l'AI non
viene interpellata):

- campi automatici del modulo (``x-auto`` nello schema, impostati nell'editor):
  data di oggi, valore fisso, ultimo valore approvato;
- "Etichetta: valore" scritti dall'utente, quando l'etichetta indica un solo campo
  ("Reparto: Cottura", "Tipo: straordinaria", "N. ordine: ORD-12");
- email, telefoni, codice fiscale e partita IVA (quando il testo ne contiene uno solo).

Ogni regola si applica solo quando il risultato e' univoco: nel dubbio il campo resta
all'AI. I valori trovati qui non passano dai controlli sulle risposte dell'AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from . import field_semantics as fs

NON_SPEC = "NON_SPECIFICATO"

# modi dei campi automatici (chiave "x-auto" della definizione del campo)
AUTO_TODAY = "today"   # data di oggi
AUTO_FIXED = "fixed"   # sempre il valore in "default"
AUTO_LAST = "last"     # ultimo valore approvato per questo modulo
AUTO_MODES = (AUTO_TODAY, AUTO_FIXED, AUTO_LAST)


@dataclass
class Known:
    """Valore ricavato senza AI e da dove viene (mostrato in revisione come prova)."""
    value: Any
    source: str
    words: str = ""  # parole del testo che danno il valore ("ieri", "Cottura")


# ---------------------------------------------------------------------------
# Campi automatici
# ---------------------------------------------------------------------------
def auto_mode(spec: Any) -> str:
    mode = spec.get("x-auto") if isinstance(spec, dict) else None
    return mode if mode in AUTO_MODES else ""


def coerce(value: Any, key: str, spec: Any) -> Any:
    """Valore scritto dall'utente (testo) convertito al tipo del campo; None se non va bene."""
    spec = spec if isinstance(spec, dict) else {}
    kind = fs.kind(key, spec)
    if value is None:
        return None
    if kind == "bool":
        if isinstance(value, bool):
            return value
        return _bool_word(str(value))
    if kind == "number":
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            num: Optional[float] = float(value)
        else:
            num = _single_number(str(value))
        if num is None:
            return None
        if fs.base_type(spec) == "integer":
            return int(num) if num == int(num) else None
        return int(num) if num == int(num) else num  # "5" -> 5, non 5.0 nel documento
    if kind == "choice":
        return _choice(str(value), spec.get("enum") or [])
    if kind in ("list", "object"):
        want = list if kind == "list" else dict
        return value if isinstance(value, want) else None
    if kind == "date":
        return _one_date(str(value))
    text = str(value).strip()
    return text if text and text.upper() != NON_SPEC else None


def auto_values(schema: Dict[str, Any], last: Optional[Dict[str, Any]] = None,
                today: Optional[date] = None) -> Dict[str, Known]:
    """Valori dei campi automatici. ``last``: dati dell'ultimo documento approvato del
    modulo (per i campi "ultimo valore usato"); senza, quei campi restano all'AI."""
    today = today or date.today()
    out: Dict[str, Known] = {}
    for key, spec in ((schema or {}).get("properties") or {}).items():
        mode = auto_mode(spec)
        if mode == AUTO_TODAY:
            out[key] = Known(today.isoformat(), "data di oggi")
        elif mode == AUTO_FIXED:
            value = coerce(spec.get("default"), key, spec)
            if value is not None:
                out[key] = Known(value, "valore fisso del modulo")
        elif mode == AUTO_LAST and isinstance(last, dict):
            prev = last.get(key)
            if not _blank(prev):
                value = prev if fs.kind(key, spec) in ("list", "object") else coerce(prev, key, spec)
                if value is not None:
                    out[key] = Known(value, "ultimo valore usato")
    return out


# ---------------------------------------------------------------------------
# Dal testo dell'utente
# ---------------------------------------------------------------------------
_ABBR = {"n": "numero", "nr": "numero", "num": "numero", "no": "numero", "matr": "matricola",
         "rif": "riferimento", "tel": "telefono", "cell": "cellulare", "cod": "codice", "rep": "reparto",
         "resp": "responsabile", "qta": "quantita", "q": "quantita", "prot": "protocollo",
         "tecn": "tecnico", "forn": "fornitore", "rapp": "rapporto", "ord": "ordine", "uff": "ufficio"}
_LABEL_STOP = {"il", "lo", "la", "i", "gli", "le", "di", "del", "della", "dello", "dei", "degli", "delle",
               "da", "dal", "dalla", "e", "ed", "a", "al", "alla", "in", "per", "the", "of"}
# abbreviazioni con il punto che non chiudono una frase ("verifica: Ing. Rossi")
_TITLES = {"ing", "dott", "dottssa", "sig", "sigra", "geom", "arch", "avv", "prof", "rag", "per", "p",
           "n", "nr", "cod", "rif", "tel", "matr", "art", "ecc", "es", "s", "spa", "srl", "snc", "sas"}
_EMPTY = {"", "-", "--", "?", "nd", "n.d.", "n/a", "na", "/", "...", "x"}
_TRUE = {"si", "sì", "yes", "vero", "true", "ok", "fatto", "fatta", "eseguito", "eseguita", "presente"}
_FALSE = {"no", "non", "falso", "false", "nessuno", "nessuna", "niente", "assente", "ko"}
_NEG = {"non", "no", "nessun", "nessuno", "nessuna", "senza", "mai", "not"}

_COLON = re.compile(r":(?!\d)")  # non gli orari "14:30"
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_PHONE = re.compile(r"(?<![\w/.-])(?:\+\d{2}[\s.]?)?(?:3\d{2}|0\d{1,3})[\s./-]?\d{3,4}[\s./-]?\d{3,4}(?![\w/-])")
_CF = re.compile(r"\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b", re.I)
_PIVA = re.compile(r"(?<![\d/.-])\d{11}(?![\d/.-])")
_NUMBER = re.compile(r"-?\d{1,3}(?:\.\d{3})+(?:,\d+)?|-?\d+(?:[.,]\d+)?")


def _blank(v: Any) -> bool:
    return v is None or v == [] or v == {} or (isinstance(v, str) and (not v.strip() or v.strip().upper() == NON_SPEC))


def _words(text: str) -> List[str]:
    return [_ABBR.get(w, w) for w in re.findall(r"[a-z0-9]+", fs.norm(text))]


def _bool_word(text: str) -> Optional[bool]:
    w = fs.norm(text).strip(" .!")
    if w in _TRUE:
        return True
    if w in _FALSE:
        return False
    return None


def _single_number(text: str) -> Optional[float]:
    """Il valore e' un solo numero, al massimo con un'unita' ("680 euro", "3,5 ore")."""
    nums = _NUMBER.findall(text)
    rest = _NUMBER.sub(" ", text)
    if len(nums) != 1 or len(re.findall(r"[^\W\d_]+", rest)) > 2:
        return None
    tok = nums[0]
    if "," in tok:
        tok = tok.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", tok):
        tok = tok.replace(".", "")  # 1.200 = milleduecento
    try:
        return float(tok)
    except ValueError:
        return None


def _choice(text: str, options: Iterable[Any]) -> Optional[str]:
    opts = [str(o) for o in options if "specificato" not in str(o).lower()]
    val = set(_words(text))
    if not val:
        return None
    exact = [o for o in opts if set(_words(o.replace("_", " "))) == val]
    if len(exact) == 1:
        return exact[0]
    if exact:
        return None
    if val & _NEG:
        return None
    sub = [o for o in opts if val <= set(_words(o.replace("_", " ")))
           and not set(_words(o.replace("_", " "))) & _NEG]
    return sub[0] if len(sub) == 1 else None


def _one_date(text: str, today: Optional[date] = None) -> Optional[str]:
    from .fact_guard import date_mentions_ctx, parse_date_value
    d = parse_date_value(text.strip())
    if d is not None:
        return d.isoformat()
    found = {m.date for m in date_mentions_ctx(text, today)}
    return next(iter(found)).isoformat() if len(found) == 1 else None


def _sentence_ends(text: str) -> List[int]:
    """Posizioni in cui finisce un pezzo di testo: a capo, ";", fine frase (non dopo
    "Ing." o "n.")."""
    ends = []
    for m in re.finditer(r"\n|;|[.!?](?=\s+\S)", text):
        if m.group(0) == ".":
            prev = re.search(r"([^\W\d_]+)\s*$", text[:m.start()])
            if prev and (fs.norm(prev.group(1)).replace(".", "") in _TITLES or len(prev.group(1)) == 1):
                continue
            if re.match(r"\d", text[m.end():m.end() + 1] or ""):  # 1.200, 5.10
                continue
        ends.append(m.start())
    return ends


def _segments(text: str) -> List[Tuple[int, str]]:
    out = []
    start = 0
    for end in _sentence_ends(text) + [len(text)]:
        piece = text[start:end]
        if piece.strip():
            out.append((start, piece))
        start = end + 1
    return out


class _Fields:
    """Parole di ogni campo, per capire a quale campo si riferisce un'etichetta."""

    def __init__(self, props: Dict[str, Any]):
        self.props = props
        self.words: Dict[str, Set[str]] = {}
        for key, spec in props.items():
            title = str(spec.get("title") or "") if isinstance(spec, dict) else ""
            raw = _words(key.replace("_", " ")) + _words(title)
            # campi "Dal"/"Al": fatti solo di parole brevi, che altrove si ignorano
            self.words[key] = {w for w in raw if w not in _LABEL_STOP} or set(raw)

    def match(self, label: List[str]) -> Optional[str]:
        lab = [w for w in label if w not in _LABEL_STOP] or list(label)
        if not lab or len(lab) > 4:
            return None
        lab_set = set(lab)
        exact = [k for k, ws in self.words.items() if ws == lab_set]
        if len(exact) == 1:
            return exact[0]
        if exact:
            return None

        def covers(ws: Set[str]) -> bool:
            return all(any(f == w or (len(w) >= 4 and f.startswith(w)) for f in ws) for w in lab_set)

        cand = [k for k, ws in self.words.items() if covers(ws)]
        return cand[0] if len(cand) == 1 else None


def _label_values(text: str, fields: _Fields) -> List[Tuple[str, str, str]]:
    """Coppie (campo, valore, frase) scritte come "Etichetta: valore"."""
    out: List[Tuple[str, str, str]] = []
    for _seg_start, seg in _segments(text):
        colons = [m.start() for m in _COLON.finditer(seg)]
        if not colons:
            continue
        # per ogni ":" l'etichetta: le ultime parole prima, fino alla punteggiatura
        labels: List[Tuple[int, int, Optional[str]]] = []  # (inizio etichetta, ":", campo)
        for c in colons:
            before = seg[:c]
            cut = max(before.rfind(ch) for ch in ",()[]-–")
            chunk = before[cut + 1:]
            toks = list(re.finditer(r"[^\W_][\w°'.]*", chunk))
            if not toks:
                labels.append((c, c, None))
                continue
            key = None
            begin = cut + 1 + toks[-1].start()
            for n in range(min(4, len(toks)), 0, -1):  # prima l'etichetta piu' lunga
                part = toks[-n:]
                found = fields.match(_words(" ".join(t.group(0) for t in part)))
                if found:
                    key, begin = found, cut + 1 + part[0].start()
                    break
            labels.append((begin, c, key))
        for i, (_b, c, key) in enumerate(labels):
            if key is None:
                continue
            end = labels[i + 1][0] if i + 1 < len(labels) else len(seg)
            value = seg[c + 1:end].strip().strip(",-–").strip()
            value = re.sub(r"[\s,.]+$", "", value) if not re.search(r"\b\w\.$", value) else value.strip()
            out.append((key, value, seg[labels[i][0]:end].strip()))
    return out


def _convert(key: str, spec: Dict[str, Any], value: str, today: Optional[date]) -> Any:
    if fs.norm(value) in _EMPTY:
        return None
    kind = fs.kind(key, spec)
    if kind in ("list", "object") or "const" in spec:
        return None
    if kind == "date":
        return _one_date(value, today)
    if kind == "time":
        m = re.fullmatch(r"(?:ore\s+)?([01]?\d|2[0-3])[:.]([0-5]\d)", value.strip(), re.I)
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None
    if kind in ("bool", "number", "choice"):
        return coerce(value, key, spec)
    limit = 200 if kind == "text" else 80
    if not value or len(value) > limit:
        return None
    return value


def _contact(key: str, spec: Dict[str, Any], text: str) -> Optional[Tuple[str, str]]:
    ws = set(fs.words(key) + fs.words(str(spec.get("title") or "")))
    if fs.base_type(spec) != "string" or spec.get("enum"):
        return None
    if ws & {"email", "mail", "pec"}:
        found = {m.group(0).rstrip(".").lower(): m.group(0).rstrip(".") for m in _EMAIL.finditer(text)}
    elif ws & {"telefono", "tel", "cellulare", "cell", "phone", "recapito"}:
        found = {re.sub(r"\D", "", m.group(0)): m.group(0) for m in _PHONE.finditer(text)
                 if not re.search(r"iva|fiscale|c\.?f\.?\s*$", text[max(0, m.start() - 14):m.start()], re.I)}
    elif {"codice", "fiscale"} <= ws or "cf" in ws:
        found = {m.group(0).upper(): m.group(0).upper() for m in _CF.finditer(text)}
    elif ws & {"iva", "piva"}:
        found = {m.group(0): m.group(0) for m in _PIVA.finditer(text)}
    else:
        return None
    if len(found) != 1:  # nessuno o piu' d'uno: decide l'AI
        return None
    value = next(iter(found.values()))
    return value, value


def from_text(schema: Dict[str, Any], text: str, today: Optional[date] = None) -> Dict[str, Known]:
    """Valori dei campi che il testo indica senza ambiguita' (vedi la descrizione del modulo)."""
    props = {k: v for k, v in ((schema or {}).get("properties") or {}).items() if isinstance(v, dict)}
    text = text or ""
    if not props or not text.strip():
        return {}
    out: Dict[str, Known] = {}
    seen: Dict[str, int] = {}
    for key, value, quote in _label_values(text, _Fields(props)):
        seen[key] = seen.get(key, 0) + 1
        conv = _convert(key, props[key], value, today)
        if conv is not None:
            out[key] = Known(conv, quote, value)
    for key, n in seen.items():  # stesso campo indicato due volte: decide l'AI
        if n > 1:
            out.pop(key, None)

    for key, spec in props.items():
        if key in out or "const" in spec:
            continue
        hit = _contact(key, spec, text)
        if hit:
            out[key] = Known(hit[0], hit[1])
    # Le date scritte nel discorso ("lunedì scorso", "ieri") restano all'AI: provato a
    # compilarle qui, il modello 0.6B senza il campo data da scrivere metteva la data
    # nell'oggetto o in "Rilevata da". I campi data rimasti vuoti li riempie comunque
    # il controllo dei fatti (fact_guard) con la stessa regola.
    return out
