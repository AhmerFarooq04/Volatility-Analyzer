param([Parameter(Mandatory=$true)][string]$PythonPath)
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repoPath
$logPath = Join-Path $repoPath 'monthly_refresh.log'
& $PythonPath -m earnings_calculator.monthly --max-symbols 50 *>> $logPath
exit $LASTEXITCODE
