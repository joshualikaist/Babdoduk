@echo off
powershell.exe -NoProfile -File "%~dp0ops_tasks.ps1" -Action Status
exit /b %ERRORLEVEL%
