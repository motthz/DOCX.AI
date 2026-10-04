"""Backup e ripristino dei dati utente in un unico file ZIP.

Contenuto: database (copia consistente via API SQLite), moduli del workspace,
regole AI, allegati (foto). Esportazioni e componenti AI sono esclusi per
default (rigenerabili / grandi), le esportazioni si possono includere.

Il ripristino non puo' sovrascrivere il DB aperto: il file viene messo in
``restore_pending.zip`` e applicato al prossimo avvio, prima di aprire il DB.
"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Callable, List, Optional

from ..config import Config
from ..db import Database

LOG = logging.getLogger(__name__)

MANIFEST = "maintenanceai_backup.json"
PENDING = "restore_pending.zip"
INCLUDED_DIRS = ("workspace", "rules", "attachments")


def backups_dir(config: Config) -> Path:
    return config.data_root / "backups"


def create_backup(config: Config, db: Database, dest: Optional[Path] = None, *,
                  include_exports: bool = False,
                  progress: Optional[Callable[[str], None]] = None) -> Path:
    from .. import __version__
    stamp = time.strftime("%Y%m%d_%H%M%S")
    dest = Path(dest) if dest else backups_dir(config) / f"MaintenanceAI_backup_{stamp}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    root = config.data_root
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "maintenance_ai.db"
        if progress:
            progress("Copia del database…")
        db.backup_to(db_copy)
        dirs = list(INCLUDED_DIRS) + (["exports"] if include_exports else [])
        with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            zf.write(db_copy, "maintenance_ai.db")
            for d in dirs:
                base = root / d
                if not base.is_dir():
                    continue
                if progress:
                    progress(f"Archiviazione {d}…")
                for f in base.rglob("*"):
                    if f.is_file():
                        zf.write(f, f.relative_to(root).as_posix())
            zf.writestr(MANIFEST, json.dumps({
                "app": "MaintenanceAI", "version": __version__,
                "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "dirs": dirs,
            }, indent=2))
    LOG.info("Backup creato: %s", dest)
    return dest


def validate_backup(path: Path) -> dict:
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
        if MANIFEST not in names or "maintenance_ai.db" not in names:
            raise ValueError("Il file non e' un backup di MaintenanceAI.")
        for n in names:
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Percorso non sicuro nel backup: {n}")
        return json.loads(zf.read(MANIFEST))


def schedule_restore(config: Config, path: Path) -> dict:
    """Prepara il ripristino: verra' applicato al prossimo avvio."""
    info = validate_backup(path)
    shutil.copy2(path, config.data_root / PENDING)
    return info


def apply_pending_restore(data_root: Path) -> Optional[str]:
    """Da chiamare all'avvio PRIMA di aprire il DB. Ritorna un messaggio o None."""
    pending = Path(data_root) / PENDING
    if not pending.is_file():
        return None
    try:
        validate_backup(pending)
        safety = Path(data_root) / "backups" / f"pre_ripristino_{time.strftime('%Y%m%d_%H%M%S')}"
        safety.mkdir(parents=True, exist_ok=True)
        db_file = Path(data_root) / "maintenance_ai.db"
        for suffix in ("", "-wal", "-shm"):
            f = Path(str(db_file) + suffix)
            if f.exists():
                shutil.move(str(f), safety / f.name)
        with zipfile.ZipFile(pending) as zf:
            dirs = json.loads(zf.read(MANIFEST)).get("dirs", list(INCLUDED_DIRS))
            for d in dirs:
                target = Path(data_root) / d
                if target.exists():
                    shutil.move(str(target), safety / d)
            zf.extractall(data_root, members=[n for n in zf.namelist() if n != MANIFEST])
        pending.unlink()
        return f"Backup ripristinato. I dati precedenti sono stati salvati in {safety}."
    except Exception as exc:  # noqa: BLE001
        LOG.exception("Ripristino fallito")
        try:
            pending.rename(pending.with_suffix(".failed.zip"))
        except OSError:
            pass
        return f"Ripristino non riuscito: {exc}"


def auto_backup_if_due(config: Config, db: Database, *, every_days: int, keep: int) -> Optional[Path]:
    """Backup automatico periodico; conserva solo gli ultimi ``keep`` file."""
    if every_days <= 0:
        return None
    last = db.get_setting("backup.last_auto")
    if last and time.time() - float(last) < every_days * 86400:
        return None
    path = create_backup(config, db)
    db.set_setting("backup.last_auto", str(time.time()))
    files: List[Path] = sorted(backups_dir(config).glob("MaintenanceAI_backup_*.zip"))
    for old in files[:-max(1, keep)]:
        try:
            old.unlink()
        except OSError:
            pass
    return path
