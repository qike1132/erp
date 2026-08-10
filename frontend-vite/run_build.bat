@echo off
cd /d D:\erp_system\frontend-vite
echo Building frontend...
call "C:\Users\Administrator\.trae-cn\binaries\node\versions\24.14.0\npx.cmd" vite build > D:\erp_system\frontend-vite\build_batch.log 2>&1
echo Build exit code: %ERRORLEVEL%