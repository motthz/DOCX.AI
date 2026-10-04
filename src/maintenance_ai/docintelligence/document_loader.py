"""DocumentLoader: caricamento universale di file supportati.

Formati:
- PDF (testo nativo + OCR tramite PDFParser + OCRService)
- DOCX (python-docx parser esistente, riutilizzato)
- XLSX (openpyxl parser esistente, riutilizzato)
- TXT (testo puro)
- JPG/JPEG/PNG (OCR diretto via OCRService)

Fornisce:
- scansione ricorsiva di cartelle,
- output normalizzato come LoadedDocument per ogni file,
- cache SHA-256 basata via parsed_cache del DB (se fornito).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..config import Config
from ..db import Database
from ..parsers.docx_parser import extract_text as docx_extract, load_document as docx_load
from ..parsers.xlsx_parser import extract_text as xlsx_extract, load_workbook_safe as xlsx_load
from ..security import (
    SecurityError,
    SecurityLimits,
    sha256_file,
    validate_file_size,
)
from .ocr_service import OCRService
from .pdf_parser import PDFExtraction, PDFParser


LOG = logging.getLogger(__name__)


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".txt",
    ".jpg",
    ".jpeg",
    ".png",
}

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}


@dataclass
class TextSpan:
    """Porzione di testo con provenienza"""

    text: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    cell: Optional[str] = None
    paragraph_index: Optional[int] = None
    source_kind: str = ""        # "native" | "ocr"
    ocr_confidence: Optional[float] = None


@dataclass
class LoadedDocument:
    """Risultato del caricamento di UN file."""

    path: Path
    ext: str
    file_sha256: str
    size_bytes: int
    full_text: str = ""
    spans: List[TextSpan] = field(default_factory=list)
    pages_count: Optional[int] = None
    sheets_info: Dict[str, int] = field(default_factory=dict)     # sheet_name -> rows
    used_ocr: bool = False
    needs_ocr: bool = False
    ocr_available: bool = False
    errors: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    # PDF details (if applicable)
    pdf_extraction: Optional[PDFExtraction] = None
    # Cache state
    loaded_from_cache: bool = False

    def display_name(self) -> str:
        return Path(self.path).name


class DocumentLoader:
    def __init__(
        self,
        config: Config,
        *,
        security_limits: Optional[SecurityLimits] = None,
        db: Optional[Database] = None,
        ocr_service: Optional[OCRService] = None,
        pdf_parser: Optional[PDFParser] = None,
    ):
        self.config = config
        self.limits = security_limits or SecurityLimits()
        self.db = db
        self.ocr = ocr_service or (OCRService(config) if config else None)
        self.pdf = pdf_parser or PDFParser(self.ocr)

    # --------------------------------------------------------------
    # Public: scansione cartella ricorsiva
    # --------------------------------------------------------------
    def scan_folder(
        self,
        folder: Path,
        *,
        recursive: bool = True,
        progress_cb: Optional[Callable[[int, int, Path], None]] = None,
    ) -> List[LoadedDocument]:
        folder = Path(folder)
        if not folder.is_dir():
            return []
        files: List[Path] = []
        iterator = folder.rglob("*") if recursive else folder.glob("*")
        for p in iterator:
            if not p.is_file():
                continue
            ext = p.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue
            files.append(p)
        files.sort()
        total = len(files)
        out: List[LoadedDocument] = []
        for idx, f in enumerate(files, 1):
            try:
                if progress_cb:
                    progress_cb(idx, total, f)
                doc = self.load_file(f)
                out.append(doc)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Scarto file %s: %s", f, exc)
        return out

    # --------------------------------------------------------------
    # Public: carica singolo file
    # --------------------------------------------------------------
    def load_file(self, path: Path, *, run_ocr: bool = True,
                  use_cache: bool = True) -> LoadedDocument:
        path = Path(path)
        ext = path.suffix.lower().lstrip(".")
        # Validate
        if not path.is_file():
            raise FileNotFoundError(str(path))
        validate_file_size(path, self.limits)
        # Extension: allow broader set for docintelligence than the input-gate.
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise SecurityError(f"Estensione non supportata: {path.suffix}")
        size = path.stat().st_size
        sha = sha256_file(path)

        # Cache read
        if use_cache and self.db is not None:
            cached = self.db.cache_get(sha)
            if cached is not None:
                text, meta = cached
                doc = LoadedDocument(
                    path=path, ext=ext, file_sha256=sha, size_bytes=size,
                    full_text=text, metadata=meta, loaded_from_cache=True,
                )
                return doc

        errors: List[str] = []
        if ext == "pdf":
            doc = self._load_pdf(path, run_ocr=run_ocr)
        elif ext == "docx":
            doc = self._load_docx(path)
        elif ext == "xlsx":
            doc = self._load_xlsx(path)
        elif ext == "txt":
            doc = self._load_txt(path)
        elif ext in {"jpg", "jpeg", "png"}:
            doc = self._load_image(path, run_ocr=run_ocr)
        else:
            raise SecurityError(f"Estensione non gestita internamente: {ext}")
        # Enrich with common fields
        doc.path = path
        doc.ext = ext
        doc.file_sha256 = sha
        doc.size_bytes = size
        if errors:
            doc.errors.extend(errors)
        # Cache write
        if use_cache and self.db is not None and doc.full_text:
            try:
                kind = "docintel_" + ext
                self.db.cache_store(sha, kind, doc.full_text[:500000], doc.metadata)
            except Exception as exc:  # noqa: BLE001
                LOG.warning("cache_store fallito: %s", exc)
        return doc

    # --------------------------------------------------------------
    # Per-format loaders
    # --------------------------------------------------------------
    def _load_pdf(self, path: Path, *, run_ocr: bool) -> LoadedDocument:
        doc = LoadedDocument(path=path, ext="pdf", file_sha256="", size_bytes=0)
        try:
            pdf = self.pdf.parse(path, run_ocr=run_ocr)
            doc.pdf_extraction = pdf
            doc.pages_count = pdf.page_count
            doc.metadata["page_count"] = pdf.page_count
            doc.metadata["pages_count"] = pdf.page_count
            doc.used_ocr = pdf.ocr_used
            doc.needs_ocr = (not pdf.native_text_found) and pdf.page_count > 0
            doc.ocr_available = self.ocr.is_available if self.ocr else False
            if pdf.encrypted:
                doc.metadata["encrypted"] = True
            if pdf.needs_password:
                doc.errors.append("PDF protetto da password - fornire la password")
            for err in pdf.errors:
                doc.errors.append(err)
            # Build spans per page
            for page in pdf.pages:
                if page.native_text:
                    doc.spans.append(TextSpan(
                        text=page.native_text, page=page.index, source_kind="native",
                    ))
                if page.ocr_text:
                    conf = page.ocr_page.confidence_avg if page.ocr_page else None
                    doc.spans.append(TextSpan(
                        text=page.ocr_text, page=page.index, source_kind="ocr",
                        ocr_confidence=conf,
                    ))
            doc.full_text = pdf.full_text
            if pdf.page_count > 100:
                LOG.warning("DocumentLoader PDF %s: %s pages (>100 guardrail)", path.name, pdf.page_count)
        except Exception as exc:  # noqa: BLE001
            doc.errors.append(f"Errore generico PDF: {exc}")
        return doc

    def _load_docx(self, path: Path) -> LoadedDocument:
        doc = LoadedDocument(path=path, ext="docx", file_sha256="", size_bytes=0)
        try:
            d = docx_load(path)
            ext = docx_extract(d)
            doc.full_text = ext.full_text
            doc.metadata.update(ext.meta)
            # paragraph-level spans
            for pi, ptext in enumerate(ext.paragraphs):
                if ptext.strip():
                    doc.spans.append(TextSpan(text=ptext, paragraph_index=pi, source_kind="native"))
            # table-level spans
            for ti, table in enumerate(ext.tables or []):
                for ri, row in enumerate(table):
                    row_text = " | ".join(c.strip() for c in row)
                    if row_text.strip():
                        doc.spans.append(TextSpan(
                            text=row_text,
                            paragraph_index=10000 + ti * 100 + ri,
                            source_kind="native",
                        ))
        except Exception as exc:  # noqa: BLE001
            doc.errors.append(f"Errore DOCX: {exc}")
        return doc

    def _load_xlsx(self, path: Path) -> LoadedDocument:
        doc = LoadedDocument(path=path, ext="xlsx", file_sha256="", size_bytes=0)
        try:
            wb = xlsx_load(path)
            ext = xlsx_extract(wb)
            try:
                wb.close()
            except Exception:  # noqa: BLE001
                pass
            doc.full_text = ext.full_text
            doc.metadata.update(ext.meta)
            from openpyxl.utils import get_column_letter
            for sheet_name, rows in ext.sheets.items():
                doc.sheets_info[sheet_name] = len(rows)
                for ri, row in enumerate(rows, start=1):
                    for ci, value in enumerate(row, start=1):
                        if value is None:
                            continue
                        s = str(value).strip()
                        if not s:
                            continue
                        doc.spans.append(TextSpan(
                            text=s,
                            sheet=sheet_name,
                            cell=f"{get_column_letter(ci)}{ri}",
                            source_kind="native",
                        ))
        except Exception as exc:  # noqa: BLE001
            doc.errors.append(f"Errore XLSX: {exc}")
        return doc

    def _load_txt(self, path: Path) -> LoadedDocument:
        doc = LoadedDocument(path=path, ext="txt", file_sha256="", size_bytes=0)
        try:
            data_bytes = path.read_bytes()
            # Try UTF-8 then latin-1
            try:
                text = data_bytes.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text = data_bytes.decode("utf-8", errors="replace")
                except Exception:
                    text = data_bytes.decode("latin-1", errors="replace")
            doc.full_text = text
            lines = text.splitlines()
            for li, line in enumerate(lines):
                if line.strip():
                    doc.spans.append(TextSpan(text=line, paragraph_index=li, source_kind="native"))
        except Exception as exc:  # noqa: BLE001
            doc.errors.append(f"Errore TXT: {exc}")
        return doc

    def _load_image(self, path: Path, *, run_ocr: bool) -> LoadedDocument:
        doc = LoadedDocument(path=path, ext=path.suffix.lower().lstrip("."),
                             file_sha256="", size_bytes=0)
        try:
            from PIL import Image, ExifTags  # type: ignore
            pil_img = Image.open(str(path))
            # Verify valid
            pil_img.verify()
            pil_img = Image.open(str(path))  # re-open after verify
            doc.metadata["format"] = getattr(pil_img, "format", "")
            doc.metadata["size"] = list(getattr(pil_img, "size", (0, 0)))
            # FR52 EXIF metadata extract (DateTimeOriginal/Make/Model)
            exif_section: List[str] = []
            try:
                exif_data = pil_img._getexif() if hasattr(pil_img, "_getexif") else None
                if exif_data:
                    BY_TAG = {ExifTags.TAGS.get(k, k): v for k, v in exif_data.items()}
                    dt = BY_TAG.get("DateTimeOriginal") or BY_TAG.get("DateTime")
                    if dt:
                        exif_section.append(f"Data scatto: {dt}")
                        doc.metadata["exif_datetime"] = str(dt)
                    make = BY_TAG.get("Make")
                    model = BY_TAG.get("Model")
                    if make or model:
                        dev = " ".join(str(x) for x in (make, model) if x).strip()
                        if dev:
                            exif_section.append(f"Dispositivo: {dev}")
                            doc.metadata["exif_device"] = dev
            except Exception:  # noqa: BLE001
                pass

            doc.needs_ocr = True
            doc.ocr_available = bool(self.ocr and self.ocr.is_available)
            if run_ocr and self.ocr is not None:
                ocr_out = self.ocr.ocr_pil_images([pil_img])
                doc.used_ocr = ocr_out.used_ocr
                for err in ocr_out.errors:
                    doc.errors.append(err)
                if ocr_out.pages:
                    op = ocr_out.pages[0]
                    doc.full_text = op.text or ""
                    conf = op.confidence_avg
                    for w in op.words:
                        doc.spans.append(TextSpan(
                            text=w.text, page=0, source_kind="ocr",
                            ocr_confidence=w.confidence or conf,
                        ))
                    if not doc.spans and op.text:
                        doc.spans.append(TextSpan(text=op.text, page=0, source_kind="ocr",
                                                  ocr_confidence=conf))
            else:
                doc.full_text = ""
            if exif_section:
                header = "\n".join(exif_section)
                if doc.full_text:
                    doc.full_text = header + "\n\n" + doc.full_text
                else:
                    doc.full_text = header
        except Exception as exc:  # noqa: BLE001
            doc.errors.append(f"Errore immagine: {exc}")
        return doc

    # --------------------------------------------------------------
    # FR56: async batch folder loader threading worker + callbacks
    # --------------------------------------------------------------
    def load_folder_async(
        self,
        folder: Path,
        *,
        recursive: bool = True,
        on_progress: Optional[Callable[[int, int, Path, str], None]] = None,
        on_done: Optional[Callable[[List[LoadedDocument], List[Tuple[Path, str]]], None]] = None,
    ) -> Any:
        """Kick off Thread worker. Returns threading.Thread (caller can join)."""
        import threading
        def _worker():
            folder_loc = Path(folder)
            if not folder_loc.is_dir():
                if on_done:
                    try:
                        on_done([], [(folder_loc, f"Cartella non valida: {folder_loc}")])
                    except Exception:  # noqa: BLE001
                        pass
                return
            files: List[Path] = []
            iterator = folder_loc.rglob("*") if recursive else folder_loc.glob("*")
            for p in iterator:
                if not p.is_file():
                    continue
                ext = p.suffix.lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                files.append(p)
            files.sort()
            total = len(files)
            successes: List[LoadedDocument] = []
            failures: List[Tuple[Path, str]] = []
            for idx, f in enumerate(files, 1):
                status = "ok"
                try:
                    if on_progress:
                        try:
                            on_progress(idx, total, f, "processing")
                        except Exception:  # noqa: BLE001
                            pass
                    doc = self.load_file(f)
                    successes.append(doc)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("Scarto file %s: %s", f, exc)
                    failures.append((f, str(exc)))
                    status = "error"
                if on_progress:
                    try:
                        on_progress(idx, total, f, status)
                    except Exception:  # noqa: BLE001
                        pass
            if on_done:
                try:
                    on_done(successes, failures)
                except Exception as exc:  # noqa: BLE001
                    LOG.warning("on_done callback fallito: %s", exc)
        t = threading.Thread(target=_worker, name="docloader-folder", daemon=True)
        t.start()
        return t
