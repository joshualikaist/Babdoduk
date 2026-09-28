param([ValidateSet('Start','Stop','Status','Remove')][string]$Action)
# Operator control of the Dooray Radar task of THIS checkout. The task's action, working
# directory and owner must match this checkout, so another checkout's task is never touched.
$ErrorActionPreference = 'Stop'
try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $runner = Join-Path $PSScriptRoot 'ggongbab_workers.py'
    $pythonFile = Join-Path $repoRoot '.local\ops-python.txt'
    $pythonPath = if (Test-Path -LiteralPath $pythonFile) { (Get-Content -LiteralPath $pythonFile -Raw).Trim() } else { 'python' }
    $taskName = 'Babdoduk-Dooray-Radar'
    if ($Action -in @('Start', 'Remove')) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
        $expected = '"' + $runner + '" radar'
        $expectedExe = Join-Path (Split-Path $pythonPath) 'pythonw.exe'
        $operatorSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $taskSid = if ($task.Principal.UserId -match '^S-1-') { $task.Principal.UserId } else { ([System.Security.Principal.NTAccount]$task.Principal.UserId).Translate([System.Security.Principal.SecurityIdentifier]).Value }
        if ($task.Actions.Count -ne 1 -or $task.Actions[0].Execute -ne $expectedExe -or $task.Actions[0].Arguments -cne $expected -or $task.Actions[0].WorkingDirectory -ne $repoRoot -or $taskSid -ne $operatorSid -or $task.Principal.LogonType -ne 'Interactive') { throw 'TASK_OWNER_UNVERIFIED' }
    }
    switch ($Action) {
        'Start' {
            & $pythonPath $runner check
            if ($LASTEXITCODE -ne 0) { throw 'CONFIGURATION_REQUIRED' }
            & $pythonPath $runner radar-enable
            if ($LASTEXITCODE -ne 0) { throw 'CONTROL_WRITE_FAILED' }
            Start-ScheduledTask -TaskName $taskName
            Write-Host 'Radar start requested. Use radar_tasks.ps1 -Action Status to inspect it.'
        }
        'Stop' { & $pythonPath $runner radar-disable; Write-Host 'Radar disabled; it stops within a few seconds.'; exit $LASTEXITCODE }
        'Status' { & $pythonPath $runner status; & $pythonPath $runner alerts; exit 0 }
        'Remove' {
            & $pythonPath $runner radar-disable
            Start-Sleep -Seconds 8
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
            Write-Host 'Radar task removed. Mail state, contract and browser profile retained.'
        }
    }
} catch {
    Write-Host 'RADAR_TASK_FAILED: verify installation and task ownership. Diagnostic values suppressed.'
    exit 1
}
