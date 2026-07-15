@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" set "PYTHON_EXE=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python314\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"

if defined PYTHON_EXE (
  "%PYTHON_EXE%" survey_platform_gui.py
) else (
  py -3 survey_platform_gui.py
  if errorlevel 9009 python survey_platform_gui.py
)
endlocal
