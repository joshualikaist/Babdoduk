@echo off
powershell.exe -NoProfile -File "%~dp0ops_browser.ps1" -Action Start
exit /b %ERRORLEVEL%
