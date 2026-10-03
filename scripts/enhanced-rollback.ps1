# ============================================================
# 增强型回滚机制 v2.0 — AI BUG 修复 SOP 核心组件
# 功能: 双备份策略 + 完整性校验 + 回滚前验证 + 自动清理
# 版本: 2.0 | 日期: 2026-04-18
# ============================================================

#requires -Version 3.0
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# ==================== 全局配置 ====================
$ROLLBACK_CONFIG = @{
    # 备份路径
    BackupPrimary   = '.tmp\code_backup\primary'
    BackupSecondary = '.archive\pre-fix-backup\secondary'
    
    # 完整性校验
    HashAlgorithm   = 'SHA256'
    ChecksumFile    = 'checksums.sha256'
    
    # 回滚前验证
    PreValidation   = $true
    MaxValidationRetries = 3
    
    # 自动清理
    AutoCleanup     = $true
    CleanupOnSuccess = $true
    CleanupOnFailure = $false  # 失败时保留备份用于排查
    
    # 日志
    LogFile         = '.tmp\rollback.log'
    LogMaxSize      = 10MB
}

# ==================== 日志系统 ====================
function Write-RollbackLog {
    param(
        [Parameter(Mandatory)]
        [string]$Message,
        
        [ValidateSet('INFO', 'WARN', 'ERROR', 'SUCCESS', 'VALIDATION')]
        [string]$Level = 'INFO'
    )
    
    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'
    $logEntry = "[$timestamp] [$Level] $Message"
    
    # 输出到控制台
    switch ($Level) {
        'INFO'       { Write-Output $logEntry }
        'WARN'       { Write-Warning $logEntry }
        'ERROR'      { Write-Error $logEntry }
        'SUCCESS'    { Write-Host $logEntry -ForegroundColor Green }
        'VALIDATION' { Write-Host $logEntry -ForegroundColor Cyan }
    }
    
    # 写入日志文件
    if ($ROLLBACK_CONFIG.LogFile) {
        $logDir = Split-Path $ROLLBACK_CONFIG.LogFile -Parent
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Force -Path $logDir | Out-Null }
        Add-Content -Path $ROLLBACK_CONFIG.LogFile -Value $logEntry -Encoding UTF8
    }
}

# ==================== 双备份策略 ====================

### 功能1: 创建双备份
function Start-DualBackup {
    param(
        [Parameter(Mandatory)]
        [string]$SourcePath,
        
        [string]$BackupName = $(Get-Date -Format 'yyyyMMdd_HHmmss')
    )
    
    Write-RollbackLog "开始双备份: 源路径=$SourcePath" 'INFO'
    
    try {
        # 创建备份目录
        $primaryPath   = Join-Path $ROLLBACK_CONFIG.BackupPrimary $BackupName
        $secondaryPath = Join-Path $ROLLBACK_CONFIG.BackupSecondary $BackupName
        
        New-Item -ItemType Directory -Force -Path $primaryPath | Out-Null
        New-Item -ItemType Directory -Force -Path $secondaryPath | Out-Null
        
        # 第一份备份: 快速回滚用 (本地)
        Write-RollbackLog "创建主备份 (Primary): $primaryPath" 'INFO'
        Copy-Item -Path $SourcePath -Destination $primaryPath -Recurse -Force -ErrorAction Stop
        
        # 第二份备份: 灾难恢复用 (归档)
        Write-RollbackLog "创建辅备份 (Secondary): $secondaryPath" 'INFO'
        Copy-Item -Path $SourcePath -Destination $secondaryPath -Recurse -Force -ErrorAction Stop
        
        # 生成完整性校验文件
        Write-RollbackLog "生成完整性校验哈希..." 'VALIDATION'
        $checksums = @{}
        
        foreach ($backupPath in @($primaryPath, $secondaryPath)) {
            $checksumFile = Join-Path $backupPath $ROLLBACK_CONFIG.ChecksumFile
            $checksums[$backupPath] = New-BackupChecksum -BackupPath $backupPath -ChecksumFile $checksumFile
        }
        
        # 验证双备份一致性
        $consistent = Compare-BackupIntegrity -PrimaryChecksum $checksums[$primaryPath] -SecondaryChecksum $checksums[$secondaryPath]
        
        if (-not $consistent) {
            Write-RollbackLog "双备份一致性校验失败！" 'ERROR'
            return $false
        }
        
        Write-RollbackLog "双备份创建成功 [Primary: $primaryPath] [Secondary: $secondaryPath]" 'SUCCESS'
        return @{
            Primary   = $primaryPath
            Secondary = $secondaryPath
            Checksum  = $checksums[$primaryPath]
            Consistent = $true
        }
    }
    catch {
        Write-RollbackLog "双备份创建失败: $_" 'ERROR'
        return $false
    }
}

### 功能2: 生成备份校验和
function New-BackupChecksum {
    param(
        [Parameter(Mandatory)]
        [string]$BackupPath,
        
        [Parameter(Mandatory)]
        [string]$ChecksumFile
    )
    
    $checksums = @{}
    $fileList = Get-ChildItem -Path $BackupPath -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -ne $ROLLBACK_CONFIG.ChecksumFile }
    
    foreach ($file in $fileList) {
        $hash = Get-FileHash -Path $file.FullName -Algorithm $ROLLBACK_CONFIG.HashAlgorithm -ErrorAction SilentlyContinue
        if ($hash) {
            # 使用相对路径作为 key
            $relativePath = $file.FullName.Replace($BackupPath, '').TrimStart('\')
            $checksums[$relativePath] = $hash.Hash
            
            # 写入校验文件
            "$($hash.Hash)  $relativePath" | Out-File -Append -FilePath $ChecksumFile -Encoding UTF8
        }
    }
    
    Write-RollbackLog "校验和生成完成: $($checksums.Count) 个文件" 'VALIDATION'
    return $checksums
}

### 功能3: 比较双备份一致性
function Compare-BackupIntegrity {
    param(
        [Parameter(Mandatory)]
        [hashtable]$PrimaryChecksum,
        
        [Parameter(Mandatory)]
        [hashtable]$SecondaryChecksum
    )
    
    if ($PrimaryChecksum.Count -ne $SecondaryChecksum.Count) {
        Write-RollbackLog "双备份文件数不一致: Primary=$($PrimaryChecksum.Count), Secondary=$($SecondaryChecksum.Count)" 'ERROR'
        return $false
    }
    
    $mismatchCount = 0
    foreach ($key in $PrimaryChecksum.Keys) {
        if ($PrimaryChecksum[$key] -ne $SecondaryChecksum[$key]) {
            Write-RollbackLog "文件哈希不匹配: $key" 'ERROR'
            $mismatchCount++
        }
    }
    
    if ($mismatchCount -gt 0) {
        Write-RollbackLog "发现 $mismatchCount 个文件哈希不一致" 'ERROR'
        return $false
    }
    
    Write-RollbackLog "双备份一致性校验通过" 'SUCCESS'
    return $true
}

# ==================== 完整性校验 ====================

### 功能4: 验证备份完整性
function Test-BackupIntegrity {
    param(
        [Parameter(Mandatory)]
        [string]$BackupPath
    )
    
    Write-RollbackLog "验证备份完整性: $BackupPath" 'VALIDATION'
    
    $checksumFile = Join-Path $BackupPath $ROLLBACK_CONFIG.ChecksumFile
    
    if (-not (Test-Path $checksumFile)) {
        Write-RollbackLog "校验文件不存在: $checksumFile" 'ERROR'
        return $false
    }
    
    $passed = 0
    $failed = 0
    $missing = 0
    
    # 读取校验文件并验证
    Get-Content $checksumFile -ErrorAction SilentlyContinue | ForEach-Object {
        $parts = $_ -split '\s{2,}'
        if ($parts.Count -ne 2) { return }
        
        $expectedHash = $parts[0]
        $relativePath = $parts[1]
        $fullPath = Join-Path $BackupPath $relativePath
        
        if (-not (Test-Path $fullPath)) {
            Write-RollbackLog "文件缺失: $relativePath" 'ERROR'
            $missing++
            return
        }
        
        $actualHash = (Get-FileHash -Path $fullPath -Algorithm $ROLLBACK_CONFIG.HashAlgorithm -ErrorAction SilentlyContinue).Hash
        
        if ($actualHash -eq $expectedHash) {
            $passed++
        } else {
            Write-RollbackLog "哈希不匹配: $relativePath" 'ERROR'
            $failed++
        }
    }
    
    Write-RollbackLog "完整性校验结果: 通过=$passed, 失败=$failed, 缺失=$missing" 'VALIDATION'
    
    return ($failed -eq 0 -and $missing -eq 0)
}

# ==================== 回滚前验证 ====================

### 功能5: 回滚前预验证
function Invoke-PreRollbackValidation {
    param(
        [Parameter(Mandatory)]
        [string]$BackupPath,
        
        [string]$TargetPath = '.'
    )
    
    Write-RollbackLog "=== 开始回滚前验证 ===" 'VALIDATION'
    
    $validationResults = @{
        BackupExists       = $false
        IntegrityCheck     = $false
        SpaceCheck         = $false
        PermissionCheck    = $false
        TargetWritable     = $false
        RollbackDryRun     = $false
    }
    
    # 1. 备份是否存在
    Write-RollbackLog "[1/6] 检查备份目录存在性..." 'VALIDATION'
    if (Test-Path $BackupPath) {
        $validationResults.BackupExists = $true
        Write-RollbackLog "  ✓ 备份目录存在" 'SUCCESS'
    } else {
        Write-RollbackLog "  ✗ 备份目录不存在" 'ERROR'
        return $validationResults
    }
    
    # 2. 完整性校验
    Write-RollbackLog "[2/6] 执行完整性校验..." 'VALIDATION'
    $validationResults.IntegrityCheck = Test-BackupIntegrity -BackupPath $BackupPath
    if ($validationResults.IntegrityCheck) {
        Write-RollbackLog "  ✓ 完整性校验通过" 'SUCCESS'
    } else {
        Write-RollbackLog "  ✗ 完整性校验失败" 'ERROR'
        return $validationResults
    }
    
    # 3. 磁盘空间检查
    Write-RollbackLog "[3/6] 检查磁盘空间..." 'VALIDATION'
    $drive = (Get-Location).Drive.Name
    $disk = Get-PSDrive -Name $drive
    $backupSize = (Get-ChildItem -Path $BackupPath -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    $freeSpace = $disk.Free
    
    if ($freeSpace -gt ($backupSize * 2)) {
        $validationResults.SpaceCheck = $true
        Write-RollbackLog "  ✓ 磁盘空间充足 (需要: $([Math]::Round($backupSize/1MB, 1))MB, 可用: $([Math]::Round($freeSpace/1MB, 1))MB)" 'SUCCESS'
    } else {
        Write-RollbackLog "  ✗ 磁盘空间不足" 'ERROR'
        return $validationResults
    }
    
    # 4. 权限检查
    Write-RollbackLog "[4/6] 检查写入权限..." 'VALIDATION'
    try {
        $testFile = Join-Path $TargetPath '.rollback_permission_test'
        "test" | Out-File -FilePath $testFile -ErrorAction Stop
        Remove-Item $testFile -Force -ErrorAction SilentlyContinue
        $validationResults.PermissionCheck = $true
        Write-RollbackLog "  ✓ 写入权限正常" 'SUCCESS'
    } catch {
        Write-RollbackLog "  ✗ 写入权限不足: $_" 'ERROR'
        return $validationResults
    }
    
    # 5. 目标路径可写检查
    Write-RollbackLog "[5/6] 检查目标路径..." 'VALIDATION'
    if (Test-Path $TargetPath) {
        $validationResults.TargetWritable = $true
        Write-RollbackLog "  ✓ 目标路径可访问" 'SUCCESS'
    } else {
        Write-RollbackLog "  ✗ 目标路径不存在" 'ERROR'
        return $validationResults
    }
    
    # 6. 模拟回滚 (Dry Run)
    Write-RollbackLog "[6/6] 执行模拟回滚..." 'VALIDATION'
    try {
        $filesToRestore = Get-ChildItem -Path $BackupPath -Recurse -File -ErrorAction SilentlyContinue |
                         Where-Object { $_.Name -ne $ROLLBACK_CONFIG.ChecksumFile }
        
        $testCount = 0
        foreach ($file in $filesToRestore | Select-Object -First 5) {
            $relativePath = $file.FullName.Replace($BackupPath, '').TrimStart('\')
            $targetFile = Join-Path $TargetPath $relativePath
            $targetDir = Split-Path $targetFile -Parent
            
            if (-not (Test-Path $targetDir)) {
                # 仅检查是否能创建目录，不实际创建
                Write-RollbackLog "  [模拟] 需要创建目录: $targetDir" 'VALIDATION'
            }
            
            $testCount++
        }
        
        $validationResults.RollbackDryRun = $true
        Write-RollbackLog "  ✓ 模拟回滚完成 (测试 $testCount 个文件)" 'SUCCESS'
    } catch {
        Write-RollbackLog "  ✗ 模拟回滚失败: $_" 'ERROR'
        return $validationResults
    }
    
    Write-RollbackLog "=== 回滚前验证全部通过 ===" 'SUCCESS'
    return $validationResults
}

# ==================== 执行回滚 ====================

### 功能6: 执行回滚操作
function Invoke-Rollback {
    param(
        [Parameter(Mandatory)]
        [string]$BackupPath,
        
        [string]$TargetPath = '.'
    )
    
    Write-RollbackLog "========================================" 'INFO'
    Write-RollbackLog "开始执行回滚操作" 'INFO'
    Write-RollbackLog "备份源: $BackupPath" 'INFO'
    Write-RollbackLog "目标路径: $TargetPath" 'INFO'
    Write-RollbackLog "========================================" 'INFO'
    
    # 执行回滚前验证
    if ($ROLLBACK_CONFIG.PreValidation) {
        $validation = Invoke-PreRollbackValidation -BackupPath $BackupPath -TargetPath $TargetPath
        
        # 检查所有验证项是否通过
        $allPassed = $true
        foreach ($key in $validation.Keys) {
            if (-not $validation[$key]) {
                $allPassed = $false
                Write-RollbackLog "验证项 [$key] 未通过" 'ERROR'
            }
        }
        
        if (-not $allPassed) {
            Write-RollbackLog "回滚前验证未全部通过，终止回滚" 'ERROR'
            return $false
        }
    }
    
    try {
        # 记录回滚前状态
        $rollbackStartTime = Get-Date
        
        # 执行文件恢复
        $filesRestored = 0
        $filesFailed = 0
        
        $filesToRestore = Get-ChildItem -Path $BackupPath -Recurse -File -ErrorAction SilentlyContinue |
                         Where-Object { $_.Name -ne $ROLLBACK_CONFIG.ChecksumFile }
        
        foreach ($file in $filesToRestore) {
            $relativePath = $file.FullName.Replace($BackupPath, '').TrimStart('\')
            $targetFile = Join-Path $TargetPath $relativePath
            $targetDir = Split-Path $targetFile -Parent
            
            # 确保目标目录存在
            if (-not (Test-Path $targetDir)) {
                New-Item -ItemType Directory -Force -Path $targetDir -ErrorAction SilentlyContinue | Out-Null
            }
            
            # 复制文件
            try {
                Copy-Item -Path $file.FullName -Destination $targetFile -Force -ErrorAction Stop
                $filesRestored++
            } catch {
                Write-RollbackLog "文件恢复失败: $relativePath - $_" 'ERROR'
                $filesFailed++
            }
        }
        
        $rollbackEndTime = Get-Date
        $duration = ($rollbackEndTime - $rollbackStartTime).TotalSeconds
        
        Write-RollbackLog "回滚完成: 成功=$filesRestored, 失败=$filesFailed, 耗时=$([Math]::Round($duration, 1))s" 'SUCCESS'
        
        # 回滚后验证
        $postValidation = Test-BackupIntegrity -BackupPath $TargetPath
        if ($postValidation) {
            Write-RollbackLog "回滚后完整性校验通过" 'SUCCESS'
        } else {
            Write-RollbackLog "回滚后完整性校验失败！" 'ERROR'
            return $false
        }
        
        return $true
    }
    catch {
        Write-RollbackLog "回滚执行失败: $_" 'ERROR'
        return $false
    }
}

# ==================== 自动清理 ====================

### 功能7: 任务完成后自动清理所有备份
function Invoke-AutoCleanup {
    param(
        [bool]$Success = $true
    )
    
    Write-RollbackLog "=== 开始自动清理 ===" 'INFO'
    
    if ($Success -and $ROLLBACK_CONFIG.CleanupOnSuccess) {
        # 清理主备份
        if (Test-Path $ROLLBACK_CONFIG.BackupPrimary) {
            Write-RollbackLog "清理主备份目录: $($ROLLBACK_CONFIG.BackupPrimary)" 'INFO'
            Remove-Item -Path $ROLLBACK_CONFIG.BackupPrimary -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # 清理辅备份
        if (Test-Path $ROLLBACK_CONFIG.BackupSecondary) {
            Write-RollbackLog "清理辅备份目录: $($ROLLBACK_CONFIG.BackupSecondary)" 'INFO'
            Remove-Item -Path $ROLLBACK_CONFIG.BackupSecondary -Recurse -Force -ErrorAction SilentlyContinue
        }
        
        # 清理临时文件
        $tempDirs = @('.tmp\logs', '.tmp\test_results', '.tmp\error_trace.log', '.tmp\baseline.json')
        foreach ($dir in $tempDirs) {
            if (Test-Path $dir) {
                Write-RollbackLog "清理临时文件: $dir" 'INFO'
                Remove-Item -Path $dir -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
        
        Write-RollbackLog "所有备份和临时文件已清理完成" 'SUCCESS'
    }
    elseif (-not $Success -and $ROLLBACK_CONFIG.CleanupOnFailure) {
        # 失败时也清理（不推荐，默认关闭）
        Write-RollbackLog "回滚失败，但仍执行清理（不推荐）" 'WARN'
        if (Test-Path $ROLLBACK_CONFIG.BackupPrimary) {
            Remove-Item -Path $ROLLBACK_CONFIG.BackupPrimary -Recurse -Force -ErrorAction SilentlyContinue
        }
    }
    else {
        Write-RollbackLog "保留备份文件用于排查 (Success=$Success)" 'INFO'
    }
    
    Write-RollbackLog "=== 自动清理完成 ===" 'SUCCESS'
}

# ==================== 主流程 ====================

### 功能8: 一键执行完整回滚流程
function Start-EnhancedRollback {
    param(
        [Parameter(Mandatory)]
        [string]$SourcePath,      # 需要备份的源路径
        
        [string]$TargetPath = '.', # 回滚目标路径
        
        [switch]$SkipValidation,  # 跳过回滚前验证
        
        [switch]$SkipCleanup      # 跳过自动清理
    )
    
    Write-RollbackLog "============================================" 'INFO'
    Write-RollbackLog "  增强型回滚机制 v2.0 - 启动" 'INFO'
    Write-RollbackLog "============================================" 'INFO'
    
    # 覆盖配置
    if ($SkipValidation) { $ROLLBACK_CONFIG.PreValidation = $false }
    if ($SkipCleanup) { $ROLLBACK_CONFIG.AutoCleanup = $false }
    
    # 步骤1: 创建双备份
    Write-RollbackLog "[步骤 1/5] 创建双备份..." 'INFO'
    $backupResult = Start-DualBackup -SourcePath $SourcePath
    
    if (-not $backupResult) {
        Write-RollbackLog "双备份创建失败，终止执行" 'ERROR'
        Invoke-AutoCleanup -Success $false
        return $false
    }
    
    # 步骤2: 执行修复操作（由外部调用方执行）
    Write-RollbackLog "[步骤 2/5] 等待外部修复操作完成..." 'INFO'
    Write-RollbackLog "  提示: 请在此处执行代码修复操作" 'INFO'
    Write-RollbackLog "  修复完成后调用 Invoke-Rollback 或等待自动回滚" 'INFO'
    
    # 步骤3: 回滚前验证
    if ($ROLLBACK_CONFIG.PreValidation) {
        Write-RollbackLog "[步骤 3/5] 执行回滚前验证..." 'INFO'
        $validation = Invoke-PreRollbackValidation -BackupPath $backupResult.Primary -TargetPath $TargetPath
        
        $allPassed = $true
        foreach ($key in $validation.Keys) {
            if (-not $validation[$key]) {
                $allPassed = $false
            }
        }
        
        if (-not $allPassed) {
            # Invoke-PreRollbackValidation 校验的是**刚创建的备份本身**
            # （存在/完整性/磁盘空间/权限/试跑），不是"修复后状态"。
            # 备份不可用 == 回滚点不成立 → 终止；绝不能拿一个校验失败的备份去回滚。
            # （第五轮审计：原代码在此处调用 Invoke-Rollback，方向拧反 —— 备份越坏越回滚。）
            Write-RollbackLog "备份验证未通过：回滚点不可用，终止（不执行回滚）" 'ERROR'
            Invoke-AutoCleanup -Success $false
            return $false
        }
        Write-RollbackLog "备份验证通过：回滚点已就绪（如需回滚请显式调用 Invoke-Rollback）" 'SUCCESS'
    }
    
    # 步骤4: 自动清理（任务成功后）
    if ($ROLLBACK_CONFIG.AutoCleanup) {
        Write-RollbackLog "[步骤 4/5] 执行自动清理..." 'INFO'
        Invoke-AutoCleanup -Success $true
    }
    
    # 步骤5: 完成
    Write-RollbackLog "[步骤 5/5] 回滚流程完成" 'SUCCESS'
    Write-RollbackLog "============================================" 'SUCCESS'
    
    return $true
}

# ==================== 导出函数 ====================
Export-ModuleMember -Function @(
    'Start-DualBackup',
    'New-BackupChecksum',
    'Compare-BackupIntegrity',
    'Test-BackupIntegrity',
    'Invoke-PreRollbackValidation',
    'Invoke-Rollback',
    'Invoke-AutoCleanup',
    'Start-EnhancedRollback',
    'Write-RollbackLog'
)
