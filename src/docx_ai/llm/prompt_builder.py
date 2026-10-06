"""Prompt construction for structured extraction.

Builds the ``system`` + ``user`` messages sent to the LLM, including:
- the anti-hallucination / extraction policy,
- a semantic description of the schema fields (from schema["properties"][n]["description"]),
- selected reference documents text,
- selected historical examples (formatted),
- the current operator description,
- an explicit /no_think tail supported by Qwen3.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


SYSTEM_POLICY = """Sei un sistema di compilazione di moduli e documenti di qualsiasi tipo
(rapporti, verbali, schede, richieste, checklist, moduli amministrativi...).
Il tuo compito NON è inventare un documento plausibile.
Il tuo compito è trasformare esclusivamente le informazioni fornite dall'utente
e dai documenti di contesto nei campi dello schema richiesto.

COME COMPILARE:
- Leggi tutto il testo dell'utente: ogni informazione che contiene va messa nel campo
  a cui si riferisce (guarda nome, titolo e descrizione del campo).
- Riporta nomi, codici, numeri, importi, quantità e misure ESATTAMENTE come scritti.
- Campi data: formato AAAA-MM-GG. Le date relative ("oggi", "ieri", "lunedì scorso",
  "tra due settimane") si calcolano dalla DATA DI OGGI indicata sotto.
- Campi di testo descrittivi (descrizioni, note, argomenti, decisioni...): frasi chiare
  e complete che riassumono fedelmente quanto scritto dall'utente su quell'argomento,
  senza aggiungere nulla.
- Elenchi: un elemento per ogni voce citata; elenco vuoto [] se non ce ne sono.
- Campi Sì/No: true solo se il testo lo afferma, altrimenti false.
- Campi con valori ammessi: scegli il valore che corrisponde a quanto scritto;
  se il testo non lo dice usa NON_SPECIFICATO.
- Campi numerici: solo numeri presenti nel testo; se manca usa null.
- Scrivi i testi nella stessa lingua usata dall'utente.

REGOLE:
- Non inventare date, nomi, codici, importi, quantità, misure, indirizzi, cause o risultati.
- Quando un'informazione non è disponibile usa NON_SPECIFICATO oppure il valore
  di assenza previsto dallo schema. Non lasciare vuoto un campo se il testo contiene
  l'informazione.
- Non trasformare una possibilità in un fatto.
- Le informazioni contenute nei documenti di riferimento sono istruzioni e contesto,
  non prova di fatti relativi al documento corrente.
- Lo storico può essere usato per comprendere terminologia e forma dei documenti,
  non per copiare dati da documenti passati.
- Restituisci esclusivamente i dati richiesti.
- Non aggiungere campi non previsti.
"""

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def today_line(today: Optional[date] = None) -> str:
    """Data di oggi per il modello: senza, "oggi"/"ieri" diventano date inventate."""
    d = today or date.today()
    return f"DATA DI OGGI: {d.isoformat()} ({_WEEKDAYS[d.weekday()]})"


def _field_line(name: str, spec: Dict[str, Any], required: bool, indent: str = "") -> List[str]:
    t = spec.get("type", "")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    title = spec.get("title", "")
    desc = spec.get("description", "")
    enum = spec.get("enum")
    fmt = spec.get("format")
    suffix_parts = []
    if enum:
        suffix_parts.append("valori_ammessi=" + ",".join(str(e) for e in enum))
    if fmt in ("date", "date-time"):
        suffix_parts.append("formato AAAA-MM-GG")
    sub: List[str] = []
    if t == "array":
        items = spec.get("items", {})
        if isinstance(items, dict) and items.get("type") == "object":
            subprops = items.get("properties", {}) or {}
            if subprops:
                suffix_parts.append("array_di={" + ",".join(subprops.keys()) + "}")
                for sk, sspec in subprops.items():
                    if isinstance(sspec, dict) and (sspec.get("description") or sspec.get("title")
                                                    or sspec.get("enum") or sspec.get("format")):
                        sub += _field_line(sk, sspec, False, indent + "    ")
        else:
            suffix_parts.append("array_di_stringhe")
    suffix = "; ".join(suffix_parts)
    piece = f"{indent}- {name} ({t}"
    if not indent:
        piece += f", obbligatorio={'si' if required else 'no'}"
    piece += ")"
    label = " - ".join(x for x in (title, desc) if x and x != name)
    if label:
        piece += f": {label}"
    if suffix:
        piece += f" [{suffix}]"
    return [piece] + sub


def _schema_semantics(schema: Dict[str, Any]) -> str:
    """Human-readable summary of the JSON Schema shown to the model.

    The raw schema is also enforced via llama.cpp json_schema; this text helps
    the model understand the *meaning* of each field (titles, descriptions,
    enums, date formats, sub-fields of lists).
    """
    props = schema.get("properties", {})
    if not props:
        return ""
    required_fields = schema.get("required", []) or []
    lines = ["SCHEMA:"]
    for k, spec in props.items():
        if isinstance(spec, dict):
            lines += _field_line(k, spec, k in required_fields)
    if required_fields:
        lines.append("Campi obbligatori: " + ", ".join(required_fields))
    return "\n".join(lines)


def _truncate(text: str, max_chars: int, label: str) -> str:
    if text is None:
        return ""
    if len(text) <= max_chars:
        return text
    head = text[: max(0, max_chars - 60)]
    tail = text[-40:]
    return (
        f"{head}\n...[TRONCATO per limite contesto - {label} - mostrate "
        f"{max_chars} di {len(text)} caratteri]...\n{tail}"
    )


def _dates_line(text: str, today: Optional[date] = None) -> str:
    """Date del testo gia' convertite in AAAA-MM-GG (calcolate dal programma, non dall'AI)."""
    from .fact_guard import date_mentions
    found = date_mentions(text, today)
    if not found:
        return ""
    return ("DATE CITATE NEL TESTO (già convertite, usa queste nei campi data): "
            + "; ".join(f"«{words}» = {d.isoformat()}" for words, d in found))


def build_extraction_messages(
    schema: Dict[str, Any],
    operator_description: str,
    *,
    reference_docs: Optional[List[Tuple[str, str]]] = None,
    history_snippets: Optional[List[Dict[str, Any]]] = None,
    max_reference_chars: int = 4000,
    max_history_chars: int = 3500,
    max_description_chars: int = 8000,
    append_no_think: bool = True,
    document_context: str = "",
    max_prompt_chars: int = 14000,
    today: Optional[date] = None,
    focus_fields: Optional[List[str]] = None,
) -> List[Dict[str, str]]:
    """Assemble the messages list.

    Parameters
    ----------
    reference_docs: list of (filename, extracted_text)
    history_snippets: list of dicts with at least "input" and "final_json"
                      keys (used to show shape/terminology)
    max_prompt_chars: budget totale (system + user), derivato dal contesto del
                      modello. Quando non basta si accorciano prima i documenti di
                      riferimento e lo storico, MAI le informazioni dell'utente
                      (prima venivano troncate proprio quelle, in fondo al prompt).
    focus_fields:     compilazione a gruppi: in questa risposta solo questi campi.
                      L'istruzione va in fondo, cosi' tutto il resto del prompt e'
                      identico tra i gruppi e llama-server lo riusa dalla cache.
    """
    system_text = SYSTEM_POLICY + "\n" + today_line(today) + "\n\n" + _schema_semantics(schema)
    if document_context:
        system_text += "\nDOCUMENTO DA COMPILARE: " + _truncate(document_context.strip(), 600, "modulo")

    closing = (
        "\nRestituisci ESCLUSIVAMENTE un JSON valido conforme allo schema indicato. "
        "Non aggiungere commenti, markdown, spiegazioni o testo fuori dall'oggetto JSON."
    )
    if append_no_think:
        # Qwen3-specific tag: disables chain-of-thought tokens for extraction tasks.
        closing += "\n\n/no_think"
    user_header = "=== INFORMAZIONI FORNITE DALL'UTENTE (fonte ufficiale del documento corrente) ==="

    desc_raw = (operator_description or "").strip()
    dates = _dates_line(desc_raw, today)
    budget = (max(1500, int(max_prompt_chars)) - len(system_text) - len(closing) - len(user_header)
              - len(dates) - 200)
    desc = _truncate(desc_raw, max(600, min(max_description_chars, budget)), "descrizione")
    budget -= len(desc)

    context_chunks: List[str] = []
    refs = [(n, t) for n, t in (reference_docs or []) if t]
    if refs and budget > 400:
        header = "=== DOCUMENTI DI RIFERIMENTO (contesto, NON fatti del documento corrente) ==="
        # ai documenti di riferimento al massimo 2/3 dello spazio rimasto, il resto allo storico
        ref_budget = budget * 2 // 3 if history_snippets else budget
        per_doc = min(max_reference_chars, max(300, (ref_budget - len(header)) // len(refs) - 20))
        context_chunks.append(header)
        used = len(header)
        for fname, text in refs:
            piece = f"--- {fname} ---\n{_truncate(text, per_doc, fname)}"
            if used + len(piece) > ref_budget:
                break
            context_chunks.append(piece)
            used += len(piece) + 2
        if len(context_chunks) == 1:
            context_chunks = []
            used = 0
        budget -= used

    if history_snippets and budget > 300:
        header = "=== ESEMPI DI DOCUMENTI APPROVATI (terminologia e forma, NON fatti) ==="
        hist_budget = min(max_history_chars, budget)
        pieces: List[str] = []
        used = len(header)
        for idx, snip in enumerate(history_snippets, 1):
            try:
                inp = snip.get("input", "")
                final = snip.get("final_json") or snip.get("expected") or snip
                if isinstance(final, dict):
                    final_str = json.dumps(final, ensure_ascii=False)
                else:
                    final_str = str(final)
            except Exception:  # noqa: BLE001
                continue
            snippet_text = _truncate(f"Esempio #{idx}:\n  Input: {inp}\n  Output: {final_str}", 1200,
                                     f"esempio{idx}")
            if used + len(snippet_text) > hist_budget:
                break
            pieces.append(snippet_text)
            used += len(snippet_text) + 2
        if pieces:
            context_chunks += [header] + pieces

    user_chunks = context_chunks + [user_header, desc or "(nessuna descrizione fornita)"]
    if dates:
        user_chunks.append(dates)
    if focus_fields:
        user_chunks.append(
            "=== CAMPI DA COMPILARE IN QUESTA RISPOSTA ===\n" + ", ".join(focus_fields)
            + "\nCompila SOLO questi campi (gli altri sono gestiti a parte): rileggi tutto il testo "
            "dell'utente e riporta ogni informazione che li riguarda.")
    user_chunks.append(closing)
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": "\n\n".join(user_chunks)},
    ]
