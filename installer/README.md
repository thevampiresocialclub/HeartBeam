# Building the HeartBeam Windows installer

`heartbeam.iss` is an Inno Setup script that produces a single
`HeartBeam-Setup-<version>.exe` (~2 MB) which installs HeartBeam on a friend's
machine without them needing to touch Python or PowerShell.

## One-time build setup

1. Install Inno Setup 6:
   ```powershell
   winget install JRSoftware.InnoSetup
   ```

That's it. Python is **not** bundled — `install.ps1` winget-installs Python 3.12
on the target machine if it's missing, which keeps the installer at ~2 MB
instead of ~80 MB. (An earlier revision of this doc described staging an
embedded Python into `installer\python-embed\`; the `.iss` has never referenced
that folder, so ignore any such instructions.)

## Build

From the repo root:
```powershell
ISCC.exe installer\heartbeam.iss
```
Output lands at `installer\Output\HeartBeam-Setup-<version>.exe`.

## What it does on the target machine

1. Copies the HeartBeam source to `%LOCALAPPDATA%\HeartBeam`.
2. Runs `scripts\install.ps1`, which installs Python 3.12 and ffmpeg via winget
   if missing, creates a venv, and detects NVIDIA to select the GPU or CPU build.
   The optional GPU checkbox forces the GPU build with CUDA 12.8 wheels.
3. Optionally runs `scripts\install_metal_model.py` (~2 GB download) if the
   user ticked the metal-preset checkbox.
4. Creates a Start Menu shortcut "HeartBeam" that opens the GUI, plus a
   "HeartBeam Console" shortcut with the environment activated.
5. Registers a normal uninstaller in Add/Remove Programs.

## What it intentionally does NOT do

- Doesn't bundle the 3 GB of ML deps — those come down on first run. That's
  the whole point of Option A.
- Doesn't bundle ffmpeg — the install script auto-installs via winget if it's
  not on PATH (and the install runs without admin, so winget per-user works).
  Note: ffmpeg is **not** optional. `heartbeam/io.py` shells out to it to decode
  the input file, so `-SkipFfmpeg` must never be passed from the `.iss`.
- Doesn't bundle the Rifforge model for the metal preset — that's a separate
  ~2 GB download triggered only if the user opts in.

## Manual test before shipping

After building, install on a clean Windows VM (Hyper-V or VirtualBox) without
admin rights to confirm:

- Installer runs without elevation prompts
- First-run pip install completes in 4-6 min on a typical broadband connection
- `heartbeam --help` works from the Start Menu shortcut
- Uninstaller removes the application while keeping user projects, preparation
  sessions and model caches. See [Files and distribution](../docs/FILES-AND-DISTRIBUTION.md).
