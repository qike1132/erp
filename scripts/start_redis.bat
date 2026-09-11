@echo off
echo ================================================
echo  Redis Server for ERP System
echo ================================================
echo.
echo Starting Redis server on port 6379...
echo.
rem 密码从环境变量 REDIS_PASSWORD 读取（见 .env），不再硬编码
start "" "C:\Redis\redis-server.exe" "C:\Redis\redis.windows.conf" --requirepass %REDIS_PASSWORD%
echo Redis server started!
echo.
echo Press any key to close this window (Redis will keep running)
pause >nul
