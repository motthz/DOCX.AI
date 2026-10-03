# MaintenanceAI: build completa di release.
#   1. scripts\build.ps1  (test + PyInstaller onedir + self-test dell'exe)
#   2. release\MaintenanceAI-<ver>-portable-win64.zip
#   3. release\MaintenanceAI-Setup-<ver>.exe  (Inno Setup 6)
# Uso:  powershell -ExecutionPolicy Bypass -File scripts\release.ps1 [-SkipBuild]
param([switch]$SkipBuild)
$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$Version = (& $venvPython -c "import sys; sys.path.insert(0, 'src'); import maintenance_ai; print(maintenance_ai.__version__)").Trim()
Write-Host "[release] MaintenanceAI $Version" -ForegroundColor Cyan

if (-not $SkipBuild) {
    & (Join-Path $ProjectRoot "scripts\build.ps1")
    if ($LASTEXITCODE -ne 0) { throw "build.ps1 fallito" }
}
$DistDir = Join-Path $ProjectRoot "dist\MaintenanceAI"
if (-not (Test-Path (Join-Path $DistDir "MaintenanceAI.exe"))) { throw "Build mancante: $DistDir" }

$ReleaseDir = Join-Path $ProjectRoot "release"
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null

# Portable ZIP
$Zip = Join-Path $ReleaseDir "MaintenanceAI-$Version-portable-win64.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path $DistDir -DestinationPath $Zip -CompressionLevel Optimal
Write-Host "[release] ZIP portable: $Zip" -ForegroundColor Green

# Installer Inno Setup
$iscc = @(
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
    (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 non trovato. Installare con: winget install JRSoftware.InnoSetup" }
& $iscc "/Q" "/DAppVersion=$Version" (Join-Path $ProjectRoot "packaging\installer\MaintenanceAI.iss")
if ($LASTEXITCODE -ne 0) { throw "ISCC fallito (exit=$LASTEXITCODE)" }
Write-Host "[release] Installer: $(Join-Path $ReleaseDir "MaintenanceAI-Setup-$Version.exe")" -ForegroundColor Green
