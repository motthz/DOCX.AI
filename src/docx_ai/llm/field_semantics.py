"""Significato dei campi di un modulo dedotto da nome, titolo e descrizione.

Gli schemi creati dall'editor visuale hanno spesso solo il nome del campo
(``data``, ``firma_operatore``, ``pulizia_si``) senza ``format`` ne' descrizione:
il modello piccolo non capiva che ``data`` e' una data (scriveva testo libero o
nulla) e il controllo dei fatti non verificava la data. Qui il tipo di dato viene
ricavato dalle parole del campo, senza AI.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional

# parole che indicano una data (nome o titolo del campo, parole intere)
_DATE_WORDS = {"data", "date", "scadenza", "deadline", "datum", "giorno"}
_TIME_WORDS = {"ora", "orario", "ore", "time", "inizio_ora", "fine_ora"}
_PERSON_WORDS = ("nome", "cognome", "redattore", "tecnico", "responsabile", "cliente", "partecipant",
                 "firmatari", "richiedente", "operatore", "referente", "fornitore", "azienda", "ditta",
                 "committente", "incaricato", "esecutore", "autore", "destinatari", "presenti", "firma",
                 "verificatore", "manutentore", "name", "customer", "technician", "author", "supplier",
                 "company", "signature")
_CODE_WORDS = ("numero", "codice", "matricola", "cod", "serial", "ordine", "targa", "protocollo",
               "commessa", "lotto", "riferimento", "rif", "ticket", "code", "number", "id", "nr", "num")


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text.lower()).strip()


def words(text: str) -> list:
    """Parole di un nome di campo: "dataIntervento"/"data_intervento" -> [data, intervento]."""
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", text or "")
    return [w for w in re.split(r"[^a-z0-9]+", norm(text)) if w]


def label(key: str, spec: Optional[Dict[str, Any]] = None) -> str:
    """Nome leggibile del campo: titolo se presente, altrimenti la chiave senza trattini."""
    spec = spec if isinstance(spec, dict) else {}
    title = str(spec.get("title") or "").strip()
    if title:
        return title
    return " ".join(words(key)).capitalize() or key


def base_type(spec: Any) -> str:
    if not isinstance(spec, dict):
        return "string"
    t = spec.get("type", "string")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    return str(t)


def kind(key: str, spec: Any) -> str:
    """Tipo di dato del campo: date, time, person, code, number, bool, choice, list, text."""
    spec = spec if isinstance(spec, dict) else {}
    t = base_type(spec)
    if t == "boolean":
        return "bool"
    if t in ("number", "integer"):
        return "number"
    if t in ("array", "object"):
        return "list" if t == "array" else "object"
    if spec.get("enum"):
        return "choice"
    fmt = spec.get("format")
    if fmt in ("date", "date-time"):
        return "date"
    if fmt == "time":
        return "time"
    key_words = words(key)
    # senza titolo conta l'inizio della descrizione ("Data del prossimo incontro")
    title_words = words(str(spec.get("title") or "")) or words(str(spec.get("description") or ""))[:2]
    w = set(key_words) | set(title_words)
    # "data" deve essere una parola intera: "dati_tecnici" non e' una data
    if w & _DATE_WORDS and not w & {"settimana", "luogo"}:
        return "date"
    if key_words in (["dal"], ["al"]):
        return "date"
    if w & _TIME_WORDS and not w & {"lavoro", "lavorate", "totali", "numero", "n"}:
        return "time"
    if is_person(key, spec):
        return "person"
    if w & set(_CODE_WORDS) or re.search(r"(^|_)n(_|$)|^n[a-z]?\d", key.lower()):
        return "code"
    return "text"


def is_person(key: str, spec: Any) -> bool:
    """Campo con nomi di persone o aziende (anche elenchi: partecipanti, presenti)."""
    spec = spec if isinstance(spec, dict) else {}
    joined = " ".join(words(key) + words(str(spec.get("title") or "")))
    return any(h in joined for h in _PERSON_WORDS)


KIND_HINT = {
    "date": "data, scrivi AAAA-MM-GG",
    "time": "ora, scrivi HH:MM",
    "person": "nome di persona o azienda, come scritto nel testo",
    "code": "codice o numero, copiato identico dal testo",
    "number": "numero",
    "bool": "Sì/No: true solo se il testo lo afferma",
    "choice": "scegli tra i valori ammessi",
    "list": "elenco: TUTTE le voci citate nel testo, una per elemento",
    "object": "oggetto",
    "text": "testo",
}


def pair_partner(key: str, props: Dict[str, Any]) -> Optional[str]:
    """Caselle Sì/No a coppie (``pulizia_si`` / ``pulizia_no``): chiave dell'altra casella."""
    m = re.fullmatch(r"(.*?)[_\s-]?(si|sì|no|yes)$", key, re.I)
    if not m or base_type(props.get(key)) != "boolean":
        return None
    stem, suffix = m.group(1), m.group(2).lower()
    other = ("no",) if suffix in ("si", "sì", "yes") else ("si", "sì", "yes")
    for sep in ("_", "", "-", " "):
        for o in other:
            for cand in (f"{stem}{sep}{o}", f"{stem}{sep}{o.upper()}"):
                if cand != key and cand in props and base_type(props[cand]) == "boolean":
                    return cand
    return None


# parole troppo generiche per capire a quale campo si riferisce un valore
_GENERIC = {"numero", "n", "nr", "num", "codice", "cod", "id", "firma", "nome", "cognome", "dati", "dato",
            "valore", "campo", "si", "no", "del", "della", "dello", "di", "il", "la", "lo", "le", "per",
            "data", "date", "the", "of", "number", "code", "name"}
# parole del testo equivalenti alle parole dei campi (radici di 5 lettere)
SYNONYMS = {
    "opera": {"tecni", "opera", "manut", "esegu", "inter"}, "manut": {"manut", "tecni", "inter"},
    "tecni": {"tecni", "opera", "manut"}, "esecu": {"esegu", "effet", "fatta", "fatto", "fatte"},
    "verif": {"verif", "contr", "colla", "appro", "esito"}, "redat": {"redig", "redat", "scriv", "verba"},
    "richi": {"richi", "chied"}, "clien": {"clien", "ditta", "azien", "press"},
    "forni": {"forni", "ditta", "azien"}, "respo": {"respo", "incar", "deve"},
    "rappo": {"rappo", "rapp", "repor"}, "impor": {"impor", "euro", "eur", "costo", "prezz", "spesa", "total"},
    "stima": {"stima", "previ", "circa"}, "cauzi": {"cauzi", "depos"}, "ordin": {"ordin", "ord"}, "matri": {"matri", "seria", "s"},
    "commi": {"commi", "clien"}, "parte": {"parte", "prese"}, "prese": {"prese", "parte"},
    # apparecchiature/impianti: il testo nomina la macchina, non la parola "apparecchiatura"
    "appar": {"appar", "macch", "impia", "pompa", "motor", "compr", "nastr", "valvo", "forno", "quadr",
              "press", "robot", "affet", "confe", "mulin", "impas", "riemp", "etich", "frigo", "cella",
              "carre", "mulet", "gener", "caldai", "ventil", "trasp", "tappa", "dosat", "insac", "pesat"},
}
SYNONYMS["impia"] = SYNONYMS["macch"] = SYNONYMS["attre"] = SYNONYMS["dispo"] = SYNONYMS["appar"]


def field_stems(key: str, spec: Any) -> set:
    """Radici (5 lettere) delle parole significative del campo, con i sinonimi:
    "firma_operatore_manutenzione" -> {opera, manut, tecni, esegu, inter}."""
    spec = spec if isinstance(spec, dict) else {}
    ws = words(key) + words(str(spec.get("title") or ""))
    stems = {w[:5] for w in ws if w not in _GENERIC and len(w) >= 3}
    out = set(stems)
    for s in stems:
        out |= SYNONYMS.get(s, set())
    return out
