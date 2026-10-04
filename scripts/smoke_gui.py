r"""Smoke test della GUI: costruisce la finestra principale su una cartella dati
isolata, visita ogni scheda, apre ogni finestra e fallisce su qualsiasi eccezione Tk.

    .venv\Scripts\python.exe scripts\smoke_gui.py [--shots CARTELLA] [--dark]

Con --shots salva uno screenshot per ogni passo (utile per la revisione grafica).
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import traceback
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

from tkinter import messagebox  # noqa: E402

for name in ("showinfo", "showwarning", "showerror"):
    setattr(messagebox, name, lambda *a, **k: "ok")
for name in ("askyesno", "askokcancel", "askyesnocancel"):
    setattr(messagebox, name, lambda *a, **k: False)

from maintenance_ai.app import App  # noqa: E402
from maintenance_ai.ui.shell import MainWindow  # noqa: E402

errors: list = []
app = App.bootstrap()
for k, v in (("first_run_done", "1"), ("ui.tour_done", "1"), ("ui.theme", "dark" if args.dark else "light"),
             ("ui.lang", args.lang), ("ai.preload", "0"), ("backup.auto_days", "0")):
    app.db.set_setting(k, v)
mod = app.module_manager.list_modules()[0]
sample = {k: "NON_SPECIFICATO" for k in (mod.schema or {}).get("properties", {})}
sample.update({"apparecchiatura": "C-12", "numero_rapporto": "123456", "note": "Sostituita la cinghia."})
desc = "Il 2 ottobre 2026 Mario Rossi ha sostituito la cinghia del compressore C-12."
rid = app.db.create_report(module_id=mod.id, module_version=mod.version, status="draft",
                           input_description=desc, draft_json=json.dumps(sample))
app.db.add_report_version(rid, json.dumps(sample), "Approvazione")

win = MainWindow(app)
root = win.root
root.report_callback_exception = lambda et, ev, tb: errors.append(
    "".join(traceback.format_exception(et, ev, tb)))
if args.shots:
    args.shots.mkdir(parents=True, exist_ok=True)


def shot(name: str, target=None) -> None:
    if not args.shots:
        return
    from PIL import ImageGrab
    root.update()
    if target is not None and target.winfo_exists():
        target.lift()
        target.update()
        x, y = target.winfo_rootx(), target.winfo_rooty()
        ImageGrab.grab((x, y, x + target.winfo_width(), y + target.winfo_height()), all_screens=True).save(
            args.shots / f"{name}.png")
        return
    grab = root.grab_current()
    tops = [w for w in root.winfo_children() if isinstance(w, __import__("tkinter").Toplevel)
            and w.winfo_viewable() and w.winfo_width() > 300]
    target = grab if grab is not None and grab is not root else (tops[-1] if tops else root)
    x, y = target.winfo_rootx(), target.winfo_rooty()
    ImageGrab.grab((x, y, x + target.winfo_width(), y + target.winfo_height()), all_screens=True).save(
        args.shots / f"{name}.png")


def dialog(factory):
    def run():
        factory()
    return run


def review():
    from maintenance_ai.ui.dialogs.review import ReviewDialog
    return ReviewDialog(win, mod, rid, sample, description=desc, sources=[desc])


def versions():
    from maintenance_ai.ui.dialogs.versions import VersionsDialog
    return VersionsDialog(win, rid)


def template_editor():
    from maintenance_ai.ui.dialogs.template_editor import TemplateEditor
    return TemplateEditor(win, mod)


def pdf_preview():
    from maintenance_ai.exporters.pdf_exporter import export_pdf
    from maintenance_ai.ui.dialogs.pdf_preview import PdfPreview
    pdf = tmp / "t.pdf"
    export_pdf(pdf, sample, mod.schema, module_name=mod.name)
    return PdfPreview(root, pdf, win=win)


def table_import():
    from maintenance_ai.ui.dialogs.table_import import TableImportDialog
    return TableImportDialog(win, mod)


def ai_setup():
    win.open_ai_setup()


def new_module():
    win.sidebar.new_module()


def ocr():
    from maintenance_ai.ui.dialogs.ocr_tool import OcrDialog
    return OcrDialog(win)


def rules():
    from maintenance_ai.ui.dialogs.rules_picker import RulesPicker
    return RulesPicker(win)


def export_done():
    from maintenance_ai.ui.dialogs.export_done import ExportDoneDialog
    pdf = tmp / "t.pdf"
    return ExportDoneDialog(win, mod, tmp / "t.json", None, pdf)


def tour():
    win.start_tour()


steps = [(f"page_{k}", (lambda k=k: win.show_page(k))) for k in
         ("home", "report", "history", "module", "documents", "settings")]
steps += [("collapse_sidebar", lambda: win.sidebar.set_collapsed(True)),
          ("expand_sidebar", lambda: win.sidebar.set_collapsed(False)),
          ("dlg_review", review), ("dlg_versions", versions), ("dlg_template_editor", template_editor),
          ("dlg_pdf_preview", pdf_preview), ("dlg_table_import", table_import), ("dlg_ai_setup", ai_setup),
          ("dlg_new_module", new_module), ("dlg_ocr", ocr), ("dlg_rules", rules), ("dlg_export_done", export_done),
          ("tour", tour), ("theme_cycle", win.cycle_theme), ("help", win.show_help)]


def close_toplevels() -> None:
    for w in list(root.winfo_children()):
        if w.winfo_class() in ("Toplevel", "CTkToplevel"):
            try:
                w.destroy()
            except Exception:  # noqa: BLE001
                pass


def run(i: int = 0) -> None:
    if i >= len(steps):
        root.after(500, lambda: (close_toplevels(), win.close(force=True)))
        return
    name, fn = steps[i]
    root.after(2800, close_toplevels)  # chiude anche i dialoghi modali (wait_window)
    try:
        res = fn()
        target = res if hasattr(res, "winfo_exists") and res is not root else None
        root.after(2200, lambda: shot(name, target))
        print(f"[OK]   {name}", flush=True)
    except Exception:  # noqa: BLE001
        errors.append(f"{name}: {traceback.format_exc()}")
        print(f"[FAIL] {name}", flush=True)
    root.after(3200, lambda: run(i + 1))


root.after(1500, run)
win.show()
app.shutdown()
shutil.rmtree(tmp, ignore_errors=True)
if errors:
    print("\n".join(errors))
    print(f"GUI SMOKE: FAILED ({len(errors)} errori)")
    sys.exit(1)
print("GUI SMOKE: PASSED")
