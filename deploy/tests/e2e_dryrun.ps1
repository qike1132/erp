#Requires -Version 5.1
# 历史文件名仅为兼容；不执行构建/安装，也不读取真实配置、联网或连接数据库。
$ErrorActionPreference = 'Stop'
$deployDir = Split-Path $PSScriptRoot -Parent
foreach($name in @('_lib.ps1','build_package.ps1','install_package.ps1','tests\test_lib.ps1')){
  $tokens=$null; $errors=$null
  $path=Join-Path $deployDir $name
  [void][Management.Automation.Language.Parser]::ParseFile($path,[ref]$tokens,[ref]$errors)
  if($errors){ throw "PowerShell 解析失败：$path`n$($errors -join "`n")" }
  Write-Host "[PASS] PowerShell 语法：$name"
}
& (Join-Path $PSScriptRoot 'test_lib.ps1')
if($LASTEXITCODE){ exit $LASTEXITCODE }
Write-Host '隔离部署静态与辅助测试通过；未执行真实安装或构建。'
