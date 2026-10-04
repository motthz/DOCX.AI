"""Stampa la sezione del CHANGELOG.md relativa a una versione (note di rilascio)."""

import sys
from pathlib import Path

text = (Path(__file__).resolve().parent.parent / "CHANGELOG.md").read_text(encoding="utf-8")
version = sys.argv[1]
out, inside = [], False
for line in text.splitlines():
    if line.startswith("## "):
        if inside:
            break
        inside = line.startswith(f"## [{version}]")
        continue
    if inside:
        out.append(line)
print("\n".join(out).strip() or f"MaintenanceAI {version}")
