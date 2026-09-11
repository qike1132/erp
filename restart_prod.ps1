# ============================================================
# 滨发协同系统（ERP）— 方案 A：一键重启脚本
# 用途：改完代码后手动运行，自动完成「构建前端 + 重启后端」
# 用法：
#   .\restart_prod.ps1              完整构建（含类型检查）+ 重启后端
#   .\restart_prod.ps1 -Fast        快速构建（跳过类型检查）+ 重启后端
#   .\restart_prod.ps1 -SkipBuild   只重启后端，不构建前端
# 注意：会停掉当前占用 API 端口的进程（含开发模式 uvicorn），请确认后运行
# ============================================================

param(
    [switch]$Fast,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

Write-Host "=== ERP 一键重启（构建前端 + 重启后端）===" -ForegroundColor Cyan

# ------------------------------------------------------------
# 1. 从 .env 加载环境变量（API_PORT / UVICORN_WORKERS 等）
# ------------------------------------------------------------
$envFile = Join-Path $Root ".env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        if ($_ -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$' -and $Matches[1] -notmatch '^\s*#') {
            $key = $Matches[1]
            $val = $Matches[2].Trim().Trim('"')
            if (-not [Environment]::GetEnvironmentVariable($key)) {
                [Environment]::SetEnvironmentVariable($key, $val, "Process")
            }
        }
    }
} else {
    Write-Host "WARNING: 未找到 .env，将使用默认端口/参数" -ForegroundColor Yellow
}

$ApiPort = [int]($env:API_PORT ?? "5002")
$Workers = $env:UVICORN_WORKERS ?? "4"

# ------------------------------------------------------------
# 2. 前端构建（产物输出到 frontend-vite/dist）
# ------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "`n[1/3] 构建前端..." -ForegroundColor Yellow
    Push-Location (Join-Path $Root "frontend-vite")
    try {
        if ($Fast) {
            Write-Host "  快速构建（跳过类型检查）: npm run build:fast"
            & npm run build:fast
        } else {
            Write-Host "  完整构建（含类型检查）: npm run build"
            & npm run build
        }
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  ERROR: 前端构建失败，已中止，后端未重启" -ForegroundColor Red
            exit 1
        }
        Write-Host "  前端构建完成 -> frontend-vite/dist" -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    Write-Host "`n[1/3] 已跳过前端构建（-SkipBuild）" -ForegroundColor DarkGray
}

# ------------------------------------------------------------
# 3. 停掉旧后端（占用 API 端口的进程）
# ------------------------------------------------------------
Write-Host "`n[2/3] 停止旧后端 (端口 $ApiPort)..." -ForegroundColor Yellow
$listeners = Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue
if ($listeners) {
    foreach ($conn in $listeners) {
        $oldPid = $conn.OwningProcess
        Write-Host "  终止 PID $oldPid（占用端口 $ApiPort）..."
        Stop-Process -Id $oldPid -Force -ErrorAction SilentlyContinue
    }
    # 等待端口释放（最多 10 秒）
    for ($i = 0; $i -lt 10; $i++) {
        Start-Sleep -Seconds 1
        if (-not (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue)) {
            break
        }
    }
} else {
    Write-Host "  端口 $ApiPort 无占用进程" -ForegroundColor DarkGray
}

if (Get-NetTCPConnection -LocalPort $ApiPort -State Listen -ErrorAction SilentlyContinue) {
    Write-Host "  ERROR: 端口 $ApiPort 未能释放，请检查占用进程" -ForegroundColor Red
    exit 1
}

# ------------------------------------------------------------
# 4. 启动新后端（后台运行，日志写入 logs/backend.out.log）
# ------------------------------------------------------------
Write-Host "`n[3/3] 启动后端 (uvicorn, workers=$Workers)..." -ForegroundColor Yellow
$logDir = Join-Path $Root "logs"
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$logFile = Join-Path $logDir "backend.out.log"

$uvicornArgs = @(
    "-m", "uvicorn", "fastapi_app.main:app",
    "--host", "0.0.0.0",
    "--port", "$ApiPort",
    "--workers", "$Workers",
    "--http", "httptools",
    "--no-access-log",
    "--proxy-headers",
    "--forwarded-allow-ips=*",
    "--timeout-keep-alive", "5"
)

Start-Process -FilePath "python" -ArgumentList $uvicornArgs `
    -WorkingDirectory $Root `
    -RedirectStandardOutput $logFile `
    -RedirectStandardError $logFile `
    -WindowStyle Hidden

# ------------------------------------------------------------
# 5. 健康检查（轮询 /api/health，最多 30 秒）
# ------------------------------------------------------------
Write-Host "`n等待后端就绪（轮询 /api/health）..." -ForegroundColor Yellow
$healthUrl = "http://127.0.0.1:$ApiPort/api/health"
$ready = $false
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $resp = Invoke-WebRequest -Uri $healthUrl -UseBasicParsing -TimeoutSec 2
        if ($resp.StatusCode -eq 200) {
            $ready = $true
            break
        }
    } catch { }
}

if ($ready) {
    Write-Host "`n=== 后端已就绪: $healthUrl ===" -ForegroundColor Green
} else {
    Write-Host "`nWARNING: 后端未在 30 秒内就绪，请查看日志: $logFile" -ForegroundColor Yellow
}
