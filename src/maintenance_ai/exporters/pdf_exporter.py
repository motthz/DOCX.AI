"""PDF exporter using ReportLab.

Renders the structured JSON data into a standard MaintenanceAI report layout.
This is NOT a pixel-perfect rendering of an arbitrary DOCX/XLSX; that would
require a real Office rendering engine. It is a deterministic, branded PDF
representation of the approved structured data.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    PageBreak,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


def _labelize(key: str) -> str:
    return key.replace("_", " ").strip().title()


LOG = logging.getLogger(__name__)


def _format_value(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, list):
        if not value:
            return "—"
        parts: List[str] = []
        for idx, item in enumerate(value, 1):
            if isinstance(item, dict):
                inner = "  ".join(f"{k}: {v}" for k, v in item.items())
                parts.append(f"{idx}. {inner}")
            else:
                parts.append(f"{idx}. {item}")
        return "\n".join(parts)
    if isinstance(value, dict):
        return "  ".join(f"{k}: {v}" for k, v in value.items())
    return str(value)


def _group_fields(schema_props: Dict[str, Any], data: Dict[str, Any]
                  ) -> Tuple[List[Tuple[str, Any]], List[Tuple[str, Any]]]:
    """Return (scalar_fields, list_fields).

    List fields (arrays of objects or strings) are rendered as separate tables.
    """
    scalars: List[Tuple[str, Any]] = []
    lists: List[Tuple[str, Any]] = []
    for key in schema_props.keys() if schema_props else data.keys():
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            lists.append((key, value))
        else:
            scalars.append((key, value))
    return scalars, lists


def _style_table_base() -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0d3b66")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 10),
        ("ALIGN", (0, 0), (-1, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#cccccc")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
         [colors.whitesmoke, colors.HexColor("#fafafa")]),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ])


def _build_list_table(title: str, value: Any) -> List[Any]:
    story: List[Any] = []
    story.append(Paragraph(
        f"<b>{_labelize(title)}</b>",
        ParagraphStyle(name="ListTitle", fontName="Helvetica-Bold",
                       fontSize=11, textColor=colors.HexColor("#0d3b66"),
                       spaceBefore=10, spaceAfter=4),
    ))
    if not value:
        story.append(Paragraph("Nessun elemento.",
                               ParagraphStyle(name="Empty", fontSize=9,
                                              textColor=colors.gray)))
        return story
    if isinstance(value[0], dict):
        keys = list(value[0].keys())
        header = [_labelize(k) for k in keys]
        rows = [header]
        for idx, row in enumerate(value):
            rows.append([_format_value(row.get(k, "")) for k in keys])
            # Split huge tables across pages every 80 data rows so platypus
            # doesn't try to render one giga-row outside page bounds.
            if idx > 0 and idx % 80 == 0:
                tbl = Table(rows, repeatRows=1, colWidths=None)
                tbl.setStyle(_style_table_base())
                story.append(tbl)
                story.append(PageBreak())
                rows = [header]
        tbl = Table(rows, repeatRows=1, colWidths=None)
        tbl.setStyle(_style_table_base())
        story.append(tbl)
    else:
        rows = [["#", "Elemento"]]
        for idx, row in enumerate(value, 1):
            rows.append([str(idx), _format_value(row)])
            if idx > 0 and idx % 200 == 0:
                tbl = Table(rows, repeatRows=1, colWidths=(1*cm, 15*cm))
                tbl.setStyle(_style_table_base())
                story.append(tbl)
                story.append(PageBreak())
                rows = [["#", "Elemento"]]
        tbl = Table(rows, repeatRows=1, colWidths=(1*cm, 15*cm))
        tbl.setStyle(_style_table_base())
        story.append(tbl)
    return story


def _insert_pagebreak_every(story: List[Any], every: int = 500) -> List[Any]:
    """Insert PageBreak() sentinel every N non-break flowables.

    ReportLab SimpleDocTemplate already splits oversized content across pages,
    but for extremely long stories (thousands of list rows / paragraphs) the
    layout engine can exceed reasonable time/memory without intermediate
    breaks. Inserting explicit PageBreak() sentinels keeps each page chunk
    small.
    """
    out: List[Any] = []
    count = 0
    for item in story:
        if isinstance(item, PageBreak):
            count = 0
            out.append(item)
            continue
        out.append(item)
        count += 1
        if count >= every:
            out.append(PageBreak())
            count = 0
    return out


def export_pdf(
    output_path: Path,
    data: Dict[str, Any],
    schema: Dict[str, Any] | None = None,
    *,
    report_id: str = "",
    module_name: str = "",
    review_notes: str = "",
) -> Path:
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    schema_props = schema.get("properties", {}) if schema else {}
    scalars, lists = _group_fields(schema_props, data)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.8 * cm,
        title=f"Rapporto {module_name or 'manutenzione'}",
        author="MaintenanceAI",
        subject=report_id or "",
    )

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                        fontSize=18, textColor=colors.HexColor("#0d3b66"), spaceAfter=4)
    meta_style = ParagraphStyle("Meta", parent=styles["Normal"], fontSize=9,
                                textColor=colors.gray, alignment=TA_CENTER,
                                spaceAfter=10)
    label_style = ParagraphStyle("Label", fontName="Helvetica-Bold",
                                 fontSize=10, textColor=colors.HexColor("#1f2937"))
    value_style = ParagraphStyle("Value", fontName="Helvetica",
                                 fontSize=10, textColor=colors.black, leading=13)

    story: List[Any] = []

    # Header
    story.append(Paragraph(
        f"Rapporto di {module_name or 'Manutenzione'}",
        h1,
    ))
    pieces = []
    if report_id:
        pieces.append(f"ID: {report_id}")
    pieces.append(f"Generato: {time.strftime('%Y-%m-%d %H:%M')}")
    pieces.append("MaintenanceAI")
    story.append(Paragraph(" &nbsp;|&nbsp; ".join(pieces), meta_style))
    story.append(Spacer(1, 0.3 * cm))

    # Scalar table (split every 60 data rows so long reports don't produce
    # a single 2000-row Table outside page bounds)
    header_row = ["Campo", "Valore"]
    scalar_chunk: List[List[Any]] = [header_row]
    for idx, (key, value) in enumerate(scalars, 1):
        scalar_chunk.append([
            Paragraph(_labelize(key), label_style),
            Paragraph(_format_value(value).replace("\n", "<br/>"), value_style),
        ])
        if idx % 60 == 0:
            tbl = Table(scalar_chunk, repeatRows=1, colWidths=(5.5 * cm, 11.5 * cm))
            tbl.setStyle(_style_table_base())
            story.append(tbl)
            story.append(PageBreak())
            scalar_chunk = [header_row]
    if len(scalar_chunk) > 1:
        tbl = Table(scalar_chunk, repeatRows=1, colWidths=(5.5 * cm, 11.5 * cm))
        tbl.setStyle(_style_table_base())
        story.append(tbl)

    # List tables
    for title, value in lists:
        story.extend(_build_list_table(title, value))

    # Review notes section (printed before the MaintenanceAI footer)
    if review_notes:
        story.append(Spacer(1, 0.5 * cm))
        rule = HRFlowable(width="100%", thickness=0.3,
                          lineCap=None, color=colors.HexColor("#cbd5e1"),
                          spaceBefore=6, spaceAfter=8)
        try:
            story.append(rule)
        except Exception:  # noqa: BLE001
            pass
        story.append(Paragraph(
            "<b>Note del revisore</b>",
            ParagraphStyle("NotesTitle", parent=styles["Normal"],
                           fontSize=10, fontName="Helvetica-Bold",
                           textColor=colors.HexColor("#0f172a"),
                           spaceAfter=4, spaceBefore=4),
        ))
        for para in [p.strip() for p in str(review_notes).splitlines() if p.strip()]:
            story.append(Paragraph(
                para,
                ParagraphStyle("NotesBody", parent=styles["Normal"],
                               fontSize=9, leading=12,
                               textColor=colors.HexColor("#334155"),
                               spaceAfter=3),
            ))

    # Footer note
    story.append(Spacer(1, 0.6 * cm))
    story.append(Paragraph(
        "Documento generato da MaintenanceAI su dati approvati. "
        "Il file JSON approvato è fonte ufficiale dei campi.",
        ParagraphStyle("Footer", fontSize=8, textColor=colors.gray,
                       alignment=TA_CENTER, spaceBefore=12),
    ))

    # Final guardrail: ensure very long stories get explicit page breaks
    # every 500 flowables so layout stays bounded.
    story = _insert_pagebreak_every(story, every=500)

    LOG.info("PDF export: building report with %s story flowables, module=%s",
             len(story), module_name or "-")
    doc.build(story)
    return output_path
