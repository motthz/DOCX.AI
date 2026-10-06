"""Controllo anti-allucinazione: ogni valore proposto dall'AI deve trovare
riscontro nei testi sorgente (descrizione dell'operatore + documenti).

Per ogni campo restituisce uno stato:
- ``ok``        tutti i dati "rischiosi" (numeri, codici, date, nomi) compaiono nelle fonti
- ``missing``   almeno un dato non compare: probabile invenzione, da verificare
- ``inferred``  valore non verificabile testualmente (booleani, scelte da elenco)
- ``empty``     campo vuoto / NON_SPECIFICATO
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

EMPTY_MARKERS = {"", "non_specificato", "non specificato", "[da definire]", "[da compilare]", "n/a", "-"}
MONTHS = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
    "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}
_ISO_DATE = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_EU_DATE = re.compile(r"\b(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2,4})\b")
_TEXT_DATE = re.compile(r"\b(\d{1,2})\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.I)
_CODE = re.compile(r"\b(?=[\w\-/.]*\d)[\w][\w\-/.]*\b")
_NAME = re.compile(r"\b[A-ZÀ-Ý][a-zà-ÿ']{2,}(?:\s+[A-ZÀ-Ý][a-zà-ÿ']{2,})+\b")


def _norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower())


def _dates(text: str) -> set:
    out = set()
    for y, m, d in _ISO_DATE.findall(text):
        out.add((int(y), int(m), int(d)))
    for d, m, y in _EU_DATE.findall(text):
        yy = int(y) + (2000 if len(y) == 2 else 0)
        out.add((yy, int(m), int(d)))
    for d, mname, y in _TEXT_DATE.findall(text):
        out.add((int(y), MONTHS[mname.lower()], int(d)))
    return out


@dataclass
class FieldCheck:
    status: str
    missing: List[str] = field(default_factory=list)

    @property
    def message(self) -> str:
        if self.status == "missing":
            return "Non trovato nelle fonti: " + ", ".join(self.missing[:4])
        return {"ok": "Trovato nelle fonti", "inferred": "Dedotto (verificare)",
                "empty": "Non specificato"}.get(self.status, "")


class GroundingChecker:
    def __init__(self, sources: List[str]):
        raw = "\n".join(s for s in sources if s)
        self._raw = raw
        self._norm = _norm(raw)
        self._compact = re.sub(r"[\s\-/.]", "", self._norm)
        self._dates = _dates(raw)
        # anche "ieri", "lunedì scorso", "5 ottobre" senza anno: non sono date inventate
        from .fact_guard import source_dates
        self._dates |= {(d.year, d.month, d.day) for d in source_dates(raw)}

    def _present(self, token: str) -> bool:
        n = _norm(token).strip()
        if not n:
            return True
        if n in self._norm:
            return True
        return re.sub(r"[\s\-/.]", "", n) in self._compact

    def check_value(self, value: Any, spec: Optional[Dict[str, Any]] = None) -> FieldCheck:
        spec = spec or {}
        if value is None or isinstance(value, bool):
            return FieldCheck("inferred" if isinstance(value, bool) else "empty")
        if isinstance(value, (list, dict)):
            items = value.values() if isinstance(value, dict) else value
            checks = [self.check_value(v, None) for v in items]
            if not checks or all(c.status == "empty" for c in checks):
                return FieldCheck("empty")
            missing = [m for c in checks for m in c.missing]
            if missing:
                return FieldCheck("missing", missing)
            return FieldCheck("ok" if any(c.status == "ok" for c in checks) else "inferred")
        text = str(value).strip()
        if _norm(text) in EMPTY_MARKERS:
            return FieldCheck("empty")
        if spec.get("enum") and value in spec["enum"]:
            return FieldCheck("inferred")
        risky: List[str] = []
        value_dates = _dates(text)
        for d in value_dates:
            if d not in self._dates:
                risky.append(f"{d[2]:02d}/{d[1]:02d}/{d[0]}")
        stripped = _ISO_DATE.sub(" ", _EU_DATE.sub(" ", _TEXT_DATE.sub(" ", text)))
        for tok in _CODE.findall(stripped):
            if not self._present(tok):
                risky.append(tok)
        for name in _NAME.findall(text):
            if not self._present(name):
                risky.append(name)
        if risky:
            return FieldCheck("missing", sorted(set(risky)))
        if value_dates or _CODE.search(stripped) or _NAME.search(text) or self._present(text):
            return FieldCheck("ok")
        # testo libero senza dati specifici: verifica che le parole chiave compaiano
        words = [w for w in re.findall(r"[a-zà-ÿ]{5,}", text.lower())]
        if words and sum(self._present(w) for w in words) >= max(1, len(words) // 2):
            return FieldCheck("ok")
        return FieldCheck("inferred")

    def check(self, data: Dict[str, Any], schema: Optional[Dict[str, Any]] = None) -> Dict[str, FieldCheck]:
        props = (schema or {}).get("properties", {}) or {}
        return {k: self.check_value(v, props.get(k)) for k, v in (data or {}).items()}


def summarize(checks: Dict[str, FieldCheck]) -> Dict[str, int]:
    out: Dict[str, int] = {"ok": 0, "missing": 0, "inferred": 0, "empty": 0}
    for c in checks.values():
        out[c.status] = out.get(c.status, 0) + 1
    return out
