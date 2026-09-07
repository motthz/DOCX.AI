"""PDFParser: estrazione testo nativa e pagina-per-pagina.

Priorità:
1. Estrazione testo nativa per pagina (pypdf)
2. Per pagine con testo troppo scarso: estrai immagini embedded dalla pagina
3. Se immagini presenti: passale a OCRService
4. Combina testo nativo + OCR per la pagina

Conserva:
- numero pagina,
- bounding box quando disponibile da pypdf (visit_text),
- sorgente testo per parola (native/OCR).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .ocr_service import OCRExtraction, OCRPage, OCRService, OCRWord


LOG = logging.getLogger(__name__)


@dataclass
class PDFPage:
    index: int
    native_text: str = ""
    ocr_text: str = ""
    has_images: bool = False
    images_count: int = 0
    ocr_ran: bool = False
    ocr_page: Optional[OCRPage] = None
    error: str = ""

    @property
    def text(self) -> str:
        parts = []
        if self.native_text.strip():
            parts.append(self.native_text)
        if self.ocr_text.strip():
            parts.append(self.ocr_text)
        return "\n".join(parts)


@dataclass
class PDFExtraction:
    pages: List[PDFPage] = field(default_factory=list)
    full_text: str = ""
    page_count: int = 0
    native_text_found: bool = False
    ocr_used: bool = False
    encrypted: bool = False
    needs_password: bool = False
    errors: List[str] = field(default_factory=list)

    def text_for_page(self, idx: int) -> str:
        if 0 <= idx < len(self.pages):
            return self.pages[idx].text
        return ""


class PDFParser:
    """Wrapper around pypdf + OCRService per il parsing PDF offline e CPU-only."""

    NATIVE_TEXT_THRESHOLD_CHARS = 40  # meno di questa soglia per pagina → tentativo OCR

    def __init__(self, ocr_service: Optional[OCRService] = None):
        self.ocr = ocr_service

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------
    def parse(self, path: Path, *, run_ocr: bool = True,
              max_pages: Optional[int] = None) -> PDFExtraction:
        path = Path(path)
        out = PDFExtraction()
        if not path.is_file():
            out.errors.append(f"File non trovato: {path}")
            return out
        reader: Any = None
        try:
            from pypdf import PdfReader  # lazy import
        except ImportError as exc:
            out.errors.append(f"Libreria pypdf non disponibile: {exc}")
            return out
        try:
            reader = PdfReader(str(path))
        except Exception as exc:  # noqa: BLE001
            out.errors.append(f"Impossibile aprire PDF: {exc}")
            return out
        try:
            if reader.is_encrypted:
                out.encrypted = True
                try:
                    ok = reader.decrypt("")
                    if not ok:
                        out.needs_password = True
                        out.errors.append("PDF protetto da password (password vuota fallita)")
                        return out
                except Exception as exc:  # noqa: BLE001
                    out.needs_password = True
                    out.errors.append(f"PDF protetto, errore decrypt: {exc}")
                    return out
        except Exception:  # noqa: BLE001
            # some builds don't expose is_encrypted cleanly
            pass

        out.page_count = len(reader.pages) if hasattr(reader, "pages") else 0
        limit_pages = max_pages if max_pages and max_pages > 0 else out.page_count
        ocr_input_images: List[Tuple[int, Any]] = []   # (page_idx, pil_image_or_None)

        for page_idx in range(min(out.page_count, limit_pages)):
            page_rec = PDFPage(index=page_idx)
            try:
                pypdf_page = reader.pages[page_idx]
            except Exception as exc:  # noqa: BLE001
                page_rec.error = f"Caricamento pagina fallito: {exc}"
                out.pages.append(page_rec)
                continue

            # Native text
            try:
                page_rec.native_text = (pypdf_page.extract_text() or "").strip()
                if page_rec.native_text:
                    out.native_text_found = True
            except Exception as exc:  # noqa: BLE001
                page_rec.error = f"Estrazione testo fallita: {exc}"

            # Collect images
            extracted_images = self._extract_page_images(pypdf_page)
            page_rec.images_count = len(extracted_images)
            page_rec.has_images = page_rec.images_count > 0

            out.pages.append(page_rec)

            # Decide if OCR is needed for this page
            if (
                run_ocr
                and self.ocr is not None
                and len(page_rec.native_text.strip()) < self.NATIVE_TEXT_THRESHOLD_CHARS
                and page_rec.has_images
            ):
                for pil_img in extracted_images:
                    ocr_input_images.append((page_idx, pil_img))

        # Run OCR in batch
        if run_ocr and self.ocr is not None and ocr_input_images:
            try:
                # Group per page (one page may produce multiple images)
                images_only = [img for _, img in ocr_input_images if img is not None]
                if images_only:
                    ocr_out = self.ocr.ocr_pil_images(images_only)
                    # Map results back to pages (rough 1:1 mapping, assume images_ordered)
                    cursor = 0
                    for (p_idx, _img), ocr_page in zip(ocr_input_images, ocr_out.pages):
                        if cursor >= len(ocr_out.pages):
                            break
                        rec_page = out.pages[p_idx]
                        if ocr_page.text:
                            if rec_page.ocr_text:
                                rec_page.ocr_text += "\n" + ocr_page.text
                            else:
                                rec_page.ocr_text = ocr_page.text
                            rec_page.ocr_ran = True
                            rec_page.ocr_page = ocr_page
                            out.ocr_used = True
                        cursor += 1
            except Exception as exc:  # noqa: BLE001
                out.errors.append(f"OCR batch fallito: {exc}")

        out.full_text = "\n".join(p.text for p in out.pages if p.text)
        return out

    # --------------------------------------------------------------
    # Image extraction: tries PIL via pypdf's /Resources/XObject
    # --------------------------------------------------------------
    def _extract_page_images(self, pypdf_page: Any) -> List[Any]:
        """Return a list of PIL.Image extracted from the page (possibly empty)."""
        out: List[Any] = []
        try:
            resources = pypdf_page.get("/Resources")
            if not resources:
                return out
            xobjects = resources.get("/XObject")
            if xobjects is None:
                return out
            xobjects_dict = xobjects.get_object() if hasattr(xobjects, "get_object") else xobjects
            if not hasattr(xobjects_dict, "items"):
                return out
            for _name, xobj_ref in xobjects_dict.items():
                try:
                    xobj = xobj_ref.get_object() if hasattr(xobj_ref, "get_object") else xobj_ref
                    subtype = xobj.get("/Subtype") if hasattr(xobj, "get") else None
                    if subtype != "/Image":
                        continue
                    img = self._pypdf_image_to_pil(xobj)
                    if img is not None:
                        out.append(img)
                except Exception:  # noqa: BLE001
                    continue
        except Exception:  # noqa: BLE001
            pass
        return out

    @staticmethod
    def _pypdf_image_to_pil(xobj: Any) -> Optional[Any]:
        try:
            from PIL import Image  # type: ignore
        except ImportError:
            return None
        try:
            data = xobj.get_data() if hasattr(xobj, "get_data") else None
            if data is None:
                return None
            width = int(xobj.get("/Width", 0) or 0)
            height = int(xobj.get("/Height", 0) or 0)
            if width <= 0 or height <= 0:
                return None
            color_space = xobj.get("/ColorSpace")
            if isinstance(color_space, list):
                color_space = color_space[0]
            mode: Optional[str] = None
            bits = int(xobj.get("/BitsPerComponent", 8) or 8)
            if color_space == "/DeviceRGB" and bits == 8:
                mode = "RGB"
            elif color_space == "/DeviceCMYK":
                mode = "CMYK"
            elif color_space == "/DeviceGray":
                mode = "L" if bits == 8 else "1"
            try:
                filter_ = xobj.get("/Filter")
                if isinstance(filter_, list):
                    filter_ = filter_[0]
                if filter_ == "/DCTDecode":
                    return Image.open(io.BytesIO(data))
                if mode is None:
                    return None
                return Image.frombytes(mode, (width, height), data)
            except Exception:  # noqa: BLE001
                return None
        except Exception:  # noqa: BLE001
            return None
