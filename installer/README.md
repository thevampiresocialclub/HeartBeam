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
   if missing, creates a venv, and pip-installs `heartbeam[cpu,gui]` — or
   `[gpu,gui]` if the user ticked that option in the wizard. Left to itself the
   script auto-detects NVIDIA, but the installer passes the variant explicitly.
3. Optionally runs `scripts\install_metal_model.py` (~2 GB download) if the
   user ticked the metal-preset checkbox.
4. Creates a Start Menu shortcut "HeartBeam Console" that opens a CMD prompt
   with the venv pre-activated.
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
- Uninstaller removes everything cleanly
