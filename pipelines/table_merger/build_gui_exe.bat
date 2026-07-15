@echo off
setlocal

cd /d "%~dp0"

set "PYEXE=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYEXE=py -3"

%PYEXE% -m pip install pandas openpyxl rapidfuzz pyinstaller
if errorlevel 1 exit /b 1

%PYEXE% -m PyInstaller --noconfirm --clean sheet_merge_gui.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo EXE: %~dp0dist\sheet_merge_gui.exe
endlocal
