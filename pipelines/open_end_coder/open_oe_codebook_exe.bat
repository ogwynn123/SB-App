@echo off
setlocal

cd /d "%~dp0"

if not exist "%~dp0dist\oe_record_coder_gui.exe" (
  echo EXE not found. Building first...
  call "%~dp0build_gui_exe.bat"
  if errorlevel 1 exit /b 1
)

start "" "%~dp0dist\oe_record_coder_gui.exe" %*
endlocal
