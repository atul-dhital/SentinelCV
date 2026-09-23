<#
.SYNOPSIS
  Run a local live webcam liveness check against SentinelCV.
.DESCRIPTION
  Authenticates against the backend, optionally creates a temporary visitor log
  for the supplied user, captures focused webcam frames, and verifies one or
  more liveness challenges end to end.
.EXAMPLE
  .\scripts\run_live_liveness_check.ps1 -Email live.user@sentinelcv.dev -Password 'Passw0rd!'
#>

param(
    [Parameter(Mandatory = $true)]
    [string]$Email,

    [Parameter(Mandatory = $true)]
    [string]$Password,

    [string[]]$Challenges = @("blink", "head_turn", "smile"),
    [string]$ApiBaseUrl = "http://127.0.0.1:8000/api/v1",
    [string]$Python = "c:/python314/python.exe",
    [int]$CameraIndex = 0,
    [string]$VisitorLogId = "",
    [string]$SourceVideo = "live_liveness_local_test",
    [string]$TempDirectory = "tmp_service_logs/live-liveness",
    [switch]$KeepArtifacts
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$helperPath = Join-Path $projectRoot "scripts\live_liveness_helper.py"
$artifactRoot = Join-Path $projectRoot $TempDirectory
$validChallenges = @("blink", "head_turn", "smile")

$challengeConfigs = @{
    blink = @{ intervalMs = 350; durationMs = 5600; maxFrames = 14; prompt = "Look directly at the camera and blink naturally two or three times." }
    head_turn = @{ intervalMs = 450; durationMs = 5600; maxFrames = 10; prompt = "Turn your head left, then right, while keeping your face centered." }
    smile = @{ intervalMs = 450; durationMs = 5000; maxFrames = 10; prompt = "Smile naturally and hold it for two or three seconds." }
}

function Write-Section {
    param([string]$Title)
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host $Title -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
}

function Invoke-ApiJson {
    param(
        [string]$Method,
        [string]$Uri,
        [object]$Body,
        [hashtable]$Headers,
        [Microsoft.PowerShell.Commands.WebRequestSession]$WebSession
    )

    $payload = if ($null -ne $Body) { $Body | ConvertTo-Json -Depth 6 } else { $null }
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -WebSession $WebSession -Body $payload -ContentType "application/json" -TimeoutSec 180
}

if (-not (Test-Path $helperPath)) {
    throw "Missing helper script: $helperPath"
}

if (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
    throw "Python executable not found: $Python"
}

$normalizedChallenges = @()
foreach ($challenge in $Challenges) {
    $normalized = $challenge.Trim().ToLowerInvariant()
    if ($validChallenges -notcontains $normalized) {
        throw "Unsupported challenge '$challenge'. Valid values: $($validChallenges -join ', ')"
    }
    $normalizedChallenges += $normalized
}

New-Item -ItemType Directory -Path $artifactRoot -Force | Out-Null

Write-Section "Authenticate"

$session = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$loginResponse = Invoke-ApiJson -Method "Post" -Uri "$ApiBaseUrl/auth/login" -Body @{
    email = $Email
    password = $Password
} -Headers @{} -WebSession $session

if (-not $loginResponse.access_token) {
    throw "Login response did not include an access token."
}

$headers = @{ Authorization = "Bearer $($loginResponse.access_token)" }
Write-Host "Authenticated as $Email" -ForegroundColor Green

if ([string]::IsNullOrWhiteSpace($VisitorLogId)) {
    Write-Section "Create Temporary Visitor Log"
    $createdLogJson = & $Python $helperPath create-visitor-log --email $Email --source-video $SourceVideo
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create a temporary visitor log."
    }

    $createdLog = $createdLogJson | ConvertFrom-Json
    $VisitorLogId = $createdLog.visitor_log_id
    Write-Host "Temporary visitor log: $VisitorLogId" -ForegroundColor Green
} else {
    Write-Host "Using provided visitor log: $VisitorLogId" -ForegroundColor Green
}

$results = @()

foreach ($challenge in $normalizedChallenges) {
    $config = $challengeConfigs[$challenge]
    $artifactPath = Join-Path $artifactRoot "$challenge-frames.json"

    Write-Section "Challenge: $challenge"
    Write-Host $config.prompt -ForegroundColor Yellow
    [void](Read-Host "Press Enter when you are ready to start capture")

    $startResponse = Invoke-ApiJson -Method "Post" -Uri "$ApiBaseUrl/liveness/challenge/start" -Body @{
        visitor_log_id = $VisitorLogId
        challenge_type = $challenge
    } -Headers $headers -WebSession $session

    $challengeId = $startResponse.challenge_id
    if ([string]::IsNullOrWhiteSpace($challengeId)) {
        throw "Challenge start for '$challenge' did not return a challenge_id."
    }

    & $Python $helperPath capture-frames --output $artifactPath --camera-index $CameraIndex --duration-ms $config.durationMs --interval-ms $config.intervalMs --max-frames $config.maxFrames --width 320 --height 240 --face-focus
    if ($LASTEXITCODE -ne 0) {
        throw "Webcam capture failed for challenge '$challenge'."
    }

    $capturePayload = Get-Content $artifactPath -Raw | ConvertFrom-Json
    $frames = @($capturePayload.frames)
    if ($frames.Count -eq 0) {
        throw "No frames were captured for challenge '$challenge'."
    }

    $verifyBody = if ($frames.Count -gt 1) {
        @{ challenge_id = $challengeId; video_frames = $frames }
    } else {
        @{ challenge_id = $challengeId; video_frame = $frames[0] }
    }

    $verifyResponse = Invoke-ApiJson -Method "Post" -Uri "$ApiBaseUrl/liveness/challenge/verify" -Body $verifyBody -Headers $headers -WebSession $session
    $method = if ($verifyResponse.details.method) { [string]$verifyResponse.details.method } else { "unknown" }
    $confidence = if ($null -ne $verifyResponse.confidence) { [double]$verifyResponse.confidence } else { 0.0 }
    $verified = [bool]$verifyResponse.verified

    $result = [PSCustomObject]@{
        challenge = $challenge
        verified = $verified
        confidence = $confidence
        method = $method
        frameCount = $frames.Count
        challengeId = $challengeId
    }
    $results += $result

    if ($verified) {
        Write-Host ("PASS {0}: confidence={1:P1}, method={2}, frames={3}" -f $challenge, $confidence, $method, $frames.Count) -ForegroundColor Green
    } else {
        Write-Host ("WARN {0}: confidence={1:P1}, method={2}, frames={3}" -f $challenge, $confidence, $method, $frames.Count) -ForegroundColor Yellow
    }
}

$summaryPath = Join-Path $artifactRoot ("summary-" + (Get-Date -Format "yyyyMMdd-HHmmss") + ".json")
$results | ConvertTo-Json -Depth 5 | Set-Content -Path $summaryPath -Encoding UTF8

if (-not $KeepArtifacts) {
    Get-ChildItem -Path $artifactRoot -Filter "*-frames.json" -ErrorAction SilentlyContinue | Remove-Item -Force
}

Write-Section "Summary"
$results | Format-Table challenge, verified, confidence, method, frameCount -AutoSize
Write-Host "Summary JSON: $summaryPath" -ForegroundColor Cyan

if ($results.Where({ -not $_.verified }).Count -gt 0) {
    exit 1
}

exit 0