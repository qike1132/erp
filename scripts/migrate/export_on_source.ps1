# ============================================================
# ERP System - Migration Export Script (RUN ON SOURCE SERVER)
# Exports PostgreSQL database + packages project files.
# Output: D:\erp_migration_package\erp_migration_<timestamp>\
#
# Usage (PowerShell, admin recommended):
#   powershell -ExecutionPolicy Bypass -File scripts\migrate\export_on_source.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\migrate\export_on_source.ps1 -DbPassword "xxx" -IncludeBackups
# ============================================================
param(
    [string]$ProjectDir = "D:\erp_system",
    [string]$OutputDir  = "D:\erp_migration_package",
    [string]$DbPassword = "",
    [switch]$IncludeBackups,
    [switch]$SkipZip
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn([string]$m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Fail([string]$m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

# ---- helper: parse .env into hashtable ----
function Read-EnvFile([string]$path) {
    $map = @{}
    if (-not (Test-Path $path)) { return $map }
    Get-Content $path -Encoding UTF8 | ForEach-Object {
        $line = $_.Trim()
        if ($line -match '^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
            $map[$Matches[1]] = $Matches[2].Trim().Trim('"')
        }
    }
    return $map
}

# ---- helper: locate pg_dump.exe ----
function Find-PgDump {
    $cmd = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\14\bin\pg_dump.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

# ============================================================
Write-Step "ERP Migration - Export (source server)"
Write-Host "  ProjectDir : $ProjectDir"
Write-Host "  OutputDir  : $OutputDir"

if (-not (Test-Path $ProjectDir)) { Write-Fail "Project dir not found: $ProjectDir"; exit 1 }
if (-not (Test-Path (Join-Path $ProjectDir ".env"))) {
    Write-Fail ".env not found in $ProjectDir"; exit 1
}

# ---- 1. read env ----
$envMap = Read-EnvFile (Join-Path $ProjectDir ".env")
$dbHost = if ($envMap["DB_HOST"]) { $envMap["DB_HOST"] } else { "localhost" }
$dbPort = if ($envMap["DB_PORT"]) { $envMap["DB_PORT"] } else { "5432" }
$dbUser = if ($envMap["DB_USER"]) { $envMap["DB_USER"] } else { "erp_app" }
$dbName = if ($envMap["DB_NAME"]) { $envMap["DB_NAME"] } else { "erp_system" }
if (-not $DbPassword) { $DbPassword = $envMap["DB_PASSWORD"] }
if (-not $DbPassword) { Write-Fail "DB_PASSWORD not found in .env and -DbPassword not given"; exit 1 }

Write-Ok "DB: $dbUser@$dbHost`:$dbPort/$dbName"

# ---- 2. locate pg_dump ----
$pgDump = Find-PgDump
if (-not $pgDump) {
    Write-Fail "pg_dump not found. Install PostgreSQL 16 or add its bin to PATH."
    Write-Host "  You may pass the full path by editing Find-PgDump."
    exit 1
}
Write-Ok "pg_dump: $pgDump"

# ---- 3. create package dir ----
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$pkgDir = Join-Path $OutputDir "erp_migration_$stamp"
$projectCopy = Join-Path $pkgDir "project"
New-Item -ItemType Directory -Force -Path $pkgDir, $projectCopy | Out-Null
Write-Ok "Package dir: $pkgDir"

# ---- 4. dump database ----
Write-Step "Step 1/3 - Dump PostgreSQL database"
$dumpFile = Join-Path $pkgDir "erp_system.dump"
$env:PGPASSWORD = $DbPassword
try {
    Write-Host "  Dumping (may take minutes)..."
    $dumpOut = & $pgDump -h $dbHost -p $dbPort -U $dbUser `
        --no-owner --no-privileges -d $dbName -Fc -f $dumpFile 2>&1
    if ($LASTEXITCODE -ne 0) {
        $dumpOut | Select-Object -Last 30 | ForEach-Object { Write-Host "  $_" }
        Write-Fail "pg_dump failed (exit=$LASTEXITCODE)"
        exit 1
    }
} finally {
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
}
$dumpSize = [math]::Round((Get-Item $dumpFile).Length / 1MB, 2)
Write-Ok "Dump created: $dumpFile ($dumpSize MB)"

# ---- 5. copy project files ----
Write-Step "Step 2/3 - Copy project files (exclude junk dirs)"
# robocopy /XD: bare names exclude same-named dirs anywhere; full paths exclude only that dir.
# Use bare names for universal junk, full paths for project-specific dirs so that e.g.
# frontend-vite\dist is preserved while root \dist is skipped.
$excludeNames = @(".git", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")
$excludePaths = @(
    (Join-Path $ProjectDir "logs"),
    (Join-Path $ProjectDir "temp"),
    (Join-Path $ProjectDir "build"),
    (Join-Path $ProjectDir "evidence"),
    (Join-Path $ProjectDir "dist")          # root dist only (exe packaging output)
)
if (-not $IncludeBackups) { $excludePaths += (Join-Path $ProjectDir "backups") }

$robocopyArgs = @($ProjectDir, $projectCopy, "/E", "/XD")
$robocopyArgs += $excludeNames
$robocopyArgs += $excludePaths
$robocopyArgs += @("/XF", "*.pyc", "*.pyo", "*.log", "*.tmp", "*.pid")
$robocopyArgs += @("/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:1", "/W:1")

& robocopy @robocopyArgs
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Fail "robocopy failed (exit=$rc)"; exit 1 }
Write-Ok "Project copied (robocopy exit=$rc)"

# ---- 6. manifest ----
Write-Step "Step 3/3 - Generate manifest"
$hash = (Get-FileHash $dumpFile -Algorithm SHA256).Hash
$fileCount = (Get-ChildItem $projectCopy -Recurse -File).Count
$totalMB = [math]::Round(((Get-ChildItem $projectCopy -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 2)
$manifest = @"
ERP Migration Package
=====================
exported_at  : $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
source_host  : $env:COMPUTERNAME
db_host      : $dbHost
db_port      : $dbPort
db_user      : $dbUser
db_name      : $dbName
dump_file    : erp_system.dump
dump_sha256  : $hash
dump_size_mb : $dumpSize
file_count   : $fileCount
project_mb   : $totalMB
"@
$manifest | Set-Content -Path (Join-Path $pkgDir "manifest.txt") -Encoding UTF8
Write-Ok "Manifest written"
Write-Host $manifest

# ---- 7. optional zip ----
if (-not $SkipZip) {
    Write-Step "Optional - Create zip archive"
    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($tar) {
        $zipPath = Join-Path $OutputDir "erp_migration_$stamp.zip"
        Push-Location $OutputDir
        & tar.exe -a -c -f $zipPath "erp_migration_$stamp"
        $zipRc = $LASTEXITCODE
        Pop-Location
        if ($zipRc -eq 0) {
            $zipSize = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
            Write-Ok "Zip created: $zipPath ($zipSize MB)"
        } else {
            Write-Warn "tar zip failed (exit=$zipRc). Copy the folder $pkgDir manually."
        }
    } else {
        Write-Warn "tar.exe not found. Copy the folder $pkgDir manually."
    }
}

Write-Host ""
Write-Host "=== EXPORT COMPLETE ===" -ForegroundColor Green
Write-Host "  Package: $pkgDir"
Write-Host "  Transfer this folder/zip to the target server, then run setup_on_target.ps1 there."
