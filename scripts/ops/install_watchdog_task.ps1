<#
.SYNOPSIS
    Register / update the ERP watchdog scheduled task (observability, plan item S2).

.DESCRIPTION
    Runs scripts/ops/watchdog.py every N minutes. It checks:
      backend /api/health, /api/health/ready, ARQ worker, web entry,
      backup freshness, free disk space (optionally: NSSM service states).

    Defaults to the SYSTEM account (no logon needed, no stored password).
    Run this from an ELEVATED PowerShell: creating a scheduled task is denied
    for a non-elevated user on this machine ("Access is denied").

    NOTE: keep this file ASCII-only; Windows PowerShell 5.1 decodes BOM-less
    script files with the ANSI code page and would mangle non-ASCII text.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts/ops/install_watchdog_task.ps1
    powershell -ExecutionPolicy Bypass -File scripts/ops/install_watchdog_task.ps1 -AsCurrentUser
    powershell -ExecutionPolicy Bypass -File scripts/ops/install_watchdog_task.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$TaskName = 'erp-watchdog',
    [int]$IntervalMinutes = 5,
    [switch]$AsCurrentUser,
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$cmdPath = Join-Path $root 'scripts\ops\watchdog_task.cmd'

if ($Uninstall) {
    schtasks.exe /Delete /TN $TaskName /F | Out-Null
    Write-Host "Removed scheduled task: $TaskName"
    exit 0
}

if (-not (Test-Path $cmdPath)) { throw "not found: $cmdPath" }

# Plain string concatenation (no embedded backtick escapes) so quoting survives.
$action = 'cmd.exe /c "' + $cmdPath + '"'

if ($AsCurrentUser) {
    $result = schtasks.exe /Create /TN $TaskName /TR $action /SC MINUTE /MO $IntervalMinutes /F
} else {
    $result = schtasks.exe /Create /TN $TaskName /TR $action /SC MINUTE /MO $IntervalMinutes /RU SYSTEM /RL HIGHEST /F
}
Write-Host $result

schtasks.exe /Query /TN $TaskName /FO LIST | Select-String 'TaskName|Status|Schedule|Next Run|Task To Run'
Write-Host ''
Write-Host 'Manual verification:'
Write-Host "  schtasks.exe /Run /TN $TaskName"
Write-Host '  then inspect logs\watchdog.log and logs\watchdog_state.json'
