# ============================================================
# erp-web 单一职责迁移脚本(幂等,支持 -DryRun)
# 用途:注册 erp-web(NSSM 托管 nginx)并完成生产切换
# 执行:管理员 PowerShell(非提权无法操作服务,已实测 ACL 边界)
#   .\scripts\migrate_erp_web.ps1 -DryRun   只打印命令序列
#   .\scripts\migrate_erp_web.ps1           真实执行
# 前置:代码已部署(main 拉到本机);nssm 在 C:\nssm\nssm.exe
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

# 1) 注册 erp-web(stopped 状态,幂等:已存在则更新配置)
if ($DryRun) {
    if (Get-Service erp-web -ErrorAction SilentlyContinue) {
        Write-Host "nssm set erp-web Application $NginxExe"
    } else {
        Write-Host "nssm install erp-web $NginxExe"
    }
    Write-Host "nssm set erp-web Application $NginxExe"
    Write-Host "nssm set erp-web AppParameters $NginxArgs"
    Write-Host "nssm set erp-web AppDirectory $Root"
    Write-Host "nssm set erp-web AppExit Default Restart"
    Write-Host "nssm set erp-web AppRestartDelay 5000"
    Write-Host "nssm set erp-web Start SERVICE_AUTO_START"
    Write-Host "nssm set erp-web AppStdout $Root\logs\erp-web.log"
    Write-Host "nssm set erp-web AppStderr $Root\logs\erp-web.log"
    Write-Host "nssm stop erp-prod"
    Write-Host "nssm start erp-web"
    Write-Host "nssm start erp-prod"
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
}

# 2) 停旧树(NSSM Job Object 干净杀掉 prod_runner → uvicorn + nginx 整树)
Invoke-Step "stop erp-prod (kills whole legacy tree)" {
    & $Nssm stop erp-prod
}

# 3) 起 erp-web 并验证 nginx 真在服务
Invoke-Step "start erp-web" {
    & $Nssm start erp-web
}
Invoke-Step "verify erp-web serving :3000" {
    Start-Sleep -Seconds 2
    $resp = Invoke-WebRequest -Uri "http://127.0.0.1:3000/" -UseBasicParsing -TimeoutSec 10
    if ($resp.Headers["Server"] -notmatch "nginx") {
        throw ":3000 的 Server 头不是 nginx(实际: $($resp.Headers['Server']))"
    }
}

# 4) 起后端并验证健康
Invoke-Step "start erp-prod (slimmed supervisor, uvicorn only)" {
    & $Nssm start erp-prod
}
Invoke-Step "verify backend /api/health" {
    $deadline = (Get-Date).AddSeconds(45)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-WebRequest -Uri "http://127.0.0.1:5002/api/health" -UseBasicParsing -TimeoutSec 3
            if ($r.StatusCode -eq 200) { break }
        } catch { Start-Sleep -Seconds 2 }
    }
}

# 5) 终态判定
Invoke-Step "final verdict via runtime_mode_probe.py" {
    Set-Location $Root
    & python scripts/diag/runtime_mode_probe.py
}

Write-Host ""
Write-Host "[migrate] 完成。请按 docs/superpowers/specs/2026-09-28-erp-web-single-responsibility-design.md §9 验证四条硬判据。" -ForegroundColor Green
Write-Host "[migrate] 回滚步骤见本脚本头部注释。" -ForegroundColor Green
