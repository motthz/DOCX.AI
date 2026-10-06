"""Controllo deterministico dei fatti proposti dall'AI ("a prova di errore").

Un modello piccolo puo' inventare o convertire male date, numeri, codici e nomi.
Dopo ogni compilazione questi valori vengono confrontati con il testo dell'utente
(e i documenti di riferimento), senza usare l'AI:

- date: devono comparire nel testo in qualsiasi formato (05/10/2026, 5 ottobre,
  2026-10-05) o derivare da espressioni relative ("oggi", "ieri", "lunedì scorso",
  "tra 3 giorni") calcolate sulla data di oggi. Giorno e mese scambiati o l'anno
  sbagliato vengono corretti; una data che non ha riscontro viene tolta;
- numeri dei campi numerici: devono comparire nel testo (anche 1.250,50 / 1250.5);
- codici e numeri dentro i campi brevi (matricole, ordini, targhe...): idem;
- nomi di persone/aziende nei campi relativi: almeno una parola deve comparire.

Un valore senza riscontro diventa "non specificato": il campo resta da compilare
in revisione invece di finire nel documento con un dato inventato.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

NON_SPEC = "NON_SPECIFICATO"

MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_ABBR = {
    "gen": 1, "feb": 2, "mar": 3, "apr": 4, "mag": 5, "giu": 6, "lug": 7, "ago": 8, "set": 9,
    "sett": 9, "ott": 10, "nov": 11, "dic": 12, "jan": 1, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "dec": 12,
}
_ALL_MONTHS = {**MONTHS, **_MONTH_ABBR}
WEEKDAYS = {
    "lunedi": 0, "martedi": 1, "mercoledi": 2, "giovedi": 3, "venerdi": 4, "sabato": 5, "domenica": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
}
NUMBER_WORDS = {
    "zero": 0, "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
    "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13,
    "quattordici": 14, "quindici": 15, "sedici": 16, "diciassette": 17, "diciotto": 18,
    "diciannove": 19, "venti": 20, "trenta": 30, "quaranta": 40, "cinquanta": 50, "cento": 100,
    "mille": 1000, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10,
}
_RELATIVE_DAYS = {
    "oggi": 0, "stamattina": 0, "stamani": 0, "stasera": 0, "stanotte": 0, "today": 0, "tonight": 0,
    "ieri": -1, "yesterday": -1, "altroieri": -2, "avantieri": -2, "l'altro ieri": -2,
    "altro ieri": -2, "domani": 1, "tomorrow": 1, "dopodomani": 2,
}
# campi che contengono nomi di persone o aziende
_PERSON_HINTS = ("nome", "cognome", "redattore", "tecnico", "responsabile", "cliente", "partecipant",
                 "firmatari", "richiedente", "operatore", "referente", "fornitore", "azienda", "ditta",
                 "committente", "incaricato", "esecutore", "autore", "destinatari", "presenti",
                 "name", "customer", "technician", "author", "supplier", "company")
_TITLES = {"ing", "dott", "dottssa", "sig", "sigra", "geom", "arch", "avv", "prof", "per", "ind", "spa",
           "srl", "snc", "sas", "mr", "mrs", "ms", "dr", "the", "del", "della", "dei", "di", "da", "van"}

_D = r"(\d{1,2})"
_ISO_RE = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
_EU_RE = re.compile(r"(?<![\d.,/-])" + _D + r"\s*[/.\-]\s*" + _D + r"(?:\s*[/.\-]\s*(\d{4}|\d{2}))?(?![\d/-]|[.,]\d)")
_TEXT_RE = re.compile(
    r"\b" + _D + r"(?:°|º)?\s+(" + "|".join(sorted(_ALL_MONTHS, key=len, reverse=True))
    + r")\.?(?:\s+(?:del\s+)?(\d{4}))?\b", re.I)
_TEXT_EN_RE = re.compile(
    r"\b(" + "|".join(sorted(_ALL_MONTHS, key=len, reverse=True)) + r")\.?\s+" + _D
    + r"(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b", re.I)
_NUM_RE = re.compile(r"(?<![\w.,])[-+]?\d[\d.,']*\d|(?<![\w.,])[-+]?\d")
_CODE_RE = re.compile(r"\b(?=[\w\-/.]*\d)[\w][\w\-/.]*\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower())


def _mkdate(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _year(y: Optional[str], today: date) -> int:
    if not y:
        return today.year
    yy = int(y)
    return yy + 2000 if yy < 100 else yy


# ---------------------------------------------------------------------------
# Date
# ---------------------------------------------------------------------------
def explicit_dates(text: str, today: Optional[date] = None) -> Set[date]:
    """Date scritte nel testo (giorno/mese all'italiana); senza anno: anno corrente."""
    today = today or date.today()
    out: Set[date] = set()
    for y, m, d in _ISO_RE.findall(text or ""):
        dt = _mkdate(int(y), int(m), int(d))
        if dt:
            out.add(dt)
    for d, m, y in _EU_RE.findall(text or ""):
        if not y and (int(m) > 12 or int(d) > 31):
            continue
        dt = _mkdate(_year(y, today), int(m), int(d))
        if dt:
            out.add(dt)
    for d, mon, y in _TEXT_RE.findall(text or ""):
        dt = _mkdate(_year(y, today), _ALL_MONTHS[mon.lower()], int(d))
        if dt:
            out.add(dt)
    for mon, d, y in _TEXT_EN_RE.findall(text or ""):
        if mon.lower() not in MONTHS:  # "mar 5" ecc. troppo ambiguo
            continue
        dt = _mkdate(_year(y, today), MONTHS[mon.lower()], int(d))
        if dt:
            out.add(dt)
    return out


def _count(word: str) -> Optional[int]:
    if word.isdigit():
        return int(word)
    return NUMBER_WORDS.get(word)


def relative_dates(text: str, today: Optional[date] = None) -> Set[date]:
    """Date indicate a parole: oggi, ieri, lunedì scorso, tra 3 giorni, 2 settimane fa..."""
    today = today or date.today()
    t = _norm(text)
    out: Set[date] = set()
    for word, delta in _RELATIVE_DAYS.items():
        if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", t):
            out.add(today + timedelta(days=delta))
    unit = r"(giorn[oi]|settiman[ae]|mes[ei]|days?|weeks?|months?)"
    for n, u in re.findall(r"(?:tra|fra|entro|in)\s+(\w+)\s+" + unit, t):
        c = _count(n)
        if c is not None:
            out.add(_shift(today, c, u))
    for n, u in re.findall(r"(\w+)\s+" + unit + r"\s+(?:fa|ago)\b", t):
        c = _count(n)
        if c is not None:
            out.add(_shift(today, -c, u))
    for name, wd in WEEKDAYS.items():
        for m in re.finditer(r"(?<![a-z])" + name + r"(?![a-z])", t):
            around = t[max(0, m.start() - 12): m.end() + 12]
            back = (today.weekday() - wd) % 7 or 7
            fwd = (wd - today.weekday()) % 7 or 7
            past = today - timedelta(days=back)
            future = today + timedelta(days=fwd)
            if re.search(r"scors|passat|last", around):
                out.add(past)
            elif re.search(r"prossim|next|venturo", around):
                out.add(future)
            else:  # "lunedì" da solo: il piu' vicino, prima o dopo (e oggi stesso)
                out.update({past, future})
                if wd == today.weekday():
                    out.add(today)
    return out


def _shift(today: date, n: int, unit: str) -> date:
    if unit.startswith(("giorn", "day")):
        return today + timedelta(days=n)
    if unit.startswith(("settiman", "week")):
        return today + timedelta(weeks=n)
    month = today.month - 1 + n
    y, m = today.year + month // 12, month % 12 + 1
    d = today.day
    while d > 28 and _mkdate(y, m, d) is None:
        d -= 1
    return date(y, m, d)


def date_mentions(text: str, today: Optional[date] = None, limit: int = 12) -> List[Tuple[str, date]]:
    """Date scritte nel testo con le parole usate, nell'ordine in cui compaiono:
    [("1 ottobre 2026", date(2026, 10, 1)), ("ieri", ...)]. Date al modello gia'
    convertite: un modello piccolo altrimenti scrive la data di oggi in ogni campo
    data (che il controllo dei fatti poi toglie: dato perso)."""
    today = today or date.today()
    text = text or ""
    found: List[Tuple[int, str, date]] = []
    for m in _ISO_RE.finditer(text):
        dt = _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if dt:
            found.append((m.start(), m.group(0), dt))
    for m in _EU_RE.finditer(text):
        d, mo, y = m.group(1), m.group(2), m.group(3)
        if not y:  # "3/4" senza anno: piu' spesso una frazione o una misura che una data
            continue
        dt = _mkdate(_year(y, today), int(mo), int(d))
        if dt:
            found.append((m.start(), m.group(0).strip(), dt))
    for m in _TEXT_RE.finditer(text):
        dt = _mkdate(_year(m.group(3), today), _ALL_MONTHS[m.group(2).lower()], int(m.group(1)))
        if dt:
            found.append((m.start(), m.group(0).strip(), dt))
    for m in _TEXT_EN_RE.finditer(text):
        if m.group(1).lower() in MONTHS:
            dt = _mkdate(_year(m.group(3), today), MONTHS[m.group(1).lower()], int(m.group(2)))
            if dt:
                found.append((m.start(), m.group(0).strip(), dt))
    for word, delta in _RELATIVE_DAYS.items():
        for m in re.finditer(r"(?<![^\W\d_])" + re.escape(word) + r"(?![^\W\d_])", text, re.I):
            found.append((m.start(), m.group(0), today + timedelta(days=delta)))
    out: List[Tuple[str, date]] = []
    seen: Set[Tuple[str, date]] = set()
    for _pos, words, dt in sorted(found, key=lambda f: f[0]):
        key = (words.lower(), dt)
        if key not in seen:
            seen.add(key)
            out.append((words, dt))
    return out[:limit]


def source_dates(text: str, today: Optional[date] = None) -> Set[date]:
    return explicit_dates(text, today) | relative_dates(text, today)


def parse_date_value(value: Any) -> Optional[date]:
    """Data contenuta in un valore che e' *solo* una data (AAAA-MM-GG, GG/MM/AAAA, testo)."""
    if not isinstance(value, str):
        return None
    v = value.strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[T ]\d{1,2}:\d{2}(?::\d{2})?.*)?", v)
    if m:
        return _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})", v)
    if m:
        return _mkdate(_year(m.group(3), date.today()), int(m.group(2)), int(m.group(1)))
    m = _TEXT_RE.fullmatch(v)
    if m and m.group(3):
        return _mkdate(int(m.group(3)), _ALL_MONTHS[m.group(2).lower()], int(m.group(1)))
    return None


def _format_like(original: str, new: date) -> str:
    """Scrive la data corretta nello stesso formato proposto dall'AI."""
    v = original.strip()
    m = re.fullmatch(r"(\d{4})([-/.])(\d{1,2})\2(\d{1,2})(.*)", v)
    if m:
        return f"{new.year:04d}{m.group(2)}{new.month:02d}{m.group(2)}{new.day:02d}{m.group(5)}"
    m = re.fullmatch(r"(\d{1,2})([/.\-])(\d{1,2})\2(\d{4}|\d{2})", v)
    if m:
        y = f"{new.year:04d}" if len(m.group(4)) == 4 else f"{new.year % 100:02d}"
        return f"{new.day:02d}{m.group(2)}{new.month:02d}{m.group(2)}{y}"
    return new.isoformat()


def fix_date(value: date, allowed: Set[date]) -> Tuple[Optional[date], str]:
    """(data corretta o None, motivo). La data e' gia' giusta se e' in ``allowed``."""
    if value in allowed:
        return value, "ok"
    swapped = _mkdate(value.year, value.day, value.month) if value.day <= 12 else None
    cands = [d for d in allowed if d == swapped]
    if len(cands) == 1:
        return cands[0], "giorno e mese scambiati"
    cands = [d for d in allowed if (d.month, d.day) == (value.month, value.day)]
    if len(cands) == 1:
        return cands[0], "anno errato"
    return None, "data non presente nel testo"


# ---------------------------------------------------------------------------
# Numeri e codici
# ---------------------------------------------------------------------------
def _number_readings(token: str) -> Set[float]:
    """Interpretazioni possibili di un numero scritto (1.250,50 / 1,250.50 / 1250.5 / 1'250)."""
    s = token.replace("'", "").strip("+")
    out: Set[float] = set()

    def add(x: str) -> None:
        try:
            out.add(round(float(x), 6))
        except ValueError:
            pass
    if "," in s and "." in s:
        if s.rfind(",") > s.rfind("."):
            add(s.replace(".", "").replace(",", "."))
        else:
            add(s.replace(",", ""))
    elif "," in s:
        add(s.replace(",", "."))
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", s):
            add(s.replace(",", ""))
    elif "." in s:
        add(s)
        if re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
            add(s.replace(".", ""))
    else:
        add(s)
    return out


def source_numbers(text: str) -> Set[float]:
    out: Set[float] = set()
    for tok in _NUM_RE.findall(text or ""):
        out |= _number_readings(tok)
    for w in re.findall(r"[a-z]+", _norm(text)):
        if w in NUMBER_WORDS:
            out.add(float(NUMBER_WORDS[w]))
    return out


@dataclass
class Correction:
    field: str
    old: Any
    new: Any
    reason: str

    def describe(self) -> str:
        new = "vuoto" if self.new in (None, NON_SPEC) else repr(self.new)
        return f"{self.field}: {self.old!r} → {new} ({self.reason})"


class FactGuard:
    def __init__(self, sources: Iterable[str], today: Optional[date] = None):
        self.today = today or date.today()
        self.raw = "\n".join(s for s in sources if s)
        self.norm = _norm(self.raw)
        self.compact = re.sub(r"[\s\-/.:_]", "", self.norm)
        self.dates = source_dates(self.raw, self.today)
        self.numbers = source_numbers(self.raw)
        self.corrections: List[Correction] = []

    # ---- primitive ----
    def _present(self, token: str) -> bool:
        n = _norm(token).strip()
        if not n:
            return True
        if re.search(r"(?<![a-z0-9])" + re.escape(n) + r"(?![a-z0-9])", self.norm):
            return True
        c = re.sub(r"[\s\-/.:_]", "", n)
        return len(c) >= 4 and c in self.compact

    def _number_ok(self, value: float) -> bool:
        return any(abs(value - n) < 1e-6 for n in self.numbers)

    def _codes_ok(self, text: str) -> List[str]:
        """Codici/numeri del valore che non compaiono nelle fonti."""
        missing = []
        for tok in _CODE_RE.findall(text):
            if parse_date_value(tok) or self._present(tok):
                continue
            readings = _number_readings(tok) if re.fullmatch(r"[-+]?\d[\d.,']*", tok) else set()
            if readings and any(self._number_ok(r) for r in readings):
                continue
            missing.append(tok)
        return missing

    def _person_ok(self, text: str) -> bool:
        words = [w for w in re.findall(r"[a-z]{3,}", _norm(text)) if w not in _TITLES]
        return not words or any(self._present(w) for w in words)

    # ---- valori ----
    def _check_string(self, path: str, value: str, spec: Dict[str, Any], person: bool) -> Any:
        if value.strip().upper() == NON_SPEC or not value.strip():
            return value
        as_date = parse_date_value(value)
        if as_date is not None or spec.get("format") in ("date", "date-time"):
            if as_date is None:
                return value  # data scritta a parole (es. "fine mese"): la verifica la revisione
            fixed, why = fix_date(as_date, self.dates)
            if fixed == as_date:
                return value
            new = _format_like(value, fixed) if fixed else NON_SPEC
            self.corrections.append(Correction(path, value, new, why))
            return new
        if spec.get("enum"):
            return value
        short = len(value.split()) <= 6
        if short:
            missing = self._codes_ok(value)
            if missing:
                self.corrections.append(Correction(path, value, NON_SPEC,
                                                   "non presente nel testo: " + ", ".join(missing[:3])))
                return NON_SPEC
        if person and short and not self._person_ok(value):
            self.corrections.append(Correction(path, value, NON_SPEC, "nome non presente nel testo"))
            return NON_SPEC
        return value

    def _check_number(self, path: str, value: Any) -> Any:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        if self._number_ok(float(value)):
            return value
        self.corrections.append(Correction(path, value, None, "numero non presente nel testo"))
        return None

    def _check(self, path: str, value: Any, spec: Dict[str, Any], person: bool) -> Any:
        spec = spec if isinstance(spec, dict) else {}
        t = spec.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), None)
        if isinstance(value, str):
            return self._check_string(path, value, spec, person)
        if t in ("number", "integer"):
            return self._check_number(path, value)
        if isinstance(value, list):
            raw_items = spec.get("items")
            items: Dict[str, Any] = raw_items if isinstance(raw_items, dict) else {}
            out = []
            for i, item in enumerate(value):
                checked = self._check(f"{path}[{i + 1}]", item, items, person)
                if isinstance(item, str) and checked == NON_SPEC:
                    continue  # voce inventata: tolta dall'elenco
                out.append(checked)
            return out
        if isinstance(value, dict):
            raw_props = spec.get("properties")
            props: Dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
            return {k: self._check(f"{path}.{k}", v, props.get(k, {}), _is_person(k, props.get(k)))
                    for k, v in value.items()}
        return value

    def apply(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        props = (schema or {}).get("properties", {}) or {}
        out = dict(data)
        for key, value in data.items():
            spec = props.get(key, {})
            label = (spec.get("title") if isinstance(spec, dict) else None) or key
            out[key] = self._check(label, value, spec, _is_person(key, spec))
        return out


def _is_person(key: str, spec: Any) -> bool:
    text = _norm(key + " " + (spec.get("title", "") if isinstance(spec, dict) else ""))
    return any(h in text for h in _PERSON_HINTS)


def verify(data: Dict[str, Any], schema: Dict[str, Any], sources: Iterable[str],
           today: Optional[date] = None) -> Tuple[Dict[str, Any], List[Correction]]:
    """Ritorna (dati verificati, correzioni applicate)."""
    if not isinstance(data, dict):
        return data, []
    guard = FactGuard(sources, today)
    return guard.apply(data, schema), guard.corrections
