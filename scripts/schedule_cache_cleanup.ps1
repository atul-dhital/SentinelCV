<
.SYNOPSIS
  Registers a scheduled task for SentinelCV cache/session cleanup.
.DESCRIPTION
  Creates a Windows Scheduled Task that runs run_cache_cleanup.ps1 at a fixed interval.
.PARAMETER TaskName
  Task name to register.
.PARAMETER EnvFile
  Env file to pass to cleanup script (default: .env.staging).
.PARAMETER IntervalMinutes
  Repetition interval in minutes.
.PARAMETER MaxKeys
  Maximum keys to scan per run.
.PARAMETER Python
  Python executable to use (default: python).
#>

param(
    [string]$TaskName = "SentinelCV-CacheCleanup",
    [string]$EnvFile = ".env.staging",
    [int]$IntervalMinutes = 60,
    [int]$MaxKeys = 500,
    [string]$Python = "python"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$runnerScript = Join-Path $projectRoot "scripts\run_cache_cleanup.ps1"

if (-not (Test-Path $runnerScript)) {
    Write-Error "run_cache_cleanup.ps1 not found at $runnerScript"
    exit 1
}

$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -EnvFile `"$EnvFile`" -MaxKeys $MaxKeys -Python `"$Python`""

schtasks /Create /F /SC MINUTE /MO $IntervalMinutes /TN $TaskName /TR $action /RL LIMITED
