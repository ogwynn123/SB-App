@echo off
setlocal
cd /d "%~dp0"
py -3 -m local_browser_app.server %*
endlocal

