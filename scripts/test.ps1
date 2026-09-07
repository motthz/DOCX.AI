$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot
$env:PYTHONDONTWRITEBYTECODE = "1"

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Ambiente virtuale non trovato. Eseguire prima scripts\setup_dev.ps1."
}
$env:PYTHONPATH = "$ProjectRoot\src;$ProjectRoot"

# 1. Unittest (con o senza coverage)
Write-Host "[test] Unittest package: tests" -ForegroundColor Cyan

$hasCoverage = $false
try {
    $out = & $venvPython -c "import coverage; print(coverage.__version__)" 2>$null
    if ($LASTEXITCODE -eq 0 -and $out) { $hasCoverage = $true }
} catch {}

$skipCoverage = [bool]$env:SKIP_COVERAGE_GATE
if ($hasCoverage -and -not $skipCoverage) {
    Write-Host "[test] Coverage attivo (fail-under=70). Usare `$env:SKIP_COVERAGE_GATE=1 per bypassare." -ForegroundColor DarkGray
    & $venvPython -m coverage run --source=src/maintenance_ai --branch -m unittest discover -s tests -v
    $unitExit = $LASTEXITCODE
    if ($unitExit -eq 0) {
        & $venvPython -m coverage report --show-missing --fail-under=70
        $covExit = $LASTEXITCODE
        if ($covExit -ne 0) {
            Write-Error "[test] Coverage soglia 70% non raggiunta (exit=$covExit). Aumenta coverage o imposta SKIP_COVERAGE_GATE=1"
            exit 1
        }
    }
} else {
    if ($skipCoverage) {
        Write-Host "[test] SKIP_COVERAGE_GATE attivo - salto coverage threshold." -ForegroundColor Yellow
    } elseif (-not $hasCoverage) {
        Write-Warning "[test] Modulo 'coverage' non installato. Esegui scripts\setup_dev.ps1 o imposta SKIP_COVERAGE_GATE=1."
    }
    & $venvPython -m unittest discover -s tests -v
    $unitExit = $LASTEXITCODE
}

# 2. Self-test
Write-Host "[test] --self-test applicazione" -ForegroundColor Cyan
& $venvPython -m maintenance_ai.main --self-test
$selfExit = $LASTEXITCODE

Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
if ($unitExit -ne 0 -or $selfExit -ne 0) {
    Write-Error "[test] Fallito. unittest=$unitExit self-test=$selfExit"
    exit 1
}
Write-Host "[test] OK" -ForegroundColor Green
