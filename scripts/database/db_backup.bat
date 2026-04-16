@echo off
chcp 65001 >nul
echo ============================================================
echo ERP系统数据库备份工具
echo ============================================================
echo.

cd /d "%~dp0.."
cd ..

if not exist "venv\Scripts\python.exe" (
    if not exist ".venv\Scripts\python.exe" (
        echo [错误] 未找到Python虚拟环境
        echo 请确保已在项目根目录创建虚拟环境
        pause
        exit /b 1
    )
    set PYTHON_PATH=.venv\Scripts\python.exe
) else (
    set PYTHON_PATH=venv\Scripts\python.exe
)

echo [信息] 使用Python: %PYTHON_PATH%
echo.

%PYTHON_PATH% scripts\database\db_manager.py backup --type manual

echo.
echo ============================================================
echo 备份操作已完成
echo ============================================================
pause
