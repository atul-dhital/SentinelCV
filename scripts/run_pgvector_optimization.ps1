<#
.SYNOPSIS
  Creates or updates pgvector indexes for face embeddings.
.DESCRIPTION
  Runs scripts/pgvector_optimize.sql against the configured database.
  Supports ivfflat and hnsw index types with tunable parameters.
.PARAMETER EnvFile
  Env file to load (default: .env.staging).
.PARAMETER DatabaseUrl
  Optional database URL override.
.PARAMETER IndexType
  ivfflat or hnsw (defaults to PGVECTOR_INDEX_TYPE or hnsw).
.PARAMETER IvfflatLists
  List count for ivfflat (defaults to PGVECTOR_IVFFLAT_LISTS or 100).
.PARAMETER HnswM
  HNSW M parameter (defaults to PGVECTOR_HNSW_M or 16).
.PARAMETER HnswEfConstruction
  HNSW ef_construction parameter (defaults to PGVECTOR_HNSW_EF_CONSTRUCTION or 64).
.PARAMETER Psql
  psql executable name or path (default: psql).
#>

param(
    [string]$EnvFile = ".env.staging",
    [string]$DatabaseUrl = "",
    [string]$IndexType = "",
    [int]$IvfflatLists = 0,
    [int]$HnswM = 0,
    [int]$HnswEfConstruction = 0,
    [string]$Psql = "psql"
)

function Import-EnvFile {
    param([string]$Path)
    if (-not $Path) {
        return
    }
    if (-not (Test-Path $Path)) {
        return
    }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#") -or -not $line.Contains("=")) {
            return
        }
        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        if ($key) {
          $existing = [Environment]::GetEnvironmentVariable($key, "Process")
          if (-not $existing) {
            [Environment]::SetEnvironmentVariable($key, $value, "Process")
          }
        }
    }
}

function Get-EnvInt {
    param([string]$Name, [int]$DefaultValue)
    $raw = [Environment]::GetEnvironmentVariable($Name, "Process")
    if (-not $raw) {
        return $DefaultValue
    }
    $parsed = 0
    if ([int]::TryParse($raw, [ref]$parsed)) {
        return $parsed
    }
    return $DefaultValue
}

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptRoot "..")
$sqlFile = Join-Path $projectRoot "scripts\pgvector_optimize.sql"

if (-not (Test-Path $sqlFile)) {
    Write-Error "pgvector_optimize.sql not found at $sqlFile"
    exit 1
}

Import-EnvFile $EnvFile

$databaseUrlValue = if ($DatabaseUrl) { $DatabaseUrl } else { $env:DATABASE_URL }
if (-not $databaseUrlValue) {
    Write-Error "DATABASE_URL not set. Provide -DatabaseUrl or set in env file."
    exit 1
}

$indexTypeValue = if ($IndexType) { $IndexType } elseif ($env:PGVECTOR_INDEX_TYPE) { $env:PGVECTOR_INDEX_TYPE } else { "hnsw" }
$indexTypeValue = $indexTypeValue.ToLower()
if ($indexTypeValue -ne "ivfflat" -and $indexTypeValue -ne "hnsw") {
    $indexTypeValue = "hnsw"
}

$ivfflatListsValue = if ($IvfflatLists -gt 0) { $IvfflatLists } else { Get-EnvInt "PGVECTOR_IVFFLAT_LISTS" 100 }
$hnswMValue = if ($HnswM -gt 0) { $HnswM } else { Get-EnvInt "PGVECTOR_HNSW_M" 16 }
$hnswEfConstructionValue = if ($HnswEfConstruction -gt 0) { $HnswEfConstruction } else { Get-EnvInt "PGVECTOR_HNSW_EF_CONSTRUCTION" 64 }

$setStatements = @(
    "SET sentinelcv.pgv_index_type = '$indexTypeValue';",
    "SET sentinelcv.pgv_ivfflat_lists = '$ivfflatListsValue';",
    "SET sentinelcv.pgv_hnsw_m = '$hnswMValue';",
    "SET sentinelcv.pgv_hnsw_ef_construction = '$hnswEfConstructionValue';"
)

$psqlArgs = @("-v", "ON_ERROR_STOP=1", "-d", $databaseUrlValue)
if ($setStatements.Count -gt 0) {
    $psqlArgs += "-c"
    $psqlArgs += ($setStatements -join " ")
}
$psqlArgs += "-f"
$psqlArgs += $sqlFile

$psqlCommand = Get-Command $Psql -ErrorAction SilentlyContinue
if (-not $psqlCommand) {
  Write-Error "psql not found. Install PostgreSQL client tools or pass -Psql with the full path."
  exit 1
}

Write-Host "Running pgvector optimization (index type: $indexTypeValue)..."
& $Psql @psqlArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "pgvector optimization failed."
    exit $LASTEXITCODE
}

Write-Host "pgvector optimization complete."
