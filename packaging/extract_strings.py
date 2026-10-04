r"""Estrae le stringhe dell'interfaccia da tradurre in src/docx_ai/locales/en.json.

    .venv\Scripts\python.exe packaging\extract_strings.py [--check]

Raccoglie i testi passati a t(...) e, nelle finestre Tk, i valori di text=/title=/
label=, i titoli delle finestre e i messaggi dei messagebox. Le chiavi nuove vengono
aggiunte al catalogo con valore vuoto (da tradurre); --check fallisce se mancano
traduzioni.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "src" / "docx_ai" / "ui"
CATALOG = ROOT / "src" / "docx_ai" / "locales" / "en.json"
TEXT_KW = {"text", "title", "label", "subtitle", "placeholder_text", "message", "prompt"}
MSG_FUNCS = {"showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askyesnocancel"}
_PREFIX = re.compile(r"^([^\w«(\"'¿¡{\[]*)(.*?)(\s*)$", re.S)


def _core(s: str) -> str:
    m = _PREFIX.match(s)
    return (m.group(2) if m else s).strip()


def _const(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def extract() -> set:
    out = set()
    for f in UI.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            cands = []
            if name == "t" and node.args:
                cands.append(_const(node.args[0]))
            if name in MSG_FUNCS or name in ("title", "wm_title", "heading", "add_command", "add"):
                cands += [_const(a) for a in node.args[:2]]
            for kw in node.keywords:
                if kw.arg in TEXT_KW:
                    cands.append(_const(kw.value))
            for c in cands:
                if c and re.search(r"[A-Za-zÀ-ÿ]{2}", c):
                    core = _core(c)
                    if core and not re.fullmatch(r"[\w.\-]+\.(py|json|docx|xlsx|zip|png)", core):
                        out.add(core)
    from docx_ai.docintelligence.rules_manager import FEATURE_LABELS_V2
    out.update(FEATURE_LABELS_V2.values())
    # etichette passate a t() tramite variabili (schede, stati dello storico)
    from docx_ai.ui.pages.history import STATUS, STATUS_LABEL
    from docx_ai.ui.shell import PAGES
    out.update(lbl for _k, lbl, _i in PAGES)
    out.update(lbl for _k, lbl in STATUS)
    out.update(STATUS_LABEL.values())
    out.update(("Approvazione", "Importazione"))
    return out


def main() -> int:
    sys.path.insert(0, str(ROOT / "src"))
    keys = extract()
    cat = json.loads(CATALOG.read_text(encoding="utf-8")) if CATALOG.is_file() else {}
    removed = [k for k in cat if k not in keys]
    cat = {k: cat.get(k, "") for k in sorted(keys)}  # rimuove le stringhe non piu' usate
    missing = [k for k, v in cat.items() if not v]
    if "--check" in sys.argv:
        if missing:
            print(f"{len(missing)} stringhe senza traduzione inglese:")
            print("\n".join(missing[:50]))
            return 1
        print(f"Catalogo completo: {len(cat)} stringhe.")
        return 0
    CATALOG.parent.mkdir(parents=True, exist_ok=True)
    CATALOG.write_text(json.dumps(dict(sorted(cat.items())), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{len(cat)} stringhe nel catalogo, {len(missing)} da tradurre, {len(removed)} rimosse -> {CATALOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
