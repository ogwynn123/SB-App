@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist "%SCRIPT_DIR%dist\survey_pipeline_gui.exe" (
  start "" "%SCRIPT_DIR%dist\survey_pipeline_gui.exe" %*
  endlocal
  exit /b 0
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 "%SCRIPT_DIR%survey_pipeline_gui.py" %*
  set "RC=%ERRORLEVEL%"
  if not "%RC%"=="0" (
    echo.
    echo survey_pipeline_gui.py exited with code %RC%.
    pause
  )
  exit /b %RC%
)

where python >nul 2>nul
if %ERRORLEVEL%==0 (
  python "%SCRIPT_DIR%survey_pipeline_gui.py" %*
  set "RC=%ERRORLEVEL%"
  if not "%RC%"=="0" (
    echo.
    echo survey_pipeline_gui.py exited with code %RC%.
    pause
  )
  exit /b %RC%
)

echo Python interpreter not found on PATH.
pause
exit /b 9009
