# MaintenanceAI Launcher - PyInstaller onefile
# Entry point: src/launcher.py
# Modalita' ONE-FILE per creare un singolo MaintenanceAI.exe nella root.
# Non include nessuna dipendenza di MaintenanceAI: solo il launcher e la stdlib.

import os
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent.parent if Path(SPECPATH).resolve().parent.name == "packaging" else Path(SPECPATH).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

block_cipher = None

a = Analysis(
    [str(SRC / "launcher.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "PIL",
        "docx",
        "openpyxl",
        "reportlab",
        "jsonschema",
        "defusedxml",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="MaintenanceAI",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # NO console: usa MessageBox per errori
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
