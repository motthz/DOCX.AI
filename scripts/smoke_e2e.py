# H2: llama-server.exe reale + modello Qwen3, health check, poi shutdown
# H3: flusso report end-to-end create_draft -> approve -> finalize_exports
# H5: esporta modulo ZIP e lo valida
import os, sys, json, time, pathlib, urllib.request, urllib.parse, socket, subprocess, zipfile, hashlib, atexit, tempfile, shutil
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

results = {}

# ========================================================================= H2
print("=== H2: llama-server.exe reale + /health")
llama_dir = ROOT / "runtime" / "llama"
model = ROOT / "models" / "Qwen3-1.7B-Q8_0.gguf"
if not (llama_dir / "llama-server.exe").is_file():
    results["h2"] = ("SKIP", "manca llama-server.exe")
elif not model.is_file():
    results["h2"] = ("SKIP", "manca modello Qwen3-1.7B")
else:
    # porta libera range
    def free_port():
        s = socket.socket(); s.bind(("127.0.0.1", 0))
        p = s.getsockname()[1]; s.close(); return p
    port = free_port()
    key = hashlib.sha256(os.urandom(16)).hexdigest()
    env = os.environ.copy()
    env["PATH"] = str(llama_dir) + os.pathsep + env.get("PATH", "")
    cmd = [
        str(llama_dir / "llama-server.exe"),
        "-m", str(model),
        "--host", "127.0.0.1",
        "--port", str(port),
        "--api-key", key,
        "-c", "4096",
        "--no-webui",
    ]
    CREATE_NO_WINDOW = 0x08000000
    pop = subprocess.Popen(cmd, creationflags=CREATE_NO_WINDOW, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=env)
    atexit.register(lambda: pop.poll() is None and pop.kill())
    ok = False
    start = time.time()
    err = ""
    while time.time() - start < 180:
        time.sleep(3)
        if pop.poll() is not None:
            err = f"llama-server è morto subito exit={pop.returncode}"
            break
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/health")
            req.add_header("Authorization", f"Bearer {key}")
            with urllib.request.urlopen(req, timeout=5) as r:
                if r.status == 200:
                    ok = True
                    break
        except Exception as e:
            last_err = str(e)
    # shutdown
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/inference/server_state", method="POST")
        req.add_header("Authorization", f"Bearer {key}")
        req.add_header("Content-Type", "application/json")
        body = json.dumps({"action": "stop"}).encode()
        try:
            with urllib.request.urlopen(req, data=body, timeout=5) as r:
                _ = r.read()
        except:
            pass
    except:
        pass
    time.sleep(2)
    if pop.poll() is None:
        pop.terminate()
        time.sleep(2)
        if pop.poll() is None:
            pop.kill()
    results["h2"] = ("PASS" if ok else "FAIL", err or f"health status ok={ok} port={port}")
    print(results["h2"])

# ========================================================================= H3
print("\n=== H3: flusso report end-to-end create_draft -> approve -> finalize")
os.environ["MAINTENANCE_AI_CONFIG"] = str(ROOT / "config" / "default.json")
from maintenance_ai.app import App
from maintenance_ai.module_manager import ModuleManager  # noqa: F401
app = App.bootstrap(ROOT / "config" / "default.json")
atexit.register(lambda: app.shutdown())
# pick first module available in DB
rows = app.db.list_modules()
if not rows:
    results["h3"] = ("SKIP", "nessun modulo installato in DB")
else:
    r0 = rows[0]
    mod = app.module_manager.load_module(r0["slug"])
    print("usando modulo slug=", mod.slug, "name=", mod.name)
    draft = app.reports.create_draft(
        mod=mod,
        description="Controllo pompa P1. Verifica paraoli e ricambio effettuato. Pressione uscita 6.2 bar. Tutto OK dopo sostituzione. Manutenzione ordinaria.",
        use_mock=True,
    )
    print("draft ok, report_id=", draft.report_id, "success=", draft.success)
    approved = json.loads(json.dumps(draft.data))
    app.reports.approve_draft(report_id=draft.report_id, approved_data=approved)
    # finalize
    json_path, template_path, pdf_path = app.reports.finalize_exports(
        report_id=draft.report_id,
        mod=mod,
    )
    print("exports json =", json_path)
    print("exports tmpl =", template_path)
    print("exports pdf  =", pdf_path)
    paths = {
        "json": pathlib.Path(json_path),
        "pdf": pathlib.Path(pdf_path),
    }
    if template_path is not None:
        paths["template"] = pathlib.Path(template_path)
    checks = {k: {"exists": p.is_file(), "size": p.stat().st_size if p.is_file() else 0} for k, p in paths.items()}
    all_ok = all(v["exists"] and v["size"] > 0 for v in checks.values())
    # anche JSON parsabile
    parsed_ok = False
    if checks["json"]["exists"]:
        try:
            with open(paths["json"], "r", encoding="utf-8") as f:
                parsed_ok = isinstance(json.load(f), dict)
        except Exception:
            parsed_ok = False
        with open(paths["pdf"], "rb") as f:
            pdf_ok = f.read(5).startswith(b"%PDF-")
    results["h3"] = ("PASS" if all_ok and parsed_ok and pdf_ok else "FAIL", json.dumps({"files": checks, "json_parsed": parsed_ok, "pdf_header_ok": pdf_ok}, indent=2))
    print(results["h3"])

# ========================================================================= H5
print("\n=== H5: export modulo ZIP e validazione entries")
if not rows:
    results["h5"] = ("SKIP", "nessun modulo")
else:
    slug = rows[0]["slug"]
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="mai_h5_"))
    zip_out = out_dir / (slug + ".zip")
    exported = app.module_manager.export_module_zip(slug, zip_out)
    print("export ->", exported)
    issues = []
    if not zip_out.is_file() or zip_out.stat().st_size < 1024:
        issues.append("zip mancante o troppo piccolo")
    try:
        with zipfile.ZipFile(zip_out) as zf:
            names = zf.namelist()
            if len(names) < 3:
                issues.append("troppo poche entries")
            from maintenance_ai.security import safe_resolve_name
            for n in names:
                resolved = safe_resolve_name(out_dir, n)
                if str(resolved).startswith(str(out_dir)) is False:
                    issues.append(f"path escape in entry: {n}")
    except Exception as e:
        issues.append(f"zip invalido: {e}")
    shutil.rmtree(out_dir, ignore_errors=True)
    results["h5"] = ("PASS" if not issues else "FAIL", "; ".join(issues) or "zip OK entries safe")
    print(results["h5"])

print("\n=== RIEPILOGO")
for k, v in results.items():
    print(f"[{k}] {v[0]}: {v[1]}")
with open(ROOT / "dl_cache" / "h2h3h5.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)
sys.exit(0 if all(v[0] != "FAIL" for v in results.values()) else 1)
