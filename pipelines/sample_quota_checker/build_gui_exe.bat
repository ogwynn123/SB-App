@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %ERRORLEVEL%==0 (
  py -3 -m PyInstaller --noconfirm --clean sample_quota_checker.spec
) else (
  python -m PyInstaller --noconfirm --clean sample_quota_checker.spec
)

if errorlevel 1 exit /b 1
echo Build complete: %~dp0dist\sample_quota_checker.exe
endlocal
