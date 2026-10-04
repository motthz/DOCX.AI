"""Pulizia periodica: log, debug AI, cache di download, residui temporanei."""

from __future__ import annotations

import logging
import shutil
import tempfile
import time
from pathlib import Path
from typing import Dict

LOG = logging.getLogger(__name__)

CRASH_LOG_MAX = 2 * 1024 * 1024       # crash.log oltre 2 MB viene troncato (resta la coda)
LLM_DEBUG_KEEP = 20                   # ultime N cartelle di debug AI
TEMP_MAX_AGE_S = 2 * 86400            # residui mai_* in %TEMP% piu' vecchi di 2 giorni


def _trim_file(path: Path, max_bytes: int) -> bool:
    try:
        size = path.stat().st_size
    except OSError:
        return False
    if size <= max_bytes:
        return False
    with open(path, "rb") as fh:
        fh.seek(size - max_bytes // 2)
        tail = fh.read()
    path.write_bytes(b"[... log precedente troncato ...]\n" + tail)
    return True


def run(data_root: Path) -> Dict[str, int]:
    stats = {"trimmed": 0, "removed": 0}
    data_root = Path(data_root)
    logs = data_root / "logs"
    if _trim_file(logs / "crash.log", CRASH_LOG_MAX):
        stats["trimmed"] += 1
    debug = logs / "llm_debug"
    if debug.is_dir():
        dirs = sorted((d for d in debug.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime)
        for d in dirs[:-LLM_DEBUG_KEEP]:
            shutil.rmtree(d, ignore_errors=True)
            stats["removed"] += 1
    for leftover in ("dl_cache", "exports/selftest", "exports/selftest_di"):
        p = data_root / leftover
        if p.is_dir() and not any(p.glob("*.part")):
            shutil.rmtree(p, ignore_errors=True)
            stats["removed"] += 1
    now = time.time()
    for p in Path(tempfile.gettempdir()).glob("mai_*"):
        try:
            if now - p.stat().st_mtime > TEMP_MAX_AGE_S:
                shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink()
                stats["removed"] += 1
        except OSError:
            pass
    LOG.info("Pulizia completata: %s", stats)
    return stats
