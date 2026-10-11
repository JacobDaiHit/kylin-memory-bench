param([string]$Distro = "openKylin-KMB", [string]$User = "kmb")
$ErrorActionPreference = "Stop"
$projectPath = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$wslPath = (& wsl.exe -d $Distro -- wslpath -u $projectPath).Trim()
if ($LASTEXITCODE) { throw "Cannot locate project inside the existing WSL distribution." }
Write-Output "Open http://127.0.0.1:6084/vnc.html?autoconnect=1&resize=scale after startup."
& wsl.exe -d $Distro -u $User -- bash "$wslPath/scripts/start_desktop.sh"
if ($LASTEXITCODE) { throw "Desktop ended with an error; inspect the printed log directory." }
