$ErrorActionPreference = 'SilentlyContinue'
$found = @()

# 1. py launcher
$py = Get-Command py.exe
if ($py) {
    Write-Host "py launcher: $($py.Source)"
    & $py.Source -3.12 --version
    if ($LASTEXITCODE -eq 0) { $found += 'py -3.12' }
}

# 2. python in PATH
$python = Get-Command python.exe
if ($python) {
    Write-Host "python: $($python.Source)"
    & $python.Source --version
    $found += $python.Source
}

# 3. common install locations
$candidates = @(
    "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
    "C:\Python312\python.exe",
    "C:\Program Files\Python312\python.exe",
    "$env:ProgramFiles\Python312\python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) {
        Write-Host "candidate: $c"
        & $c --version
        $found += $c
    }
}

Write-Host "`nFound $($found.Count) python candidates"
if ($found.Count -gt 0) { Write-Host "FIRST: $($found[0])" }
