@echo off
setlocal

cd /d "%~dp0"
if exist ".\dist\sheet_merge_gui.exe" (
  start "" ".\dist\sheet_merge_gui.exe" %*
  endlocal
  exit /b 0
)

powershell -NoProfile -ExecutionPolicy Bypass -File ".\run_sheetMerging_gui.ps1" %*

endlocal
