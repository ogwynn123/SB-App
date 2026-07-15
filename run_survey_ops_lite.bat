@echo off
setlocal
cd /d "%~dp0"
py -3 survey_ops_lite.py
if errorlevel 1 pause
