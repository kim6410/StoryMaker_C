$ErrorActionPreference = 'Stop'
$Root = 'F:\StoryMaker_C'
& (Join-Path $Root 'scripts\Stop-StoryMakerC8032.ps1')
Start-Sleep -Seconds 2
& (Join-Path $Root 'scripts\Start-StoryMakerC8032.ps1')
