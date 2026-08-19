$ErrorActionPreference = 'Stop'

$python = 'C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe'
$baseReq = 'd:\erp_system\requirements\base.txt'
$desktop = [Environment]::GetFolderPath('Desktop')
$wheelsDir = Join-Path $desktop 'erp_wheels_py312_win64'
$zipPath = Join-Path $desktop 'erp_python_deps_py312_win64.zip'

if (Test-Path $wheelsDir) { Remove-Item $wheelsDir -Recurse -Force }
New-Item -ItemType Directory -Force -Path $wheelsDir | Out-Null
Write-Host "[1/3] 目标: Python 3.12 / Windows x64"
Write-Host "      下载目录: $wheelsDir"

Write-Host "`n[2/3] 开始下载全部依赖 (含传递依赖)，请耐心等待..."
& $python -m pip download `
    -r $baseReq `
    -d $wheelsDir `
    --only-binary=:all: `
    --platform win_amd64 `
    --python-version 3.12 `
    --implementation cp `
    --no-cache-dir `
    2>&1 | Select-Object -Last 15 | ForEach-Object { Write-Host "  $_" }

if ($LASTEXITCODE -ne 0) {
    Write-Host "`n[FAIL] pip download 失败 (exit=$LASTEXITCODE)" -ForegroundColor Red
    exit 1
}

$files = Get-ChildItem $wheelsDir -File
$totalMB = [math]::Round(($files | Measure-Object Length -Sum).Sum / 1MB, 2)
Write-Host "`n下载完成: $($files.Count) 个文件, $totalMB MB" -ForegroundColor Green

Write-Host "`n[3/3] 打包 zip..."
if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Compress-Archive -Path $wheelsDir -DestinationPath $zipPath -CompressionLevel Optimal
$zipMB = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "已打包: $zipPath ($zipMB MB)" -ForegroundColor Green

Write-Host "`n--- 依赖清单 ---"
$files | Sort-Object Name | ForEach-Object { Write-Host "  $($_.Name)" }
