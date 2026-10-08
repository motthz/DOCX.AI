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


# abbreviazioni seguite dal punto che non chiudono la frase ("verifica: Ing. Laura Sala")
_ABBR = {"ing", "dott", "dottssa", "sig", "sigra", "geom", "arch", "avv", "prof", "matr", "cod", "rif", "art",
         "pag", "tel", "ecc", "nr", "num", "n", "es", "spett", "egr", "gent", "mr", "dr", "rev", "sez", "pos"}
_BOUNDARY = re.compile(r"([a-z0-9]+)\.\s|[;!?\n]")


def _sentence_tail(text: str) -> str:
    """Ultima frase del testo (il punto delle abbreviazioni non chiude la frase)."""
    cut = 0
    for m in _BOUNDARY.finditer(text):
        if m.group(1) is None or m.group(1) not in _ABBR:
            cut = m.end()
    return text[cut:]


def _sentence_head(text: str) -> str:
    for m in _BOUNDARY.finditer(text):
        if m.group(1) is None or m.group(1) not in _ABBR:
            return text[:m.start() + (len(m.group(1)) if m.group(1) else 0)]
    return text


def _match(context: set, stems: set) -> bool:
    """Parole vicine e parole del campo in comune, anche abbreviate ("matr." ~ matricola)."""
    for w in context:
        for st in stems:
            if w == st or (len(w) >= 4 and len(st) >= 4 and (st.startswith(w) or w.startswith(st))):
                return True
    return False


class EvidenceChecker:
    def __init__(self, sources: Iterable[str]):
        raw = "\n".join(s for s in sources if s)
        self.norm = fs.norm(raw)
        # testo dell'utente (prima fonte): dove cercare le parole vicine a un valore
        self.user = fs.norm(next((s for s in sources if s), ""))
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
                # la scelta e' confermata dalla frase citata o dalle sue parole nel testo
                # ("controllo programmato" -> manutenzione_ordinaria_programmata)
                if isinstance(value, str) and value != NON_SPEC and "specificato" not in value.lower() \
                        and not found and not self._option_in_text(value):
                    self._fix(out, key, name, value, NON_SPEC, "scelta non ricavabile dal testo")
            elif k in ("text", "person", "code", "time") and isinstance(value, str):
                v = value.strip()
                if v and v.upper() != NON_SPEC and not found and self.overlap(v) < 0.4:
                    self._fix(out, key, name, value, NON_SPEC, "non presente nel testo")
            elif k == "list" and isinstance(value, list) and value and not found:
                kept = [item for item in value if self._item_grounded(item)]
                if len(kept) != len(value):
                    self._fix(out, key, name, value, kept, "voci non presenti nel testo")
        self._label_echo(out, props)
        self._codes_in_place(out, props)
        self._duplicates(out, props)
        self._persons_in_place(out, props)
        self._numbers_in_place(out, props)
        self._pairs(out, props, evidence)
        return out

    # ------------------------------------------------------------------
    def _option_in_text(self, option: str) -> bool:
        stems = [w[:5] for w in re.findall(r"[a-z0-9]+", fs.norm(option)) if len(w) >= 4 and w not in _STOP]
        # parole distintive dell'opzione (non "manutenzione", comune a tutte le opzioni)
        return bool(stems) and any(st in self.stems for st in stems[-1:])

    def _contexts(self, value: str) -> List[set]:
        """Radici delle parole vicine a ogni occorrenza del valore nel testo dell'utente,
        nella stessa frase ("Rapporto n. 245/26" -> {rappo})."""
        v = fs.norm(value).strip()
        out: List[set] = []
        if not v:
            return out
        for m in re.finditer(r"(?<![a-z0-9])" + re.escape(v) + r"(?![a-z0-9])", self.user):
            left = _sentence_tail(self.user[max(0, m.start() - 50): m.start()])
            right = re.split(r"[;!?\n,]", _sentence_head(self.user[m.end(): m.end() + 25]))[0]
            # anche le parole del valore stesso: "Pompa P12" dice gia' che e' una macchina
            out.append({w[:5] for w in re.findall(r"[a-z0-9]+", left + " " + v + " " + right) if len(w) >= 2})
        return out

    def _near(self, value: str, key: str, spec: Any) -> Optional[bool]:
        """True se il valore compare nel testo vicino a parole del campo, False se compare
        solo altrove, None se non si puo' dire (campo generico o valore non nel testo)."""
        stems = fs.field_stems(key, spec)
        ctxs = self._contexts(value)
        if not stems or not ctxs:
            return None
        return any(_match(c, stems) for c in ctxs)

    def _claimed_elsewhere(self, value: str, key: str, props: Dict[str, Any]) -> Optional[str]:
        """Altro campo a cui il testo collega il valore con le parole vicine (o None)."""
        ctxs = self._contexts(value)
        for other, spec in props.items():
            st = fs.field_stems(other, spec)
            if other != key and st and any(_match(c, st) for c in ctxs):
                return other
        return None

    def _label_echo(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Il modello scrive il nome del campo come valore ("Oggetto della riunione")."""
        for key, value in list(out.items()):
            spec = props.get(key) or {}
            if not isinstance(value, str) or fs.kind(key, spec) not in ("text", "person", "code", "time"):
                continue
            v = fs.norm(value).strip(" .")
            if not v or v.upper() == NON_SPEC or v in self.norm:
                continue
            ref = fs.norm(" ".join([fs.label(key, spec), key.replace("_", " "), str(spec.get("description") or "")]))
            ref_words = set(re.findall(r"[a-z0-9]+", ref)) | {"del", "della", "dello", "dei", "di", "il", "la", "lo"}
            if v in ref or set(re.findall(r"[a-z0-9]+", v)) <= ref_words:
                self._fix(out, key, fs.label(key, spec), value, NON_SPEC, "è il nome del campo, non un dato")

    def _codes_in_place(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Campi codice (numero rapporto, n. ordine, matricola): il codice deve comparire
        vicino alle parole del campo. "CF-12" della macchina non e' il numero del rapporto."""
        for key, value in list(out.items()):
            spec = props.get(key) or {}
            if fs.kind(key, spec) == "code" and isinstance(value, str) and len(value.split()) > 5:
                # una frase intera non e' un codice ("Oggi controllo programmato sulla...")
                self._fix(out, key, fs.label(key, spec), value, NON_SPEC, "non è un codice")
                continue
            if not isinstance(value, str) or not re.search(r"\d", value):
                continue
            k = fs.kind(key, spec)
            # anche un codice "nudo" in un campo di testo ("P12" come reparto)
            if k != "code" and not (k == "text" and re.fullmatch(r"[A-Za-z]{1,4}[-/.]?\d[\w\-/.]*", value.strip())):
                continue
            if k == "code":
                # "RAPPORTO 77" / "n. 245/26": il codice senza le parole del campo
                stems = fs.field_stems(key, spec) | {"n", "nr", "num", "numer", "cod", "codic"}
                parts = value.strip().split()
                while len(parts) > 1 and fs.norm(parts[0]).strip(".:°#")[:5] in stems:
                    parts.pop(0)
                if len(parts) != len(value.strip().split()):
                    out[key] = value = " ".join(parts)
            # tolto solo se il testo lo collega a un altro campo ("confezionatrice CF-12" ->
            # apparecchiatura): un'abbreviazione non prevista ("matr. 10457") non basta
            other = self._claimed_elsewhere(value, key, props) if self._near(value, key, spec) is False else None
            if other:
                self._fix(out, key, fs.label(key, spec), value, NON_SPEC,
                          "il testo lo indica come " + fs.label(other, props.get(other)).lower())


    def _persons_in_place(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Un nome che il testo collega a un altro campo ("verifica: Ing. Laura Sala")
        non va nella firma di chi ha fatto la pulizia."""
        person_keys = [k for k in props if fs.kind(k, props.get(k)) == "person"]
        if len(person_keys) < 2:
            return
        for key in person_keys:
            value = out.get(key)
            if not isinstance(value, str) or not value.strip() or value.strip().upper() == NON_SPEC:
                continue
            name = re.sub(r"^(?:ing|dott(?:ssa)?|sig(?:ra)?|geom|arch|avv|prof)\.?\s+", "", value.strip(), flags=re.I)
            if self._near(name, key, props.get(key)) is not False:
                continue
            ctxs = self._contexts(name)
            others = [k for k in person_keys if k != key and fs.field_stems(k, props.get(k))
                      and any(_match(c, fs.field_stems(k, props.get(k))) for c in ctxs)]
            if others:
                self._fix(out, key, fs.label(key, props.get(key)), value, NON_SPEC,
                          "il testo lo indica come " + fs.label(others[0], props.get(others[0])).lower())

    def _numbers_in_place(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Importi e quantita': il numero deve stare vicino alle parole del campo
        ("10 risme" non e' l'importo stimato)."""
        for key, value in list(out.items()):
            spec = props.get(key) or {}
            k = fs.kind(key, spec)
            if isinstance(value, bool) or value is None:
                continue
            if k == "number" and isinstance(value, (int, float)):
                text = f"{value:g}"
            elif k == "text" and isinstance(value, str) and re.fullmatch(r"[€$]?\s*\d[\d.,]*\s*(?:€|euro|eur)?",
                                                                       value.strip(), re.I):
                text = re.sub(r"[^\d.,]", "", value)
            else:
                continue
            if fs.field_stems(key, spec) & {"impor", "costo", "prezz", "spesa", "total", "cauzi", "valor"} \
                    and self._near(text, key, spec) is False:
                self._fix(out, key, fs.label(key, spec), value, None if k == "number" else NON_SPEC,
                          "il numero nel testo si riferisce ad altro")

    def _duplicates(self, out: Dict[str, Any], props: Dict[str, Any]) -> None:
        """Lo stesso codice o nome in piu' campi (P12 come reparto, linea e apparecchiatura;
        il tecnico anche come firma della verifica): resta solo nei campi a cui il testo lo
        collega con le parole vicine."""
        groups: Dict[str, List[str]] = {}
        for key, value in out.items():
            spec = props.get(key) or {}
            if fs.kind(key, spec) not in ("text", "person", "code") or not isinstance(value, str):
                continue
            v = fs.norm(value).strip(" .")
            if not v or v.upper() == NON_SPEC or len(v.split()) > 4:
                continue
            groups.setdefault(v, []).append(key)
        for v, keys in groups.items():
            if len(keys) < 2:
                continue
            near = {k: self._near(out[k], k, props.get(k)) for k in keys}
            if any(near[k] is None for k in keys):
                continue  # campo generico o valore non trovato: non si puo' decidere
            keep = [k for k in keys if near[k]]
            if not keep:  # nessun campo collegato: resta nel primo campo non-codice
                keep = [next((k for k in keys if fs.kind(k, props.get(k)) != "code"), keys[0])]
            for k in keys:
                if k not in keep:
                    self._fix(out, k, fs.label(k, props.get(k)), out[k], NON_SPEC,
                              "valore di un altro campo")

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
            # "pulizia non necessaria", "pulizia: no", "badge assente"
            if len(w) >= 4 and w[:5] in targets and any(x in _NEGATIONS for x in words[i + 1: i + 3]) \
                    and "solo" not in words[i + 1: i + 3]:
                return True
        return False

    def _pairs(self, out: Dict[str, Any], props: Dict[str, Any],
               evidence: Optional[Dict[str, Optional[str]]] = None) -> None:
        done = set()
        evidence = evidence or {}
        for key in props:
            other = fs.pair_partner(key, props)
            if not other or key in done:
                continue
            done |= {key, other}
            if out.get(key) is True and out.get(other) is True:
                for k in (key, other):
                    self._fix(out, k, fs.label(k, props.get(k)), True, False,
                              "Sì e No spuntati insieme: scegli in revisione")
                continue
            yes, no = (key, other) if re.search(r"(si|sì|yes)$", key, re.I) else (other, key)
            # "Non è stata necessaria pulizia": Sì escluso dal testo -> No
            if out.get(yes) is True or out.get(no) is True:
                continue
            stem_key = re.sub(r"[_\s-]?(si|sì|yes)$", "", yes, flags=re.I)
            ev = evidence.get(yes) or ""
            if not (ev and self.quote_found(ev) and self._negated(ev, stem_key, {})):
                # frase non citata: le frasi del testo che parlano dell'argomento lo negano tutte
                targets = {w[:5] for w in fs.words(stem_key) if len(w) >= 4 and w not in _STOP}
                sentences = [x for x in re.split(r"(?<=[a-z0-9]{3})\.\s|[;!?\n]", self.user)
                             if targets & {w[:5] for w in re.findall(r"[a-z]+", x)}]
                if not sentences or not all(self._negated(x, stem_key, {}) for x in sentences):
                    continue
                ev = sentences[0].strip()
            # il No tolto sopra perche' la frase citata non c'era: il testo lo conferma
            self.fixes = [f for f in self.fixes if not (f.field == fs.label(no, props.get(no)) and f.old is True)]
            self._fix(out, no, fs.label(no, props.get(no)), out.get(no), True, f"il testo lo esclude: «{ev}»")

    def _fix(self, out: Dict[str, Any], key: str, name: str, old: Any, new: Any, reason: str) -> None:
        out[key] = new
        self.fixes.append(Fix(name, old, new, reason))


def apply(data: Dict[str, Any], evidence: Dict[str, Optional[str]], schema: Dict[str, Any],
          sources: Iterable[str]) -> Tuple[Dict[str, Any], List[Fix]]:
    checker = EvidenceChecker(sources)
    return checker.apply(data, evidence, schema), checker.fixes


def placement_suspects(data: Dict[str, Any], schema: Dict[str, Any], sources: Iterable[str]) -> List[str]:
    """Campi brevi (nomi, codici, testi di poche parole) il cui valore compare nel testo
    solo lontano dalle parole del campo: candidati a "informazione vera, campo sbagliato".
    Da soli non bastano per togliere il valore (la conferma la da' verify_placement)."""
    checker = EvidenceChecker(sources)
    props = (schema or {}).get("properties") or {}
    out = []
    for key, value in (data or {}).items():
        spec = props.get(key) or {}
        # solo nomi e codici: per reparti, luoghi e testi brevi il modello interrogato da solo
        # rispondeva spesso "non indicato" anche quando il dato c'era ("del magazzino")
        if fs.kind(key, spec) not in ("person", "code") or not isinstance(value, str):
            continue
        v = re.sub(r"^(?:ing|dott(?:ssa)?|sig(?:ra)?|geom|arch|avv|prof)\.?\s+", "", value.strip(), flags=re.I)
        if not v or v.upper() == NON_SPEC or len(v.split()) > 4:
            continue
        if checker._near(v, key, spec) is False:
            out.append(key)
    return out


PLACEMENT_SYSTEM = (
    "Rispondi a UNA domanda su un testo. Se il testo contiene la risposta, copiala con le parole del "
    "testo (poche parole). Se il testo non dice esplicitamente la risposta, rispondi esattamente "
    "NON INDICATO. Non dedurre e non usare informazioni che rispondono ad altre domande.")


def placement_question(text: str, key: str, spec: Any) -> List[Dict[str, str]]:
    spec = spec if isinstance(spec, dict) else {}
    desc = str(spec.get("description") or "").strip()
    what = fs.label(key, spec) + (f" ({desc})" if desc else "")
    return [{"role": "system", "content": PLACEMENT_SYSTEM},
            {"role": "user", "content": f"Testo:\n{text}\n\nDomanda: nel testo, qual è «{what}»?\n/no_think"}]


PLACEMENT_SCHEMA = {"type": "object", "properties": {"risposta": {"type": "string", "maxLength": 120}},
                    "required": ["risposta"], "additionalProperties": False}


def not_indicated(answer: str) -> bool:
    a = fs.norm(answer or "").strip(" .\"'«»")
    return not a or a in ("non indicato", "non indicata", "non specificato", "nessuno", "non presente") \
        or a.startswith("non indicat")
