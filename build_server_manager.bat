@echo off
chcp 65001 >nul
echo ========================================
echo ERP 服务器管理器打包脚本
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
echo [1/5] 检查并安装依赖包...
pip install pyinstaller psutil >nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 依赖包安装失败
    pause
    exit /b 1
)
echo [OK] 依赖包已安装
echo.

echo [2/5] 检查必要文件...
if not exist "server_manager.py" (
    echo [错误] 找不到 server_manager.py
    pause
    exit /b 1
)
if not exist "server_manager.spec" (
    echo [错误] 找不到 server_manager.spec
    pause
    exit /b 1
)
echo [OK] 必要文件检查通过
echo.

echo [3/5] 清理旧的打包文件...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist
echo [OK] 清理完成
echo.

echo [4/5] 开始打包...
echo 这可能需要 5-15 分钟，请耐心等待...
echo.

pyinstaller --clean server_manager.spec

if %errorlevel% neq 0 (
    echo.
    echo [错误] 打包失败！
    pause
    exit /b 1
)

echo.
echo [5/5] 打包完成！
echo.
echo ========================================
echo 可执行文件位置: dist\ERP服务器管理器.exe
echo ========================================
echo.

REM 检查是否生成exe
if exist "dist\ERP服务器管理器.exe" (
    echo [OK] EXE 文件生成成功
    
    echo.
    echo 下一步操作:
    echo 1. 测试可执行文件是否正常运行
    echo 2. 将 dist 文件夹复制到桌面或其他位置
    echo 3. 运行 ERP服务器管理器.exe
    echo.
    
    choice /C YN /M "是否复制EXE到桌面"
    if errorlevel 1 (
        echo.
        echo 正在复制到桌面...
        copy "dist\ERP服务器管理器.exe" "%USERPROFILE%\Desktop\ERP服务器管理器.exe" >nul
        if %errorlevel% equ 0 (
            echo [OK] 已复制到桌面: %USERPROFILE%\Desktop\ERP服务器管理器.exe
        ) else (
            echo [警告] 复制失败，请手动复制
        )
    )
    
    echo.
    choice /C YN /M "是否现在测试运行"
    if errorlevel 1 (
        echo.
        echo 正在启动测试...
        start "" "dist\ERP服务器管理器.exe"
        echo.
        echo [提示] 服务器管理器窗口已打开
        echo 请验证以下功能:
        echo   1. FastAPI 服务启动/停止
        echo   2. Flask 服务启动/停止  
        echo   3. 全部启动/停止
        echo   4. 日志显示正常
        echo   5. 关闭窗口时的处理
    )
) else (
    echo [错误] EXE 文件未生成，请检查打包日志
)

echo.
pause
