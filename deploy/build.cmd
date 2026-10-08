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
echo Tip: dry-run = run "build.cmd -DryRun"  ^(needs nothing in deploy\binaries^)
echo      real build requires the 6 installers in deploy\binaries\ (see deploy\README.md)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
echo.
echo === done (exit=%RC%) ===
pause
exit /b %RC%
