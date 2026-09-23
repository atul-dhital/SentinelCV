param(
    [int]$Port = 9001,
    [string]$Backend = "inference",
    [string]$ModelId = "rfdetr-nano",
    [string]$PythonExe = "",
    [switch]$SkipInstall
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvDir = Join-Path $ProjectRoot ".person-detector-adapter-venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$ServerScript = Join-Path $ProjectRoot "scripts\person_detector_adapter_server.py"

function Resolve-Python {
    if ($PythonExe -and (Test-Path $PythonExe)) {
        return $PythonExe
    }
    $candidates = @(
        @{ Cmd = "py"; Args = @("-3.12", "-c", "import sys; print(sys.executable)") },
        @{ Cmd = "py"; Args = @("-3.11", "-c", "import sys; print(sys.executable)") },
        @{ Cmd = "python"; Args = @("-c", "import sys; print(sys.executable)") }
    )
    foreach ($candidate in $candidates) {
        try {
            $resolved = & $candidate.Cmd @($candidate.Args) 2>$null
            if ($LASTEXITCODE -eq 0 -and $resolved -and (Test-Path $resolved.Trim())) {
                return $resolved.Trim()
            }
        } catch {
            continue
        }
    }
    throw "No suitable Python found. Install Python 3.11/3.12 or pass -PythonExe."
}

function Test-Listening($port) {
    $null -ne (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

if (Test-Listening $Port) {
    Write-Host "Person detector adapter already listening on $Port" -ForegroundColor Green
    exit 0
}

if (-not (Test-Path $VenvPython)) {
    $BasePython = Resolve-Python
    Write-Host "Creating adapter venv with $BasePython" -ForegroundColor Yellow
    & $BasePython -m venv $VenvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create venv at $VenvDir"
    }
}

if (-not $SkipInstall) {
    Write-Host "Installing adapter dependencies..." -ForegroundColor Yellow
    & $VenvPython -m pip install --upgrade pip
    & $VenvPython -m pip install fastapi uvicorn python-multipart pillow numpy opencv-python requests
    if ($Backend -eq "inference") {
        & $VenvPython -m pip install inference
    } elseif ($Backend -in @("sdk", "inference_sdk", "roboflow_http")) {
        & $VenvPython -m pip install inference-sdk
    } elseif ($Backend -eq "ultralytics") {
        & $VenvPython -m pip install ultralytics
    }
}

$env:PERSON_ADAPTER_BACKEND = $Backend
$env:PERSON_SECONDARY_MODEL = $ModelId
$env:PERSON_ADAPTER_PORT = "$Port"

Write-Host "Starting person detector adapter on http://127.0.0.1:$Port/infer" -ForegroundColor Green
Write-Host "Backend=$Backend Model=$ModelId" -ForegroundColor Green
Start-Process powershell -ArgumentList @(
    "-NoExit",
    "-Command",
    "Set-Location '$ProjectRoot'; `$env:PERSON_ADAPTER_BACKEND='$Backend'; `$env:PERSON_SECONDARY_MODEL='$ModelId'; `$env:PERSON_ADAPTER_PORT='$Port'; & '$VenvPython' '$ServerScript'"
) -WindowStyle Normal

Write-Host "Set SentinelCV AI env:" -ForegroundColor Cyan
Write-Host "`$env:PERSON_DETECTOR_MODE='fallback_fusion'"
Write-Host "`$env:PERSON_SECONDARY_INFERENCE_URL='http://127.0.0.1:$Port/infer'"
Write-Host "`$env:PERSON_DISTILLATION_CAPTURE='1'"
