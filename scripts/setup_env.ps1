$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configDir = Join-Path $projectRoot "config"
$envPath = Join-Path $configDir ".env"
$examplePath = Join-Path $configDir ".env.example"

if (-not (Test-Path $configDir)) {
    New-Item -ItemType Directory -Path $configDir -Force | Out-Null
}

if (-not (Test-Path $examplePath)) {
    throw "환경설정 예제 파일이 없습니다: $examplePath"
}

if (Test-Path $envPath) {
    Write-Host "기존 환경설정 파일을 유지합니다: $envPath"
} else {
    Copy-Item -LiteralPath $examplePath -Destination $envPath
    Write-Host "새 환경설정 파일을 만들었습니다: $envPath"
}

Write-Host "실제 API 키와 비밀번호는 .env에 직접 입력하세요."
Write-Host "기존 V1/Beta/Dell 프로젝트의 .env는 복사하지 마세요."
Write-Host "스크립트는 비밀값을 화면이나 로그에 출력하지 않습니다."

Start-Process notepad.exe -ArgumentList $envPath
