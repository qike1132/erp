@echo off
REM ============================================================
REM  restart_erp_prod.bat -- restart backend service erp-prod
REM
REM  Why (2026-10-05): GET /api/v1/aux/available-shipment returned
REM  500 ReadOnlySQLTransactionError on the read replica. Fix is
REM  already in the working tree (lock_orders=False on the display
REM  endpoint); the backend process must reload code to pick it up.
REM
REM  What it does:
REM   Step 1: nssm restart erp-prod (same op as server_manager GUI)
REM   Step 2: poll http://127.0.0.1:5002/api/health until 200
REM
REM  Result log: D:\erp_system\logs\restart_erp_prod_result.txt
REM  NOTE: pure ASCII only -- cmd would tear UTF-8 Chinese apart.
REM ============================================================
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights, please click Yes on the UAC prompt...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set LOG=D:\erp_system\logs\restart_erp_prod_result.txt
echo === restart erp-prod %date% %time% === > "%LOG%"

echo [1/2] restarting service erp-prod ...
C:\nssm\nssm.exe restart erp-prod >> "%LOG%" 2>&1
sc.exe query erp-prod | find "RUNNING" >> "%LOG%" 2>&1

echo [2/2] waiting for backend /api/health ...
set /a TRIES=0
:waitloop
ping -n 4 127.0.0.1 >nul
set /a TRIES+=1
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:5002/api/health' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { Write-Output 'DOWN' }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "try { (Invoke-WebRequest -Uri 'http://127.0.0.1:5002/api/health' -UseBasicParsing -TimeoutSec 3).StatusCode } catch { Write-Output 'DOWN' }" | find "200" >nul
if %errorlevel% equ 0 goto healthy
if %TRIES% geq 30 (
    echo RESULT: FAIL - backend not healthy after 90s. See logs\erp-prod.log
    echo RESULT: FAIL - backend not healthy after 90s >> "%LOG%"
    pause
    exit /b 1
)
goto waitloop

:healthy
echo RESULT: OK - backend healthy (HTTP 200), new code is live.
echo RESULT: OK - backend healthy (HTTP 200), new code is live. >> "%LOG%"
echo.
type "%LOG%"
echo.
echo Full log: %LOG%
pause
