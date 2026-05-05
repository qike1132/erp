@echo off
echo ========================================
echo 构建 1.3 版本 APK
echo ========================================
chcp 65001>nul
cd /d "d:\erp_system\android-app"
echo.
echo [1/2] 清理旧构建...
call gradlew.bat clean --no-daemon --console=plain
echo.
echo [2/2] 构建 Debug APK...
call gradlew.bat assembleDebug --no-daemon --console=plain
echo.
echo ========================================
echo 检查构建结果...
if exist "app\build\outputs\apk\debug\app-debug.apk" (
    echo ✅ APK 构建成功！
    echo.
    echo 复制到发布目录...
    copy /Y "app\build\outputs\apk\debug\app-debug.apk" "d:\erp_system\static\releases\erp-v1.3.apk"
    echo ✅ 完成！
    echo.
    echo APK 位置：
    echo - 构建目录: app\build\outputs\apk\debug\app-debug.apk
    echo - 发布目录: d:\erp_system\static\releases\erp-v1.3.apk
) else (
    echo ❌ APK 构建失败！
)
echo.
pause
