# ============================================================
# ERP System - Build Portable Package (RUN ON SOURCE SERVER)
# Creates D:\erp_portable\ with:
#   runtime\python313\   - full Python 3.13.13 + all deps (copied)
#   app\                 - project code (exclude junk)
#   settings\            - env-specific config (.env / jwt / nginx / redis)
#   deploy\              - install_on_target.ps1
#   manifest.txt
#
# Usage (PowerShell):
#   powershell -ExecutionPolicy Bypass -File scripts\migrate\build_portable.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\migrate\build_portable.ps1 -PyDir "C:\...\Python313" -OutDir "D:\erp_portable"
# ============================================================
param(
    [string]$ProjectDir = "D:\erp_system",
    [string]$PyDir = "",
    [string]$OutDir = "D:\erp_portable",
    [string]$TargetIP = "192.168.1.97",
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn([string]$m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Fail([string]$m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

# ---- auto-locate Python ----
if (-not $PyDir) {
    $cands = @(
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python313"),
        (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312"),
        "C:\Python313", "C:\Python312"
    )
    foreach ($c in $cands) {
        if (Test-Path (Join-Path $c "python.exe")) { $PyDir = $c; break }
    }
    if (-not $PyDir) {
        $pyCmd = Get-Command python -ErrorAction SilentlyContinue
        if ($pyCmd) { $PyDir = Split-Path $pyCmd.Source -Parent }
    }
}
$pyExe = Join-Path $PyDir "python.exe"
if (-not (Test-Path $pyExe)) { Write-Fail "python.exe not found in $PyDir"; exit 1 }
$ver = & $pyExe -c "import sys; print(sys.version.split()[0])"
Write-Ok "Python: $PyDir ($ver)"

# ---- preflight project ----
if (-not (Test-Path (Join-Path $ProjectDir ".env"))) {
    Write-Fail ".env not found in $ProjectDir"; exit 1
}

# ============================================================
Write-Step "ERP Portable Build"
Write-Host "  ProjectDir : $ProjectDir"
Write-Host "  PyDir      : $PyDir"
Write-Host "  OutDir     : $OutDir"
Write-Host "  TargetIP   : $TargetIP"

if (Test-Path $OutDir) { Remove-Item $OutDir -Recurse -Force }
foreach ($sub in @("runtime", "app", "settings", "deploy")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $OutDir $sub) | Out-Null
}

# ---- 1. copy Python runtime ----
Write-Step "Step 1/4 - Copy Python runtime (may take a few minutes)"
$dstPy = Join-Path $OutDir "runtime\python313"
# robocopy full python dir (exclude __pycache__ + .pyc to save space)
& robocopy $PyDir $dstPy /E `
    /XD __pycache__ (Join-Path $PyDir "Lib\__pycache__") `
    /XF "*.pyc" "*.pyo" `
    /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Fail "robocopy python failed (exit=$rc)"; exit 1 }
Write-Ok "Runtime copied (robocopy exit=$rc)"

# self-check: copied python must import a core dep
$checkExe = Join-Path $dstPy "python.exe"
$smoke = & $checkExe -c "import fastapi, uvicorn, sqlalchemy, asyncpg; print('imports-ok')" 2>&1
if ($smoke -match "imports-ok") { Write-Ok "Runtime self-check passed: $smoke" }
else { Write-Warn "Runtime self-check failed: $smoke" }

# ---- 2. copy app code ----
Write-Step "Step 2/4 - Copy app code (exclude junk)"
$appDst = Join-Path $OutDir "app"
$excludeNames = @("node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
$excludePaths = @(
    (Join-Path $ProjectDir ".git"),
    (Join-Path $ProjectDir "logs"),
    (Join-Path $ProjectDir "temp"),
    (Join-Path $ProjectDir "build"),
    (Join-Path $ProjectDir "evidence"),
    (Join-Path $ProjectDir "backups"),
    (Join-Path $ProjectDir "dist")
)
$roboArgs = @($ProjectDir, $appDst, "/E", "/XD") + $excludeNames + $excludePaths +
    @("/XF", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.pid") +
    @("/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")
& robocopy @roboArgs | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Fail "robocopy app failed (exit=$rc)"; exit 1 }
Write-Ok "App copied (robocopy exit=$rc)"

# ---- 3. copy settings ----
Write-Step "Step 3/4 - Copy settings"
$setDst = Join-Path $OutDir "settings"

# 3a. .env
Copy-Item (Join-Path $ProjectDir ".env") (Join-Path $setDst ".env") -Force
Write-Ok ".env copied"

# 3b. jwt keys
if (Test-Path (Join-Path $ProjectDir "config\jwt")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $setDst "jwt") | Out-Null
    Copy-Item (Join-Path $ProjectDir "config\jwt\*") (Join-Path $setDst "jwt\") -Force
    Write-Ok "jwt keys copied"
} else {
    Write-Warn "config\jwt not found - JWT keys missing from package!"
}

# 3c. nginx / redis / security headers / pgbouncer
foreach ($f in @("nginx-windows.conf", "redis.production.conf", "redis-broker.conf", "security-headers.conf")) {
    $src = Join-Path $ProjectDir "config\$f"
    if (Test-Path $src) { Copy-Item $src (Join-Path $setDst $f) -Force }
}
if (Test-Path (Join-Path $ProjectDir "config\pgbouncer")) {
    New-Item -ItemType Directory -Force -Path (Join-Path $setDst "pgbouncer") | Out-Null
    Copy-Item (Join-Path $ProjectDir "config\pgbouncer\*") (Join-Path $setDst "pgbouncer\") -Force
}
Write-Ok "nginx/redis/headers configs copied"

# ---- 4. manifest + deploy script ----
Write-Step "Step 4/4 - Manifest + deploy script"

# copy install_on_target.ps1 next to build script into deploy\
$installSrc = Join-Path $PSScriptRoot "install_on_target.ps1"
if (-not (Test-Path $installSrc)) { $installSrc = Join-Path $ProjectDir "scripts\migrate\install_on_target.ps1" }
if (Test-Path $installSrc) {
    Copy-Item $installSrc (Join-Path $OutDir "deploy\install_on_target.ps1") -Force
    Write-Ok "install_on_target.ps1 copied"
} else {
    Write-Warn "install_on_target.ps1 not found - copy it manually to deploy/"
}

$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$pySizeMB = [math]::Round(((Get-ChildItem $dstPy -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 2)
$appCount = (Get-ChildItem $appDst -Recurse -File).Count
$appSizeMB = [math]::Round(((Get-ChildItem $appDst -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 2)

$manifest = @"
ERP Portable Package
====================
built_at     : $stamp
python       : $ver ($PyDir)
runtime_mb   : $pySizeMB
app_files    : $appCount
app_mb       : $appSizeMB
target_ip    : $TargetIP
install_hint : deploy\install_on_target.ps1 -PackageDir <this dir> -PgSuperPassword <postgres> -NewServerIP $TargetIP
"@
$manifest | Set-Content -Path (Join-Path $OutDir "manifest.txt") -Encoding UTF8
Write-Ok "Manifest written"
Write-Host $manifest

# ---- optional zip ----
if (-not $SkipZip) {
    $zip = "$OutDir.zip"
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Write-Ok "Zipping (large package, may take minutes)..."
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    $zipRc = 0
    if ($tar) {
        Push-Location (Split-Path $OutDir -Parent)
        & tar.exe -a -c -f $zip (Split-Path $OutDir -Leaf)
        $zipRc = $LASTEXITCODE
        Pop-Location
    } else {
        Write-Warn "tar.exe not found - falling back to Compress-Archive (slower)."
        try {
            Compress-Archive -Path $OutDir -DestinationPath $zip -CompressionLevel Optimal -Force
        } catch {
            $zipRc = 1
            Write-Warn "Compress-Archive failed: $($_.Exception.Message)"
        }
    }
    if ($zipRc -eq 0 -and (Test-Path $zip)) {
        $zipMB = [math]::Round((Get-Item $zip).Length / 1MB, 2)
        Write-Ok "Zip created: $zip ($zipMB MB)"
    } else {
        Write-Warn "Zip creation failed. Copy folder $OutDir manually."
    }
}

Write-Host ""
Write-Host "=== BUILD COMPLETE ===" -ForegroundColor Green
Write-Host "  Package: $OutDir"
Write-Host "  Transfer this to target server, then run:"
Write-Host "    powershell -ExecutionPolicy Bypass -File <pkg>\deploy\install_on_target.ps1 -PackageDir <pkg> -PgSuperPassword <postgres-pwd> -NewServerIP $TargetIP"
