# Launch the environment created by install.ps1, including its FFmpeg path.
[CmdletBinding()]
param([string] $InstallDir = "")
$ErrorActionPreference = "Stop"
if (-not $InstallDir) { $InstallDir = Split-Path -Parent $PSScriptRoot }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$receiptPath = Join-Path $InstallDir "heartbeam-install.json"
if (-not (Test-Path -LiteralPath $receiptPath)) { throw "Run scripts\install.ps1 successfully before using this launcher." }
$receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
if ($receipt.ready -ne $true) { throw "Setup is incomplete or an update was interrupted. Rerun scripts\install.ps1 before launching." }
if (-not (Test-Path -LiteralPath $receipt.ffmpeg_dir)) { throw "Saved FFmpeg location is missing. Rerun setup to repair it." }
$env:PATH = "$($receipt.ffmpeg_dir);$env:PATH"
$exe = Join-Path $receipt.venv "Scripts\heartbeam-gui.exe"
if (-not (Test-Path -LiteralPath $exe)) { throw "HeartBeam launcher is missing. Rerun setup to repair it." }
Start-Process -FilePath $exe -WorkingDirectory $InstallDir -WindowStyle Hidden
