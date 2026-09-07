$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

Write-Host "[setup_dev] Progetto: $ProjectRoot" -ForegroundColor Cyan

# 1. Python disponibile?
$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    throw "Python non trovato in PATH. Installare Python 3.12 x64."
}
& $python.Source --version

# 2. Crea venv se non esiste
$venv = Join-Path $ProjectRoot ".venv"
if (-not (Test-Path $venv)) {
    Write-Host "[setup_dev] Creazione ambiente virtuale .venv..." -ForegroundColor Yellow
    & $python.Source -m venv $venv
    if ($LASTEXITCODE -ne 0) { throw "creazione venv fallita" }
}
$venvPython = Join-Path $venv "Scripts\python.exe"
$venvPip = Join-Path $venv "Scripts\pip.exe"

# 3. Upgrade pip + installa dipendenze
Write-Host "[setup_dev] Installazione dipendenze da requirements-dev.txt..." -ForegroundColor Yellow
& $venvPython -m pip install --upgrade pip setuptools wheel
if ($LASTEXITCODE -ne 0) { throw "upgrade pip fallito" }

# 3b. Coverage (opzionale ma richiesto da scripts/test.ps1 --fail-under 70)
Write-Host "[setup_dev] Installazione coverage..." -ForegroundColor Gray
& $venvPip install coverage
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[setup_dev] coverage installazione fallita - test.ps1 puo' usare `$env:SKIP_COVERAGE_GATE=1 per bypassare"
}

$reqDev = Join-Path $ProjectRoot "requirements-dev.txt"
if (Test-Path $reqDev) {
    & $venvPip install -r $reqDev
    if ($LASTEXITCODE -ne 0) { throw "pip install -r requirements-dev.txt fallito" }
}

# 4. Scrivi lockfile per il build (non per eseguire)
$lockFile = Join-Path $ProjectRoot "requirements-lock.txt"
& $venvPython -m pip freeze | Out-File -FilePath $lockFile -Encoding ascii
Write-Host "[setup_dev] requirements-lock.txt creato" -ForegroundColor DarkGray

# 5. Auto-copia cartelle runtime se esistono
@("runtime\llama", "models") | ForEach-Object {
    $p = Join-Path $ProjectRoot $_
    if (-not (Test-Path $p)) {
        Write-Host "[setup_dev] ATTENZIONE: cartella mancante '$_' (da popolare prima del primo avvio con llama-server)" -ForegroundColor DarkYellow
    }
}

# 6. Verifica con self-test veloce
Write-Host "[setup_dev] Avvio self-test..." -ForegroundColor Yellow
$env:PYTHONPATH = "$ProjectRoot\src;$ProjectRoot"
& $venvPython -m maintenance_ai.main --self-test
if ($LASTEXITCODE -ne 0) {
    Write-Warning "[setup_dev] self-test terminato con exit code $LASTEXITCODE - vedere log sopra."
} else {
    Write-Host "[setup_dev] Ambiente pronto. Per avviare: scripts\run_dev.ps1" -ForegroundColor Green
}
