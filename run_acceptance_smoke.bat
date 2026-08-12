@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 acceptance_smoke.py %*
) else (
  python acceptance_smoke.py %*
)

exit /b %ERRORLEVEL%
