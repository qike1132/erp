# ============================================================
# 滨发协同系统（ERP）— Phase 1 切换脚本
# 用途：释放「手工 / 开发期」进程占用的 3000 / 5002 端口
#       → 启动 NSSM 托管的 erp-prod（uvicorn workers + nginx 服务 dist）
#         与 erp-arq（ARQ worker）→ 健康校验。
#
# ⚠️ 破坏性脚本（会强杀进程）。运行前请先 -DryRun 预览。
#
# 用法：
#   .\scripts\phase1_switch.ps1 -DryRun   只打印将执行的动作，不做任何变更
#   .\scripts\phase1_switch.ps1           正式切换（需管理员权限）
#   .\scripts\phase1_switch.ps1 -Force    允许强杀 NSSM 托管服务占用的端口（不推荐）
#
# 护栏（2026-09-24 加固，对齐 restart_prod.ps1 的 M9 范式）：
#   1. 端口占用者若属于 NSSM 托管服务（erp-prod / erp-arq）的**进程树**，
#      则拒绝强杀并提示改用 nssm restart，除非显式 -Force。
#      （历史事故：杀端口另起进程与 NSSM 自动重启互抢 5002，见 restart_prod.ps1 顶部注释）
#   2. 非管理员会话在**任何杀进程之前**即退出 —— 否则会「杀了开发进程却起不来生产服务」，
#      把站点留在全停状态。
#   3. 提供 -DryRun，便于先看清单再决定。
# ============================================================

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Force,
    [string]$LogPath
)

$ErrorActionPreference = 'Continue'
$Root = Split-Path -Parent $PSScriptRoot   # 本脚本位于 scripts/，其父目录即仓库根
if (-not $LogPath) { $LogPath = Join-Path $Root 'logs\phase1_switch.log' }

# 端口占用者若属于这些 NSSM 服务的进程树，禁止裸杀
$ManagedServices = @('erp-prod', 'erp-arq')

function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    return ([Security.Principal.WindowsPrincipal]$id).IsInRole(
        [Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-ManagedProcessMap {
    # 返回 @{ PID = 服务名 }，覆盖服务的**整棵进程树**。
    # NSSM 会 spawn 子进程（nginx / uvicorn 由子进程持有端口），
    # 只比对服务自身 PID 会漏判 —— 必须沿父子链下钻。
    $map = @{}
    foreach ($svcName in $ManagedServices) {
        $svc = Get-CimInstance Win32_Service -Filter "Name='$svcName'" -ErrorAction SilentlyContinue
        if (-not $svc -or $svc.ProcessId -le 0) { continue }
        $map[[int]$svc.ProcessId] = $svcName
        $queue = New-Object System.Collections.Queue
        $queue.Enqueue([int]$svc.ProcessId)
        while ($queue.Count -gt 0) {
            $cur = [int]$queue.Dequeue()
            $kids = Get-CimInstance Win32_Process -Filter "ParentProcessId=$cur" -ErrorAction SilentlyContinue
            foreach ($k in $kids) {
                $kpid = [int]$k.ProcessId
                if (-not $map.ContainsKey($kpid)) {
                    $map[$kpid] = $svcName
                    $queue.Enqueue($kpid)
                }
            }
        }
    }
    return $map
}

function Step($n, $msg) { Write-Host "`n===== [$n] $msg =====" -ForegroundColor Cyan }

$logDir = Split-Path -Parent $LogPath
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
if (-not $DryRun) { Start-Transcript -Path $LogPath -Force | Out-Null }

Write-Host "=== ERP Phase 1 切换 ===" -ForegroundColor Cyan
if ($DryRun) { Write-Host "模式: DryRun（只预览，不做任何变更）" -ForegroundColor Yellow }

# ------------------------------------------------------------
# 前置护栏：权限（必须在杀进程之前判定）
# ------------------------------------------------------------
if (-not $DryRun -and -not (Test-IsAdmin)) {
    Write-Host "ERROR: 非管理员会话。" -ForegroundColor Red
    Write-Host "  Step 2/3 的 Start-Service 需要提权；若在此状态先强杀端口占用者，" -ForegroundColor Red
    Write-Host "  会「杀了开发进程却起不来生产服务」，把站点留在全停状态。" -ForegroundColor Red
    Write-Host "  预览:  .\scripts\phase1_switch.ps1 -DryRun" -ForegroundColor Yellow
    Write-Host "  正式:  以管理员身份重新运行本脚本" -ForegroundColor Yellow
    Stop-Transcript | Out-Null
    exit 1
}

Step 1 'Stop manual processes (Vite dev :3000 + manual backend :5002)'
$managedMap = Get-ManagedProcessMap
if ($managedMap.Count -gt 0) {
    Write-Host ("  已识别 NSSM 托管进程树 PID: " + (($managedMap.Keys | Sort-Object) -join ', ')) -ForegroundColor DarkGray
}

$refused = 0
foreach ($port in 3000, 5002) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    foreach ($c in $conns) {
        $ownerPid = [int]$c.OwningProcess
        $p = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if (-not $p) { continue }

        if ($managedMap.ContainsKey($ownerPid) -and -not $Force) {
            $refused++
            Write-Host "REFUSE: 端口 $port 由 NSSM 服务 '$($managedMap[$ownerPid])' 的进程树持有" -ForegroundColor Red
            Write-Host "        ($($p.ProcessName) PID=$ownerPid) —— 拒绝裸杀。" -ForegroundColor Red
            Write-Host "        正确方式: nssm restart $($managedMap[$ownerPid])（或 ERP 服务器管理器 GUI）" -ForegroundColor Yellow
            Write-Host "        应急裸杀: 本脚本加 -Force（自行承担与 NSSM 抢端口的风险）" -ForegroundColor DarkGray
            continue
        }

        if ($DryRun) {
            Write-Host "  [DryRun] 将强杀: $($p.ProcessName) PID=$ownerPid (port $port)"
        } else {
            Write-Host "  Kill: $($p.ProcessName) PID=$ownerPid (port $port)"
            Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        }
    }
}

if ($DryRun) {
    Write-Host "`n[DryRun] 预览结束，未做任何变更。" -ForegroundColor Yellow
    Stop-Transcript | Out-Null
    exit 0
}

if ($refused -gt 0) {
    Write-Host "`n注意: $refused 个端口占用者属 NSSM 托管服务，已跳过强杀（服务应已在运行）。" -ForegroundColor Yellow
}

Start-Sleep -Seconds 3
foreach ($port in 3000, 5002) {
    $left = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($left) { Write-Host "WARN: port $port still occupied by: $($left.OwningProcess | Select-Object -Unique)" -ForegroundColor Yellow }
    else { Write-Host "OK: port $port released" -ForegroundColor Green }
}

Step 2 'Start erp-prod (prod_runner: uvicorn workers + nginx hosting dist)'
try { Start-Service -Name 'erp-prod' -ErrorAction Stop; Write-Host 'OK: erp-prod started' -ForegroundColor Green }
catch { Write-Host "FAIL: erp-prod start failed: $($_.Exception.Message)" -ForegroundColor Red }

Step 3 'Start erp-arq (ARQ cron backup worker)'
try { Start-Service -Name 'erp-arq' -ErrorAction Stop; Write-Host 'OK: erp-arq started' -ForegroundColor Green }
catch { Write-Host "FAIL: erp-arq start failed: $($_.Exception.Message)" -ForegroundColor Red }

Step 4 'Disable zombie scheduled tasks (pointing to non-existent paths)'
foreach ($t in 'ERP_Database_Backup', 'ERPSystem') {
    try {
        Disable-ScheduledTask -TaskName $t -ErrorAction Stop | Out-Null
        Write-Host "OK: disabled $t" -ForegroundColor Green
    } catch { Write-Host "FAIL: disable $t failed: $($_.Exception.Message)" -ForegroundColor Red }
}

Step 5 'Health verification (wait up to 90 seconds)'
$deadline = (Get-Date).AddSeconds(90)
$backendOk = $false; $nginxOk = $false
while ((Get-Date) -lt $deadline -and -not ($backendOk -and $nginxOk)) {
    Start-Sleep -Seconds 3
    if (-not $backendOk) {
        try {
            $r = Invoke-WebRequest -Uri 'http://127.0.0.1:5002/api/health' -UseBasicParsing -TimeoutSec 5
            if ($r.StatusCode -eq 200) { $backendOk = $true; Write-Host 'OK: backend /api/health -> 200' -ForegroundColor Green }
        } catch { Write-Host '... backend not ready' }
    }
    if (-not $nginxOk) {
        try {
            $r2 = Invoke-WebRequest -Uri 'http://127.0.0.1:3000/nginx-health' -UseBasicParsing -TimeoutSec 5
            if ($r2.Content -like '*nginx*') { $nginxOk = $true; Write-Host 'OK: nginx /nginx-health marker found' -ForegroundColor Green }
        } catch { Write-Host '... nginx not ready' }
    }
}
if (-not $backendOk) { Write-Host 'FAIL: backend not ready within 90s' -ForegroundColor Red }
if (-not $nginxOk)   { Write-Host 'FAIL: nginx not ready within 90s' -ForegroundColor Red }

Step 6 'Security re-check: doc endpoints must be 404 (production mode)'
foreach ($u in 'http://127.0.0.1:3000/api/docs', 'http://127.0.0.1:3000/api/openapi.json') {
    try {
        $r = Invoke-WebRequest -Uri $u -UseBasicParsing -TimeoutSec 5
        Write-Host "FAIL: $u -> $($r.StatusCode) (expected 404)" -ForegroundColor Red
    } catch {
        Write-Host "OK: $u -> $($_.Exception.Response.StatusCode.value__) (closed)" -ForegroundColor Green
    }
}

Step 7 'Final state: services and ports'
Get-Service erp-prod, erp-arq | Select-Object Name, Status | Format-Table -AutoSize
Get-NetTCPConnection -LocalPort 3000, 5002 -State Listen -ErrorAction SilentlyContinue |
    Select-Object LocalAddress, LocalPort, OwningProcess | Format-Table -AutoSize

Write-Host "`n===== PHASE1 DONE =====" -ForegroundColor Green
Stop-Transcript | Out-Null
