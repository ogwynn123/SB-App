@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m PyInstaller --noconfirm --clean trend_table_updater.spec
) else (
  python -m PyInstaller --noconfirm --clean trend_table_updater.spec
)

if errorlevel 1 exit /b 1
echo Build complete: %~dp0dist\trend_table_updater.exe
endlocal
