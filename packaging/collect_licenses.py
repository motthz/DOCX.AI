r"""Raccoglie in LICENSES/ i testi di licenza completi dei componenti distribuiti.

    .venv\Scripts\python.exe packaging\collect_licenses.py

Fonti: metadati dei pacchetti installati (dist-info), licenza di Python e di
Tcl/Tk dell'interprete usato per la build, testi fissi per llama.cpp e Qwen3.
"""

from __future__ import annotations

import importlib.metadata as md
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "LICENSES"


def runtime_packages() -> list[str]:
    names = []
    for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z0-9_.\-]+)==", line)
        if m:
            names.append(m.group(1))
    return names


def license_text(dist: md.Distribution) -> str:
    chunks = []
    for f in dist.files or []:
        name = f.name.lower()
        if any(k in name for k in ("license", "licence", "copying", "notice")) and "dist-info" in str(f):
            try:
                chunks.append(Path(dist.locate_file(f)).read_text(encoding="utf-8", errors="replace"))
            except OSError:
                pass
    if not chunks:
        meta = dist.metadata
        chunks.append(meta.get("License-Expression") or meta.get("License") or "Vedi metadati del pacchetto.")
    return "\n\n".join(chunks)


LLAMA_MIT = """MIT License

Copyright (c) 2023-2026 The ggml authors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

QWEN = """Modelli Qwen3 (Qwen/Qwen3-1.7B-GGUF, Qwen/Qwen3-0.6B-GGUF)
Copyright (c) Alibaba Cloud. Distribuiti con licenza Apache License 2.0:
https://www.apache.org/licenses/LICENSE-2.0
I modelli NON sono inclusi nell'installer: vengono scaricati dall'utente
dalla finestra "Componenti AI" direttamente da HuggingFace.
"""


def main() -> None:
    OUT.mkdir(exist_ok=True)
    index = ["DOCX.AI - licenze dei componenti di terze parti", "=" * 56, ""]
    for name in runtime_packages() + ["pyinstaller"]:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            continue
        lic = dist.metadata.get("License-Expression") or dist.metadata.get("License") or ""
        fname = f"{dist.metadata['Name']}.txt"
        (OUT / fname).write_text(license_text(dist), encoding="utf-8")
        index.append(f"- {dist.metadata['Name']} {dist.version}  ({lic.splitlines()[0][:60] if lic else 'vedi file'})  -> {fname}")
    base = Path(sys.base_prefix)
    py_lic = base / "LICENSE.txt"
    if py_lic.is_file():
        (OUT / "Python.txt").write_text(py_lic.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        index.append(f"- Python {sys.version.split()[0]} (PSF License)  -> Python.txt")
    tcl = next((base / "tcl").glob("t*8*/license.terms"), None) if (base / "tcl").is_dir() else None
    if tcl:
        (OUT / "Tcl-Tk.txt").write_text(tcl.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
        index.append("- Tcl/Tk (BSD-style)  -> Tcl-Tk.txt")
    (OUT / "llama.cpp.txt").write_text(LLAMA_MIT, encoding="utf-8")
    index.append("- llama.cpp (MIT, scaricato a richiesta)  -> llama.cpp.txt")
    (OUT / "Qwen3.txt").write_text(QWEN, encoding="utf-8")
    index.append("- Modelli Qwen3 (Apache-2.0, scaricati a richiesta)  -> Qwen3.txt")
    index.append("- Icone Lucide (ISC)  -> Lucide.txt")
    (OUT / "README.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
    print("\n".join(index))


if __name__ == "__main__":
    main()
