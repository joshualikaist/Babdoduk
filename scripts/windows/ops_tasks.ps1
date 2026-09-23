param([ValidateSet('Start','Stop','Status','Recover','Remove')][string]$Action)
$ErrorActionPreference = 'Stop'
try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $runner = Join-Path $PSScriptRoot 'ggongbab_workers.py'
    $pythonFile = Join-Path $repoRoot '.local\ops-python.txt'
    $pythonPath = if (Test-Path -LiteralPath $pythonFile) { (Get-Content -LiteralPath $pythonFile -Raw).Trim() } else { 'python' }
    $taskName = 'Babdoduk-Portal-Worker'
    if ($Action -in @('Start', 'Remove')) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $expected = '"' + $runner + '" watch'
        $expectedExe = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
        $operatorSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $taskSid = if ($task.Principal.UserId -match '^S-1-') { $task.Principal.UserId } else { ([System.Security.Principal.NTAccount]$task.Principal.UserId).Translate([System.Security.Principal.SecurityIdentifier]).Value }
        if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $expectedExe -or $task.Actions[0].Arguments -cne $expected -or $task.Actions[0].WorkingDirectory -ne $repoRoot -or $taskSid -ne $operatorSid -or $task.Principal.LogonType -ne 'Interactive') { throw 'TASK_OWNER_UNVERIFIED' }
    }
    switch ($Action) {
        'Start' {
            & $pythonPath $runner check
            if ($LASTEXITCODE -ne 0) { throw 'CONFIGURATION_REQUIRED' }
            & $pythonPath $runner enable
            if ($LASTEXITCODE -ne 0) { throw 'CONTROL_WRITE_FAILED' }
            Start-ScheduledTask -TaskName $taskName
            Write-Host 'Worker start requested. Use status_ggongbab_workers.cmd to inspect it.'
        }
        'Stop' { & $pythonPath $runner stop; exit $LASTEXITCODE }
        'Status' { & $pythonPath $runner status; exit $LASTEXITCODE }
        'Recover' { & $pythonPath $runner recover; exit $LASTEXITCODE }
        'Remove' {
            & $pythonPath $runner stop
            if ($LASTEXITCODE -ne 0) { throw 'WORKER_NOT_STOPPED' }
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host 'Task removed. Portal browser, profile, baseline, pending and logs retained.'
        }
    }
} catch {
    Write-Host 'OPS_TASK_FAILED: verify installation and task ownership. Diagnostic values suppressed.'
    exit 1
}
