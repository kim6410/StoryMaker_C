$ErrorActionPreference = 'Stop'
$TaskName = 'StoryMaker_C_8032_AutoStart'
$Root = 'F:\StoryMaker_C'
$Python = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Python)) { throw "Python not found: $Python" }
$action = New-ScheduledTaskAction -Execute $Python -Argument '-m uvicorn app.main:app --host 127.0.0.1 --port 8032' -WorkingDirectory $Root
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $triggerStartup -Settings $settings -Principal $principal -Description 'Automatically runs StoryMaker_C FastAPI/Uvicorn on 127.0.0.1:8032 at Windows startup and restarts it after failures.' -Force | Out-Null
Write-Host "Installed scheduled task: $TaskName"
Get-ScheduledTask -TaskName $TaskName | Select-Object TaskName,State,TaskPath | Format-List
