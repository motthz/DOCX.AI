"""Aggiornamento automatico da GitHub Releases.

All'avvio l'app chiede a GitHub l'ultima release pubblicata. Se e' piu' recente
della versione in uso:

- versione installata (Inno Setup): scarica ``DOCX.AI-Setup-<ver>.exe`` in
  ``%LOCALAPPDATA%\\DOCX.AI\\updates``, lo verifica (dimensione e SHA-256
  pubblicati da GitHub) e lo esegue in modalita' silenziosa alla chiusura o con
  "Riavvia e aggiorna" (l'installer riapre l'app);
- ZIP portable o sviluppo: segnala soltanto la nuova versione.

Si disattiva da Impostazioni o con la variabile ``DOCX_AI_NO_UPDATE=1`` (IT
aziendale). Usa solo la libreria standard.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Tuple

from .. import __version__
from ..datadir import local_app_dir

LOG = logging.getLogger(__name__)

REPO = "motthz/DOCX.AI"
LATEST_API = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASES_URL = f"https://github.com/{REPO}/releases/latest"
USER_AGENT = f"DOCX.AI/{__version__} updater"
INSTALLER_RE = re.compile(r"^DOCX\.AI-Setup-(\d+(?:\.\d+)*)\.exe$", re.IGNORECASE)
# parametri Inno Setup: nessuna domanda, nessun nuovo download del modello AI
SILENT_ARGS = ["/SILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/AIMODEL=none"]

ProgressFn = Callable[[Optional[float], str], None]


@dataclass
class UpdateInfo:
    version: str
    page_url: str
    notes: str = ""
    asset_name: str = ""
    asset_url: str = ""
    size: int = 0
    sha256: Optional[str] = None


def parse_version(text: str) -> Tuple[int, ...]:
    m = re.match(r"^\s*v?(\d+(?:\.\d+)*)", text or "")
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def is_newer(candidate: str, current: str = __version__) -> bool:
    return parse_version(candidate) > parse_version(current)


def disabled_by_policy() -> bool:
    return os.environ.get("DOCX_AI_NO_UPDATE", "").strip().lower() in ("1", "true", "yes", "si", "on")


def updates_dir() -> Path:
    return local_app_dir() / "updates"


def can_self_install(app_root: Path) -> bool:
    """True per l'exe installato con Inno Setup (non per ZIP portable o sorgenti)."""
    return (sys.platform == "win32" and bool(getattr(sys, "frozen", False))
            and (Path(app_root) / "unins000.exe").is_file())


def _open(url: str, timeout: float):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 - https only


def parse_release(raw: dict) -> Optional[UpdateInfo]:
    if raw.get("draft") or raw.get("prerelease"):
        return None
    version = ".".join(map(str, parse_version(raw.get("tag_name", ""))))
    if not version:
        return None
    info = UpdateInfo(version=version, page_url=raw.get("html_url") or RELEASES_URL,
                      notes=raw.get("body") or "")
    for asset in raw.get("assets", []):
        m = INSTALLER_RE.match(asset.get("name", ""))
        if m and parse_version(m.group(1)) == parse_version(version):
            digest = asset.get("digest") or ""
            info.asset_name = asset["name"]
            info.asset_url = asset.get("browser_download_url", "")
            info.size = int(asset.get("size") or 0)
            info.sha256 = digest[7:].lower() if digest.lower().startswith("sha256:") else None
            break
    return info


def check(current: str = __version__, timeout: float = 10.0) -> Optional[UpdateInfo]:
    """Ultima release se piu' recente di ``current``, altrimenti None.

    Errori di rete, repository privato (404) o limiti di GitHub: None, senza eccezioni.
    """
    try:
        with _open(LATEST_API, timeout) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - l'aggiornamento non deve mai bloccare l'app
        LOG.info("Controllo aggiornamenti non riuscito: %s", exc)
        return None
    info = parse_release(raw) if isinstance(raw, dict) else None
    if info and is_newer(info.version, current):
        return info
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _valid(path: Path, info: UpdateInfo) -> bool:
    try:
        if info.size and path.stat().st_size != info.size:
            return False
    except OSError:
        return False
    return not info.sha256 or _sha256(path) == info.sha256


def download(info: UpdateInfo, progress: Optional[ProgressFn] = None,
             cancel: Optional[threading.Event] = None, dest_dir: Optional[Path] = None) -> Path:
    """Scarica e verifica l'installer; se e' gia' stato scaricato lo riusa."""
    if not info.asset_url:
        raise RuntimeError("La release non contiene l'installer per Windows.")
    folder = Path(dest_dir) if dest_dir else updates_dir()
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / info.asset_name
    if dest.is_file() and _valid(dest, info):
        return dest
    part = dest.with_suffix(".part")
    with _open(info.asset_url, 60.0) as resp, open(part, "wb") as fh:
        total = int(resp.headers.get("Content-Length") or info.size or 0)
        done = 0
        while True:
            if cancel is not None and cancel.is_set():
                break
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            fh.write(chunk)
            done += len(chunk)
            if progress:
                progress(done / total if total else None, f"{done / 1048576:.0f} MB")
    if cancel is not None and cancel.is_set():
        part.unlink(missing_ok=True)
        raise RuntimeError("Download annullato.")
    if not _valid(part, info):
        part.unlink(missing_ok=True)
        raise RuntimeError("L'aggiornamento scaricato è incompleto o danneggiato.")
    part.replace(dest)
    return dest


def cleanup(current: str = __version__, dest_dir: Optional[Path] = None) -> None:
    """Rimuove installer di versioni gia' installate e download interrotti."""
    folder = Path(dest_dir) if dest_dir else updates_dir()
    if not folder.is_dir():
        return
    for f in folder.iterdir():
        m = INSTALLER_RE.match(f.name)
        if f.suffix == ".part" or (m and not is_newer(m.group(1), current)):
            try:
                f.unlink()
            except OSError:
                pass


def installer_command(installer: Path, *, relaunch: bool) -> list:
    return [str(installer), *SILENT_ARGS, f"/RELAUNCH={1 if relaunch else 0}"]


def launch_installer(installer: Path, *, relaunch: bool) -> None:
    """Avvia l'installer staccato dall'app, che deve chiudersi subito dopo."""
    flags = 0
    if sys.platform == "win32":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    LOG.info("Avvio aggiornamento: %s", installer)
    subprocess.Popen(installer_command(installer, relaunch=relaunch), close_fds=True, creationflags=flags)
