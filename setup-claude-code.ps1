# Claude Code 快速配置脚本
# 用于将项目配置复制到用户目录

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Claude Code MiMo API 配置工具" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 获取用户目录
$userProfile = $env:USERPROFILE
$claudeDir = Join-Path $userProfile ".claude"

Write-Host "用户目录: $userProfile" -ForegroundColor Yellow
Write-Host "配置目录: $claudeDir" -ForegroundColor Yellow
Write-Host ""

# 创建 .claude 目录（如果不存在）
if (-not (Test-Path $claudeDir)) {
    Write-Host "创建目录: $claudeDir" -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path $claudeDir | Out-Null
} else {
    Write-Host "目录已存在: $claudeDir" -ForegroundColor Gray
}

# 复制 settings.json
$settingsSource = Join-Path $PSScriptRoot ".claude\settings.json"
$settingsDest = Join-Path $claudeDir "settings.json"

if (Test-Path $settingsSource) {
    Write-Host "复制: settings.json" -ForegroundColor Green
    Copy-Item $settingsSource $settingsDest -Force
} else {
    Write-Host "错误: 找不到 $settingsSource" -ForegroundColor Red
    exit 1
}

# 复制 .claude.json
$claudeJsonSource = Join-Path $PSScriptRoot ".claude.json"
$claudeJsonDest = Join-Path $userProfile ".claude.json"

if (Test-Path $claudeJsonSource) {
    Write-Host "复制: .claude.json" -ForegroundColor Green
    Copy-Item $claudeJsonSource $claudeJsonDest -Force
} else {
    Write-Host "警告: 找不到 $claudeJsonSource" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  配置完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "接下来请按以下步骤操作：" -ForegroundColor White
Write-Host "1. 完全关闭 VS Code" -ForegroundColor White
Write-Host "2. 重新打开 VS Code" -ForegroundColor White
Write-Host "3. 点击 Spark 图标 ✨ 打开 Claude Code" -ForegroundColor White
Write-Host "4. 在 Claude Code 中输入 /status 验证配置" -ForegroundColor White
Write-Host ""
Write-Host "按任意键退出..."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
