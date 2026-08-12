@echo off
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul
if %ERRORLEVEL%==0 (
  start "" pyw -3 "%~dp0survey_ops_lite.py" %*
  endlocal
  exit /b 0
)

py -3 "%~dp0survey_ops_lite.py" %*
if errorlevel 1 pause
endlocal
