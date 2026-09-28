param([string]$PythonExe = 'python')
# Registers the Dooray Radar (list-level, unread-safe) as a logon task of this checkout.
# Same model as the Portal worker: Interactive logon, Limited, no stored password, no
# elevation, no WakeToRun. The Radar attaches to the dedicated Dooray browser that the
# operator keeps open; it never starts Chrome or asks for SSO by itself.
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
    $taskName = 'Babdoduk-Dooray-Radar'
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) { throw 'TASK_ALREADY_EXISTS_REMOVE_FIRST' }
    $operator = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $principal = New-ScheduledTaskPrincipal -UserId $operator -LogonType Interactive -RunLevel Limited
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $operator
    $trigger.Delay = 'PT60S'
    $action = New-ScheduledTaskAction -Execute $pythonWindowless -Argument ('"' + $runner + '" radar') -WorkingDirectory $repoRoot
    $settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings | Out-Null
    Write-Host 'Radar task installed (disabled until radar_tasks.ps1 -Action Start).'
} catch {
    Write-Host 'INSTALL_FAILED: check Python/configuration, existing task, and Task Scheduler policy. No elevation or live login was attempted.'
    exit 1
}
