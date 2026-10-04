r"""Genera i manifest winget (schema 1.9) per la release corrente.

    .venv\Scripts\python.exe scripts\winget_manifest.py

Usa release\MaintenanceAI-Setup-<ver>.exe per calcolare lo SHA-256 e scrive i
manifest in release\winget\<ver>\. Per pubblicarli nel catalogo ufficiale:
    winget install wingetcreate
    wingetcreate submit --token <PAT GitHub> release\winget\<ver>
(la PR verso microsoft/winget-pkgs va inviata dal titolare dell'account).
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from maintenance_ai import __version__  # noqa: E402

PKG = "MaintenanceAI.MaintenanceAI"
REPO = "https://github.com/motthz/MaintenanceAI"
SCHEMA = "https://aka.ms/winget-manifest.{kind}.1.9.0.schema.json"


def main() -> None:
    setup = ROOT / "release" / f"MaintenanceAI-Setup-{__version__}.exe"
    if not setup.is_file():
        raise SystemExit(f"Installer mancante: {setup} (eseguire scripts\release.ps1)")
    sha = hashlib.sha256(setup.read_bytes()).hexdigest().upper()
    out = ROOT / "release" / "winget" / __version__
    out.mkdir(parents=True, exist_ok=True)
    head = f"PackageIdentifier: {PKG}\nPackageVersion: {__version__}\n"
    (out / f"{PKG}.yaml").write_text(
        f"# yaml-language-server: $schema={SCHEMA.format(kind='version')}\n{head}"
        "DefaultLocale: it-IT\nManifestType: version\nManifestVersion: 1.9.0\n", encoding="utf-8")
    (out / f"{PKG}.installer.yaml").write_text(
        f"# yaml-language-server: $schema={SCHEMA.format(kind='installer')}\n{head}"
        "InstallerType: inno\nScope: user\nUpgradeBehavior: install\n"
        "InstallerSwitches:\n  Silent: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER\n"
        "  SilentWithProgress: /SILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER\n"
        "Installers:\n  - Architecture: x64\n"
        f"    InstallerUrl: {REPO}/releases/download/v{__version__}/{setup.name}\n"
        f"    InstallerSha256: {sha}\n"
        "ManifestType: installer\nManifestVersion: 1.9.0\n", encoding="utf-8")
    (out / f"{PKG}.locale.it-IT.yaml").write_text(
        f"# yaml-language-server: $schema={SCHEMA.format(kind='defaultLocale')}\n{head}"
        "PackageLocale: it-IT\nPublisher: MaintenanceAI\nPackageName: MaintenanceAI\n"
        f"PackageUrl: {REPO}\nLicense: Proprietaria\nLicenseUrl: {REPO}/blob/main/LICENSE\n"
        "ShortDescription: Rapporti di manutenzione con AI locale e offline\n"
        "Tags: [manutenzione, rapporti, ai, offline]\n"
        f"ReleaseNotesUrl: {REPO}/releases/tag/v{__version__}\n"
        "ManifestType: defaultLocale\nManifestVersion: 1.9.0\n", encoding="utf-8")
    print(f"Manifest winget in {out}")


if __name__ == "__main__":
    main()
