@echo off
echo ================================================
echo  Redis Server for ERP System
echo ================================================
echo.
echo Starting Redis server on port 6379...
echo.
start "" "C:\Redis\redis-server.exe" "C:\Redis\redis.windows.conf" --requirepass ERP_Redis_2026_Secure_Password
echo Redis server started!
echo.
echo Press any key to close this window (Redis will keep running)
pause >nul
