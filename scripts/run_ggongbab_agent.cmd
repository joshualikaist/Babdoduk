@echo off
REM Unattended ggongbab agent for Windows Task Scheduler.
REM Scans the Dooray mailbox, registers candidates as project tasks, then runs
REM the ingest pipeline. No human input; stops cleanly if the SSO session expired.
REM
REM Exit codes: 0 success, 10 auth required, 20 UI changed, 30 project not found,
REM             40 pipeline failed. Task Scheduler shows this as "Last Run Result".

cd /d "%~dp0.."
if not exist ".local" mkdir ".local"

echo. >> ".local\agent.log"
echo ===== %DATE% %TIME% ===== >> ".local\agent.log"

REM --cdp attaches to the resident Chrome; the login only survives there.
python scripts\dooray_web_agent.py --run --since-last-run --run-pipeline --cdp >> ".local\agent.log" 2>&1
set RESULT=%ERRORLEVEL%

if %RESULT% EQU 10 (
  echo AUTH_REQUIRED: run "python scripts\dooray_web_agent.py --setup --cdp" to log in again >> ".local\agent.log"
)
if %RESULT% EQU 20 (
  echo UI_CHANGED: run "python scripts\dooray_web_agent.py --discover" >> ".local\agent.log"
)

exit /b %RESULT%
