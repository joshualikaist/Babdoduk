@echo off
powershell.exe -NoProfile -File "%~dp0ops_tasks.ps1" -Action Start
exit /b %ERRORLEVEL%
