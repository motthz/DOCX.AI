"""AIService: wrapper unificato per tutte le chiamate LLM.

Integra:
- Regole interne software (costante, non modificabile)
- Regole feature (RulesManager, file .txt)
- Regole modulo (RulesManager, file .txt)
- Richiesta utente + documenti di contesto + storico
- JsonPipeline esistente per parsing/validazione JSON
- Log operazioni su DB ai_operations
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config
from ..db import Database
from ..llm.json_pipeline import ExtractionResult, JsonPipeline
from ..llm.llama_server import LlamaServer, LlamaServerOptions, MockLlamaServer
from ..llm.ollama_backend import OllamaBackend, OllamaBackendOptions
from ..llm.prompt_builder import (
    SYSTEM_POLICY as EXTRACTION_POLICY,
    _schema_semantics,
    _truncate,
)
from ..services.context_service import ContextService
from ..module_manager import LoadedModule
from .document_retriever import RetrievedChunk
from .rules_manager import RulesManager
from .source_tracker import SourceRef


LOG = logging.getLogger(__name__)


# ------------------------------------------------------------------
# Regole INTERNE del software. Non modificabili dall'utente.
# Ogni feature può specificarne un sottoinsieme + il principio comune.
# ------------------------------------------------------------------
INTERNAL_SOFTWARE_RULES: Dict[str, str] = {
    "base": """PRINCIPI GENERICI DEL SOFTWARE (NON MODIFICABILI):
1. Non inventare MAI date, nomi, codici, numeri, quantità, valori, procedure o persone.
2. Se un'informazione non è disponibile nei documenti di contesto o nel testo dell'utente, usa [DA DEFINIRE] (o NON_SPECIFICATO per i campi JSON).
3. Non trasformare una possibilità ("potrebbe", "dovrebbe") in un fatto certo.
4. Cita SEMPRE la fonte quando l'AI produce testo strutturato.
5. Non modificare o "migliorare" arbitrariamente testo, firme, approvazioni.
6. Preserva la formattazione quando possibile. Avverti se non puoi.
7. Documenti di riferimento = contesto e istruzioni, NON prove di attività eseguite.
8. Storico = forma e terminologia, NON fatti da copiare.
9. Quando valori da fonti diverse sono in conflitto: NON scegliere. Segnala entrambi.
10. L'output non è definitivo: deve essere revisionato dall'utente.
""",
    "document_creation": """REGOLE SPECIFICHE CREAZIONE DOCUMENTO:
- Riprendi terminologia, struttura, stili e intestazioni dai documenti di riferimento.
- Non inventare codici documento, versioni, responsabili, frequenze, liste di controllo.
- Indica sempre [DA DEFINIRE] nelle sezioni in cui non ci sono informazioni sufficienti.
- Cita esplicitamente da quale documento di riferimento hai ripreso una struttura o una frase.
- Non copiare interi documenti: componi solo le parti pertinenti alla richiesta.
- Produci un testo strutturato con titoli, paragrafi, tabelle e passaggi ordinati.
""",
    "document_edit": """REGOLE SPECIFICHE MODIFICA DOCUMENTO:
- Modifica SOLAMENTE le parti esplicitamente richieste.
- Non riformattare, riorganizzare o riscrivere arbitrariamente parti non toccate.
- Se la formattazione non può essere preservata perfettamente, scrivi un avvertimento.
- Produci una NUOVA versione; l'originale non viene mai sovrascritto.
""",
    "document_audit": """REGOLE SPECIFICHE AUDIT DOCUMENTI:
- Agisci come auditor molto scrupoloso. Cerca attivamente anomalie.
- Non dichiarare "non conformità certa" senza prove sufficienti.
- Usa formule prudenziali: "Possibile criticità", "Da verificare", "Informazioni insufficienti".
- Per ogni criticità riporta SEMPRE: titolo, gravità, descrizione, file interessati, pagina/foglio/cella/sezione, evidenza (estratto), motivo della segnalazione, suggerimento di verifica.
- Non riassumere: cerca contraddizioni, dati mancanti, riferimenti inesistenti, date impossibili, versioni incompatibili, catene di tracciabilità interrotte.
""",
    "smart_fill": """REGOLE SPECIFICHE COMPILAZIONE SMART:
- Compila un campo SOLO se esiste evidenza testuale esplicita in almeno un documento.
- Non dedurre da pattern, esempi, o dati storici.
- Se due fonti riportano valori diversi NON scegliere: segnala "Conflitto rilevato" + entrambe le alternative + relative fonti.
- Lascia vuoto o inserisci [DA COMPILARE] in assenza di fonti.
- Per ogni valore prodotto, elenca la fonte (file, pagina, foglio, cella, sezione, estratto).
""",
    "report_compilation": """REGOLE SPECIFICHE REPORTISTICA (esistente):
- Vedi EXTRACTION_POLICY.
- Estrazione strutturata JSON. NON testo libero.
""",
}


@dataclass
class AIResult:
    """Wrapper unificato risultato generico AI."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    error: str = ""
    attempts: int = 0
    raw_text: str = ""
    # Free-text output (for document generation / modification / audit markdown)
    text_output: str = ""
    # References collected from context (for display in UI)
    sources_used: List[SourceRef] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.sources_used is None:
            self.sources_used = []


class AIService:
    def __init__(
        self,
        config: Config,
        db: Database,
        rules: RulesManager,
        *,
        context: Optional[ContextService] = None,
        mock: bool = False,
    ):
        self.config = config
        self.db = db
        self.rules = rules
        self.context = context
        self._pipeline: Optional[JsonPipeline] = None
        self._server_chain: List[Any] = []  # all non-mock servers we started
        self._mock = mock

    # --------------------------------------------------------------
    # LLM pipeline: lazy-init + failover chain + debug artifacts
    # --------------------------------------------------------------
    def pipeline(self, *, use_mock: Optional[bool] = None) -> JsonPipeline:
        if use_mock is None:
            use_mock = self._mock
        if use_mock:
            return JsonPipeline(MockLlamaServer(), max_retries=1)
        if self._pipeline is not None:
            return self._pipeline
        eff = self.config.llm_effective
        chain: List[Any] = []
        max_retries = max(0, int(eff.get("max_retries", 3)))
        backend = str(eff.get("backend", "llama_server")).lower()

        # 1) Primary backend di config (ollama or llama primary model)
        if backend == "ollama":
            o_opts = OllamaBackendOptions(
                url=str(eff.get("ollama_url", "http://127.0.0.1:11434")),
                model=str(eff.get("ollama_model", "qwen3:0.6b-instruct-q8_0")),
            )
            ollama_srv = OllamaBackend(o_opts)
            try:
                ollama_srv.start(timeout=5.0)
                chain.append(ollama_srv)
                self._server_chain.append(ollama_srv)
            except Exception as exc:  # noqa: BLE001
                LOG.warning(f"Ollama backend non disponibile (procedo con fallback): {exc}")

        # 2) Llama primary (sempre tentiamo come primary o fallback)
        primary_model_path = self.config.resolve_app_path(eff["model"]) if eff.get("model") else None
        if primary_model_path and primary_model_path.exists():
            try:
                opts = LlamaServerOptions(
                    runtime_dir=self.config.resolve_app_path(eff["runtime_dir"]),
                    runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
                    model_path=primary_model_path,
                    context_size=int(eff.get("context_size", 4096)),
                    host=eff.get("host", "127.0.0.1"),
                    port_min=int(eff.get("port_min", 39280)),
                    port_max=int(eff.get("port_max", 39299)),
                    no_webui=bool(eff.get("no_webui", True)),
                    no_think=bool(eff.get("no_think", True)),
                    thread_override=eff.get("thread_override"),
                )
                primary = LlamaServer(opts)
                primary.start()
                chain.append(primary)
                self._server_chain.append(primary)
            except Exception as exc:  # noqa: BLE001
                LOG.warning(f"Llama primary non disponibile: {exc}")

        # 3) Llama fallback (0.6B)
        fallback_model_path = None
        if eff.get("fallback_model"):
            fallback_model_path = self.config.resolve_app_path(eff["fallback_model"])
        if fallback_model_path and fallback_model_path.exists():
            try:
                fb_opts = LlamaServerOptions(
                    runtime_dir=self.config.resolve_app_path(eff["runtime_dir"]),
                    runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
                    model_path=fallback_model_path,
                    context_size=max(512, int(int(eff.get("context_size", 4096)) // 2)),
                    host=eff.get("host", "127.0.0.1"),
                    port_min=int(eff.get("port_min", 39280)),
                    port_max=int(eff.get("port_max", 39299)),
                    no_webui=bool(eff.get("no_webui", True)),
                    no_think=bool(eff.get("no_think", True)),
                    thread_override=eff.get("thread_override"),
                )
                fb = LlamaServer(fb_opts)
                fb.start()
                chain.append(fb)
                self._server_chain.append(fb)
            except Exception as exc:  # noqa: BLE001
                LOG.warning(f"Llama fallback non disponibile: {exc}")

        # 4) Mock deterministico always-on fallback (per sicurezza)
        chain.append(MockLlamaServer())

        # Debug dump root
        debug_root = None
        if bool(eff.get("debug", False)):
            debug_root = self.config.logs_root() / "llm_debug"

        # First chain server is "mock only" → use single server constructor (legacy)
        if len(chain) == 1:
            self._pipeline = JsonPipeline(chain[0], max_retries=max_retries, debug_root=debug_root)
        else:
            self._pipeline = JsonPipeline(chain[0], max_retries=max_retries, debug_root=debug_root,
                                          server_chain=chain)
        return self._pipeline

    def shutdown(self) -> None:
        excs: List[str] = []
        chain = self._server_chain or []
        for srv in reversed(chain):
            try:
                srv.stop()
            except Exception as exc:  # noqa: BLE001
                excs.append(str(exc))
        if excs:
            LOG.warning(f"Errori durante stop LLM: {excs}")
        self._server_chain = []
        self._pipeline = None

    # --------------------------------------------------------------
    # Log operation to DB
    # --------------------------------------------------------------
    def _log_op(self, feature: str, operation: str, files: List[str],
                sources: List[str], outcome: str, error: str = "") -> int:
        try:
            return self.db.log_ai_operation(
                feature=feature,
                operation=operation[:5000],
                files_json=json.dumps(files, ensure_ascii=False)[:20000],
                sources_json=json.dumps(sources, ensure_ascii=False)[:20000],
                model=Path(self.config.llm_effective.get("model", "")).name,
                outcome=outcome,
                error=error[:5000],
            )
        except Exception as exc:  # noqa: BLE001
            LOG.warning("log ai operation fallito: %s", exc)
            return 0

    # --------------------------------------------------------------
    # 1) JSON extraction (usato da Smart Fill + report esistente)
    # --------------------------------------------------------------
    def extract_structured(
        self,
        feature_key: str,
        schema: Dict[str, Any],
        user_request: str,
        *,
        module: Optional[LoadedModule] = None,
        retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        reference_docs: Optional[List[Tuple[str, str]]] = None,
        history_snippets: Optional[List[Dict[str, Any]]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        use_mock: Optional[bool] = None,
    ) -> AIResult:
        module_folder = module.folder_path if module is not None else None
        internal_block = (
            INTERNAL_SOFTWARE_RULES["base"] + "\n" +
            INTERNAL_SOFTWARE_RULES.get(feature_key, "")
        )
        combined = self.rules.get_combined_rules(
            feature_key, module_folder, internal_rules=internal_block
        )
        system_text = (
            combined.all_text() + "\n\n"
            + EXTRACTION_POLICY + "\n"
            + _schema_semantics(schema)
        )
        user_parts: List[str] = []
        if retrieved_chunks:
            user_parts.append("=== BRANI PIÙ PERTINENTI DEI DOCUMENTI (fonti) ===")
            srcs_used: List[SourceRef] = []
            for idx, rc in enumerate(retrieved_chunks, 1):
                fname = rc.file_path.name
                ref = SourceRef(
                    file_name=fname,
                    file_path=rc.file_path,
                    file_sha256=rc.file_sha256,
                    page=rc.chunk.page,
                    sheet=rc.chunk.sheet,
                    cell=rc.chunk.cell_ref,
                    paragraph_index=rc.chunk.paragraph_index,
                    excerpt=_truncate(rc.text, 600, fname),
                    source_kind=rc.chunk.span_source_kind or "native",
                )
                srcs_used.append(ref)
                loc = []
                if ref.page is not None:
                    loc.append(f"pagina={ref.page+1}")
                if ref.sheet:
                    loc.append(f"foglio={ref.sheet}")
                if ref.cell:
                    loc.append(f"cella={ref.cell}")
                loc_str = " ".join(loc)
                user_parts.append(f"--- Fonte #{idx}: {fname} {loc_str} ---\n{ref.excerpt}")
        if reference_docs:
            user_parts.append("=== DOCUMENTI AGGIUNTIVI ===")
            for fname, text in reference_docs:
                user_parts.append(f"--- {fname} ---\n{_truncate(text, 4000, fname)}")
        if history_snippets:
            user_parts.append("=== ESEMPI STORICI (solo forma) ===")
            for snip in history_snippets[:4]:
                inp = snip.get("input", "")
                out = snip.get("final_json") or ""
                if isinstance(out, dict):
                    out = json.dumps(out, ensure_ascii=False)
                user_parts.append(f"I: {inp}\nO: {_truncate(str(out), 1500, 'esempio')}")
        user_parts.append("=== RICHIESTA UTENTE ===")
        user_parts.append(user_request or "(nessuna)")
        user_parts.append(
            "\nRestituisci ESCLUSIVAMENTE un JSON valido conforme allo schema. "
            "Nessun testo fuori dall'oggetto JSON."
        )
        user_parts.append("\n/no_think")
        user_text = "\n\n".join(user_parts)

        pipeline = self.pipeline(use_mock=use_mock)
        # Direct call (bypass build_extraction_messages because we built a custom system)
        messages = [
            {"role": "system", "content": system_text},
            {"role": "user", "content": user_text},
        ]
        extraction = pipeline.extract(
            schema,
            "",  # operator_description is already in user_text
            reference_docs=None,
            history_snippets=None,
            extra={"_custom_messages": messages} if False else None,
        )
        # Patch pipeline.extract con chiamata diretta se extra non supporta custom messages:
        if extraction.attempts == 0 or not extraction.success and not extraction.raw:
            # Fallback: direct chat
            extraction = self._direct_structured_call(
                pipeline, schema, messages
            )
        files_list = []
        sources_list = []
        if retrieved_chunks:
            for rc in retrieved_chunks:
                if str(rc.file_path) not in files_list:
                    files_list.append(str(rc.file_path))
            for s in srcs_used:
                sources_list.append(s.to_display())
        outcome = "success" if extraction.success else "error"
        self._log_op(feature_key, user_request, files_list, sources_list,
                     outcome, extraction.error_message)
        return AIResult(
            success=extraction.success,
            data=extraction.data,
            error=extraction.error_message,
            attempts=extraction.attempts,
            raw_text=extraction.raw or "",
            sources_used=srcs_used if retrieved_chunks else [],
        )

    # --------------------------------------------------------------
    # 2) Free-text generation (Creazione / Modifica / Audit testuali)
    # --------------------------------------------------------------
    def generate_free_text(
        self,
        feature_key: str,
        user_request: str,
        *,
        output_schema_hints: Optional[Dict[str, Any]] = None,
        module: Optional[LoadedModule] = None,
        retrieved_chunks: Optional[List[RetrievedChunk]] = None,
        reference_docs: Optional[List[Tuple[str, str]]] = None,
        extra_instructions: str = "",
        max_tokens: int = 2500,
        use_mock: Optional[bool] = None,
    ) -> AIResult:
        module_folder = module.folder_path if module is not None else None
        internal_block = (
            INTERNAL_SOFTWARE_RULES["base"] + "\n" +
            INTERNAL_SOFTWARE_RULES.get(feature_key, "")
        )
        combined = self.rules.get_combined_rules(
            feature_key, module_folder, internal_rules=internal_block
        )
        system_text = combined.all_text() + "\n\n" + (extra_instructions or "")
        if output_schema_hints:
            system_text += "\n\n" + _schema_semantics(output_schema_hints)
        user_parts: List[str] = []
        srcs_used: List[SourceRef] = []
        if retrieved_chunks:
            user_parts.append("=== BRANI PIÙ PERTINENTI (fonti) ===")
            for idx, rc in enumerate(retrieved_chunks, 1):
                fname = rc.file_path.name
                ref = SourceRef(
                    file_name=fname, file_path=rc.file_path,
                    file_sha256=rc.file_sha256,
                    page=rc.chunk.page, sheet=rc.chunk.sheet, cell=rc.chunk.cell_ref,
                    paragraph_index=rc.chunk.paragraph_index,
                    excerpt=_truncate(rc.text, 800, fname),
                    source_kind=rc.chunk.span_source_kind or "native",
                )
                srcs_used.append(ref)
                loc = []
                if ref.page is not None:
                    loc.append(f"pagina={ref.page+1}")
                if ref.sheet:
                    loc.append(f"foglio={ref.sheet}")
                if ref.cell:
                    loc.append(f"cella={ref.cell}")
                loc_str = " ".join(loc)
                user_parts.append(f"--- Fonte #{idx}: {fname} {loc_str} ---\n{ref.excerpt}")
        if reference_docs:
            user_parts.append("=== DOCUMENTI RIFERIMENTO ===")
            for fname, text in reference_docs:
                user_parts.append(f"--- {fname} ---\n{_truncate(text, 3000, fname)}")
        user_parts.append("=== RICHIESTA UTENTE ===")
        user_parts.append(user_request or "(nessuna)")
        user_parts.append("\n/no_think")
        user_text = "\n\n".join(user_parts)

        pipeline = self.pipeline(use_mock=use_mock)
        try:
            resp = pipeline.server.chat_completions(
                messages=[
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": user_text},
                ],
                temperature=0.1,
                max_tokens=max_tokens,
                json_schema=output_schema_hints,
                timeout=1200,
            )
            choices = resp.get("choices") or []
            content = (choices[0].get("message") or {}).get("content", "") if choices else ""
            # Validate JSON if schema requested
            data = None
            if output_schema_hints and content:
                import jsonschema as _js
                try:
                    data = json.loads(content)
                    try:
                        _js.validate(data, output_schema_hints)
                    except _js.ValidationError:
                        data = None
                except Exception:  # noqa: BLE001
                    data = None
            ok = bool(content)
            err = "" if ok else "LLM ha restituito testo vuoto"
            files_list = []
            if retrieved_chunks:
                for rc in retrieved_chunks:
                    if str(rc.file_path) not in files_list:
                        files_list.append(str(rc.file_path))
            self._log_op(feature_key, user_request, files_list,
                         [s.to_display() for s in srcs_used],
                         "success" if ok else "error", err)
            return AIResult(
                success=ok,
                data=data,
                error=err,
                attempts=1,
                raw_text=content,
                text_output=content,
                sources_used=srcs_used,
            )
        except Exception as exc:  # noqa: BLE001
            self._log_op(feature_key, user_request, [], [], "error", str(exc))
            return AIResult(success=False, error=str(exc), attempts=0)

    # --------------------------------------------------------------
    # Helper: bypass structured extraction fallback via direct call
    # --------------------------------------------------------------
    def _direct_structured_call(
        self,
        pipeline: JsonPipeline,
        schema: Dict[str, Any],
        messages: List[Dict[str, str]],
    ) -> ExtractionResult:
        from ..llm.json_pipeline import (
            _fill_missing_defaults, _lenient_json_parse,
        )
        last_error = ""
        attempts = 0
        for attempt in range(pipeline.max_retries + 1):
            attempts = attempt + 1
            try:
                resp = pipeline.server.chat_completions(
                    messages=messages,
                    temperature=0.05 if attempt == 0 else 0.2,
                    max_tokens=pipeline._estimate_max_tokens(schema),
                    json_schema=schema,
                )
            except Exception as exc:  # noqa: BLE001
                last_error = f"Chiamata LLM fallita: {exc}"
                continue
            choices = resp.get("choices") or []
            if not choices:
                last_error = "Risposta LLM vuota"
                continue
            raw = (choices[0].get("message") or {}).get("content", "")
            parsed, err = _lenient_json_parse(raw)
            if parsed is None:
                last_error = f"Parsing JSON fallito: {err}"
                messages = pipeline._append_repair_messages(messages, raw, last_error)
                continue
            if not isinstance(parsed, dict):
                parsed = {"value": parsed}
            repaired = _fill_missing_defaults(parsed, schema)
            import jsonschema
            try:
                jsonschema.validate(repaired, schema)
            except jsonschema.ValidationError as exc:
                last_error = f"Schema validation fallito: {exc.message}"
                messages = pipeline._append_repair_messages(messages, raw, last_error)
                continue
            return ExtractionResult(
                success=True, data=repaired, error_message="",
                attempts=attempts, raw=raw,
            )
        return ExtractionResult(
            success=False, data=None, error_message=last_error or "Fallimento",
            attempts=attempts, raw=None,
        )
