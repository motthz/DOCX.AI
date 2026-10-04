"""Download + install of the local AI components from inside the app.

Installs into the user's data dir (``%LOCALAPPDATA%\\MaintenanceAI``), which is
always writable, so it works when the app itself lives in a read-only folder
(e.g. installed under Program Files). ``Config.resolve_ai_path`` looks there
first.

Components:
- llama.cpp ``llama-server.exe`` (Windows CPU x64 build from GitHub releases)
- Qwen3 GGUF model from HuggingFace, verified with SHA-256 when known.

Only the standard library is used (urllib, zipfile, hashlib).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import threading
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Optional

LOG = logging.getLogger(__name__)

LLAMA_RELEASES_API = "https://api.github.com/repos/ggml-org/llama.cpp/releases"
PREFERRED_LLAMA_TAG = "b10655"

MODELS: Dict[str, Dict[str, Any]] = {
    "Qwen3-1.7B-Q8_0.gguf": {
        "url": "https://huggingface.co/Qwen/Qwen3-1.7B-GGUF/resolve/main/Qwen3-1.7B-Q8_0.gguf",
        "sha256": "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a",
        "label": "Qwen3 1.7B (consigliato, ~1.8 GB)",
    },
    "Qwen3-0.6B-Q8_0.gguf": {
        "url": "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf",
        "sha256": None,
        "label": "Qwen3 0.6B (PC lenti, ~640 MB)",
    },
}
# Modello opzionale per la ricerca semantica nei documenti
EMBEDDING_MODEL: Dict[str, Dict[str, Any]] = {
    "Qwen3-Embedding-0.6B-Q8_0.gguf": {
        "url": "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B-GGUF/resolve/main/Qwen3-Embedding-0.6B-Q8_0.gguf",
        "sha256": None,
        "label": "Ricerca semantica nei documenti (~640 MB)",
    },
}
RUNTIME_VARIANTS = {"cpu": ("win-cpu", "llama"), "vulkan": ("win-vulkan", "llama-vulkan")}

USER_AGENT = "MaintenanceAI-installer"

# progress(fraction 0..1 or None for indeterminate, message)
ProgressFn = Callable[[Optional[float], str], None]


class InstallCancelled(Exception):
    pass


@dataclass
class InstallResult:
    runtime_dir: Path
    model_path: Path


class AIInstaller:
    def __init__(self, data_root: Path, *, runtime_rel: str = "runtime/llama",
                 models_rel: str = "models"):
        self.runtime_dir = Path(data_root) / runtime_rel
        self.models_dir = Path(data_root) / models_rel
        self.cache_dir = Path(data_root) / "dl_cache"
        self._cancel = threading.Event()

    def cancel(self) -> None:
        self._cancel.set()

    # ------------------------------------------------------------------
    def _open(self, url: str, timeout: float = 30.0):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https only

    def _download(self, url: str, dest: Path, progress: ProgressFn, label: str,
                  expected_size: Optional[int] = None) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        with self._open(url, timeout=60.0) as resp:
            total = int(resp.headers.get("Content-Length") or expected_size or 0)
            done = 0
            with open(part, "wb") as fh:
                while True:
                    if self._cancel.is_set():
                        raise InstallCancelled()
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    fh.write(chunk)
                    done += len(chunk)
                    if total:
                        progress(done / total,
                                 f"{label}: {done / 1048576:.0f} / {total / 1048576:.0f} MB")
                    else:
                        progress(None, f"{label}: {done / 1048576:.0f} MB")
        if total and done != total:
            part.unlink(missing_ok=True)
            raise IOError(f"Download incompleto ({done}/{total} byte): {url}")
        part.replace(dest)
        return dest

    @staticmethod
    def _sha256(path: Path, progress: ProgressFn, label: str) -> str:
        h = hashlib.sha256()
        size = max(path.stat().st_size, 1)
        done = 0
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024 * 4), b""):
                h.update(chunk)
                done += len(chunk)
                progress(done / size, f"Verifica integrità {label}…")
        return h.hexdigest()

    # ------------------------------------------------------------------
    def _find_llama_asset(self, variant: str = "cpu") -> dict:
        tag = RUNTIME_VARIANTS[variant][0]
        urls = [f"{LLAMA_RELEASES_API}/tags/{PREFERRED_LLAMA_TAG}",
                f"{LLAMA_RELEASES_API}?per_page=20"]
        for url in urls:
            try:
                with self._open(url) as resp:
                    raw = json.loads(resp.read().decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                LOG.info("llama.cpp release lookup %s fallito: %s", url, exc)
                continue
            for rel in raw if isinstance(raw, list) else [raw]:
                for asset in rel.get("assets", []):
                    name = asset.get("name", "")
                    if tag in name and "x64" in name and name.endswith(".zip"):
                        return asset
        raise RuntimeError(f"Nessuna build llama.cpp Windows {variant} x64 trovata su GitHub.")

    def install_runtime(self, progress: ProgressFn, variant: str = "cpu") -> Path:
        target = self.runtime_dir.parent / RUNTIME_VARIANTS[variant][1]
        exe = target / "llama-server.exe"
        if exe.is_file():
            progress(1.0, "Runtime llama.cpp già presente.")
            return target
        progress(None, "Ricerca runtime llama.cpp…")
        asset = self._find_llama_asset(variant)
        zpath = self._download(asset["browser_download_url"], self.cache_dir / asset["name"],
                               progress, "Runtime llama.cpp", asset.get("size"))
        progress(None, "Estrazione runtime…")
        with tempfile.TemporaryDirectory(dir=self.cache_dir) as tmp:
            with zipfile.ZipFile(zpath) as zf:
                for member in zf.namelist():
                    target = (Path(tmp) / member).resolve()
                    if not str(target).startswith(str(Path(tmp).resolve())):
                        raise RuntimeError(f"Percorso non sicuro nell'archivio: {member}")
                zf.extractall(tmp)
            found = next(Path(tmp).rglob("llama-server.exe"), None)
            if found is None:
                raise RuntimeError("llama-server.exe non trovato nell'archivio scaricato.")
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            shutil.copytree(found.parent, target)
        zpath.unlink(missing_ok=True)
        progress(1.0, "Runtime installato.")
        return target

    def install_model(self, name: str, progress: ProgressFn) -> Path:
        info = MODELS.get(name) or EMBEDDING_MODEL[name]
        dest = self.models_dir / name
        if dest.is_file():
            progress(1.0, f"Modello {name} già presente.")
            return dest
        tmp = self._download(info["url"], self.cache_dir / name, progress, f"Modello {name}")
        if info.get("sha256"):
            actual = self._sha256(tmp, progress, name)
            if actual.lower() != info["sha256"].lower():
                tmp.unlink(missing_ok=True)
                raise RuntimeError(f"Checksum SHA-256 del modello non valido ({name}). Riprovare.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(dest))
        progress(1.0, f"Modello {name} installato.")
        return dest

    def install(self, model_name: str, progress: ProgressFn, *, gpu: bool = False,
                embeddings: bool = False) -> InstallResult:
        self._cancel.clear()
        runtime = self.install_runtime(progress)
        if gpu:
            try:
                self.install_runtime(progress, "vulkan")
            except InstallCancelled:
                raise
            except Exception as exc:  # noqa: BLE001 - la GPU e' facoltativa
                LOG.warning("Runtime GPU non installato: %s", exc)
        model = self.install_model(model_name, progress)
        if embeddings:
            self.install_model(next(iter(EMBEDDING_MODEL)), progress)
        shutil.rmtree(self.cache_dir, ignore_errors=True)
        return InstallResult(runtime_dir=runtime, model_path=model)
