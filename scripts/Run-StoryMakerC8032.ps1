$ErrorActionPreference = 'Stop'
$Root = 'F:\StoryMaker_C'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
$LogDir = Join-Path $Root 'logs\server-8032'
$PidFile = Join-Path $LogDir 'storymaker-c-8032.pid'
$StdoutLog = Join-Path $LogDir 'stdout.log'
$StderrLog = Join-Path $LogDir 'stderr.log'

New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
Set-Location $Root

if (-not (Test-Path $Python)) {
    throw "Python virtual environment not found: $Python"
}

$existing = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $owner = Get-CimInstance Win32_Process -Filter "ProcessId=$($existing[0].OwningProcess)" -ErrorAction SilentlyContinue
    if ($owner -and $owner.CommandLine -match 'uvicorn\s+app\.main:app' -and $owner.CommandLine -match '(--port\s+8032|--port=8032)') {
        Add-Content -Path $StdoutLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Already running PID $($owner.ProcessId)."
        exit 0
    }
    throw "Port 8032 is already in use by PID $($existing[0].OwningProcess)."
}

$process = Start-Process -FilePath $Python -ArgumentList @('-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8032') -WorkingDirectory $Root -RedirectStandardOutput $StdoutLog -RedirectStandardError $StderrLog -PassThru -WindowStyle Hidden
Set-Content -Path $PidFile -Value $process.Id -Encoding ASCII
Add-Content -Path $StdoutLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Started PID $($process.Id)."

try {
    Wait-Process -Id $process.Id
    $process.Refresh()
    $exitCode = $process.ExitCode
    Add-Content -Path $StdoutLog -Value "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Exited PID $($process.Id), code $exitCode."
    exit $exitCode
}
finally {
    Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
}
