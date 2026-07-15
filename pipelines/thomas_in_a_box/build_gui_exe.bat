@echo off
setlocal

cd /d "%~dp0"

set "PYEXE=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYEXE=py -3"

%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

%PYEXE% -m pip install pyinstaller
if errorlevel 1 exit /b 1

%PYEXE% -m PyInstaller --noconfirm --clean tomas_pipeline_worker.spec
if errorlevel 1 exit /b 1

%PYEXE% -m PyInstaller --noconfirm --clean tomas_pipeline_gui.spec
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo WORKER: %~dp0dist\tomas_pipeline_worker.exe
echo EXE: %~dp0dist\tomas_pipeline_gui.exe
endlocal
