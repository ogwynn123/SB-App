@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 run_tests.py %*
) else (
  python run_tests.py %*
)

exit /b %ERRORLEVEL%
