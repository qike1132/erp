# ============================================================
# ERP System - Migration Setup Script (RUN ON TARGET SERVER 192.168.1.97)
# One-shot restore: unpack -> database -> config -> services -> start -> verify.
# Preconditions: Python 3.12 / PostgreSQL 16 / Redis / Nginx / NSSM installed.
#
# Usage (PowerShell, MUST run as Administrator):
#   powershell -ExecutionPolicy Bypass -File setup_on_target.ps1 `
#       -PackageZip "D:\migration_in\erp_migration_20260817_100000" `
#       -PgSuperPassword <uper password from .env>  # secret-scan:allow 参数用法示例占位符，非真凭据
#
# Optional switches to re-run only a failing stage:
#   -SkipDbRestore  -SkipRedis  -SkipNginx  -SkipNssm  -SkipStart  -SkipVerify
# ============================================================
param(
    [string]$PackageZip = "",
    [string]$TargetDir = "D:\erp_system",
    [string]$NewServerIP = "192.168.1.97",
    [string]$PgSuperPassword = "",          # postgres superuser password (required unless -SkipDbRestore)
    [string]$PgBinDir = "",                  # e.g. C:\Program Files\PostgreSQL\16\bin
    [string]$DbPassword = "",                # app DB password; defaults to .env DB_PASSWORD
    [string]$RedisPassword = "",             # defaults to .env REDIS_PASSWORD
    [string]$RedisBinDir = "",               # e.g. C:\Redis
    [string]$NginxDir = "C:\nginx",
    [string]$NssmExe = "",                   # e.g. C:\nssm\nssm.exe
    [string]$PythonExe = "",                 # e.g. C:\Python312\python.exe
    [switch]$InstallDeps,                    # auto pip install requirements/base.txt if imports fail
    [switch]$SkipDbRestore,
    [switch]$SkipRedis,
    [switch]$SkipNginx,
    [switch]$SkipNssm,
    [switch]$SkipStart,
    [switch]$SkipVerify
)

$ErrorActionPreference = "Stop"

function Write-Step([string]$m) { Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-Ok([string]$m)   { Write-Host "  [OK] $m" -ForegroundColor Green }
function Write-Warn([string]$m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Write-Fail([string]$m) { Write-Host "  [FAIL] $m" -ForegroundColor Red }

# ---- helpers ----
function Test-Admin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return (New-Object Security.Principal.WindowsPrincipal($id)).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

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

function Find-PgDump {
    $cmd = Get-Command pg_dump -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $candidates = @(
        "C:\Program Files\PostgreSQL\17\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\16\bin\pg_dump.exe",
        "C:\Program Files\PostgreSQL\15\bin\pg_dump.exe"
    )
    foreach ($c in $candidates) { if (Test-Path $c) { return $c } }
    return $null
}

# ============================================================
# [0] Preflight
# ============================================================
Write-Step "ERP Migration - Setup (target server)"
if (-not (Test-Admin)) { Write-Fail "Please run as Administrator."; exit 1 }
if ($NewServerIP -notmatch '^\d{1,3}(\.\d{1,3}){3}$') {
    Write-Fail "Invalid -NewServerIP: $NewServerIP"; exit 1
}

# ---- locate package ----
$projectAlreadyInPlace = (Test-Path (Join-Path $TargetDir ".env")) -and (Test-Path (Join-Path $TargetDir "fastapi_app"))
if ($projectAlreadyInPlace) {
    Write-Ok "Project already present at $TargetDir (.env + fastapi_app found). Skipping unpack."
} elseif (-not $PackageZip -or -not (Test-Path $PackageZip)) {
    Write-Fail "Package not found: '$PackageZip'. Pass -PackageZip pointing to the folder/zip from export_on_source.ps1, or ensure $TargetDir already has the project."
    exit 1
} else {
    Write-Ok "Package: $PackageZip"
}

# ============================================================
# [1] Preflight checks (binaries)
# ============================================================
Write-Step "Step 1/8 - Preflight environment"
$failFlag = $false

if (-not $PythonExe) {
    $pyCmd = Get-Command python -ErrorAction SilentlyContinue
    if ($pyCmd) { $PythonExe = $pyCmd.Source }
}
if ($PythonExe -and (Test-Path $PythonExe)) { Write-Ok "Python: $PythonExe" }
else { Write-Fail "Python not found. Install Python 3.12 or pass -PythonExe."; $failFlag = $true }

if (-not $PgBinDir) {
    $pgDumpFound = Find-PgDump
    if ($pgDumpFound) { $PgBinDir = Split-Path $pgDumpFound -Parent }
}
$psql = if ($PgBinDir) { Join-Path $PgBinDir "psql.exe" } else { $null }
$pgRestore = if ($PgBinDir) { Join-Path $PgBinDir "pg_restore.exe" } else { $null }
if ($psql -and (Test-Path $psql) -and $pgRestore -and (Test-Path $pgRestore)) {
    Write-Ok "PostgreSQL: $PgBinDir"
} else {
    Write-Fail "PostgreSQL tools not found. Install PostgreSQL 16 or pass -PgBinDir."; $failFlag = $true
}

if (-not $RedisBinDir) {
    foreach ($c in @("C:\Redis", "C:\Program Files\Redis", "C:\Program Files\Redis\Redis")) {
        if (Test-Path (Join-Path $c "redis-server.exe")) { $RedisBinDir = $c; break }
    }
}
if ($RedisBinDir -and (Test-Path (Join-Path $RedisBinDir "redis-server.exe"))) {
    Write-Ok "Redis: $RedisBinDir"
} else {
    Write-Warn "Redis not found. Install tporadowski/redis to C:\Redis or pass -RedisBinDir."
}

if (-not $NssmExe) {
    foreach ($c in @("C:\nssm\nssm.exe", "C:\Program Files\nssm\nssm.exe", "C:\Program Files (x86)\nssm\nssm.exe")) {
        if (Test-Path $c) { $NssmExe = $c; break }
    }
}
if ($NssmExe -and (Test-Path $NssmExe)) { Write-Ok "NSSM: $NssmExe" }
else { Write-Fail "NSSM not found. Download https://nssm.cc to C:\nssm\nssm.exe or pass -NssmExe."; $failFlag = $true }

if (-not $SkipNginx) {
    if (Test-Path (Join-Path $NginxDir "nginx.exe")) { Write-Ok "Nginx: $NginxDir" }
    else { Write-Warn "Nginx not found at $NginxDir. prod_runner will fall back to vite preview; for production install nginx to C:\nginx." }
}

if ($failFlag) { Write-Fail "Missing prerequisites. Fix above then rerun."; exit 1 }

# ============================================================
# [2] Stop old services (if any)
# ============================================================
Write-Step "Step 2/8 - Stop old ERP services"
if (-not $SkipStart) {
    foreach ($svc in @("erp-prod", "erp-arq")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne "Stopped") {
            if ($NssmExe -and (Test-Path $NssmExe)) { & $NssmExe stop $svc | Out-Null }
            else { Stop-Service $svc -Force -ErrorAction SilentlyContinue }
            Write-Ok "Stopped $svc"
        }
    }
    # stop leftover python/uvicorn on port 5002
    $portOwners = Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue
    foreach ($conn in $portOwners) {
        Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    }
}

# ============================================================
# [3] Unpack / copy project to TargetDir
# ============================================================
Write-Step "Step 3/8 - Unpack project to $TargetDir"
$srcRoot = ""
$dumpFile = $null

if ($projectAlreadyInPlace) {
    # project already copied by user; nothing to unpack, but still look for a dump next to it
    $srcRoot = $TargetDir
    $dumpFile = Get-ChildItem $TargetDir -Recurse -Filter "erp_system.dump" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $dumpFile) {
        $dumpFile = Get-ChildItem $TargetDir -Recurse -Filter "*.dump" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($dumpFile) { Write-Ok "DB dump: $($dumpFile.FullName)" }
    elseif (-not $SkipDbRestore) { Write-Warn "No .dump found in $TargetDir. Will skip database restore." }
} else {
    $tmpExtract = Join-Path $env:TEMP "erp_migration_extract"
    if (Test-Path $tmpExtract) { Remove-Item $tmpExtract -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Force -Path $tmpExtract | Out-Null

    $pkgIsDir = (Get-Item $PackageZip).PSIsContainer
    if ($pkgIsDir) {
        $srcRoot = $PackageZip
    } else {
        # zip file -> extract
        Push-Location $tmpExtract
        try {
            & tar.exe -xf $PackageZip 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { throw "tar extract failed" }
        } catch {
            Write-Warn "tar extract failed, trying Expand-Archive..."
            Expand-Archive -Path $PackageZip -DestinationPath $tmpExtract -Force
        }
        Pop-Location
        $srcRoot = $tmpExtract
    }

    # locate the "project" folder inside package.
    # The zip (created by tar -a) contains a top-level dir "erp_migration_<stamp>/",
    # so search: direct child -> one level down -> recursive.
    $projectSrc = $null
    foreach ($cand in @((Join-Path $srcRoot "project"), (Join-Path $srcRoot "erp_system"))) {
        if (Test-Path $cand) { $projectSrc = Get-Item $cand; break }
    }
    if (-not $projectSrc) {
        foreach ($sub in (Get-ChildItem $srcRoot -Directory -ErrorAction SilentlyContinue)) {
            $cand = Join-Path $sub.FullName "project"
            if (Test-Path $cand) { $projectSrc = Get-Item $cand; break }
            $cand2 = Join-Path $sub.FullName "erp_system"
            if (Test-Path $cand2) { $projectSrc = Get-Item $cand2; break }
        }
    }
    if (-not $projectSrc) {
        $projectSrc = Get-ChildItem $srcRoot -Recurse -Directory -Filter "project" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if (-not $projectSrc -and (Test-Path (Join-Path $srcRoot "fastapi_app"))) { $projectSrc = Get-Item $srcRoot }
    if (-not $projectSrc) { Write-Fail "Cannot locate 'project' folder inside package."; exit 1 }
    Write-Ok "Project source: $($projectSrc.FullName)"

    New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
    & robocopy $projectSrc.FullName $TargetDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
    $rc = $LASTEXITCODE
    if ($rc -ge 8) { Write-Fail "robocopy copy failed (exit=$rc)"; exit 1 }
    Write-Ok "Project copied to $TargetDir (robocopy exit=$rc)"

    # locate dump file
    $dumpFile = Get-ChildItem $srcRoot -Recurse -Filter "erp_system.dump" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $dumpFile) {
        $dumpFile = Get-ChildItem $srcRoot -Recurse -Filter "*.dump" -ErrorAction SilentlyContinue | Select-Object -First 1
    }
    if ($dumpFile) { Write-Ok "DB dump: $($dumpFile.FullName)" }
    elseif (-not $SkipDbRestore) { Write-Warn "No .dump found in package. Will skip database restore." }
}

# optional: install python dependencies if requested
if ($InstallDeps) {
    Write-Host "  Installing Python deps (requirements/base.txt)..."
    Push-Location $TargetDir
    try {
        & $PythonExe -m pip install -r requirements/base.txt 2>&1 | Select-Object -Last 10 | ForEach-Object { Write-Host "  $_" }
        if ($LASTEXITCODE -ne 0) { Write-Warn "pip install reported non-zero exit code" }
        else { Write-Ok "Python dependencies installed" }
    } finally {
        Pop-Location
    }
}

# ============================================================
# [4] Restore database
# ============================================================
Write-Step "Step 4/8 - Restore PostgreSQL database"
if ($SkipDbRestore) {
    Write-Warn "SkipDbRestore set - database NOT restored."
} else {
    $envFile = Join-Path $TargetDir ".env"
    $envMap = Read-EnvFile $envFile
    $dbHost = if ($envMap["DB_HOST"]) { $envMap["DB_HOST"] } else { "localhost" }
    $dbPort = if ($envMap["DB_PORT"]) { $envMap["DB_PORT"] } else { "5432" }
    $dbUser = if ($envMap["DB_USER"]) { $envMap["DB_USER"] } else { "erp_app" }
    $dbName = if ($envMap["DB_NAME"]) { $envMap["DB_NAME"] } else { "erp_system" }
    if (-not $DbPassword) { $DbPassword = $envMap["DB_PASSWORD"] }
    if (-not $DbPassword) { Write-Fail "DB_PASSWORD missing. Pass -DbPassword."; exit 1 }
    if (-not $PgSuperPassword) { Write-Fail "-PgSuperPassword required to create role/database."; exit 1 }
    if (-not $dumpFile) { Write-Fail "No database dump file available."; exit 1 }

    # escape single quotes for SQL
    $escapedAppPw = $DbPassword.Replace("'", "''")

    # 4a. ensure PostgreSQL service running (probe by name prefix: postgresql-x64-*)
    $pgSvc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($pgSvc -and $pgSvc.Status -ne "Running") { Start-Service $pgSvc -ErrorAction SilentlyContinue }
    Start-Sleep -Seconds 2

    # 4b. create role & database as postgres superuser
    $env:PGPASSWORD = $PgSuperPassword
    try {
        $roleExists = (& $psql -h $dbHost -p $dbPort -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$dbUser'" 2>$null)
        $roleExists = (($roleExists | Out-String).Trim())
        if ($roleExists -ne "1") {
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE ROLE $dbUser LOGIN PASSWORD '$escapedAppPw'" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE ROLE failed (exit=$LASTEXITCODE)"; exit 1 }
            Write-Ok "Role $dbUser created"
        } else {
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "ALTER ROLE $dbUser LOGIN PASSWORD '$escapedAppPw'" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Fail "ALTER ROLE failed (exit=$LASTEXITCODE)"; exit 1 }
            Write-Ok "Role $dbUser exists, password synced"
        }
        $dbExists = (& $psql -h $dbHost -p $dbPort -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName'" 2>$null)
        $dbExists = (($dbExists | Out-String).Trim())
        if ($dbExists -ne "1") {
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE DATABASE $dbName OWNER $dbUser" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE DATABASE failed (exit=$LASTEXITCODE)"; exit 1 }
            Write-Ok "Database $dbName created"
        } else {
            Write-Warn "Database $dbName already exists - will drop & recreate to restore cleanly."
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$dbName' AND pid <> pg_backend_pid()" 2>&1 | Out-Null
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "DROP DATABASE $dbName" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Fail "DROP DATABASE failed (exit=$LASTEXITCODE)"; exit 1 }
            & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE DATABASE $dbName OWNER $dbUser" 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE DATABASE (recreate) failed (exit=$LASTEXITCODE)"; exit 1 }
            Write-Ok "Database $dbName recreated"
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }

    # 4c. restore dump with erp_app
    $env:PGPASSWORD = $DbPassword
    try {
        Write-Host "  Restoring dump (pg_restore, may take minutes)..."
        $restoreOut = & $pgRestore -h $dbHost -p $dbPort -U $dbUser -d $dbName --no-owner --no-privileges -j 4 $dumpFile.FullName 2>&1
        if ($LASTEXITCODE -ne 0) {
            $restoreOut | Select-Object -Last 30 | ForEach-Object { Write-Host "  $_" }
            Write-Fail "pg_restore exited with code $LASTEXITCODE (check errors above)"
        } else {
            Write-Ok "Database restored from $($dumpFile.Name)"
        }
    } finally {
        Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    }
}

# ============================================================
# [5] Update .env for new server
# ============================================================
Write-Step "Step 5/8 - Update .env for new server"
$envFile = Join-Path $TargetDir ".env"
if (-not (Test-Path $envFile)) { Write-Fail ".env not found in $TargetDir"; exit 1 }

# capture original Redis password so URL-embedded passwords can be rewritten together
$origEnvMap = Read-EnvFile $envFile
$oldRedisPw = $origEnvMap["REDIS_PASSWORD"]

$envLines = Get-Content $envFile -Encoding UTF8
$outLines = @()
$changed = $false

foreach ($line in $envLines) {
    $newLine = $line
    if ($line -match '^ALLOWED_HOSTS=') {
        # .env stores a JSON array like ["192.168.0.95","localhost","127.0.0.1"]
        $raw = ($line -split '=', 2)[1].Trim()
        $hosts = @()
        try { $hosts = @($raw | ConvertFrom-Json) } catch { $hosts = @() }
        if ($hosts.Count -eq 0) {
            $hosts = ($raw -replace '[\[\]"]', '' -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        if ($hosts -notcontains $NewServerIP) { $hosts += $NewServerIP }
        $json = $hosts | ConvertTo-Json -Compress
        $newLine = "ALLOWED_HOSTS=$json"
        $changed = $true
    }
    elseif ($line -match '^CORS_ORIGINS=') {
        $origins = ($line -split '=', 2)[1]
        $newOrigin = "http://${NewServerIP}:3000"
        if ($origins -notmatch [regex]::Escape($newOrigin)) {
            $newLine = "CORS_ORIGINS=$origins,$newOrigin"
            $changed = $true
        }
    }
    elseif ($line -match '^\s*ASYNC_DATABASE_REPLICA_URL=') {
        $newLine = "# ASYNC_DATABASE_REPLICA_URL= (read replica not migrated; app falls back to primary)"
        $changed = $true
    }
    elseif ($DbPassword -and $line -match '^DB_PASSWORD=') {
        $newLine = "DB_PASSWORD=$DbPassword"
        $changed = $true
    }
    elseif ($RedisPassword -and $line -match '^REDIS_PASSWORD=') {
        $newLine = "REDIS_PASSWORD=$RedisPassword"
        $changed = $true
    }
    # sync any URL that embeds the old redis password (REDIS_URL / _CACHE_ / _BROKER_ / _RESULT_ / LIMITER)
    if ($RedisPassword -and $oldRedisPw -and $oldRedisPw -ne $RedisPassword) {
        if ($newLine -match "redis://:[^@]+@") {
            $newLine = $newLine -replace [regex]::Escape($oldRedisPw), $RedisPassword
            if ($newLine -ne $line) { $changed = $true }
        }
    }
    $outLines += $newLine
}

if ($changed) {
    # preserve UTF-8 without BOM (dotenv handles both, keep it clean)
    [System.IO.File]::WriteAllLines($envFile, $outLines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok ".env updated (ALLOWED_HOSTS/CORS/DB_PASSWORD/REDIS_PASSWORD/REPLICA)"
} else {
    Write-Warn ".env unchanged (nothing to patch)"
}

# ============================================================
# [6] Configure Redis
# ============================================================
Write-Step "Step 6/8 - Configure Redis instances"
if ($SkipRedis) {
    Write-Warn "SkipRedis set - Redis NOT configured."
} elseif (-not $RedisBinDir) {
    Write-Warn "Redis not found - skip. Configure manually: two instances on 6379 (cache) & 6380 (arq)."
} else {
    $envMap = Read-EnvFile $envFile
    if (-not $RedisPassword) { $RedisPassword = $envMap["REDIS_PASSWORD"] }
    if (-not $RedisPassword) { Write-Warn "REDIS_PASSWORD empty; writing conf without requirepass." }

    $redisServer = Join-Path $RedisBinDir "redis-server.exe"
    $redisDataDir = Join-Path $RedisBinDir "data"
    New-Item -ItemType Directory -Force -Path $redisDataDir | Out-Null

    function New-DeployRedisConf([string]$srcConf, [string]$dstConf, [string]$password, [string]$logName) {
        $lines = Get-Content $srcConf -Encoding UTF8
        # strip any existing requirepass, then append ours
        $filtered = $lines | Where-Object { $_ -notmatch '^\s*requirepass' }
        # force absolute dir + logfile so the service writes RDB/AOF/logs under Redis\data
        $filtered = $filtered | ForEach-Object {
            if ($_ -match '^\s*dir\s') { "dir $redisDataDir" }
            elseif ($_ -match '^\s*logfile\s') { "logfile `"$redisDataDir\$logName`"" }
            else { $_ }
        }
        if ($password) { $filtered += "requirepass $password" }
        [System.IO.File]::WriteAllLines($dstConf, $filtered, (New-Object System.Text.UTF8Encoding($false)))
    }

    # cache instance -> 6379, service "Redis"
    $srcCache = Join-Path $TargetDir "config\redis.production.conf"
    $dstCache = Join-Path $RedisBinDir "erp-redis.conf"
    if (Test-Path $srcCache) {
        New-DeployRedisConf $srcCache $dstCache $RedisPassword "redis.log"
        Write-Ok "Cache conf: $dstCache"
        $redisSvc = Get-Service -Name "Redis" -ErrorAction SilentlyContinue
        if (-not $redisSvc) {
            & $redisServer --service-install $dstCache --service-name Redis 2>&1 | ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -eq 0) { Write-Ok "Redis service installed" }
            else { Write-Warn "redis-server --service-install failed. Install service manually or via NSSM." }
        } else {
            Write-Warn "Service 'Redis' already exists - restarting to load new conf."
            Restart-Service -Name "Redis" -Force -ErrorAction SilentlyContinue
        }
    }

    # arq broker instance -> 6380, service "RedisBroker"
    $srcBroker = Join-Path $TargetDir "config\redis-broker.conf"
    $dstBroker = Join-Path $RedisBinDir "erp-redis-broker.conf"
    if (Test-Path $srcBroker) {
        New-DeployRedisConf $srcBroker $dstBroker $RedisPassword "redis-broker.log"
        Write-Ok "Broker conf: $dstBroker"
        $brokerSvc = Get-Service -Name "RedisBroker" -ErrorAction SilentlyContinue
        if (-not $brokerSvc) {
            & $redisServer --service-install $dstBroker --service-name RedisBroker 2>&1 | ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -eq 0) { Write-Ok "RedisBroker service installed" }
            else { Write-Warn "redis-server --service-install failed for broker. Install manually or via NSSM." }
        } else {
            Write-Warn "Service 'RedisBroker' already exists - restarting to load new conf."
            Restart-Service -Name "RedisBroker" -Force -ErrorAction SilentlyContinue
        }
    }
}

# ============================================================
# [7] Install Windows services via NSSM
# ============================================================
Write-Step "Step 7/8 - Install Windows services (NSSM)"
if ($SkipNssm) {
    Write-Warn "SkipNssm set - services NOT registered."
} else {
    if (-not $NssmExe) { Write-Fail "NSSM not found."; exit 1 }
    if (-not $PythonExe) { Write-Fail "Python not found."; exit 1 }

    # NSSM AppEnvironmentExtra 是 REG_MULTI_SZ：每个 "KEY=value" 必须是**独立参数**（同 install_on_target.ps1）。
    $envExtra = @(
        "APP_ENV=production"
        "FASTAPI_DEBUG=false"
        "PYTHONPATH=$TargetDir"
        "PYTHONUTF8=1"
        "PYTHONUNBUFFERED=1"
        "UVICORN_WORKERS=4"
        "PYTHONIOENCODING=utf-8"
    )

    function Install-NssmService {
        param([string]$Name, [string]$Params)
        $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if ($existing) {
            Write-Warn "Service $Name already exists - removing and reinstalling."
            & $NssmExe stop $Name | Out-Null
            & $NssmExe remove $Name confirm | Out-Null
        }
        $logDir = Join-Path $TargetDir "logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null

        & $NssmExe install $Name $PythonExe | Out-Null
        & $NssmExe set $Name AppParameters $Params | Out-Null
        & $NssmExe set $Name AppDirectory $TargetDir | Out-Null
        & $NssmExe set $Name AppStdout (Join-Path $logDir "$Name.log") | Out-Null
        & $NssmExe set $Name AppStderr (Join-Path $logDir "$Name.log") | Out-Null
        & $NssmExe set $Name AppRotateFiles 1 | Out-Null
        & $NssmExe set $Name AppRotateBytes 10485760 | Out-Null
        & $NssmExe set $Name AppExit "Default Restart" | Out-Null
        & $NssmExe set $Name AppRestartDelay 5000 | Out-Null
        & $NssmExe set $Name Start SERVICE_AUTO_START | Out-Null
        & $NssmExe set $Name AppEnvironmentExtra $envExtra | Out-Null
        & $NssmExe set $Name AppNoConsole 1 | Out-Null
        Write-Ok "Service $Name installed (params: $Params)"
    }

    Install-NssmService "erp-prod" "-m fastapi_app.core.prod_runner --no-arq"
    Install-NssmService "erp-arq"  "-m arq fastapi_app.core.arq_app.WorkerSettings"
}

# ============================================================
# [8] Start services & verify
# ============================================================
Write-Step "Step 8/8 - Start services & verify"
if (-not $SkipStart) {
    foreach ($svc in @("Redis", "RedisBroker", "erp-prod", "erp-arq")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s) {
            if ($s.Status -ne "Running") { Start-Service $svc -ErrorAction SilentlyContinue }
            Write-Ok "Service $svc -> $(Get-Service $svc | Select-Object -ExpandProperty Status)"
        }
    }
    if (-not $SkipNginx) {
        # nginx is launched by prod_runner; ensure not double-starting. Nothing to do here.
        Write-Ok "Nginx will be managed by prod_runner (front-end)."
    }
}

if (-not $SkipVerify) {
    Write-Host "`n--- Verification ---" -ForegroundColor Yellow
    Start-Sleep -Seconds 15   # allow backend to boot

    # backend health
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 10
        Write-Ok "Backend /api/health -> $($r.StatusCode)"
    } catch {
        Write-Fail "Backend /api/health unreachable: $($_.Exception.Message)"
    }

    # frontend
    try {
        $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 10
        Write-Ok "Frontend :3000 -> $($r2.StatusCode)"
    } catch {
        Write-Warn "Frontend :3000 not reachable yet (nginx may still be starting): $($_.Exception.Message)"
    }

    # database tables
    if (-not $SkipDbRestore -and $psql) {
        $envMap = Read-EnvFile $envFile
        $dbUser = if ($envMap["DB_USER"]) { $envMap["DB_USER"] } else { "erp_app" }
        $dbName = if ($envMap["DB_NAME"]) { $envMap["DB_NAME"] } else { "erp_system" }
        if (-not $DbPassword) { $DbPassword = $envMap["DB_PASSWORD"] }
        $env:PGPASSWORD = $DbPassword
        try {
            $tableCount = & $psql -h localhost -p 5432 -U $dbUser -d $dbName -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'" 2>$null
            if ($tableCount) { Write-Ok "Database $dbName has $($tableCount.Trim()) public tables" }
            else { Write-Fail "Cannot query database $dbName" }
        } finally {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }

    # redis ping
    if ($RedisBinDir -and (Test-Path (Join-Path $RedisBinDir "redis-cli.exe"))) {
        $redisCli = Join-Path $RedisBinDir "redis-cli.exe"
        if (-not $RedisPassword) { $RedisPassword = (Read-EnvFile $envFile)["REDIS_PASSWORD"] }
        $authArg = if ($RedisPassword) { @("-a", $RedisPassword) } else { @() }
        foreach ($port in @(6379, 6380)) {
            $pong = & $redisCli @authArg -p $port ping 2>$null
            if ($pong -match "PONG") { Write-Ok "Redis :$port PONG" }
            else { Write-Warn "Redis :$port not responding: $pong" }
        }
    }
}

Write-Host ""
Write-Host "=== MIGRATION COMPLETE ===" -ForegroundColor Green
Write-Host "  Access ERP at: http://$NewServerIP`:3000"
Write-Host "  Manual checks: see docs/ERP_MIGRATION_GUIDE.md section 6.2"
