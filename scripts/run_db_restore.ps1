<#
.SYNOPSIS
  Restores a database backup with optional decryption.
.PARAMETER EnvFile
  Env file to load (default: .env.staging).
.PARAMETER Input
  Backup file path.
.PARAMETER DatabaseUrl
  Optional database URL override.
.PARAMETER Encrypted
  Indicates the backup file is encrypted.
.PARAMETER Key
  Backup encryption key value.
.PARAMETER KeyFile
  Path to backup encryption key file.
.PARAMETER KeyEnv
  Env var name for backup key (default: SENTINELCV_BACKUP_KEY).
.PARAMETER Python
  Python executable (default: python).
#>

param(
    [string]$EnvFile = ".env.staging",
    [string]$Input,
    [string]$DatabaseUrl = "",
    [switch]$Encrypted,
    [string]$Key = "",
    [string]$KeyFile = "",
    [string]$KeyEnv = "SENTINELCV_BACKUP_KEY",
    [string]$Python = "python"
)

if (-not $Input) {
    Write-Error "Input backup file is required."
    exit 1
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$restoreScript = Join-Path $projectRoot "scripts\restore_database.py"

if (-not (Test-Path $restoreScript)) {
    Write-Error "restore_database.py not found at $restoreScript"
    exit 1
}

$argsList = @($restoreScript, "--env-file", $EnvFile, "--input", $Input)
if ($DatabaseUrl) {
    $argsList += "--database-url"
    $argsList += $DatabaseUrl
}
if ($Encrypted) {
    $argsList += "--encrypted"
}
if ($Key) {
    $argsList += "--key"
    $argsList += $Key
}
if ($KeyFile) {
    $argsList += "--key-file"
    $argsList += $KeyFile
}
if ($KeyEnv) {
    $argsList += "--key-env"
    $argsList += $KeyEnv
}

& $Python @argsList
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
