@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

if exist "%SCRIPT_DIR%dist\tomas_pipeline_gui.exe" (
  start "" "%SCRIPT_DIR%dist\tomas_pipeline_gui.exe" %*
  endlocal
  exit /b 0
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT_DIR%tomas_pipeline_gui.py" %*
  endlocal
  exit /b %ERRORLEVEL%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%SCRIPT_DIR%tomas_pipeline_gui.py" %*
  endlocal
  exit /b %ERRORLEVEL%
)

echo Python interpreter not found on PATH.
pause
endlocal
