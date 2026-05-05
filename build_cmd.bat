@echo off
chcp 65001 >nul
echo ============================================
echo ERP APK 构建脚本 (CMD 模式)
echo ============================================

REM 设置环境变量
set JAVA_HOME=C:\Program Files\Java\jdk-17
set ANDROID_HOME=C:\Users\Administrator\AppData\Local\Android\Sdk
set GRADLE_OPTS=-Dorg.gradle.daemon=false -Dorg.gradle.console=plain

cd /d "d:\erp_system\android-app"

echo.
echo [1/3] 清理旧构建...
call gradlew.bat clean --no-daemon --console=plain

echo.
echo [2/3] 构建 Debug APK...
call gradlew.bat assembleDebug --no-daemon --console=plain

echo.
echo [3/3] 检查构建结果...
if exist "app\build\outputs\apk\debug\app-debug.apk" (
    echo ✅ 构建成功!
    echo 📦 APK: app\build\outputs\apk\debug\app-debug.apk
    for %%F in ("app\build\outputs\apk\debug\app-debug.apk") do (
        echo 📊 大小: %%~zF bytes
    )
    
    echo.
    echo [4/4] 复制到发布目录...
    copy /Y "app\build\outputs\apk\debug\app-debug.apk" "d:\erp_system\static\releases\erp-v1.2.apk"
    echo ✅ 已复制到: d:\erp_system\static\releases\erp-v1.2.apk
) else (
    echo ❌ 构建失败，APK 未生成
)

echo.
echo ============================================
pause
