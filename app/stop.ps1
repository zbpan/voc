$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$data = if ($env:VOC_DATA_DIR) { $env:VOC_DATA_DIR } else { Join-Path $root 'runtime' }
$pidFile = Join-Path $data 'server.pid'
if (Test-Path $pidFile) {
    $serverPid = [int](Get-Content $pidFile)
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$serverPid"
    if ($process -and $process.CommandLine.Contains($root) -and $process.CommandLine.Contains('run.py')) {
        Stop-Process -Id $serverPid
        Write-Output 'VOC stopped. Unfinished jobs will resume on next start.'
    }
    Remove-Item $pidFile -ErrorAction SilentlyContinue
}
