@echo off
cd /d D:\erp_system\frontend-vite
echo Running vite build...
call node node_modules\vite\bin\vite.js build --logLevel warn > D:\erp_system\frontend-vite\build_now.log 2>&1
echo Exit: %ERRORLEVEL%
