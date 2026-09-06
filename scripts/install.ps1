# HeartBeam install script — Windows / PowerShell.
#
# What this does:
#   1. Verifies Python 3.10+ and ffmpeg are present (or installs ffmpeg via winget).
#   2. Creates a venv at <install-dir>\.venv (default: %LOCALAPPDATA%\HeartBeam\.venv).
#   3. pip-installs heartbeam[cpu] (or [gpu] if -Gpu is passed). cu121 GPU build
#      pulls torch from pytorch.org's index; CPU build uses PyPI defaults.
#   4. Optionally runs scripts\install_metal_model.py for the metal preset (~2 GB).
#   5. Verifies `heartbeam --help` works.
#
# Run from an admin PowerShell only if you choose -InstallScope AllUsers.
# Otherwise per-user install is fine and does NOT need admin.

[CmdletBinding()]
param(
    [Parameter()] [string] $InstallDir = "$env:LOCALAPPDATA\HeartBeam",
    [Parameter()] [ValidateSet("Auto","CPU","GPU")] [string] $Variant = "Auto",
    [switch] $InstallMetal,
    [switch] $SkipFfmpeg
)

$ErrorActionPreference = "Stop"
$ProgressPreference    = "Continue"

function Write-Step($msg) { Write-Host "`n>>> $msg" -ForegroundColor Cyan }
function Write-Ok  ($msg) { Write-Host "    [ok] $msg"   -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    [warn] $msg" -ForegroundColor Yellow }
function Write-Err ($msg) { Write-Host "    [err] $msg"  -ForegroundColor Red }

# ---------- 0. Detect GPU ----------
# HeartBeam targets NVIDIA: GTX 1050 / RTX xx50 and up. Only CUDA accelerates
# this pipeline — CTranslate2 (WhisperX's ASR engine) is CUDA-or-CPU only, and
# audio-separator's DirectML path falls back to CPU for the very model
# architectures our presets use. AMD and Intel GPUs therefore get the CPU build,
# which works but takes 20-75 min per song.
if ($Variant -eq "Auto") {
    Write-Step "Detecting GPU"
    $nvidia = $null
    try { $nvidia = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null } catch {}
    if ($LASTEXITCODE -eq 0 -and $nvidia) {
        $Variant = "GPU"
        Write-Ok "NVIDIA GPU found: $($nvidia -split "`n" | Select-Object -First 1) -> GPU build"
    } else {
        $Variant = "CPU"
        $gpuName = (Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue |
                    Select-Object -First 1 -ExpandProperty Name)
        Write-Warn "no NVIDIA GPU detected ($gpuName) -> CPU build"
        Write-Warn "CPU is not a supported target: ~20-30 min/song ('pop'), 45-75 min ('rock')."
        Write-Warn "'heartbeam' will require --allow-cpu to run at all."
    }
}

# ---------- 1. Python ----------
Write-Step "Checking Python 3.10+"
$py = $null
foreach ($cmd in @("py -3.12", "py -3.11", "py -3.10", "python")) {
    try {
        $ver = & cmd /c "$cmd --version 2>&1"
        if ($LASTEXITCODE -eq 0 -and $ver -match "Python 3\.(1[0-9])") {
            $py = $cmd
            Write-Ok "found: $ver via '$cmd'"
            break
        }
    } catch {}
}
if (-not $py) {
    Write-Warn "Python 3.10+ not found — installing Python 3.12 via winget"
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Err "winget is also missing. Install Python 3.12 manually from https://www.python.org/downloads/ then re-run this installer."
        exit 1
    }
    winget install --id=Python.Python.3.12 -e --silent --accept-package-agreements --accept-source-agreements
    # winget updates PATH for new shells; probe the standard install path so we can use it now.
    $candidate = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
    if (Test-Path $candidate) {
        $py = $candidate
        Write-Ok "installed: $py"
    } else {
        Write-Err "Python installed via winget but not found at the expected path. Close and reopen PowerShell, then re-run this installer."
        exit 1
    }
}

# ---------- 2. ffmpeg ----------
if (-not $SkipFfmpeg) {
    Write-Step "Checking ffmpeg"
    $ffmpeg = (Get-Command ffmpeg -ErrorAction SilentlyContinue).Source
    if (-not $ffmpeg) {
        Write-Warn "ffmpeg not on PATH — installing via winget (Gyan.FFmpeg, includes libass)"
        winget install --id=Gyan.FFmpeg -e --silent --accept-package-agreements --accept-source-agreements
        # Path is set for new shells but not this one. Probe known winget install dirs.
        $candidates = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin\ffmpeg.exe" -ErrorAction SilentlyContinue
        if ($candidates) {
            $ffmpegDir = $candidates[0].DirectoryName
            $env:PATH = "$ffmpegDir;$env:PATH"
            Write-Ok "ffmpeg installed at $($candidates[0].FullName)"
        } else {
            Write-Warn "ffmpeg installed but PATH not yet visible. Close and reopen PowerShell after install completes."
        }
    } else {
        Write-Ok "found: $ffmpeg"
    }
}

# ---------- 3. Venv ----------
Write-Step "Creating venv at $InstallDir\.venv"
if (-not (Test-Path $InstallDir)) {
    New-Item -ItemType Directory -Path $InstallDir | Out-Null
}
$venv = Join-Path $InstallDir ".venv"
if (-not (Test-Path $venv)) {
    & cmd /c "$py -m venv `"$venv`""
    if ($LASTEXITCODE -ne 0) { Write-Err "venv creation failed"; exit 1 }
    Write-Ok "venv created"
} else {
    Write-Ok "venv already exists — reusing"
}
$venvPy = Join-Path $venv "Scripts\python.exe"

# ---------- 4. pip install heartbeam ----------
Write-Step "Upgrading pip"
& $venvPy -m pip install --upgrade pip setuptools wheel | Out-Null

Write-Step "Installing heartbeam ($Variant variant)"
# Resolve the package source: either this repo (editable) or PyPI/git.
$repoRoot = Split-Path -Parent $PSScriptRoot
$pyproject = Join-Path $repoRoot "pyproject.toml"
if (Test-Path $pyproject) {
    Write-Ok "installing from local source: $repoRoot"
    # 'gui' is not optional in practice: the Start Menu / desktop shortcuts point
    # at heartbeam-gui.exe, which pip generates regardless — but it runs under
    # pythonw, so a missing streamlit fails silently with no console to show why.
    $extra = if ($Variant -eq "GPU") { "[gpu,gui]" } else { "[cpu,gui]" }
    if ($Variant -eq "GPU") {
        # cu128, not cu121. These wheels carry kernels for sm_61 (GTX 1050)
        # through sm_120 (RTX 50-series / Blackwell). cu121 stops at sm_90, so on
        # any RTX 50-series card it fails at runtime with "no kernel image is
        # available for execution on the device".
        & $venvPy -m pip install --index-url https://download.pytorch.org/whl/cu128 `
            torch torchaudio torchvision
        if ($LASTEXITCODE -ne 0) { Write-Err "torch (cu128) install failed"; exit 1 }
    }
    & $venvPy -m pip install "$repoRoot$extra"
} else {
    Write-Err "pyproject.toml not found at $pyproject — run this from a HeartBeam checkout"
    exit 1
}
if ($LASTEXITCODE -ne 0) { Write-Err "pip install failed"; exit 1 }

# ---------- 5. Metal preset (optional) ----------
if ($InstallMetal) {
    Write-Step "Installing metal preset (Mesk Rifforge, ~2 GB)"
    $metalScript = Join-Path $repoRoot "scripts\install_metal_model.py"
    & $venvPy $metalScript
    if ($LASTEXITCODE -ne 0) { Write-Warn "metal install failed; heartbeam will still work without --separator metal" }
}

# ---------- 6. Verify ----------
Write-Step "Verifying install"
& $venvPy -c "from heartbeam.cli import _build_parser; _build_parser(); print('heartbeam OK')"
if ($LASTEXITCODE -ne 0) { Write-Err "verification failed"; exit 1 }

# The GUI shortcut is the primary launcher, so prove its import chain works now
# rather than letting it fail silently under pythonw on first double-click.
& $venvPy -c "import streamlit, heartbeam.gui; print('heartbeam-gui OK')"
if ($LASTEXITCODE -ne 0) { Write-Err "GUI verification failed - the shortcut would not launch"; exit 1 }

# Confirm torch can actually drive this machine's GPU. Catches the cu121-on-
# Blackwell class of failure at install time rather than 40 minutes into a run.
if ($Variant -eq "GPU") {
    & $venvPy -c "import torch;a=torch.cuda.get_arch_list();p=torch.cuda.get_device_properties(0);s=f'sm_{p.major}{p.minor}';print(f'{p.name} {s} {p.total_memory/1024**3:.1f}GB torch={torch.__version__}');exit(0 if s in a else 1)"
    if ($LASTEXITCODE -ne 0) {
        Write-Err "this torch build has no kernels for your GPU's compute capability."
        Write-Err "reinstall torch from the cu128 index (see scripts/install.ps1)."
        exit 1
    }
    Write-Ok "GPU verified"
}

# ffmpeg is required to decode the *input* file, not just to render video.
if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warn "ffmpeg still not on PATH. Open a NEW terminal (winget updates PATH only for new shells) and run 'ffmpeg -version'. Until then every run fails at 'loading original audio'."
} else {
    Write-Ok "ffmpeg on PATH"
}

Write-Host ""
Write-Host "==========================================" -ForegroundColor Green
Write-Host "  HeartBeam installed at: $venv" -ForegroundColor Green
Write-Host "==========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Try it:" -ForegroundColor Cyan
Write-Host "    & `"$venv\Scripts\heartbeam.exe`" song.mp3 lyrics.txt --separator rock --align-device cpu -v"
Write-Host ""
Write-Host "Or activate the venv and use 'heartbeam' directly:" -ForegroundColor Cyan
Write-Host "    & `"$venv\Scripts\Activate.ps1`""
Write-Host "    heartbeam --help"
Write-Host ""
