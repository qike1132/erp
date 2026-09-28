# ============================================================
# erp-web 单一职责迁移脚本(幂等,支持 -DryRun)
# 用途:注册 erp-web(NSSM 托管 nginx)并完成生产切换
# 执行:管理员 PowerShell(非提权无法操作服务,已实测 ACL 边界)
#   .\scripts\migrate_erp_web.ps1 -DryRun   只打印命令序列
#   .\scripts\migrate_erp_web.ps1           真实执行
# 前置:代码已部署(main 拉到本机);nssm 在 C:\nssm\nssm.exe
#
# 幂等:启动/停止前先查服务状态,已在目标态则跳过——因此可在任意中间态重跑
# (如 erp-prod 已停、或上次中断在半途)。
#
# 回滚(如需):
#   nssm stop erp-web
#   nssm set erp-web Start SERVICE_DISABLED   # 防止开机自启与旧 prod_runner 双 nginx
#   git revert <本系列提交>
#   nssm restart erp-prod                      # 旧 prod_runner 重新拉起 nginx
# ============================================================
param([switch]$DryRun)

$ErrorActionPreference = "Stop"
$Nssm = "C:\nssm\nssm.exe"
$Root = "D:\erp_system"
$NginxExe = "C:\nginx\nginx.exe"
$NginxArgs = "-p D:\erp_system -c D:\erp_system\config\nginx-windows.conf -e D:\erp_system\logs\nginx-error.log"

if (-not (Test-Path $Nssm)) { throw "未找到 nssm: $Nssm" }
if (-not (Test-Path $NginxExe)) { throw "未找到 nginx: $NginxExe" }

function Invoke-Step {
    param([string]$Desc, [scriptblock]$Act)
    Write-Host "[migrate] $Desc" -ForegroundColor Cyan
    if ($DryRun) { return }
    & $Act
    if ($LASTEXITCODE -ne 0 -and $null -ne $LASTEXITCODE) {
        throw "step failed: $Desc (rc=$LASTEXITCODE)"
    }
}

function Get-SvcStateText {
    param([string]$Name)
    $svc = Get-Service -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $svc) { return 'NOTINSTALLED' }
    return $svc.Status.ToString()
}

function Start-SvcIfNeeded {
    param([string]$Name, [int]$TimeoutSec = 25)
    if ((Get-SvcStateText $Name) -eq 'RUNNING') {
        Write-Host "[migrate]   $Name 已是 RUNNING,跳过 start" -ForegroundColor DarkGray
        return
    }
    & $Nssm start $Name
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if ((Get-SvcStateText $Name) -eq 'RUNNING') {
            Write-Host "[migrate]   $Name 已 RUNNING" -ForegroundColor DarkGray
            return
        }
        Start-Sleep -Seconds 1
    }
    throw "$Name 在 ${TimeoutSec}s 内未进入 RUNNING(当前: $(Get-SvcStateText $Name))。可重跑本脚本(幂等),或按头部注释回滚。"
}

# 1) 注册 erp-web(stopped 状态,幂等:已存在则更新配置)
if ($DryRun) {
    if (Get-Service erp-web -ErrorAction SilentlyContinue) {
        Write-Host "nssm set erp-web Application $NginxExe"
    } else {
        Write-Host "nssm install erp-web $NginxExe"
    }
    # 已存在时的实际路径还会显式 set Application(纠正换 Python/nginx 后的指向);
    # DryRun 下两条择一打印即可,不打重复。
    Write-Host "nssm set erp-web AppParameters $NginxArgs"
    Write-Host "nssm set erp-web AppDirectory $Root"
    Write-Host "nssm set erp-web AppExit Default Restart"
    Write-Host "nssm set erp-web AppRestartDelay 5000"
    Write-Host "nssm set erp-web Start SERVICE_AUTO_START"
    Write-Host "nssm set erp-web AppStdout $Root\logs\erp-web.log"
    Write-Host "nssm set erp-web AppStderr $Root\logs\erp-web.log"
    Write-Host "nssm set erp-web AppRotateFiles 1"
    Write-Host "nssm set erp-web AppRotateBytes 10485760"
    Write-Host "nssm set erp-web AppNoConsole 1"
    Write-Host "nssm stop erp-prod            # 已是 STOPPED 则跳过"
    Write-Host "nssm start erp-web            # 已是 RUNNING 则跳过"
    Write-Host "nssm start erp-prod           # 已是 RUNNING 则跳过"
    Write-Host "nssm start erp-arq            # 已是 RUNNING 则跳过"
    Write-Host "python scripts/diag/runtime_mode_probe.py"
    exit 0
}

Invoke-Step "register erp-web (install or update)" {
    if (Get-Service erp-web -ErrorAction SilentlyContinue) {
        & $Nssm set erp-web Application $NginxExe
        & $Nssm set erp-web AppParameters $NginxArgs
    } else {
        & $Nssm install erp-web $NginxExe
        & $Nssm set erp-web AppParameters $NginxArgs
    }
}
Invoke-Step "configure erp-web" {
    & $Nssm set erp-web AppDirectory $Root
    & $Nssm set erp-web AppExit Default Restart
    & $Nssm set erp-web AppRestartDelay 5000
    & $Nssm set erp-web Start SERVICE_AUTO_START
    & $Nssm set erp-web AppStdout "$Root\logs\erp-web.log"
    & $Nssm set erp-web AppStderr "$Root\logs\erp-web.log"
    & $Nssm set erp-web AppRotateFiles 1
    & $Nssm set erp-web AppRotateBytes 10485760
    & $Nssm set erp-web AppNoConsole 1
}

# 2) 停旧树(NSSM Job Object 干净杀掉 prod_runner → uvicorn + nginx 整树)
#    关键顺序:必须先停 erp-prod 再起 erp-web,否则双 nginx 抢 :3000。
Invoke-Step "stop erp-prod (kills whole legacy tree)" {
    if ((Get-SvcStateText 'erp-prod') -eq 'STOPPED') {
        Write-Host "[migrate]   erp-prod 已是 STOPPED,跳过 stop" -ForegroundColor DarkGray
    } else {
        & $Nssm stop erp-prod
        $deadline = (Get-Date).AddSeconds(45)
        while ((Get-Date) -lt $deadline) {
            if ((Get-SvcStateText 'erp-prod') -eq 'STOPPED') { break }
            Start-Sleep -Seconds 1
        }
        if ((Get-SvcStateText 'erp-prod') -ne 'STOPPED') {
            throw "erp-prod 在 45s 内未确认 STOPPED——旧 nginx 可能仍占 :3000,继续会双跑。请查明后重跑。"
        }
    }
}

# 3) 起 erp-web 并验证 nginx 真在服务
Invoke-Step "start erp-web" { Start-SvcIfNeeded -Name 'erp-web' }
Invoke-Step "verify erp-web serving :3000" {
    $ok = $false
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline) {
        try {
            $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000/nginx-health" -UseBasicParsing -TimeoutSec 5
            if ($resp.Content -match '"service":"nginx"') { $ok = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $ok) {
        throw "erp-web 已启动但 :3000/nginx-health 未返回 nginx 标记——端口可能被 dev server 等其它进程占用。请先停掉占用者(dev server 用 GUI 停止开发模式)再重跑。"
    }
}

# 4) 起后端并验证健康
Invoke-Step "start erp-prod (slimmed supervisor, uvicorn only)" { Start-SvcIfNeeded -Name 'erp-prod' }
Invoke-Step "verify backend /api/health" {
    $script:BackendHealthy = $false
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { $script:BackendHealthy = $true; break }
        } catch { }
        Start-Sleep -Seconds 2
    }
    if (-not $script:BackendHealthy) {
        throw "后端 /api/health 在 45s 内未恢复 200。系统处于半迁移态(erp-web 已起,erp-prod 异常)——可重跑本脚本(幂等),或按头部注释回滚。"
    }
}

# 5) 起 ARQ(定时备份的唯一调度者;此前遗漏会导致备份静默停摆)
Invoke-Step "start erp-arq (backup scheduler)" { Start-SvcIfNeeded -Name 'erp-arq' }
Invoke-Step "verify erp-arq running" {
    if ((Get-SvcStateText 'erp-arq') -ne 'RUNNING') {
        throw "erp-arq 未 RUNNING——定时备份会静默停摆。请检查 logs\erp-arq.log 与 erp-redis-broker 服务。"
    }
}

# 6) 终态判定
Invoke-Step "final verdict via runtime_mode_probe.py" {
    Set-Location $Root
    & python scripts/diag/runtime_mode_probe.py
}

Write-Host ""
Write-Host "[migrate] 完成。请按 deliverables/2026-09-28-erp-web-migration/VERIFICATION.md 验证四条硬判据。" -ForegroundColor Green
Write-Host "[migrate] 回滚步骤见本脚本头部注释。" -ForegroundColor Green
