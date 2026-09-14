# Install HeartBeam with Claude Code or Codex

Give this repository to a coding agent running **locally on the computer where HeartBeam will run**. A subscription is optional setup help, not a HeartBeam runtime requirement. A cloud-only chat or coding task cannot install software on your PC.

Repository: [thevampiresocialclub/HeartBeam](https://github.com/thevampiresocialclub/HeartBeam). It is public and can be cloned without an invitation.

Copy this request to your agent:

> Install https://github.com/thevampiresocialclub/HeartBeam on my Windows PC. Read INSTALL-WITH-AN-AGENT.md first. Check my hardware, use the repository's setup script and dependency constraints, run its diagnostics, create a shortcut and launch it. Keep my existing projects and software intact. Tell me which checks passed and whether you completed a real song test. Do not silently upgrade dependencies or claim that a successful import proves the ML pipeline works.

## Supported starting point

- Windows x64 and 64-bit Python **3.12**. The script can use winget to install prerequisites when available; otherwise follow the explicit error message. Do not substitute Python 3.14 or a 32-bit interpreter.
- Compatible NVIDIA graphics and driver for full audio preparation. The development baseline is RTX 5070, Torch 2.8.0 with CUDA 12.8. Other cards require an actual test; GPU marketing names alone are not certification.
- Without NVIDIA, `Auto` selects **Editor** mode for already-prepared projects. It has no local ML packages, separation or automatic lyric rematching. The proposed remote bridge/cloud service is **not implemented**.
- CPU ML is an explicit experimental CLI option. It is not a promise that an ordinary laptop can run the complete GUI workflow acceptably.
- Plan for several GB of dependencies and additional model/project space. Check free space before downloading. Do not use old 700 MB/3 GB estimates as installation guarantees.

## Agent procedure

1. Locate the checkout and read its current Git revision/status. For a new install, use this repository's verified URL and the maintainer's recommended revision. Keep the checkout in a durable user-owned folder. Do not operate on an unrelated repository or overwrite a dirty checkout.
2. Check Windows architecture, available NVIDIA GPU, free disk space, Python and FFmpeg. Explain the chosen variant before large downloads. Do not change machine-wide execution policies or disable security settings.
3. Run the following from the checkout. The default environment is `<checkout>\.venv`, so later launch/update commands agree about its location:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Use `-Variant GPU` to require the GPU configuration, `-Variant Editor` for a prepared-project editor, or `-PythonPath 'C:\path\to\python.exe'` to select an existing Python 3.12 interpreter. `-InstallDir 'D:\Apps\HeartBeam'` places the environment there while retaining the source checkout. Keep both folders. Do not silently change the variant in an existing installation.

`-SkipFfmpeg` skips downloading FFmpeg; FFmpeg and FFprobe must still be present. Setup must return nonzero when a required check fails. The Windows constraints pin the known dependency set, but are not a hash-locked offline distribution; never claim stronger reproducibility than was tested.

4. For the GPU variant, download only the default Pop models first:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_models.py --presets pop --whisper medium --language en
```

Use the actual environment path if `-InstallDir` was supplied. Model download failure is a failed preparation step; retain completed downloads and fix the reported problem before retrying. Rock/metal packs are optional and can be added later. Models stay under `~/.heartbeam/models` or `HEARTBEAM_MODEL_ROOT`.

5. Inspect the diagnostic report and create shortcuts:

```powershell
.\.venv\Scripts\python.exe -m heartbeam.doctor --variant GPU --json heartbeam-diagnostics.json
.\scripts\create_shortcut.ps1 -VenvDir .\.venv
.\scripts\start.ps1
```

Use `--variant Editor` for the editor-only installation. The setup report and installation receipt are local files and are ignored by Git. The launcher carries the saved FFmpeg directory into the app process. If diagnosing from another shell, make the receipt's `ffmpeg_dir` available on that shell's PATH first.

6. Complete the appropriate smoke test. **GPU:** use a short song supplied by the user, prepare audio/match lyrics, save, review timing, build karaoke, change lead/backing levels, export MP4 and reopen the project. Confirm audio, duration and visible highlights. **Editor:** open a prepared project, seek audio via the waveform, edit timing/appearance, change track levels, save/reopen and export. Do not claim the GPU workflow was tested using a generated tone alone.
7. Report the checkout revision, variant, install location, diagnostics, whether models were downloaded, smoke-test outcome and any remaining limitation. A doctor pass is not a real-model quality or timing test.

## Updating an installed checkout

Stop active preparation/export and close HeartBeam before updating. Save wanted edits first. Inspect `git status`; preserve local changes rather than discarding them. Fetch the intended remote and review incoming changes. Use a fast-forward update to the maintainer's chosen revision, then rerun the same setup command and diagnostics. Do not use `git reset --hard`, delete projects, or run an unconstrained `pip install --upgrade` as routine maintenance.

An editable installation follows source changes, while rerunning setup applies dependency changes. Keep the previous revision available for rollback; never automatically open newer project formats in an older app. The installer does not delete `Documents/HeartBeam/Projects`, preparation sessions or model caches.

## When something fails

- **Wrong Python:** use 64-bit Python 3.12 and a fresh install directory. Do not repurpose another application's environment.
- **Missing FFmpeg/FFprobe or libass:** install a full FFmpeg build, verify its path and rerun setup. A warning is not successful installation.
- **Missing PyArrow/Mutagen or dependency conflict:** rerun the constrained setup; collect the complete error if resolution fails. Do not remove dependencies to force a success result.
- **CUDA error on an RTX 50-series card:** retain the tested `cu128` Torch build; do not downgrade to `cu121`.
- **ONNX provider errors:** collect the diagnostic and real-model error. A provider listed as available does not prove that the model executed on it.
- **Application opens an unexpected old session:** check the process/version using the local port. Do not kill an unidentified service or discard unsaved work.
- **Model download failed:** retry the affected setup step after fixing connectivity or disk space. Do not label partial downloads ready.

Do not upload songs, model weights, credentials or local diagnostic reports to an issue by default. Share a minimal error and relevant versions. See [BUILD-STATUS.md](BUILD-STATUS.md) for what the maintainer actually verified.
