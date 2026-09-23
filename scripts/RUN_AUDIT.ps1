# SentinelCV Audit Framework - PowerShell Quick Start
# Run comprehensive system audit

# Script lives in scripts/; run from project root so audit\ paths resolve.
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "SentinelCV System Audit" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Check Python
try {
    python --version | Out-Null
} catch {
    Write-Host "[ERROR] Python not found. Please install Python 3.10+" -ForegroundColor Red
    pause
    exit 1
}

Write-Host "[1/5] Setting up audit environment..." -ForegroundColor Yellow
if (-not (Test-Path "audit\venv")) {
    Write-Host "Creating virtual environment..." -ForegroundColor Gray
    python -m venv audit\venv
}

Write-Host "[2/5] Installing dependencies..." -ForegroundColor Yellow
& audit\venv\Scripts\Activate.ps1
pip install -q -r audit\requirements.txt

Write-Host "[3/5] Running comprehensive audit..." -ForegroundColor Yellow
Write-Host ""

python audit\audit_cli.py run --environment prod --output html --save

Write-Host ""
Write-Host "[4/5] Generating summary..." -ForegroundColor Yellow

Write-Host "[5/5] Done!" -ForegroundColor Green
Write-Host ""
Write-Host "Report saved to:" -ForegroundColor Cyan
Get-Child audit\audit_report_*.html | Select-Object -First 1 | ForEach-Object {
    Write-Host "  $($_.FullName)" -ForegroundColor White
}
Write-Host ""
Write-Host "Opening HTML report..." -ForegroundColor Cyan
Start-Process $_.FullName

Write-Host ""
Write-Host "Press any key to continue..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
