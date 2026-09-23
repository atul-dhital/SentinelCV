# ============================================================
# SentinelCV - Start All Services
# Launches Backend, AI Service, and Frontend in separate windows
# ============================================================

param(
    [switch]$EnablePersonFallback,
    [switch]$EnablePersonDistillationCapture,
    [int]$PersonAdapterPort = 9001,
    [string]$PersonAdapterBackend = "inference",
    [string]$PersonSecondaryModel = "rfdetr-nano",
    [switch]$PersonAdapterSkipInstall
)

# Script lives in scripts/; project root is one level up.
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPython  = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PersonAdapterScript = Join-Path $ProjectRoot "scripts\start_person_detector_adapter.ps1"

# Verify Python venv exists
if (-not (Test-Path $VenvPython)) {
    Write-Host "ERROR: Python venv not found at $VenvPython" -ForegroundColor Red
    Write-Host "Run: python -m venv .venv && .venv\Scripts\pip install -r backend\requirements.txt"
    exit 1
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   SentinelCV - Starting All Services"       -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# ── 0. Infrastructure: PostgreSQL + Redis ───────────────────
# Postgres is a Scoop install (NOT a Windows service), so it does not
# auto-start on reboot and must be launched here. Redis IS a Windows service
# (auto-start), so we only ensure it is running.
$PgBin   = "C:\Users\dhita\scoop\apps\postgresql\current\bin"
$PgCtl   = Join-Path $PgBin "pg_ctl.exe"
$PgReady = Join-Path $PgBin "pg_isready.exe"
$PgData  = "C:\Users\dhita\scoop\apps\postgresql\current\data"
$PgLog   = Join-Path $ProjectRoot "tmp_service_logs\postgres.log"

function Test-Listening($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Test-QueueWorker {
    $worker = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like '*advanced_job_worker.py*' } |
        Select-Object -First 1
    return $null -ne $worker
}

# Real readiness: a stale postmaster.pid can hold port 5432 without serving,
# so prefer pg_isready over a bare port check.
function Test-Postgres {
    if (Test-Path $PgReady) {
        & $PgReady -h localhost -p 5432 -U postgres *> $null
        return ($LASTEXITCODE -eq 0)
    }
    return (Test-Listening 5432)
}

Write-Host "[0/4] Ensuring PostgreSQL + Redis are running..." -ForegroundColor Yellow

if (Test-Postgres) {
    Write-Host "      [OK] PostgreSQL already accepting connections on 5432" -ForegroundColor Green
} elseif (Test-Path $PgCtl) {
    New-Item -ItemType Directory -Force -Path (Split-Path $PgLog) | Out-Null
    # Start DETACHED (Start-Process, no -Wait). Bare `& pg_ctl start` blocks the
    # launcher forever when a stale postmaster.pid exists ("another server might
    # be running"). Detach + poll pg_isready instead.
    Start-Process -FilePath $PgCtl -ArgumentList @('-D', $PgData, '-l', $PgLog, '-w', '-t', '20', 'start') -WindowStyle Hidden
    $pgOk = $false
    for ($i = 0; $i -lt 20; $i++) {
        Start-Sleep -Seconds 1
        if (Test-Postgres) { $pgOk = $true; break }
    }
    if ($pgOk) {
        Write-Host "      [OK] PostgreSQL started" -ForegroundColor Green
    } else {
        Write-Host "      [WARN] PostgreSQL did not come up in 20s; check $PgLog" -ForegroundColor Yellow
    }
} else {
    Write-Host "      [WARN] pg_ctl not found at $PgCtl - start PostgreSQL manually" -ForegroundColor Yellow
}

# Ensure the app database + pgvector extension exist (idempotent; no-op if present).
# Guards against a fresh/reset cluster where only the server, not visitor_db, exists.
$Psql = Join-Path $PgBin "psql.exe"
if ((Test-Postgres) -and (Test-Path $Psql)) {
    $hasDb = (& $Psql -h localhost -p 5432 -U postgres -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='visitor_db';" 2>$null)
    if ("$hasDb".Trim() -ne '1') {
        & $Psql -h localhost -p 5432 -U postgres -d postgres -c "CREATE DATABASE visitor_db;" *> $null
        Write-Host "      [OK] Created database visitor_db" -ForegroundColor Green
    }
    & $Psql -h localhost -p 5432 -U postgres -d visitor_db -c "CREATE EXTENSION IF NOT EXISTS vector;" *> $null
    Write-Host "      [OK] visitor_db + pgvector ensured" -ForegroundColor Green
}

$redis = Get-Service -Name 'Redis' -ErrorAction SilentlyContinue
if ($redis) {
    if ($redis.Status -ne 'Running') {
        try { Start-Service 'Redis'; Write-Host "      [OK] Redis service started" -ForegroundColor Green }
        catch { Write-Host "      [WARN] Could not start Redis service: $($_.Exception.Message)" -ForegroundColor Yellow }
    } else {
        Write-Host "      [OK] Redis service running" -ForegroundColor Green
    }
} elseif (Test-Listening 6379) {
    Write-Host "      [OK] Redis already listening on 6379" -ForegroundColor Green
} else {
    Write-Host "      [WARN] Redis service not found - start Redis manually" -ForegroundColor Yellow
}

Start-Sleep -Seconds 1

if ($EnablePersonFallback) {
    if (Test-Listening $PersonAdapterPort) {
        Write-Host "[AI] Person detector adapter already running on $PersonAdapterPort" -ForegroundColor Green
    } elseif (Test-Path $PersonAdapterScript) {
        Write-Host "[AI] Starting person detector adapter on port $PersonAdapterPort..." -ForegroundColor Yellow
        $adapterArgs = @(
            "-ExecutionPolicy", "Bypass",
            "-File", $PersonAdapterScript,
            "-Port", "$PersonAdapterPort",
            "-Backend", $PersonAdapterBackend,
            "-ModelId", $PersonSecondaryModel
        )
        if ($PersonAdapterSkipInstall) {
            $adapterArgs += "-SkipInstall"
        }
        Start-Process powershell -ArgumentList $adapterArgs -WindowStyle Normal
        Start-Sleep -Seconds 5
    } else {
        Write-Host "[WARN] Person detector adapter script missing: $PersonAdapterScript" -ForegroundColor Yellow
    }
}

# ── 1. Backend API (Port 8000) ──────────────────────────────
if (Test-Listening 8000) {
    Write-Host "[1/4] Backend already running on 8000 - skipping" -ForegroundColor Green
} else {
    Write-Host "[1/4] Starting Backend API on port 8000..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$ProjectRoot\backend'; & '$VenvPython' -m uvicorn main:app --reload --host 0.0.0.0 --port 8000"
    ) -WindowStyle Normal
    Start-Sleep -Seconds 3
}

# ── 2. AI Service (Port 8001) ───────────────────────────────
if (Test-Listening 8001) {
    Write-Host "[2/4] AI Service already running on 8001 - skipping" -ForegroundColor Green
    if ($EnablePersonFallback) {
        Write-Host "      [WARN] Existing AI service may not have fallback_fusion env vars. Restart AI service if needed." -ForegroundColor Yellow
    }
} else {
    Write-Host "[2/4] Starting AI Service on port 8001..." -ForegroundColor Yellow
    $aiEnv = ""
    if ($EnablePersonFallback) {
        $secondaryUrl = "http://127.0.0.1:$PersonAdapterPort/infer"
        $aiEnv += "`$env:PERSON_DETECTOR_MODE='fallback_fusion'; "
        $aiEnv += "`$env:PERSON_SECONDARY_INFERENCE_URL='$secondaryUrl'; "
        $aiEnv += "`$env:PERSON_SECONDARY_MODEL='$PersonSecondaryModel'; "
        if ($EnablePersonDistillationCapture) {
            $aiEnv += "`$env:PERSON_DISTILLATION_CAPTURE='1'; "
        }
    }
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$ProjectRoot\ai_services'; $aiEnv & '$VenvPython' -m uvicorn processor:app --host 0.0.0.0 --port 8001"
    ) -WindowStyle Normal
    Start-Sleep -Seconds 3
}

# ── 3. Frontend (Port 3001) ─────────────────────────────────
if (Test-Listening 3001) {
    Write-Host "[3/4] Frontend already running on 3001 - skipping" -ForegroundColor Green
} else {
    Write-Host "[3/4] Starting Frontend on port 3001..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$ProjectRoot\frontend'; npm run dev"
    ) -WindowStyle Normal
}

# ── 4. Redis queue worker ───────────────────────────────────────────────────
if (Test-QueueWorker) {
    Write-Host "[4/4] Queue worker already running - skipping" -ForegroundColor Green
} else {
    Write-Host "[4/4] Starting Redis queue worker..." -ForegroundColor Yellow
    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-Command",
        "Set-Location '$ProjectRoot\backend'; & '$VenvPython' scripts\advanced_job_worker.py --job-type all --poll-interval 1 --pop-timeout 5"
    ) -WindowStyle Normal
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "   All services launched!" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Green
Write-Host ""
Write-Host "  Backend API:    http://localhost:8000/docs"  -ForegroundColor White
Write-Host "  AI Service:     http://localhost:8001/health" -ForegroundColor White
Write-Host "  Frontend:       http://localhost:3001"        -ForegroundColor White
Write-Host ""
Write-Host "  Waiting for services to be ready (up to 90s)..." -ForegroundColor Gray

function Test-Http($url) {
    try { (Invoke-WebRequest -Uri $url -TimeoutSec 3 -UseBasicParsing -ErrorAction Stop).StatusCode -eq 200 }
    catch { $false }
}

# Every dependency the app needs, checked the same way each run.
$checks = [ordered]@{
    'PostgreSQL  (5432)' = { Test-Postgres }
    'Redis       (6379)' = { Test-Listening 6379 }
    'Backend API (8000)' = { Test-Http 'http://localhost:8000/health' }
    'AI Service  (8001)' = { Test-Http 'http://localhost:8001/health' }
    'Frontend    (3001)' = { Test-Http 'http://localhost:3001' }
    'Queue worker' = { Test-QueueWorker }
}
if ($EnablePersonFallback) {
    $adapterHealthUrl = "http://127.0.0.1:$PersonAdapterPort/health"
    $checks["Person adapter ($PersonAdapterPort)"] = { Test-Http $adapterHealthUrl }
}

$status   = @{}
$deadline = (Get-Date).AddSeconds(90)
do {
    $allUp = $true
    foreach ($name in $checks.Keys) {
        if (-not $status[$name]) { $status[$name] = & $checks[$name] }
        if (-not $status[$name]) { $allUp = $false }
    }
    if ($allUp) { break }
    Start-Sleep -Seconds 2
} while ((Get-Date) -lt $deadline)

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "   Service Status" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
$down = 0
foreach ($name in $checks.Keys) {
    if ($status[$name]) {
        Write-Host ("  [UP]   {0}" -f $name) -ForegroundColor Green
    } else {
        Write-Host ("  [DOWN] {0}" -f $name) -ForegroundColor Red
        $down++
    }
}
Write-Host ""
if ($down -eq 0) {
    Write-Host "ALL SERVICES ARE READY!" -ForegroundColor Green
    exit 0
} else {
    Write-Host "$down service(s) NOT ready - check their windows / tmp_service_logs." -ForegroundColor Yellow
    exit 1
}
