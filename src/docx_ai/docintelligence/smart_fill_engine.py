"""SmartFillEngine: estende compilazione esistente con modalità "Compila da documenti".

INPUT:
    - modulo (schema JSON da compilare)
    - lista di file o una cartella (PDF, DOCX, XLSX, TXT, immagini, scansioni)

OUTPUT per ogni campo:
    - valore (o [DA COMPILARE])
    - list[SourceRef] (fonti usate)
    - confidence se disponibile
    - conflitti rilevati

Modalità:
    - Per ogni campo: cerca candidati nei documenti
    - Conflitti: mostra tutte le alternative, NON decide
    - Dati mancanti: [DA COMPILARE]
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..llm.json_pipeline import JsonPipeline
from ..module_manager import LoadedModule
from .ai_service import AIResult, AIService
from .document_indexer import Chunk, DocumentIndexer
from .document_loader import DocumentLoader, LoadedDocument
from .document_retriever import DocumentRetriever, RetrievedChunk
from .source_tracker import Conflict, FieldWithSources, SourceRef, SourceTracker


LOG = logging.getLogger(__name__)


DEFAULT_MISSING = "[DA COMPILARE]"


@dataclass
class SmartFillResult:
    """Risultato della compilazione smart (prima della conferma utente)."""

    data: Dict[str, Any]                                   # valori finali (sentinali inclusi)
    fields_with_sources: Dict[str, FieldWithSources]       # per ogni campo, fonti
    conflicts: List[Conflict]                              # conflitti non risolti
    documents_used: List[LoadedDocument] = field(default_factory=list)
    validation_errors: List[str] = field(default_factory=list)
    raw_llm_text: str = ""
    sources_list: List[SourceRef] = field(default_factory=list)   # fonti globali
    summary: str = ""

    @property
    def total_fields(self) -> int:
        return len(self.fields_with_sources)

    @property
    def filled_fields(self) -> int:
        return sum(
            1 for v in self.data.values()
            if v not in (None, "", DEFAULT_MISSING, "NON_SPECIFICATO")
        )


SMART_FILL_SCHEMA_TEMPLATE = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
}


class SmartFillEngine:
    def __init__(
        self,
        config: Config,
        loader: DocumentLoader,
        indexer: DocumentIndexer,
        retriever: DocumentRetriever,
        ai: AIService,
    ):
        self.config = config
        self.loader = loader
        self.indexer = indexer
        self.retriever = retriever
        self.ai = ai
        self.source_tracker = SourceTracker()

    # --------------------------------------------------------------
    # Public: compila modulo da documenti
    # --------------------------------------------------------------
    def fill_from_documents(
        self,
        module: LoadedModule,
        reference_folder: Optional[Path] = None,
        reference_files: Optional[List[Path]] = None,
        *,
        progress_cb: Optional[Callable[[str], None]] = None,
        use_mock: bool = False,
    ) -> SmartFillResult:
        step = lambda m: progress_cb(m) if progress_cb else None
        schema = module.schema or {}
        field_names = list(schema.get("properties", {}).keys())

        # 1) Load documents
        step("Analisi campi del modulo…")
        docs: List[LoadedDocument] = []
        if reference_folder is not None:
            step(f"Scansione cartella {reference_folder.name}…")
            docs.extend(self.loader.scan_folder(
                Path(reference_folder), recursive=True,
                progress_cb=lambda i, n, p: step(f"Caricamento {i}/{n}: {p.name}"),
            ))
        if reference_files:
            for p in reference_files:
                try:
                    docs.append(self.loader.load_file(Path(p)))
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Scarto %s: %s", p, exc)
        if not docs:
            step("Nessun documento caricato.")

        # 2) Index chunks
        step("Indicizzazione documenti…")
        all_chunks: List[Chunk] = []
        for d in docs:
            try:
                all_chunks.extend(self.indexer.index_document(d))
            except Exception:  # noqa: BLE001
                pass

        # 3) Retrieve chunks FOR EACH FIELD (budget-aware)
        step("Ricerca informazioni per ogni campo…")
        per_field_chunks: Dict[str, List[RetrievedChunk]] = {}
        # Prima: cerca su tutti i campi per buildare un contesto generale
        global_query = " ".join(field_names)
        global_chunks = self.retriever.retrieve(
            all_chunks, global_query, top_k=18, max_total_chars=9000,
        )
        per_field_sources: Dict[str, List[SourceRef]] = {k: [] for k in field_names}
        # Per ogni campo, chunks focalizzati
        for fn in field_names:
            q = f"{fn} {fn.replace('_', ' ')}"
            r = self.retriever.retrieve(all_chunks, q, top_k=6, max_total_chars=3000)
            merged_map: Dict[str, RetrievedChunk] = {}
            for c in global_chunks + r:
                key = f"{c.chunk.file_sha256}|{c.chunk.chunk_index}"
                merged_map[key] = c
            per_field_chunks[fn] = list(merged_map.values())[:12]
            # Costruisci già le fonti di base (per UI)
            for rc in per_field_chunks[fn]:
                if rc.score >= 0.08:
                    ref = SourceRef(
                        file_path=rc.chunk.file_path,
                        file_name=rc.chunk.file_path.name if rc.chunk.file_path else "",
                        file_sha256=rc.chunk.file_sha256 or "",
                        page=rc.chunk.page,
                        sheet=rc.chunk.sheet,
                        cell=rc.chunk.cell_ref,
                        paragraph_index=rc.chunk.paragraph_index,
                        excerpt=(rc.chunk.chunk_text or "")[:300],
                        confidence=min(1.0, rc.score * 2.0),
                    )
                    per_field_sources[fn].append(ref)

        # 4) Pre-build schema for AI (clone + same shape)
        step("Analisi AI (compilazione campo per campo)…")
        ai_schema = self._schema_for_ai(schema)

        # Build retrieved chunks union to pass as context
        union_chunks: Dict[str, RetrievedChunk] = {}
        for fn, cs in per_field_chunks.items():
            for c in cs:
                key = f"{c.chunk.file_sha256}|{c.chunk.chunk_index}"
                if key not in union_chunks or union_chunks[key].score < c.score:
                    union_chunks[key] = c
        chunks_union = sorted(union_chunks.values(), key=lambda x: -x.score)[:50]

        # Richiesta AI
        user_request_lines: List[str] = []
        user_request_lines.append(
            "Compila i campi del modulo leggendo ESCLUSIVAMENTE dai documenti di contesto forniti.\n"
            "Regole:\n"
            "- Non inventare MAI valori.\n"
            f"- Se un campo non ha evidenza nei documenti usa '{DEFAULT_MISSING}'.\n"
            "- Se due fonti riportano valori diversi per lo stesso campo, elenca "
            "tutti i valori trovati separati da ' || ' e non fare la media.\n"
            "- Per gli array: compila solo se trovi elementi certi; altrimenti [] .\n"
            "- Per gli oggetti compila solo i sotto-campi per cui hai prove.\n"
        )
        user_request_lines.append("=== CAMPI RICHIESTI ===")
        for fn in field_names:
            p = schema.get("properties", {}).get(fn, {}) or {}
            t = p.get("type", "string")
            desc = p.get("description", "")
            enum = p.get("enum")
            line = f"- {fn} (type: {t})"
            if desc:
                line += f" — {desc}"
            if enum:
                line += f" [valori possibili: {', '.join(str(e) for e in enum)}]"
            user_request_lines.append(line)
        user_request_lines.append("")
        user_request_lines.append(
            "Restituisci un JSON VALIDO secondo lo schema indicato. NON aggiungere spiegazioni."
        )

        result: AIResult = self.ai.extract_structured(
            "smart_fill", ai_schema,
            user_request="\n".join(user_request_lines),
            module=module,
            retrieved_chunks=chunks_union,
            reference_docs=None,
            history_snippets=None,
            use_mock=use_mock,
        )
        step("Validazione e tracciabilità…")
        raw_data: Dict[str, Any] = {}
        validation_errors: List[str] = []
        if result.success and isinstance(result.data, dict):
            raw_data = dict(result.data)
        # 5) Apply defaults + fill missing
        try:
            JsonPipeline._fill_missing_defaults(ai_schema, raw_data)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        for fn in field_names:
            if fn not in raw_data or raw_data[fn] in (None, "", "NON_SPECIFICATO"):
                raw_data[fn] = DEFAULT_MISSING

        # Detect "||" conflicts in string fields (AI could list them)
        conflicts: List[Conflict] = []
        fields_with_sources: Dict[str, FieldWithSources] = {}
        for fn in field_names:
            val = raw_data.get(fn, DEFAULT_MISSING)
            sources = per_field_sources.get(fn, [])
            # Split candidate conflicts
            candidates: List[Tuple[Any, List[SourceRef]]] = []
            if isinstance(val, str) and " || " in val:
                for alt in val.split(" || "):
                    alt = alt.strip()
                    if alt:
                        candidates.append((alt, list(sources)))
                raw_data[fn] = DEFAULT_MISSING  # utente deve scegliere
            else:
                candidates.append((val, list(sources)))
            for val_cand, srcs in candidates:
                if val_cand in (DEFAULT_MISSING, "NON_SPECIFICATO", "", None, [], {}):
                    continue
                # Aggiungi a source tracker per la rilevazione automatica conflitti
                for s in (srcs or [None]):
                    self.source_tracker.add(fn, val_cand, s)
            # Build FieldWithSources e Conflict finali
        fields_with_sources, conflicts = self.source_tracker.build_fields(field_names)
        # Final data: prendi valori non-conflictuali da fields_with_sources
        final_data: Dict[str, Any] = {}
        for fn in field_names:
            fws = fields_with_sources.get(fn)
            if fws is not None and fws.value not in (None, ""):
                final_data[fn] = fws.value
            elif fn in raw_data and raw_data[fn] != DEFAULT_MISSING:
                final_data[fn] = raw_data[fn]
            else:
                final_data[fn] = DEFAULT_MISSING
        # 6) jsonschema validate (soft)
        try:
            import jsonschema  # type: ignore
            jsonschema.validate(instance=final_data, schema=schema)
        except Exception as exc:  # noqa: BLE001
            validation_errors.append(f"Validazione JSON Schema: {exc}")

        # Summary
        filled = sum(
            1 for v in final_data.values()
            if v not in (None, "", DEFAULT_MISSING, "NON_SPECIFICATO")
        )
        summary = (
            f"Compilazione smart: {filled}/{len(field_names)} campi "
            f"da {len(docs)} documenti, {len(conflicts)} conflitti."
        )
        step("Completato.")
        return SmartFillResult(
            data=final_data,
            fields_with_sources=fields_with_sources,
            conflicts=conflicts,
            documents_used=docs,
            validation_errors=validation_errors,
            raw_llm_text=result.raw_text,
            sources_list=result.sources_used,
            summary=summary,
        )

    # --------------------------------------------------------------
    # Helpers
    # --------------------------------------------------------------
    def _schema_for_ai(self, module_schema: Dict[str, Any]) -> Dict[str, Any]:
        """Restituisce uno schema valido per l'AI basato sullo schema del modulo.

        Rende tutti i campi opzionali per consentire i sentinel.
        """
        import copy
        s = copy.deepcopy(SMART_FILL_SCHEMA_TEMPLATE)
        s["properties"] = copy.deepcopy(module_schema.get("properties", {}))
        # Nessun required: l'AI può lasciare i campi vuoti, noi li filliamo con sentinella
        s["required"] = []
        return s

    # --------------------------------------------------------------
    # Public: salva JSON compilato dopo conferma (con metadata fonti)
    # --------------------------------------------------------------
    def save_approved(
        self,
        module: LoadedModule,
        result: SmartFillResult,
        output_dir: Path,
        *,
        approved_data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Path]:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = f"SmartFill_{module.slug}_{stamp}"
        final_data = approved_data if approved_data is not None else result.data
        out: Dict[str, Path] = {}
        data_json = output_dir / f"{base}.json"
        metadata = {
            "module_slug": module.slug,
            "module_name": module.name,
            "approved_data": final_data,
            "filled_fields_summary": {
                f: {
                    "value": fs.value,
                    "sources": [s.to_dict() for s in fs.sources],
                }
                for f, fs in result.fields_with_sources.items()
            },
            "conflicts": [c.to_dict() for c in result.conflicts],
            "documents_used": [
                {
                    "path": str(d.path),
                    "pages": d.pages_count,
                    "sheets": d.sheets_info,
                    "used_ocr": d.used_ocr,
                }
                for d in result.documents_used
            ],
            "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        data_json.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")
        out["json"] = data_json
        return out
