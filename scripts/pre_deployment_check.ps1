<#
.SYNOPSIS
  SentinelCV Pre-Deployment Check (PowerShell)
.DESCRIPTION
  Local staging readiness checks for Windows environments.
.PARAMETER EnvFile
  Path to the env file to load (default: .env.staging)
.EXAMPLE
  .\scripts\pre_deployment_check.ps1 -EnvFile .env.staging
#>

param(
    [string]$EnvFile = ".env.staging"
)

$Passed = 0
$Failed = 0
$Warnings = 0

function Write-Status {
    param(
        [string]$Level,
        [string]$Message
    )

    switch ($Level) {
        "PASS" { Write-Host "[PASS] $Message" -ForegroundColor Green; $script:Passed++ }
        "FAIL" { Write-Host "[FAIL] $Message" -ForegroundColor Red; $script:Failed++ }
        "WARN" { Write-Host "[WARN] $Message" -ForegroundColor Yellow; $script:Warnings++ }
        default { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
    }
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Load-EnvFile {
    param([string]$Path)

    if (-not (Test-Path $Path)) {
        Write-Status "WARN" "Env file not found: $Path"
        return
    }

    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if (-not $line -or $line.StartsWith("#")) { return }
        if ($line -notmatch "=") { return }

        $parts = $line.Split("=", 2)
        $key = $parts[0].Trim()
        $value = $parts[1].Trim()
        Set-Item -Path "Env:$key" -Value $value
    }

    Write-Status "PASS" "Loaded env file: $Path"
}

Write-Host "SentinelCV Pre-Deployment Check (PowerShell)" -ForegroundColor Cyan
Write-Host "Timestamp: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")" -ForegroundColor Cyan

Load-EnvFile -Path $EnvFile

Write-Section "System Requirements"

$os = [System.Environment]::OSVersion.VersionString
Write-Status "PASS" "Operating System: $os"

$driveName = (Get-Location).Drive.Name
$drive = Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue
if ($drive -and $drive.Free -gt 5GB) {
    $freeGB = [Math]::Round($drive.Free / 1GB, 2)
    Write-Status "PASS" "Disk space available: $freeGB GB"
} else {
    Write-Status "WARN" "Low disk space on $driveName"
}

$osInfo = Get-CimInstance Win32_OperatingSystem
$freeMemMB = [Math]::Round($osInfo.FreePhysicalMemory / 1024, 0)
if ($freeMemMB -ge 2048) {
    Write-Status "PASS" "Available memory: $freeMemMB MB"
} else {
    Write-Status "WARN" "Low memory: $freeMemMB MB"
}

Write-Section "Dependency Checks"

$pythonCmd = Get-Command python -ErrorAction SilentlyContinue
if ($pythonCmd) {
    Write-Status "PASS" "Python found: $($pythonCmd.Path)"
} else {
    Write-Status "FAIL" "Python not found on PATH"
}

$dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
if ($dockerCmd) {
    Write-Status "PASS" "Docker found: $($dockerCmd.Path)"
    try {
        $composeVersion = docker compose version 2>$null
        if ($composeVersion) {
            Write-Status "PASS" "Docker Compose available"
        } else {
            Write-Status "WARN" "Docker Compose not available"
        }
    } catch {
        Write-Status "WARN" "Docker Compose not available"
    }
} else {
    Write-Status "WARN" "Docker not found"
}

$psqlCmd = Get-Command psql -ErrorAction SilentlyContinue
if ($psqlCmd) {
    Write-Status "PASS" "psql found: $($psqlCmd.Path)"
} else {
    Write-Status "WARN" "psql not found"
}

$gitCmd = Get-Command git -ErrorAction SilentlyContinue
if ($gitCmd) {
    Write-Status "PASS" "git found: $($gitCmd.Path)"
} else {
    Write-Status "WARN" "git not found"
}

Write-Section "Application Setup"

if (Test-Path $EnvFile) {
    Write-Status "PASS" "Env file exists: $EnvFile"
} else {
    Write-Status "WARN" "Env file missing: $EnvFile"
}

foreach ($dir in @("backend", "frontend", "tests")) {
    if (Test-Path $dir) {
        Write-Status "PASS" "$dir directory found"
    } else {
        Write-Status "FAIL" "$dir directory not found"
    }
}

Write-Section "Database Connectivity"

if ($psqlCmd -and $env:DATABASE_URL) {
    try {
        psql $env:DATABASE_URL -c "SELECT 1" 1>$null 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Status "PASS" "Database connection successful"
        } else {
            Write-Status "WARN" "Database connection failed"
        }
    } catch {
        Write-Status "WARN" "Database connection failed"
    }
} else {
    Write-Status "WARN" "DATABASE_URL or psql not available"
}

Write-Section "Port Availability"

$ports = @(8000, 8001, 5432, 6379, 3001, 9090)
foreach ($port in $ports) {
    $inUse = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($inUse) {
        Write-Status "WARN" "Port $port is in use"
    } else {
        Write-Status "PASS" "Port $port is available"
    }
}

Write-Section "Deployment Files"

$files = @(
    "docker-compose.yml",
    "docker-compose.prod.yml",
    "docker-compose.prod-green.yml",
    "nginx.prod.conf",
    "scripts\validate_env.py",
    "scripts\setup_postgres_production.py"
)

foreach ($file in $files) {
    if (Test-Path $file) {
        Write-Status "PASS" "Found $file"
    } else {
        Write-Status "WARN" "Missing $file"
    }
}

Write-Section "Summary"
Write-Host "Passed:  $Passed" -ForegroundColor Green
Write-Host "Failed:  $Failed" -ForegroundColor Red
Write-Host "Warnings: $Warnings" -ForegroundColor Yellow

if ($Failed -eq 0) {
    Write-Host "System is ready for local staging." -ForegroundColor Green
    exit 0
}

Write-Host "System is NOT ready. Fix failures before proceeding." -ForegroundColor Red
exit 1
