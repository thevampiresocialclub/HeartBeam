# SOFA aligner — one-time setup

WhisperX is speech-trained and clips word ends on held vowels and vibrato. SOFA
(Singing-Oriented Forced Aligner) is trained on singing and aligns phonemes
instead of CTC characters, which gives much better timing on sustained notes.

SOFA pins old numpy / pandas / librosa that conflict with our main venv, so we
run it from a **sidecar venv** and call its CLI via subprocess.

## 1. Clone SOFA

```powershell
cd C:\Users\young\tools
git clone https://github.com/qiuqiao/SOFA.git
```

## 2. Create the sidecar venv

```powershell
cd C:\Users\young\tools\SOFA
py -3.10 -m venv .venv-sofa
.\.venv-sofa\Scripts\Activate.ps1
pip install --upgrade pip
# Install torch + torchaudio matched to your CUDA.
pip install --index-url https://download.pytorch.org/whl/cu121 torch==2.4.1+cu121 torchaudio==2.4.1+cu121
pip install -r requirements.txt
deactivate
```

If Python 3.10 isn't installed: `winget install Python.Python.3.10`.

> **RTX 50-series (Blackwell) warning.** The `torch==2.4.1+cu121` pin above has
> no kernels for `sm_120` and will fail with *"no kernel image is available for
> execution on the device"*. You need cu128 wheels (`torch>=2.7`) instead —
> but SOFA pins old numpy / pandas / librosa, so that combination is untested
> and may not resolve. Run SOFA on the CPU, or treat this path as unverified on
> 50-series hardware. This is the sidecar venv only; it does not affect
> HeartBeam's main environment.

## 3. Download a checkpoint + dictionary

Get a SOFA-compatible checkpoint and English dictionary from the project's
[Releases](https://github.com/qiuqiao/SOFA/releases) page. Drop the .ckpt under
`C:\Users\young\tools\SOFA\ckpt\` and the dictionary file under
`C:\Users\young\tools\SOFA\dictionary\`.

## 4. Tell HeartBeam where SOFA lives

Either set environment variables (persist in PowerShell profile):

```powershell
$env:HEARTBEAM_SOFA_PYTHON = "C:\Users\young\tools\SOFA\.venv-sofa\Scripts\python.exe"
$env:HEARTBEAM_SOFA_REPO   = "C:\Users\young\tools\SOFA"
$env:HEARTBEAM_SOFA_CKPT   = "C:\Users\young\tools\SOFA\ckpt\<model>.ckpt"
$env:HEARTBEAM_SOFA_DICT   = "C:\Users\young\tools\SOFA\dictionary\<dict>.txt"
```

Or pass them per-invocation:

```powershell
heartbeam song.mp3 lyrics.txt --aligner sofa `
  --sofa-python "C:\…\SOFA\.venv-sofa\Scripts\python.exe" `
  --sofa-repo "C:\…\SOFA" `
  --sofa-ckpt "C:\…\SOFA\ckpt\xxx.ckpt" `
  --sofa-dict "C:\…\SOFA\dictionary\xxx.txt"
```

## 5. Run

```powershell
heartbeam tests\fixtures\Helena.mp3 tests\fixtures\lyrics.txt --aligner sofa --align-device cpu -v
```

## What SOFA outputs

SOFA writes TextGrid files with two tiers (words and phonemes) and start/end
timestamps in seconds. `heartbeam/align_sofa.py` parses the words tier and
groups them back into our `Line` / `Word` schema using lyrics line order. If the
word count mismatches the lyrics file (e.g. backing-vocal echoes), the adapter
logs a warning and groups best-effort.
