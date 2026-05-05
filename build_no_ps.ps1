# 禁用所有 PowerShell 集成
$env:VSCODE_SHELL_ENV_REPORTING = "0"
$env:TRAE_AI_SHELL_ID = ""
$env:PAGER = ""
$env:GIT_PAGER = ""
$env:LESS = ""

# 设置构建环境
$env:JAVA_HOME = "C:\Program Files\Java\jdk-17"
$env:ANDROID_HOME = "C:\Users\Administrator\AppData\Local\Android\Sdk"
$env:GRADLE_OPTS = "-Dorg.gradle.daemon=false -Dorg.gradle.console=plain"

# 切换到项目目录
Set-Location "d:\erp_system\android-app"

# 执行 Gradle 构建
& .\gradlew.bat assembleDebug --no-daemon --console=plain

# 检查构建结果
$apkPath = "d:\erp_system\android-app\app\build\outputs\apk\debug\app-debug.apk"
if (Test-Path $apkPath) {
    Write-Host "✅ 构建成功!" -ForegroundColor Green
    Write-Host "📦 APK: $apkPath"
    $size = (Get-Item $apkPath).Length / 1MB
    Write-Host "📊 大小: $([math]::Round($size, 1)) MB"
    
    # 复制到发布目录
    Copy-Item $apkPath "d:\erp_system\static\releases\erp-v1.2.apk" -Force
    Write-Host "✅ 已复制到发布目录" -ForegroundColor Green
} else {
    Write-Host "❌ 构建失败，APK 未生成" -ForegroundColor Red
}
