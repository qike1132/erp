@echo off
REM Chinese-named launcher (double-click friendly). Delegates to build.cmd so the
REM logic lives in one place. ASCII-only content: cmd.exe reads .cmd in the OEM
REM code page, so non-ASCII here would corrupt. See deploy\README.md.
call "%~dp0build.cmd" %*
