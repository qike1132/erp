$files = @(
    @{ path = 'd:\erp_system\frontend-vite\src\views\production\ProductionView.vue'; desc = 'ProductionView' },
    @{ path = 'd:\erp_system\frontend-vite\src\api\index.ts'; desc = 'api/index' },
    @{ path = 'd:\erp_system\frontend-vite\src\types\index.ts'; desc = 'types/index' },
    @{ path = 'd:\erp_system\frontend-vite\src\mobile\views\production\MProductionView.vue'; desc = 'MProductionView' }
)

foreach ($f in $files) {
    $filePath = $f.path
    $tempPath = $filePath + '.tmp'
    
    if (-not (Test-Path $filePath)) {
        Write-Output "SKIP: $($f.desc) - file not found"
        continue
    }
    
    $lines = [System.IO.File]::ReadAllLines($filePath, [System.Text.Encoding]::UTF8)
    $newLines = [System.Collections.ArrayList]::new()
    $skipNext = 0
    
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        
        if ($skipNext -gt 0) {
            $skipNext--
            continue
        }
        
        $trimmed = $line.Trim()
        
        # === ProductionView.vue specific ===
        
        # Skip packaging department entry
        if ($trimmed -like "*value:*'packaging'*label:*'包装部'*") {
            continue
        }
        
        # Skip packaging deptColors entry
        if ($trimmed -like "packaging:*") {
            if ($trimmed -like "*main:*" -and $trimmed -like "*gradient:*") {
                continue
            }
        }
        
        # Fix deptStats loop
        if ($line -like "*for (const dept of*packaging*") {
            $line = $line.Replace("'packaging', ", "")
        }
        
        # Fix chart legend
        if ($line -like "*legend*data*包装*") {
            $line = $line.Replace("'包装', ", "")
        }
        
        # Skip packaging series in monthly chart (name line + data line + itemStyle line)
        if ($trimmed -like "name:*'包装'*type:*'bar'*") {
            $skipNext = 2
            continue
        }
        
        # Skip <th>包装</th>
        if ($trimmed -eq '<th>包装</th>') {
            continue
        }
        
        # Skip {{ d.packaging.quantity }}
        if ($line -like "*d.packaging.quantity*") {
            continue
        }
        
        # Skip CSS with packaging
        if ($trimmed -like ".pr-dept-icon-packaging*") { continue }
        if ($trimmed -like ".pr-dept-packaging*") { continue }
        if ($trimmed -like ".pr-dept-tag-packaging*") { continue }
        if ($trimmed -like ".pr-dept-btn-packaging*") { continue }
        
        # === api/index.ts specific ===
        
        # Skip packaging API lines
        if ($trimmed -like "packaging:*" -and $trimmed -like "*production-summary/packaging*") {
            continue
        }
        if ($trimmed -like "createPackaging:*" -and $trimmed -like "*packaging/create*") {
            continue
        }
        if ($trimmed -like "editPackaging:*" -and $trimmed -like "*packaging/edit*") {
            continue
        }
        if ($trimmed -like "deletePackaging:*" -and $trimmed -like "*packaging/delete*") {
            continue
        }
        
        # === types/index.ts specific ===
        
        # Skip packaging in MonthlyDayData
        if ($trimmed -like "packaging:*" -and $trimmed -like "*quantity*") {
            continue
        }
        
        # === MProductionView.vue specific ===
        
        # Skip packaging department in computed
        if ($trimmed -like "*key:*'packaging'*name:*'包装部'*") {
            continue
        }
        
        [void]$newLines.Add($line)
    }
    
    # Write using Copy instead of Move
    [System.IO.File]::WriteAllLines($tempPath, $newLines, (New-Object System.Text.UTF8Encoding $false))
    Copy-Item -Path $tempPath -Destination $filePath -Force
    Remove-Item -Path $tempPath -Force
    Write-Output "$($f.desc) updated. Lines: $($newLines.Count)"
}
