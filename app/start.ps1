param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$port = if ($env:VOC_PORT) { $env:VOC_PORT } else { '8765' }
$url = "http://127.0.0.1:$port"
$running = $false
try {
    $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 2
    $running = $health.session_id -eq 'ses_e420f1c63ffesu6ymnjfYfrdcG'
} catch {}
if (-not $running) {
    if (-not (Test-Path "$root/dist/index.html")) { throw 'Please run npm install and npm run build inside app first.' }
    $logs = Join-Path (Split-Path $root -Parent) 'data/tasks'
    New-Item -ItemType Directory -Path $logs -Force | Out-Null
    $python = (Get-Command python).Source
    $command = '"' + $python + '" "' + $root + '/run.py" 1>"' + $logs + '/voc-server.log" 2>"' + $logs + '/voc-server.err.log"'
    Start-Process -FilePath cmd.exe -ArgumentList '/s /c', ('"' + $command + '"') -WindowStyle Hidden -WorkingDirectory $root
    for ($attempt = 0; $attempt -lt 6; $attempt++) {
        try {
            $health = Invoke-RestMethod "$url/api/health" -TimeoutSec 1
            if ($health.session_id -eq 'ses_e420f1c63ffesu6ymnjfYfrdcG') { $running = $true; break }
        } catch {}
        Start-Sleep -Milliseconds 150
    }
    if (-not $running) { throw "VOC did not start. Read $logs/voc-server.err.log" }
}
Write-Output "VOC: $url"
if (-not $NoBrowser) { Start-Process $url }
