$ErrorActionPreference = 'Stop'
$TaskName = 'StoryMaker_C_8032_AutoStart'
$listener = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    Write-Host 'StoryMaker_C 8032 is not running.'
    exit 0
}
$pidToStop = $listener[0].OwningProcess
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidToStop" -ErrorAction SilentlyContinue
if (-not $proc) { throw "PID $pidToStop could not be inspected." }
if ($proc.CommandLine -notmatch 'uvicorn\s+app\.main:app' -or $proc.CommandLine -notmatch '(--port\s+8032|--port=8032)') {
    throw "Refusing to stop PID $pidToStop because it is not the StoryMaker_C 8032 uvicorn process. CommandLine: $($proc.CommandLine)"
}
Stop-Process -Id $pidToStop -Force
Start-Sleep -Seconds 2
$still = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if ($still) { throw "Port 8032 is still listening after stopping PID $pidToStop." }
Write-Host "StoryMaker_C 8032 stopped. PID=$pidToStop"
