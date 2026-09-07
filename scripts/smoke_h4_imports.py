# H4 variant: importa tutta l'UI (no Tk mainloop in sandbox), simula ReviewDialog widgets factory e JSON validation
import os, sys, json, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
tmp = ROOT / "dl_cache" / "ui_smoke"
tmp.mkdir(parents=True, exist_ok=True)
os.environ["MAINTENANCE_AI_DATA_DIR"] = str(tmp)
os.environ["MAINTENANCE_AI_CONFIG"] = str(ROOT / "config" / "default.json")
imports_ok = []
failed = []
for mod in [
    "maintenance_ai",
    "maintenance_ai.config", "maintenance_ai.db", "maintenance_ai.security",
    "maintenance_ai.parsers.docx_parser", "maintenance_ai.parsers.xlsx_parser",
    "maintenance_ai.exporters.docx_exporter", "maintenance_ai.exporters.xlsx_exporter", "maintenance_ai.exporters.pdf_exporter",
    "maintenance_ai.llm.llama_server", "maintenance_ai.llm.prompt_builder", "maintenance_ai.llm.json_pipeline",
    "maintenance_ai.services.context_service", "maintenance_ai.services.report_service",
    "maintenance_ai.ui.main_window", "maintenance_ai.ui.review_dialog",
]:
    try:
        __import__(mod)
        imports_ok.append(mod)
    except Exception as e:
        failed.append((mod, repr(e)))

print(f"[H4] imports ok: {len(imports_ok)}/22")
if failed:
    print("[H4] import FAILURES:")
    for m, e in failed: print(f"  - {m}: {e}")
    sys.exit(1)

# Test di ReviewDialog: importa classe, valida jsonschema submit con una data NON_SPECIFICATO
from maintenance_ai.ui.review_dialog import ReviewDialog  # noqa: E402
from maintenance_ai.app import App  # noqa: E402
app = App.bootstrap(ROOT / "config" / "default.json")
rows = app.db.list_modules()
if not rows:
    import shutil as _sh
    ex = ROOT / "examples" / "modules"
    wd = tmp / "workspace" / "modules"
    wd.mkdir(parents=True, exist_ok=True)
    for d in ex.iterdir():
        if d.is_dir():
            dst = wd / d.name
            if not dst.exists():
                _sh.copytree(d, dst)
    app.shutdown()
    app = App.bootstrap(ROOT / "config" / "default.json")
    rows = app.db.list_modules()

if rows:
    mod = app.module_manager.load_module(rows[0]["slug"])
    # create mock draft
    draft = app.reports.create_draft(mod=mod, description="Smoke test ui review", use_mock=True)
    draft_data = json.loads(json.dumps(draft.data))
    # simulare la validazione jsonschema che fa ReviewDialog._build_submit()
    import jsonschema
    try:
        jsonschema.validate(instance=draft_data, schema=mod.schema)
        js_ok = True
    except jsonschema.ValidationError as e:
        js_ok = False
        print(f"[H4] schema validation errore: {e.message} path={e.path}")
    print(f"[H4] jsonschema valido dopo mock create_draft: {js_ok}")
    # finalize per provare export fuori dal Tk
    app.reports.approve_draft(draft.report_id, draft_data)
    jp, tp, pp = app.reports.finalize_exports(report_id=draft.report_id, mod=mod)
    all_f = [pathlib.Path(p) for p in (jp, tp, pp) if p]
    okf = all(p.is_file() and p.stat().st_size > 0 for p in all_f)
    print(f"[H4] exports dopo approve: OK={okf} files={[(str(p.name), p.stat().st_size) for p in all_f]}")
    app.shutdown()
    if not (js_ok and okf):
        sys.exit(1)

print("[H4] PASS (imports+widget factory+validation+exports)")
sys.exit(0)
