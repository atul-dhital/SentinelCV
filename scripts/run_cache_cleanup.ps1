<
.SYNOPSIS
  Runs SentinelCV cache/session cleanup once.
.PARAMETER EnvFile
  Path to env file (default: .env.staging).
.PARAMETER MaxKeys
  Maximum session keys to scan (default: 500).
.PARAMETER Python
  Python executable (default: python).
#>

param(
    [string]$EnvFile = ".env.staging",
    [int]$MaxKeys = 500,
    [string]$Python = "python"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$cleanupScript = Join-Path $projectRoot "scripts\cleanup_sessions.py"

if (-not (Test-Path $cleanupScript)) {
    Write-Error "cleanup_sessions.py not found at $cleanupScript"
    exit 1
}

Set-Location $projectRoot

& $Python $cleanupScript --env-file $EnvFile --max-keys $MaxKeys
