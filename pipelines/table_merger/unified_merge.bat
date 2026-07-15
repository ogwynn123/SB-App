@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT_DIR%unified_merge.py" %*
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%SCRIPT_DIR%unified_merge.py" %*
  exit /b %ERRORLEVEL%
)

echo Python interpreter not found on PATH.
exit /b 9009
