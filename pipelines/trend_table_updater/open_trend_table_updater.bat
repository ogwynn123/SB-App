@echo off
setlocal
cd /d "%~dp0"

if exist ".\dist\trend_table_updater.exe" (
  start "" ".\dist\trend_table_updater.exe" %*
  endlocal
  exit /b 0
)

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 ".\trend_table_updater_gui.py" %*
) else (
  python ".\trend_table_updater_gui.py" %*
)

endlocal
