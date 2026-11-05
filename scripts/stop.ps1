$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$processFile = Join-Path $projectRoot 'tmp\dev-processes.json'
if (-not (Test-Path -LiteralPath $processFile)) { Write-Output 'No saved FASTLANE processes.'; exit }
$saved = Get-Content -LiteralPath $processFile | ConvertFrom-Json
foreach ($processId in @($saved.api, $saved.web, $saved.worker)) {
    if (-not $processId) { continue }
    $process = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction SilentlyContinue
    if ($process -and $process.CommandLine -and ($process.CommandLine.Contains('apps.api.main:app') -or $process.CommandLine.Contains('ml.live.refresh') -or ($process.CommandLine.Contains('worker-supervisor.ps1') -and $process.CommandLine.Contains($projectRoot)) -or (($process.CommandLine.Contains('next') -or $process.CommandLine.Contains('standalone')) -and $process.CommandLine.Contains($projectRoot)))) {
        $ownedTree = @($processId)
        for ($treeIndex=0; $treeIndex -lt $ownedTree.Count; $treeIndex++) {
            $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $($ownedTree[$treeIndex])" -ErrorAction SilentlyContinue
            foreach ($child in $children) { $ownedTree += $child.ProcessId }
        }
        [array]::Reverse($ownedTree)
        foreach ($ownedId in $ownedTree) { Stop-Process -Id $ownedId -ErrorAction SilentlyContinue }
    }
}
Remove-Item -LiteralPath $processFile
Write-Output 'Stopped saved FASTLANE dev processes.'
