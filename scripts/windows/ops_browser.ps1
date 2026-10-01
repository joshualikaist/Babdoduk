param([ValidateSet('Start','Status','Recover')][string]$Action)
# The Babdoduk Ops Chrome: ONE dedicated Chrome (KAIST Portal tab + Dooray tab), its own profile
# (.local\ops-browser-profile) and a loopback-only CDP port (127.0.0.1:9224).
#   Start   - reuse a verified browser, start it only when absent, open only a missing tab
#   Status  - running / missing / stale / unverified, and tab presence; never a URL or account
#   Recover - targeted single-attempt recovery of the verified dedicated process only
$ErrorActionPreference = 'Stop'
try {
    $repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
    $runner = Join-Path $PSScriptRoot 'ggongbab_workers.py'
    $pythonFile = Join-Path $repoRoot '.local\ops-python.txt'
    $pythonPath = if (Test-Path -LiteralPath $pythonFile) { (Get-Content -LiteralPath $pythonFile -Raw).Trim() } else { 'python' }
    $command = @{ Start = 'ops-browser-start'; Status = 'ops-browser-status'; Recover = 'ops-browser-recover' }[$Action]
    & $pythonPath $runner $command
    exit $LASTEXITCODE
} catch {
    Write-Host 'OPS_BROWSER_FAILED: verify the operations checkout. Diagnostic values suppressed.'
    exit 1
}
