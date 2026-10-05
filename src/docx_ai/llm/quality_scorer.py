"""Quality scorer 0..100 for LLM-generated JSON report data."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

SCORE_BAD_GREEN = 75
SCORE_BAD_YELLOW = 50


def _required_names(schema: Dict[str, Any]) -> List[str]:
    if not isinstance(schema, dict):
        return []
    r = schema.get("required")
    if isinstance(r, list):
        return [x for x in r if isinstance(x, str)]
    return []


def _properties(schema: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(schema, dict):
        return {}
    p = schema.get("properties")
    if isinstance(p, dict):
        return {k: v for k, v in p.items() if isinstance(v, dict)}
    return {}


def _enum_sentinels(enum_list: Any) -> Tuple[bool, List[Any]]:
    """Detect unspecified enum sentinels. Returns (has_sentinel, list_of_sentinels)."""
    if not isinstance(enum_list, list):
        return False, []
    sentinels: List[Any] = []
    for v in enum_list:
        if isinstance(v, str) and (v == "NON_SPECIFICATO" or v == "" or "SPECIFICATO" in v or "non specific" in v.lower()):
            sentinels.append(v)
    if sentinels:
        return True, sentinels
    # Fallback: se enum contiene stringhe vuote o "Altro" come ultimo valore opzionale
    last_empty = [e for e in enum_list if isinstance(e, str) and e.strip() == ""]
    if last_empty:
        return True, last_empty
    return False, []


def _filled(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, str) and (v == "NON_SPECIFICATO" or v.strip() == ""):
        return False
    if isinstance(v, (list, dict)) and len(v) == 0:
        return False
    return True


def score(data: Dict[str, Any], schema: Dict[str, Any]) -> int:
    """Punteggio 0..100: campi obbligatori compilati (60), campi facoltativi (20),
    elenchi con un valore reale invece del "non specificato" (20).

    Le voci che non si applicano al modulo (nessun campo facoltativo, nessun elenco)
    non tolgono punti: il loro peso viene ridistribuito sulle altre. Un modulo con
    tutti i campi compilati vale quindi 100 anche se i valori sono brevi (nomi, date).
    """
    if not isinstance(data, dict):
        data = {}
    if not isinstance(schema, dict):
        schema = {}
    props = _properties(schema)
    required = [x for x in _required_names(schema) if x in props]
    optional = [k for k in props if k not in required]

    parts: List[Tuple[float, float]] = []  # (peso, frazione 0..1)
    if required:
        parts.append((60.0, sum(_filled(data.get(k)) for k in required) / len(required)))
    if optional:
        parts.append((20.0, sum(_filled(data.get(k)) for k in optional) / len(optional)))
    enum_fields = [(k, p) for k, p in props.items() if "enum" in p]
    if enum_fields:
        enum_ok = 0
        for k, p in enum_fields:
            has_s, sentinels = _enum_sentinels(p.get("enum"))
            v = data.get(k)
            if not has_s or (v not in sentinels and v is not None and v != ""):
                enum_ok += 1
        parts.append((20.0, enum_ok / len(enum_fields)))
    weight = sum(w for w, _ in parts)
    if not weight:
        return 0
    total = sum(w * f for w, f in parts) / weight * 100.0
    return max(0, min(100, int(round(total))))


def quality_band(score0100: int) -> str:
    if score0100 >= SCORE_BAD_GREEN:
        return "green"
    if score0100 >= SCORE_BAD_YELLOW:
        return "yellow"
    return "red"


def quality_text(band: str, score0100: int) -> str:
    if band == "green":
        return f"Qualità AI: ottima ({score0100}/100)"
    if band == "yellow":
        return f"Qualità AI: sufficiente — rivedi i campi ({score0100}/100)"
    return f"Qualità AI: bassa — completa i dati manualmente ({score0100}/100)"
