@echo off
setlocal

cd /d "%~dp0"

set "PYEXE=python"
where py >nul 2>nul
if %ERRORLEVEL%==0 set "PYEXE=py -3"

%PYEXE% -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

%PYEXE% -m PyInstaller --onefile --name survey_pipeline ^
  --hidden-import docx ^
  --hidden-import pdfplumber ^
  --add-data "survey_unformatter.py;." ^
  --add-data "surveyConvertJSON.py;." ^
  --add-data "question_attributes.py;." ^
  --add-data "wincrossTableCompile.py;." ^
  --add-data "unified_pipeline.py;." ^
  --add-data "..\..\survey_tool_cli.py;." ^
  survey_pipeline.py
if errorlevel 1 exit /b 1

echo.
echo Build complete.
echo EXE: %~dp0dist\survey_pipeline.exe
endlocal
