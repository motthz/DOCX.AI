"""DOCX exporter: copy a DOCX template then apply placeholders.

Keeps the original template file untouched on disk.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict

from ..parsers.docx_parser import apply_placeholders, load_document


def export_docx(
    template_path: Path,
    output_path: Path,
    values: Dict[str, Any],
) -> Path:
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, output_path)
    doc = load_document(output_path)
    apply_placeholders(doc, values)
    doc.save(str(output_path))
    return output_path
