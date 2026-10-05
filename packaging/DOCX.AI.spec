# DOCX.AI PyInstaller spec - onedir mode.
# Invocato da scripts\build.ps1 via `pyinstaller --clean packaging\DOCX.AI.spec`
#
# - onedir (non onefile): llama-server.exe, le DLL e il modello GGUF
#   rimangono file separati, più facili da aggiornare/diagnosticare.
# - Manteniamo separati anche config/ VERSION.txt LICENSES/;
#   package.ps1 li copia nella cartella di release.

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent  # repo root (genitore di packaging/)
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

block_cipher = None

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hidden = collect_submodules("docx_ai") + collect_submodules("customtkinter") + [
    "docx", "openpyxl", "reportlab", "jsonschema", "defusedxml", "defusedxml.ElementTree", "defusedxml.common",
    "reportlab.graphics", "reportlab.graphics.barcode", "reportlab.lib", "reportlab.pdfbase", "reportlab.pdfgen",
    "reportlab.platypus", "PIL", "PIL._tkinter_finder", "PIL.Image", "PIL.ImageDraw", "PIL.ImageFont",
    "PIL.ImageTk", "pypdfium2", "pypdf", "darkdetect",
]

a = Analysis(
    [str(SRC / "docx_ai" / "__main__.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=collect_dynamic_libs("pypdfium2") + collect_dynamic_libs("pypdfium2_raw"),
    datas=[
        (str(ROOT / "config"), "config"),
        (str(ROOT / "build" / "VERSION.txt"), "."),
        (str(ROOT / "LICENSES"), "LICENSES"),
        (str(SRC / "docx_ai" / "assets"), "docx_ai/assets"),
        (str(SRC / "docx_ai" / "locales"), "docx_ai/locales"),
        (str(ROOT / "docs"), "docs"),
        (str(ROOT / "examples"), "examples"),  # moduli di esempio (pulsante nella barra laterale)
    ] + collect_data_files("customtkinter") + collect_data_files("pypdfium2") + collect_data_files("pypdfium2_raw"),
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Non usati: riducono dimensione e tempo di avvio (punto 58)
        "matplotlib", "numpy", "pandas", "scipy", "IPython", "jupyter", "notebook", "pytest", "black",
        "mypy", "ruff", "coverage", "setuptools", "pip", "pkg_resources", "unittest", "pydoc", "pydoc_data",
        "doctest", "lib2to3", "xmlrpc", "tkinter.test", "test", "distutils", "lxml.html", "lxml.isoschematron",
        "lxml.objectify", "PIL.ImageQt", "PIL.ImageShow", "PIL.FpxImagePlugin", "PIL.MicImagePlugin",
        "PyInstaller",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
    optimize=2,  # bytecode ottimizzato, senza assert e docstring (punto 59)
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

MANIFEST_FILE = str(Path(SPECPATH).resolve() / "app.manifest")
ICON_FILE = str(SRC / "docx_ai" / "assets" / "app.ico")
VERSION_FILE = str(ROOT / "build" / "version_info.txt")  # da packaging/gen_version.py

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DOCX.AI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Applicazione a finestra (nessuna console nera). Gli errori di avvio
    # finiscono in %LOCALAPPDATA%\DOCX.AI\logs\crash.log e in una MessageBox.
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest=MANIFEST_FILE,
    icon=ICON_FILE,
    version=VERSION_FILE,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DOCX.AI",
)
