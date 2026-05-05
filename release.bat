@echo off
chcp 65001 >nul
echo ==========================================
echo   ERP APK 一键打包发布
echo ==========================================
echo.

if "%1"=="" (
    set BUMP=minor
) else (
    set BUMP=%1
)

if "%2"=="" (
    set CHANGELOG=日常版本更新
) else (
    set CHANGELOG=%2
)

echo 版本递增级别: %BUMP%
echo 更新日志: %CHANGELOG%
echo.

python scripts\build_and_release.py --bump %BUMP% --changelog "%CHANGELOG%"

echo.
echo 上传完成，版本处于「待发布」状态
echo 请在管理页面点击「发布」按钮: http://192.168.0.95:3000/app-update
echo.
pause
