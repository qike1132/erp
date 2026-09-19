# ============================================================================
#  fix_nssm_appenv.ps1 —— 修正 NSSM AppEnvironmentExtra「单元素」错配
# ----------------------------------------------------------------------------
#  背景（2026-09-17 审核 S2）：
#    erp-prod / erp-arq 的 AppEnvironmentExtra 是 REG_MULTI_SZ，但只有 1 个元素：
#      'APP_ENV=production FASTAPI_DEBUG=false PYTHONPATH=... PYTHONUTF8=1 ...'
#    NSSM 按「每个元素」设一个环境变量（在第一个 = 处切分），单元素 ⇒ 只产生
#    APP_ENV 一个变量，其余全部失效。APP_ENV 之所以没炸，是靠 config.py 的
#    「取首 token」容错救回的（侥幸）。
#    后果：PYTHONUNBUFFERED 未生效 → erp-prod.log 行序错乱/启动日志滞后；
#          PYTHONUTF8 未生效 → erp-arq.log 中文乱码。
#
#  本脚本把它改写为「一变量一元素」（语义等价，只是让它们真正生效）。
#
#  用法（必须管理员 PowerShell）：
#    .\fix_nssm_appenv.ps1 -DryRun      # 只读预览，不改任何东西（非管理员也可跑）
#    .\fix_nssm_appenv.ps1 -Verify      # 只读校验当前元素个数与内容
#    .\fix_nssm_appenv.ps1              # 备份 + 写入（不重启服务）
#    .\fix_nssm_appenv.ps1 -Restart     # 备份 + 写入 + 重启两个服务（会短暂中断）
#    .\fix_nssm_appenv.ps1 -Rollback    # 从最近一次备份还原
#
#  注意：写入后必须重启对应服务才生效。erp-prod 重启会让 :5002 与 :3000 短暂中断。
# ============================================================================

[CmdletBinding()]
param(
    [switch]$DryRun,
    [switch]$Verify,
    [switch]$Restart,
    [switch]$Rollback,
    [string]$BackupDir = 'D:\erp_system\deliverables\audit-2026-09-17\nssm_env_backup'
)

$ErrorActionPreference = 'Stop'

$NssmPath = 'C:\nssm\nssm.exe'
$ParamsRoot = 'HKLM:\SYSTEM\CurrentControlSet\Services\{0}\Parameters'

# 期望的「一变量一元素」形态。内容与原单串完全一致，只是拆成 6 个元素。
# （UVICORN_WORKERS 对 erp-arq 无意义，但保留以保持与原配置逐字一致，减少变量。）
$Expected = @(
    'APP_ENV=production',
    'FASTAPI_DEBUG=false',
    'PYTHONPATH=D:\erp_system',
    'PYTHONUTF8=1',
    'PYTHONUNBUFFERED=1',
    'UVICORN_WORKERS=8'
)
$TargetServices = @('erp-prod', 'erp-arq')


function Test-IsAdmin {
    $id = [Security.Principal.WindowsIdentity]::GetCurrent()
    $p = New-Object Security.Principal.WindowsPrincipal($id)
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-EnvExtraRaw {
    param([string]$Service)
    $key = $ParamsRoot -f $Service
    try {
        $item = Get-ItemProperty -Path $key -Name 'AppEnvironmentExtra' -ErrorAction Stop
        return $item.AppEnvironmentExtra
    } catch {
        return $null
    }
}

function Get-EnvExtraEntries {
    param([string]$Service)
    # REG_MULTI_SZ 末尾的终止空元素会被 PowerShell 读成一个空字符串，它不产生
    # 任何环境变量，必须在计数与逐项比较前剔除：否则 nssm 写入 6 条后会读成
    # 7 条，Assert-EnvExtra 的个数校验会误判失败，脚本在写完 erp-prod 后中断。
    $raw = @(Get-EnvExtraRaw -Service $Service)
    return @($raw | Where-Object { -not [string]::IsNullOrEmpty($_) })
}

function Show-Current {
    param([string]$Service)
    $raw = Get-EnvExtraRaw -Service $Service
    Write-Host ("[{0}] AppEnvironmentExtra" -f $Service) -ForegroundColor Cyan
    if ($null -eq $raw) {
        Write-Host '    (不存在 / 无法读取)' -ForegroundColor Yellow
        return
    }
    $arr = @(Get-EnvExtraEntries -Service $Service)
    Write-Host ("    有效元素个数 = {0}（已剔除终止空元素）" -f $arr.Count)
    $i = 0
    foreach ($e in $arr) {
        Write-Host ("      [{0}] {1}" -f $i, $e)
        $i = $i + 1
    }
    # 判据不是「元素个数 > 1」，而是「每个元素是否恰好只有一个 =」：
    # NSSM 按首个 = 切分，一条拼接串会吞掉其后所有变量 —— 这正是本缺陷。
    # 旧判据只看个数，把「1 条拼接串 + 1 个空元素」误报成绿色正常。
    $joined = @($arr | Where-Object { ($_.Split('=').Count - 1) -gt 1 })
    if ($joined.Count -gt 0) {
        Write-Host ("    >>> 异常：有 {0} 个元素含多个 = => 其后变量全部失效" -f $joined.Count) -ForegroundColor Red
    } elseif ($arr.Count -ne $Expected.Count) {
        Write-Host ("    >>> 异常：元素个数 = {0}，期望 {1}" -f $arr.Count, $Expected.Count) -ForegroundColor Red
    } else {
        Write-Host '    >>> 正常：一变量一元素' -ForegroundColor Green
    }
}

function Backup-Current {
    param([string]$Service)
    if (-not (Test-Path $BackupDir)) {
        New-Item -ItemType Directory -Path $BackupDir -Force | Out-Null
    }
    $raw = Get-EnvExtraRaw -Service $Service
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    $file = Join-Path $BackupDir ("{0}-AppEnvironmentExtra-{1}.json" -f $Service, $stamp)
    $obj = [pscustomobject]@{ Service = $Service; Value = @($raw); CapturedAt = $stamp }
    $obj | ConvertTo-Json -Depth 5 | Set-Content -Path $file -Encoding UTF8
    Write-Host ("    已备份 -> {0}" -f $file) -ForegroundColor DarkGray
    return $file
}

function Set-EnvExtra {
    param([string]$Service, [string[]]$Entries)
    if (-not (Test-Path $NssmPath)) { throw "找不到 nssm: $NssmPath" }
    # nssm set <svc> AppEnvironmentExtra KEY=VALUE KEY=VALUE ...
    # 每个参数成为一个独立的 REG_MULTI_SZ 元素 —— 这正是修复的关键。
    $argv = @('set', $Service, 'AppEnvironmentExtra') + $Entries
    Write-Host ("    执行: nssm {0}" -f ($argv -join ' ')) -ForegroundColor DarkGray
    $out = & $NssmPath @argv 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw ("nssm set 失败（rc={0}）：{1}" -f $LASTEXITCODE, ($out -join ' '))
    }
}

function Assert-EnvExtra {
    param([string]$Service, [string[]]$Entries)
    $raw = @(Get-EnvExtraEntries -Service $Service)
    if ($raw.Count -ne $Entries.Count) {
        throw ("写后校验失败：{0} 元素个数 = {1}，期望 {2}" -f $Service, $raw.Count, $Entries.Count)
    }
    for ($i = 0; $i -lt $Entries.Count; $i++) {
        if ([string]$raw[$i] -ne $Entries[$i]) {
            throw ("写后校验失败：{0} 第 {1} 个元素 = '{2}'，期望 '{3}'" -f $Service, $i, $raw[$i], $Entries[$i])
        }
    }
    Write-Host ("    写后校验通过：{0} 个元素，逐项一致" -f $raw.Count) -ForegroundColor Green
}

function Do-Rollback {
    if (-not (Test-Path $BackupDir)) { throw "备份目录不存在：$BackupDir" }
    foreach ($svc in $TargetServices) {
        $f = Get-ChildItem -Path $BackupDir -Filter ("{0}-AppEnvironmentExtra-*.json" -f $svc) |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if ($null -eq $f) { Write-Host "[$svc] 无备份，跳过" -ForegroundColor Yellow; continue }
        $obj = Get-Content -Path $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $entries = @($obj.Value)
        Write-Host ("[{0}] 从 {1} 还原（{2} 个元素）" -f $svc, $f.Name, $entries.Count) -ForegroundColor Cyan
        if ($entries.Count -gt 0 -and $entries[0] -ne '') {
            Set-EnvExtra -Service $svc -Entries $entries
            Assert-EnvExtra -Service $svc -Entries $entries
        }
    }
    Write-Host '还原完成。重启服务后生效。' -ForegroundColor Green
}


# ------------------------------- 主流程 -------------------------------

Write-Host '=== NSSM AppEnvironmentExtra 修正（S2） ===' -ForegroundColor White
Write-Host ''

if ($Verify) {
    foreach ($svc in $TargetServices) { Show-Current -Service $svc; Write-Host '' }
    Write-Host '（-Verify 只读，未做任何修改）'
    exit 0
}

if ($DryRun) {
    Write-Host '--- 当前状态 ---' -ForegroundColor White
    foreach ($svc in $TargetServices) { Show-Current -Service $svc; Write-Host '' }
    Write-Host '--- 将要写入的形态（每个 KEY=VALUE 独立成一个元素）---' -ForegroundColor White
    foreach ($svc in $TargetServices) {
        Write-Host ("[{0}] {1} 个元素" -f $svc, $Expected.Count) -ForegroundColor Cyan
        foreach ($e in $Expected) { Write-Host ("      {0}" -f $e) }
    }
    Write-Host ''
    Write-Host '（-DryRun 只读，未做任何修改。去掉 -DryRun 即为实际执行。）' -ForegroundColor Yellow
    exit 0
}

if (-not (Test-IsAdmin)) {
    Write-Host '需要管理员权限才能写 HKLM 注册表。请用「管理员 PowerShell」重跑。' -ForegroundColor Red
    Write-Host '可先以非管理员身份跑 -DryRun / -Verify 查看现状。' -ForegroundColor Yellow
    exit 1
}

if ($Rollback) {
    Do-Rollback
    exit 0
}

foreach ($svc in $TargetServices) {
    Write-Host ("[{0}]" -f $svc) -ForegroundColor Cyan
    Show-Current -Service $svc
    Backup-Current -Service $svc | Out-Null
    Set-EnvExtra -Service $svc -Entries $Expected
    Assert-EnvExtra -Service $svc -Entries $Expected
    Write-Host ''
}

if ($Restart) {
    foreach ($svc in $TargetServices) {
        Write-Host ("重启 {0} ..." -f $svc) -ForegroundColor Yellow
        & $NssmPath restart $svc | Out-Null
    }
    Write-Host '已重启。erp-prod 重启期间 :5002/:3000 会短暂中断。' -ForegroundColor Yellow
} else {
    Write-Host '已写入，但【尚未生效】—— 需重启服务：' -ForegroundColor Yellow
    Write-Host '    nssm restart erp-arq   ;   nssm restart erp-prod' -ForegroundColor Yellow
    Write-Host '（erp-prod 重启会让 :5002 后端与 :3000 前端短暂中断，建议低峰执行）' -ForegroundColor Yellow
}

Write-Host ''
Write-Host '重启后有效性验证（三选一即可）：' -ForegroundColor White
Write-Host '  1) type D:\erp_system\logs\erp-arq.log   -> 中文不再乱码'
Write-Host '  2) 新起的 erp-prod 子进程环境中存在 PYTHONUNBUFFERED=1 / UVICORN_WORKERS=8'
Write-Host '  3) logs\erp-prod.log 中本代启动日志及时落盘（不再滞后到下一轮）'
