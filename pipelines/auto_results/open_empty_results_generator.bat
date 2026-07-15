@echo off
setlocal

cd /d "%~dp0"

if "%~1"=="" (
  py -3 .\empty_results_generator.py --help
  endlocal
  exit /b 0
)

py -3 .\empty_results_generator.py %*

endlocal
