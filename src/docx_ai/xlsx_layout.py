"""Geometria e stile di un foglio Excel come lo mostra Excel (per l'editor visuale).

Larghezze di colonna e altezze di riga reali (anche nascoste), celle unite,
riempimenti, bordi, caratteri, allineamenti, a capo automatico, formati numerici
principali, colori del tema del file e immagini. Nessuna dipendenza da Tk: la
finestra disegna il risultato su un Canvas.
"""

from __future__ import annotations

import colorsys
import datetime as _dt
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

# tema predefinito di Office (ordine degli indici di tema di Excel)
DEFAULT_THEME = ["FFFFFF", "000000", "E7E6E6", "44546A", "4472C4", "ED7D31", "A5A5A5", "FFC000", "5B9BD5",
                 "70AD47", "0563C1", "954F72"]
BORDER_WIDTH = {"hair": 1, "thin": 1, "dotted": 1, "dashed": 1, "dashDot": 1, "dashDotDot": 1,
                "medium": 2, "mediumDashed": 2, "mediumDashDot": 2, "mediumDashDotDot": 2,
                "slantDashDot": 2, "thick": 3, "double": 3}
BORDER_DASH = {"dotted": (1, 2), "hair": (1, 1), "dashed": (4, 2), "mediumDashed": (6, 3),
               "dashDot": (4, 2, 1, 2), "mediumDashDot": (6, 3, 2, 3), "dashDotDot": (4, 2, 1, 2, 1, 2),
               "mediumDashDotDot": (6, 3, 2, 3, 2, 3), "slantDashDot": (6, 2, 2, 2)}
EMU_PX = 9525
MAX_ROWS, MAX_COLS = 1000, 80


@dataclass
class CellDraw:
    row: int
    col: int
    box: Tuple[int, int, int, int]
    text: str = ""
    fill: Optional[str] = None
    font: Tuple[str, int, bool, bool, bool, bool] = ("Calibri", 11, False, False, False, False)
    color: str = "#000000"
    halign: str = "left"
    valign: str = "bottom"
    wrap: bool = False
    borders: Dict[str, Tuple[int, str, Tuple[int, ...]]] = field(default_factory=dict)
    clip_right: int = 0  # fin dove il testo puo' estendersi (celle vuote a destra)


@dataclass
class SheetModel:
    xs: List[int]
    ys: List[int]
    cells: Dict[Tuple[int, int], CellDraw]
    covered: Set[Tuple[int, int]]
    merged: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)  # alto-sx -> basso-dx
    anchor: Dict[Tuple[int, int], Tuple[int, int]] = field(default_factory=dict)  # coperta -> alto-sx
    gridlines: bool = True
    images: List[Tuple[int, int, int, int, bytes]] = field(default_factory=list)

    @property
    def width(self) -> int:
        return self.xs[-1]

    @property
    def height(self) -> int:
        return self.ys[-1]


def theme_colors(wb: Any) -> List[str]:
    """Colori del tema del file (dk1, lt1, dk2, lt2, accent1-6, link) nell'ordine degli indici."""
    raw = getattr(wb, "loaded_theme", None)
    if not raw:
        return list(DEFAULT_THEME)
    try:
        text = raw.decode("utf-8", "ignore") if isinstance(raw, bytes) else str(raw)
        names = ["lt1", "dk1", "lt2", "dk2", "accent1", "accent2", "accent3", "accent4", "accent5",
                 "accent6", "hlink", "folHlink"]
        out = []
        for i, n in enumerate(names):
            m = re.search(r"<a:" + n + r">(.*?)</a:" + n + ">", text, re.S)
            val = None
            if m:
                v = re.search(r'(?:srgbClr val|lastClr)="([0-9A-Fa-f]{6})"', m.group(1))
                val = v.group(1) if v else None
            out.append(val or DEFAULT_THEME[i])
        return out
    except Exception:  # noqa: BLE001
        return list(DEFAULT_THEME)


def _tint(hex6: str, tint: float) -> str:
    r, g, b = (int(hex6[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, lum, s = colorsys.rgb_to_hls(r, g, b)
    lum = lum * (1 + tint) if tint < 0 else lum * (1 - tint) + tint
    r, g, b = colorsys.hls_to_rgb(h, max(0.0, min(1.0, lum)), s)
    return "".join(f"{round(x * 255):02X}" for x in (r, g, b))


def resolve_color(color: Any, theme: List[str], default: Optional[str] = None) -> Optional[str]:
    """Colore openpyxl (rgb, indicizzato, tema + tinta) -> '#RRGGBB'."""
    if color is None:
        return default
    try:
        ctype = getattr(color, "type", None)
        tint = float(getattr(color, "tint", 0) or 0)
        hex6: Optional[str] = None
        if ctype == "rgb" and isinstance(color.rgb, str):
            rgb = color.rgb
            if len(rgb) == 8 and rgb[:2] == "00" and rgb != "00000000":
                rgb = "FF" + rgb[2:]  # alcuni programmi scrivono alfa 00 per colori pieni
            if len(rgb) == 8 and rgb[:2] == "00":
                return default
            hex6 = rgb[-6:]
        elif ctype == "indexed" and color.indexed is not None:
            from openpyxl.styles.colors import COLOR_INDEX
            idx = int(color.indexed)
            if idx in (64, 65):  # colore di sistema (primo piano / sfondo)
                return default
            if 0 <= idx < len(COLOR_INDEX):
                hex6 = COLOR_INDEX[idx][-6:]
        elif ctype == "theme" and color.theme is not None:
            idx = int(color.theme)
            if 0 <= idx < len(theme):
                hex6 = theme[idx]
        if hex6 is None:
            return default
        if tint:
            hex6 = _tint(hex6, tint)
        return "#" + hex6.upper()
    except Exception:  # noqa: BLE001
        return default


def _col_widths(ws: Any, n_cols: int) -> List[int]:
    from openpyxl.utils import column_index_from_string
    fmt = ws.sheet_format
    # senza larghezza predefinita Excel usa 8,43 caratteri = 64 px (larghezza salvata 9,140625)
    base = fmt.defaultColWidth or (9.140625 if (fmt.baseColWidth or 8) == 8 else fmt.baseColWidth + 1.140625)
    widths = [base] * (n_cols + 1)
    hidden = [False] * (n_cols + 1)
    for key, dim in ws.column_dimensions.items():
        try:
            lo = dim.min or column_index_from_string(key)
            hi = dim.max or lo
        except Exception:  # noqa: BLE001
            continue
        for c in range(lo, min(hi, n_cols) + 1):
            if dim.width:
                widths[c] = dim.width
            if dim.hidden:
                hidden[c] = True
    # pixel come Excel con Calibri 11: trunc(((256*w + trunc(128/7))/256) * 7)
    return [0 if hidden[c] else int(((256 * widths[c] + 18) / 256) * 7) for c in range(n_cols + 1)]


def _row_heights(ws: Any, n_rows: int) -> List[int]:
    default = ws.sheet_format.defaultRowHeight or 15
    out = [0] * (n_rows + 1)
    for r in range(1, n_rows + 1):
        dim = ws.row_dimensions.get(r) if hasattr(ws.row_dimensions, "get") else None
        if dim is not None and dim.hidden:
            continue
        h = dim.height if dim is not None and dim.height else default
        out[r] = round(h * 96 / 72)
    return out


def display_value(value: Any, number_format: str = "General") -> str:
    """Testo come lo mostra Excel per i formati piu' comuni."""
    if value is None:
        return ""
    fmt = (number_format or "General")
    if isinstance(value, bool):
        return "VERO" if value else "FALSO"
    if isinstance(value, _dt.datetime):
        if value.time() == _dt.time(0, 0):
            return value.strftime("%d/%m/%Y")
        return value.strftime("%d/%m/%Y %H:%M")
    if isinstance(value, _dt.date):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, _dt.time):
        return value.strftime("%H:%M")
    if isinstance(value, (int, float)):
        pct = "%" in fmt
        v = value * 100 if pct else value
        m = re.search(r"0[.,](0+)", fmt)
        decimals = len(m.group(1)) if m else (None if fmt == "General" else 0)
        thousands = "#,##" in fmt or "#.##" in fmt
        if decimals is None:
            s = f"{v:.10g}"
            s = s.replace(".", ",")
        else:
            s = f"{v:,.{decimals}f}" if thousands else f"{v:.{decimals}f}"
            s = s.replace(",", "§").replace(".", ",").replace("§", ".")
        if "€" in fmt:
            s = s + " €" if fmt.rstrip().endswith("€") or "€]" in fmt else "€ " + s
        return s + ("%" if pct else "")
    return str(value)


def build(ws: Any, theme: Optional[List[str]] = None) -> SheetModel:
    theme = theme or list(DEFAULT_THEME)
    n_rows = min(max(ws.max_row + 5, 30), MAX_ROWS)
    n_cols = min(max(ws.max_column + 3, 10), MAX_COLS)
    cw = _col_widths(ws, n_cols)
    rh = _row_heights(ws, n_rows)
    xs = [0]
    for c in range(1, n_cols + 1):
        xs.append(xs[-1] + cw[c])
    ys = [0]
    for r in range(1, n_rows + 1):
        ys.append(ys[-1] + rh[r])

    merged: Dict[Tuple[int, int], Tuple[int, int]] = {}
    covered: Set[Tuple[int, int]] = set()
    anchor: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for rng in ws.merged_cells.ranges:
        if rng.min_row > n_rows or rng.min_col > n_cols:
            continue
        merged[(rng.min_row, rng.min_col)] = (min(rng.max_row, n_rows), min(rng.max_col, n_cols))
        for r in range(rng.min_row, min(rng.max_row, n_rows) + 1):
            for c in range(rng.min_col, min(rng.max_col, n_cols) + 1):
                if (r, c) != (rng.min_row, rng.min_col):
                    covered.add((r, c))
                    anchor[(r, c)] = (rng.min_row, rng.min_col)

    cells: Dict[Tuple[int, int], CellDraw] = {}
    for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, n_rows), max_col=min(ws.max_column, n_cols)):
        for cell in row:
            r, c = cell.row, cell.column
            if (r, c) in covered or not isinstance(r, int) or not isinstance(c, int):
                continue
            r2, c2 = merged.get((r, c), (r, c))
            box = (xs[c - 1], ys[r - 1], xs[c2], ys[r2])
            d = CellDraw(r, c, box)
            value = cell.value
            d.text = display_value(value, cell.number_format)
            f = cell.font
            if f is not None:
                d.font = (f.name or "Calibri", int(round(float(f.sz or 11))), bool(f.b), bool(f.i),
                          bool(f.u) and f.u != "none", bool(f.strike))
                d.color = resolve_color(f.color, theme, "#000000") or "#000000"
            fill = cell.fill
            if fill is not None and getattr(fill, "fill_type", None) == "solid":
                d.fill = resolve_color(fill.fgColor, theme) or resolve_color(fill.bgColor, theme)
            al = cell.alignment
            h = (al.horizontal if al is not None else None) or "general"
            if h == "general":
                h = "right" if isinstance(value, (int, float, _dt.date, _dt.time)) and \
                    not isinstance(value, bool) else ("center" if isinstance(value, bool) else "left")
            d.halign = {"centerContinuous": "center", "fill": "left", "justify": "left",
                        "distributed": "center"}.get(h, h)
            d.valign = {"center": "center", "top": "top", "justify": "top",
                        "distributed": "center"}.get((al.vertical if al is not None else None) or "bottom",
                                                     "bottom")
            d.wrap = bool(al is not None and al.wrap_text)
            b = cell.border
            if b is not None:
                for side in ("left", "right", "top", "bottom"):
                    sd = getattr(b, side, None)
                    style = getattr(sd, "style", None) if sd is not None else None
                    if style:
                        d.borders[side] = (BORDER_WIDTH.get(style, 1),
                                           resolve_color(sd.color, theme, "#000000") or "#000000",
                                           BORDER_DASH.get(style, ()))
            if d.text or d.fill or d.borders:
                cells[(r, c)] = d

    # testo che "sborda" nelle celle vuote a destra (come in Excel), se non va a capo
    for (r, c), d in cells.items():
        if not d.text or d.wrap or d.halign != "left":
            d.clip_right = d.box[2]
            continue
        right = d.box[2]
        cc = (merged.get((r, c), (r, c)))[1] + 1
        while cc <= n_cols and (r, cc) not in covered and not (cells.get((r, cc)) and cells[(r, cc)].text):
            right = xs[cc]
            cc += 1
            if right - d.box[2] > 1200:
                break
        d.clip_right = right

    images = []
    for img in getattr(ws, "_images", []) or []:
        try:
            anchor = img.anchor
            frm = anchor._from
            x = xs[min(frm.col, n_cols)] + int(frm.colOff / EMU_PX)
            y = ys[min(frm.row, n_rows)] + int(frm.rowOff / EMU_PX)
            ext = getattr(anchor, "ext", None)
            to = getattr(anchor, "to", None)
            if to is not None:
                w = xs[min(to.col, n_cols)] + int(to.colOff / EMU_PX) - x
                h = ys[min(to.row, n_rows)] + int(to.rowOff / EMU_PX) - y
            elif ext is not None:
                w, h = int(ext.width / EMU_PX), int(ext.height / EMU_PX)
            else:
                w, h = int(img.width), int(img.height)
            images.append((x, y, max(1, w), max(1, h), img._data()))
        except Exception:  # noqa: BLE001
            continue

    gridlines = True
    try:
        gridlines = ws.sheet_view.showGridLines is not False
    except Exception:  # noqa: BLE001
        pass
    return SheetModel(xs=xs, ys=ys, cells=cells, covered=covered, merged=merged, anchor=anchor,
                      gridlines=gridlines, images=images)


def cell_at(model: SheetModel, x: float, y: float) -> Optional[Tuple[int, int]]:
    """Cella (riga, colonna) nel punto (x, y) del foglio; per le celle unite quella in alto a sinistra."""
    import bisect
    if not (0 <= x < model.xs[-1] and 0 <= y < model.ys[-1]):
        return None
    c = bisect.bisect_right(model.xs, x)
    r = bisect.bisect_right(model.ys, y)
    if c < 1 or r < 1 or c >= len(model.xs) or r >= len(model.ys):
        return None
    return model.anchor.get((r, c), (r, c))


def cell_box(model: SheetModel, rc: Tuple[int, int]) -> Tuple[int, int, int, int]:
    r, c = rc
    r2, c2 = model.merged.get(rc, rc)
    return model.xs[c - 1], model.ys[r - 1], model.xs[c2], model.ys[r2]
