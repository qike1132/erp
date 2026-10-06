@echo off
REM ============================================================
REM  restore_web_3000.bat -- restore production web serving
REM
REM  Problem (2026-10-05): an elevated session left a "vite dev"
REM  server (node.exe) bound to port 3000 and the erp-web (nginx)
REM  service was stopped, so users got dev-mode rendering
REM  (e.g. backup page columns misaligned) instead of the
REM  production build in frontend-vite/dist.
REM
REM  What it does:
REM   Step 1: kill the node.exe listening on port 3000
REM           (ONLY if it is node.exe -- nginx is never touched)
REM   Step 2: start the erp-web service (nginx, serves dist)
REM   Step 3: verify http://127.0.0.1:3000/ serves the production
REM           build (has assets/index-*.js, no @vite/client)
REM
REM  Result log: D:\erp_system\logs\restore_web_result.txt
REM  NOTE: pure ASCII only -- cmd would tear UTF-8 Chinese apart.
REM ============================================================
setlocal

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo Requesting administrator rights, please click Yes on the UAC prompt...
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

set LOG=D:\erp_system\logs\restore_web_result.txt
echo === restore erp-web %date% %time% === > "%LOG%"

echo [1/3] stopping vite dev (node.exe) on port 3000 ...
powershell -NoProfile -Command "$pids=Get-NetTCPConnection -LocalPort 3000 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique; foreach($p in $pids){ $proc=Get-Process -Id $p -ErrorAction SilentlyContinue; if($proc -and $proc.ProcessName -eq 'node'){ Stop-Process -Id $p -Force; Write-Output ('killed node pid ' + $p) } else { Write-Output ('skip pid ' + $p + ' (not node, left running)') } }" >> "%LOG%" 2>&1

echo [2/3] starting service erp-web ...
sc start erp-web >> "%LOG%" 2>&1
if %errorlevel% neq 0 (
    echo sc start failed, retrying via net start ...
    net start erp-web >> "%LOG%" 2>&1
)

ping -n 4 127.0.0.1 >nul

echo [3/3] verifying http://127.0.0.1:3000/ ...
powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:3000/' -UseBasicParsing -TimeoutSec 8; $h = $r.Content; if ($h -match '@vite/client') { Write-Output 'RESULT: FAIL - vite dev still serving on 3000' } elseif ($h -match 'assets/index-') { Write-Output 'RESULT: OK - production build serving on 3000' } else { Write-Output 'RESULT: UNKNOWN - unexpected index content' } } catch { Write-Output ('RESULT: ERROR - ' + $_.Exception.Message) }" >> "%LOG%" 2>&1
powershell -NoProfile -Command "sc.exe query erp-web | Select-String STATE" >> "%LOG%" 2>&1

echo.
type "%LOG%"
echo.
echo Full log: %LOG%
pause
