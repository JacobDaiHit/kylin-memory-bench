param(
  [string]$SourceDistro = "Ubuntu",
  [string]$TargetDistro = "openKylin-KMB",
  [string]$RuntimeBase = "/home/maedaily/.local/share/kmb-live"
)
$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sourcePath = (& wsl.exe -d $SourceDistro -- wslpath -u $projectPath).Trim()
if ($LASTEXITCODE) { throw "Cannot resolve the project in source WSL." }
& wsl.exe -d $SourceDistro -u root -- bash "$sourcePath/scripts/runtime_bridge.sh" export $RuntimeBase
if ($LASTEXITCODE) { throw "Runtime export failed." }
$targetPath = (& wsl.exe -d $TargetDistro -- wslpath -u $projectPath).Trim()
if ($LASTEXITCODE) { throw "Cannot resolve the project in target WSL." }
& wsl.exe -d $TargetDistro -u root -- bash "$targetPath/scripts/runtime_bridge.sh" import $RuntimeBase
if ($LASTEXITCODE) { throw "Runtime import failed." }
Write-Output "Runtime mounts are ready. Keep the openKylin desktop running while testing."
Write-Output "After WSL shuts down, run this script again; it does not reinstall either agent."
