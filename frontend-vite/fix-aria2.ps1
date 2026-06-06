$srcPath = 'd:\erp_system\frontend-vite\src'
$excludePatterns = @('UiToast', 'UiUpload', 'UiProgressBar', 'UiProgress', 'DefaultLayout')

$files = Get-ChildItem -Path $srcPath -Recurse -Filter '*.vue' | Where-Object {
    $fn = $_.FullName
    $exclude = $false
    foreach ($p in $excludePatterns) {
        if ($fn -match $p) { $exclude = $true; break }
    }
    -not $exclude
}

foreach ($file in $files) {
    $lines = Get-Content $file.FullName -Encoding UTF8
    $modified = $false
    $newLines = @()

    foreach ($line in $lines) {
        $newLine = $line

        # Check if line has <i class="fas or <i :class= without aria-hidden
        if (($line -match '<i\s+class="fas\s' -or $line -match '<i\s+:class=') -and $line -notmatch 'aria-hidden') {
            # Add aria-hidden="true" before the closing /> or >
            # Handle self-closing: ... />
            if ($newLine -match '<i\s+[^>]*class="fas\s[^"]*"[^/]*/>') {
                $newLine = $newLine -replace '/>', ' aria-hidden="true" />'
            }
            # Handle self-closing with space: ... / >
            elseif ($newLine -match '<i\s+[^>]*class="fas\s[^"]*"[^/]*/\s*>') {
                $newLine = $newLine -replace '/\s*>', ' aria-hidden="true" />'
            }
            # Handle <i :class=... />
            elseif ($newLine -match '<i\s+:class="[^"]*"[^/]*/>') {
                $newLine = $newLine -replace '/>', ' aria-hidden="true" />'
            }
            # Handle <i :class=[...] />
            elseif ($newLine -match '<i\s+:class="\[[^\]]*\]"[^/]*/>') {
                $newLine = $newLine -replace '/>', ' aria-hidden="true" />'
            }
            # Handle closing tag: ... ></i>
            elseif ($newLine -match '<i\s+[^>]*class="fas\s[^"]*"[^>]*></i>') {
                $newLine = $newLine -replace '></i>', ' aria-hidden="true"></i>'
            }
            # Handle <i :class=... ></i>
            elseif ($newLine -match '<i\s+:class="[^"]*"[^>]*></i>') {
                $newLine = $newLine -replace '></i>', ' aria-hidden="true"></i>'
            }
            # Handle <i :class=[...] ></i>
            elseif ($newLine -match '<i\s+:class="\[[^\]]*\]"[^>]*></i>') {
                $newLine = $newLine -replace '></i>', ' aria-hidden="true"></i>'
            }
            # Handle <i class="fas ..."> with content after
            elseif ($newLine -match '<i\s+class="fas\s[^"]*"[^>]*>') {
                $newLine = $newLine -replace '>', ' aria-hidden="true">', 1
            }
            # Handle <i :class=... >
            elseif ($newLine -match '<i\s+:class="[^"]*"[^>]*>') {
                $newLine = $newLine -replace '>', ' aria-hidden="true">', 1
            }
        }

        if ($newLine -ne $line) { $modified = $true }
        $newLines += $newLine
    }

    if ($modified) {
        Set-Content -Path $file.FullName -Value $newLines -Encoding UTF8
        Write-Output "MODIFIED: $($file.FullName.Replace($srcPath + '\', ''))"
    }
}

Write-Output "`nDone."
