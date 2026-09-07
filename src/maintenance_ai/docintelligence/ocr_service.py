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

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from ..config import Config


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
            import ctypes
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
            import math as _m
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
        import subprocess
        import sys
        page = OCRPage(page_index=idx, ocr_engine="windows_ocr", used=True)
        ps_code = r"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() | ? { $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' })[0]
[Windows.Storage.StorageFile,Windows.Storage,ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder,Windows.Graphics.Imaging,ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine,Windows.Foundation,ContentType=WindowsRuntime] | Out-Null
$imgPath = '__IMG_PATH__'
$file = [Windows.Storage.StorageFile]::GetFileFromPathAsync($imgPath)
$file = $asTask.Invoke($null, @($file)).Result
$stream = $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
$stream = $asTask.Invoke($null, @($stream)).Result
$decoder = [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
$decoder = $asTask.Invoke($null, @($decoder)).Result
$bmp = $decoder.GetSoftwareBitmapAsync()
$bmp = $asTask.Invoke($null, @($bmp)).Result
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($engine -eq $null) { $engine = [Windows.Media.Ocr.OcrEngine]::Create(([Windows.Globalization.Language]::new('it-IT'))) }
$result = $engine.RecognizeAsync($bmp)
$result = $asTask.Invoke($null, @($result)).Result
Write-Output $result.Text
"""
        try:
            safe_path = str(Path(path).resolve()).replace("'", "''")
            code = ps_code.replace("__IMG_PATH__", safe_path)
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                 "-Command", code],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=0x08000000 if hasattr(sys, "frozen") or os.name == "nt" else 0,
            )
            text = (proc.stdout or "").strip()
            if not text and proc.stderr:
                raise RuntimeError((proc.stderr or "").strip()[:500])
            page.text = text or ""
            page.confidence_avg = 0.75 if page.text else None  # rough approximation
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"PowerShell OCR: {exc}") from exc
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


import os  # noqa: E402  (used inside _ocr_image_* helpers)
import sys  # noqa: E402
