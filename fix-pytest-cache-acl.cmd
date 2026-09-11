@echo off
rem ============================================================================
rem  Fix broken ACL on pytest cache directories
rem
rem  Affected paths (protected DACL that denies every principal):
rem    D:\erp_system\.pytest_cache
rem    D:\erp_system\.archive\cleanup-20260815\cache-dirs\.pytest_cache
rem    D:\erp_system\.archive\cleanup-20260815\cache-dirs\pytest-cache-files-f4pbu0gf
rem
rem  All three are pure caches regenerated automatically -> safe to delete.
rem  Needs Administrator rights; the script self-elevates through UAC.
rem  Set the environment variable NOPAUSE=1 for unattended / scripted runs.
rem
rem  Implementation notes (learned the hard way):
rem    * Every icacls ACE spec is QUOTED. An unquoted "(OI)(CI)F" sitting inside
rem      a parenthesised if-block is tokenised as a nested command group and
rem      aborts the whole batch with "(CI)F was unexpected at this time".
rem    * Control flow uses goto only - there are no parenthesised if-blocks.
rem    * Existence is tested with "if exist", which is the ONLY reliable built-in
rem      here: it returns TRUE for an ACL-denied directory. "attrib" wrongly
rem      reports TRUE for missing paths, and "dir" wrongly reports FALSE for
rem      denied ones (both verified empirically on this machine).
rem ============================================================================
setlocal EnableExtensions

rem --- self-elevate -----------------------------------------------------------
fltmc >nul 2>&1 && goto :elevated
net session >nul 2>&1 && goto :elevated
echo Requesting administrator privileges...
powershell -NoProfile -Command "Start-Process -Verb RunAs -FilePath '%~f0'"
exit /b 0

:elevated
echo ============================================================
echo  Running with administrator privileges
echo ============================================================

for %%P in (
    "D:\erp_system\.pytest_cache"
    "D:\erp_system\.archive\cleanup-20260815\cache-dirs\.pytest_cache"
    "D:\erp_system\.archive\cleanup-20260815\cache-dirs\pytest-cache-files-f4pbu0gf"
) do call :Fix %%P

echo.
echo ============================================================
echo  Verification
echo ============================================================
set "FAIL=0"
call :Check "D:\erp_system\.pytest_cache"
call :Check "D:\erp_system\.archive\cleanup-20260815\cache-dirs\.pytest_cache"
call :Check "D:\erp_system\.archive\cleanup-20260815\cache-dirs\pytest-cache-files-f4pbu0gf"

echo.
if "%FAIL%"=="1" goto :verdict_fail
echo   RESULT: OK - every broken pytest cache directory is gone.
echo   pytest will recreate .pytest_cache on the next run with a normal ACL.
goto :finish

:verdict_fail
echo   RESULT: FAILED - at least one path still exists.
echo   Fallbacks, in order of preference:
echo     1. Reboot into Safe Mode and delete it from there.
echo     2. Check whether an antivirus / EDR product is holding it.
echo     3. Manually run: takeown /f "path" /r /d y /a
echo                      icacls "path" /inheritance:e /t
echo                      icacls "path" /reset /t

:finish
echo.
if not "%NOPAUSE%"=="" exit /b %FAIL%
pause
exit /b %FAIL%

rem ---------------------------------------------------------------------------
:Check
set "T=%~1"
if not exist "%T%" goto :check_absent
echo   STILL PRESENT : %T%
set "FAIL=1"
exit /b 0
:check_absent
echo   gone          : %T%
exit /b 0

rem ---------------------------------------------------------------------------
:Fix
set "T=%~1"
echo.
echo --- %T%
if not exist "%T%" goto :fix_skip

rem Pass 1: own the top-level directory so it becomes enumerable.
rem         /a assigns ownership to BUILTIN\Administrators, matching the owner
rem         pattern of the healthy cache directories in this tree.
takeown /f "%T%" /a >nul 2>&1
icacls "%T%" /grant "*S-1-5-32-544:(OI)(CI)F" /c /q >nul 2>&1

rem Pass 2: now recurse - take ownership of every child.
takeown /f "%T%" /r /d y /a >nul 2>&1

rem Pass 3: clear the protected flag, then restore inherited defaults.
icacls "%T%" /inheritance:e /t /c /q >nul 2>&1
icacls "%T%" /reset /t /c /q >nul 2>&1

rem Pass 4: grant Administrators full control over the whole subtree.
icacls "%T%" /grant "*S-1-5-32-544:(OI)(CI)F" /t /c /q >nul 2>&1

rem Pass 5: delete.
rmdir /s /q "%T%" 2>nul
if not exist "%T%" goto :fix_removed

rem Retry once after re-taking ownership recursively.
takeown /f "%T%" /r /d y /a >nul 2>&1
icacls "%T%" /grant "*S-1-5-32-544:(OI)(CI)F" /t /c /q >nul 2>&1
rmdir /s /q "%T%" 2>nul
if not exist "%T%" goto :fix_removed

echo     FAILED to remove
exit /b 0

:fix_removed
echo     removed
exit /b 0

:fix_skip
echo     not present, skip
exit /b 0
