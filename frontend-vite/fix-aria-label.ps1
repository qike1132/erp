$srcPath = 'd:\erp_system\frontend-vite\src'
$excludePatterns = @('UiToast', 'UiUpload', 'UiProgressBar', 'UiProgress', 'DefaultLayout')

# Map of icon patterns to aria-labels
$iconLabelMap = @{
    'fa-times' = '关闭'
    'fa-xmark' = '关闭'
    'fa-trash' = '删除'
    'fa-trash-alt' = '删除'
    'fa-edit' = '编辑'
    'fa-pen' = '编辑'
    'fa-search' = '搜索'
    'fa-eye' = '查看'
    'fa-eye-slash' = '切换密码可见性'
    'fa-lock' = '切换状态'
    'fa-lock-open' = '切换状态'
    'fa-plus' = '添加'
    'fa-eraser' = '清除'
    'fa-redo' = '刷新'
    'fa-sync-alt' = '刷新'
    'fa-upload' = '上传'
    'fa-download' = '下载'
    'fa-chevron-left' = '上一页'
    'fa-chevron-right' = '下一页'
    'fa-angle-left' = '上一页'
    'fa-angle-right' = '下一页'
    'fa-angle-double-left' = '首页'
    'fa-angle-double-right' = '末页'
    'fa-undo-alt' = '恢复'
    'fa-cog' = '设置'
    'fa-filter' = '筛选'
    'fa-magic' = '审核'
    'fa-shield-alt' = '巡检'
    'fa-layer-group' = '批量'
    'fa-boxes-stacked' = '批量'
    'fa-clipboard-check' = '审核'
    'fa-hand-point-left' = '返回'
    'fa-chart-pie' = '统计'
    'fa-calculator' = '计算'
    'fa-file-export' = '导出'
}

$files = Get-ChildItem -Path $srcPath -Recurse -Filter '*.vue' | Where-Object {
    $fn = $_.FullName
    $exclude = $false
    foreach ($p in $excludePatterns) {
        if ($fn -match $p) { $exclude = $true; break }
    }
    -not $exclude
}

$totalChanges = 0

foreach ($file in $files) {
    $content = Get-Content $file.FullName -Raw -Encoding UTF8
    $originalContent = $content

    # Find icon-only buttons: <button ...> <i class="fas fa-xxx ..." /> </button>
    # or <button ...> <i :class="..." /> </button>
    # These have NO text content between <button> and </button> except whitespace and <i> tags

    # Pattern: <button ...> whitespace <i .../> whitespace </button>
    # We need to check that the button doesn't have text content and doesn't already have aria-label

    # Match button tags that contain only an <i> icon (no text)
    $pattern = '(?s)(<button\s[^>]*?)(>)(\s*<i\s[^>]*?/?>\s*)(</button>)'

    $matches = [regex]::Matches($content, $pattern)
    foreach ($m in $matches) {
        $buttonOpen = $m.Groups[1].Value
        $buttonClose1 = $m.Groups[2].Value
        $iconTag = $m.Groups[3].Value
        $buttonClose2 = $m.Groups[4].Value

        # Skip if button already has aria-label
        if ($buttonOpen -match 'aria-label') { continue }

        # Skip if button has text content (not just whitespace and <i> tags)
        # Check if there's any text between the <i> tag and </button> or before <i>
        $innerContent = $m.Groups[3].Value
        $textOnly = $innerContent -replace '<[^>]+>', '' -replace '\s', ''
        if ($textOnly -ne '') { continue }

        # Determine the aria-label based on the icon
        $label = $null
        foreach ($key in $iconLabelMap.Keys) {
            if ($iconTag -match [regex]::Escape($key)) {
                $label = $iconLabelMap[$key]
                break
            }
        }

        if ($label) {
            $replacement = "$buttonOpen aria-label=`"$label`"$buttonClose1$iconTag$buttonClose2"
            $content = $content.Replace($m.Value, $replacement)
            $totalChanges++
        }
    }

    # Also handle <button ...><i ...></i></button> pattern
    $pattern2 = '(?s)(<button\s[^>]*?)(>)(\s*<i\s[^>]*?>\s*</i>\s*)(</button>)'
    $matches2 = [regex]::Matches($content, $pattern2)
    foreach ($m in $matches2) {
        $buttonOpen = $m.Groups[1].Value
        $buttonClose1 = $m.Groups[2].Value
        $iconTag = $m.Groups[3].Value
        $buttonClose2 = $m.Groups[4].Value

        if ($buttonOpen -match 'aria-label') { continue }

        $innerContent = $m.Groups[3].Value
        $textOnly = $innerContent -replace '<[^>]+>', '' -replace '\s', ''
        if ($textOnly -ne '') { continue }

        $label = $null
        foreach ($key in $iconLabelMap.Keys) {
            if ($iconTag -match [regex]::Escape($key)) {
                $label = $iconLabelMap[$key]
                break
            }
        }

        if ($label) {
            $replacement = "$buttonOpen aria-label=`"$label`"$buttonClose1$iconTag$buttonClose2"
            $content = $content.Replace($m.Value, $replacement)
            $totalChanges++
        }
    }

    if ($content -ne $originalContent) {
        Set-Content -Path $file.FullName -Value $content -NoNewline -Encoding UTF8
        Write-Output "MODIFIED: $($file.FullName.Replace($srcPath + '\', ''))"
    }
}

Write-Output "`nTotal aria-label additions: $totalChanges"
Write-Output "Done."
