"""DOCX parser / text extractor / placeholder scanner.

Uses python-docx. Handles the known Word behavior that splits placeholders
like {{impianto}} across multiple <w:r> runs, so a simple ``run.text`` lookup
would miss them. The scanner reconstructs paragraph text, finds placeholders
and can optionally rewrite runs in-place.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from defusedxml import ElementTree as DET
except Exception:  # pragma: no cover - defusedxml always installed per requirements
    DET = None  # type: ignore[assignment]

import docx
from docx.document import Document as DocxDocument
from docx.oxml.ns import qn
from docx.table import _Cell, Table
from docx.text.paragraph import Paragraph


_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*\}\}")


LOG = logging.getLogger(__name__)


@dataclass
class DocxExtraction:
    full_text: str
    paragraphs: List[str] = field(default_factory=list)
    tables: List[List[List[str]]] = field(default_factory=list)  # table->row->cell
    placeholders: List[str] = field(default_factory=list)
    meta: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def load_document(path: Path) -> DocxDocument:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"DOCX non trovato: {path}")
    return docx.Document(str(path))


def extract_text(doc: DocxDocument) -> DocxExtraction:
    out = DocxExtraction(full_text="")
    for p in doc.paragraphs:
        t = p.text or ""
        out.paragraphs.append(t)
    for tbl in doc.tables:
        matrix: List[List[str]] = []
        for row in tbl.rows:
            row_cells: List[str] = []
            for cell in row.cells:
                row_cells.append(cell.text or "")
            matrix.append(row_cells)
        out.tables.append(matrix)

    chunks: List[str] = list(out.paragraphs)
    for matrix in out.tables:
        for row in matrix:
            chunks.append(" | ".join(c.strip() for c in row))
    out.full_text = "\n".join(chunks)
    placeholders = set(_PLACEHOLDER_RE.findall(out.full_text))
    out.placeholders = sorted(placeholders)
    out.meta["paragraph_count"] = len(out.paragraphs)
    out.meta["table_count"] = len(out.tables)
    out.meta["max_paragraph_chars"] = max((len(p) for p in out.paragraphs), default=0)
    table_cells_total = sum(len(r) for m in out.tables for r in m)
    out.meta["table_cells_total"] = table_cells_total
    if len(out.paragraphs) > 10_000:
        LOG.warning("DOCX extract_text: %s paragraphs (>10k guardrail)", len(out.paragraphs))
    return out


# ---------------------------------------------------------------------------
# Robust placeholder replacement inside DOCX
# ---------------------------------------------------------------------------
def _iter_block_items(doc: DocxDocument) -> Iterable[Any]:
    """Yield paragraphs and tables in document order (including inside sections)."""
    body = doc.element.body
    for child in body.iterchildren():
        tag = child.tag.split("}", 1)[-1]
        if tag == "p":
            yield Paragraph(child, doc)
        elif tag == "tbl":
            yield Table(child, doc)


def _iter_all_paragraphs(doc: DocxDocument) -> Iterable[Paragraph]:
    for block in _iter_block_items(doc):
        if isinstance(block, Paragraph):
            yield block
        elif isinstance(block, Table):
            for row in block.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        yield p


def _replace_in_paragraph(paragraph: Paragraph, replacements: Dict[str, str]) -> None:
    """Apply replacements to a paragraph, handling Word split-run fragmentation.

    Strategy: read the full paragraph text, build a list of (placeholder, start, end)
    by regex; build a linear view of runs with (run, local_start, local_end) offsets;
    for each match overwrite the characters in the touched runs, clearing unused
    portions and putting the full replacement in the first touched run.
    """
    if not paragraph.runs:
        return
    full = "".join(r.text for r in paragraph.runs)
    matches = list(_PLACEHOLDER_RE.finditer(full))
    if not matches:
        return

    # Build run offsets map
    run_spans: List[Tuple[Any, int, int]] = []
    cursor = 0
    for run in paragraph.runs:
        length = len(run.text)
        run_spans.append((run, cursor, cursor + length))
        cursor += length

    # Process matches in reverse so earlier offsets remain valid
    for m in reversed(matches):
        key = m.group(1)
        if key not in replacements:
            continue
        repl = replacements[key]
        start, end = m.start(), m.end()

        # Find runs touched by [start, end)
        first_idx = None
        last_idx = None
        for idx, (_, rs, re_) in enumerate(run_spans):
            if not (re_ <= start or rs >= end):
                if first_idx is None:
                    first_idx = idx
                last_idx = idx
        if first_idx is None:
            continue

        first_run = run_spans[first_idx][0]
        # First run: piece before start + replacement + piece after end
        _, first_rs, first_re = run_spans[first_idx]
        _, last_rs, last_re = run_spans[last_idx]
        pre = first_run.text[: max(0, start - first_rs)]
        post_last_run = run_spans[last_idx][0]
        post = post_last_run.text[max(0, end - last_rs):]
        first_run.text = pre + repl + post
        # Clear middle runs
        for idx in range(first_idx + 1, last_idx + 1):
            run_spans[idx][0].text = ""


def apply_placeholders(doc: DocxDocument, values: Dict[str, Any]) -> None:
    """Replace all {{key}} tokens with string(key), doing its best across runs.

    For values that are lists, they are joined by ``\\n``.
    For nested dicts (e.g. componenti_controllati), flattening is delegated to
    exporters; here only top-level keys are supported.
    """
    flat: Dict[str, str] = {}
    for key, value in values.items():
        if isinstance(value, list):
            flat[key] = "\n".join(_to_display_line(v) for v in value) if value else ""
        elif isinstance(value, dict):
            flat[key] = "\n".join(
                f"- {k}: {_to_display_line(v)}" for k, v in value.items()
            )
        else:
            flat[key] = "" if value is None else str(value)

    import time as _time
    _t0 = _time.perf_counter()
    cnt = 0
    last_report = 0
    for paragraph in _iter_all_paragraphs(doc):
        _replace_in_paragraph(paragraph, flat)
        cnt += 1
        if cnt >= last_report + 2000:
            LOG.info("DOCX apply_placeholders: %s paragraphs processed ...", cnt)
            last_report = cnt
    elapsed = _time.perf_counter() - _t0
    if cnt > 5000:
        LOG.info("DOCX apply_placeholders: %s paragraphs total (%.2fs)", cnt, elapsed)


def _to_display_line(value: Any) -> str:
    if isinstance(value, dict):
        return " ; ".join(f"{k}={v}" for k, v in value.items())
    return "" if value is None else str(value)
