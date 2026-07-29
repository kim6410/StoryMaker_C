$listener = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if (-not $listener) {
    Write-Host 'STOPPED: StoryMaker_C 8032 is not listening.'
    exit 1
}
$pidFound = $listener[0].OwningProcess
$proc = Get-CimInstance Win32_Process -Filter "ProcessId=$pidFound" -ErrorAction SilentlyContinue
Write-Host "RUNNING: StoryMaker_C 8032 is listening. PID=$pidFound"
if ($proc) { Write-Host "CommandLine: $($proc.CommandLine)" }
try {
    $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8032/docs' -UseBasicParsing -TimeoutSec 10
    Write-Host "HTTP: $($response.StatusCode) /docs"
    exit 0
} catch {
    try {
        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:8032/' -UseBasicParsing -TimeoutSec 10
        Write-Host "HTTP: $($response.StatusCode) /"
        exit 0
    } catch {
        Write-Host "HTTP check failed: $($_.Exception.Message)"
        exit 2
    }
}
