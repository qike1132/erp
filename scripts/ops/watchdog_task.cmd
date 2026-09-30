@echo off
REM Run the ERP watchdog (invoked every 5 minutes by scheduled task "erp-watchdog").
REM This wrapper exists so schtasks /TR needs no nested quoting.
REM NOTE: keep this file ASCII-only. cmd.exe reads .cmd in the OEM code page
REM (GBK on zh-CN Windows), so UTF-8 Chinese comments corrupt command lines.
cd /d "%~dp0..\.."

set "PY=C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe"
if not exist "%PY%" set "PY=python"

REM Force UTF-8 stdout so Chinese text does not become mojibake in task logs.
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

"%PY%" "scripts\ops\watchdog.py" %*
exit /b %ERRORLEVEL%
