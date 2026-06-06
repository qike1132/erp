$srcPath = 'd:\erp_system\frontend-vite\src'
$excludePatterns = @('UiToast', 'UiUpload', 'UiProgressBar', 'UiProgress', 'DefaultLayout')

Get-ChildItem -Path $srcPath -Recurse -Filter '*.vue' | Where-Object {
    $fn = $_.FullName
    $exclude = $false
    foreach ($p in $excludePatterns) {
        if ($fn -match $p) { $exclude = $true; break }
    }
    -not $exclude
} | ForEach-Object {
    $content = Get-Content $_.FullName -Raw -Encoding UTF8
    $modified = $false

    # Fix 1: Add aria-hidden="true" to <i class="fas ..."> without aria-hidden
    # Pattern: <i class="fas ..."/> or <i class="fas ..."></i> without aria-hidden
    $newContent = $content -replace '(<i\s+class="fas\s+[^"]*"(?:\s+[^>]*?)?)((?:\s*/)?>)', {
        param($match)
        $before = $match.Groups[1].Value
        $after = $match.Groups[2].Value
        if ($before -match 'aria-hidden') {
            return $match.Value
        }
        $modified = $true
        return $before + ' aria-hidden="true"' + $after
    }

    # Fix 1b: Add aria-hidden="true" to <i :class=...> without aria-hidden
    $newContent = $newContent -replace '(<i\s+:class="[^"]*"(?:\s+[^>]*?)?)((?:\s*/)?>)', {
        param($match)
        $before = $match.Groups[1].Value
        $after = $match.Groups[2].Value
        if ($before -match 'aria-hidden') {
            return $match.Value
        }
        $modified = $true
        return $before + ' aria-hidden="true"' + $after
    }

    # Fix 1c: Add aria-hidden="true" to <i :class=[...]> without aria-hidden
    $newContent = $newContent -replace '(<i\s+:class="\[[^\]]*\]"(?:\s+[^>]*?)?)((?:\s*/)?>)', {
        param($match)
        $before = $match.Groups[1].Value
        $after = $match.Groups[2].Value
        if ($before -match 'aria-hidden') {
            return $match.Value
        }
        $modified = $true
        return $before + ' aria-hidden="true"' + $after
    }

    if ($modified -and ($newContent -ne $content)) {
        Set-Content -Path $_.FullName -Value $newContent -NoNewline -Encoding UTF8
        Write-Output "MODIFIED: $($_.FullName.Replace($srcPath + '\', ''))"
    }
}

Write-Output "`nDone with aria-hidden fixes."
