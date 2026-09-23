@echo off
setlocal

set "PROJECT_ROOT=%~dp0"
set "START_SCRIPT=%PROJECT_ROOT%scripts\START_ALL.ps1"

if not exist "%START_SCRIPT%" (
    echo ERROR: Could not find %START_SCRIPT%
    exit /b 1
)

where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo ERROR: powershell.exe not found.
    exit /b 1
)

echo Starting SentinelCV services...
echo.
echo This launches:
echo   - PostgreSQL, if available through local Scoop pg_ctl
echo   - Redis, if installed as a Windows service or already listening
echo   - Backend API on http://localhost:8000
echo   - AI service on http://localhost:8001
echo   - Frontend on http://localhost:3001
echo.

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%START_SCRIPT%"
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo SentinelCV startup failed with exit code %EXIT_CODE%.
    exit /b %EXIT_CODE%
)

echo.
echo SentinelCV startup command completed.
exit /b 0
