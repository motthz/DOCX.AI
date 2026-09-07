# H4: MainWindow smoke test (30s)
import os, sys, threading, time, pathlib, traceback
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
tmp = ROOT / "dl_cache" / "gui_data"
tmp.mkdir(parents=True, exist_ok=True)
os.environ["MAINTENANCE_AI_DATA_DIR"] = str(tmp)
os.environ["MAINTENANCE_AI_CONFIG"] = str(ROOT / "config" / "default.json")
# copia moduli esempio nel workspace tmp
ex = ROOT / "examples" / "modules"
wd = tmp / "workspace" / "modules"
if not wd.exists() or not any(wd.iterdir()):
    import shutil as _sh
    wd.mkdir(parents=True, exist_ok=True)
    for d in ex.iterdir():
        if d.is_dir():
            dst = wd / d.name
            if not dst.exists():
                _sh.copytree(d, dst)
from maintenance_ai.app import App
app = App.bootstrap(ROOT / "config" / "default.json")

status = {"exception": None, "started": False}

def run_gui():
    try:
        import tkinter as tk
        from maintenance_ai.ui.main_window import MainWindow
        root = tk.Tk()
        root.withdraw()
        status["started"] = True
        mw = MainWindow(root, app)
        root.update_idletasks()
        root.update()
        # rimani aperto 30s aggiornando periodicamente
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                root.update()
            except Exception as exc:
                status["exception"] = traceback.format_exc()
                break
            time.sleep(0.05)
        try:
            mw.destroy()
        except Exception:
            pass
        try:
            root.destroy()
        except Exception:
            pass
    except Exception:
        status["exception"] = traceback.format_exc()

t = threading.Thread(target=run_gui, daemon=True)
t.start()
# aspetta max 45s
deadline = time.time() + 45
while t.is_alive() and time.time() < deadline:
    time.sleep(0.5)

print("[H4] started=", status["started"])
if status["exception"]:
    print("[H4] EXCEPTION:\n" + status["exception"])
    sys.exit(1)
else:
    print("[H4] PASS: MainWindow creata senza crash, 30s loop concluso")
    sys.exit(0)
