# MaintenanceAI PyInstaller spec - onedir mode.
# Invocato da scripts\build.ps1 via `pyinstaller --clean packaging\MaintenanceAI.spec`
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

a = Analysis(
    [str(SRC / "maintenance_ai" / "__main__.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "config"), "config"),
        (str(ROOT / "build" / "VERSION.txt"), "."),
        (str(ROOT / "LICENSES"), "LICENSES"),
        (str(SRC / "maintenance_ai" / "assets"), "maintenance_ai/assets"),
    ],
    hiddenimports=[
        "maintenance_ai",
        "maintenance_ai.config",
        "maintenance_ai.db",
        "maintenance_ai.security",
        "maintenance_ai.module_manager",
        "maintenance_ai.app",
        "maintenance_ai.main",
        "maintenance_ai.parsers",
        "maintenance_ai.parsers.docx_parser",
        "maintenance_ai.parsers.xlsx_parser",
        "maintenance_ai.exporters",
        "maintenance_ai.exporters.docx_exporter",
        "maintenance_ai.exporters.xlsx_exporter",
        "maintenance_ai.exporters.pdf_exporter",
        "maintenance_ai.llm",
        "maintenance_ai.llm.llama_server",
        "maintenance_ai.llm.prompt_builder",
        "maintenance_ai.llm.json_pipeline",
        "maintenance_ai.llm.ollama_backend",
        "maintenance_ai.llm.ai_installer",
        "maintenance_ai.services",
        "maintenance_ai.services.context_service",
        "maintenance_ai.services.report_service",
        "maintenance_ai.ui",
        "maintenance_ai.ui.theme",
        "maintenance_ai.ui.main_window",
        "maintenance_ai.ui.review_dialog",
        "maintenance_ai.ui.help_dialog",
        "maintenance_ai.ui.assets",
        "maintenance_ai.ui.ai_setup_dialog",
        "docx",
        "openpyxl",
        "reportlab",
        "jsonschema",
        "defusedxml",
        "defusedxml.ElementTree",
        "defusedxml.common",
        # ReportLab plugins
        "reportlab.graphics",
        "reportlab.graphics.barcode",
        "reportlab.lib",
        "reportlab.pdfbase",
        "reportlab.pdfgen",
        "reportlab.platypus",
        # PIL usato internamente da reportlab (anche se non direttamente dall'app)
        "PIL",
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageDraw",
        "PIL.ImageFont",
        "PIL.ImageTk",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Riducono dimensione pacchetto: non usati
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "IPython",
        "jupyter",
        "notebook",
        "pytest",
        "black",
        "mypy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

MANIFEST_FILE = str(Path(SPECPATH).resolve() / "app.manifest")
ICON_FILE = str(SRC / "maintenance_ai" / "assets" / "app.ico")
VERSION_FILE = str(ROOT / "build" / "version_info.txt")  # da packaging/gen_version.py

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MaintenanceAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Applicazione a finestra (nessuna console nera). Gli errori di avvio
    # finiscono in %LOCALAPPDATA%\MaintenanceAI\logs\crash.log e in una MessageBox.
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
    name="MaintenanceAI",
)
