@echo off
setlocal

cd /d "%~dp0"

if not exist ".\dist\autoResults_gui.exe" (
  echo EXE not found: .\dist\autoResults_gui.exe
  echo Run .\build_autoResults_exe.bat first.
  pause
  exit /b 1
)

start "" ".\dist\autoResults_gui.exe" %*

endlocal
