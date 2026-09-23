@echo off
REM SentinelCV Audit Framework - Quick Start
REM This script runs a comprehensive audit of the SentinelCV system

REM Script lives in scripts\; run from project root so audit\ paths resolve.
cd /d "%~dp0.."

echo ========================================
echo SentinelCV System Audit
echo ========================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10+ from python.org
    pause
    exit /b 1
)

echo [1/5] Setting up audit environment...
if not exist "audit\venv\" (
    echo Creating virtual environment...
    python -m venv audit\venv
)

echo [2/5] Installing dependencies...
call audit\venv\Scripts\activate.bat
pip install -q -r audit\requirements.txt

echo [3/5] Running comprehensive audit...
echo.
python audit\audit_cli.py run --environment prod --output html --save

echo.
echo [4/5] Generating summary...

echo [5/5] Done!
echo.
echo Report saved to: audit\audit_report_*.html
echo Also check: audit\audit_results_*.json (raw data)
echo.
echo Opening HTML report...
start "" audit\audit_report_*.html

pause
