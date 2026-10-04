"""Smoke test della GUI eseguibile anche dentro l'exe (MaintenanceAI.exe --gui-smoke).

Costruisce la finestra principale, visita ogni scheda, apre ogni finestra di dialogo
e restituisce 1 se si verifica una qualsiasi eccezione Tk (0 altrimenti).
"""

from __future__ import annotations

import json
import tempfile
import traceback
from pathlib import Path
from typing import Any, Optional


def run(app: Any, *, lang: str = "it-IT", dark: bool = False, shots: Optional[Path] = None) -> int:
    from tkinter import messagebox

    for name in ("showinfo", "showwarning", "showerror"):
        setattr(messagebox, name, lambda *a, **k: "ok")
    for name in ("askyesno", "askokcancel", "askyesnocancel"):
        setattr(messagebox, name, lambda *a, **k: False)
    from maintenance_ai.ui.shell import MainWindow

    errors: list = []
    for k, v in (("first_run_done", "1"), ("ui.tour_done", "1"), ("ui.theme", "dark" if dark else "light"),
                 ("ui.lang", lang), ("ai.preload", "0"), ("backup.auto_days", "0")):
        app.db.set_setting(k, v)
    mods = app.module_manager.list_modules()
    mod = mods[0] if mods else app.module_manager.create_module(name="Smoke test", template_type="docx")
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
    if shots:
        shots.mkdir(parents=True, exist_ok=True)


    def shot(name: str, target=None) -> None:
        if not shots:
            return
        from PIL import ImageGrab
        root.update()
        if target is not None and target.winfo_exists():
            target.lift()
            target.update()
            x, y = target.winfo_rootx(), target.winfo_rooty()
            ImageGrab.grab((x, y, x + target.winfo_width(), y + target.winfo_height()), all_screens=True).save(
                shots / f"{name}.png")
            return
        grab = root.grab_current()
        tops = [w for w in root.winfo_children() if isinstance(w, __import__("tkinter").Toplevel)
                and w.winfo_viewable() and w.winfo_width() > 300]
        target = grab if grab is not None and grab is not root else (tops[-1] if tops else root)
        x, y = target.winfo_rootx(), target.winfo_rooty()
        ImageGrab.grab((x, y, x + target.winfo_width(), y + target.winfo_height()), all_screens=True).save(
            shots / f"{name}.png")


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
        pdf = Path(tempfile.mkdtemp(prefix="mai_gui_pdf_")) / "t.pdf"
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
        pdf = Path(tempfile.mkdtemp(prefix="mai_gui_pdf_")) / "t.pdf"
        pdf = Path(tempfile.mkdtemp(prefix="mai_gui_pdf_")) / "t.pdf"
        from maintenance_ai.exporters.pdf_exporter import export_pdf
        export_pdf(pdf, sample, mod.schema, module_name=mod.name)
        return ExportDoneDialog(win, mod, pdf.with_suffix(".json"), None, pdf)


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
    if errors:
        print("\n".join(errors))
        print(f"GUI SMOKE: FAILED ({len(errors)} errori)")
        return 1
    print("GUI SMOKE: PASSED")
    return 0
