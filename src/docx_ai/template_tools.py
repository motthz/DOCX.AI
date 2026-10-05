"""Operazioni sui campi {{...}} di un template, usate dall'editor visuale.

Logica pura (senza interfaccia), cosi' e' verificabile dai test:
- nome tecnico del campo a partire dal nome scritto dall'utente;
- inserimento / sostituzione / rimozione di un segnaposto in un paragrafo DOCX
  mantenendo lo stile del testo vicino;
- riconoscimento dei "punti da compilare" (es. ``Nome: ________``);
- nome suggerito per il campo dall'etichetta che lo precede;
- definizione JSON Schema dei tipi proposti all'utente.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional, Tuple

PLACEHOLDER_RE = re.compile(r"\{\{\s*([^\W\d][\w\.]*)\s*\}\}")

# righe da compilare tipiche dei moduli: ______  .......  …… -----
BLANK_RE = re.compile(r"_{2,}|\.{3,}|…+|-{3,}")

# tipi mostrati all'utente -> chiave interna
FIELD_TYPES = ("text", "number", "date", "bool", "choice", "list")


def spec_for(kind: str, *, title: str = "", description: str = "",
             options: Optional[List[str]] = None) -> Dict[str, Any]:
    """Definizione JSON Schema per un tipo dell'editor."""
    if kind == "number":
        spec: Dict[str, Any] = {"type": "number"}
    elif kind == "date":
        spec = {"type": "string", "format": "date"}
    elif kind == "bool":
        spec = {"type": "boolean"}
    elif kind == "choice":
        spec = {"type": "string", "enum": [o for o in (options or []) if o] or ["Sì", "No"]}
    elif kind == "list":
        spec = {"type": "array", "items": {"type": "string"}}
    else:
        spec = {"type": "string"}
    if title:
        spec["title"] = title
    if description:
        spec["description"] = description
    return spec


def kind_of(spec: Dict[str, Any]) -> str:
    """Tipo dell'editor corrispondente a una definizione JSON Schema esistente."""
    spec = spec or {}
    if isinstance(spec.get("enum"), list):
        return "choice"
    typ = spec.get("type", "string")
    if isinstance(typ, list):
        typ = next((x for x in typ if x != "null"), "string")
    if typ in ("number", "integer"):
        return "number"
    if typ == "boolean":
        return "bool"
    if typ == "array":
        return "list"
    if typ == "string" and spec.get("format") in ("date", "date-time"):
        return "date"
    return "text"


def change_kind(spec: Dict[str, Any], kind: str, options: Optional[List[str]] = None) -> Dict[str, Any]:
    """Nuova definizione col tipo scelto, conservando titolo, descrizione e chiavi extra."""
    keep = {k: v for k, v in (spec or {}).items() if k not in ("type", "format", "enum", "items")}
    new = spec_for(kind, options=options if options is not None else (spec or {}).get("enum"))
    new.update(keep)
    return new


def field_key(label: str, existing: Iterable[str] = ()) -> str:
    """Nome tecnico (lettere, numeri, _) dal nome scritto dall'utente, unico tra ``existing``.

    "Nome e cognome del cliente" -> "nome_e_cognome_del_cliente"; "N° ordine" -> "n_ordine".
    """
    text = unicodedata.normalize("NFKD", label or "").encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")[:48].strip("_")
    if not key:
        key = "campo"
    if key[0].isdigit():
        key = "campo_" + key
    taken = set(existing)
    if key not in taken:
        return key
    n = 2
    while f"{key}_{n}" in taken:
        n += 1
    return f"{key}_{n}"


def title_of(key: str, spec: Optional[Dict[str, Any]] = None) -> str:
    """Nome leggibile del campo: il titolo se c'e', altrimenti il nome tecnico 'umanizzato'."""
    t = str((spec or {}).get("title") or "").strip()
    return t or key.replace("_", " ").strip().capitalize()


def suggest_label(before: str) -> str:
    """Etichetta che precede un punto da compilare: "Data intervento: ____" -> "Data intervento"."""
    text = BLANK_RE.sub(" ", PLACEHOLDER_RE.sub(" ", before or ""))
    # l'etichetta e' l'ultima frase prima del punto di inserimento
    text = re.split(r"[.;!?\n\t|]|\s{3,}", text.rstrip(" :_-–—=\t"))[-1]
    text = re.sub(r"\s+", " ", text).strip(" :_-–—=()[]")
    words = text.split(" ")
    if len(words) > 5:
        text = " ".join(words[-5:])
    return text[:60].strip()


def blank_at(text: str, offset: int) -> Optional[Tuple[int, int]]:
    """Intervallo della riga da compilare (______) sotto o accanto alla posizione ``offset``."""
    for m in BLANK_RE.finditer(text or ""):
        if m.start() <= offset <= m.end():
            return m.start(), m.end()
    return None


def placeholder_at(text: str, offset: int) -> Optional[Tuple[int, int, str]]:
    """Segnaposto {{...}} che contiene la posizione ``offset`` (estremi esclusi)."""
    for m in PLACEHOLDER_RE.finditer(text or ""):
        if m.start() <= offset < m.end():
            return m.start(), m.end(), m.group(1)
    return None


def snap_offset(text: str, offset: int) -> int:
    """Non spezza le parole: se ``offset`` cade dentro una parola va alla sua fine."""
    offset = max(0, min(offset, len(text)))
    while 0 < offset < len(text) and text[offset - 1].isalnum() and text[offset].isalnum():
        offset += 1
    return offset


# ---------------------------------------------------------------- paragrafi DOCX
def _spans(paragraph) -> List[Tuple[Any, int, int]]:
    spans, cur = [], 0
    for run in paragraph.runs:
        spans.append((run, cur, cur + len(run.text)))
        cur += len(run.text)
    return spans


def replace_span(paragraph, start: int, end: int, text: str) -> None:
    """Sostituisce i caratteri [start, end) del paragrafo mantenendo lo stile del primo run."""
    spans = _spans(paragraph)
    touched = [i for i, (_r, rs, re_) in enumerate(spans) if not (re_ <= start or rs >= end)]
    if not touched:
        if start == end:
            insert_at(paragraph, start, text)
        return
    first, last = touched[0], touched[-1]
    fr, frs, _ = spans[first]
    lr, lrs, _ = spans[last]
    pre = fr.text[: max(0, start - frs)]
    post = lr.text[max(0, end - lrs):]
    if first == last:
        fr.text = pre + text + post
        return
    fr.text = pre + text
    for i in range(first + 1, last):
        spans[i][0].text = ""
    lr.text = post


def insert_at(paragraph, offset: int, text: str) -> None:
    """Inserisce ``text`` alla posizione ``offset`` usando lo stile del testo che precede."""
    spans = _spans(paragraph)
    if not spans:
        paragraph.add_run(text)
        return
    for run, rs, re_ in spans:
        if rs < offset <= re_ or (offset == 0 and rs == 0):
            k = offset - rs
            run.text = run.text[:k] + text + run.text[k:]
            return
    run = spans[-1][0]
    run.text = run.text + text


def place_field(paragraph, offset: int, key: str, *, end: Optional[int] = None) -> Tuple[int, int]:
    """Mette {{key}} nel paragrafo e restituisce l'intervallo occupato.

    - con ``end``: sostituisce il testo [offset, end) (selezione dell'utente);
    - sopra un segnaposto esistente: lo sostituisce;
    - sopra una riga da compilare (____): la sostituisce;
    - altrimenti inserisce nel punto, senza spezzare parole e separando con spazi.
    """
    token = "{{" + key + "}}"
    text = paragraph.text
    if end is not None and end > offset:
        replace_span(paragraph, offset, end, token)
        return offset, offset + len(token)
    ph = placeholder_at(text, offset)
    if ph:
        replace_span(paragraph, ph[0], ph[1], token)
        return ph[0], ph[0] + len(token)
    blank = blank_at(text, offset)
    if blank:
        replace_span(paragraph, blank[0], blank[1], token)
        return blank[0], blank[0] + len(token)
    offset = snap_offset(text, offset)
    before = text[offset - 1] if offset > 0 else ""
    after = text[offset] if offset < len(text) else ""
    lead = " " if before and not before.isspace() and before not in "([«\"'" else ""
    tail = " " if after and not after.isspace() and after not in ".,;:)]»\"'" else ""
    insert_at(paragraph, offset, lead + token + tail)
    return offset + len(lead), offset + len(lead) + len(token)


def remove_field_at(paragraph, start: int, end: int) -> None:
    """Toglie il segnaposto [start, end) e lo spazio doppio che lascerebbe."""
    text = paragraph.text
    if 0 < start and end < len(text) and text[start - 1] == " " and text[end] == " ":
        end += 1
    replace_span(paragraph, start, end, "")


def iter_placeholders(paragraphs: Iterable[Any]) -> Iterable[Tuple[Any, int, int, str]]:
    for p in paragraphs:
        for m in PLACEHOLDER_RE.finditer(p.text):
            yield p, m.start(), m.end(), m.group(1)


def rename_field(paragraphs: Iterable[Any], old: str, new: str) -> int:
    """Rinomina {{old}} in {{new}} in tutti i paragrafi; restituisce quante occorrenze."""
    n = 0
    for p in paragraphs:
        for m in reversed([m for m in PLACEHOLDER_RE.finditer(p.text) if m.group(1) == old]):
            replace_span(p, m.start(), m.end(), "{{" + new + "}}")
            n += 1
    return n


def remove_field(paragraphs: Iterable[Any], key: str) -> int:
    """Toglie tutte le occorrenze di {{key}}; restituisce quante."""
    n = 0
    for p in paragraphs:
        for m in reversed([m for m in PLACEHOLDER_RE.finditer(p.text) if m.group(1) == key]):
            remove_field_at(p, m.start(), m.end())
            n += 1
    return n
