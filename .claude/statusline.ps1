# Claude Code status line: model | branch | folder | context % | dirty count.
# Reads the session JSON from stdin. Runs two local git queries; no network,
# no secrets and no environment values are printed.
$ErrorActionPreference = 'SilentlyContinue'
$data = $null
try { $data = [Console]::In.ReadToEnd() | ConvertFrom-Json } catch { }

$model = 'Claude'
if ($data -and $data.model -and $data.model.display_name) { $model = [string]$data.model.display_name }

$dir = $null
if ($data -and $data.workspace -and $data.workspace.current_dir) { $dir = [string]$data.workspace.current_dir }
elseif ($data -and $data.cwd) { $dir = [string]$data.cwd }
if (-not $dir) { $dir = (Get-Location).Path }

$branch = git -C $dir branch --show-current 2>$null
if (-not $branch) { $branch = git -C $dir rev-parse --short HEAD 2>$null }
if (-not $branch) { $branch = 'no git' }
$dirty = @(git -C $dir status --porcelain 2>$null).Count

$context = 'ctx ?'
if ($data -and $data.context_window -and $null -ne $data.context_window.used_percentage) {
  $context = 'ctx {0}%' -f [math]::Round([double]$data.context_window.used_percentage)
}

Write-Output ('{0} | {1} | {2} | {3} | dirty {4}' -f $model, $branch, (Split-Path -Leaf $dir), $context, $dirty)
