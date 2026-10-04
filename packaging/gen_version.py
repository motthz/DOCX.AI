r"""Genera i file di versione per la build partendo da docx_ai.__version__
(unica fonte della versione):
  build/version_info.txt   risorsa di versione dell'exe (PyInstaller)
  build/VERSION.txt        copiato nella cartella dell'app
"""

from __future__ import annotations

import datetime
import platform
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from docx_ai import __version__  # noqa: E402

OUT = ROOT / "build"


def main() -> None:
    OUT.mkdir(exist_ok=True)
    parts = [int(x) for x in __version__.split(".")[:3]] + [0]
    t = tuple(parts[:4])
    (OUT / "version_info.txt").write_text(f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={t}, prodvers={t}, mask=0x3f, flags=0x0,
                    OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('041004B0', [
      StringStruct('CompanyName', 'DOCX.AI'),
      StringStruct('FileDescription', 'DOCX.AI - Rapporti di manutenzione con AI locale'),
      StringStruct('FileVersion', '{__version__}'),
      StringStruct('InternalName', 'DOCX.AI'),
      StringStruct('LegalCopyright', 'Copyright (c) {datetime.date.today().year} DOCX.AI. Tutti i diritti riservati.'),
      StringStruct('OriginalFilename', 'DOCX.AI.exe'),
      StringStruct('ProductName', 'DOCX.AI'),
      StringStruct('ProductVersion', '{__version__}')])]),
    VarFileInfo([VarStruct('Translation', [0x0410, 1200])])
  ]
)
""", encoding="utf-8")
    (OUT / "VERSION.txt").write_text(
        f"DOCX.AI: {__version__}\n"
        f"Build date: {datetime.date.today().isoformat()}\n"
        f"Python: {platform.python_version()}\n"
        "Componenti AI: scaricati dall'app (llama.cpp + Qwen3 GGUF)\n",
        encoding="utf-8")
    print(f"version files for {__version__} -> {OUT}")


if __name__ == "__main__":
    main()
