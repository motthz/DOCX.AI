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

import copy
import json
import logging as _logmod
import os
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import jsonschema

from .llama_server import LlamaServer, MockLlamaServer
from .prompt_builder import build_extraction_messages
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
    for c in candidates:
        if not c:
            continue
        try:
            return json.loads(c), None
        except json.JSONDecodeError as exc:
            last = f"JSONDecodeError: {exc.msg} at line {exc.lineno} col {exc.colno}"
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
        elif expected == "array" and not isinstance(value, list):
            data[key] = []
        elif expected == "object" and not isinstance(value, dict):
            data[key] = {}
        elif expected == "integer" and not isinstance(value, int) or (
            expected == "number" and not isinstance(value, (int, float))
        ):
            try:
                cast = int(value) if expected == "integer" else float(value)
                data[key] = cast
            except (TypeError, ValueError):
                # Leave as-is; validation will fail and trigger a repair retry
                pass

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
            data[key] = 0 if t == "integer" else 0.0
        elif enum:
            pick = next((e for e in enum if "non_specificato" in str(e).lower()), enum[0])
            data[key] = pick
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


def _required_only_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Strip optional properties for retry-3 "required only" schema."""
    if not isinstance(schema, dict):
        return schema or {}
    props = schema.get("properties") or {}
    req = schema.get("required") or []
    trimmed_props = {k: v for k, v in props.items() if k in req}
    out = dict(schema)
    out["properties"] = trimmed_props
    out["required"] = list(req)
    if "additionalProperties" not in out:
        out["additionalProperties"] = False
    return out


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
class JsonPipeline:
    """JSON extraction pipeline with server failover chain + retry escalation."""

    def __init__(self, server: ServerLike, *, max_retries: int = 3,
                 debug_root: Optional[Path] = None,
                 server_chain: Optional[List[ServerLike]] = None):
        # Legacy single-server argument converted to a chain of 1 element
        self.server_chain: List[ServerLike] = list(server_chain) if server_chain else [server]
        self.max_retries = max(0, int(max_retries))
        self.debug_root = debug_root
        self._do_debug = bool(debug_root)

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
    ) -> ExtractionResult:
        logger = _logmod.getLogger(__name__)
        reference_docs = list(reference_docs or [])
        history_snippets = list(history_snippets or [])

        dump_dir = _prepare_debug_dump(self.debug_root) if self._do_debug else None
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
            if on_progress:
                on_progress(0, 3, f"Backend {server_index+1}/{len(self.server_chain)}: {server_name}")

            # Build base messages for THIS backend (reset per backend)
            messages = build_extraction_messages(
                schema,
                operator_description,
                reference_docs=reference_docs,
                history_snippets=history_snippets,
                append_no_think=not isinstance(server, MockLlamaServer) or True,
            )
            max_tokens = self._estimate_max_tokens(schema)

            # Retry escalation WITHIN this backend (attempts 0..max_retries)
            for attempt in range(self.max_retries + 1):
                total_attempts += 1
                if on_progress:
                    on_progress(attempt + 1, self.max_retries + 1,
                                f"{server_name} tentativo {attempt+1}/{self.max_retries+1}")

                # --- Prepare schema/references per RETRY escalation ---
                use_schema = schema
                use_messages = list(messages)
                use_refs = reference_docs
                # attempt 0 → default; attempt 1 → prepend repair if available;
                # attempt 2 → strip 50% references + required-only schema (FR33)
                if attempt == 2:
                    # strip every other doc (retain first, skip 50% historical)
                    if len(use_refs) > 1:
                        half = use_refs[: max(1, (len(use_refs) + 1) // 2)]
                        use_refs = half
                    use_schema = _required_only_schema(schema)
                    use_messages = build_extraction_messages(
                        use_schema,
                        operator_description,
                        reference_docs=use_refs,
                        history_snippets=history_snippets[: max(0, len(history_snippets) // 2)],
                        append_no_think=not isinstance(server, MockLlamaServer) or True,
                    )
                    if last_error:
                        use_messages = self._append_repair_messages(use_messages, "", last_error)

                temp = 0.05 if attempt == 0 else 0.15 if attempt == 1 else 0.2
                try:
                    resp = server.chat_completions(
                        messages=use_messages,
                        temperature=temp,
                        max_tokens=max_tokens,
                        json_schema=use_schema,
                        extra=extra,
                    )
                except Exception as exc:  # noqa: BLE001
                    last_error = f"[{server_name}] Chiamata LLM fallita (tentativo {attempt+1}): {exc}"
                    logger.warning(last_error)
                    _write_debug(dump_dir, f"{server_index}_{attempt}_0_call_error.txt", str(exc))
                    continue

                choices = resp.get("choices") or []
                if not choices:
                    last_error = f"[{server_name}] Risposta LLM vuota (choices=[])"
                    continue
                raw = (choices[0].get("message") or {}).get("content", "")
                _write_debug(dump_dir, f"{server_index}_{attempt}_1_raw.txt", raw)
                parsed, err = _lenient_json_parse(raw)
                if parsed is None:
                    last_error = f"[{server_name}] Parsing JSON fallito: {err}"
                    messages = self._append_repair_messages(messages, raw, last_error)
                    _write_debug(dump_dir, f"{server_index}_{attempt}_2_parse_error.txt", str(err))
                    continue
                if not isinstance(parsed, dict):
                    parsed = {"value": parsed}
                repaired = _fill_missing_defaults(parsed, schema)
                _write_debug(dump_dir, f"{server_index}_{attempt}_3_parsed.json", repaired)
                try:
                    jsonschema.validate(repaired, schema)
                except jsonschema.ValidationError as exc:
                    last_error = (
                        f"[{server_name}] Schema validation fallito: {exc.message} "
                        f"(path: {list(exc.absolute_path)})"
                    )
                    messages = self._append_repair_messages(messages, raw, last_error)
                    _write_debug(dump_dir, f"{server_index}_{attempt}_4_validation_error.txt", str(exc))
                    continue

                quality = _qs.score(repaired, schema)
                _write_debug(dump_dir, "99_final_validated.json", repaired)
                _write_debug(dump_dir, "99_meta.json", {
                    "server": server_name,
                    "server_index": server_index,
                    "attempt_in_server": attempt + 1,
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
                )
            # End of retry loop for this backend: fall back to next in chain
            logger.warning(f"[{server_name}] Esauriti tutti i tentativi — passo al fallback successivo.")

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

    # ------------------------------------------------------------------
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
    def _estimate_max_tokens(schema: Dict[str, Any]) -> int:
        """Very rough estimate of required tokens based on field count."""
        props = schema.get("properties", {}) or {}
        field_count = len(props)
        for spec in props.values():
            if isinstance(spec, dict) and spec.get("type") == "array":
                items = spec.get("items") or {}
                if isinstance(items, dict) and items.get("type") == "object":
                    field_count += len(items.get("properties", {}) or {}) * 3
        return max(500, min(3200, 400 + field_count * 100))

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
