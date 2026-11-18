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

REM ---- 2026-11-18 审计 P1-27: pre-flight gate ----------------------------
REM Why this exists: erp-prod runs `python -m fastapi_app.core.prod_runner` and
REM therefore eats the D:\erp_system WORKTREE SOURCE, not a built artifact and
REM not a pinned commit. Restarting while the worktree is on another branch, or
REM with uncommitted edits, puts that code straight into production. Both have
REM already happened (AGENTS 6.1-6 and 6.1-9). A bare `nssm restart` bypassed
REM every gate, and nobody referenced this file -- so it was pure risk.
REM ASCII only: cmd would tear UTF-8 Chinese apart (see header note).
cd /d D:\erp_system

set BRANCH=
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set BRANCH=%%b
if not defined BRANCH (
    echo RESULT: REFUSED - cannot read git branch ^(not a repo?^)
    echo RESULT: REFUSED - cannot read git branch >> "%LOG%"
    exit /b 2
)
if /i not "%BRANCH%"=="main" (
    echo RESULT: REFUSED - worktree is on branch "%BRANCH%", not main.
    echo   erp-prod eats the worktree source; switching branches without a
    echo   restart plan means that branch's code becomes production.
    echo RESULT: REFUSED - branch=%BRANCH% >> "%LOG%"
    exit /b 2
)

set DIRTY=
for /f "delims=" %%s in ('git status --porcelain --untracked-files=no 2^>nul') do set DIRTY=%%s
if defined DIRTY (
    echo RESULT: REFUSED - worktree has uncommitted changes:
    echo   %DIRTY%
    echo   commit or stash them first: half-applied code across two files has
    echo   already caused an ImportError crash loop in production (AGENTS 6.1-9).
    echo RESULT: REFUSED - dirty worktree >> "%LOG%"
    exit /b 3
)

echo [0/2] preflight OK (branch=main, worktree clean) >> "%LOG%"

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
