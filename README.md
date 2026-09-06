# HeartBeam

Lyrics-aware karaoke generator. Feed it an MP3 and a plain-text lyrics file. It strips **only the lead vocals being sung in the lyrics** — backing vocals, harmonies, ad-libs, and instrumental breaks all stay intact — then emits the timing data needed to render a karaoke video with synced on-screen lyrics.

Two phases, one engine:

- **Phase 1 (`heartbeam`)** — audio. Source-separates the song, force-aligns your lyrics to the lead vocal, builds a time-domain mask, and writes `karaoke.mp3` + `timings.json` + `lyrics.lrc`.
- **Phase 2 (`heartbeam-video`)** — video. Consumes `karaoke.mp3` + `timings.json` + a `style.toml`, generates an ASS subtitle file with per-word karaoke (`\k`) tags, and renders the final MP4 via `ffmpeg` + `libass`.

Re-running Phase 2 with a different style does not re-run the slow ML pipeline.

---

## Install

Two install variants, **selected automatically** by probing for an NVIDIA GPU:

- **CPU** (~700 MB on disk): works on any machine. See [Hardware](#hardware--what-to-expect) for timings.
- **GPU** (~3 GB on disk): NVIDIA CUDA 12.1+. Separation in seconds.

### Recommended: one-line install script

```powershell
# Windows (PowerShell)
git clone <this repo>
cd HeartBeam
.\scripts\install.ps1                  # auto-detects NVIDIA -> GPU, else CPU
# or force one:
.\scripts\install.ps1 -Variant GPU     # GPU build (cu121 wheels from pytorch.org)
.\scripts\install.ps1 -Variant CPU
.\scripts\install.ps1 -InstallMetal    # also download Mesk Rifforge (~2 GB)
```

```bash
# macOS / Linux
git clone <this repo>
cd HeartBeam
./scripts/install.sh                   # auto-detects
./scripts/install.sh --gpu             # force GPU build
./scripts/install.sh --install-metal   # also download Mesk Rifforge
```

The install script handles: Python 3.10+ check, ffmpeg install (via winget on Windows or homebrew/apt on Unix), venv creation, pip install, optional metal-model download, and a final verification step.

### Shareable Windows installer

For distributing to non-technical users, build a single-`.exe` installer with Inno Setup. See `installer/README.md` — produces a ~80 MB `HeartBeam-Setup.exe` that handles everything (deps download on first run).

### Manual install

If you prefer manual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[cpu]"        # or .[gpu] for CUDA build
# ffmpeg must be on PATH separately
```

For GPU, also do:
```powershell
pip install --index-url https://download.pytorch.org/whl/cu121 torch torchaudio torchvision
```
(else you'll get CPU torch wheels.)

### Requirements

1. **Python 3.10+**
2. **ffmpeg with libass.** Auto-installed by `install.ps1` / `install.sh`. Manual: on Windows install [Gyan.FFmpeg](https://www.gyan.dev/ffmpeg/builds/) full build via winget; on macOS `brew install ffmpeg`; on Ubuntu `sudo apt install ffmpeg`. Verify with `ffmpeg -filters | grep ass`.
3. **GPU optional** but strongly recommended. CUDA on NVIDIA, MPS on Apple Silicon. 4 GB VRAM is enough; use `--align-device cpu` to keep WhisperX off the GPU on tight VRAM cards.

Model checkpoints (~500 MB for `pop`, ~3 GB for `rock`, +2 GB for `metal`) are downloaded by audio-separator on first use of each preset.

---

## Hardware — what to expect

Only **CUDA** accelerates this pipeline. That is not a design choice; it is the
state of the two libraries doing the heavy lifting:

- **WhisperX** runs ASR through CTranslate2, whose device enum is literally
  `{CPU, CUDA}`. There is no Intel, DirectML, Vulkan, or OpenVINO backend.
- **audio-separator** has a DirectML path, but MDXC/RoFormer models — which is
  every model `pop`, `rock`, and `metal` use — fall back to CPU on it
  (`ComplexFloat` is unsupported), and Demucs fails outright. It has no
  `torch.xpu` support at all.

So an AMD or Intel GPU (including Arc / Core Ultra iGPUs) gets you the CPU path,
and the install scripts correctly choose the CPU build for those machines.

Rough wall-clock for a 4-minute song:

| Machine | `pop` | `rock` |
|---|---|---|
| NVIDIA GPU (any recent) | ~1–2 min | ~2–4 min |
| Modern 8-core laptop CPU | ~20–30 min | ~45–75 min |

Levers that help on CPU, in order of payoff:

```powershell
heartbeam song.mp3 lyrics.txt --separator pop --whisper-model small --align-device cpu
$env:OMP_NUM_THREADS = "8"    # match your physical core count
```

Dropping `--whisper-model` from `medium` to `small` is close to free: the
transcript is only used to anchor your *known* lyrics to the timeline, so its
word-error rate barely matters (`small.en` and `medium.en` are both 3.1% WER on
LibriSpeech test-clean).

### Moving models between machines

Every checkpoint lives under one root — `~/.heartbeam/models` on every platform
(`C:\Users\<you>\.heartbeam\models` on Windows), overridable with
`$HEARTBEAM_MODEL_ROOT`. Pre-download on a fast connection, copy the folder, and
the slow machine never touches the network:

```powershell
# machine A
python scripts/fetch_models.py --presets pop rock --whisper medium
# copy the printed folder to machine B, then there:
[Environment]::SetEnvironmentVariable('HEARTBEAM_MODEL_ROOT','D:\heartbeam-models','User')
```

This sidesteps two real traps:

- audio-separator's default cache path is the hardcoded POSIX string
  `/tmp/audio-separator-models/`, which on Windows is *drive*-relative — running
  from `D:` would silently re-download ~2 GB into `D:\tmp\`.
- `%LOCALAPPDATA%` is unsafe as a cache root here. Python installed from the
  **Microsoft Store** runs under MSIX filesystem virtualization and silently
  redirects those writes into
  `%LOCALAPPDATA%\Packages\PythonSoftwareFoundation.Python.3.x_<hash>\LocalCache\Local\`,
  while still reporting the nominal path — so the cache lands somewhere Explorer
  and PowerShell can't see. The user profile root is outside that redirection.

---

## Usage

### The GUI (easiest)

```powershell
heartbeam-gui
```

Opens a local Streamlit app at <http://localhost:8501>: drop in a song and a
lyrics file, pick a genre profile, watch a progress bar, play and download the
result. Advanced tuning knobs are behind an expander. The Windows installer
creates Start Menu and desktop shortcuts pointing at this.

It shells out to the same `heartbeam` CLI, so anything below applies equally.

### Phase 1: strip lead vocals + emit timings

Pick the genre profile that matches your song. The profile sets both the
separator models AND the mix/mask tuning that gives the cleanest result for
that genre:

```powershell
heartbeam song.mp3 lyrics.txt -o out\                # pop (default)
heartbeam song.mp3 lyrics.txt -o out\ --separator rock
heartbeam song.mp3 lyrics.txt -o out\ --separator metal
```

| Profile | Use for | Separator stack | Mix strategy |
|---|---|---|---|
| **`pop`** *(default)* | clean studio pop, ballads | MDX23C + UVR-BVE-4B | replace |
| **`rock`** | alt-rock, emo, classic rock, anything with gang vocals + doubled leads | Ensemble (BS-Roformer + MDX23C + MDX-Inst-HQ3) + Mel-Roformer Karaoke | subtract (gain 1.5) |
| **`metal`** | metalcore, death, hardcore, anything with screamed/distorted vocals | Mesk Rifforge + Mel-Roformer Karaoke | subtract (gain 1.5) |

`metal` requires a one-time install: `python scripts/install_metal_model.py`
(downloads ~2 GB and patches the audio-separator registry).

Outputs in `out/`:

| File | What it is |
|---|---|
| `karaoke.mp3` | The headline output: lead vocal removed during sung lyrics, everything else preserved. |
| `timings.json` | Master timing artifact. Word-level start/end/score, grouped by your original lyric lines. Consumed by Phase 2. |
| `lyrics.lrc` | Standard sidecar; drop into VLC alongside `karaoke.mp3` for synced-lyrics playback. |
| `stems/` | (`--keep-stems` only) `lead.wav`, `backing.wav`, `instrumental.wav`. Debugging / remixing. |

Common flags:

```
heartbeam SONG LYRICS [-o OUT]
  --separator {pop,rock,metal}      # primary profiles; advanced: ensemble, bs-roformer, demucs
  --whisper-model {tiny,base,small,medium,large-v3}      # default medium
  --align-device {auto,cuda,cpu}    # set 'cpu' on ≤4 GB VRAM GPUs to dodge OOM
  --keep-stems                      # write stems/ for debugging
  --target-lufs FLOAT               # normalize output to e.g. -14 LUFS (preset default)
  -v / --verbose
```

Every numeric mask/mix knob (`--pad-ms`, `--crossfade-ms`, `--merge-gap-ms`,
`--energy-threshold`, `--mix-strategy`, `--vocal-gain`, `--backing-boost`) has a
preset default but accepts an override. Run `heartbeam --help` for the full list.

### Phase 2: render the karaoke video

```powershell
heartbeam-video out\karaoke.mp3 out\timings.json -o out\karaoke.mp4
```

Pass a custom style:

```powershell
heartbeam-video out\karaoke.mp3 out\timings.json -o out\karaoke.mp4 --style my-style.toml
```

Override the background ad-hoc (hex colour, image, or video):

```powershell
heartbeam-video out\karaoke.mp3 out\timings.json --background "#0a0a2a"
heartbeam-video out\karaoke.mp3 out\timings.json --background backdrop.png
heartbeam-video out\karaoke.mp3 out\timings.json --background visuals.mp4
```

### `style.toml`

All knobs map directly to ASS subtitle styling — libass renders them.

```toml
[font]
family  = "Arial"
size_px = 72
bold    = true
italic  = false

[colour]
primary   = "#FFFFFF"   # text not yet sung
highlight = "#FFD700"   # word currently being sung
outline   = "#000000"
shadow    = "#000000"

[box]
position    = "bottom"  # top | center | bottom
alignment   = "center"  # left | center | right
margin_v_px = 80
margin_h_px = 60
outline_px  = 3
shadow_px   = 2

[background]
kind  = "solid"         # solid | image | video
value = "#101820"       # hex if solid; path if image/video

[video]
resolution    = "1920x1080"
fps           = 30
codec         = "libx264"
crf           = 20
audio_bitrate = "192k"
```

The shipped default lives at `heartbeam/styles/default.toml` and is used when `--style` is omitted.

---

## How the lyrics-aware masking works

The core idea is in `heartbeam/mix.py`:

```python
output = original − mask · lead_stem
```

- `lead_stem` is the isolated lead vocal from a 3-stem source separator (Demucs htdemucs + UVR-Karaoke by default).
- `mask` is a per-sample float in `[0, 1]` built from the WhisperX-aligned word intervals (`heartbeam/mask.py`). It is `1.0` only when a word from your lyrics file is being sung at that instant (+ a 60 ms pad and a 30 ms half-cosine cross-fade at each edge).
- Outside word intervals — intros, outros, instrumental breaks, ad-libs not in your lyrics file — the mask is `0`, so the original mix passes through unchanged.
- Backing vocals are *never subtracted*, because they live in a separate stem the model split out; they remain in the original mix where you keep them.

The biggest quality risk is the separator misclassifying backing harmonies into the `lead` stem — if you hear backing vox getting clipped during sung lines, retry with `--separator mel-roformer-karaoke` (heavier but cleaner lead/backing split).

---

## Testing

The pure-Python modules (`mask`, `mix`, `timings`, `style`, `ass_writer`) have no ML dependencies and run in milliseconds:

```powershell
pip install pytest
pytest -m "not slow"
```

End-to-end pipeline tests are marked `slow` and load real models:

```powershell
pytest -m slow
```

---

## What's not (yet) in scope

- FastAPI / hosted multi-user service (the local Streamlit GUI covers single-user).
- YouTube URL ingest.
- Bouncing-ball / per-syllable effects beyond the standard `\k` word highlight.
- Multi-language beyond what WhisperX supports.
- Streaming / realtime.

These are all additive — they don't require changes to the engine modules.
