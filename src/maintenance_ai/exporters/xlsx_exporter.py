"""XLSX exporter: copy an XLSX template then apply mapping -> cells."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any, Dict, List

from ..parsers.xlsx_parser import apply_mapping, load_workbook_safe


def export_xlsx(
    template_path: Path,
    output_path: Path,
    mapping: Dict[str, Any],
    values: Dict[str, Any],
) -> List[str]:
    template_path = Path(template_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(template_path, output_path)
    wb = load_workbook_safe(output_path)
    applied = apply_mapping(wb, mapping, values)
    wb.save(str(output_path))
    wb.close()
    return applied
