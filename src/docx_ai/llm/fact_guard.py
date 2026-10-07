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


@dataclass
class DateMention:
    """Data scritta nel testo: parole usate, data calcolata e parole vicine (contesto)."""
    words: str
    date: date
    start: int
    context: str = ""


# preposizioni che introducono un giorno: "il 15", "entro il 30", "dal 3"
_DAY_INTRO = r"(?:\b(?:il|l'|del|dal|al|entro\s+il|fino\s+al|per\s+il|giorno|in\s+data|data)\s+)"
_DAY_ONLY_RE = re.compile(_DAY_INTRO + r"(\d{1,2})(?:°|º)?(?=\s*(?:$|[,;:)\n]|\.(?!\d)|\s+(?:alle|ore|h\b|e\b|ed\b|o\b|"
                          r"mattina|pomeriggio|sera|prossimo|p\.v\.|c\.m\.)))", re.I)
_SHORT_EU_RE = re.compile(_DAY_INTRO + r"(\d{1,2})\s*[/.]\s*(\d{1,2})(?!\d|\s*[/.,]\s*\d|\s*%|\s+per\s?cento|\s+"
                          r"(?:volte|mm|cm|m|km|kg|g|bar|v|a|w|kw|l|lt|h|min|pollic\w*)\b)", re.I)
# "dal 3 al 5 ottobre", "3 e 4 ottobre", "3-5 ottobre": il primo giorno prende il mese del secondo
_RANGE_RE = re.compile(r"\b(\d{1,2})(?:°|º)?\s*(?:-|e|ed|al|/|,)\s*(?:il\s+)?(\d{1,2})(?:°|º)?\s+("
                       + "|".join(sorted(_ALL_MONTHS, key=len, reverse=True))
                       + r")\.?(?:\s+(?:del\s+)?(\d{4}))?\b", re.I)
_PRIMO_RE = re.compile(r"\bprimo\s+(" + "|".join(sorted(MONTHS, key=len, reverse=True))
                       + r")(?:\s+(?:del\s+)?(\d{4}))?\b", re.I)
_WEEKDAY_RE = re.compile(r"\b(luned[iì]|marted[iì]|mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|"
                         r"tuesday|wednesday|thursday|friday|saturday|sunday)\b(?:\s+(scors[oa]|passat[oa]|"
                         r"prossim[oa]|venturo|next|last))?", re.I)
_WEEKDAY_BEFORE_RE = re.compile(r"\b(scors[oa]|passat[oa]|prossim[oa]|next|last)\s+(luned[iì]|marted[iì]|"
                                r"mercoled[iì]|gioved[iì]|venerd[iì]|sabato|domenica|monday|tuesday|"
                                r"wednesday|thursday|friday|saturday|sunday)\b", re.I)
_IN_RE = re.compile(r"\b(?:tra|fra|entro|in)\s+(\w+)\s+(giorn[oi]|settiman[ae]|mes[ei]|days?|weeks?|months?)\b",
                    re.I)
_AGO_RE = re.compile(r"\b(\w+)\s+(giorn[oi]|settiman[ae]|mes[ei]|days?|weeks?|months?)\s+(?:fa|ago)\b", re.I)


def _weekday_date(name: str, qualifier: str, today: date) -> Optional[date]:
    wd = WEEKDAYS.get(_norm(name).strip())
    if wd is None:
        return None
    q = _norm(qualifier or "")
    back = (today.weekday() - wd) % 7 or 7
    fwd = (wd - today.weekday()) % 7 or 7
    if q.startswith(("scors", "passat", "last")):
        return today - timedelta(days=back)
    if q.startswith(("prossim", "next", "ventur")):
        return today + timedelta(days=fwd)
    return None


def _context(text: str, start: int, end: int) -> str:
    """Parole vicine alla data nella stessa frase: "prossimo incontro il" / "riunione del"."""
    left = text[max(0, start - 60): start]
    left = re.split(r"[.;,:\n!?]\s", left + " ")[-1] if re.search(r"[.;,:\n!?]\s", left) else left
    right = text[end: end + 30]
    if len(text) > end + 30 and not text[end + 30].isspace() and " " in right:
        right = right.rsplit(" ", 1)[0]  # parola intera
    right = re.split(r"[.;,:\n!?]", right)[0]
    return re.sub(r"\s+", " ", (left + " … " + right).strip())


def date_mentions_ctx(text: str, today: Optional[date] = None, limit: int = 16) -> List[DateMention]:
    """Date scritte nel testo, nell'ordine in cui compaiono, con il contesto.

    Riconosce: 05/10/2026, 5.10.26, 2026-10-05, 5 ottobre (2026), 5 ott, 1° ottobre, primo
    ottobre, October 5, dal 3 al 5 ottobre, il 5/10, "il 15" (mese della data precedente
    o il mese corrente), oggi/ieri/domani, lunedì scorso, venerdì prossimo, tra 3 giorni,
    2 settimane fa."""
    today = today or date.today()
    text = text or ""
    found: List[Tuple[int, int, str, date]] = []
    taken: List[Tuple[int, int]] = []

    def add(start: int, end: int, words: str, dt: Optional[date]) -> None:
        if dt is None:
            return
        if any(a <= start < b or a < end <= b for a, b in taken):
            return
        taken.append((start, end))
        found.append((start, end, words.strip(), dt))

    for m in _ISO_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), _mkdate(int(m.group(1)), int(m.group(2)), int(m.group(3))))
    for m in _RANGE_RE.finditer(text):
        mon = _ALL_MONTHS[m.group(3).lower()]
        y = _year(m.group(4), today)
        add(m.start(1), m.end(1), f"{m.group(1)} {m.group(3)}", _mkdate(y, mon, int(m.group(1))))
    for m in _TEXT_RE.finditer(text):
        add(m.start(), m.end(), m.group(0),
            _mkdate(_year(m.group(3), today), _ALL_MONTHS[m.group(2).lower()], int(m.group(1))))
    for m in _PRIMO_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), _mkdate(_year(m.group(2), today), MONTHS[m.group(1).lower()], 1))
    for m in _TEXT_EN_RE.finditer(text):
        if m.group(1).lower() in MONTHS:
            add(m.start(), m.end(), m.group(0),
                _mkdate(_year(m.group(3), today), MONTHS[m.group(1).lower()], int(m.group(2))))
    for m in _EU_RE.finditer(text):
        day_s, mon_s, year_s = m.group(1), m.group(2), m.group(3)
        if not year_s:  # "3/4" senza anno: piu' spesso una frazione o una misura (vedi _SHORT_EU_RE)
            continue
        add(m.start(), m.end(), m.group(0), _mkdate(_year(year_s, today), int(mon_s), int(day_s)))
    for m in _SHORT_EU_RE.finditer(text):  # "il 5/10", "entro il 30.11": con la preposizione e' una data
        add(m.start(1), m.end(2), m.group(0), _mkdate(today.year, int(m.group(2)), int(m.group(1))))
    for word, delta in sorted(_RELATIVE_DAYS.items(), key=lambda kv: -len(kv[0])):  # "l'altro ieri" prima di "ieri"
        for m in re.finditer(r"(?<![^\W\d_])" + re.escape(word) + r"(?![^\W\d_])", text, re.I):
            add(m.start(), m.end(), m.group(0), today + timedelta(days=delta))
    for m in _WEEKDAY_BEFORE_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), _weekday_date(m.group(2), m.group(1), today))
    for m in _WEEKDAY_RE.finditer(text):
        add(m.start(), m.end(), m.group(0), _weekday_date(m.group(1), m.group(2) or "", today))
    for m in _IN_RE.finditer(text):
        c = _count(_norm(m.group(1)))
        if c is not None:
            add(m.start(), m.end(), m.group(0), _shift(today, c, _norm(m.group(2))))
    for m in _AGO_RE.finditer(text):
        c = _count(_norm(m.group(1)))
        if c is not None:
            add(m.start(), m.end(), m.group(0), _shift(today, -c, _norm(m.group(2))))
    # "il 15": giorno del mese dell'ultima data scritta prima (o del mese corrente)
    for m in _DAY_ONLY_RE.finditer(text):
        day = int(m.group(1))
        if not 1 <= day <= 31:
            continue
        before = [f for f in found if f[0] < m.start(1)]
        ref = max(before, key=lambda f: f[0])[3] if before else today
        dt = _mkdate(ref.year, ref.month, day)
        if dt is not None and before and dt < ref and re.search(r"prossim|success|entro", text[m.start(): m.end() + 30],
                                                                re.I):
            nxt = ref.month % 12 + 1
            dt = _mkdate(ref.year + (ref.month == 12), nxt, day)
        add(m.start(1), m.end(1), m.group(0), dt)

    out: List[DateMention] = []
    seen: Set[Tuple[str, date]] = set()
    for start, end, words, dt in sorted(found, key=lambda f: f[0]):
        key = (words.lower(), dt)
        if key in seen:
            continue
        seen.add(key)
        out.append(DateMention(words, dt, start, _context(text, start, end)))
    return out[:limit]


def date_mentions(text: str, today: Optional[date] = None, limit: int = 16) -> List[Tuple[str, date]]:
    """Date scritte nel testo con le parole usate, nell'ordine in cui compaiono:
    [("1 ottobre 2026", date(2026, 10, 1)), ("ieri", ...)]. Date al modello gia'
    convertite: un modello piccolo altrimenti scrive la data di oggi in ogni campo
    data (che il controllo dei fatti poi toglie: dato perso)."""
    return [(m.words, m.date) for m in date_mentions_ctx(text, today, limit)]


def source_dates(text: str, today: Optional[date] = None) -> Set[date]:
    return (explicit_dates(text, today) | relative_dates(text, today)
            | {m.date for m in date_mentions_ctx(text, today, limit=200)})


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


# parole equivalenti tra il nome di un campo data e le parole vicine alla data nel testo
_DATE_SYNONYMS = {
    "scade": {"entro", "termi", "scade"}, "termi": {"entro", "termi", "scade"},
    "inizi": {"dal", "inizi", "parti", "avvio"}, "fine": {"al", "fino", "termi", "concl"},
    "conse": {"conse", "entro", "evasi"}, "nasci": {"nato", "nata", "nasci"},
    "inter": {"inter", "esegu", "lavor", "sosti", "ripar", "contr", "manut"},
    "riuni": {"riuni", "sedut", "assem"}, "pross": {"pross", "succe"}, "verif": {"verif", "contr", "colla"},
    "colla": {"colla", "prova", "verif"}, "ordin": {"ordin"}, "fattu": {"fattu"},
    "emiss": {"emess", "emiss", "data"}, "rilev": {"rilev", "guast", "anoma", "segna"},
}
_DATE_FIELD_STOP = {"data", "date", "del", "della", "dello", "di", "il", "la", "lo", "giorno", "the", "of"}


def _stems(text: str) -> Set[str]:
    return {w[:5] for w in re.findall(r"[a-z]+", _norm(text)) if len(w) >= 2}


def date_field_score(key: str, spec: Any, mention: DateMention) -> int:
    """Quanto le parole vicine a una data corrispondono al campo: "prossimo incontro il 15"
    -> campo "data_prossimo_incontro" = 2, campo "data_riunione" = 0."""
    from . import field_semantics as fs
    spec = spec if isinstance(spec, dict) else {}
    words = fs.words(key) + fs.words(str(spec.get("title") or "")) + fs.words(str(spec.get("description") or ""))
    field = {w[:5] for w in words if w not in _DATE_FIELD_STOP and len(w) >= 3}
    if not field:
        return 0
    ctx = _stems(mention.context.replace("…", " "))
    score = 0
    for f in field:
        if f in ctx or ctx & _DATE_SYNONYMS.get(f, set()):
            score += 1
    return score


def _generic_date_field(key: str, spec: Any) -> bool:
    """Campo "Data"/"Date" senza altre parole: la data del documento."""
    from . import field_semantics as fs
    spec = spec if isinstance(spec, dict) else {}
    words = fs.words(key) + fs.words(str(spec.get("title") or ""))
    return bool(words) and all(w in _DATE_FIELD_STOP or w in ("documento", "rapporto", "verbale", "compilazione")
                               for w in words)


def best_date_for(key: str, spec: Any, mentions: List[DateMention]) -> Optional[DateMention]:
    """Data del testo che si riferisce al campo, solo se la scelta e' univoca."""
    scored = [(date_field_score(key, spec, m), m) for m in mentions]
    scored = [x for x in scored if x[0] > 0]
    if not scored:
        return None
    top = max(x[0] for x in scored)
    best = {m.date for sc, m in scored if sc == top}
    if len(best) != 1:
        return None
    return next(m for sc, m in scored if sc == top)


class FactGuard:
    def __init__(self, sources: Iterable[str], today: Optional[date] = None):
        self.today = today or date.today()
        sources = [s for s in sources if s]
        self.raw = "\n".join(sources)
        self.norm = _norm(self.raw)
        self.compact = re.sub(r"[\s\-/.:_]", "", self.norm)
        self.dates = source_dates(self.raw, self.today)
        self.numbers = source_numbers(self.raw)
        # date scritte dall'utente (prima fonte) con il contesto: per assegnarle ai campi
        self.mentions = date_mentions_ctx(sources[0] if sources else "", self.today, limit=40)
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
    def _check_date(self, path: str, key: str, value: str, spec: Dict[str, Any]) -> Any:
        as_date = parse_date_value(value)
        if as_date is None:
            # data scritta a parole ("ieri", "5 ottobre"): convertita in AAAA-MM-GG
            found = {m.date for m in date_mentions_ctx(value, self.today)}
            if len(found) == 1 and len(value.split()) <= 5:
                return next(iter(found)).isoformat()
            return value  # es. "fine mese": la verifica la revisione
        fixed, why = fix_date(as_date, self.dates)
        # righe di un elenco (scadenze delle azioni...): il contesto del campo e' lo stesso
        # per tutte le righe, non serve a scegliere la data di ciascuna
        nested = "[" in path or "." in path
        best = None if nested else self._date_for_field(key, spec)
        if fixed == as_date:
            # data presente nel testo ma riferita ad altro ("prossimo incontro il 15" nel
            # campo della data della riunione): si usa quella vicina alle parole del campo
            if best is not None and best.date != as_date and not any(
                    m.date == as_date and date_field_score(key, spec, m) > 0 for m in self.mentions):
                new = _format_like(value, best.date)
                self.corrections.append(Correction(path, value, new, f"data riferita al campo: «{best.words}»"))
                return new
            return value
        if fixed is None and best is not None:
            fixed, why = best.date, f"data presa dal testo: «{best.words}»"
        new = _format_like(value, fixed) if fixed else NON_SPEC
        self.corrections.append(Correction(path, value, new, why))
        return new

    def _check_string(self, path: str, key: str, value: str, spec: Dict[str, Any], person: bool,
                      is_date: bool) -> Any:
        if value.strip().upper() == NON_SPEC or not value.strip():
            return value
        if is_date or parse_date_value(value) is not None:
            return self._check_date(path, key, value, spec)
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

    def _check(self, path: str, key: str, value: Any, spec: Dict[str, Any], person: bool) -> Any:
        from . import field_semantics as fs
        spec = spec if isinstance(spec, dict) else {}
        t = spec.get("type")
        if isinstance(t, list):
            t = next((x for x in t if x != "null"), None)
        if isinstance(value, str):
            return self._check_string(path, key, value, spec, person, fs.kind(key, spec) == "date")
        if t in ("number", "integer"):
            return self._check_number(path, value)
        if isinstance(value, list):
            raw_items = spec.get("items")
            items: Dict[str, Any] = raw_items if isinstance(raw_items, dict) else {}
            out = []
            for i, item in enumerate(value):
                checked = self._check(f"{path}[{i + 1}]", key, item, items, person)
                if isinstance(item, str) and checked == NON_SPEC:
                    continue  # voce inventata: tolta dall'elenco
                out.append(checked)
            return out
        if isinstance(value, dict):
            raw_props = spec.get("properties")
            props: Dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
            return {k: self._check(f"{path}.{k}", k, v, props.get(k, {}), _is_person(k, props.get(k)))
                    for k, v in value.items()}
        return value

    def _date_for_field(self, key: str, spec: Any, single_field: bool = False) -> Optional[DateMention]:
        """Data del testo per il campo: quella vicina alle parole del campo; con un'unica
        data nel testo, quella, se il campo e' l'unico campo data o quello generico ("Data")."""
        best = best_date_for(key, spec, self.mentions)
        if best is None and len({m.date for m in self.mentions}) == 1 \
                and (single_field or _generic_date_field(key, spec)):
            best = self.mentions[0]
        return best

    def _fill_dates(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Campi data rimasti vuoti: la data del testo che si riferisce al campo (parole
        vicine), oppure l'unica data del testo se il modulo ha un solo campo data."""
        from . import field_semantics as fs
        date_keys = [k for k, sp in props.items() if fs.kind(k, sp) == "date"]
        if not date_keys or not self.mentions:
            return
        for key in date_keys:
            v = out.get(key)
            if not (v is None or (isinstance(v, str) and v.strip().upper() in ("", NON_SPEC))):
                continue
            spec = props.get(key) or {}
            best = self._date_for_field(key, spec, single_field=len(date_keys) == 1)
            if best is None:
                continue
            label = (spec.get("title") if isinstance(spec, dict) else None) or key
            out[key] = best.date.isoformat()
            self.corrections.append(Correction(label, v, out[key], f"data trovata nel testo: «{best.words}»"))

    def apply(self, data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
        props = (schema or {}).get("properties", {}) or {}
        out = dict(data)
        for key, value in data.items():
            spec = props.get(key, {})
            label = (spec.get("title") if isinstance(spec, dict) else None) or key
            out[key] = self._check(label, key, value, spec, _is_person(key, spec))
        self._fill_dates(out, props)
        return out


def _is_person(key: str, spec: Any) -> bool:
    from . import field_semantics as fs
    return fs.is_person(key, spec)


def verify(data: Dict[str, Any], schema: Dict[str, Any], sources: Iterable[str],
           today: Optional[date] = None) -> Tuple[Dict[str, Any], List[Correction]]:
    """Ritorna (dati verificati, correzioni applicate)."""
    if not isinstance(data, dict):
        return data, []
    guard = FactGuard(sources, today)
    return guard.apply(data, schema), guard.corrections
