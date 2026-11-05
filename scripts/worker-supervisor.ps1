param([ValidateRange(0,30)][int]$ArchiveLimit=1)
$ErrorActionPreference = 'Continue'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
Set-Location -LiteralPath $projectRoot
while ($true) {
    & $pythonExecutable -m ml.live.refresh --loop --archive-limit $ArchiveLimit
    $workerExitCode = $LASTEXITCODE
    Write-Output "$(Get-Date -Format o) Refresh worker exited ($workerExitCode); restarting in 15 seconds."
    Start-Sleep -Seconds 15
}
