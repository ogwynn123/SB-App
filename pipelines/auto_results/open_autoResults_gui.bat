@echo off
setlocal
set "SCRIPT_DIR=%~dp0"

cd /d "%SCRIPT_DIR%"

if exist "%SCRIPT_DIR%dist\autoResults_gui.exe" (
  start "" "%SCRIPT_DIR%dist\autoResults_gui.exe" %*
  endlocal
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_autoResults_gui.ps1" %*

endlocal
