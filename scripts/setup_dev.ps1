$ErrorActionPreference = "Stop"
# Ambiente di sviluppo: venv, dipendenze bloccate con hash, hook pre-commit, self-test.
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
Write-Host "[setup_dev] Progetto: $ProjectRoot" -ForegroundColor Cyan

if ($ProjectRoot -match "OneDrive|Dropbox|Google Drive") {
    Write-Warning "[setup_dev] Il progetto e' in una cartella sincronizzata: sposta il repository (es. C:\Dev) per evitare file bloccati durante build e git."
}

$python = Get-Command py -ErrorAction SilentlyContinue
$pyArgs = @("-3.12")
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue; $pyArgs = @() }
if (-not $python) { throw "Python 3.12 x64 non trovato. Installare con: winget install Python.Python.3.12" }

$venv = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "[setup_dev] Creazione .venv..." -ForegroundColor Yellow
    & $python.Source @pyArgs -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "creazione venv fallita" }
}
$venvPython = Join-Path $venv "Scripts\python.exe"

Write-Host "[setup_dev] Dipendenze (lock con hash)..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install --require-hashes -r (Join-Path $ProjectRoot "requirements.txt")
if ($LASTEXITCODE -ne 0) { throw "installazione requirements.txt fallita" }
& $venvPython -m pip install --require-hashes -r (Join-Path $ProjectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) { throw "installazione requirements-dev.txt fallita" }

$preCommit = Join-Path $venv "Scripts\pre-commit.exe"
if (Test-Path $preCommit) {
    & $preCommit install --hook-type pre-commit --hook-type commit-msg | Out-Null
    Write-Host "[setup_dev] Hook pre-commit installati." -ForegroundColor DarkGray
}

Write-Host "[setup_dev] Self-test..." -ForegroundColor Yellow
$env:PYTHONPATH = "$ProjectRoot\src;$ProjectRoot"
& $venvPython -m docx_ai.main --self-test
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[setup_dev] self-test terminato con exit code $LASTEXITCODE."
} else {
    Write-Host "[setup_dev] Ambiente pronto. Avvio: scripts\run_dev.ps1" -ForegroundColor Green
}
