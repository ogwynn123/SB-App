@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

if exist "%SCRIPT_DIR%dist\oe_codebook_gui.exe" (
  start "" "%SCRIPT_DIR%dist\oe_codebook_gui.exe" %*
  endlocal
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_oe_codebook_gui.ps1" -ScriptPath "oe_codebook_gui.py" %*
if errorlevel 1 (
  echo.
  echo Legacy launch failed. Press any key to close...
  pause >nul
)
endlocal
