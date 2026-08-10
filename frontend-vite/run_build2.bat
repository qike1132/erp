@echo off
cd /d D:\erp_system\frontend-vite
echo Running vite build...
call "C:\Users\Administrator\.trae-cn\binaries\node\versions\24.14.0\node_modules\npm\bin\npx-cli.js" --no-install vite build --logLevel error >> D:\erp_system\frontend-vite\build_batch2.log 2>&1
echo Exit code: %ERRORLEVEL% >> D:\erp_system\frontend-vite\build_batch2.log
echo Done.
