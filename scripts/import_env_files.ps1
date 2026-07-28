$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$configDir = Join-Path $projectRoot "config"
$targetEnv = Join-Path $configDir ".env"
$exampleEnv = Join-Path $configDir ".env.example"
$backupDir = Join-Path $configDir "backups"

if (-not (Test-Path -LiteralPath $exampleEnv)) {
    throw "Missing environment template: $exampleEnv"
}

if (-not (Test-Path -LiteralPath $targetEnv)) {
    Copy-Item -LiteralPath $exampleEnv -Destination $targetEnv
}

function Read-EnvMap {
    param([Parameter(Mandatory = $true)][string]$Path)

    $result = [ordered]@{}
    foreach ($line in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith("#")) { continue }

        $index = $trimmed.IndexOf("=")
        if ($index -lt 1) { continue }

        $key = $trimmed.Substring(0, $index).Trim()
        $value = $trimmed.Substring($index + 1)
        if ($key -match '^[A-Za-z_][A-Za-z0-9_]*$') {
            $result[$key] = $value
        }
    }
    return $result
}

function Get-AllowedKeys {
    param([Parameter(Mandatory = $true)][string]$Path)

    $keys = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($key in (Read-EnvMap -Path $Path).Keys) {
        [void]$keys.Add($key)
    }
    return $keys
}

$dialog = New-Object System.Windows.Forms.OpenFileDialog
$dialog.Title = "Select .env or configuration files to import into StoryMaker_C"
$dialog.Filter = "Environment files|.env;*.env;*.secret;*.txt|All files|*.*"
$dialog.Multiselect = $true
$dialog.CheckFileExists = $true

$result = $dialog.ShowDialog()
if ($result -ne [System.Windows.Forms.DialogResult]::OK -or $dialog.FileNames.Count -eq 0) {
    Write-Host "No files selected."
    exit 0
}

$allowedKeys = Get-AllowedKeys -Path $exampleEnv
$currentMap = Read-EnvMap -Path $targetEnv
$importedMap = [ordered]@{}
$ignoredKeys = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

foreach ($sourcePath in $dialog.FileNames) {
    if ($sourcePath -ieq $targetEnv) { continue }

    $sourceMap = Read-EnvMap -Path $sourcePath
    foreach ($key in $sourceMap.Keys) {
        if (-not $allowedKeys.Contains($key)) {
            [void]$ignoredKeys.Add($key)
            continue
        }

        $value = $sourceMap[$key]
        if ([string]::IsNullOrWhiteSpace($value)) { continue }
        $importedMap[$key] = $value
    }
}

if ($importedMap.Count -eq 0) {
    Write-Host "No allowed non-empty settings were found."
    Write-Host "No secret values were printed."
    exit 0
}

$overwrite = [System.Windows.Forms.MessageBox]::Show(
    "Overwrite existing non-empty StoryMaker_C values?`n`nYes: overwrite existing values`nNo: fill empty values only",
    "Environment merge mode",
    [System.Windows.Forms.MessageBoxButtons]::YesNoCancel,
    [System.Windows.Forms.MessageBoxIcon]::Question
)

if ($overwrite -eq [System.Windows.Forms.DialogResult]::Cancel) {
    Write-Host "Cancelled by user."
    exit 0
}

$overwriteExisting = $overwrite -eq [System.Windows.Forms.DialogResult]::Yes

if (-not (Test-Path -LiteralPath $backupDir)) {
    New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
}

$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupPath = Join-Path $backupDir ".env_before_import_$timestamp.bak"
Copy-Item -LiteralPath $targetEnv -Destination $backupPath

$lines = Get-Content -LiteralPath $targetEnv -Encoding UTF8
$updatedKeys = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)
$output = New-Object System.Collections.Generic.List[string]

foreach ($line in $lines) {
    $trimmed = $line.Trim()
    if (-not $trimmed -or $trimmed.StartsWith("#") -or -not $trimmed.Contains("=")) {
        $output.Add($line)
        continue
    }

    $index = $trimmed.IndexOf("=")
    if ($index -lt 1) {
        $output.Add($line)
        continue
    }

    $key = $trimmed.Substring(0, $index).Trim()
    if (-not $importedMap.Contains($key)) {
        $output.Add($line)
        continue
    }

    $existingValue = $trimmed.Substring($index + 1)
    if ($overwriteExisting -or [string]::IsNullOrWhiteSpace($existingValue)) {
        $output.Add("$key=$($importedMap[$key])")
        [void]$updatedKeys.Add($key)
    } else {
        $output.Add($line)
    }
}

foreach ($key in $importedMap.Keys) {
    if ($updatedKeys.Contains($key)) { continue }
    if ($currentMap.Contains($key)) { continue }
    $output.Add("$key=$($importedMap[$key])")
    [void]$updatedKeys.Add($key)
}

[System.IO.File]::WriteAllLines($targetEnv, $output, [System.Text.UTF8Encoding]::new($false))

Write-Host "Environment merge completed."
Write-Host "Selected files: $($dialog.FileNames.Count)"
Write-Host "Imported keys: $($updatedKeys.Count)"
Write-Host "Ignored unknown keys: $($ignoredKeys.Count)"
Write-Host "Backup file: $backupPath"
Write-Host "Secret values were not printed."
Write-Host "Source files were not modified, moved, or deleted."
