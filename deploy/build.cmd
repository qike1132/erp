@echo off
REM ============================================================
REM  ERP portable package - BUILD launcher (double-click friendly)
REM  Runs build_package.ps1 on the SOURCE host (read-only w.r.t. production).
REM  Keeps the window open (pause) so errors are readable.
REM  ASCII-only on purpose: cmd.exe reads .cmd in the OEM code page.
REM ============================================================
setlocal
set "SCRIPT=%~dp0build_package.ps1"
if not exist "%SCRIPT%" (
  echo [FAIL] script not found: %SCRIPT%
  pause
  exit /b 1
)
echo === ERP portable BUILD (build_package.ps1) ===
echo DryRun checks prerequisites only. Real builds require approval and Administrator access.
echo See deploy\README.md for the trusted release process.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
echo.
echo === done (exit=%RC%) ===
pause
exit /b %RC%
