"""Top-level orchestration for a report lifecycle.

Flow:
  1. create_draft(module, description)   -> (report_id, draft_json or error)
  2. approve/revise(report_id, approved_json)
  3. finalize_exports(report_id) -> writes JSON + DOCX/XLSX + PDF on disk
"""

from __future__ import annotations

import json
import logging
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
    # l'AI reale ha fallito e i campi sono vuoti da compilare a mano (motivo)
    ai_failed: str = ""

    def __post_init__(self):
        if self.source_doc_hashes is None:
            self.source_doc_hashes = []


_PDF_POOL: Any = None


def _export_pdf_isolated(pdf_path: Path, data: Dict[str, Any], schema: Dict[str, Any], **kw: Any) -> None:
    """Genera il PDF in un processo separato: ReportLab e' CPU-bound e tiene il GIL,
    in un thread bloccherebbe l'interfaccia. Se il processo non e' disponibile
    (es. ambiente limitato) ripiega sull'esecuzione diretta."""
    global _PDF_POOL
    try:
        import concurrent.futures as cf
        import multiprocessing as mp
        if _PDF_POOL is None:
            _PDF_POOL = cf.ProcessPoolExecutor(max_workers=1, mp_context=mp.get_context("spawn"))
        _PDF_POOL.submit(export_pdf, pdf_path, data, schema, **kw).result(timeout=300)
        return
    except Exception as exc:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).info("PDF nel processo principale (%s)", exc)
        _PDF_POOL = None
    export_pdf(pdf_path, data, schema, **kw)


def _for_document(value: Any) -> Any:
    """Copia dei dati per i documenti esportati: "NON_SPECIFICATO" -> "" (e tolto dagli elenchi)."""
    if isinstance(value, dict):
        return {k: _for_document(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_for_document(v) for v in value if not (isinstance(v, str) and v.strip() == "NON_SPECIFICATO")]
    if isinstance(value, str) and value.strip() == "NON_SPECIFICATO":
        return ""
    return value


def shutdown_pdf_pool() -> None:
    global _PDF_POOL
    if _PDF_POOL is not None:
        _PDF_POOL.shutdown(wait=False, cancel_futures=True)
        _PDF_POOL = None


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
        shutdown_pdf_pool()
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
        use_references: bool = True,
        use_history: bool = True,
        temperature: Optional[float] = None,
        on_token: Optional[Callable[[str], None]] = None,
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
            ref_docs = self.context.parse_reference_documents(mod) if use_references else []
            if use_references:
                hashes.extend(self._hash_of_paths([self.mm.scan_reference_documents(mod)]))
            history = self.context.select_history_snippets(mod, description) if use_history else []
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
            temperature=temperature,
            on_token=on_token,
            document_context=mod.ai_context(),
        )
        _tick(3, "Salvataggio bozza nel DB…")
        report_id = self.db.create_report(
            module_id=mod.id,
            module_version=mod.version,
            status="draft",
            input_description=description,
            draft_json=json.dumps(extraction.data, ensure_ascii=False) if extraction.success else None,
            model_filename=self._model_used(extraction),
            model_sha256="",  # optionally populated at build/package time
            llama_build=self.config.get_setting("llama_build") or "",
            source_document_hashes=json.dumps(hashes, ensure_ascii=False),
        )
        _tick(4, "Pronto per la revisione.")
        ai_failed = ""
        real = [srv for srv in getattr(pipeline, "server_chain", []) if not isinstance(srv, MockLlamaServer)]
        if real and extraction.failover_used.startswith("Mock"):
            # prima la bozza vuota del fallback sembrava una risposta (sbagliata) dell'AI
            ai_failed = extraction.error_message or "risposta non valida"
        return DraftOutcome(
            ai_failed=ai_failed,
            report_id=report_id,
            success=extraction.success,
            data=extraction.data,
            error=first_err or extraction.error_message,
            source_doc_hashes=hashes,
        )

    def _model_used(self, extraction: ExtractionResult) -> str:
        """Modello che ha prodotto davvero la bozza (non quello configurato)."""
        used = extraction.failover_used or ""
        if used.startswith("Llama(") or used.startswith("Ollama("):
            return used[used.index("(") + 1:-1]
        if used.startswith("Mock"):
            return ""  # nessuna AI: campi da compilare a mano
        return Path(self.config.llm_effective.get("model", "")).name

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
        self.db.add_report_version(report_id, updates["final_json"], "Approvazione")

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
        # Nei documenti il segnaposto interno NON_SPECIFICATO diventa un campo vuoto
        # (prima finiva stampato cosi' nel Word/Excel/PDF); il JSON resta il dato completo.
        shown = _for_document(data)
        doc_path: Optional[Path] = None
        try:
            if mod.template_type == "docx":
                doc_path = base / f"{base.name}.docx"
                export_docx(mod.template_path, doc_path, shown)
            elif mod.template_type == "xlsx":
                doc_path = base / f"{base.name}.xlsx"
                export_xlsx(mod.template_path, doc_path, mod.mapping or {}, shown)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).exception("Esportazione %s non riuscita", mod.template_type)
            doc_path = None
            # Log an error column? Keep as string for UI.
            self.db.update_report(report_id, status="approved")

        # 3. PDF output
        pdf_path = base / f"{base.name}.pdf"
        review_notes = row.get("review_notes") or ""
        photos = [(Path(a["path"]), a.get("caption") or "") for a in self.db.list_attachments(report_id)
                  if Path(a["path"]).is_file()]
        _export_pdf_isolated(pdf_path, shown, mod.schema, report_id=f"#{report_id}", module_name=mod.name,
                             review_notes=review_notes, photos=photos)
        if photos:
            photo_dir = base / "foto"
            photo_dir.mkdir(exist_ok=True)
            import shutil as _sh
            for i, (ph, _cap) in enumerate(photos, 1):
                try:
                    _sh.copy2(ph, photo_dir / f"foto_{i:02d}{ph.suffix.lower()}")
                except OSError:
                    pass

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

    # ---- Duplicazione, versioni, foto ---------------------------------------
    def duplicate_report(self, report_id: int) -> int:
        """Nuova bozza con gli stessi dati (base per un intervento simile)."""
        row = self.db.get_report(report_id)
        if row is None:
            raise ValueError(f"Report {report_id} non trovato")
        data = row.get("final_json") or row.get("draft_json") or "{}"
        return self.db.create_report(
            module_id=row.get("module_id"),
            module_version=row.get("module_version") or "1.0.0",
            status="draft",
            input_description=row.get("input_description") or "",
            draft_json=data,
            model_filename=row.get("model_filename") or "",
            source="duplicate",
        )

    def update_approved(self, report_id: int, data: Dict[str, Any], note: str = "Modifica") -> int:
        """Modifica di un rapporto gia' approvato: salva una nuova versione."""
        payload = json.dumps(data, ensure_ascii=False)
        self.db.update_report(report_id, final_json=payload, status="approved")
        return self.db.add_report_version(report_id, payload, note)

    def restore_version(self, report_id: int, version_row: Dict[str, Any]) -> int:
        data = json.loads(version_row["data_json"])
        return self.update_approved(report_id, data, f"Ripristino della versione {version_row['version']}")

    def attachments_dir(self, report_id: int) -> Path:
        return self.config.data_root / "attachments" / f"{report_id:05d}"

    def add_photos(self, report_id: int, files: List[Path], caption: str = "") -> int:
        """Copia le foto nei dati utente (ridimensionate a max 2000 px)."""
        dest_dir = self.attachments_dir(report_id)
        dest_dir.mkdir(parents=True, exist_ok=True)
        added = 0
        for src in files:
            src = Path(src)
            if src.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp", ".bmp"}:
                continue
            dest = dest_dir / f"{int(time.time() * 1000)}_{src.stem[:40]}.jpg"
            try:
                from PIL import Image, ImageOps
                with Image.open(src) as raw:
                    im = ImageOps.exif_transpose(raw).convert("RGB")
                    im.thumbnail((2000, 2000))
                    im.save(dest, "JPEG", quality=85)
            except Exception:  # noqa: BLE001
                continue
            self.db.add_attachment(report_id, str(dest), caption)
            added += 1
        return added

    def photos(self, report_id: int) -> List[Dict[str, Any]]:
        return self.db.list_attachments(report_id)

    def remove_photo(self, attachment: Dict[str, Any]) -> None:
        self.db.delete_attachment(int(attachment["id"]))
        try:
            Path(attachment["path"]).unlink()
        except OSError:
            pass
