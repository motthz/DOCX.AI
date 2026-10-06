"""Anteprima fedele di un modulo Word per l'editor visuale.

Il documento viene impaginato da un vero motore (Microsoft Word o LibreOffice,
se installati) ed esportato in PDF: le pagine si vedono esattamente come in Word,
con caratteri, tabelle, immagini, intestazioni e margini originali.

Per il trascina e rilascio serve sapere dove si trova ogni carattere: il testo del
PDF (pypdfium2) viene allineato in ordine ai paragrafi del documento, cosi' ogni
punto della pagina corrisponde a (paragrafo, posizione nel testo). I paragrafi
vuoti ricevono nella copia da impaginare un segno invisibile (1 pt, bianco) che
non cambia l'impaginazione ma ne rivela la posizione; per le celle vuote si usa il
rettangolo della cella ricavato dai bordi della tabella.
"""

from __future__ import annotations

import base64
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

LOG = logging.getLogger(__name__)

MARK = "\u00a4"  # "¤": segno dei paragrafi vuoti nella copia da impaginare
_NORM = str.maketrans({"\u2019": "'", "\u2018": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-",
                       "\u2014": "-", "\u2011": "-", "\u00ad": "", "\u2026": "..."})
_CREATE_NO_WINDOW = 0x08000000

Box = Tuple[float, float, float, float]  # x0, y0, x1, y1 in punti, origine in alto a sinistra


# ---------------------------------------------------------------------------
# Paragrafi del documento (stesso ordine nell'originale e nella copia)
# ---------------------------------------------------------------------------
@dataclass
class ParaInfo:
    paragraph: Any
    story: str           # "body" oppure "header"
    in_cell: bool
    hint: str            # testo della cella a sinistra (per suggerire il nome del campo)


def paragraphs(doc: Any) -> List[ParaInfo]:
    """Tutti i paragrafi (corpo, tabelle annidate, caselle di testo, intestazioni)."""
    from docx.oxml.ns import qn
    from docx.text.paragraph import Paragraph
    from .parsers.docx_parser import _story_elements

    out: List[ParaInfo] = []
    tc_tag = qn("w:tc")
    for element, parent in _story_elements(doc):
        story = "body" if str(element.tag).endswith("}body") else "header"
        for p in element.iter(qn("w:p")):
            cell = next((a for a in p.iterancestors(tc_tag)), None)
            hint = ""
            if cell is not None:
                prev = cell.getprevious()
                while prev is not None and prev.tag != tc_tag:
                    prev = prev.getprevious()
                if prev is not None:
                    hint = "".join(t.text or "" for t in prev.iter(qn("w:t"))).strip()
            out.append(ParaInfo(Paragraph(p, parent), story, cell is not None, hint))
    return out


def marker(idx: int) -> str:
    """Segno unico del paragrafo vuoto ``idx`` (es. "¤1f¤"): un segno uguale per tutti
    faceva saltare l'allineamento quando un paragrafo vuoto non viene disegnato."""
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    code = ""
    n = idx
    while True:
        n, r = divmod(n, 36)
        code = digits[r] + code
        if not n:
            break
    return MARK + code + MARK


# ordine degli elementi di w:rPr (schema WordprocessingML): Word lo richiede
_RPR_ORDER = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
              "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
              "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
              "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"]


def _add_marker(p: Any, text: str) -> None:
    """Segno nel paragrafo vuoto che NON cambia l'impaginazione: stesso carattere e
    stessa dimensione del segno di paragrafo (quindi stessa altezza di riga), bianco e
    largo l'1% (non va a capo nemmeno in una cella stretta)."""
    import copy as _copy
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run = p.add_run(text)
    r = run._r
    pPr = p._p.pPr
    mark = pPr.find(qn("w:rPr")) if pPr is not None else None
    rpr = _copy.deepcopy(mark) if mark is not None else OxmlElement("w:rPr")
    for child in list(rpr):
        name = child.tag.split("}", 1)[-1]
        if name not in _RPR_ORDER or name in ("color", "w", "vanish", "webHidden", "specVanish", "u",
                                              "strike", "dstrike", "highlight", "shd", "bdr"):
            rpr.remove(child)  # w:ins, w:del, w:rPrChange e attributi visibili
    old = r.find(qn("w:rPr"))
    if old is not None:
        r.remove(old)
    r.insert(0, rpr)
    for name, val in (("color", "FFFFFF"), ("w", "1")):
        el = OxmlElement(f"w:{name}")
        el.set(qn("w:val"), val)
        pos = _RPR_ORDER.index(name)
        after = [c for c in rpr if c.tag.split("}", 1)[-1] in _RPR_ORDER[:pos]]
        if after:
            after[-1].addnext(el)
        else:
            rpr.insert(0, el)


def render_copy(doc: Any) -> bytes:
    """Copia del documento da impaginare: identica, con il segno nei paragrafi vuoti."""
    import docx

    buf = io.BytesIO()
    doc.save(buf)
    copy = docx.Document(io.BytesIO(buf.getvalue()))
    for idx, info in enumerate(paragraphs(copy)):
        p = info.paragraph
        if not p.text:
            _add_marker(p, marker(idx))
    out = io.BytesIO()
    copy.save(out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# Motori di impaginazione
# ---------------------------------------------------------------------------
_WORD_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$w = New-Object -ComObject Word.Application
$w.Visible = $false
$w.DisplayAlerts = 0
try { $w.Options.SaveNormalPrompt = $false } catch {}
[Console]::Out.WriteLine('READY'); [Console]::Out.Flush()
while ($true) {
  $line = [Console]::In.ReadLine()
  if ($line -eq $null -or $line -eq 'QUIT') { break }
  $p = $line.Split('|')
  $src = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($p[0]))
  $dst = [Text.Encoding]::Unicode.GetString([Convert]::FromBase64String($p[1]))
  try {
    $d = $w.Documents.Open($src, $false, $true, $false)
    $d.ExportAsFixedFormat($dst, 17)
    $d.Close(0)
    [Console]::Out.WriteLine('OK')
  } catch { [Console]::Out.WriteLine('ERR ' + $_.Exception.Message) }
  [Console]::Out.Flush()
}
try { $w.Quit() } catch {}
"""


def _word_installed() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


def _soffice_path() -> Optional[str]:
    found = shutil.which("soffice") or shutil.which("soffice.exe")
    if found:
        return found
    if sys.platform == "win32":
        try:
            import winreg
            for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(root, r"SOFTWARE\LibreOffice\UNO\InstallPath") as k:
                        base_dir = Path(winreg.QueryValueEx(k, "")[0])
                        for exe in ("soffice.com", "soffice.exe"):  # .com attende la fine
                            if (base_dir / exe).is_file():
                                return str(base_dir / exe)
                except OSError:
                    pass
        except ImportError:
            pass
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            for exe in ("soffice.com", "soffice.exe"):
                p = Path(base) / "LibreOffice" / "program" / exe
                if p.is_file():
                    return str(p)
    for p in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
              "/Applications/LibreOffice.app/Contents/MacOS/soffice"):
        if Path(p).is_file():
            return p
    return None


class Converter:
    """DOCX -> PDF con Word (processo riutilizzato) o LibreOffice. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._word: Optional[subprocess.Popen] = None
        self._word_ok = _word_installed()
        self._word_failures = 0
        self._soffice = _soffice_path()
        self._lo_profile = Path(tempfile.mkdtemp(prefix="docxai_lo_"))

    @property
    def available(self) -> bool:
        return self._word_ok or bool(self._soffice)

    @property
    def engine(self) -> str:
        return "Microsoft Word" if self._word_ok else ("LibreOffice" if self._soffice else "")

    def can_convert(self, suffix: str) -> bool:
        """Word impagina i .docx; LibreOffice anche i fogli Excel."""
        if suffix.lower() == ".docx":
            return self.available
        return bool(self._soffice)

    def convert(self, docx_path: Path, pdf_path: Path, timeout: float = 120.0) -> None:
        with self._lock:
            if self._word_ok and Path(docx_path).suffix.lower() == ".docx":
                try:
                    self._convert_word(docx_path, pdf_path, timeout)
                    return
                except Exception as exc:  # noqa: BLE001 - si prova LibreOffice
                    LOG.warning("Impaginazione con Word non riuscita: %s", exc)
                    self._stop_word()
                    self._word_failures += 1
                    if self._word_failures >= 2:
                        self._word_ok = False  # Word non utilizzabile su questo PC: non si riprova
                    if not self._soffice:
                        raise
            if self._soffice:
                self._convert_lo(docx_path, pdf_path, timeout)
                return
            raise RuntimeError("Nessun motore di impaginazione (Word o LibreOffice) disponibile")

    def _convert_word(self, src: Path, dst: Path, timeout: float) -> None:
        if self._word is None or self._word.poll() is not None:
            # -EncodedCommand: non e' un file di script, quindi i criteri aziendali sugli
            # script (es. AllSigned) non lo bloccano
            encoded = base64.b64encode(_WORD_SCRIPT.encode("utf-16-le")).decode("ascii")
            self._word = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                encoding="utf-8", errors="replace",
                creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            if self._readline(timeout) != "READY":
                raise RuntimeError("Word non si avvia")

        def b64(p: Path) -> str:
            return base64.b64encode(str(Path(p).resolve()).encode("utf-16-le")).decode("ascii")
        assert self._word is not None and self._word.stdin is not None
        self._word.stdin.write(f"{b64(src)}|{b64(dst)}\n")
        self._word.stdin.flush()
        reply = self._readline(timeout)
        if reply != "OK" or not Path(dst).is_file():
            raise RuntimeError(reply or "nessuna risposta da Word")

    def _readline(self, timeout: float) -> str:
        proc = self._word
        assert proc is not None and proc.stdout is not None
        box: List[str] = []
        th = threading.Thread(target=lambda: box.append(proc.stdout.readline()), daemon=True)  # type: ignore[union-attr]
        th.start()
        th.join(timeout)
        if th.is_alive():
            self._stop_word()
            raise TimeoutError("Word non risponde")
        return (box[0] if box else "").strip()

    def _convert_lo(self, src: Path, dst: Path, timeout: float) -> None:
        outdir = Path(tempfile.mkdtemp(prefix="docxai_lo_out_"))
        try:
            cmd = [str(self._soffice), "--headless", "--norestore", "--nolockcheck",
                   f"-env:UserInstallation={self._lo_profile.resolve().as_uri()}",
                   "--convert-to", "pdf", "--outdir", str(outdir), str(src)]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW if sys.platform == "win32" else 0, check=False)
            out = outdir / (Path(src).stem + ".pdf")
            deadline = time.monotonic() + 20  # soffice.exe puo' tornare prima di aver finito
            while not out.is_file() and time.monotonic() < deadline:
                time.sleep(0.3)
            if not out.is_file():
                raise RuntimeError("LibreOffice non ha prodotto il PDF")
            shutil.move(str(out), str(dst))
        finally:
            shutil.rmtree(outdir, ignore_errors=True)

    def _stop_word(self) -> None:
        proc, self._word = self._word, None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.write("QUIT\n")
                proc.stdin.flush()
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        with self._lock:
            self._stop_word()
        shutil.rmtree(self._lo_profile, ignore_errors=True)


_CONVERTER: Optional[Converter] = None


def converter() -> Converter:
    global _CONVERTER
    if _CONVERTER is None:
        _CONVERTER = Converter()
    return _CONVERTER


def shutdown() -> None:
    global _CONVERTER
    if _CONVERTER is not None:
        _CONVERTER.close()
        _CONVERTER = None


# ---------------------------------------------------------------------------
# Posizione dei paragrafi sulle pagine
# ---------------------------------------------------------------------------
@dataclass
class ParaLayout:
    page: int
    boxes: Dict[int, Box] = field(default_factory=dict)  # offset nel testo -> rettangolo
    area: Optional[Box] = None                           # paragrafo vuoto: riga o cella


@dataclass
class DocLayout:
    sizes: List[Tuple[float, float]]
    paras: Dict[int, ParaLayout]
    content_bottom: Tuple[int, float] = (0, 0.0)          # (pagina, y) dell'ultimo testo
    lines: List[List[Box]] = field(default_factory=list)  # bordi di tabella per pagina

    def chars_on(self, page: int) -> List[Tuple[int, int, Box]]:
        return [(i, off, b) for i, pl in self.paras.items() if pl.page == page
                for off, b in pl.boxes.items()]


def _norm(ch: str) -> str:
    return ch.translate(_NORM).casefold()


def _stream(pdf: Any) -> Tuple[List[Tuple[str, int, Box]], List[Tuple[float, float]], List[List[Box]]]:
    import pypdfium2.raw as raw

    chars: List[Tuple[str, int, Box]] = []
    sizes: List[Tuple[float, float]] = []
    lines: List[List[Box]] = []
    for pi in range(len(pdf)):
        page = pdf[pi]
        w, h = page.get_size()
        sizes.append((w, h))
        tp = page.get_textpage()
        for i in range(tp.count_chars()):
            code = raw.FPDFText_GetUnicode(tp.raw, i)
            ch = chr(code) if code else ""
            if not ch or ch.isspace() or ch in "\x00\x02\ufffe\uffff":
                continue
            try:
                left, bottom, right, top = tp.get_charbox(i)
            except Exception:  # noqa: BLE001
                continue
            for c in _norm(ch):
                chars.append((c, pi, (left, h - top, right, h - bottom)))
        page_lines: List[Box] = []
        try:
            for obj in page.get_objects():
                if obj.type != raw.FPDF_PAGEOBJ_PATH:
                    continue
                left, bottom, right, top = obj.get_bounds()
                bw, bh = right - left, top - bottom
                if (bw < 3 and bh > 4) or (bh < 3 and bw > 4):
                    page_lines.append((left, h - top, right, h - bottom))
        except Exception:  # noqa: BLE001
            pass
        lines.append(page_lines)
        tp.close()
        page.close()
    return chars, sizes, lines


def _cell_around(lines: List[Box], x: float, y: float) -> Optional[Box]:
    """Rettangolo della cella di tabella che contiene il punto (dai bordi disegnati)."""
    vert = [b for b in lines if b[2] - b[0] < 3 and b[1] - 1 <= y <= b[3] + 1]
    hor = [b for b in lines if b[3] - b[1] < 3 and b[0] - 1 <= x <= b[2] + 1]
    lefts = [b[2] for b in vert if b[2] <= x + 0.5]
    rights = [b[0] for b in vert if b[0] >= x + 0.5]
    tops = [b[3] for b in hor if b[3] <= y + 0.5]
    bottoms = [b[1] for b in hor if b[1] >= y + 0.5]
    if not (lefts and rights and tops and bottoms):
        return None
    box = (max(lefts), max(tops), min(rights), min(bottoms))
    if box[2] - box[0] < 6 or box[3] - box[1] < 6:
        return None
    return box


def snapshot(infos: List[ParaInfo]) -> List[Tuple[str, str, bool]]:
    """(testo, storia, in cella) dei paragrafi: dati semplici da passare a un thread."""
    return [(i.paragraph.text, i.story, i.in_cell) for i in infos]


def build_layout(pdf_path: Path, infos: List[Tuple[str, str, bool]], window: int = 4000) -> DocLayout:
    """Allinea il testo del PDF ai paragrafi (in ordine) e restituisce le posizioni.
    ``infos``: vedi :func:`snapshot`."""
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        chars, sizes, lines = _stream(pdf)
    finally:
        pdf.close()
    text = "".join(c for c, _p, _b in chars)

    def needle_of(source: str) -> Tuple[str, List[int]]:
        cs: List[str] = []
        offs: List[int] = []
        for off, ch in enumerate(source):
            if ch.isspace():
                continue
            for c in _norm(ch):
                cs.append(c)
                offs.append(off)
        return "".join(cs), offs

    # 1) paragrafi vuoti: il loro segno e' unico, si trovano ovunque
    found: Dict[int, Tuple[int, str, List[int]]] = {}
    for idx, (ptext, _story, _cell) in enumerate(infos):
        if not ptext:
            needle, offs = needle_of(marker(idx))
            pos = text.find(needle)
            if pos >= 0:
                found[idx] = (pos, needle, offs)
    anchors = sorted((pos, idx) for idx, (pos, _n, _o) in found.items())

    def next_anchor(idx: int, after: int) -> int:
        for pos, i in anchors:
            if i > idx and pos >= after:
                return pos
        return len(text)

    # 2) paragrafi con testo, in ordine: cercati tra la posizione corrente e il segno
    #    del paragrafo vuoto successivo (cosi' un paragrafo non trovato non fa saltare
    #    l'allineamento); se non c'e' li', un testo unico nel documento va bene ovunque
    ptr = 0
    for idx, (ptext, story, _cell) in enumerate(infos):
        if not ptext:
            if idx in found and story == "body":
                ptr = max(ptr, found[idx][0] + len(found[idx][1]))
            continue
        needle, offs = needle_of(ptext)
        if not needle:
            continue
        pos = -1
        if story == "body":
            limit = min(next_anchor(idx, ptr), ptr + window + len(needle))
            pos = text.find(needle, ptr, limit + len(needle))
        if pos < 0:
            first = text.find(needle)
            if first >= 0 and (story != "body" or text.find(needle, first + 1) < 0):
                pos = first  # intestazioni (prima pagina) o testo che compare una sola volta
            if pos >= 0 and story == "body" and pos >= ptr:
                ptr = pos + len(needle)
        elif story == "body":
            ptr = pos + len(needle)
        if pos >= 0:
            found[idx] = (pos, needle, offs)

    paras: Dict[int, ParaLayout] = {}
    for idx, (pos, needle, offs) in found.items():
        empty = not infos[idx][0]
        page = chars[pos][1]
        pl = ParaLayout(page=page)
        for k, off in enumerate(offs):
            _ch, pg, box = chars[pos + k]
            if pg != page:
                continue  # il paragrafo continua sulla pagina dopo: si usa la prima parte
            prev = pl.boxes.get(off)
            pl.boxes[off] = box if prev is None else (min(prev[0], box[0]), min(prev[1], box[1]),
                                                      max(prev[2], box[2]), max(prev[3], box[3]))
        if empty:
            xs0 = [b[0] for b in pl.boxes.values()] or [0.0]
            ys1 = [b[3] for b in pl.boxes.values()] or [0.0]
            pl.boxes = {}
            mx0, base = min(xs0), max(ys1)
            cell = _cell_around(lines[page], mx0 + 0.5, base - 2) if infos[idx][2] else None
            if cell is None:
                width = sizes[page][0]
                right = width - mx0 if mx0 < width / 2 else width - 36
                cell = (mx0, base - 12, max(mx0 + 60, right), base + 3)
            pl.area = cell
        paras[idx] = pl
    bottom = (0, 0.0)
    for _c, pg, box in chars:
        if (pg, box[3]) > bottom:
            bottom = (pg, box[3])
    return DocLayout(sizes=sizes, paras=paras, content_bottom=bottom, lines=lines)


def locate(layout: DocLayout, page: int, x: float, y: float) -> Optional[Tuple[int, int]]:
    """(indice paragrafo, offset) sotto il punto (x, y) della pagina, in punti."""
    best: Optional[Tuple[float, int, int]] = None
    for idx, pl in layout.paras.items():
        if pl.page != page:
            continue
        if pl.area is not None:
            a = pl.area
            if a[0] <= x <= a[2] and a[1] <= y <= a[3]:
                return idx, 0
        for off, (x0, y0, x1, y1) in pl.boxes.items():
            if not (y0 - 3 <= y <= y1 + 3):
                continue
            if x0 <= x <= x1:
                return idx, off + (1 if x > (x0 + x1) / 2 else 0)
            dist = x0 - x if x < x0 else x - x1
            cand = (dist, idx, off if x < x0 else off + 1)
            if best is None or cand < best:
                best = cand
    if best is not None and best[0] <= 60:
        return best[1], best[2]
    # dentro una cella di tabella con del testo: alla fine di quel testo
    for idx, pl in layout.paras.items():
        if pl.page != page or not pl.boxes:
            continue
        x0, y0, x1, y1 = next(iter(pl.boxes.values()))
        cell = _cell_around(layout.lines[page] if page < len(layout.lines) else [], x0 + 0.5, (y0 + y1) / 2)
        if cell and cell[0] <= x <= cell[2] and cell[1] <= y <= cell[3]:
            return idx, max(pl.boxes) + 1
    return None


def span_boxes(pl: ParaLayout, start: int, end: int) -> List[Box]:
    """Rettangoli (uno per riga) del testo [start, end) di un paragrafo."""
    rows: List[Box] = []
    for off in sorted(o for o in pl.boxes if start <= o < end):
        b = pl.boxes[off]
        if rows and abs(rows[-1][3] - b[3]) < 3 and b[0] >= rows[-1][0] - 1:
            r = rows[-1]
            rows[-1] = (r[0], min(r[1], b[1]), max(r[2], b[2]), max(r[3], b[3]))
        else:
            rows.append(b)
    return rows
