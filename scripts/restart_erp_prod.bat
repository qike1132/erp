@echo off
REM ============================================================
REM  restart_erp_prod.bat -- restart backend service erp-prod
REM
REM  2026-11-18 audit P1-27: this file used to call `nssm restart` directly.
REM  Two things were wrong with that, and both had already caused real
REM  incidents in this repo:
REM
REM   (a) It bypassed every gate. `erp-prod` runs
REM       `python -m fastapi_app.core.prod_runner` and therefore eats the
REM       D:\erp_system WORKTREE SOURCE -- not a built artifact, not a
REM       pinned commit. Restarting while the worktree is on another branch,
REM       or with uncommitted edits, puts that code straight into production
REM       (AGENTS 6.1-6 and 6.1-9). See server_manager\git_guard.py.
REM
REM   (b) `nssm restart` itself is unsafe here: on NSSM 2.24 the restart
REM       primitive returns non-zero when the STOP phase fails and then never
REM       issues START, so the service sits in STOPPED forever
REM       (nssm.cpp:271-275, service_ops.py 2026-10-13). And a plain GET
REM       /api/health returning 200 does NOT prove the new code is live --
REM       the OLD process answers that probe just as happily.
REM
REM  Rather than write a second copy of the gate and a third copy of the
REM  restart sequence, this script now delegates to the single supported
REM  implementation: `scripts\restart_backend.py`. That script does
REM  explicit stop -> wait for STOPPED -> unconditional start -> wait for
REM  RUNNING, and verifies the responding worker's runtime commit equals the
REM  target HEAD (so "healthy 200 from the old process" cannot pass).
REM
REM  Do NOT reintroduce a direct `nssm restart` here.
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
cd /d D:\erp_system
if errorlevel 1 (
    echo RESULT: FAIL - cannot cd to D:\erp_system
    exit /b 2
)

set PY=D:\erp_system\.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

echo [1/1] delegating to scripts\restart_backend.py ...
"%PY%" scripts\restart_backend.py >> "%LOG%" 2>&1
set RC=%errorlevel%

type "%LOG%"

if not "%RC%"=="0" (
    echo RESULT: FAIL - restart_backend.py exited %RC%. See logs\erp-prod.log
    exit /b %RC%
)
echo RESULT: OK - backend restarted and runtime commit verified. See %LOG%
exit /b 0
