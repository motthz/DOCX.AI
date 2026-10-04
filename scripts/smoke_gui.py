r"""GUI smoke test: builds the MainWindow on an isolated data dir, visits every
tab, opens every dialog and fails on any Tk callback exception.

    .venv\\Scripts\\python.exe scripts\\smoke_gui.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

tmp = Path(tempfile.mkdtemp(prefix="mai_gui_"))
os.environ["MAINTENANCE_AI_DATA_DIR"] = str(tmp)
shutil.copytree(ROOT / "examples" / "modules", tmp / "workspace" / "modules", dirs_exist_ok=True)

from tkinter import messagebox  # noqa: E402

for name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, name, lambda *a, **k: "ok")
for name in ("askyesno", "askokcancel", "askyesnocancel"):
    setattr(messagebox, name, lambda *a, **k: False)

from maintenance_ai.app import App  # noqa: E402
from maintenance_ai.ui.main_window import MainWindow  # noqa: E402

errors: list = []
app = App.bootstrap()
app.db.set_setting("first_run_done", "1")
win = MainWindow(app.config, app.db, app.module_manager, app.context, app.reports,
                 rules_manager=app.rules_manager, doc_generator=app.doc_generator,
                 doc_modifier=app.doc_modifier, audit_engine=app.audit_engine,
                 smart_fill_engine=app.smart_fill_engine, doc_loader=app.doc_loader)
root = win.root
root.report_callback_exception = lambda et, ev, tb: errors.append(
    "".join(traceback.format_exception(et, ev, tb)))

steps = [
    ("select module", lambda: win._select_module(win._modules[0].slug) if win._modules else None),
    *[(f"tab {i}", (lambda i=i: win._notebook.select(i))) for i in range(5)],
    ("theme dark", win._toggle_theme),
    ("theme light", win._toggle_theme),
    ("help", win._on_show_help),
    ("ai setup", win._open_ai_setup),
    ("new module", win._on_new_module),
    ("doc create", win._on_doc_create),
    ("doc edit", win._on_doc_edit),
    ("doc audit", win._on_doc_audit),
    ("smart fill", win._on_doc_smart_fill),
    ("rules", win._on_doc_rules_picker),
    ("refresh", win._refresh_modules),
]


def run(i: int = 0) -> None:
    if i >= len(steps):
        root.after(800, finish)
        return
    label, fn = steps[i]
    # Modal dialogs block inside wait_window(): close them from the event loop.
    root.after(1500, close_toplevels)
    try:
        fn()
        print(f"[OK]   {label}")
    except Exception:  # noqa: BLE001
        errors.append(f"{label}: {traceback.format_exc()}")
        print(f"[FAIL] {label}")
    root.after(350, lambda: run(i + 1))


def close_toplevels() -> None:
    for w in list(root.winfo_children()):
        if w.winfo_class() == "Toplevel":
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass


def finish() -> None:
    close_toplevels()
    root.destroy()


root.after(2500, run)
win.show()
app.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
if errors:
    print("\n".join(errors))
    print(f"GUI SMOKE: FAILED ({len(errors)} errori)")
    sys.exit(1)
print("GUI SMOKE: PASSED")
