@echo off
powershell.exe -NoProfile -File "%~dp0ops_browser.ps1" -Action Recover
exit /b %ERRORLEVEL%
