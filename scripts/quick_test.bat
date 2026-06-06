@echo off
chcp 65001 >nul
echo ============================================================
echo       ERP 实时同步功能 - 快速测试脚本
echo ============================================================
echo.
echo 此脚本将执行一次模拟出库，用于验证实时同步功能
echo.
echo 请确保：
echo   [√ 1. 后端服务正在运行
echo   [√ 2. Dashboard 页面已在浏览器中打开
echo   [√ 3. 浏览器控制台已打开 (F12)
echo.
echo ============================================================
echo.

cd /d "%~dp0.."

echo [1/3] 检查 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 找不到 Python，请先安装 Python
    pause
    exit /b 1
)
echo OK
echo.

echo [2/3] 执行模拟出库...
python scripts\simulate_stockout.py

if errorlevel 1 (
    echo.
    echo 脚本执行失败，请检查错误信息
    pause
    exit /b 1
)

echo.
echo [3/3] 测试完成！
echo.
echo 现在请观察浏览器：
echo   - Dashboard 页面是否自动刷新
echo   - 出库数据是否更新
echo   - 浏览器控制台是否有 WebSocket 相关日志
echo.
echo ============================================================
echo.
pause
