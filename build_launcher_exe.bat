@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m PyInstaller --noconfirm --clean survey_launcher.spec
) else (
  python -m PyInstaller --noconfirm --clean survey_launcher.spec
)

if errorlevel 1 exit /b 1
echo Build complete: %~dp0dist\survey_launcher.exe
endlocal
