# HeartBeam

Lyrics-aware karaoke generator and video editor. Load a song and paste its lyrics, then edit timing, place and style the text, and adjust vocal levels by section. Separation aims to reduce the lead while retaining backing vocals; the result depends on the recording and model.

Two phases, one engine:

- **Phase 1 (`heartbeam`)** — audio. Separates the song, matches lyric phrases against the complete vocals, refines word timings, builds a time-domain mask, and writes `karaoke.mp3` + `timings.json` + `lyrics.lrc`. Unmatched words remain available for repair in the editor.
- **Phase 2 (`heartbeam-video`)** — video. Consumes `karaoke.mp3` + `timings.json` + a `style.toml`, generates an ASS subtitle file with per-word karaoke (`\k`) tags, and renders the final MP4 via `ffmpeg` + `libass`.

Re-running Phase 2 with a different style does not re-run the slow ML pipeline.

---

## Install

**HeartBeam targets NVIDIA GPUs — GTX 1050 / RTX xx50 and up.** The install
scripts probe for one automatically:

- **GPU** (~3 GB on disk): the supported build. A song takes 1–4 minutes.
- **CPU** (~700 MB): for running the tests, or a run you're willing to wait
  20–75 minutes for. `heartbeam` refuses to start without CUDA unless you pass
  `--allow-cpu`. See [Hardware](#hardware--what-to-expect).

### Recommended: one-line install script

```powershell
# Windows (PowerShell)
git clone <this repo>
cd HeartBeam
.\scripts\install.ps1                  # auto-detects NVIDIA -> GPU, else CPU
# or force one:
.\scripts\install.ps1 -Variant GPU     # GPU build (cu128 wheels from pytorch.org)
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
pip install --index-url https://download.pytorch.org/whl/cu128 torch torchaudio torchvision
```
(else you'll get CPU torch wheels.)

### Requirements

1. **Python 3.10+**
2. **ffmpeg with libass.** Auto-installed by `install.ps1` / `install.sh`. Manual: on Windows install [Gyan.FFmpeg](https://www.gyan.dev/ffmpeg/builds/) full build via winget; on macOS `brew install ffmpeg`; on Ubuntu `sudo apt install ffmpeg`. Verify with `ffmpeg -filters | grep ass`. **Not optional** — it decodes the input file, not just the video render.
3. **NVIDIA GPU**, GTX 1050 / RTX xx50 and up, with a driver new enough for CUDA 12.8. 4 GB VRAM works; alignment moves to the CPU automatically below 6 GB.

Model checkpoints (~500 MB for `pop`, ~3 GB for `rock`, +2 GB for `metal`) are downloaded by audio-separator on first use of each preset.

---

## Hardware — what to expect

**Supported: NVIDIA, GTX 1050 / RTX xx50 and up.** The GPU build installs torch
from the **cu128** index, whose kernels span `sm_61` (GTX 1050) through `sm_120`
(RTX 50-series / Blackwell).

> Do not "fix" this back to cu121. Those wheels stop at `sm_90`, so on any
> RTX 50-series card every CUDA call dies with *"no kernel image is available
> for execution on the device"*. `heartbeam` preflights the installed torch
> against your card's compute capability and refuses to start on a mismatch,
> rather than failing 40 minutes into a run.

Cards in the 4–6 GB range (RTX 3050 laptop, 4050) are supported, but the
separator's model is still resident when WhisperX loads its own. HeartBeam
detects this and moves alignment to the CPU automatically — it costs well under
a minute. Override with `--align-device cuda`.

Only **CUDA** accelerates this pipeline. That is not a design choice; it is the
state of the two libraries doing the heavy lifting:

- **WhisperX** runs ASR through CTranslate2, whose device enum is literally
  `{CPU, CUDA}`. There is no Intel, DirectML, Vulkan, or OpenVINO backend.
- **audio-separator** has a DirectML path, but MDXC/RoFormer models — which is
  every model `pop`, `rock`, and `metal` use — fall back to CPU on it
  (`ComplexFloat` is unsupported), and Demucs fails outright. It has no
  `torch.xpu` support at all.

So an AMD or Intel GPU — including Arc and Core Ultra iGPUs — gets you the CPU
path, not acceleration. There is currently no route around this short of
replacing both libraries.

Rough wall-clock for a 4-minute song:

| Machine | `pop` | `rock` |
|---|---|---|
| RTX 5070 (measured) | ~80 s | ~2–4 min |
| Modern 8-core CPU | ~20–30 min | ~45–75 min |

These measurements predate the phrase-matching workflow. A smaller recognition
model can reduce CPU work, but recognition errors can prevent a phrase from
being located. HeartBeam now matches the actual lyric sequence and flags gaps;
it does not proportionally distribute lyrics across whatever speech was found.

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

> **First: the commands live in the venv, not on your PATH.** A fresh terminal
> will answer `heartbeam-gui : The term ... is not recognized`. Either activate
> the venv once per shell:
>
> ```powershell
> cd C:\path\to\HeartBeam
> .\.venv\Scripts\Activate.ps1     # prompt gains (.venv)
> ```
>
> ...or call the executables by full path (`.\.venv\Scripts\heartbeam-gui.exe`).
> For a permanent double-click launcher, run `.\scripts\create_shortcut.ps1`
> once — it puts HeartBeam on your desktop and Start Menu, and those work
> without any activation.

### The GUI (easiest)

```powershell
.\.venv\Scripts\heartbeam-gui.exe     # or just `heartbeam-gui` once activated
```

Opens a local Streamlit app at <http://localhost:8501>. It covers **both
phases**:

1. **Separate audio:** choose a song, paste its lyrics and pick a genre profile.
   When separation finishes, audition the result, choose a project folder and
   select **Save project and edit video**.
2. **Edit video:** the desktop workstation keeps Play/Pause, video preview and
   waveform together on the left. The right pane has live lyric selection and
   **Appearance**, **Lyrics**, **Timing**, **Vocals** and **Export** tabs. Each
   pane scrolls independently. A single Play button drives audio, highlighting,
   video backgrounds and the waveform. Use **Save project** in the top bar to
   keep edits, then **Render video** in Export to create the MP4.

Opening a saved project goes straight to video editing. The two step buttons
let you return to separation without losing the loaded project. On narrow screens
the panes stack to keep the controls usable.

Because Phase 2 is only ffmpeg, restyling takes seconds and never re-runs the
slow ML. The Windows installer creates Start Menu and desktop shortcuts pointing
at this.

It shells out to the same `heartbeam` and `heartbeam-video` CLIs, so anything
below applies equally.

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


## Timing and section vocal editing

**Find lyrics online** searches LRCLIB by song metadata and previews the result
before you choose it. In a saved project, choose its text and timing hints or
keep your text and use only its timing hints. No song audio is uploaded.

In **Timing → Match lyric timing**, match the whole song, selected lines, or
lines needing review. The matcher uses complete vocals, verifies online timing
against the recording, then refines words inside their own phrases. Recognition
is cached. For a difficult phrase, select its line, set approximate start/end
boundaries, use **Loop this phrase** and **Play**, then run matching on that line.
Manual word corrections are retained. See [the timing system](docs/TIMING_SYSTEM.md)
for the architecture, tests and known limits.

Open a saved project to edit lyrics directly in the text box. The timing editor
supports word/edge dragging, precise numeric times, word/line/song nudges,
review flags, undo/redo, configurable selection loops, and a rendered lyric
preview. Save keeps corrected timing and review state. Export uses those current
timings; unresolved words or timing conflicts must be fixed first.

The **Playback preview** controls play or pause the shared song clock, restart at
the beginning, and jump to the previous or next lyric display boundary. Use them
to review timing, highlighting, font and placement together before rendering.

Under **Section vocals**, target a lyric line, multiple lines, a named section,
or a time range. **Vocal level** ranges from 0% (processed karaoke reference) to
100% (original reference). Drag the live slider or enter an exact percentage.
Regions replace overlapping portions of the same lane; they do not stack gains.
Use **Refit to source lyrics** to move a region after timing corrections, and
**Rebuild clean audio from corrected timing** only when you want to rebuild the
removal mask from saved stems. Both actions can be undone.

Older projects need calibrated clean/original audio: link their generation
cache, or explicitly prepare references from the original file and saved stems.
A normalized karaoke MP3 is not a calibrated clean reference. Final mix audition
and WAV download are available under **Audio references and final mix**; video
export uses the edited mix and retains a revision-specific project snapshot.

The renderer and fonts are bundled; ordinary users need no Node installation
or browser CDN access. See [BUILD-STATUS.md](BUILD-STATUS.md) for verified
behavior and limits, and [HANDOFF.md](HANDOFF.md) for the continuation guide.

## Lyric placement and styling

In the saved project's **Appearance** tab, choose **Whole song** to edit the
defaults, or **Selected lyric line / Lyric lines** for exceptions. Select a word
or use **Preview line**, then drag the lyric box on the video. Exact X/Y,
anchor, alignment, width and margin controls are available below it. Focused
handles also accept arrow keys (1 design pixel, or 10 with Shift).

Choose a font, size, bold/italic, unsung and sung colours, outline colour and
thickness, and shadow. Whole-word highlighting changes at onset; sweep mode
fills during the word. Sung words retain their colour. Zero removes the outline
or shadow. The wrapping box inserts display breaks without changing timing.

**Fonts in this project** imports static TTF/OTF files or copies an installed
family. The browser and export use the same files. Missing faces are reported
and use Noto Sans; characters absent from the chosen font block final export.
Solid, image and video backgrounds persist with the project. Images/videos
fill the canvas with a centered crop; background video audio is excluded.

Save a named style preset and download it to reuse in another song. Presets
contain appearance defaults, with no audio, timing or media paths. Applying one
preserves line exceptions; **Reset selected lines to song style** removes them.
Legacy TOML styles can be imported into song defaults.

**Render video** uses the current project's timing, vocal mix and appearance.
Positions, font sizes and outlines scale together from a 1920 × 1080 design
canvas to 720p, 1080p or 4K. Visual changes make older videos stale while keeping
prepared audio. **Lyric reading timing** can show each phrase before its first
word, hold the stack between phrases, and show 2, 3 or 4 lyric lines at once.
Vertical spacing controls where the upcoming rows sit. Word highlighting and
vocal regions keep their musical timing.

Rendering runs as a revision-labeled job, so the editor remains available.
Progress and cancellation are shown in the app. A video is published only after
the complete encode succeeds; failure or cancellation keeps the last good video.
Use **Render a short passage first** for a final-quality check of up to 60 seconds.
Save the project to keep edits across sessions. See [docs/EXPORTS.md](docs/EXPORTS.md)
for the workflow and recovery files, and [docs/PRESENTATION.md](docs/PRESENTATION.md)
for the presentation/compiler contract.
