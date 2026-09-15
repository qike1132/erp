# ============================================================
# ERP System - Portable Package Installer (RUN ON TARGET SERVER)
# Installs ERP from a portable package built by build_portable.ps1.
# Layout of package:
#   runtime\python313\   - full Python + deps
#   app\                 - project code
#   settings\            - .env / jwt / nginx / redis configs
#   deploy\install_on_target.ps1
#
# Usage (PowerShell, MUST be Administrator):
#   powershell -ExecutionPolicy Bypass -File install_on_target.ps1 `
#       -PackageDir "D:\migration_in\erp_portable" `
#       -PgSuperPassword "postgres_super_password" `
#       -NewServerIP "192.168.1.97"
#
# Skips: -SkipDbRestore -SkipRedis -SkipNginx -SkipNssm -SkipStart -SkipVerify
# ============================================================
param(
    [string]$PackageDir = "",
    [string]$TargetDir = "D:\erp_system",
    [string]$NewServerIP = "192.168.1.97",
    [string]$PgSuperPassword = "",
    [string]$PgBinDir = "",
    [string]$RedisBinDir = "",
    [string]$NginxDir = "C:\nginx",
    [string]$NssmExe = "",
    [string]$DbDumpPath = "",          # optional path to erp_system.dump
    [switch]$InstallDeps,              # pip install -r requirements/base.txt into runtime python
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
    foreach ($c in @("C:\Program Files\PostgreSQL\17\bin", "C:\Program Files\PostgreSQL\16\bin", "C:\Program Files\PostgreSQL\15\bin")) {
        if (Test-Path (Join-Path $c "pg_dump.exe")) { return (Join-Path $c "pg_dump.exe") }
    }
    return $null
}

# ============================================================
Write-Step "ERP Portable Package Installer"
if (-not (Test-Admin)) { Write-Fail "Run as Administrator."; exit 1 }
if ($NewServerIP -notmatch '^\d{1,3}(\.\d{1,3}){3}$') { Write-Fail "Invalid IP: $NewServerIP"; exit 1 }

# ---- locate package layout ----
if (-not $PackageDir -or -not (Test-Path $PackageDir)) {
    Write-Fail "-PackageDir not found. Pass the portable package dir (containing runtime\ app\ settings\)."
    exit 1
}
$runtimeDir = Join-Path $PackageDir "runtime\python313"
$appDir = Join-Path $PackageDir "app"
$setDir = Join-Path $PackageDir "settings"
$pythonExe = Join-Path $runtimeDir "python.exe"

if (-not (Test-Path $pythonExe)) { Write-Warn "runtime\python313\python.exe missing in package. Will try system python." }
if (-not (Test-Path $appDir))    { Write-Fail "app\ not found in package. Layout invalid."; exit 1 }
Write-Ok "Package layout OK"

# ============================================================
# [1] Preflight
# ============================================================
Write-Step "Step 1/9 - Preflight"
$failFlag = $false

# 1a. python (portable preferred, fallback system)
if (-not (Test-Path $pythonExe)) {
    $sysPy = Get-Command python -ErrorAction SilentlyContinue
    if ($sysPy) { $pythonExe = $sysPy.Source }
}
if ($pythonExe -and (Test-Path $pythonExe)) { Write-Ok "Python: $pythonExe" }
else { Write-Fail "No python.exe (package runtime or system)."; $failFlag = $true }

# 1b. postgres tools
if (-not $PgBinDir) {
    $pgDump = Find-PgDump
    if ($pgDump) { $PgBinDir = Split-Path $pgDump -Parent }
}
$psql = if ($PgBinDir) { Join-Path $PgBinDir "psql.exe" } else { $null }
$pgRestore = if ($PgBinDir) { Join-Path $PgBinDir "pg_restore.exe" } else { $null }
if ($psql -and (Test-Path $psql) -and $pgRestore -and (Test-Path $pgRestore)) { Write-Ok "PostgreSQL: $PgBinDir" }
else { Write-Fail "PostgreSQL tools not found. Install PostgreSQL 16 or pass -PgBinDir."; $failFlag = $true }

# 1c. redis
if (-not $RedisBinDir) {
    foreach ($c in @("C:\Redis", "C:\Program Files\Redis")) {
        if (Test-Path (Join-Path $c "redis-server.exe")) { $RedisBinDir = $c; break }
    }
}
if ($RedisBinDir -and (Test-Path (Join-Path $RedisBinDir "redis-server.exe"))) { Write-Ok "Redis: $RedisBinDir" }
else { Write-Warn "Redis not found - install tporadowski/redis to C:\Redis or pass -RedisBinDir." }

# 1d. nssm
if (-not $NssmExe) {
    foreach ($c in @("C:\nssm\nssm.exe", "C:\Program Files\nssm\nssm.exe", "C:\Program Files (x86)\nssm\nssm.exe")) {
        if (Test-Path $c) { $NssmExe = $c; break }
    }
}
if ($NssmExe -and (Test-Path $NssmExe)) { Write-Ok "NSSM: $NssmExe" }
else { Write-Fail "NSSM not found. Download https://nssm.cc to C:\nssm\nssm.exe or pass -NssmExe."; $failFlag = $true }

# 1e. nginx
if (-not $SkipNginx) {
    if (Test-Path (Join-Path $NginxDir "nginx.exe")) { Write-Ok "Nginx: $NginxDir" }
    else { Write-Warn "Nginx not found at $NginxDir. prod_runner will fall back to vite preview." }
}

if ($failFlag) { Write-Fail "Missing prerequisites. Fix and rerun."; exit 1 }

# ============================================================
# [2] Stop old services
# ============================================================
Write-Step "Step 2/9 - Stop old ERP services"
if (-not $SkipStart) {
    foreach ($svc in @("erp-prod", "erp-arq")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s -and $s.Status -ne "Stopped") {
            if ($NssmExe) { & $NssmExe stop $svc | Out-Null } else { Stop-Service $svc -Force -ErrorAction SilentlyContinue }
            Write-Ok "Stopped $svc"
        }
    }
    Get-NetTCPConnection -LocalPort 5002 -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
}

# ============================================================
# [3] Copy install dir (app + runtime) to TargetDir
# ============================================================
Write-Step "Step 3/9 - Copy install dirs to $TargetDir"
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null

# 3a. app code -> TargetDir
& robocopy $appDir $TargetDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Fail "robocopy app failed (exit=$rc)"; exit 1 }
Write-Ok "app\ -> $TargetDir"

# 3b. runtime -> TargetDir\runtime
$dstRuntime = Join-Path $TargetDir "runtime\python313"
New-Item -ItemType Directory -Force -Path (Split-Path $dstRuntime -Parent) | Out-Null
& robocopy $runtimeDir $dstRuntime /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1
$rc = $LASTEXITCODE
if ($rc -ge 8) { Write-Fail "robocopy runtime failed (exit=$rc)"; exit 1 }
Write-Ok "runtime\ -> $dstRuntime"
$pythonExe = Join-Path $dstRuntime "python.exe"

# 3c. settings -> TargetDir (merge)
if (Test-Path $setDir) {
    & robocopy $setDir $TargetDir /E /NFL /NDL /NJH /NJS /NP /R:1 /W:1 | Out-Null
    Write-Ok "settings\ merged into $TargetDir"
    # re-arrange nginx/redis configs into config\
    New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir "config") | Out-Null
    foreach ($f in @("nginx-windows.conf", "redis.production.conf", "redis-broker.conf", "security-headers.conf")) {
        $src = Join-Path $TargetDir $f
        if (Test-Path $src) { Move-Item $src (Join-Path $TargetDir "config\$f") -Force }
    }
    # jwt folder
    if (Test-Path (Join-Path $TargetDir "jwt")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir "config\jwt") | Out-Null
        Copy-Item (Join-Path $TargetDir "jwt\*") (Join-Path $TargetDir "config\jwt\") -Force
        Remove-Item (Join-Path $TargetDir "jwt") -Recurse -Force
    }
    # pgbouncer folder
    if (Test-Path (Join-Path $TargetDir "pgbouncer")) {
        New-Item -ItemType Directory -Force -Path (Join-Path $TargetDir "config\pgbouncer") | Out-Null
        Copy-Item (Join-Path $TargetDir "pgbouncer\*") (Join-Path $TargetDir "config\pgbouncer\") -Force
        Remove-Item (Join-Path $TargetDir "pgbouncer") -Recurse -Force
    }
    Write-Ok "nginx/redis configs -> config\"
}

# optional: install deps into portable python
if ($InstallDeps) {
    Write-Host "  Installing base deps into portable python..."
    Push-Location $TargetDir
    & $pythonExe -m pip install -r requirements\base.txt 2>&1 | Select-Object -Last 8 | ForEach-Object { Write-Host "  $_" }
    Pop-Location
}

# smoke test portable python
$smoke = & $pythonExe -c "import fastapi, uvicorn, sqlalchemy, asyncpg; print('imports-ok')" 2>&1
if ($smoke -match "imports-ok") { Write-Ok "Runtime self-check passed" }
else { Write-Warn "Runtime self-check failed: $smoke" }

# ============================================================
# [4] Restore database
# ============================================================
Write-Step "Step 4/9 - Restore PostgreSQL database"
$envFile = Join-Path $TargetDir ".env"
if (-not $SkipDbRestore) {
    if (-not $PgSuperPassword) { Write-Fail "-PgSuperPassword required for DB restore (or -SkipDbRestore)."; exit 1 }
    $envMap = Read-EnvFile $envFile
    $dbHost = if ($envMap["DB_HOST"]) { $envMap["DB_HOST"] } else { "localhost" }
    $dbPort = if ($envMap["DB_PORT"]) { $envMap["DB_PORT"] } else { "5432" }
    $dbUser = if ($envMap["DB_USER"]) { $envMap["DB_USER"] } else { "erp_app" }
    $dbName = if ($envMap["DB_NAME"]) { $envMap["DB_NAME"] } else { "erp_system" }
    $dbPassword = $envMap["DB_PASSWORD"]
    if (-not $dbPassword) { Write-Fail "DB_PASSWORD missing in .env."; exit 1 }

    # locate dump
    if (-not $DbDumpPath) {
        $dump = Get-ChildItem $PackageDir -Recurse -Filter "erp_system.dump" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($dump) { $DbDumpPath = $dump.FullName }
        if (-not $DbDumpPath) {
            Write-Warn "No erp_system.dump in package. Skipping DB restore (schema-only deploy)."
            $SkipDbRestore = $true
        }
    }
    if (-not $SkipDbRestore -and $DbDumpPath) {
        # ensure PG service running
        $pgSvc = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($pgSvc -and $pgSvc.Status -ne "Running") { Start-Service $pgSvc -ErrorAction SilentlyContinue }
        Start-Sleep -Seconds 2

        $escapedPw = $dbPassword.Replace("'", "''")
        $env:PGPASSWORD = $PgSuperPassword
        try {
            $roleExists = (& $psql -h $dbHost -p $dbPort -U postgres -d postgres -tAc "SELECT 1 FROM pg_roles WHERE rolname='$dbUser'" 2>$null | Out-String).Trim()
            if ($roleExists -ne "1") {
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE ROLE $dbUser LOGIN PASSWORD '$escapedPw'" 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE ROLE failed"; exit 1 }
                Write-Ok "Role $dbUser created"
            } else {
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "ALTER ROLE $dbUser LOGIN PASSWORD '$escapedPw'" 2>&1 | Out-Null
                Write-Ok "Role $dbUser exists, password synced"
            }
            $dbExists = (& $psql -h $dbHost -p $dbPort -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='$dbName'" 2>$null | Out-String).Trim()
            if ($dbExists -ne "1") {
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE DATABASE $dbName OWNER $dbUser" 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE DATABASE failed"; exit 1 }
                Write-Ok "Database $dbName created"
            } else {
                Write-Warn "Database $dbName exists - dropping & recreating."
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$dbName' AND pid <> pg_backend_pid()" 2>&1 | Out-Null
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "DROP DATABASE $dbName" 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Fail "DROP DATABASE failed"; exit 1 }
                & $psql -h $dbHost -p $dbPort -U postgres -d postgres -c "CREATE DATABASE $dbName OWNER $dbUser" 2>&1 | Out-Null
                if ($LASTEXITCODE -ne 0) { Write-Fail "CREATE DATABASE (recreate) failed"; exit 1 }
                Write-Ok "Database $dbName recreated"
            }
        } finally {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }

        $env:PGPASSWORD = $dbPassword
        try {
            Write-Host "  pg_restore... (may take minutes)"
            & $pgRestore -h $dbHost -p $dbPort -U $dbUser -d $dbName --no-owner --no-privileges -j 4 $DbDumpPath 2>&1 | Select-Object -Last 25 | ForEach-Object { Write-Host "  $_" }
            if ($LASTEXITCODE -ne 0) { Write-Fail "pg_restore exited $LASTEXITCODE (check errors)" }
            else { Write-Ok "Database restored from $DbDumpPath" }
        } finally {
            Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
        }
    }
}

# ============================================================
# [5] Update .env for new server
# ============================================================
Write-Step "Step 5/9 - Update .env for new server"
if (-not (Test-Path $envFile)) { Write-Fail ".env missing after copy."; exit 1 }
$envLines = Get-Content $envFile -Encoding UTF8
$outLines = @()
$changed = $false
foreach ($line in $envLines) {
    $newLine = $line
    if ($line -match '^ALLOWED_HOSTS=') {
        $raw = ($line -split '=', 2)[1].Trim()
        $hosts = @()
        try { $hosts = @($raw | ConvertFrom-Json) } catch { $hosts = @() }
        if ($hosts.Count -eq 0) {
            $hosts = ($raw -replace '[\[\]"]', '' -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })
        }
        if ($hosts -notcontains $NewServerIP) { $hosts += $NewServerIP }
        $newLine = "ALLOWED_HOSTS=$($hosts | ConvertTo-Json -Compress)"
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
    $outLines += $newLine
}
if ($changed) {
    [System.IO.File]::WriteAllLines($envFile, $outLines, (New-Object System.Text.UTF8Encoding($false)))
    Write-Ok ".env updated (ALLOWED_HOSTS/CORS/REPLICA)"
} else {
    Write-Warn ".env unchanged"
}

# ============================================================
# [6] Configure Redis
# ============================================================
Write-Step "Step 6/9 - Configure Redis"
if ($SkipRedis) {
    Write-Warn "SkipRedis set."
} elseif (-not $RedisBinDir) {
    Write-Warn "Redis not found - skip. Configure 6379/6380 manually."
} else {
    $envMap = Read-EnvFile $envFile
    $redisPassword = $envMap["REDIS_PASSWORD"]
    $redisServer = Join-Path $RedisBinDir "redis-server.exe"
    $redisDataDir = Join-Path $RedisBinDir "data"
    New-Item -ItemType Directory -Force -Path $redisDataDir | Out-Null

    function New-DeployRedisConf([string]$srcConf, [string]$dstConf, [string]$password, [string]$logName) {
        $lines = Get-Content $srcConf -Encoding UTF8
        $filtered = $lines | Where-Object { $_ -notmatch '^\s*requirepass' } | ForEach-Object {
            if ($_ -match '^\s*dir\s') { "dir $redisDataDir" }
            elseif ($_ -match '^\s*logfile\s') { "logfile `"$redisDataDir\$logName`"" }
            else { $_ }
        }
        if ($password) { $filtered += "requirepass $password" }
        [System.IO.File]::WriteAllLines($dstConf, $filtered, (New-Object System.Text.UTF8Encoding($false)))
    }

    foreach ($inst in @(@{ Name = "Redis"; Port = 6379; Conf = "redis.production.conf"; Log = "redis.log" },
                        @{ Name = "RedisBroker"; Port = 6380; Conf = "redis-broker.conf"; Log = "redis-broker.log" })) {
        $srcConf = Join-Path $TargetDir "config\$($inst.Conf)"
        $dstConf = Join-Path $RedisBinDir "erp-$($inst.Conf)"
        if (Test-Path $srcConf) {
            New-DeployRedisConf $srcConf $dstConf $redisPassword $inst.Log
            Write-Ok "$($inst.Name) conf: $dstConf"
            $svc = Get-Service -Name $inst.Name -ErrorAction SilentlyContinue
            if (-not $svc) {
                & $redisServer --service-install $dstConf --service-name $inst.Name 2>&1 | ForEach-Object { Write-Host "  $_" }
                if ($LASTEXITCODE -eq 0) { Write-Ok "$($inst.Name) service installed" }
                else { Write-Warn "$($inst.Name) install failed - do manually." }
            } else {
                Write-Warn "$($inst.Name) exists - restarting to load new conf."
                Restart-Service -Name $inst.Name -Force -ErrorAction SilentlyContinue
            }
        }
    }
}

# ============================================================
# [7] Install NSSM services (portable python)
# ============================================================
Write-Step "Step 7/9 - Install NSSM services"
if ($SkipNssm) {
    Write-Warn "SkipNssm set."
} else {
    if (-not $NssmExe) { Write-Fail "NSSM not found."; exit 1 }
    if (-not (Test-Path $pythonExe)) { Write-Fail "portable python missing at $pythonExe"; exit 1 }

    # NSSM AppEnvironmentExtra 是 REG_MULTI_SZ：每个 "KEY=value" 必须是**独立参数**。
    # 旧实现把整个字符串作为一个参数传入，NSSM 只按第一个 '=' 拆分，
    # 导致 APP_ENV 的值变成 "production FASTAPI_DEBUG=false PYTHONPATH=..."（永远不等于
    # production，文档端点关不掉），且 PYTHONPATH/PYTHONUTF8/UVICORN_WORKERS 等全部丢失。
    $envExtra = @(
        "APP_ENV=production"
        "FASTAPI_DEBUG=false"
        "PYTHONPATH=$TargetDir"
        "PYTHONUTF8=1"
        "PYTHONUNBUFFERED=1"
        "UVICORN_WORKERS=4"
    )

    function Install-NssmService {
        param([string]$Name, [string]$Params)
        $existing = Get-Service -Name $Name -ErrorAction SilentlyContinue
        if ($existing) {
            & $NssmExe stop $Name | Out-Null
            & $NssmExe remove $Name confirm | Out-Null
        }
        $logDir = Join-Path $TargetDir "logs"
        New-Item -ItemType Directory -Force -Path $logDir | Out-Null
        & $NssmExe install $Name $pythonExe | Out-Null
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
        Write-Ok "Service $Name installed (python: $pythonExe)"
    }

    Install-NssmService "erp-prod" "-m fastapi_app.core.prod_runner --no-arq"
    Install-NssmService "erp-arq"  "-m arq fastapi_app.core.arq_app.WorkerSettings"
}

# ============================================================
# [8] Start services
# ============================================================
Write-Step "Step 8/9 - Start services"
if (-not $SkipStart) {
    foreach ($svc in @("Redis", "RedisBroker", "erp-prod", "erp-arq")) {
        $s = Get-Service -Name $svc -ErrorAction SilentlyContinue
        if ($s) {
            if ($s.Status -ne "Running") { Start-Service $svc -ErrorAction SilentlyContinue }
            Write-Ok "Service $svc -> $(Get-Service $svc | Select-Object -ExpandProperty Status)"
        }
    }
    Write-Ok "Nginx is managed by prod_runner."
}

# ============================================================
# [9] Verify
# ============================================================
Write-Step "Step 9/9 - Verification"
if (-not $SkipVerify) {
    Start-Sleep -Seconds 15
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 10
        Write-Ok "Backend /api/health -> $($r.StatusCode)"
    } catch { Write-Fail "Backend health: $($_.Exception.Message)" }
    try {
        $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:3000" -UseBasicParsing -TimeoutSec 10
        Write-Ok "Frontend :3000 -> $($r2.StatusCode)"
    } catch { Write-Warn "Frontend :3000 not ready: $($_.Exception.Message)" }
    if ($psql) {
        $envMap = Read-EnvFile $envFile
        $dbUser = if ($envMap["DB_USER"]) { $envMap["DB_USER"] } else { "erp_app" }
        $dbName = if ($envMap["DB_NAME"]) { $envMap["DB_NAME"] } else { "erp_system" }
        $env:PGPASSWORD = $envMap["DB_PASSWORD"]
        try {
            $tc = & $psql -h localhost -p 5432 -U $dbUser -d $dbName -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'" 2>$null
            if ($tc) { Write-Ok "Database $dbName has $($tc.Trim()) public tables" }
            else { Write-Fail "Cannot query database" }
        } finally { Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue }
    }
    if ($RedisBinDir -and (Test-Path (Join-Path $RedisBinDir "redis-cli.exe"))) {
        $cli = Join-Path $RedisBinDir "redis-cli.exe"
        $pw = (Read-EnvFile $envFile)["REDIS_PASSWORD"]
        $auth = if ($pw) { @("-a", $pw) } else { @() }
        foreach ($port in @(6379, 6380)) {
            $pong = & $cli @auth -p $port ping 2>$null
            if ($pong -match "PONG") { Write-Ok "Redis :${port} PONG" }
            else { Write-Warn "Redis :${port}: $pong" }
        }
    }
}

Write-Host ""
Write-Host "=== INSTALL COMPLETE ===" -ForegroundColor Green
Write-Host "  Access ERP at: http://$NewServerIP`:3000"
Write-Host "  Manual checks: docs/ERP_PORTABLE_DEPLOY_GUIDE.md section 5.4"
