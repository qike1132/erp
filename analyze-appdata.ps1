$p = 'C:\Users\Administrator\AppData'
$t = (Get-ChildItem $p -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
Write-Host ('=== Total AppData: {0:N2} GB ===' -f ($t / 1GB))
$l = Join-Path $p 'Local'
$r = Join-Path $p 'Roaming'

Get-ChildItem $l -Directory -ErrorAction SilentlyContinue | Sort Length -Descending | Select-Object -First 30 | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
    Write-Host (' Local: {0,8:N1} MB {1}' -f ($s / 1MB), $_.Name)
}

# Analyze QoderWork subdirectories
Write-Host "=== QoderWork (1.3 GB) ==="
$qw = Join-Path $r 'QoderWork'
Get-ChildItem $qw -Directory -ErrorAction SilentlyContinue | Sort Length -Descending | Select-Object -First 15 | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
    Write-Host (' {0,8:N1} MB {1}' -f ($s / 1MB), $_.Name)
}

# Analyze npm subdirectories
Write-Host "=== npm (448 MB) ==="
$npm = Join-Path $r 'npm'
Get-ChildItem $npm -Directory -ErrorAction SilentlyContinue | Sort Length -Descending | Select-Object -First 15 | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
    Write-Host (' {0,8:N1} MB {1}' -f ($s / 1MB), $_.Name)
}

# Analyze Programs subdirectories
Write-Host "=== Programs (3.2 GB) ==="
$prog = Join-Path $l 'Programs'
Get-ChildItem $prog -Directory -ErrorAction SilentlyContinue | Sort Length -Descending | Select-Object -First 15 | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
    Write-Host (' {0,8:N1} MB {1}' -f ($s / 1MB), $_.Name)
}

# Analyze Packages
Write-Host "=== Packages (288 MB) ==="
$pkgs = Join-Path $l 'Packages'
Get-ChildItem $pkgs -Directory -ErrorAction SilentlyContinue | Sort Length -Descending | Select-Object -First 15 | ForEach-Object {
    $s = (Get-ChildItem $_.FullName -Recurse -ErrorAction SilentlyContinue -File | Measure-Object Length -Sum).Sum
    Write-Host (' {0,8:N1} MB {1}' -f ($s / 1MB), $_.Name)
}
