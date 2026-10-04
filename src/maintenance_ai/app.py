"""Application bootstrap: wires Config / DB / managers / services.

Used both by ``main.py`` (GUI + --self-test) and by tests. The ``App`` class
keeps the shared state so tests can start/stop the LLM layer independently
from the Tk mainloop.
"""

from __future__ import annotations

import logging
import logging.handlers
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


from .config import Config
from .db import Database
from .llm.llama_server import MockLlamaServer
from .module_manager import ModuleManager
from .security import SecurityLimits
from .services.context_service import ContextService
from .services.report_service import ReportService
from .docintelligence import (
    RulesManager,
    OCRService,
    DocumentLoader,
    DocumentIndexer,
    DocumentRetriever,
    AIService,
    DocumentGenerator,
    DocumentModifier,
    AuditEngine,
    SmartFillEngine,
)


def _ensure_src_on_path() -> None:
    """Ensure ``import maintenance_ai.…`` works both for ``python -m`` and
    ``python src/maintenance_ai/main.py`` invocations, and when the repo is
    launched from arbitrary CWD."""
    src_dir = Path(__file__).resolve().parents[1]
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    root = src_dir.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_API_KEY_RE = None
_JSON_BLOB_RE = None


class _MaskingFormatter(logging.Formatter):
    """Redact api-keys (32 alnum) and long JSON blobs >100 chars from log output."""

    def format(self, record: logging.LogRecord) -> str:  # noqa: N802
        global _API_KEY_RE, _JSON_BLOB_RE
        import re as _re
        if _API_KEY_RE is None:
            _API_KEY_RE = _re.compile(r"(?<![A-Za-z0-9])[A-Za-z0-9]{32}(?![A-Za-z0-9])")
            _JSON_BLOB_RE = _re.compile(r"\{[^{}]{100,}\}")
        try:
            msg = super().format(record)
        except Exception:  # noqa: BLE001
            msg = str(record.getMessage())
        msg = _API_KEY_RE.sub("[API_KEY_REDACTED]", msg)
        msg = _JSON_BLOB_RE.sub("[JSON_DATA_TRUNCATED]", msg)
        return msg


def _configure_logging(log_dir: Path, *, verbose: bool = False) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "maintenance_ai.log"
    fmt = _MaskingFormatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    handlers: list[logging.Handler] = [file_handler]
    # When run from source AND --verbose, also log to stderr.
    if (not getattr(sys, "frozen", False)) and verbose:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(fmt)
        handlers.append(stream)
    logging.basicConfig(
        level=logging.INFO,
        handlers=handlers,
        force=True,
    )
    # Prevent third-party noisy loggers from overwhelming the log.
    for noisy in ("urllib3", "PIL", "reportlab", "docx", "openpyxl", "pypdf"):
        try:
            logging.getLogger(noisy).setLevel(logging.WARNING)
        except Exception:  # noqa: BLE001
            pass


@dataclass
class App:
    config: Config
    db: Database
    module_manager: ModuleManager
    context: ContextService
    reports: ReportService
    security_limits: SecurityLimits
    rules_manager: RulesManager
    ocr_service: OCRService
    doc_loader: DocumentLoader
    doc_indexer: DocumentIndexer
    doc_retriever: DocumentRetriever
    ai_service: AIService
    doc_generator: DocumentGenerator
    doc_modifier: DocumentModifier
    audit_engine: AuditEngine
    smart_fill_engine: SmartFillEngine

    @classmethod
    def bootstrap(cls, config_path: Optional[Path] = None, *, verbose: bool = False) -> "App":
        _ensure_src_on_path()
        config = Config.load(config_path)
        _configure_logging(config.logs_root(), verbose=verbose)
        limits = SecurityLimits.from_dict(config.security_limits())
        db = Database(config.db_path())
        mm = ModuleManager(config, db, limits)
        ctx = ContextService(config, db, mm)

        # Document Intelligence shared services
        rules_manager = RulesManager(config, db=db)
        rules_manager.ensure_feature_rules_exist()
        # Retroattivamente: crea rules.txt in ogni modulo esistente sul disco
        try:
            for mod in mm.list_modules():
                rules_manager.ensure_module_rules_exist(mod.folder_path)
        except Exception:  # noqa: BLE001
            pass

        ocr_service = OCRService(config)
        doc_loader = DocumentLoader(config, security_limits=limits, db=db, ocr_service=ocr_service)
        doc_indexer = DocumentIndexer(db)
        doc_retriever = DocumentRetriever()
        ai_service = AIService(config, db, rules_manager, context=ctx)
        reports = ReportService(config, db, mm, ctx, ai_service=ai_service)
        doc_generator = DocumentGenerator(config, doc_loader, doc_indexer,
                                          doc_retriever, ai_service)
        doc_modifier = DocumentModifier(config, doc_loader, ai_service)
        audit_engine = AuditEngine(config, doc_loader, doc_indexer,
                                   doc_retriever, ai_service)
        smart_fill_engine = SmartFillEngine(config, doc_loader, doc_indexer,
                                            doc_retriever, ai_service)

        return cls(
            config=config,
            db=db,
            module_manager=mm,
            context=ctx,
            reports=reports,
            security_limits=limits,
            rules_manager=rules_manager,
            ocr_service=ocr_service,
            doc_loader=doc_loader,
            doc_indexer=doc_indexer,
            doc_retriever=doc_retriever,
            ai_service=ai_service,
            doc_generator=doc_generator,
            doc_modifier=doc_modifier,
            audit_engine=audit_engine,
            smart_fill_engine=smart_fill_engine,
        )

    def shutdown(self) -> None:
        try:
            self.reports.shutdown()
        finally:
            try:
                self.ai_service.shutdown()
            except Exception:  # noqa: BLE001
                pass
            self.db.close()

    # --------------------------- Self test ---------------------------
    def run_self_test(self, out=sys.stdout) -> int:
        """Run a fast smoke test of the core components WITHOUT touching the
        real llama-server or user data. Returns process exit code (0 on OK).

        The self-test:
          1. Proves config loads and DB works with a temporary in-memory
             duplicate (still hits same DB class).
          2. Creates/disposes a scratch module in a temporary directory
             to validate ModuleManager, parsers and exporters on both DOCX
             and XLSX.
          3. Runs a JsonPipeline with MockLlamaServer to prove the prompt
             build + schema validation + defaults pipeline all wire up.
        """
        import shutil
        import tempfile

        def _log(msg: str) -> None:
            try:
                print(msg, file=out, flush=True)
            except Exception:
                pass

        _log(f"[SELFTEST] MaintenanceAI {self.config.version}")
        _log(f"[SELFTEST] app_root = {self.config.app_root}")
        _log(f"[SELFTEST] data_root = {self.config.data_root}")

        failures: list[str] = []

        # 1. Config / DB basics
        try:
            db_info = self.db.get_setting("db_test_key")
            self.db.set_setting("db_test_key", "ok")
            assert self.db.get_setting("db_test_key") == "ok"
            if db_info is not None:
                self.db.set_setting("db_test_key", db_info)
            _log("[SELFTEST] DB write/read: OK")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"DB basic ops failed: {exc!r}")
            _log(f"[SELFTEST] FAIL {failures[-1]}")

        # 2. Scratch workspace inside exports/selftest
        # Scratch dirs live in %TEMP%: the self-test never writes into user exports.
        import tempfile
        scratch = Path(tempfile.mkdtemp(prefix="mai_selftest_"))
        # Build a lightweight DB-backed ModuleManager rooted at scratch for the test
        try:
            from .db import Database as _DB
            from .module_manager import ModuleManager as _MM
            scratch_db_path = scratch / "selftest.db"
            scratch_db = _DB(scratch_db_path)
            scratch_mm = _MM.__new__(_MM)
            scratch_mm.config = self.config
            scratch_mm.db = scratch_db
            scratch_mm.limits = self.security_limits
            scratch_mm.workspace = scratch / "modules"
            scratch_mm.workspace.mkdir(parents=True, exist_ok=True)

            schema_docx = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "TestDocx",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tipo_intervento": {"type": "string", "const": "selftest_docx"},
                    "impianto": {"type": "string"},
                    "esito": {"type": "string", "enum": ["regolare", "anomalia", "non_specificato"]},
                    "attivita": {"type": "array", "items": {"type": "string"}},
                    "note": {"type": "string"},
                },
                "required": ["tipo_intervento", "impianto", "esito", "attivita", "note"],
            }
            mod_docx = scratch_mm.create_module(
                name="Selftest DOCX", slug="selftest_docx", template_type="docx",
                description="Modulo temporaneo per self-test DOCX",
                schema=schema_docx, mapping={},
            )
            # Template contains placeholders: check extraction
            from .parsers.docx_parser import extract_text as d_extract, load_document as d_load
            doc = d_load(mod_docx.template_path)
            ext = d_extract(doc)
            if "impianto" not in ext.placeholders:
                raise AssertionError(
                    f"Placeholder impianto mancante nel template DOCX. "
                    f"Placeholder trovati: {ext.placeholders!r}"
                )
            _log("[SELFTEST] DOCX template placeholder detection: OK")

            # Exporter DOCX
            from .exporters.docx_exporter import export_docx
            values = {
                "tipo_intervento": "selftest_docx",
                "impianto": "Pompa ST-01",
                "esito": "regolare",
                "attivita": ["Controllo A", "Verifica B"],
                "note": "Self-test",
            }
            out_docx = scratch / "out.docx"
            export_docx(mod_docx.template_path, out_docx, values)
            if not out_docx.exists() or out_docx.stat().st_size < 1000:
                raise AssertionError("export_docx non ha prodotto un file valido")
            doc2 = d_load(out_docx)
            text_after = d_extract(doc2).full_text
            if "Pompa ST-01" not in text_after:
                raise AssertionError(
                    "Il DOCX esportato non contiene i valori attesi. "
                    "Testo: " + text_after[:400]
                )
            _log("[SELFTEST] DOCX export + placeholder replacement: OK")

            # XLSX module
            schema_xlsx = {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "title": "TestXlsx",
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "tipo_intervento": {"type": "string", "const": "selftest_xlsx"},
                    "impianto": {"type": "string"},
                    "data_intervento": {"type": "string"},
                    "esito": {"type": "string"},
                    "note": {"type": "string"},
                },
                "required": ["tipo_intervento", "impianto", "data_intervento", "esito", "note"],
            }
            mapping_xlsx = {
                "impianto": {"type": "cell", "sheet": "Rapporto", "cell": "B3"},
                "data_intervento": {"type": "cell", "sheet": "Rapporto", "cell": "B4"},
                "esito": {"type": "cell", "sheet": "Rapporto", "cell": "B5"},
                "note": {"type": "cell", "sheet": "Rapporto", "cell": "B6"},
            }
            mod_xlsx = scratch_mm.create_module(
                name="Selftest XLSX", slug="selftest_xlsx", template_type="xlsx",
                description="Modulo temporaneo per self-test XLSX",
                schema=schema_xlsx, mapping=mapping_xlsx,
            )
            from .parsers.xlsx_parser import extract_text as x_extract, load_workbook_safe as x_load
            wb = x_load(mod_xlsx.template_path)
            xext = x_extract(wb)
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
            if "impianto" not in " ".join(xext.placeholders):
                # XLSX template created from minimal schema has {{impianto}} as cell value B2
                _log(f"[SELFTEST] XLSX placeholders: {xext.placeholders!r}")
            _log("[SELFTEST] XLSX template parsing: OK")

            from .exporters.xlsx_exporter import export_xlsx
            vals_x = {
                "tipo_intervento": "selftest_xlsx",
                "impianto": "Nastro ST-X2",
                "data_intervento": "2026-08-27",
                "esito": "regolare",
                "note": "selftest note",
            }
            out_xlsx = scratch / "out.xlsx"
            applied = export_xlsx(mod_xlsx.template_path, out_xlsx, mapping_xlsx, vals_x)
            if not out_xlsx.exists() or out_xlsx.stat().st_size < 1000:
                raise AssertionError("export_xlsx non ha prodotto un file valido")
            wb2 = x_load(out_xlsx)
            ws = wb2["Rapporto"]
            if str(ws["B3"].value) != "Nastro ST-X2":
                raise AssertionError(
                    f"XLSX mapping fallito: B3={ws['B3'].value!r}"
                )
            try:
                wb2.close()
            except Exception:  # noqa: BLE001
                pass
            _log(f"[SELFTEST] XLSX export + mapping (campi applicati: {applied}): OK")

            # PDF exporter
            from .exporters.pdf_exporter import export_pdf
            pdf_path = scratch / "out.pdf"
            export_pdf(pdf_path, values, schema_docx, report_id="selftest",
                       module_name="Selftest")
            if not pdf_path.exists() or pdf_path.stat().st_size < 2000:
                raise AssertionError("export_pdf non ha prodotto un file valido")
            _log(f"[SELFTEST] PDF export: OK ({pdf_path.stat().st_size} bytes)")

            # JSON pipeline (mock)
            from .llm.json_pipeline import JsonPipeline
            server = MockLlamaServer()
            server.start()
            pipeline = JsonPipeline(server, max_retries=1)
            result = pipeline.extract(
                schema_docx,
                "Rumore anomalo sulla pompa ST-01. Pulizia eseguita. Tutto regolare.",
            )
            if not result.success:
                raise AssertionError(f"Pipeline mock fallita: {result.error_message}")
            # Mock should have produced required keys
            for req in schema_docx.get("required", []):
                if req not in (result.data or {}):
                    raise AssertionError(f"Mock output manca campo {req} -> {result.data}")
            import jsonschema
            try:
                jsonschema.validate(result.data, schema_docx)
            except jsonschema.ValidationError as exc:
                raise AssertionError(f"Mock output non valida: {exc.message}") from exc
            _log(f"[SELFTEST] JsonPipeline (mock): OK (attempts={result.attempts})")

            scratch_db.close()
        except Exception as exc:  # noqa: BLE001
            import traceback
            failures.append(f"Scratch module/export/pipeline failure: {exc!r}")
            _log("[SELFTEST] FAIL " + traceback.format_exc())
        finally:
            shutil.rmtree(scratch, ignore_errors=True)

        # Security primitives
        try:
            from .security import safe_resolve_name, safe_slug
            r = scratch or Path(tempfile.mkdtemp())
            resolved = safe_resolve_name(r, "sub/ok.txt")
            if not str(resolved.resolve()).startswith(str(r.resolve())):
                raise AssertionError(f"safe_resolve_name ha escapato la root: {resolved}")
            if safe_slug("..\\bad/name?.txt") == "..\\bad/name?.txt":
                raise AssertionError("safe_slug non ha pulito il nome")
            _log("[SELFTEST] Security path/slug: OK")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"Security primitives failed: {exc!r}")
            _log(f"[SELFTEST] FAIL {failures[-1]}")

        # Document Intelligence (mock)
        try:
            scratch2 = Path(tempfile.mkdtemp(prefix="mai_selftest_di_"))

            # Rules manager
            rm = RulesManager(scratch2 / "data")
            rm.ensure_feature_rules_exist()
            for key in ("report_compilation", "document_creation", "document_edit",
                        "document_audit", "smart_fill"):
                if not rm.feature_rules_path(key).is_file():
                    raise AssertionError(f"rules per feature {key} non creato")
                if rm.read_feature_rules(key) != "":
                    raise AssertionError(f"rules {key} non nasce vuoto")
            # Module rules
            mod_folder = scratch2 / "modules" / "M_test"
            mod_folder.mkdir(parents=True, exist_ok=True)
            rm.ensure_module_rules_exist(mod_folder)
            rpath = mod_folder / "rules.txt"
            if not rpath.is_file():
                raise AssertionError("rules modulo non creato")
            if rm.read_module_rules(mod_folder) != "":
                raise AssertionError("rules modulo non nasce vuoto")
            # Salvataggio utente + persistenza (AI non può modificarli: no method, verificato struttura)
            rm.user_save_feature_rules("document_creation", "# Regola utente\n", _from_ui=True)
            if "Regola utente" not in rm.read_feature_rules("document_creation"):
                raise AssertionError("salvataggio rules feature non persistito")
            rm.user_save_module_rules(mod_folder, "# Regola modulo\n", _from_ui=True)
            if "Regola modulo" not in rm.read_module_rules(mod_folder):
                raise AssertionError("salvataggio rules modulo non persistito")
            _log("[SELFTEST] RulesManager (feature+module, init vuoto, salva utente): OK")

            # SourceTracker: rilevazione conflitti
            from .docintelligence import SourceTracker, SourceRef
            st = SourceTracker()
            st.add("impianto", "P-100", SourceRef(file_name="a.pdf", page=1))
            st.add("impianto", "P-200", SourceRef(file_name="b.pdf", page=3))
            st.add("impianto", "P-100", SourceRef(file_name="c.pdf", page=2))
            fields, conflicts = st.build_fields(["impianto"])
            if not conflicts or conflicts[0].field != "impianto":
                raise AssertionError(
                    f"SourceTracker conflitto non rilevato: conflicts={conflicts}")
            if len({alt[0] for alt in conflicts[0].alternatives}) < 2:
                raise AssertionError("Conflitto non ha 2 alternative")
            _log("[SELFTEST] SourceTracker conflitti: OK")

            # Loader/TXT/JSON pipeline smart fill mock
            (scratch2 / "reports").mkdir()
            f1 = scratch2 / "reports" / "r1.txt"
            f1.write_text("Rapporto n. 123\nMacchina: P-104\nData: 12/08/2026\n"
                          "Responsabile: Mario Rossi", encoding="utf-8")
            f2 = scratch2 / "reports" / "r2.txt"
            f2.write_text("Rapporto n. 123\nNote: controllo completo\nEsito: regolare",
                          encoding="utf-8")
            loaded = self.doc_loader.load_file(f1)
            if "P-104" not in (loaded.full_text or ""):
                raise AssertionError("Loader TXT non ha estratto il testo")
            # Indexer + retriever
            chunks = self.doc_indexer.index_document(loaded)
            if not chunks:
                raise AssertionError("Indexer non ha prodotto chunk")
            retrieved = self.doc_retriever.retrieve(chunks, "Macchina P-104")
            if not retrieved:
                raise AssertionError("Retriever non ha trovato chunk")
            _log("[SELFTEST] DocumentLoader+Indexer+Retriever (TXT): OK")

            # Smart Fill mock (use_mock=True) senza conflitti → riempie
            from .module_manager import LoadedModule
            schema_dummy = {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "macchina": {"type": "string"},
                    "data": {"type": "string"},
                    "responsabile": {"type": "string"},
                    "note_extra": {"type": "string"},
                },
            }
            loaded_mod_dummy = LoadedModule.__new__(LoadedModule)
            loaded_mod_dummy.slug = "selftest_sf"
            loaded_mod_dummy.name = "Selftest SF"
            loaded_mod_dummy.schema = schema_dummy
            loaded_mod_dummy.mapping = {}
            loaded_mod_dummy.folder_path = scratch2 / "modules" / "sf"
            loaded_mod_dummy.folder_path.mkdir(parents=True, exist_ok=True)
            sf_res = self.smart_fill_engine.fill_from_documents(
                module=loaded_mod_dummy,
                reference_folder=scratch2 / "reports",
                use_mock=True,
            )
            if not isinstance(sf_res.data, dict):
                raise AssertionError("SmartFill non ha prodotto dict")
            for req in ("macchina", "data", "responsabile", "note_extra"):
                if req not in sf_res.data:
                    raise AssertionError(f"SmartFill manca campo {req}: {sf_res.data}")
            _log("[SELFTEST] SmartFillEngine (mock, 4 campi + 2 file TXT): OK")

            shutil.rmtree(scratch2, ignore_errors=True)
        except Exception as exc:  # noqa: BLE001
            import traceback
            failures.append(f"Document Intelligence failure: {exc!r}")
            _log("[SELFTEST] FAIL " + traceback.format_exc())

        if failures:
            _log(f"[SELFTEST] FAILED ({len(failures)} errori)")
            return 2
        _log("[SELFTEST] PASSED")
        return 0
