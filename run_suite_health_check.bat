@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE="
if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" set "PYTHON_EXE=%LocalAppData%\Python\pythoncore-3.14-64\python.exe"
if not defined PYTHON_EXE if exist "%LocalAppData%\Programs\Python\Python314\python.exe" set "PYTHON_EXE=%LocalAppData%\Programs\Python\Python314\python.exe"

if defined PYTHON_EXE (
  "%PYTHON_EXE%" suite_health_check.py %*
) else (
  py -3 suite_health_check.py %*
  if errorlevel 9009 python suite_health_check.py %*
)
endlocal
