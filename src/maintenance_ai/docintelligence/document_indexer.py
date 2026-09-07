"""DocumentIndexer: chunking + storage in SQLite document_chunks."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ..db import Database
from .document_loader import LoadedDocument, TextSpan


TOKEN_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][\w\-]*", re.UNICODE)


def _tokens(text: str, limit: int = 200) -> List[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "")][:limit]


@dataclass
class Chunk:
    chunk_index: int
    chunk_text: str
    file_path: Path
    file_sha256: str
    page: Optional[int] = None
    sheet: Optional[str] = None
    cell_ref: Optional[str] = None
    paragraph_index: Optional[int] = None
    keywords: List[str] = field(default_factory=list)
    span_source_kind: str = ""
    ocr_confidence: Optional[float] = None


class DocumentIndexer:
    """Chunk LoadedDocument into ~300-char overlapping pieces, store in DB."""

    CHUNK_CHARS = 500
    OVERLAP_CHARS = 80

    def __init__(self, db: Database):
        self.db = db

    # --------------------------------------------------------------
    def index_document(self, doc: LoadedDocument) -> List[Chunk]:
        if not doc.file_sha256:
            raise ValueError("LoadedDocument.file_sha256 vuoto")
        chunks = self._chunk_document(doc)
        # Store
        db_rows: List[Dict[str, Any]] = []
        for ch in chunks:
            db_rows.append({
                "chunk_index": ch.chunk_index,
                "page": ch.page,
                "sheet": ch.sheet,
                "cell_ref": ch.cell_ref,
                "paragraph_index": ch.paragraph_index,
                "chunk_text": ch.chunk_text,
                "keywords_json": ch.keywords,
            })
        try:
            self.db.store_chunks(doc.file_sha256, db_rows)
        except Exception:  # noqa: BLE001
            pass
        return chunks

    def index_many(self, docs: Iterable[LoadedDocument]) -> Dict[str, List[Chunk]]:
        out: Dict[str, List[Chunk]] = {}
        for doc in docs:
            try:
                out[doc.file_sha256] = self.index_document(doc)
            except Exception:  # noqa: BLE001
                continue
        return out

    # --------------------------------------------------------------
    def _chunk_document(self, doc: LoadedDocument) -> List[Chunk]:
        if doc.spans:
            return self._chunk_by_spans(doc)
        # Fallback: full_text chunking, no provenance
        return self._chunk_by_fulltext(doc)

    def _chunk_by_spans(self, doc: LoadedDocument) -> List[Chunk]:
        chunks: List[Chunk] = []
        buffer: List[str] = []
        buffer_len = 0
        idx = 0
        last_span: Optional[TextSpan] = None
        for span in doc.spans:
            t = span.text or ""
            if not t.strip():
                continue
            if buffer_len + len(t) > self.CHUNK_CHARS and buffer:
                # Emit
                ct = "\n".join(buffer)
                chunks.append(Chunk(
                    chunk_index=idx,
                    chunk_text=ct,
                    file_path=doc.path,
                    file_sha256=doc.file_sha256,
                    page=last_span.page if last_span else None,
                    sheet=last_span.sheet if last_span else None,
                    cell_ref=last_span.cell if last_span else None,
                    paragraph_index=last_span.paragraph_index if last_span else None,
                    keywords=_tokens(ct),
                    span_source_kind=last_span.source_kind if last_span else "",
                    ocr_confidence=last_span.ocr_confidence if last_span else None,
                ))
                idx += 1
                # Keep overlap
                overlap_source = "\n".join(buffer)
                overlap_tail = overlap_source[-self.OVERLAP_CHARS:] if buffer else ""
                buffer = [overlap_tail] if overlap_tail else []
                buffer_len = sum(len(b) for b in buffer)
            buffer.append(t)
            buffer_len += len(t) + 1
            last_span = span
        # Flush
        if buffer:
            ct = "\n".join(buffer)
            chunks.append(Chunk(
                chunk_index=idx,
                chunk_text=ct,
                file_path=doc.path,
                file_sha256=doc.file_sha256,
                page=last_span.page if last_span else None,
                sheet=last_span.sheet if last_span else None,
                cell_ref=last_span.cell if last_span else None,
                paragraph_index=last_span.paragraph_index if last_span else None,
                keywords=_tokens(ct),
                span_source_kind=last_span.source_kind if last_span else "",
                ocr_confidence=last_span.ocr_confidence if last_span else None,
            ))
        return chunks

    def _chunk_by_fulltext(self, doc: LoadedDocument) -> List[Chunk]:
        chunks: List[Chunk] = []
        text = doc.full_text or ""
        if not text:
            return chunks
        idx = 0
        pos = 0
        total = len(text)
        while pos < total:
            end = min(total, pos + self.CHUNK_CHARS)
            ct = text[pos:end]
            chunks.append(Chunk(
                chunk_index=idx,
                chunk_text=ct,
                file_path=doc.path,
                file_sha256=doc.file_sha256,
                keywords=_tokens(ct),
            ))
            idx += 1
            if end >= total:
                break
            pos = end - self.OVERLAP_CHARS
            if pos <= 0:
                break
        return chunks
