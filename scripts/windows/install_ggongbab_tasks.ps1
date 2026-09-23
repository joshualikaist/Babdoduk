param([string]$PythonExe = 'python')
$ErrorActionPreference = 'Stop'
try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $runner = Join-Path $PSScriptRoot 'ggongbab_workers.py'
    $pythonPath = (& $PythonExe -c 'import sys; print(sys.executable)').Trim()
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $pythonPath)) { throw 'PYTHON_REQUIRED' }
    & $pythonPath $runner check
    if ($LASTEXITCODE -ne 0) { throw 'CONFIGURATION_REQUIRED' }
    $pythonWindowless = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $pythonWindowless)) { throw 'PYTHONW_REQUIRED' }
    $taskName = 'Babdoduk-Portal-Worker'
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'TASK_ALREADY_EXISTS_REMOVE_FIRST' }
    $operator = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $operator -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $operator
    $trigger.Delay = 'PT30S'
    $action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('"' + $runner + '" watch') -WorkingDirectory $repoRoot
    # Only supervisor crashes are restarted here. Persistent worker human-action
    # latches survive these restarts. No WakeToRun; no stored password or elevation.
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    $localDir = Join-Path $repoRoot '.local'
    New-Item -ItemType Directory -Path $localDir -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $localDir 'ops-python.txt') -Value $pythonPath -Encoding UTF8
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    & $pythonPath $runner enable
    if ($LASTEXITCODE -ne 0) { throw 'CONTROL_WRITE_FAILED' }
    Write-Host 'Installed. Starts 30 seconds after your next logon. Use start_ggongbab_workers.cmd to start now.'
} catch {
    Write-Host 'INSTALL_FAILED: check Python/configuration, existing task, and Task Scheduler policy. No elevation or live login was attempted.'
    exit 1
}
