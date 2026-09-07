# Solo H3 + H5 (H2 già PASSATO due volte)
import os, sys, json, time, pathlib, zipfile, tempfile, shutil, atexit
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
results = {}
# Forza DATA_DIR locale per evitare lock sandbox del -journal in LOCALAPPDATA
tmp_data = ROOT / "dl_cache" / "smoke_data"
if tmp_data.exists():
    # safety remove previous journal
    for p in tmp_data.rglob("*.db-journal"):
        try: p.unlink()
        except Exception: pass
tmp_data.mkdir(parents=True, exist_ok=True)
os.environ["MAINTENANCE_AI_DATA_DIR"] = str(tmp_data)
os.environ["MAINTENANCE_AI_CONFIG"] = str(ROOT / "config" / "default.json")
# Copia preventiva esempi moduli in smoke_data workspace PRIMA del bootstrap
wd = tmp_data / "workspace" / "modules"
ex = ROOT / "examples" / "modules"
if ex.exists():
    wd.mkdir(parents=True, exist_ok=True)
    for d in ex.iterdir():
        if d.is_dir():
            dst = wd / d.name
            if not dst.exists():
                import shutil as _sh
                _sh.copytree(d, dst)
from maintenance_ai.app import App
app = App.bootstrap(ROOT / "config" / "default.json")
atexit.register(lambda: app.shutdown())
rows = app.db.list_modules()
if not rows:
    for slug in sorted([p.name for p in wd.iterdir() if p.is_dir()]):
        try:
            app.module_manager.load_module(slug)
        except Exception:
            pass
    rows = app.db.list_modules()
if not rows:
    results["h3"] = ("SKIP", "no moduli in DB")
    results["h5"] = ("SKIP", "no moduli in DB")
else:
    # H3
    r0 = rows[0]
    mod = app.module_manager.load_module(r0["slug"])
    draft = app.reports.create_draft(
        mod=mod,
        description="Controllo pompa P1. Verifica paraoli e ricambio effettuato. Pressione uscita 6.2 bar. Tutto OK dopo sostituzione. Manutenzione ordinaria.",
        use_mock=True,
    )
    approved = json.loads(json.dumps(draft.data))
    app.reports.approve_draft(report_id=draft.report_id, approved_data=approved)
    json_path, template_path, pdf_path = app.reports.finalize_exports(report_id=draft.report_id, mod=mod)
    paths = {"json": pathlib.Path(json_path), "pdf": pathlib.Path(pdf_path)}
    if template_path: paths["template"] = pathlib.Path(template_path)
    checks = {k: {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else 0} for k, p in paths.items()}
    all_ok = all(v["exists"] and v["size"] > 0 for v in checks.values())
    parsed_ok = False
    pdf_ok = False
    if checks["json"]["exists"]:
        with open(paths["json"], "r", encoding="utf-8") as f: parsed_ok = isinstance(json.load(f), dict)
    if checks["pdf"]["exists"]:
        with open(paths["pdf"], "rb") as f: pdf_ok = f.read(5).startswith(b"%PDF-")
    results["h3"] = ("PASS" if all_ok and parsed_ok and pdf_ok else "FAIL", json.dumps({"files": checks, "json_parsed": parsed_ok, "pdf_header_ok": pdf_ok, "report_id": draft.report_id}, indent=2))
    print("H3", results["h3"])

    # H5
    slug = rows[0]["slug"]
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="mai_h5_"))
    zip_out = out_dir / (slug + ".zip")
    exported = app.module_manager.export_module_zip(slug, zip_out)
    issues = []
    if not (isinstance(exported, pathlib.Path) or isinstance(zip_out, pathlib.Path)) or not zip_out.is_file() or zip_out.stat().st_size < 1024:
        issues.append("zip mancante o troppo piccolo")
    try:
        with zipfile.ZipFile(zip_out) as zf:
            names = zf.namelist()
            if len(names) < 3: issues.append("troppo poche entries (" + str(len(names)) + ")")
            from maintenance_ai.security import safe_resolve_name
            for n in names:
                resolved = safe_resolve_name(out_dir, n)
                if not str(resolved).startswith(str(out_dir) + os.sep) and str(resolved) != str(out_dir):
                    issues.append(f"path escape in entry: {n}")
    except Exception as e:
        issues.append(f"zip invalido: {e}")
    shutil.rmtree(out_dir, ignore_errors=True)
    results["h5"] = ("PASS" if not issues else "FAIL", "; ".join(issues) or "zip OK entries safe")
    print("H5", results["h5"])

print("\n=== RIEPILOGO H3/H5 ===")
for k, v in results.items():
    print(f"[{k}] {v[0]}: {v[1]}")
with open(ROOT / "dl_cache" / "h3h5.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
sys.exit(0 if all(v[0] != "FAIL" for v in results.values()) else 1)
