# fix_service_env.ps1 — 修复 erp-prod / erp-arq 两个 NSSM 服务的环境变量配置
#
# 背景：install_on_target.ps1 / setup_on_target.ps1 旧实现把 AppEnvironmentExtra
# 写成单个字符串，NSSM 按第一个 '=' 拆分后 APP_ENV 变成
# "production FASTAPI_DEBUG=false PYTHONPATH=..."（永远不等于 production），
# 其余变量（PYTHONPATH/UVICORN_WORKERS 等）全部丢失，导致 /api/docs 关不掉。
#
# 本脚本以正确的 REG_MULTI_SZ（每个 KEY=value 独立条目）重写，并重启服务生效。
# 需要以管理员身份运行。

#Requires -RunAsAdministrator
param(
    [string]$NssmExe = "C:\nssm\nssm.exe"
)

$ErrorActionPreference = "Stop"
$TargetDir = "D:\erp_system"

if (-not (Test-Path $NssmExe)) { Write-Host "FAIL: nssm not found at $NssmExe"; exit 1 }

$common = @(
    "APP_ENV=production"
    "FASTAPI_DEBUG=false"
    "PYTHONPATH=$TargetDir"
    "PYTHONUTF8=1"
    "PYTHONUNBUFFERED=1"
    "UVICORN_WORKERS=4"
)

foreach ($svc in @("erp-prod", "erp-arq")) {
    & $NssmExe set $svc AppEnvironmentExtra @common | Out-Null
    if ($svc -eq "erp-arq") {
        & $NssmExe set $svc AppEnvironmentExtra "APP_ENV=production" "FASTAPI_DEBUG=false" "PYTHONPATH=$TargetDir" "PYTHONUTF8=1" "PYTHONUNBUFFERED=1" "UVICORN_WORKERS=4" "PYTHONIOENCODING=utf-8" | Out-Null
    }
    Write-Host "[$svc] AppEnvironmentExtra rewritten"
}

foreach ($svc in @("erp-prod", "erp-arq")) {
    & $NssmExe stop $svc | Out-Null
    Start-Sleep -Seconds 2
    & $NssmExe start $svc | Out-Null
    Write-Host "[$svc] restarted"
}

Write-Host "Verifying (expect docs:404, root:200)..."
Start-Sleep -Seconds 15
try {
    $docs = (Invoke-WebRequest -Uri "http://127.0.0.1:5002/api/docs" -UseBasicParsing -TimeoutSec 8).StatusCode
} catch {
    $docs = $_.Exception.Response.StatusCode.value__
}
try {
    $root = (Invoke-WebRequest -Uri "http://127.0.0.1:5002/" -UseBasicParsing -TimeoutSec 8).StatusCode
} catch {
    $root = $_.Exception.Response.StatusCode.value__
}
Write-Host "GET /api/docs -> $docs  (expect 404)"
Write-Host "GET /          -> $root  (expect 200)"
if ($docs -eq 404 -and $root -eq 200) { Write-Host "OK: fix verified" } else { Write-Host "WARN: state unexpected, check manually" }
