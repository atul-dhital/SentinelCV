<#
.SYNOPSIS
  Runs data retention cleanup for SentinelCV.
.PARAMETER EnvFile
  Env file to load (default: .env.staging).
.PARAMETER OrgId
  Optional organization id to target.
.PARAMETER DryRun
  Report counts without deleting.
.PARAMETER Python
  Python executable (default: python).
#>

param(
    [string]$EnvFile = ".env.staging",
    [string]$OrgId = "",
    [switch]$DryRun,
    [string]$Python = "python"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$cleanupScript = Join-Path $projectRoot "scripts\retention_cleanup.py"

if (-not (Test-Path $cleanupScript)) {
    Write-Error "retention_cleanup.py not found at $cleanupScript"
    exit 1
}

$argsList = @($cleanupScript, "--env-file", $EnvFile)
if ($OrgId) {
    $argsList += "--org-id"
    $argsList += $OrgId
}
if ($DryRun) {
    $argsList += "--dry-run"
}

& $Python @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
