"""Pacchetto diagnostico e segnalazione problemi.

Il pacchetto contiene log, versione, configurazione, impostazioni e info
hardware, ma NON rapporti, database, documenti o foto. Nome utente e percorso
del profilo vengono mascherati nei testi.
"""

from __future__ import annotations

import json
import os
import platform
import re
import time
import urllib.parse
import zipfile
from pathlib import Path
from typing import Any, Dict

ISSUES_URL = "https://github.com/motthz/MaintenanceAI/issues/new"


def _mask(text: str) -> str:
    home = str(Path.home())
    user = os.environ.get("USERNAME", "")
    text = text.replace(home, "%USERPROFILE%")
    if user and len(user) > 2:
        text = re.sub(re.escape(user), "<utente>", text, flags=re.I)
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.]+", "<email>", text)
    return text


def system_info(app: Any) -> Dict[str, Any]:
    from .. import __version__
    from ..llm import hardware
    hw = hardware.detect()
    st = app.config.ai_components_status()
    return {
        "versione": __version__,
        "windows": platform.platform(),
        "python": platform.python_version(),
        "hardware": hw.summary(),
        "ai_runtime": st["runtime_ok"], "ai_modello": st["model_ok"], "ai_leggero": st["fallback_ok"],
        "ai_backend": getattr(app.ai_service, "backend_label", ""),
        "moduli": len(app.module_manager.list_modules()),
        "rapporti": app.db.count_reports(),
        "cartella_dati_rete": str(app.config.data_root).startswith("\\\\"),
    }


def create_package(app: Any, dest_dir: Path) -> Path:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / f"MaintenanceAI_diagnostica_{time.strftime('%Y%m%d_%H%M%S')}.zip"
    logs = app.config.logs_root()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("sistema.json", json.dumps(system_info(app), indent=2, ensure_ascii=False))
        settings = {k: v for k, v in app.settings.all().items()}
        zf.writestr("impostazioni.json", json.dumps(settings, indent=2, ensure_ascii=False))
        zf.writestr("config.json", _mask(json.dumps(app.config.raw, indent=2, ensure_ascii=False)))
        for name in ("maintenance_ai.log", "maintenance_ai.log.1", "crash.log"):
            f = logs / name
            if f.is_file():
                data = f.read_text(encoding="utf-8", errors="replace")[-400_000:]
                zf.writestr(f"log/{name}", _mask(data))
        ops = app.db.list_ai_operations(limit=50)
        zf.writestr("ai_operazioni.json", _mask(json.dumps(
            [{k: o.get(k) for k in ("feature", "timestamp", "model", "outcome", "error", "retry_count")}
             for o in ops], indent=2, ensure_ascii=False)))
    return out


def issue_url(app: Any, title: str = "") -> str:
    info = system_info(app)
    params = {"template": "bug.yml", "labels": "bug", "title": title or "[Bug] ",
              "version": info["versione"], "os": "Windows 11" if "10.0.2" in info["windows"] else "Windows 10",
              "diag": "Sistema: " + ", ".join(f"{k}={v}" for k, v in info.items())}
    return ISSUES_URL + "?" + urllib.parse.urlencode(params)
