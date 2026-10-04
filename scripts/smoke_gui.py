r"""Smoke test della GUI da sorgente (vedi maintenance_ai.ui.gui_smoke).

    .venv\Scripts\python.exe scripts\smoke_gui.py [--shots CARTELLA] [--dark] [--lang en-US]

Nell'exe: MaintenanceAI.exe --gui-smoke
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

ap = argparse.ArgumentParser()
ap.add_argument("--shots", type=Path, default=None)
ap.add_argument("--dark", action="store_true")
ap.add_argument("--lang", default="it-IT")
args = ap.parse_args()

tmp = Path(tempfile.mkdtemp(prefix="mai_gui_"))
os.environ["MAINTENANCE_AI_DATA_DIR"] = str(tmp)
shutil.copytree(ROOT / "examples" / "modules", tmp / "workspace" / "modules", dirs_exist_ok=True)

try:  # come main.py: coordinate reali su schermi HiDPI (anche per gli screenshot)
    import ctypes
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except Exception:  # noqa: BLE001
    pass

from maintenance_ai.app import App  # noqa: E402
from maintenance_ai.ui import gui_smoke  # noqa: E402

app = App.bootstrap()
try:
    code = gui_smoke.run(app, lang=args.lang, dark=args.dark, shots=args.shots)
finally:
    app.shutdown()
    shutil.rmtree(tmp, ignore_errors=True)
sys.exit(code)
