param([string]$PythonPath, [string]$UserId = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
if (-not $PythonPath) {
    $localPython = Join-Path $repoPath '.venv\Scripts\python.exe'
    $parentPython = Join-Path (Split-Path -Parent $repoPath) 'venv\Scripts\python.exe'
    $PythonPath = if (Test-Path -LiteralPath $localPython) { $localPython } else { $parentPython }
}
$PythonPath = (Resolve-Path -LiteralPath $PythonPath).Path
$runner = Join-Path $PSScriptRoot 'refresh-monthly.ps1'
$arguments = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + $runner + '" -PythonPath "' + $PythonPath + '"'
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $arguments -WorkingDirectory $repoPath
# Daily check: new-month work starts on the first; later checks resume paused work.
# After completion, ensure_current exits without any market-data requests.
$firstRun = (Get-Date).Date.AddHours(7)
if ($firstRun -le (Get-Date)) { $firstRun = $firstRun.AddDays(1) }
$trigger = New-ScheduledTaskTrigger -Once -At $firstRun -RepetitionInterval (New-TimeSpan -Hours 2)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45)
$principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName 'VolatilityAnalyzer-MonthlyEarnings' -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Description 'Build or resume current month earnings CSV; no orders or options analysis.' -Force
