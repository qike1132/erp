@echo off
chcp 65001 >nul
echo ========================================
echo  ERP 服务器管理器 v8 GUI 打包脚本
echo ========================================
echo.
echo 产物：dist\server_manager_v8.exe（与 v6 ERP_System.exe 并存）
echo.

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python
    pause & exit /b 1
)

REM 安装/校验 PyInstaller
python -m pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo [步骤] 安装 PyInstaller...
    python -m pip install pyinstaller
)

REM 校验 pywebview（v8 GUI 依赖）
python -c "import webview" 2>nul
if %errorlevel% neq 0 (
    echo [步骤] 安装 pywebview...
    python -m pip install pywebview
)

echo [步骤] 清理旧构建...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo [步骤] 开始打包（可能需要数分钟）...
pyinstaller packaging\server_manager_v8.spec
if %errorlevel% neq 0 (
    echo [错误] 打包失败，请查看 build/ 目录日志
    pause & exit /b 1
)

echo.
echo ========================================
echo  打包完成
echo ========================================
if exist dist\server_manager_v8.exe (
    echo [OK] EXE: dist\server_manager_v8.exe
    for %%F in (dist\server_manager_v8.exe) do echo     大小: %%~zF 字节
    echo.
    echo 双击即可启动（v6/v8 可并存运行）。
    echo 首次运行若提示 WebView2 缺失：win10/11 一般已自带；
    echo     Windows Server 2019 需安装 WebView2 Runtime：
    echo     https://developer.microsoft.com/microsoft-edge/webview2/
) else (
    echo [警告] 未找到 EXE
)

echo.
pause
