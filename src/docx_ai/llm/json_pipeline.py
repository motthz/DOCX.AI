"""End-to-end JSON extraction pipeline.

Responsible for:
1. Prompt build
2. LLM call (wraps llama_server or a mock)
3. JSON parse + jsonschema validation
4. One attempt at "repair" of trivial structural issues (trailing commas,
   markdown fences, arrays instead of objects, missing required fields with
   NON_SPECIFICATO defaults, ...)
5. One optional retry with augmented feedback message.
"""

from __future__ import annotations

import json
import logging as _logmod
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import jsonschema

from .prompt_builder import build_extraction_messages
from . import evidence as _ev
from . import quality_scorer as _qs


@dataclass
class ExtractionResult:
    success: bool
    data: Optional[Dict[str, Any]]
    error_message: str = ""
    attempts: int = 0
    raw: Optional[str] = None  # Raw LLM content text of the *final* attempt
    failover_used: str = ""  # backend name used to get a result
    quality_score: int = 0  # 0..100 rubric
    debug_dir: Optional[str] = None  # path to artifact dump (if debug)
    # valori dell'AI tolti/corretti dal controllo dei fatti (fact_guard), leggibili
    corrections: Optional[List[str]] = None
    # frase del testo citata dall'AI per ogni campo (risposta con prova), per la revisione
    evidence: Optional[Dict[str, str]] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "data": self.data,
            "error_message": self.error_message,
            "attempts": self.attempts,
            "failover_used": self.failover_used,
            "quality_score": self.quality_score,
            "debug_dir": self.debug_dir,
        }


ServerLike = Any  # protocol: chat_completions(...) compatible


_NON_SPEC = "NON_SPECIFICATO"


# ---------------------------------------------------------------------------
# Small repair primitives
# ---------------------------------------------------------------------------
def _strip_markdown_fences(text: str) -> str:
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text)
    if fenced:
        return fenced.group(1).strip()
    # Sometimes ```json without closing fence
    m = re.match(r"^```(?:json)?\s*([\s\S]*)$", text)
    if m:
        body = m.group(1)
        return body.rstrip("`").strip()
    return text


def _extract_json_object(text: str) -> Optional[str]:
    # Find first balanced { ... } block
    depth = 0
    start = -1
    in_str = False
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                return text[start: i + 1]
    if start >= 0 and depth > 0:
        # Unterminated - append closing brace
        candidate = text[start:] + "}"
        return candidate
    return None


def _lenient_json_parse(text: str) -> Tuple[Optional[Any], Optional[str]]:
    text = text or ""
    cleaned = _strip_markdown_fences(text)
    # Strip trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
    # Try to grab a JSON object sub-region if whole text isn't JSON
    candidates = [cleaned, _extract_json_object(cleaned)]
    last: Optional[str] = None
    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c), None
        except json.JSONDecodeError as exc:
            last = f"JSONDecodeError: {exc.msg} at line {exc.lineno} col {exc.colno}"
    if not text.strip():
        return None, "Risposta vuota dal modello"
    return None, last or "Impossibile interpretare la risposta come JSON"


def _fill_missing_defaults(data: Dict[str, Any], schema: Dict[str, Any]) -> Dict[str, Any]:
    """Add NON_SPECIFICATO to missing required string fields / empty arrays.

    For boolean fields missing: default False.
    For fields with the wrong type (e.g. LLM returned a string where a bool is
    expected), do a best-effort cast before validation.
    """
    if not isinstance(data, dict):
        return data
    props = schema.get("properties", {}) or {}
    required = schema.get("required", []) or []
    # Copy to avoid mutating caller input
    data = dict(data)

    # ---- First pass: best-effort type cast of existing values ----
    for key, spec in props.items():
        if key not in data:
            continue
        expected = spec.get("type", "string")
        value = data[key]
        if expected == "boolean" and not isinstance(value, bool):
            s = "" if value is None else str(value).strip().lower()
            truthy = {"1", "true", "si", "yes", "on", "x", "conforme", "ok"}
            falsy = {"0", "false", "no", "non", "", "off", "non conforme", "ko", _NON_SPEC.lower()}
            if s in truthy:
                data[key] = True
            elif s in falsy or value is None or s == _NON_SPEC:
                data[key] = False
            else:
                data[key] = bool(value)
        elif expected == "string" and not isinstance(value, str):
            data[key] = _NON_SPEC if value is None else str(value)
        elif isinstance(spec.get("enum"), list) and isinstance(value, str) and value not in spec["enum"]:
            # "approvato" -> "Approvato": stessa opzione scritta diversamente
            norm = value.strip().casefold()
            data[key] = next((e for e in spec["enum"] if str(e).strip().casefold() == norm), value)
        elif expected == "array" and not isinstance(value, list):
            data[key] = []
        elif expected == "object" and not isinstance(value, dict):
            data[key] = {}
        elif (
            (expected == "integer" and (not isinstance(value, int) or isinstance(value, bool)))
            or (expected == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)))
        ):
            try:
                if isinstance(value, str):
                    value = value.strip().replace(" ", "")
                    if "," in value:  # formato italiano: 1.234,50
                        value = value.replace(".", "").replace(",", ".")
                cast = int(float(value)) if expected == "integer" else float(value)
                data[key] = cast
            except (TypeError, ValueError):
                # "NON_SPECIFICATO", "n.d." ... -> numero non indicato
                data[key] = None

    # campi a valore fisso (const): sempre quel valore (con la risposta "con prova" il
    # modello finto dei test non lo conosce; quello vero lo scrive gia' per grammatica)
    for key, spec in props.items():
        if isinstance(spec, dict) and "const" in spec:
            data[key] = spec["const"]

    # ---- Second pass: fill missing required fields with schema-appropriate default ----
    for key in required:
        if key in data:
            continue
        spec = props.get(key, {})
        t = spec.get("type", "string")
        enum = spec.get("enum")
        if t == "boolean":
            data[key] = False
        elif t == "array":
            data[key] = []
        elif t == "object":
            data[key] = {}
        elif t in ("integer", "number"):
            # mai 0: sarebbe un valore inventato. Vuoto, da compilare in revisione
            data[key] = None
        elif enum:
            # mai la prima opzione a caso: il sentinella "non specificato" se c'e'
            data[key] = next((e for e in enum if "non_specificato" in str(e).lower()), _NON_SPEC)
        else:
            data[key] = _NON_SPEC

    # ---- Normalize known sentinel None values (after cast, before nested recursion) ----
    for key, spec in props.items():
        value = data.get(key)
        if value is None:
            t = spec.get("type", "string")
            if t == "boolean":
                data[key] = False
            elif t == "array":
                data[key] = []
            elif t == "object":
                data[key] = {}
            elif t in ("integer", "number") or (isinstance(t, list) and "null" in t):
                pass  # null ammesso (vedi llm_schema): numero non indicato
            else:
                data[key] = _NON_SPEC
        # Handle nested array<object> items: fill missing fields recursively
        if isinstance(value, list) and spec.get("type") == "array":
            items_schema = spec.get("items", {})
            if isinstance(items_schema, dict) and items_schema.get("type") == "object":
                normalized = []
                for item in value:
                    if isinstance(item, dict):
                        normalized.append(_fill_missing_defaults(item, items_schema))
                    else:
                        normalized.append(item)
                data[key] = normalized

    # Strip additionalProperties if schema forbids them
    if schema.get("additionalProperties") is False:
        data = {k: v for k, v in data.items() if k in props}
    return data


# ---------------------------------------------------------------------------
# Artifact dump & disk-cap helpers
# ---------------------------------------------------------------------------

_LLM_DEBUG_CAP_BYTES = 50 * 1024 * 1024  # 50 MB cap for FR38


def _total_dir_bytes(root: Path) -> int:
    total = 0
    try:
        for p in root.rglob("*"):
            if p.is_file():
                try:
                    total += p.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _prune_old_artifacts(debug_root: Path, cap_bytes: int = _LLM_DEBUG_CAP_BYTES) -> None:
    if not debug_root.exists():
        return
    total = _total_dir_bytes(debug_root)
    if total <= cap_bytes:
        return
    # Sort dirs oldest first: each dump is YYYYMMDD-HHMMSS-uuid
    try:
        dirs = sorted([d for d in debug_root.iterdir() if d.is_dir()])
    except OSError:
        return
    for d in dirs:
        if total <= cap_bytes:
            break
        try:
            sz = _total_dir_bytes(d)
            shutil.rmtree(d, ignore_errors=True)
            total -= sz
        except Exception:  # noqa: BLE001
            pass


def _prepare_debug_dump(debug_root: Path) -> Optional[Path]:
    try:
        debug_root.mkdir(parents=True, exist_ok=True)
        _prune_old_artifacts(debug_root)
        stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
        dump_dir = debug_root / stamp
        dump_dir.mkdir(parents=True, exist_ok=True)
        return dump_dir
    except Exception as exc:  # noqa: BLE001
        _logmod.getLogger(__name__).warning(f"Cannot create LLM debug dump dir: {exc}")
        return None


def _write_debug(dump_dir: Optional[Path], name: str, content: Any) -> None:
    if dump_dir is None:
        return
    try:
        path = dump_dir / name
        if isinstance(content, (dict, list)):
            text = json.dumps(content, ensure_ascii=False, indent=2)
        elif isinstance(content, (bytes, bytearray)):
            path.write_bytes(bytes(content))
            return
        else:
            text = "" if content is None else str(content)
        path.write_text(text, encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _relax_props(props: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for key, spec in (props or {}).items():
        if not isinstance(spec, dict):
            out[key] = spec
            continue
        spec = dict(spec)
        t = spec.get("type")
        enum = spec.get("enum")
        if isinstance(enum, list) and enum and not any("specificato" in str(e).lower() for e in enum):
            spec["enum"] = list(enum) + [_NON_SPEC]
        elif t in ("number", "integer"):
            spec["type"] = [t, "null"]
        elif t == "array" and isinstance(spec.get("items"), dict):
            items = dict(spec["items"])
            if items.get("type") == "object" and isinstance(items.get("properties"), dict):
                items["properties"] = _relax_props(items["properties"])
            spec["items"] = items
        out[key] = spec
    return out


def llm_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Schema imposto al modello: come quello del modulo, ma con un'uscita per i dati
    che il testo non contiene. Senza, la grammatica JSON costringeva il modello a
    scegliere comunque un'opzione (la prima) o a scrivere 0 nei campi numerici:
    risposte sbagliate presentate come certe. In revisione questi campi risultano
    vuoti e l'approvazione (validata sullo schema originale) li richiede."""
    if not isinstance(schema, dict) or not isinstance(schema.get("properties"), dict):
        return schema or {}
    out = dict(schema)
    out["properties"] = _relax_props(schema["properties"])
    return out


def prompt_char_budget(server: Any, max_tokens: int) -> int:
    """Caratteri di prompt che entrano nel contesto del modello lasciando spazio
    alla risposta. Prima il prompt (fino a 14000 caratteri) + la risposta potevano
    superare il contesto da 4096 token: llama-server rifiutava la richiesta o
    perdeva l'inizio del prompt."""
    ctx = 0
    opts = getattr(server, "options", None)
    if opts is not None:
        ctx = int(getattr(opts, "context_size", 0) or 0)
    if not ctx:
        ctx = 4096 if type(server).__name__ == "OllamaBackend" else 8192
    tokens = ctx - int(max_tokens) - 256
    # ~2.8 caratteri per token per testo italiano misto a JSON (stima prudente)
    return max(3000, min(40000, int(tokens * 2.8)))


# Peso massimo di un gruppo di campi (un campo semplice pesa 1, un elenco di righe
# 2 + le sue colonne). Un modello piccolo che deve scrivere 20-40 campi in una sola
# risposta ne salta molti; a gruppi di ~8 li compila quasi tutti.
GROUP_WEIGHT = 8
# modelli piccoli (0.6B/1.7B): gruppi piu' piccoli, ogni campo riceve piu' "attenzione"
SMALL_MODEL_GROUP_WEIGHT = 5


def is_small_model(server: Any) -> bool:
    """Modello da 2 miliardi di parametri o meno (Qwen3 0.6B / 1.7B)."""
    import re as _re
    name = ""
    opts = getattr(server, "options", None)
    for attr in ("model_path", "model"):
        val = getattr(opts, attr, None) if opts is not None else None
        if val:
            name = os.path.basename(str(val)).lower()
            break
    m = _re.search(r"(\d+(?:\.\d+)?)\s*b\b", name.replace("-", " ").replace("_", " ").replace(":", " "))
    return m is not None and float(m.group(1)) <= 2.0


def _field_weight(spec: Any) -> int:
    if isinstance(spec, dict) and spec.get("type") == "array":
        items = spec.get("items") or {}
        if isinstance(items, dict) and items.get("type") == "object":
            return 2 + len(items.get("properties") or {})
        return 2
    return 1


def split_schema(schema: Dict[str, Any], max_weight: int = GROUP_WEIGHT) -> List[Dict[str, Any]]:
    """Divide lo schema in gruppi di campi consecutivi (stesso ordine del modulo).

    Gli schemi piccoli restano interi: una sola chiamata. ``max_weight`` <= 0
    disattiva la divisione."""
    props = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(props, dict) or max_weight <= 0:
        return [schema]
    weights = {k: _field_weight(v) for k, v in props.items()}
    if sum(weights.values()) <= max_weight * 3 // 2:
        return [schema]
    groups: List[List[str]] = []
    cur: List[str] = []
    used = 0
    for key, w in weights.items():
        if cur and used + w > max_weight:
            groups.append(cur)
            cur, used = [], 0
        cur.append(key)
        used += w
    if cur:
        groups.append(cur)
    required = list(schema.get("required") or [])
    out: List[Dict[str, Any]] = []
    for keys in groups:
        sub = {k: v for k, v in schema.items() if k not in ("properties", "required")}
        sub["properties"] = {k: props[k] for k in keys}
        sub["required"] = [k for k in required if k in keys]
        out.append(sub)
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class JsonPipeline:
    """JSON extraction pipeline with server failover chain + retry escalation."""

    def __init__(self, server: ServerLike, *, max_retries: int = 3,
                 debug_root: Optional[Path] = None,
                 server_chain: Optional[List[ServerLike]] = None,
                 evidence: bool = True):
        # Legacy single-server argument converted to a chain of 1 element
        self.server_chain: List[ServerLike] = list(server_chain) if server_chain else [server]
        self.max_retries = max(0, int(max_retries))
        self.debug_root = debug_root
        self._do_debug = bool(debug_root)
        self.group_weight: Optional[int] = None  # None = in base al modello
        # risposta con prova per ogni campo (llm/evidence.py)
        self.evidence = bool(evidence)

    # ------------------------------------------------------------------
    def extract(
        self,
        schema: Dict[str, Any],
        operator_description: str,
        *,
        reference_docs: Optional[List[Tuple[str, str]]] = None,
        history_snippets: Optional[List[Dict[str, Any]]] = None,
        extra: Optional[Dict[str, Any]] = None,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
        temperature: Optional[float] = None,
        on_token: Optional[Callable[[str], None]] = None,
        document_context: str = "",
    ) -> ExtractionResult:
        """``temperature``: temperatura del primo tentativo (i retry la alzano un po').
        ``on_token``: se il backend supporta lo streaming riceve il testo generato."""
        logger = _logmod.getLogger(__name__)
        reference_docs = list(reference_docs or [])
        history_snippets = list(history_snippets or [])

        dump_dir = _prepare_debug_dump(self.debug_root) if (self._do_debug and self.debug_root) else None
        _write_debug(dump_dir, "01_schema.json", schema)
        _write_debug(dump_dir, "02_operator.txt", operator_description)
        _write_debug(dump_dir, "03_reference_docs.txt", "\n\n==== DOCUMENTO ====\n".join(
            f"[{n}]\n{c}" for n, c in reference_docs
        ) if reference_docs else "")
        _write_debug(dump_dir, "04_history.json", history_snippets)

        last_error = ""
        total_attempts = 0

        # Iterate BACKEND failover chain (primary 1.7B → fallback 0.6B → mock)
        for server_index, server in enumerate(self.server_chain):
            server_name = self._backend_name(server)
            weight = self.group_weight
            if weight is None:
                weight = SMALL_MODEL_GROUP_WEIGHT if is_small_model(server) else GROUP_WEIGHT
            groups = split_schema(schema, weight)
            chunked = len(groups) > 1
            if on_progress:
                on_progress(0, len(groups), f"Backend {server_index+1}/{len(self.server_chain)}: {server_name}")
            # stesso budget per tutti i gruppi: prompt identico salvo l'elenco dei campi
            # finale, cosi' llama-server rielabora solo quello (cache del prompt)
            max_tokens = max(self._estimate_max_tokens(g, server, evidence=self.evidence) for g in groups)
            budget = prompt_char_budget(server, max_tokens)
            merged: Dict[str, Any] = {}
            proofs: Dict[str, Optional[str]] = {}
            raws: List[str] = []
            failed: List[str] = []
            for gi, group in enumerate(groups):
                if on_progress and chunked:
                    on_progress(gi + 1, len(groups), f"{server_name}: gruppo di campi {gi+1}/{len(groups)}")
                if on_token is not None and chunked and gi:
                    on_token("\n")
                data, raw, err, attempts, group_proofs = self._extract_group(
                    server, server_name, schema, group, operator_description,
                    reference_docs=reference_docs, history_snippets=history_snippets,
                    document_context=document_context, budget=budget, temperature=temperature,
                    on_token=on_token, extra=extra, dump_dir=dump_dir,
                    tag=f"{server_index}_{gi}", chunked=chunked)
                total_attempts += attempts
                if data is None:
                    last_error = err
                    failed += list(group["properties"])
                    continue
                merged.update(data)
                proofs.update(group_proofs)
                raws.append(raw or "")
            if not raws:  # nessun gruppo riuscito
                logger.warning(f"[{server_name}] Esauriti tutti i tentativi — passo al fallback successivo.")
                continue

            notes: List[str] = []
            if failed:
                # un gruppo non riuscito non butta via gli altri: i suoi campi restano
                # vuoti e vanno completati in revisione
                props = schema.get("properties") or {}
                names = [str((props.get(k) or {}).get("title") or k) for k in failed]
                notes.append("L'AI non ha compilato questi campi (da completare in revisione): "
                             + ", ".join(names))
                logger.warning(f"[{server_name}] campi non compilati: {failed} ({last_error})")
            repaired = _fill_missing_defaults(merged, schema)
            raw = "\n".join(raws)
            sources = [operator_description] + [t for _n, t in reference_docs]

            # Prove citate dall'AI: Sì/No e scelte senza una frase che le confermi, testi
            # senza riscontro e caselle Sì/No incoerenti vengono tolti (llm/evidence.py)
            repaired, ev_fixes = _ev.apply(repaired, proofs, schema, sources)
            # Controllo deterministico: date, numeri, codici e nomi devono avere
            # riscontro nel testo dell'utente o nei documenti (non nello storico);
            # i campi data vuoti ricevono la data del testo che si riferisce a loro.
            from .fact_guard import verify as _verify_facts
            repaired, fixes = _verify_facts(repaired, schema, sources)
            all_fixes: List[Any] = list(ev_fixes) + list(fixes)
            _write_debug(dump_dir, "97_evidence.json", proofs)
            _write_debug(dump_dir, "98_fact_guard.json", [c.describe() for c in all_fixes])
            quality = _qs.score(repaired, schema)
            _write_debug(dump_dir, "99_final_validated.json", repaired)
            _write_debug(dump_dir, "99_meta.json", {
                "server": server_name,
                "server_index": server_index,
                "groups": len(groups),
                "failed_fields": failed,
                "total_attempts": total_attempts,
                "quality": quality,
            })
            return ExtractionResult(
                success=True,
                data=repaired,
                error_message="",
                attempts=total_attempts,
                raw=raw,
                failover_used=server_name,
                quality_score=quality,
                debug_dir=str(dump_dir) if dump_dir else None,
                corrections=notes + [c.describe() for c in all_fixes],
                evidence={k: v for k, v in proofs.items() if v},
            )

        # End of chain: all backends failed
        return ExtractionResult(
            success=False,
            data=None,
            error_message=last_error or "Fallimento dopo tutti i tentativi e tutti i fallback",
            attempts=total_attempts,
            raw=None,
            failover_used="none",
            quality_score=0,
            debug_dir=str(dump_dir) if dump_dir else None,
        )

    def _extract_group(
        self,
        server: ServerLike,
        server_name: str,
        schema: Dict[str, Any],
        group: Dict[str, Any],
        operator_description: str,
        *,
        reference_docs: List[Tuple[str, str]],
        history_snippets: List[Dict[str, Any]],
        document_context: str,
        budget: int,
        temperature: Optional[float],
        on_token: Optional[Callable[[str], None]],
        extra: Optional[Dict[str, Any]],
        dump_dir: Optional[Path],
        tag: str,
        chunked: bool,
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str], str, int, Dict[str, Optional[str]]]:
        """Un gruppo di campi con i suoi tentativi: (dati, testo grezzo, errore, tentativi, prove).

        Il prompt descrive sempre lo schema completo (il modello sa dove va ogni
        informazione); la grammatica JSON impone solo i campi del gruppo."""
        logger = _logmod.getLogger(__name__)
        focus = list(group.get("properties") or {}) if chunked else None
        max_tokens = self._estimate_max_tokens(group, server, evidence=self.evidence)
        messages = build_extraction_messages(
            schema,
            operator_description,
            reference_docs=reference_docs,
            history_snippets=history_snippets,
            document_context=document_context,
            max_prompt_chars=budget,
            focus_fields=focus,
            evidence=self.evidence,
        )
        value_schema = llm_schema(group)
        model_schema = _ev.wrap_schema(value_schema) if self.evidence else value_schema
        group_props = group.get("properties") or {}
        last_error = ""

        # Retry escalation WITHIN this backend (attempts 0..max_retries)
        for attempt in range(self.max_retries + 1):
            use_messages = list(messages)
            # attempt 2 -> meta' dei documenti e dello storico (prompt piu' corto).
            # Lo schema resta completo: togliere i campi facoltativi li perdeva.
            if attempt == 2 and (len(reference_docs) > 1 or history_snippets):
                use_messages = build_extraction_messages(
                    schema,
                    operator_description,
                    reference_docs=reference_docs[: max(1, (len(reference_docs) + 1) // 2)],
                    history_snippets=history_snippets[: len(history_snippets) // 2],
                    document_context=document_context,
                    max_prompt_chars=budget,
                    focus_fields=focus,
                    evidence=self.evidence,
                )
                if last_error:
                    use_messages = self._append_repair_messages(use_messages, "", last_error)

            base_t = 0.05 if temperature is None else max(0.0, float(temperature))
            temp = base_t if attempt == 0 else base_t + 0.1 if attempt == 1 else base_t + 0.15
            try:
                stream_fn = getattr(server, "chat_completions_stream", None)
                if on_token is not None and stream_fn is not None:
                    if attempt:
                        on_token("\n\n— nuovo tentativo —\n")
                    resp = stream_fn(
                        use_messages, on_delta=on_token, temperature=temp,
                        max_tokens=max_tokens, json_schema=model_schema, extra=extra)
                else:
                    resp = server.chat_completions(
                        messages=use_messages,
                        temperature=temp,
                        max_tokens=max_tokens,
                        json_schema=model_schema,
                        extra=extra,
                    )
            except Exception as exc:  # noqa: BLE001
                last_error = f"[{server_name}] Chiamata LLM fallita (tentativo {attempt+1}): {exc}"
                logger.warning(last_error)
                _write_debug(dump_dir, f"{tag}_{attempt}_0_call_error.txt", str(exc))
                continue

            choices = resp.get("choices") or []
            if not choices:
                last_error = f"[{server_name}] Risposta LLM vuota (choices=[])"
                continue
            raw = (choices[0].get("message") or {}).get("content", "")
            _write_debug(dump_dir, f"{tag}_{attempt}_1_raw.txt", raw)
            parsed, err = _lenient_json_parse(raw)
            if parsed is None:
                last_error = f"[{server_name}] Parsing JSON fallito: {err}"
                messages = self._append_repair_messages(messages, raw, last_error)
                _write_debug(dump_dir, f"{tag}_{attempt}_2_parse_error.txt", str(err))
                continue
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
            proofs: Dict[str, Optional[str]] = {}
            if self.evidence:
                parsed, proofs = _ev.unwrap(parsed, group_props)
            repaired = _fill_missing_defaults(parsed, group)
            _write_debug(dump_dir, f"{tag}_{attempt}_3_parsed.json", repaired)
            try:
                jsonschema.validate(repaired, value_schema)
            except jsonschema.ValidationError as exc:
                last_error = (
                    f"[{server_name}] Schema validation fallito: {exc.message} "
                    f"(path: {list(exc.absolute_path)})"
                )
                messages = self._append_repair_messages(messages, raw, last_error)
                _write_debug(dump_dir, f"{tag}_{attempt}_4_validation_error.txt", str(exc))
                continue
            return repaired, raw, "", attempt + 1, proofs
        return None, None, last_error, self.max_retries + 1, {}

    # ------------------------------------------------------------------
    @property
    def server(self) -> ServerLike:
        """Primo backend della catena (compatibilita' con il codice esistente)."""
        return self.server_chain[0]

    def chat(self, messages: List[Dict[str, Any]], **kwargs: Any) -> Dict[str, Any]:
        """chat_completions con failover sulla catena di backend (testo libero).

        ``on_delta`` (opzionale) attiva lo streaming dove supportato."""
        on_delta = kwargs.pop("on_delta", None)
        last: Optional[BaseException] = None
        for server in self.server_chain:
            try:
                stream_fn = getattr(server, "chat_completions_stream", None)
                if on_delta is not None and stream_fn is not None:
                    return stream_fn(messages, on_delta=on_delta, **kwargs)
                return server.chat_completions(messages=messages, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last = exc
                _logmod.getLogger(__name__).warning("Backend %s fallito: %s", self._backend_name(server), exc)
        raise RuntimeError(f"Nessun backend AI disponibile: {last}")

    @staticmethod
    def _backend_name(server: ServerLike) -> str:
        cls = type(server).__name__
        try:
            if cls == "LlamaServer":
                model_name = str(getattr(server.options, "model_path", ""))
                return f"Llama({os.path.basename(model_name) or 'default'})"
            if cls == "OllamaBackend":
                return f"Ollama({getattr(server.options, 'model', '')})"
        except Exception:  # noqa: BLE001
            pass
        return cls

    @staticmethod
    def _estimate_max_tokens(schema: Dict[str, Any], server: Any = None, *, evidence: bool = False) -> int:
        """Very rough estimate of required tokens based on field count, capped to
        half of the model context (the rest is for the prompt)."""
        props = schema.get("properties", {}) or {}
        field_count = len(props)
        for spec in props.values():
            if isinstance(spec, dict) and spec.get("type") == "array":
                items = spec.get("items") or {}
                if isinstance(items, dict) and items.get("type") == "object":
                    field_count += len(items.get("properties", {}) or {}) * 3
        # la frase citata come prova: ~50 token per campo
        estimate = max(500, min(3600, 400 + field_count * 100 + (len(props) * 55 if evidence else 0)))
        ctx = int(getattr(getattr(server, "options", None), "context_size", 0) or 0)
        if ctx:
            estimate = min(estimate, max(400, ctx // 2))
        return estimate

    @staticmethod
    def _append_repair_messages(messages: List[Dict[str, str]],
                                raw_last: str,
                                error: str) -> List[Dict[str, str]]:
        last_user = messages[-1]["content"] if messages and messages[-1]["role"] == "user" else ""
        tail = (
            f"\n\n---- TENTATIVO PRECEDENTE FALLITO ----\n"
            f"Il tuo ultimo output (troncato):\n{(raw_last or '')[:600]}\n\n"
            f"Errore ricevuto:\n{error}\n\n"
            f"RIPRODUCI ESCLUSIVAMENTE l'oggetto JSON VALIDO e conforme allo schema, "
            f"correggendo il problema sopra indicato. Nessun testo fuori dall'oggetto JSON.\n"
            f"/no_think"
        )
        new_messages = list(messages)
        if new_messages and new_messages[-1]["role"] == "user":
            new_messages[-1] = {"role": "user", "content": last_user + tail}
        else:
            new_messages.append({"role": "user", "content": tail.strip()})
        return new_messages
