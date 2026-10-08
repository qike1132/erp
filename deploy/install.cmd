@echo off
REM ============================================================
REM  ERP portable package - INSTALL launcher (double-click friendly)
REM  Runs install_package.ps1 on the TARGET host. MUST be Administrator.
REM  Keeps the window open (pause) so errors are readable.
REM  ASCII-only on purpose: cmd.exe reads .cmd in the OEM code page.
REM ============================================================
setlocal
REM --- require Administrator (net session fails without elevation) ---
net session >nul 2>&1
if errorlevel 1 (
  echo [FAIL] This installer must run as Administrator.
  echo        Right-click install.cmd and choose "Run as administrator".
  pause
  exit /b 1
)
set "SCRIPT=%~dp0install_package.ps1"
if not exist "%SCRIPT%" (
  echo [FAIL] script not found: %SCRIPT%
  pause
  exit /b 1
)
echo === ERP portable INSTALL (install_package.ps1) ===
echo You will be prompted for the package path (-Package) and the package password.
echo See deploy\README.md for the switches (-Force / -Blank / -ServerIP ...).
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT%" %*
set "RC=%ERRORLEVEL%"
echo.
echo === done (exit=%RC%) ===
pause
exit /b %RC%
