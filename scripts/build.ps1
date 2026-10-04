$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$venvPyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
@($venvPython, $venvPyInstaller) | ForEach-Object {
    if (-not (Test-Path $_)) { throw "Manca $_ - eseguire scripts\setup_dev.ps1" }
}

$SpecFile = Join-Path $ProjectRoot "packaging\DOCX.AI.spec"
if (-not (Test-Path $SpecFile)) { throw "Manca file spec: $SpecFile" }

# 0. Pulizia
foreach ($folder in @("build", "dist")) {
    $p = Join-Path $ProjectRoot $folder
    if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
}

# 0b. File di versione (unica fonte: src/docx_ai/__init__.py)
& $venvPython (Join-Path $ProjectRoot "packaging\gen_version.py")
if ($LASTEXITCODE -ne 0) { throw "gen_version fallito" }

# 1. Test obbligatori prima della build
Write-Host "[build] Esecuzione test..." -ForegroundColor Cyan
& (Join-Path $ProjectRoot "scripts\test.ps1")
if ($LASTEXITCODE -ne 0) { throw "test falliti: build annullata" }

# 2. PyInstaller (onedir)
Write-Host "[build] PyInstaller onedir..." -ForegroundColor Cyan
$env:PYTHONDONTWRITEBYTECODE = "1"
& $venvPyInstaller --noconfirm --clean $SpecFile
$pyiExit = $LASTEXITCODE
Remove-Item Env:\PYTHONDONTWRITEBYTECODE -ErrorAction SilentlyContinue
if ($pyiExit -ne 0) { throw "PyInstaller fallito (exit=$pyiExit)" }

# 3. Copia config/VERSION/LICENSES in dist (fallback se _internal non viene
#    popolato correttamente oppure vogliamo la tree "pubblica" chiara).
$DistDir = Join-Path $ProjectRoot "dist\DOCX.AI"
foreach ($rel in @("config", "LICENSES")) {
    $src = Join-Path $ProjectRoot $rel
    $dst = Join-Path $DistDir $rel
    if (Test-Path $src) {
        if (Test-Path $dst) { Remove-Item $dst -Recurse -Force -ErrorAction SilentlyContinue }
        Copy-Item -Path $src -Destination $dst -Recurse -Force
    }
}
foreach ($f in @("build\VERSION.txt")) {
    $src = Join-Path $ProjectRoot $f
    $dst = Join-Path $DistDir (Split-Path $f -Leaf)
    if (Test-Path $src) { Copy-Item -Path $src -Destination $dst -Force }
}

# 4. Self-test sull'eseguibile buildato
$Exe = Join-Path $ProjectRoot "dist\DOCX.AI\DOCX.AI.exe"
if (-not (Test-Path $Exe)) { throw "Atteso eseguibile non trovato: $Exe" }

Write-Host "[build] Self-test versione pacchettizzata..." -ForegroundColor Cyan
$so = Join-Path $env:TEMP "docxai_selftest_stdout.txt"
$se = Join-Path $env:TEMP "docxai_selftest_stderr.txt"
Remove-Item $so, $se -ErrorAction SilentlyContinue
$sp = Start-Process -FilePath $Exe -ArgumentList "--self-test" -Wait -PassThru -RedirectStandardOutput $so -RedirectStandardError $se -WindowStyle Hidden
Write-Host "[build] Self-test exit code: $($sp.ExitCode)" -ForegroundColor $(if ($sp.ExitCode -eq 0) { "Green" } else { "Red" })
if (Test-Path $se) {
    $err = Get-Content $se -Tail 40 -ErrorAction SilentlyContinue
    if ($err) { Write-Host "--- stderr ---" ; $err ; Write-Host "--- end stderr ---" }
}
if ($sp.ExitCode -ne 0) {
    throw "Self-test della build fallito (exit=$($sp.ExitCode)). Build NON valida."
}
# 5. Smoke test dell'interfaccia sull'exe (pagine e dialoghi, cartella dati temporanea)
Write-Host "[build] Smoke test GUI dell'exe..." -ForegroundColor Cyan
$gs = Start-Process -FilePath $Exe -ArgumentList "--gui-smoke" -Wait -PassThru -WindowStyle Normal `
    -RedirectStandardOutput (Join-Path $env:TEMP "docxai_guismoke.txt")
if ($gs.ExitCode -ne 0) {
    Get-Content (Join-Path $env:TEMP "docxai_guismoke.txt") -Tail 40
    throw "Smoke test GUI della build fallito (exit=$($gs.ExitCode))."
}
Write-Host "[build] OK. Eseguibile: $Exe" -ForegroundColor Green
