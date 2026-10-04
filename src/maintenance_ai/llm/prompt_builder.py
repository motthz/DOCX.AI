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
from typing import Any, Dict, List, Optional, Tuple


SYSTEM_POLICY = """Sei un sistema di estrazione dati per rapporti di manutenzione.
Il tuo compito NON è inventare un rapporto plausibile.
Il tuo compito è trasformare esclusivamente le informazioni fornite dall'operatore
e dai documenti di contesto nei campi dello schema richiesto.

REGOLE:
- Non inventare date, nomi, codici, quantità, misure, componenti, cause o risultati.
- Quando un'informazione non è disponibile usa NON_SPECIFICATO oppure il valore
  di assenza previsto dallo schema.
- Non trasformare una possibilità in un fatto.
- Le informazioni contenute nei documenti di riferimento sono istruzioni e contesto,
  non prova che una specifica attività sia stata eseguita.
- Lo storico può essere usato per comprendere terminologia e forma dei rapporti,
  non per copiare fatti da interventi passati.
- Restituisci esclusivamente i dati richiesti.
- Non aggiungere campi non previsti.
"""


def _schema_semantics(schema: Dict[str, Any]) -> str:
    """Human-readable summary of the JSON Schema shown to the model.

    The raw schema is also enforced via llama.cpp json_schema; this text helps
    the model understand the *meaning* of each field (descriptions, enums, etc).
    """
    props = schema.get("properties", {})
    if not props:
        return ""
    lines = ["SCHEMA:"]
    for k, spec in props.items():
        t = spec.get("type", "")
        desc = spec.get("description", "")
        enum = spec.get("enum")
        required = k in (schema.get("required", []) or [])
        suffix_parts = []
        if enum:
            suffix_parts.append("valori_ammessi=" + ",".join(str(e) for e in enum))
        if t == "array":
            items = spec.get("items", {})
            if isinstance(items, dict) and items.get("type") == "object":
                subprops = items.get("properties", {})
                if subprops:
                    suffix_parts.append(
                        "array_di={" + ",".join(subprops.keys()) + "}"
                    )
            else:
                suffix_parts.append("array_di_stringhe")
        suffix = "; ".join(suffix_parts)
        piece = f"- {k} ({t}, obbligatorio={'si' if required else 'no'})"
        if desc:
            piece += f": {desc}"
        if suffix:
            piece += f" [{suffix}]"
        lines.append(piece)
    required_fields = schema.get("required", []) or []
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


def build_extraction_messages(
    schema: Dict[str, Any],
    operator_description: str,
    *,
    reference_docs: Optional[List[Tuple[str, str]]] = None,
    history_snippets: Optional[List[Dict[str, Any]]] = None,
    max_reference_chars: int = 4000,
    max_history_chars: int = 3500,
    max_description_chars: int = 3000,
    append_no_think: bool = True,
) -> List[Dict[str, str]]:
    """Assemble the messages list.

    Parameters
    ----------
    reference_docs: list of (filename, extracted_text)
    history_snippets: list of dicts with at least "input" and "final_json"
                      keys (used to show shape/terminology)
    """
    system_text = SYSTEM_POLICY + "\n" + _schema_semantics(schema)

    user_chunks: List[str] = []

    if reference_docs:
        user_chunks.append("=== DOCUMENTI DI RIFERIMENTO (contesto, NON fatti dell'intervento corrente) ===")
        for fname, text in reference_docs:
            piece = f"--- {fname} ---\n{_truncate(text, max_reference_chars, fname)}"
            user_chunks.append(piece)

    if history_snippets:
        user_chunks.append("=== ESEMPI DI RAPPORTI APPROVATI (terminologia e forma, NON fatti) ===")
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
            snippet_text = (
                f"Esempio #{idx}:\n  Input: {inp}\n  Output: {final_str}"
            )
            user_chunks.append(_truncate(snippet_text, 1200, f"esempio{idx}"))

    desc = _truncate((operator_description or "").strip(), max_description_chars, "descrizione")
    user_chunks.append("=== DESCRIZIONE OPERATORE (fonte ufficiale dell'intervento corrente) ===")
    user_chunks.append(desc or "(nessuna descrizione fornita)")

    user_chunks.append(
        "\nRestituisci ESCLUSIVAMENTE un JSON valido conforme allo schema indicato. "
        "Non aggiungere commenti, markdown, spiegazioni o testo fuori dall'oggetto JSON."
    )
    if append_no_think:
        # Qwen3-specific tag: disables chain-of-thought tokens for extraction tasks.
        user_chunks.append("\n/no_think")

    user_text = "\n\n".join(user_chunks)
    total = len(system_text) + len(user_text)
    # Global cap to avoid silently eating all CPU on a long prompt
    cap = 14000
    if total > cap:
        overflow = total - cap
        # Take from the end of user_text
        user_text = user_text[: max(500, len(user_text) - overflow)]
        user_text += f"\n\n[NOTA: contesto globale troncato di {overflow} caratteri per rispettare limiti di token.]"
    return [
        {"role": "system", "content": system_text},
        {"role": "user", "content": user_text},
    ]
