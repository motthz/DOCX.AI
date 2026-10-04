"""Top-level orchestration for a report lifecycle.

Flow:
  1. create_draft(module, description)   -> (report_id, draft_json or error)
  2. approve/revise(report_id, approved_json)
  3. finalize_exports(report_id) -> writes JSON + DOCX/XLSX + PDF on disk
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..db import Database
from ..exporters.docx_exporter import export_docx
from ..exporters.pdf_exporter import export_pdf
from ..exporters.xlsx_exporter import export_xlsx
from ..llm.json_pipeline import ExtractionResult, JsonPipeline
from ..llm.llama_server import LlamaServerOptions, LlamaServer, MockLlamaServer
from ..module_manager import LoadedModule, ModuleManager
from ..security import sha256_file
from .context_service import ContextService


ABSENT = object()


@dataclass
class DraftOutcome:
    report_id: int
    success: bool
    data: Optional[Dict[str, Any]]
    error: str = ""
    source_doc_hashes: List[str] = None  # type: ignore[assignment]

    def __post_init__(self):
        if self.source_doc_hashes is None:
            self.source_doc_hashes = []


class ReportService:
    def __init__(
        self,
        config: Config,
        db: Database,
        module_manager: ModuleManager,
        context: ContextService,
        pipeline: Optional[JsonPipeline] = None,
        ai_service: Any = None,
    ):
        self.config = config
        self.db = db
        self.mm = module_manager
        self.context = context
        self._pipeline_override = pipeline
        self._server: Any = None
        # Shared AIService (failover chain llama -> ollama -> mock). When set,
        # reports reuse its single llama-server instead of starting another one.
        self.ai_service = ai_service

    # ---- LLM pipeline (lazily created on first use) ------------------------
    def pipeline(self, *, use_mock: bool = False) -> JsonPipeline:
        if self._pipeline_override is not None:
            return self._pipeline_override
        if use_mock:
            server: Any = MockLlamaServer()
            max_retries = self.config.llm_effective.get("max_retries", 1)
            return JsonPipeline(server, max_retries=max_retries)
        if self.ai_service is not None:
            return self.ai_service.pipeline(use_mock=False)
        if self._server is None:
            eff = self.config.llm_effective
            opts = LlamaServerOptions(
                runtime_dir=self.config.resolve_ai_path(eff["runtime_dir"]),
                runtime_exe=eff.get("runtime_exe", "llama-server.exe"),
                model_path=self.config.resolve_ai_path(eff["model"]),
                context_size=int(eff.get("context_size", 4096)),
                host=eff.get("host", "127.0.0.1"),
                port_min=int(eff.get("port_min", 39280)),
                port_max=int(eff.get("port_max", 39299)),
                no_webui=bool(eff.get("no_webui", True)),
                no_think=bool(eff.get("no_think", True)),
                thread_override=eff.get("thread_override"),
            )
            server = LlamaServer(opts)
            server.start()
            self._server = server
        else:
            server = self._server
        max_retries = self.config.llm_effective.get("max_retries", 2)
        return JsonPipeline(server, max_retries=max_retries)

    def shutdown(self) -> None:
        try:
            if self._server is not None:
                self._server.stop()
        finally:
            self._server = None

    # ---- Draft creation ----------------------------------------------------
    def create_draft(
        self,
        mod: LoadedModule,
        description: str,
        *,
        use_mock: bool = False,
        on_progress: Optional[Callable[[int, int, str], None]] = None,
    ) -> DraftOutcome:
        total = 4
        hashes: List[str] = []

        def _tick(step: int, desc: str) -> None:
            if on_progress is not None:
                try:
                    on_progress(step, total, desc)
                except Exception:  # noqa: BLE001
                    pass

        try:
            _tick(0, "Preparazione contesto…")
            ref_docs = self.context.parse_reference_documents(mod)
            hashes.extend(self._hash_of_paths([self.mm.scan_reference_documents(mod)]))
            history = self.context.select_history_snippets(mod, description)
            _tick(1, "Costruzione contesto completata.")
        except Exception as exc:  # noqa: BLE001
            ref_docs = []
            history = []
            first_err = f"Preparazione contesto fallita: {exc}"
        else:
            first_err = ""

        _tick(2, "Estrazione dati con LLM locale…")
        pipeline = self.pipeline(use_mock=use_mock)
        extraction: ExtractionResult = pipeline.extract(
            schema=mod.schema,
            operator_description=description,
            reference_docs=ref_docs,
            history_snippets=history,
        )
        _tick(3, "Salvataggio bozza nel DB…")
        report_id = self.db.create_report(
            module_id=mod.id,
            module_version=mod.version,
            status="draft",
            input_description=description,
            draft_json=json.dumps(extraction.data, ensure_ascii=False) if extraction.success else None,
            model_filename=Path(self.config.llm_effective.get("model", "")).name,
            model_sha256="",  # optionally populated at build/package time
            llama_build=self.config.get_setting("llama_build") or "",
            source_document_hashes=json.dumps(hashes, ensure_ascii=False),
        )
        _tick(4, "Pronto per la revisione.")
        return DraftOutcome(
            report_id=report_id,
            success=extraction.success,
            data=extraction.data,
            error=first_err or extraction.error_message,
            source_doc_hashes=hashes,
        )

    def _hash_of_paths(self, path_groups: Any) -> List[str]:
        out: List[str] = []
        for group in path_groups:
            for p in group or []:
                try:
                    pp = Path(p)
                    if pp.exists() and pp.is_file():
                        out.append(sha256_file(pp))
                except Exception:  # noqa: BLE001
                    pass
        return out

    # ---- Approval & revision -----------------------------------------------
    def revise_draft(self, report_id: int, new_data: Dict[str, Any]) -> None:
        self.db.update_report(
            report_id,
            draft_json=json.dumps(new_data, ensure_ascii=False),
            status="draft",
        )

    def approve_draft(self, report_id: int, approved_data: Dict[str, Any]) -> None:
        review_notes = ""
        if isinstance(approved_data, dict):
            review_notes = str(approved_data.pop("__review_notes__", "") or "").strip()
        updates: Dict[str, Any] = {
            "final_json": json.dumps(approved_data, ensure_ascii=False),
            "status": "approved",
            "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if review_notes:
            updates["review_notes"] = review_notes
        self.db.update_report(report_id, **updates)

    # ---- Exports -----------------------------------------------------------
    def finalize_exports(
        self,
        report_id: int,
        mod: LoadedModule,
        *,
        exports_dir: Optional[Path] = None,
    ) -> Tuple[Path, Optional[Path], Path]:
        row = self.db.get_report(report_id)
        if row is None:
            raise ValueError(f"Report {report_id} non trovato")
        final_json_str = row["final_json"] or row["draft_json"] or "{}"
        try:
            data = json.loads(final_json_str) if isinstance(final_json_str, str) else dict(final_json_str)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON del report non valido: {exc}") from exc

        exports_root = Path(exports_dir) if exports_dir else self.config.exports_root()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        base = exports_root / f"{mod.slug}_{report_id:05d}_{stamp}"
        base.mkdir(parents=True, exist_ok=True)

        # 1. JSON output
        json_path = base / f"{base.name}.json"
        json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

        # 2. DOCX/XLSX output (only if template exists + mapping filled for xlsx)
        doc_path: Optional[Path] = None
        try:
            if mod.template_type == "docx":
                doc_path = base / f"{base.name}.docx"
                export_docx(mod.template_path, doc_path, data)
            elif mod.template_type == "xlsx":
                doc_path = base / f"{base.name}.xlsx"
                export_xlsx(mod.template_path, doc_path, mod.mapping or {}, data)
        except Exception:  # noqa: BLE001
            doc_path = None
            # Log an error column? Keep as string for UI.
            self.db.update_report(report_id, status="approved")

        # 3. PDF output
        pdf_path = base / f"{base.name}.pdf"
        review_notes = row.get("review_notes") or ""
        export_pdf(pdf_path, data, mod.schema,
                   report_id=f"#{report_id}", module_name=mod.name,
                   review_notes=review_notes)

        # Also copy / save a copy inside module history folder for next runs?
        history_folder = mod.history_folder()
        if history_folder.exists():
            try:
                history_json = history_folder / f"{base.name}.json"
                history_json.write_text(
                    json.dumps({"input": row["input_description"], "final_json": data},
                               indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except Exception:  # noqa: BLE001
                pass

        self.db.update_report(
            report_id,
            status="exported",
            output_json_path=str(json_path),
            output_document_path=str(doc_path) if doc_path else None,
            output_pdf_path=str(pdf_path),
        )
        return json_path, doc_path, pdf_path
