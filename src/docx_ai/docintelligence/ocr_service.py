"""OCRService: estrazione testo da immagini/PDF scannerizzati.

Strategia di estrazione (in ordine):
1. Prima tenta estrazione nativa (il chiamante la fa sempre prima per i PDF)
2. Se il testo estratto è vuoto o quasi vuoto, usa OCR
3. OCR tier 1: Windows.Media.Ocr tramite Win32 ctypes (Win10+, nessun download, CPU)
4. OCR tier 2: Tesseract portatile in runtime/tesseract/ se presente
5. Fallback: restituisce testo vuoto ma segnala lo stato in `used_ocr` e `ocr_available`

Preserva quando possibile: numero pagina, bounding box, confidence per parola.
Non fallisce tutto il flusso se una pagina è illeggibile: segnala in errors.
"""

from __future__ import annotations

import atexit
import logging
import os
import queue
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple



LOG = logging.getLogger(__name__)


@dataclass
class OCRWord:
    text: str
    bbox: Optional[Tuple[int, int, int, int]] = None   # (x1, y1, x2, y2) pixel
    confidence: Optional[float] = None                  # 0.0 .. 1.0


@dataclass
class OCRPage:
    page_index: int
    words: List[OCRWord] = field(default_factory=list)
    text: str = ""
    ocr_engine: str = ""           # "windows_ocr" / "tesseract" / ""
    confidence_avg: Optional[float] = None
    error: str = ""                # "" if ok
    used: bool = False             # True se l'OCR è stato eseguito (anche fallendo)


@dataclass
class OCRExtraction:
    pages: List[OCRPage] = field(default_factory=list)
    full_text: str = ""
    ocr_available: bool = False
    used_ocr: bool = False
    errors: List[str] = field(default_factory=list)

    def text_for_page(self, idx: int) -> str:
        if 0 <= idx < len(self.pages):
            return self.pages[idx].text or ""
        return ""

    def words_for_page(self, idx: int) -> List[OCRWord]:
        if 0 <= idx < len(self.pages):
            return self.pages[idx].words or []
        return []


def _ocr_variants(path: Path, tmp: Path) -> List[Path]:
    """Copie ritoccate della pagina per l'OCR di Windows, che sbaglia molto con certe
    immagini: tratti troppo netti (scansioni pulite, scrittura a mano grande) e righe
    del quaderno che toccano le lettere. Leggera sfocatura e righe chiare tolte: sullo
    stampatello a mano l'errore e' sceso dal 43% al 6% dei caratteri."""
    try:
        from PIL import Image, ImageFilter, ImageOps
        img = Image.open(path)
        img.load()
    except Exception:  # noqa: BLE001 - formato non leggibile da Pillow: solo l'originale
        return []
    if img.width * img.height > 40_000_000:
        return []
    img = img.convert("RGB")
    no_lines = ImageOps.grayscale(img).point(lambda v: 255 if v > 160 else v)
    out = []
    for name, im in (("sfocata", img.filter(ImageFilter.GaussianBlur(1.2))), ("senza_righe", no_lines),
                     ("senza_righe_sfocata", no_lines.filter(ImageFilter.GaussianBlur(1.0)))):
        q = tmp / f"{name}.png"
        try:
            im.save(q)
            out.append(q.resolve())
        except OSError:
            pass
    return out


_GOOD_TOKEN = re.compile(r"^[(\"']?([A-Za-zÀ-ÿ]+(['’][A-Za-zÀ-ÿ]+)?|\d+([.,/:\-]\d+)*[A-Za-z]{0,3}|"
                         r"[A-Z]{1,5}-?\d+[\w\-/]*)[)\"'.,;:!?]?$")
_COMMON_WORDS = set("""a ad al alla alle allo ai agli anche che chi con col come da dal dalla dalle dai dagli
de del della delle dello dei degli di e ed è era fa fatto fatta già gli ha hanno ho i il in la le lo ma mi ne
nel nella nelle nello nei negli no non o per più poi può quando se si sì sia sono stato stata su sul sulla
sulle sui tra un una uno via ore data n numero dopo prima tutto tutti ogni oggi ieri domani entro the and of
to for with is""".split())


def _reading_score(text: str) -> float:
    """Quanto una lettura OCR sembra testo vero: parole comuni riconosciute e parole
    "pulite" (lettere, numeri, codici) contro i frammenti con simboli spuri."""
    raw = text.split()
    hits = sum(w.strip(".,;:()\"'").lower() in _COMMON_WORDS for w in raw)
    good = sum(len(w) for w in raw if _GOOD_TOKEN.match(w))
    bad = sum(len(w) for w in raw if not _GOOD_TOKEN.match(w))
    return 4 * hits + (good - 2 * bad) / 10


def _best_reading(texts: List[str]) -> str:
    """La lettura migliore tra originale (primo) e varianti: una variante vince solo se
    nettamente migliore, sulle scritture illeggibili (corsivo) cambierebbe a caso."""
    if not texts:
        return ""
    best, best_score = texts[0], _reading_score(texts[0])
    floor = best_score * 1.15 + 2
    for txt in texts[1:]:
        s = _reading_score(txt)
        if s > floor and s > best_score:
            best, best_score = txt, s
    return best


_PS_HEADER = r"""$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
Function Await($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    $netTask.Result
}
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Storage.Streams.IRandomAccessStream,Windows.Storage.Streams,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrResult,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage([Windows.Globalization.Language]::new('it-IT')) }
if ($engine -eq $null) { throw 'Nessuna lingua OCR installata in Windows' }
"""
_PS_RECOGNIZE = r"""
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bmp = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bmp)) ([Windows.Media.Ocr.OcrResult])
    $stream.Dispose()
    Write-Output '@@OCR-VARIANTE@@'
    foreach ($line in $result.Lines) { Write-Output $line.Text }
"""
_PS_ONE_SHOT = "foreach ($imgPath in @(__IMG_PATHS__)) {" + _PS_RECOGNIZE + "}\n"
# processo fisso: un elenco di immagini per riga (separate da |), risposta chiusa da @@OCR-FINE@@
_PS_WORKER = r"""
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
while ($true) {
  $req = [Console]::In.ReadLine()
  if ($req -eq $null -or $req -eq '@@FINE@@') { break }
  foreach ($imgPath in $req.Split('|')) {
    try {""" + _PS_RECOGNIZE + r"""    } catch { Write-Output '@@OCR-VARIANTE@@' }
  }
  Write-Output '@@OCR-FINE@@'
  [Console]::Out.Flush()
}
"""


class _OcrWorker:
    """PowerShell con l'OCR di Windows gia' caricato, riusato per tutte le pagine
    (prima ~1 s di avvio per ogni immagine: lungo per i PDF scansionati di molte
    pagine). Si chiude da solo dopo qualche minuto di inattivita'."""

    IDLE_SECONDS = 300
    _lock = threading.Lock()
    _proc: Optional[subprocess.Popen] = None
    _lines: "queue.Queue[Optional[str]]" = queue.Queue()
    _timer: Optional[threading.Timer] = None
    disabled = False

    @classmethod
    def _start(cls) -> None:
        from .. import winshell
        cls._lines = queue.Queue()
        cls._proc = winshell.popen(_PS_HEADER + _PS_WORKER, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                   bufsize=1)
        proc, lines = cls._proc, cls._lines

        def _read() -> None:
            try:
                for line in proc.stdout:  # type: ignore[union-attr]
                    lines.put(line.rstrip("\r\n"))
            except Exception:  # noqa: BLE001
                pass
            lines.put(None)
        threading.Thread(target=_read, name="ocr-worker", daemon=True).start()

    @classmethod
    def close(cls) -> None:
        proc, cls._proc = cls._proc, None
        if cls._timer is not None:
            cls._timer.cancel()
            cls._timer = None
        if proc is None:
            return
        try:
            proc.stdin.write("@@FINE@@\n")  # type: ignore[union-attr]
            proc.stdin.flush()  # type: ignore[union-attr]
            proc.wait(timeout=3)
        except Exception:  # noqa: BLE001
            try:
                proc.kill()
            except Exception:  # noqa: BLE001
                pass

    @classmethod
    def recognize(cls, paths: List[str], timeout: float) -> Optional[List[str]]:
        """Testo di ogni immagine, o None se il processo fisso non funziona."""
        if cls.disabled or os.name != "nt" or any("|" in p or "\n" in p for p in paths):
            return None
        import time as _time
        with cls._lock:
            try:
                if cls._proc is None or cls._proc.poll() is not None:
                    cls._start()
                cls._proc.stdin.write("|".join(paths) + "\n")  # type: ignore[union-attr]
                cls._proc.stdin.flush()  # type: ignore[union-attr]
                out: List[str] = []
                deadline = _time.monotonic() + timeout
                while True:
                    line = cls._lines.get(timeout=max(0.1, deadline - _time.monotonic()))
                    if line is None:
                        raise RuntimeError("processo OCR terminato")
                    if line.strip() == "@@OCR-FINE@@":
                        break
                    out.append(line)
            except Exception as exc:  # noqa: BLE001
                LOG.info("OCR con processo fisso non disponibile (%s): uso uno script per immagine", exc)
                cls.close()
                cls.disabled = True
                return None
            if cls._timer is not None:
                cls._timer.cancel()
            cls._timer = threading.Timer(cls.IDLE_SECONDS, cls.close)
            cls._timer.daemon = True
            cls._timer.start()
        return [x.strip() for x in "\n".join(out).split("@@OCR-VARIANTE@@")[1:]]


atexit.register(_OcrWorker.close)


class OCRService:
    def __init__(self, config_or_tesseract_root: Any = None):
        """Accetta: oggetto Config oppure un Path/str alla cartella runtime/tesseract.
        Se viene passato None, usa solo Windows OCR (se disponibile) o Tesseract da PATH."""
        self._tesseract_root: Optional[Path] = None
        if hasattr(config_or_tesseract_root, "resolve_app_path") and callable(config_or_tesseract_root.resolve_app_path):
            self.config = config_or_tesseract_root
            try:
                self._tesseract_root = Path(config_or_tesseract_root.resolve_app_path("runtime/tesseract"))
            except Exception:  # noqa: BLE001
                pass
        elif config_or_tesseract_root is not None:
            self.config = None
            self._tesseract_root = Path(config_or_tesseract_root)
        else:
            self.config = None
        self._tesseract_exe: Optional[Path] = None
        self._windows_ocr_checked = False
        self._windows_ocr_available = False
        self._detect_backends()

    # --------------------------------------------------------------
    # Backend detection
    # --------------------------------------------------------------
    def _detect_backends(self) -> None:
        # 1) Check portable Tesseract
        try:
            rt = self._tesseract_root
            if rt is not None and rt.is_dir():
                for exe_name in ("tesseract.exe", "tesseract"):
                    p = rt / exe_name
                    if p.is_file():
                        self._tesseract_exe = p
                        LOG.info("Trovato Tesseract portatile: %s", p)
                        break
        except Exception:  # noqa: BLE001
            pass
        # Altrimenti PATH:
        if self._tesseract_exe is None:
            import shutil as _sh
            try:
                p = _sh.which("tesseract")
                if p:
                    self._tesseract_exe = Path(p)
            except Exception:  # noqa: BLE001
                pass
        # 2) Windows OCR check is lazily done on first use (import ctypes is cheap
        #    but calling WinRT needs to be safe)

    def _ensure_windows_ocr(self) -> bool:
        if self._windows_ocr_checked:
            return self._windows_ocr_available
        self._windows_ocr_checked = True
        try:
            import os as _os
            if _os.name != "nt":
                self._windows_ocr_available = False
                return False
            try:
                # Try WinRT via win32ctypes - it's already in venv
                from win32ctypes.core.compat import get_osfhandle  # noqa: F401
            except Exception:
                pass
            # Simplest signal: check Windows version (Vista+ have OCR APIs on Win10)
            ver = sys.getwindowsversion() if hasattr(sys, "getwindowsversion") else None
            if ver and ver.major >= 10:
                # Tentative: will actually be checked at first OCR call
                self._windows_ocr_available = True
            else:
                self._windows_ocr_available = False
        except Exception:  # noqa: BLE001
            self._windows_ocr_available = False
        return self._windows_ocr_available

    @property
    def is_available(self) -> bool:
        return self._tesseract_exe is not None or self._ensure_windows_ocr()

    # --------------------------------------------------------------
    # Public API
    # --------------------------------------------------------------
    def ocr_images(self, image_paths: List[Path]) -> OCRExtraction:
        """Esegui OCR su una lista di immagini (una per pagina)."""
        out = OCRExtraction(ocr_available=self.is_available)
        if not image_paths:
            return out
        for idx, p in enumerate(image_paths):
            page = self._ocr_single_image(p, idx)
            out.pages.append(page)
            if page.text:
                out.used_ocr = True
            if page.error:
                out.errors.append(f"Pagina {idx+1}: {page.error}")
        out.full_text = "\n".join(p.text for p in out.pages if p.text)
        return out

    # --------------------------------------------------------------
    # FR65 Projection-profile deskew: angle -10..+10°, step 0.5°, threshold 0.3°
    # --------------------------------------------------------------
    @staticmethod
    def deskew_projection(pil_image: Any, *,
                          angle_min: float = -10.0,
                          angle_max: float = 10.0,
                          step: float = 0.5,
                          threshold: float = 0.3) -> Any:
        """Return (possibly) rotated PIL image corrected for skew angle."""
        try:
            from PIL import Image
            img = pil_image
            if img is None:
                return pil_image
            gray = img.convert("L")
            best_angle = 0.0
            best_var = -1.0
            a = angle_min
            while a <= (angle_max + 1e-9):
                if abs(a) < 1e-9:
                    rot = gray
                else:
                    rot = gray.rotate(a, resample=Image.BICUBIC, expand=True, fillcolor=255)
                try:
                    import numpy as _np  # type: ignore
                    arr = _np.asarray(rot).astype(_np.float64)
                    # Invert so text = 1 (dark pixels)
                    vals = 255.0 - arr
                    rows_profile = vals.sum(axis=1)
                    varv = float(_np.var(rows_profile))
                except Exception:
                    # Fallback: variance manual (numpy not guaranteed)
                    rows: List[float] = []
                    width, height = rot.size
                    pixels = rot.load()
                    for y in range(height):
                        s = 0.0
                        for x in range(width):
                            s += (255.0 - float(pixels[x, y]))
                        rows.append(s)
                    mean_v = sum(rows) / len(rows)
                    varv = sum((v - mean_v) ** 2 for v in rows) / len(rows)
                if varv > best_var:
                    best_var = varv
                    best_angle = a
                a += step
            if abs(best_angle) >= threshold:
                return img.rotate(best_angle, resample=Image.BICUBIC, expand=True, fillcolor=(255, 255, 255))
            return img
        except Exception:  # noqa: BLE001
            return pil_image

    def ocr_pil_images(self, pil_images: List[Any],
                        *, tmp_dir: Optional[Path] = None,
                        auto_deskew: bool = True) -> OCRExtraction:
        """OCR di Pillow images, salvando temporaneamente in PNG."""
        import tempfile
        from pathlib import Path as _P
        out = OCRExtraction(ocr_available=self.is_available)
        if not pil_images:
            return out
        tdir = tmp_dir or _P(tempfile.mkdtemp(prefix="mai_ocr_"))
        try:
            tdir.mkdir(parents=True, exist_ok=True)
            saved: List[_P] = []
            for idx, img in enumerate(pil_images):
                try:
                    if img is None:
                        continue
                    if auto_deskew:
                        img = self.deskew_projection(img)
                    tmp_path = tdir / f"page_{idx:04d}.png"
                    img.convert("RGB").save(str(tmp_path), format="PNG")
                    saved.append(tmp_path)
                except Exception as exc:  # noqa: BLE001
                    out.errors.append(f"Salvataggio pagina {idx+1} fallito: {exc}")
            return self.ocr_images(saved)
        finally:
            if tmp_dir is None:
                import shutil
                shutil.rmtree(tdir, ignore_errors=True)

    # --------------------------------------------------------------
    # Single image OCR
    # --------------------------------------------------------------
    def _ocr_single_image(self, path: Path, idx: int) -> OCRPage:
        page = OCRPage(page_index=idx)
        if not self.is_available:
            page.error = "Nessun motore OCR disponibile (installare Tesseract in runtime/tesseract/ o usare Windows 10+)"
            return page
        # Tier 1: Windows OCR
        if self._ensure_windows_ocr():
            try:
                return self._ocr_image_windows(path, idx)
            except Exception as exc:  # noqa: BLE001
                page.error = f"Windows OCR fallito: {exc}"
        # Tier 2: Tesseract
        if self._tesseract_exe is not None:
            try:
                return self._ocr_image_tesseract(path, idx)
            except Exception as exc:  # noqa: BLE001
                if page.error:
                    page.error += f" ; Tesseract fallito: {exc}"
                else:
                    page.error = f"Tesseract fallito: {exc}"
        return page

    # --------------------------------------------------------------
    # Win10+ Windows.Media.Ocr via subprocess/clipboard escape.
    # Actually calling WinRT directly from pure Python is complex.
    # Best-effort: PowerShell with WinRT. Slow but guaranteed available on Win10+.
    # --------------------------------------------------------------
    def _ocr_image_windows(self, path: Path, idx: int) -> OCRPage:
        page = OCRPage(page_index=idx, ocr_engine="windows_ocr", used=True)
        import shutil
        import tempfile
        tmp = Path(tempfile.mkdtemp(prefix="docx_ai_ocr_"))
        try:
            paths = [Path(path).resolve()] + _ocr_variants(Path(path), tmp)
            timeout = 120 + 60 * (len(paths) - 1)
            # processo OCR che resta aperto: PowerShell + WinRT costano ~1 s ad ogni avvio
            texts = _OcrWorker.recognize([str(p) for p in paths], timeout)
            if texts is None:  # processo fisso non disponibile: uno script per volta
                code = _PS_HEADER + _PS_ONE_SHOT.replace("__IMG_PATHS__", ",".join(
                    "'" + str(p).replace("'", "''") + "'" for p in paths))
                # niente "-ExecutionPolicy Bypass" (segnale tipico dei malware per gli antivirus):
                # con -Command i criteri di esecuzione degli script non si applicano
                from .. import winshell
                proc = winshell.run(code, timeout=timeout)
                texts = [x.strip() for x in (proc.stdout or "").split("@@OCR-VARIANTE@@")[1:]]
                if not any(texts) and proc.stderr:
                    raise RuntimeError((proc.stderr or "").strip()[:500])
            page.text = _best_reading(texts)
            page.confidence_avg = 0.75 if page.text else None  # rough approximation
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"PowerShell OCR: {exc}") from exc
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return page

    # --------------------------------------------------------------
    # Portable Tesseract fallback
    # --------------------------------------------------------------
    def _ocr_image_tesseract(self, path: Path, idx: int) -> OCRPage:
        import subprocess
        import sys
        page = OCRPage(page_index=idx, ocr_engine="tesseract", used=True)
        assert self._tesseract_exe is not None
        tess = self._tesseract_exe
        tess_dir = tess.parent
        tessdata = tess_dir / "tessdata"
        env = dict(os.environ) if hasattr(os, "environ") else {}
        if tessdata.is_dir():
            env["TESSDATA_PREFIX"] = str(tess_dir)
        # Try ita+eng if available, else default
        lang = "ita+eng"
        if tessdata.is_dir():
            ita = tessdata / "ita.traineddata"
            if not ita.is_file():
                lang = "eng"
        cmd = [
            str(tess),
            str(Path(path).resolve()),
            "stdout",
            "-l", lang,
        ]
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=300,
                creationflags=0x08000000 if hasattr(sys, "frozen") or os.name == "nt" else 0,
                env=env if env else None,
                cwd=str(tess_dir),
            )
            out = (proc.stdout or "").strip()
            if not out and proc.stderr:
                # Some warnings go to stderr; proceed if stdout is empty but rc=0
                if proc.returncode != 0:
                    raise RuntimeError((proc.stderr or "").strip()[:500])
            page.text = out or ""
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"Tesseract: {exc}") from exc
        return page


import sys  # noqa: E402
