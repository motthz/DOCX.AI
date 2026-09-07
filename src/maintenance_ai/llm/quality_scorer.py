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


def score(data: Dict[str, Any], schema: Dict[str, Any]) -> int:
    """Rubric 40/20/20/20."""
    if not isinstance(data, dict):
        data = {}
    if not isinstance(schema, dict):
        schema = {}
    props = _properties(schema)
    required = [x for x in _required_names(schema) if x in props]
    optional = [k for k in props if k not in required]

    # 40% required filled
    req_total = max(1, len(required))
    req_ok = 0
    for k in required:
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, str) and (v == "NON_SPECIFICATO" or v.strip() == ""):
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        if isinstance(v, dict) and len(v) == 0:
            continue
        req_ok += 1
    req_score = (req_ok / req_total) * 40.0

    # 20% enum non-sentinel
    enum_fields = [(k, p) for k, p in props.items() if "enum" in p]
    enum_total = max(1, len(enum_fields))
    enum_ok = 0
    for k, p in enum_fields:
        has_s, sentinels = _enum_sentinels(p.get("enum"))
        if not has_s:
            enum_ok += 1
            continue
        v = data.get(k)
        if v in sentinels or v is None or v == "":
            continue
        enum_ok += 1
    enum_score = (enum_ok / enum_total) * 20.0

    # 20% informative string length (>10 chars). Compute over all string values top-level.
    string_fields: List[str] = []
    for k, p in props.items():
        pt = p.get("type")
        if pt == "string":
            string_fields.append(k)
    str_total = max(1, len(string_fields))
    str_frac = 0.0
    for k in string_fields:
        v = data.get(k)
        if isinstance(v, str) and len(v) > 10 and v != "NON_SPECIFICATO":
            str_frac += min(1.0, len(v) / 200.0)
    str_score = (str_frac / str_total) * 20.0

    # 20% optional filled
    opt_total = max(1, len(optional))
    opt_ok = 0
    for k in optional:
        v = data.get(k)
        if v is None:
            continue
        if isinstance(v, str) and (v == "NON_SPECIFICATO" or v.strip() == ""):
            continue
        if isinstance(v, list) and len(v) == 0:
            continue
        if isinstance(v, dict) and len(v) == 0:
            continue
        opt_ok += 1
    opt_score = (opt_ok / opt_total) * 20.0

    total = req_score + enum_score + str_score + opt_score
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
