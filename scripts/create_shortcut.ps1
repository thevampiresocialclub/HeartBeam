# Create a desktop + Start Menu shortcut for HeartBeam GUI.
#
# Usage:
#   .\scripts\create_shortcut.ps1                      # uses .venv next to repo
#   .\scripts\create_shortcut.ps1 -VenvDir C:\path\to\.venv
#   .\scripts\create_shortcut.ps1 -NoStartMenu         # desktop only

[CmdletBinding()]
param(
    [string] $VenvDir = "",
    [switch] $NoStartMenu,
    [switch] $NoDesktop
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($VenvDir)) {
    $scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
    $VenvDir = Join-Path $scriptDir "..\.venv"
}
$VenvDir = (Resolve-Path $VenvDir).Path
$exe = Join-Path $VenvDir "Scripts\heartbeam-gui.exe"
if (-not (Test-Path $exe)) {
    Write-Error "heartbeam-gui.exe not found at $exe. Did you run scripts\install.ps1?"
    exit 1
}

# Use the venv root as the shortcut working dir so any relative paths resolve sanely.
$wd = Split-Path -Parent $VenvDir

# Try to use an icon file if present (we don't ship one yet — Windows will use the exe's default).
$icon = Join-Path (Split-Path -Parent $PSScriptRoot) "assets\heartbeam.ico"
if (-not (Test-Path $icon)) {
    $icon = $exe  # fall back to exe's embedded icon (generic)
}

function New-Shortcut([string]$path, [string]$target, [string]$wd, [string]$icon, [string]$desc, [string]$arguments = "") {
    $shell = New-Object -ComObject WScript.Shell
    $lnk = $shell.CreateShortcut($path)
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $wd
    $lnk.IconLocation = $icon
    $lnk.Description = $desc
    $lnk.Arguments = $arguments
    $lnk.Save()
    Write-Host "  [ok] $path" -ForegroundColor Green
}

Write-Host "Creating HeartBeam shortcuts..." -ForegroundColor Cyan
$target = $exe
$arguments = ""
if (Test-Path -LiteralPath (Join-Path $wd "heartbeam-install.json")) {
    $target = (Get-Command powershell.exe).Source
    $launcher = Join-Path $PSScriptRoot "start.ps1"
    $arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$launcher`" -InstallDir `"$wd`""
}

if (-not $NoDesktop) {
    $desktop = [Environment]::GetFolderPath('Desktop')
    $lnkPath = Join-Path $desktop "HeartBeam.lnk"
    New-Shortcut $lnkPath $target $wd $icon "HeartBeam karaoke generator" $arguments
}

if (-not $NoStartMenu) {
    $startMenu = Join-Path ([Environment]::GetFolderPath('StartMenu')) "Programs\HeartBeam"
    if (-not (Test-Path $startMenu)) {
        New-Item -ItemType Directory -Path $startMenu -Force | Out-Null
    }
    $lnkPath = Join-Path $startMenu "HeartBeam.lnk"
    New-Shortcut $lnkPath $target $wd $icon "HeartBeam karaoke generator" $arguments
}

Write-Host ""
Write-Host "Done. Double-click 'HeartBeam' on your desktop to launch." -ForegroundColor Green
