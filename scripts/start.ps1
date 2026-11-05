param([int]$WebPort = 3000, [int]$ApiPort = 8000, [switch]$Production)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExecutable = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonExecutable)) { throw 'Run the README setup steps to create .venv first.' }
$logDirectory = Join-Path $projectRoot 'tmp'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
foreach ($port in @($ApiPort,$WebPort)) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) {
        throw "Port $port is already in use. Stop the existing service or use the manual README commands."
    }
}
& $pythonExecutable -c "from apps.api.database import initialize; initialize()"
if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed.' }
$env:CORS_ORIGINS = "http://127.0.0.1:$WebPort,http://localhost:$WebPort"
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:$ApiPort"
$env:API_BASE_URL = "http://127.0.0.1:$ApiPort"
if ($Production) {
    & node.exe (Join-Path $projectRoot 'scripts\prepare-standalone.mjs')
    if ($LASTEXITCODE -ne 0) { throw 'Run npm.cmd run build before production startup.' }
    $env:APP_ENV = 'production'
    $env:PORT = "$WebPort"
    $env:HOSTNAME = '127.0.0.1'
}
$apiProcess = Start-Process -FilePath $pythonExecutable -ArgumentList '-m','uvicorn','apps.api.main:app','--host','127.0.0.1','--port',$ApiPort -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'api.log') -RedirectStandardError (Join-Path $logDirectory 'api-error.log') -PassThru
$nodeExecutable = (Get-Command node.exe).Source
$nextExecutable = Join-Path $projectRoot 'node_modules\next\dist\bin\next'
if ($Production) {
    $serverExecutable = Join-Path $projectRoot 'apps\web\.next\standalone\apps\web\server.js'
    $webProcess = Start-Process -FilePath $nodeExecutable -ArgumentList $serverExecutable -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'web.log') -RedirectStandardError (Join-Path $logDirectory 'web-error.log') -PassThru
} else {
    $webProcess = Start-Process -FilePath $nodeExecutable -ArgumentList $nextExecutable,'dev','--webpack','--hostname','127.0.0.1','--port',$WebPort -WorkingDirectory (Join-Path $projectRoot 'apps\web') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'web.log') -RedirectStandardError (Join-Path $logDirectory 'web-error.log') -PassThru
}
$workerScript = Join-Path $projectRoot 'scripts\worker-supervisor.ps1'
$workerProcess = Start-Process -FilePath 'powershell.exe' -ArgumentList '-NoProfile','-NonInteractive','-File',('"{0}"' -f $workerScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logDirectory 'worker.log') -RedirectStandardError (Join-Path $logDirectory 'worker-error.log') -PassThru
@{ api = $apiProcess.Id; web = $webProcess.Id; worker = $workerProcess.Id } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $logDirectory 'dev-processes.json')
Write-Output "FASTLANE: http://127.0.0.1:$WebPort | API docs: http://127.0.0.1:$ApiPort/docs"
