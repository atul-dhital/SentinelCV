<#
.SYNOPSIS
  Registers a scheduled task for SentinelCV retention cleanup.
.PARAMETER TaskName
  Task name to register.
.PARAMETER EnvFile
  Env file to pass (default: .env.staging).
.PARAMETER StartTime
  Start time in HH:mm (24h) format.
.PARAMETER OrgId
  Optional organization id to target.
.PARAMETER DryRun
  Run in dry-run mode.
.PARAMETER Python
  Python executable to use (default: python).
#>

param(
    [string]$TaskName = "SentinelCV-RetentionCleanup",
    [string]$EnvFile = ".env.staging",
    [string]$StartTime = "02:00",
    [string]$OrgId = "",
    [switch]$DryRun,
    [string]$Python = "python"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$runnerScript = Join-Path $projectRoot "scripts\run_retention_cleanup.ps1"

if (-not (Test-Path $runnerScript)) {
    Write-Error "run_retention_cleanup.ps1 not found at $runnerScript"
    exit 1
}

$action = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$runnerScript`" -EnvFile `"$EnvFile`" -Python `"$Python`""
if ($OrgId) {
    $action += " -OrgId `"$OrgId`""
}
if ($DryRun) {
    $action += " -DryRun"
}

schtasks /Create /F /SC DAILY /ST $StartTime /TN $TaskName /TR $action /RL LIMITED
