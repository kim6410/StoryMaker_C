$ErrorActionPreference = 'Stop'
$TaskName = 'StoryMaker_C_8032_AutoStart'
$Root = 'F:\StoryMaker_C'
$Runner = Join-Path $Root 'scripts\Run-StoryMakerC8032.ps1'

$listener = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if ($listener) {
    $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener[0].OwningProcess)" -ErrorAction SilentlyContinue
    Write-Host "StoryMaker_C 8032 is already running. PID=$($listener[0].OwningProcess)"
    if ($proc) { Write-Host $proc.CommandLine }
    exit 0
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 3
} else {
    Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',"`"$Runner`"") -WindowStyle Hidden
    Start-Sleep -Seconds 3
}

$listener = Get-NetTCPConnection -LocalPort 8032 -State Listen -ErrorAction SilentlyContinue
if (-not $listener) { throw 'StoryMaker_C 8032 failed to start. Check logs\server-8032.' }
Write-Host "StoryMaker_C 8032 started. PID=$($listener[0].OwningProcess)"
