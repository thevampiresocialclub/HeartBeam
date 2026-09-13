# Install the checked-out HeartBeam revision. Requires 64-bit Python 3.12.
# Default location: <checkout>\.venv. No machine-wide execution-policy changes.
[CmdletBinding()]
param(
    [string] $InstallDir = "",
    [ValidateSet("Auto", "GPU", "CPU", "Editor")] [string] $Variant = "Auto",
    [string] $PythonPath = "",
    [switch] $InstallMetal,
    [switch] $SkipFfmpeg
)
$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($InstallDir)) { $InstallDir = $repoRoot }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
$constraints = Join-Path $repoRoot "requirements\windows-py312.txt"

function Invoke-Checked([string] $Program, [string[]] $Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed with exit code $LASTEXITCODE" }
}

function Find-Python {
    $probes = @()
    if ($PythonPath) { $probes += @{ Program = $PythonPath; Prefix = @() } }
    else {
        $probes += @{ Program = "py"; Prefix = @("-3.12") }
        $probes += @{ Program = "python"; Prefix = @() }
        $probes += @{ Program = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"; Prefix = @() }
    }
    foreach ($probe in $probes) {
        try {
            $prefix = $probe.Prefix
            $found = & $probe.Program @prefix -c "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8; print(sys.executable)" 2>$null
            if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -Last 1).Trim() }
        } catch { }
    }
    return $null
}

function Refresh-ToolPath {
    # Changes this installer process only; don't replace the user's saved PATH.
    $machinePath = [Environment]::GetEnvironmentVariable("PATH", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
    $env:PATH = "$env:PATH;$machinePath;$userPath"
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
        $found = Get-ChildItem "$env:LOCALAPPDATA\Microsoft\WinGet\Packages\Gyan.FFmpeg_*\ffmpeg-*-full_build\bin\ffmpeg.exe" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($found) { $env:PATH = "$($found.DirectoryName);$env:PATH" }
    }
}

try {
    if (-not (Test-Path -LiteralPath $constraints)) { throw "Dependency constraints missing: $constraints" }
    if ($Variant -eq "Auto") {
        $nvidia = $null
        try { $nvidia = & nvidia-smi --query-gpu=name --format=csv,noheader 2>$null } catch { }
        if ($nvidia -and $LASTEXITCODE -eq 0) { $Variant = "GPU" }
        else {
            $Variant = "Editor"
            Write-Warning "No NVIDIA GPU detected. Installing the editor for prepared projects. Audio preparation requires a compatible NVIDIA GPU; no remote processing bridge is included."
        }
    }
    if ($Variant -eq "CPU") { Write-Warning "CPU processing is experimental. The CLI requires --allow-cpu; GUI CPU preparation is not supported." }
    if ($InstallMetal -and $Variant -eq "Editor") { throw "Metal model downloads require an ML variant, not Editor." }

    Write-Host "Checking 64-bit Python 3.12..."
    $pythonExe = Find-Python
    if (-not $pythonExe -and -not $PythonPath) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Install 64-bit Python 3.12 from python.org, then rerun with -PythonPath 'C:\path\to\python.exe'. winget is unavailable."
        }
        Invoke-Checked "winget" @("install", "--id=Python.Python.3.12", "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements")
        Refresh-ToolPath
        $pythonExe = Find-Python
    }
    if (-not $pythonExe) { throw "No compatible Python found. Supply -PythonPath for 64-bit Python 3.12." }

    Refresh-ToolPath
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        if ($SkipFfmpeg) { throw "-SkipFfmpeg skips installation, not the requirement. Put ffmpeg and ffprobe on PATH first." }
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "Install FFmpeg (full build with libass), add its bin folder to PATH, then rerun. winget is unavailable." }
        Invoke-Checked "winget" @("install", "--id=Gyan.FFmpeg", "-e", "--silent", "--accept-package-agreements", "--accept-source-agreements")
        Refresh-ToolPath
    }
    if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue) -or -not (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
        throw "FFmpeg installation is incomplete. Both ffmpeg and ffprobe must be available before setup can continue."
    }

    New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    $venv = Join-Path $InstallDir ".venv"
    $venvPy = Join-Path $venv "Scripts\python.exe"
    $receiptPath = Join-Path $InstallDir "heartbeam-install.json"
    if (Test-Path -LiteralPath $receiptPath) {
        $old = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
        if ($old.variant -ne $Variant) { throw "This directory contains a $($old.variant) installation. Use another -InstallDir for $Variant; setup will not replace it silently." }
    }
    if (-not (Test-Path -LiteralPath $venv)) { Invoke-Checked $pythonExe @("-m", "venv", $venv) }
    if (-not (Test-Path -LiteralPath $venvPy)) { throw "Existing environment is incomplete: $venv. Use a new -InstallDir or repair it explicitly." }
    Invoke-Checked $venvPy @("-c", "import sys,struct; assert sys.version_info[:2] == (3,12) and struct.calcsize('P') == 8, 'Use a new install directory with 64-bit Python 3.12'")

    # An interrupted update must not leave the previous readiness claim valid.
    @{ schema_version = 1; variant = $Variant; ready = $false; source = $repoRoot } |
        ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Invoke-Checked $venvPy @("-m", "pip", "install", "-c", $constraints, "pip", "setuptools", "wheel")
    if ($Variant -eq "GPU") {
        Invoke-Checked $venvPy @("-m", "pip", "install", "--index-url", "https://download.pytorch.org/whl/cu128", "torch==2.8.0+cu128", "torchaudio==2.8.0+cu128", "torchvision==0.23.0+cu128")
    } elseif ($Variant -eq "CPU") {
        Invoke-Checked $venvPy @("-m", "pip", "install", "--index-url", "https://download.pytorch.org/whl/cpu", "torch==2.8.0+cpu", "torchaudio==2.8.0+cpu")
    }
    $extra = switch ($Variant) { "GPU" { "gpu,gui" }; "CPU" { "cpu,gui" }; "Editor" { "gui" } }
    Invoke-Checked $venvPy @("-m", "pip", "install", "-c", $constraints, "--editable", "$repoRoot[$extra]")
    if ($Variant -eq "GPU") {
        # faster-whisper requires CPU ORT metadata while audio-separator[gpu]
        # requires GPU ORT. Their Python files overlap. Restore the constrained
        # GPU payload last, then require actual CUDA execution in doctor.
        # See requirements/README.md for the upstream packaging limitation.
        Invoke-Checked $venvPy @("-m", "pip", "install", "-c", $constraints, "--force-reinstall", "--no-deps", "onnxruntime-gpu")
    }
    if ($InstallMetal) { Invoke-Checked $venvPy @((Join-Path $PSScriptRoot "install_metal_model.py")) }

    $report = Join-Path $InstallDir "heartbeam-diagnostics.json"
    Invoke-Checked $venvPy @("-m", "heartbeam.doctor", "--variant", $Variant, "--json", $report)
    # Write readiness only after all required checks passed.
    @{ schema_version = 1; variant = $Variant; ready = $true; source = $repoRoot; venv = $venv;
       ffmpeg_dir = (Split-Path -Parent (Get-Command ffmpeg).Source) } |
        ConvertTo-Json | Set-Content -LiteralPath $receiptPath -Encoding UTF8

    Write-Host "HeartBeam setup checks passed ($Variant)." -ForegroundColor Green
    Write-Host "Launch: & '$PSScriptRoot\start.ps1' -InstallDir '$InstallDir'"
    Write-Host "Report: $report"
    if ($Variant -ne "Editor") { Write-Host "Next: pre-download Pop models and complete the short-song smoke test in INSTALL-WITH-AN-AGENT.md." }
    exit 0
} catch {
    Write-Error "HeartBeam setup did not finish: $_" -ErrorAction Continue
    exit 1
}
