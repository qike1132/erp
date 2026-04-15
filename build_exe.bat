@echo off
chcp 65001 >nul
echo ========================================
echo ERP 系统打包脚本
echo ========================================
echo.

REM 检查 Python 是否安装
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    pause
    exit /b 1
)

echo [OK] Python 环境检查通过
echo.

REM 检查是否在虚拟环境中
python -c "import sys; print('venv' if hasattr(sys, 'real_prefix') else 'no venv')" | findstr "venv" >nul
if %errorlevel% neq 0 (
    echo [警告] 未检测到虚拟环境，建议在虚拟环境中打包
    echo.
    choice /C YN /M "是否继续打包"
    if errorlevel 2 exit /b 0
)

echo.
echo [1/4] 检查并安装 PyInstaller...
pip show pyinstaller >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在安装 PyInstaller...
    pip install pyinstaller
    if %errorlevel% neq 0 (
        echo [错误] PyInstaller 安装失败
        pause
        exit /b 1
    )
)
echo [OK] PyInstaller 已就绪
echo.

echo [2/4] 清理旧的打包文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [OK] 清理完成
echo.

echo [3/4] 开始打包...
echo 这可能需要 5-15 分钟，请耐心等待...
echo.

pyinstaller --clean erp_system.spec

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [4/4] 打包完成！
echo.
echo ========================================
echo 可执行文件位置: dist\ERP_System.exe
echo ========================================
echo.
echo 下一步操作:
echo 1. 测试可执行文件是否正常运行
echo 2. 将 dist 文件夹整个复制到目标机器
echo 3. 在目标机器上运行 ERP_System.exe
echo.
choice /C YN /M "是否现在测试运行可执行文件"
if errorlevel 1 (
    echo.
    echo 正在启动测试...
    cd dist
    start ERP_System.exe
    echo.
    echo [提示] 测试窗口已打开，请验证功能
    echo 按 Ctrl+C 可以停止服务器
)

echo.
pause
