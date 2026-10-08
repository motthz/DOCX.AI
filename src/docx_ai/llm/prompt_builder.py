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

from .fact_guard import stated_today


SYSTEM_POLICY = """Sei un sistema di compilazione di moduli e documenti di qualsiasi tipo
(rapporti, verbali, schede, richieste, checklist, moduli amministrativi...).
Il tuo compito NON è inventare un documento plausibile.
Il tuo compito è trasformare esclusivamente le informazioni fornite dall'utente
e dai documenti di contesto nei campi dello schema richiesto.

COME COMPILARE:
- Leggi TUTTO il testo dell'utente, frase per frase: ogni informazione va nel campo a cui
  si riferisce (guarda nome, titolo e descrizione del campo). Un'informazione può servire
  a più campi.
- Riporta nomi, codici, numeri, importi, quantità e misure ESATTAMENTE come scritti.
- Campi data: formato AAAA-MM-GG. Usa le date già convertite elencate in "DATE NEL TESTO";
  scegli quella che si riferisce al campo (guarda le parole vicine alla data).
- Campi di testo descrittivi (descrizioni, note, argomenti, decisioni...): frasi chiare
  e complete che riassumono fedelmente quanto scritto dall'utente su quell'argomento,
  senza aggiungere nulla.
- Elenchi: un elemento per ogni voce citata; elenco vuoto [] se non ce ne sono.
- Campi Sì/No: true solo se il testo lo afferma, false se lo nega o non ne parla.
- Campi con valori ammessi: scegli il valore che corrisponde a quanto scritto;
  se il testo non lo dice usa NON_SPECIFICATO.
- Campi numerici: solo numeri presenti nel testo; se manca usa null.
- Scrivi i testi nella stessa lingua usata dall'utente.

REGOLE:
- Non inventare date, nomi, codici, importi, quantità, misure, indirizzi, cause o risultati.
- Quando un'informazione non è disponibile usa NON_SPECIFICATO oppure il valore
  di assenza previsto dallo schema. Non lasciare vuoto un campo se il testo contiene
  l'informazione.
- Non trasformare una possibilità ("forse", "potrebbe") in un fatto.
- Le informazioni contenute nei documenti di riferimento sono istruzioni e contesto,
  non prova di fatti relativi al documento corrente.
- Lo storico può essere usato per comprendere terminologia e forma dei documenti,
  non per copiare dati da documenti passati.
- Restituisci esclusivamente i dati richiesti.
- Non aggiungere campi non previsti.
"""

# Risposta con prova (vedi llm/evidence.py): il modello cita la frase del testo da cui
# ricava ogni valore. Un esempio concreto e' l'aiuto piu' efficace per un modello piccolo.
EVIDENCE_POLICY = """FORMATO DELLA RISPOSTA:
Per ogni campo scrivi un oggetto {"evidenza": "...", "valore": ...}:
- "evidenza": le parole del testo dell'utente da cui ricavi il valore, COPIATE ESATTAMENTE
  (poche parole, al massimo una frase). Se il testo non contiene l'informazione: "".
- "valore": il valore del campo ricavato da quella evidenza. Con evidenza "" usa
  NON_SPECIFICATO (testi e scelte), null (numeri), false (Sì/No) o [] (elenchi).

ESEMPIO (solo per il formato: i dati dell'esempio NON vanno mai usati)
Testo: "Stamattina il tecnico Gino Neri ha cambiato la valvola V-3 del reparto Forni, 2 ore di lavoro. Collaudo superato, nessuna perdita."
Date nel testo: «Stamattina» = 2031-03-14
Campi: data_intervento (data), tecnico (persona), apparecchiatura (testo), ore (numero), esito (valori: positivo, negativo), cliente (persona), perdite_rilevate (Sì/No)
Risposta:
{"data_intervento": {"evidenza": "Stamattina", "valore": "2031-03-14"}, "tecnico": {"evidenza": "il tecnico Gino Neri", "valore": "Gino Neri"}, "apparecchiatura": {"evidenza": "la valvola V-3 del reparto Forni", "valore": "Valvola V-3 (reparto Forni)"}, "ore": {"evidenza": "2 ore di lavoro", "valore": 2}, "esito": {"evidenza": "Collaudo superato", "valore": "positivo"}, "cliente": {"evidenza": "", "valore": "NON_SPECIFICATO"}, "perdite_rilevate": {"evidenza": "nessuna perdita", "valore": false}}
"""

_WEEKDAYS = ("lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica")


def today_line(today: Optional[date] = None) -> str:
    """Data di oggi per il modello: senza, "oggi"/"ieri" diventano date inventate."""
    d = today or date.today()
    return f"DATA DI OGGI: {d.isoformat()} ({_WEEKDAYS[d.weekday()]})"


def _field_line(name: str, spec: Dict[str, Any], required: bool, indent: str = "") -> List[str]:
    from . import field_semantics as fs
    spec = spec if isinstance(spec, dict) else {}
    t = fs.base_type(spec)
    title = spec.get("title", "")
    desc = spec.get("description", "")
    enum = spec.get("enum")
    k = fs.kind(name, spec)
    suffix_parts = []
    if enum:
        suffix_parts.append("valori_ammessi=" + ",".join(str(e) for e in enum))
    if k == "date":
        suffix_parts.append("data, formato AAAA-MM-GG")
    elif k in ("time", "person", "code"):
        suffix_parts.append(fs.KIND_HINT[k])
    sub: List[str] = []
    if t == "array":
        items = spec.get("items", {})
        if isinstance(items, dict) and items.get("type") == "object":
            subprops = items.get("properties", {}) or {}
            if subprops:
                suffix_parts.append("array_di={" + ",".join(subprops.keys()) + "}")
                for sk, sspec in subprops.items():
                    sub += _field_line(sk, sspec, False, indent + "    ")
        else:
            suffix_parts.append("array_di_stringhe")
    suffix = "; ".join(suffix_parts)
    piece = f"{indent}- {name} ({t}"
    if not indent:
        piece += f", obbligatorio={'si' if required else 'no'}"
    piece += ")"
    readable = title or (fs.label(name, spec) if fs.label(name, spec).lower() != name.lower() else "")
    label = " - ".join(x for x in (readable, desc) if x and x != name)
    if label:
        piece += f": {label}"
    if suffix:
        piece += f" [{suffix}]"
    return [piece] + sub


def _focus_lines(schema: Dict[str, Any], keys: List[str]) -> str:
    """Campi da compilare ripetuti subito prima della risposta, con il loro significato:
    il modello piccolo "dimentica" le descrizioni lette all'inizio del prompt."""
    from . import field_semantics as fs
    props = schema.get("properties", {}) or {}
    lines = []
    for k in keys:
        raw = props.get(k)
        spec: Dict[str, Any] = raw if isinstance(raw, dict) else {}
        kd = fs.kind(k, spec)
        hint = fs.KIND_HINT.get(kd, "testo")
        if kd == "choice":
            hint = "valori: " + ", ".join(str(e) for e in spec.get("enum") or [])
        elif kd == "list":
            items = spec.get("items") or {}
            if isinstance(items, dict) and isinstance(items.get("properties"), dict):
                hint = "elenco di righe con " + ", ".join(items["properties"])
        desc = str(spec.get("description") or "").strip()
        lines.append(f"- {k} = {fs.label(k, spec)} ({hint})" + (f": {desc}" if desc else ""))
    return "\n".join(lines)


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
    """Date del testo gia' convertite in AAAA-MM-GG (calcolate dal programma, non dall'AI),
    con le parole vicine per capire a quale campo si riferiscono."""
    from .fact_guard import date_mentions_ctx
    found = date_mentions_ctx(text, today)
    if not found:
        return ""
    parts = []
    for m in found:
        ctx = m.context.replace("…", "[" + m.words + "]") if m.context else ""
        parts.append(f"«{m.words}» = {m.date.isoformat()}" + (f" (\"{ctx}\")" if ctx and ctx != m.words else ""))
    return "DATE NEL TESTO (già convertite, usa queste nei campi data):\n" + "\n".join("- " + p for p in parts)


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
    evidence: bool = False,
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
    evidence:         risposta {"evidenza", "valore"} per campo (vedi llm/evidence.py).
    """
    ev_policy = ""
    if evidence:
        ev_policy = EVIDENCE_POLICY
        # contesto piccolo (profilo compatibility, 4096 token): l'esempio lascia il posto al
        # testo dell'utente, che non deve mai essere accorciato
        if len(SYSTEM_POLICY) + len(EVIDENCE_POLICY) + 3 * len(operator_description or "") \
                + 120 * len(schema.get("properties") or {}) > int(max_prompt_chars):
            ev_policy = EVIDENCE_POLICY.split("ESEMPIO", 1)[0]
    system_text = SYSTEM_POLICY + "\n" + (ev_policy + "\n" if ev_policy else "") \
        + today_line(stated_today(operator_description or "", today)) + "\n\n" + _schema_semantics(schema)
    if document_context:
        system_text += "\nDOCUMENTO DA COMPILARE: " + _truncate(document_context.strip(), 600, "modulo")

    closing = (
        "\nRestituisci ESCLUSIVAMENTE un JSON valido conforme allo schema indicato"
        + (", con evidenza e valore per ogni campo" if evidence else "") + ". "
        "Non aggiungere commenti, markdown, spiegazioni o testo fuori dall'oggetto JSON."
    )
    if append_no_think:
        # Qwen3-specific tag: disables chain-of-thought tokens for extraction tasks.
        closing += "\n\n/no_think"
    user_header = "=== INFORMAZIONI FORNITE DALL'UTENTE (fonte ufficiale del documento corrente) ==="

    desc_raw = (operator_description or "").strip()
    dates = _dates_line(desc_raw, today)
    all_keys = list((schema.get("properties") or {}))
    # spazio per l'elenco dei campi in fondo: calcolato sull'elenco completo, uguale per
    # tutti i gruppi (il prompt deve restare identico per la cache di llama-server)
    focus_reserve = len(_focus_lines(schema, all_keys)) + 250
    budget = (max(1500, int(max_prompt_chars)) - len(system_text) - len(closing) - len(user_header)
              - len(dates) - focus_reserve)
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
    keys = [k for k in (focus_fields or all_keys) if k in (schema.get("properties") or {})]
    if keys:
        only = (" Compila SOLO questi campi (gli altri sono gestiti a parte)." if focus_fields else "")
        user_chunks.append(
            "=== CAMPI DA COMPILARE IN QUESTA RISPOSTA ===\n" + _focus_lines(schema, keys)
            + "\n" + only.strip() + (" " if only else "")
            + "Rileggi tutto il testo dell'utente e riporta ogni informazione che riguarda questi campi.")
    user_chunks.append(closing)
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": "\n\n".join(user_chunks)},
    ]
