# ============================================================
# SOP v9.0 阶段5: 环境初始化与增强备份 (PowerShell)
# 用途: FIX阶段启动前的环境校验、双备份、校验和生成
# 调用: powershell -File phase5-init-backup.ps1 [-HealthUrl url] [-Language python] [-GracePeriod 3]
# 输出: stdout JSON 结果
# ============================================================
#requires -Version 3.0
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

param(
    [string]$HealthUrl = '',
    [string]$Language = 'python',
    [int]$GracePeriod = 3
)

# 钳位 GracePeriod 到 1-60
$GracePeriod = [Math]::Max(1, [Math]::Min(60, $GracePeriod))

# 参数消毒: 检测路径穿越
if ($HealthUrl -match '\.\.' -or $HealthUrl -match '[&;|`$]') {
    $HealthUrl = [System.Uri]::EscapeDataString($HealthUrl)
    Write-Warning "[SANITIZED] HealthUrl 已转义"
}

# 5.2 PowerShell 环境校验
if (-not $PSVersionTable.PSVersion -or $PSVersionTable.PSVersion.Major -lt 3) {
    Write-Error "[ERROR] [FATAL] PowerShell 版本过低 (需要 3.0+)"; exit 1
}

# 5.3 权限检测
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$PRIVILEGE_MODE = if ($isAdmin) { 'full' } else { 'limited' }

# 5.4 初始化临时目录
Remove-Item -Recurse -Force .tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path .tmp, .tmp/code_backup, .tmp/config_backup, .tmp/logs, .tmp/test_results | Out-Null

# 5.5 磁盘空间智能预估（需要3倍源码空间）
$drive = (Get-Location).Drive.Name
$disk = Get-PSDrive -Name $drive
$sourceSize = (Get-ChildItem -Path . -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -notlike '*\.tmp*' -and $_.FullName -notlike '*\node_modules*' -and $_.FullName -notlike '*\__pycache__*' } |
    Measure-Object -Property Length -Sum).Sum
$estimatedNeed = if ($sourceSize -gt 0) { $sourceSize * 3 } else { 500MB }
$freeSpace = $disk.Free
if ($freeSpace -lt $estimatedNeed) {
    Write-Error "[ERROR] [FATAL] 磁盘空间不足 (需要: $([Math]::Round($estimatedNeed/1MB,1))MB, 可用: $([Math]::Round($freeSpace/1MB,1))MB)"; exit 1
}

# 5.6 依赖服务健康检查（如适用）
$healthStatus = 'SKIPPED'
if ($HealthUrl -ne '') {
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -Method GET -TimeoutSec 5
        if ($resp.StatusCode -eq 200) {
            $healthStatus = 'OK'
            Write-Output "[DEP_OK] 服务可达"
        }
    } catch {
        $healthStatus = 'DOWN'
        Write-Warning "[DEP_DOWN] 服务不可达: $_"
    }
}

# 5.7 双备份创建（主备份 + 辅备份）
$backupMethod = 'git_stash'
if (git rev-parse --git-dir 2>$null) {
    git stash push -m 'FIX前自动备份' 2>$null
} else {
    $backupMethod = 'file_copy'
    Copy-Item -Path . -Destination .tmp\code_backup\primary -Recurse -Force -Exclude '.tmp','node_modules','__pycache__','.git'
    Copy-Item -Path . -Destination .archive\pre-fix-backup\secondary -Recurse -Force -Exclude '.tmp','node_modules','__pycache__' -ErrorAction SilentlyContinue
}

# 5.8 生成 SHA256 校验文件
$checksums = @{}
Get-ChildItem -Path .tmp\code_backup\primary -Recurse -File -ErrorAction SilentlyContinue | ForEach-Object {
    $hash = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash
    $relPath = $_.FullName.Replace('.tmp\code_backup\primary\', '')
    $checksums[$relPath] = $hash
}
$checksums | ConvertTo-Json | Out-File -Encoding utf8 .tmp\code_backup\checksums.json

# 5.9 配置脱敏备份 + 依赖快照
$configFiles = Get-ChildItem -Path . -Recurse -Include *.json,*.config,*.env,*.ini -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notlike '*\.tmp*' -and $_.FullName -notlike '*\node_modules*' }
foreach ($file in $configFiles) {
    $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
    $desensitized = $content `
        -replace '(?i)(password|passwd|pwd)\s*[=:]\s*["'']?\w[^"'',\s}]*["'']?', '$1=***' `
        -replace '(?i)"(password|secret|key|token|api_key|auth_token)"\s*:\s*"[^"]*"', '"$1":"***"'
    $desensitized | Out-File -Encoding utf8 ".tmp/config_backup/$($file.Name)"
}
pip freeze > .tmp/deps_before.txt 2>$null

# 5.10 生成基线 JSON
$baseline = @{
    sop_version = '9.0'
    phase = 'FIX_START'
    privilege_mode = $PRIVILEGE_MODE
    disk_free_mb = [Math]::Round($freeSpace/1MB, 1)
    backup_primary = '.tmp/code_backup/primary'
    backup_secondary = '.archive/pre-fix-backup/secondary'
    checksum_count = $checksums.Count
    backup_method = $backupMethod
    health_status = $healthStatus
    exec_timestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
}
$baseline | ConvertTo-Json -Depth 4 | Out-File -Encoding utf8 .tmp\baseline.json

# 输出结构化结果
$result = @{
    status = 'COMPLETED'
    phase = 5
    privilege_mode = $PRIVILEGE_MODE
    disk_free_mb = [Math]::Round($freeSpace/1MB, 1)
    backup_method = $backupMethod
    health_status = $healthStatus
    checksum_count = $checksums.Count
    baseline_file = '.tmp/baseline.json'
}
Write-Output ($result | ConvertTo-Json -Depth 4)
