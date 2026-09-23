<
.SYNOPSIS
  Removes the SentinelCV cache/session cleanup scheduled task.
.PARAMETER TaskName
  Task name to remove (default: SentinelCV-CacheCleanup).
#>

param(
    [string]$TaskName = "SentinelCV-CacheCleanup"
)

try {
    schtasks /Query /TN $TaskName 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "Task '$TaskName' not found." -ForegroundColor Yellow
        exit 0
    }

    schtasks /Delete /TN $TaskName /F | Out-Null
    Write-Host "Removed scheduled task: $TaskName" -ForegroundColor Green
    exit 0
} catch {
    Write-Error "Failed to remove scheduled task: $TaskName"
    exit 1
}
