param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $projectRoot

Write-Host "Generating backend coverage report..."
& $Python -m pytest backend/tests --cov=backend --cov-report=xml --cov-report=html

Write-Host "Running Bandit security scan..."
try {
    & $Python -m bandit -r backend -f json -o bandit-report.json
} catch {
    Write-Warning "Bandit scan completed with findings or bandit is unavailable."
}

Write-Host "Running Pylint quality scan..."
try {
    & $Python -m pylint backend --exit-zero --output-format=json > pylint-report.json
} catch {
    Write-Warning "Pylint scan completed with findings or pylint is unavailable."
}

Write-Host "Artifacts:"
Write-Host "  coverage.xml"
Write-Host "  htmlcov/index.html"
Write-Host "  bandit-report.json"
Write-Host "  pylint-report.json"
