"""Risposte "con prova": per ogni campo il modello cita prima le parole del testo da
cui ricava il valore, poi il valore.

Un modello piccolo (Qwen3 1.7B) che scrive direttamente i valori tende a saltare
informazioni presenti nel testo, a dedurre cose non scritte (Sì/No, scelte da
elenco) e a riempire i campi con dati plausibili. Obbligarlo a copiare la frase
da cui prende il valore (grammatica JSON: ``{"evidenza": "...", "valore": ...}``)
lo costringe a cercare l'informazione nel testo prima di rispondere; il
programma poi verifica che la frase citata esista davvero nel testo:

- Sì/No a true e scelte da elenco senza una frase che le confermi -> tolte
  (false / da scegliere in revisione): erano deduzioni inventate;
- Sì/No a true quando la frase citata nega proprio quella cosa ("nessun fermo
  macchina" per il campo "fermo impianto") -> false;
- testi senza frase e senza parole in comune con il testo dell'utente -> tolti;
- caselle a coppie (``pulizia_si`` / ``pulizia_no``) entrambe spuntate -> tolte.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import field_semantics as fs

NON_SPEC = "NON_SPECIFICATO"
EVIDENCE_KEY = "evidenza"
VALUE_KEY = "valore"
EVIDENCE_MAX = 160  # caratteri: una frase, non un paragrafo (meno token, niente divagazioni)

_STOP = {"della", "delle", "degli", "dello", "nella", "nelle", "negli", "nello", "sono", "stato", "stata",
         "stati", "state", "essere", "anche", "come", "dopo", "prima", "quindi", "perche", "questo",
         "questa", "quello", "quella", "with", "that", "this", "from", "have", "were", "been", "sulla",
         "sulle", "sugli", "alla", "alle", "agli", "dalla", "dalle", "dagli", "tutto", "tutti", "tutte",
         "viene", "vengono", "fatto", "fatta", "fatti", "fatte", "ogni", "molto", "poco", "circa"}
_NEGATIONS = {"non", "nessun", "nessuno", "nessuna", "senza", "no", "niente", "nulla", "assente", "assenti",
              "mai", "not", "none", "without"}


@dataclass
class Fix:
    field: str
    old: Any
    new: Any
    reason: str

    def describe(self) -> str:
        new = "vuoto" if self.new in (None, NON_SPEC) else repr(self.new)
        return f"{self.field}: {self.old!r} → {new} ({self.reason})"


# ---------------------------------------------------------------------------
# Schema imposto al modello
# ---------------------------------------------------------------------------
def wrap_schema(model_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Ogni campo diventa ``{"evidenza": testo, "valore": <campo>}`` (in quest'ordine:
    la grammatica fa scrivere prima la prova). Tutti i campi sono obbligatori: con
    i campi facoltativi la grammatica permetteva al modello di chiudere il JSON
    saltandoli (dati del testo persi)."""
    props = (model_schema or {}).get("properties") or {}
    wrapped: Dict[str, Any] = {}
    for key, spec in props.items():
        wrapped[key] = {
            "type": "object",
            "properties": {
                EVIDENCE_KEY: {"type": "string", "maxLength": EVIDENCE_MAX},
                VALUE_KEY: spec,
            },
            "required": [EVIDENCE_KEY, VALUE_KEY],
            "additionalProperties": False,
        }
    out = {k: v for k, v in (model_schema or {}).items() if k not in ("properties", "required")}
    out.update({"type": "object", "properties": wrapped, "required": list(wrapped),
                "additionalProperties": False})
    return out


def unwrap(parsed: Dict[str, Any], props: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Optional[str]]]:
    """(valori, prove). Accetta anche la risposta "piatta" (backend senza grammatica):
    in quel caso la prova del campo e' ``None`` (sconosciuta, nessuna regola applicata)."""
    values: Dict[str, Any] = {}
    evidence: Dict[str, Optional[str]] = {}
    for key, raw in (parsed or {}).items():
        if key not in props:
            continue
        spec = props.get(key) or {}
        if isinstance(raw, dict) and VALUE_KEY in raw:
            values[key] = raw.get(VALUE_KEY)
            ev = raw.get(EVIDENCE_KEY)
            evidence[key] = ev.strip() if isinstance(ev, str) else ""
        elif isinstance(raw, dict) and fs.base_type(spec) != "object":
            continue  # oggetto senza valore (risposta vuota): campo mancante
        else:
            values[key] = raw
            evidence[key] = None
    return values, evidence


# ---------------------------------------------------------------------------
# Verifica delle prove
# ---------------------------------------------------------------------------
def _stems(text: str) -> List[str]:
    return [w[:5] for w in re.findall(r"[a-z0-9]+", fs.norm(text)) if len(w) >= 4 and w not in _STOP]


class EvidenceChecker:
    def __init__(self, sources: Iterable[str]):
        raw = "\n".join(s for s in sources if s)
        self.norm = fs.norm(raw)
        self.flat = re.sub(r"[^a-z0-9]+", " ", self.norm).strip()
        self.stems = set(_stems(raw))
        self.fixes: List[Fix] = []

    def quote_found(self, quote: Optional[str]) -> bool:
        """La frase citata compare nel testo (uguale, o quasi: piccole differenze di
        punteggiatura, maiuscole, accenti o qualche parola cambiata)."""
        if not quote:
            return False
        q = re.sub(r"[^a-z0-9]+", " ", fs.norm(quote)).strip()
        if not q:
            return False
        if f" {q} " in f" {self.flat} ":
            return True
        words = q.split()
        if len(words) < 2:
            return len(q) >= 3 and q in self.flat
        # almeno 3/4 delle parole significative in sequenza approssimata nel testo
        stems = [w[:5] for w in words if len(w) >= 3]
        if not stems:
            return False
        hit = sum(1 for s in stems if s in self.flat)
        return hit / len(stems) >= 0.75

    def overlap(self, value: str) -> float:
        stems = _stems(value)
        if not stems:
            return 1.0
        return sum(1 for s in stems if s in self.stems) / len(stems)

    # ------------------------------------------------------------------
    def apply(self, data: Dict[str, Any], evidence: Dict[str, Optional[str]],
              schema: Dict[str, Any]) -> Dict[str, Any]:
        props = (schema or {}).get("properties") or {}
        out = dict(data)
        for key, value in data.items():
            if key not in evidence or evidence[key] is None:
                continue  # risposta senza prove (backend senza grammatica): nessuna regola
            spec = props.get(key) or {}
            ev = evidence[key] or ""
            found = self.quote_found(ev)
            name = fs.label(key, spec)
            k = fs.kind(key, spec)
            if k == "bool":
                if value is True and not found:
                    self._fix(out, key, name, value, False, "nessuna frase del testo lo conferma")
                elif value is True and self._negated(ev, key, spec):
                    self._fix(out, key, name, value, False, f"il testo lo esclude: «{ev}»")
            elif k == "choice":
                if isinstance(value, str) and value != NON_SPEC and "specificato" not in value.lower() \
                        and not found:
                    self._fix(out, key, name, value, NON_SPEC, "scelta non ricavabile dal testo")
            elif k in ("text", "person", "code", "time") and isinstance(value, str):
                v = value.strip()
                if v and v.upper() != NON_SPEC and not found and self.overlap(v) < 0.4:
                    self._fix(out, key, name, value, NON_SPEC, "non presente nel testo")
            elif k == "list" and isinstance(value, list) and value and not found:
                kept = [item for item in value if self._item_grounded(item)]
                if len(kept) != len(value):
                    self._fix(out, key, name, value, kept, "voci non presenti nel testo")
        self._pairs(out, props)
        return out

    def _item_grounded(self, item: Any) -> bool:
        if isinstance(item, dict):
            texts = [str(v) for v in item.values() if isinstance(v, (str, int, float)) and str(v).strip()
                     and str(v).strip().upper() != NON_SPEC]
            return not texts or any(self.overlap(t) >= 0.5 for t in texts)
        if isinstance(item, str):
            return self.overlap(item) >= 0.4
        return True

    def _negated(self, ev: str, key: str, spec: Dict[str, Any]) -> bool:
        """La frase citata nega l'oggetto del campo: "nessun fermo" per "fermo impianto".
        Non si applica ai campi gia' negativi ("..._no", "non conforme")."""
        field_words = set(fs.words(key) + fs.words(str(spec.get("title") or "")))
        if field_words & _NEGATIONS:
            return False
        targets = {w[:5] for w in field_words if len(w) >= 4 and w not in _STOP}
        words = re.findall(r"[a-z0-9]+", fs.norm(ev))
        for i, w in enumerate(words):
            if w in _NEGATIONS:
                window = words[i + 1: i + 6]
                if any(x[:5] in targets for x in window if len(x) >= 4):
                    return True
        return False

    def _pairs(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        done = set()
        for key in props:
            other = fs.pair_partner(key, props)
            if not other or key in done:
                continue
            done |= {key, other}
            if out.get(key) is True and out.get(other) is True:
                for k in (key, other):
                    self._fix(out, k, fs.label(k, props.get(k)), True, False,
                              "Sì e No spuntati insieme: scegli in revisione")

    def _fix(self, out: Dict[str, Any], key: str, name: str, old: Any, new: Any, reason: str) -> None:
        out[key] = new
        self.fixes.append(Fix(name, old, new, reason))


def apply(data: Dict[str, Any], evidence: Dict[str, Optional[str]], schema: Dict[str, Any],
          sources: Iterable[str]) -> Tuple[Dict[str, Any], List[Fix]]:
    checker = EvidenceChecker(sources)
    return checker.apply(data, evidence, schema), checker.fixes
