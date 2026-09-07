$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $ProjectRoot

# Prima esegue build.ps1 (già esegue test + self-test)
& (Join-Path $ProjectRoot "scripts\build.ps1")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$PackageRoot = Join-Path $ProjectRoot "release\MaintenanceAI"
if (Test-Path $PackageRoot) { Remove-Item $PackageRoot -Recurse -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Path $PackageRoot -Force | Out-Null

# 1. Copia contenuto dist
Copy-Item (Join-Path $ProjectRoot "dist\MaintenanceAI\*") $PackageRoot -Recurse -Force

# 2. runtime/llama
$RuntimeSrc = Join-Path $ProjectRoot "runtime\llama"
if (Test-Path $RuntimeSrc) {
    $RuntimeDst = Join-Path $PackageRoot "runtime\llama"
    New-Item -ItemType Directory -Path $RuntimeDst -Force | Out-Null
    Copy-Item "$RuntimeSrc\*" $RuntimeDst -Recurse -Force
} else {
    Write-Warning "[package] runtime\llama non presente - pacchetto NON sarà avviabile senza runtime."
}

# 3. models/*.gguf (se presenti)
$ModelsSrc = Join-Path $ProjectRoot "models"
if (Test-Path $ModelsSrc) {
    $Ggufs = Get-ChildItem $ModelsSrc -Filter "*.gguf" -ErrorAction SilentlyContinue
    if ($Ggufs) {
        $ModelsDst = Join-Path $PackageRoot "models"
        New-Item -ItemType Directory -Path $ModelsDst -Force | Out-Null
        Copy-Item $Ggufs.FullName $ModelsDst -Force
    } else {
        Write-Warning "[package] Nessun file .gguf trovato in models\"
    }
}

# 4. config e licenze
Copy-Item (Join-Path $ProjectRoot "config") (Join-Path $PackageRoot "config") -Recurse -Force
Copy-Item (Join-Path $ProjectRoot "LICENSES") (Join-Path $PackageRoot "LICENSES") -Recurse -Force
Copy-Item (Join-Path $ProjectRoot "VERSION.txt") (Join-Path $PackageRoot "VERSION.txt") -Force

# 5. Self-test sul pacchetto finito
Write-Host "[package] Esecuzione self-test pacchetto..." -ForegroundColor Cyan
$PkgExe = Join-Path $PackageRoot "MaintenanceAI.exe"
& $PkgExe --self-test
if ($LASTEXITCODE -ne 0) {
    throw "Self-test pacchetto fallito (exit=$LASTEXITCODE). Package NON valido."
}

# 6. ZIP
$Zip = Join-Path $ProjectRoot "release\MaintenanceAI-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force -ErrorAction SilentlyContinue }
Compress-Archive -Path (Join-Path $PackageRoot "*") -DestinationPath $Zip

Write-Host "[package] OK. Pacchetto: $PackageRoot" -ForegroundColor Green
Write-Host "[package] ZIP: $Zip" -ForegroundColor Green
