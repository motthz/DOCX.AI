# DOCX.AI: bootstrap runtime + modello
# Passo 1) Ultima release llama.cpp Windows CPU x64
# Passo 2) Modello Qwen3-1.7B-Q8_0.gguf con verifica SHA-256
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$llamaDir = Join-Path $root "runtime\llama"
$modelsDir = Join-Path $root "models"
$dlDir = Join-Path $root "dl_cache"
New-Item -ItemType Directory -Force -Path $llamaDir, $modelsDir, $dlDir | Out-Null

# -----------------------------------------------------------------------------
# STEP 1: trova e scarica ultima release llama.cpp win-cpu-x64
# -----------------------------------------------------------------------------
Write-Host "==> Query GitHub API per release build llama.cpp (tag bXXXX) con asset win-cpu-x64.zip..."
$preferredTag = "b10646"
$foundRelease = $null
$candidateUrls = @(
    "https://api.github.com/repos/ggml-org/llama.cpp/releases/tags/$preferredTag",
    "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=30"
)
foreach ($u in $candidateUrls) {
    try {
        $raw = Invoke-RestMethod -Uri $u -UseBasicParsing
        $list = @()
        if ($raw -is [array]) { $list = $raw } else { $list = @($raw) }
        foreach ($r in $list) {
            $ast = $r.assets | Where-Object { $_.name -like "*win-cpu*x64.zip" } | Select-Object -First 1
            if ($ast) { $foundRelease = $r; $foundAsset = $ast; break }
        }
    } catch { Write-Host "    skip $u : $_" }
    if ($foundRelease) { break }
}
if (-not $foundRelease) { throw "Nessuna release build trovata con asset win-cpu-x64.zip (tentato $preferredTag + ultime 30 release)" }
$tag = $foundRelease.tag_name
$asset = $foundAsset
Write-Host "    Release build scelta: $tag  (asset: $($asset.name))"
$zipPath = Join-Path $dlDir $asset.name
if (-not (Test-Path $zipPath) -or (Get-Item $zipPath).Length -ne $asset.size) {
    Write-Host "==> Download $($asset.name) ($([math]::Round($asset.size/1MB,1)) MB)..."
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing
    $ProgressPreference = "Continue"
}
Write-Host "==> Estrazione runtime in $llamaDir..."
$extractTemp = Join-Path $dlDir ("llama_" + $tag)
if (Test-Path $extractTemp) { Remove-Item -Recurse -Force $extractTemp }
Expand-Archive -Path $zipPath -DestinationPath $extractTemp -Force
$found = Get-ChildItem -Recurse -Filter "llama-server.exe" -Path $extractTemp | Select-Object -First 1
if (-not $found) { throw "llama-server.exe non trovato nell'archivio" }
$srcBinDir = $found.Directory.FullName
Get-ChildItem -Path $llamaDir -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem -Path $srcBinDir | ForEach-Object { Copy-Item -Path $_.FullName -Destination (Join-Path $llamaDir $_.Name) -Recurse }
Write-Host "    OK: $((Get-ChildItem $llamaDir).Count) file in runtime/llama"
$pinOut = Join-Path $root "VERSION.txt"
$ver = Get-Content $pinOut -Raw -Encoding UTF8
if ($ver -match "LLAMA_CPP_BUILD_TAG:.*") {
    $ver = $ver -replace "LLAMA_CPP_BUILD_TAG:.*", ("LLAMA_CPP_BUILD_TAG: " + $tag)
} else {
    $ver += "`r`nLLAMA_CPP_BUILD_TAG: " + $tag
}
Set-Content -Path $pinOut -Value $ver -Encoding UTF8

# -----------------------------------------------------------------------------
# STEP 2: scarica Qwen3-1.7B-Q8_0.gguf e verifica SHA-256
# -----------------------------------------------------------------------------
$EXPECTED_SHA = "061b54daade076b5d3362dac252678d17da8c68f07560be70818cace6590cb1a"
$modelRepo = "Qwen/Qwen3-1.7B-GGUF"
$modelName = "Qwen3-1.7B-Q8_0.gguf"
$modelOut = Join-Path $modelsDir $modelName
$cacheModel = Join-Path $dlDir $modelName
$modelUrl = "https://huggingface.co/$modelRepo/resolve/main/$modelName"
if (-not (Test-Path $modelOut)) {
    if (Test-Path $cacheModel) {
        Write-Host "==> Uso cache locale: $cacheModel"
    } else {
        Write-Host "==> Download modello $modelName da HuggingFace (~1.8 GB, attendere...)"
        $ProgressPreference = "SilentlyContinue"
        Invoke-WebRequest -Uri $modelUrl -OutFile $cacheModel -UseBasicParsing
        $ProgressPreference = "Continue"
        Write-Host "    Download completato."
    }
    Write-Host "==> Verifica SHA-256..."
    $actual = (Get-FileHash -Path $cacheModel -Algorithm SHA256).Hash.ToLowerInvariant()
    Write-Host "    Atteso : $EXPECTED_SHA"
    Write-Host "    Reale  : $actual"
    if ($actual -ne $EXPECTED_SHA) {
        Remove-Item $cacheModel -Force -ErrorAction SilentlyContinue
        throw "SHA-256 modello NON corrisponde! Download corrotto o modello sbagliato."
    }
    Write-Host "    SHA-256 OK."
    Copy-Item -Path $cacheModel -Destination $modelOut -Force
}
$modelPinLine = "QWEN3_1_7B_Q8_0_SHA256: $EXPECTED_SHA"
$ver2 = Get-Content $pinOut -Raw -Encoding UTF8
if ($ver2 -match "QWEN3_1_7B_Q8_0_SHA256:.*") {
    $ver2 = $ver2 -replace "QWEN3_1_7B_Q8_0_SHA256:.*", $modelPinLine
} else {
    $ver2 += "`r`n" + $modelPinLine
}
Set-Content -Path $pinOut -Value $ver2 -Encoding UTF8

# Fallback 0.6B (se lo trova online lo scarica, altrimenti salta)
$fallbackName = "Qwen3-0.6B-Q8_0.gguf"
$fallbackOut = Join-Path $modelsDir $fallbackName
if (-not (Test-Path $fallbackOut)) {
    Write-Host "==> Download fallback $fallbackName (~640 MB)..."
    $fbUrl = "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/$fallbackName"
    $fbCache = Join-Path $dlDir $fallbackName
    if (-not (Test-Path $fbCache)) {
        try {
            $ProgressPreference = "SilentlyContinue"
            Invoke-WebRequest -Uri $fbUrl -OutFile $fbCache -UseBasicParsing
            $ProgressPreference = "Continue"
        } catch {
            Write-Warning "Fallback 0.6B non scaricabile: $_"
        }
    }
    if (Test-Path $fbCache) {
        Copy-Item -Path $fbCache -Destination $fallbackOut -Force
        Write-Host "    Fallback OK."
    }
}

Write-Host ""
Write-Host "=== FINE BOOTSTRAP RUNTIME ==="
Get-ChildItem $llamaDir -Filter *.exe | ForEach-Object { Write-Host "  exe   : $($_.Name)" }
Get-ChildItem $modelsDir -Filter *.gguf | ForEach-Object { Write-Host "  model : $($_.Name)  $([math]::Round($_.Length/1GB,2)) GB" }
