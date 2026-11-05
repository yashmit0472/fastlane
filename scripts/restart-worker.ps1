param([ValidateRange(0,30)][int]$ArchiveLimit=1)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectRoot 'tmp\dev-processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { throw 'Use scripts/start.ps1 to start FASTLANE first.' }
$saved = Get-Content -LiteralPath $processFile | ConvertFrom-Json
if ($saved.worker) {
    $workerRoot = Get-CimInstance Win32_Process -Filter "ProcessId = $($saved.worker)" -ErrorAction SilentlyContinue
    if ($workerRoot) {
        if ((-not $workerRoot.CommandLine.Contains('ml.live.refresh') -and -not $workerRoot.CommandLine.Contains('worker-supervisor.ps1')) -or -not $workerRoot.CommandLine.Contains($projectRoot)) { throw 'Recorded worker PID belongs to another process; refusing to stop it.' }
        $workerTree = @($workerRoot.ProcessId)
        for ($workerIndex=0; $workerIndex -lt $workerTree.Count; $workerIndex++) {
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($workerTree[$workerIndex])" -ErrorAction SilentlyContinue
            foreach ($child in $children) { $workerTree += $child.ProcessId }
        }
        [array]::Reverse($workerTree)
        foreach ($ownedWorkerId in $workerTree) { Stop-Process -Id $ownedWorkerId -ErrorAction SilentlyContinue }
    }
}
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
$logDirectory = Join-Path $projectRoot 'tmp'
$workerScript = Join-Path $projectRoot 'scripts\worker-supervisor.ps1'
$newWorker = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-NonInteractive','-File',('"{0}"' -f $workerScript),'-ArchiveLimit',$ArchiveLimit -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'worker.log') -RedirectStandardError (Join-Path $logDirectory 'worker-error.log') -PassThru
$saved.worker = $newWorker.Id
$saved | ConvertTo-Json | Set-Content -LiteralPath $processFile
Write-Output "Restarted FASTLANE refresh worker $($newWorker.Id); website and API remain running."
