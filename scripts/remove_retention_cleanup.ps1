<#
.SYNOPSIS
  Removes the scheduled task for SentinelCV retention cleanup.
.PARAMETER TaskName
  Task name to remove (default: SentinelCV-RetentionCleanup).
#>

param(
    [string]$TaskName = "SentinelCV-RetentionCleanup"
)

schtasks /Delete /TN $TaskName /F
