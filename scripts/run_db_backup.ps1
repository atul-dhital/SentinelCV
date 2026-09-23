<#
.SYNOPSIS
  Creates a database backup with optional encryption.
.PARAMETER EnvFile
  Env file to load (default: .env.staging).
.PARAMETER OutputDir
  Backup output directory (default: ./backups).
.PARAMETER DatabaseUrl
  Optional database URL override.
.PARAMETER Encrypt
  Enable backup encryption.
.PARAMETER KeepPlain
  Keep plaintext backup when encrypting.
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
    [string]$OutputDir = "./backups",
    [string]$DatabaseUrl = "",
    [switch]$Encrypt,
    [switch]$KeepPlain,
    [string]$Key = "",
    [string]$KeyFile = "",
    [string]$KeyEnv = "SENTINELCV_BACKUP_KEY",
    [string]$Python = "python"
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$backupScript = Join-Path $projectRoot "scripts\backup_database.py"

if (-not (Test-Path $backupScript)) {
    Write-Error "backup_database.py not found at $backupScript"
    exit 1
}

$argsList = @($backupScript, "--env-file", $EnvFile, "--output-dir", $OutputDir)
if ($DatabaseUrl) {
    $argsList += "--database-url"
    $argsList += $DatabaseUrl
}
if ($Encrypt) {
    $argsList += "--encrypt"
}
if ($KeepPlain) {
    $argsList += "--keep-plain"
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
