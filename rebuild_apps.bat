@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 rebuild_apps.py %*
) else (
  python rebuild_apps.py %*
)

exit /b %ERRORLEVEL%
