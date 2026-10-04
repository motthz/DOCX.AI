$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

$venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    throw "Ambiente virtuale non trovato. Eseguire prima scripts\setup_dev.ps1."
}
$env:PYTHONPATH = "$ProjectRoot\src;$ProjectRoot"
& $venvPython -m docx_ai.main @args
exit $LASTEXITCODE
