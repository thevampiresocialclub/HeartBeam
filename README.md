# HeartBeam

Lyrics-aware karaoke generator and video editor. Load a song and paste its lyrics, then edit timing, place and style the text, and adjust vocal levels by section. Separation aims to reduce the lead while retaining backing vocals; the result depends on the recording and model.

Two phases, one engine:

- **Phase 1 (`heartbeam`)** — audio. Separates the song, matches lyric phrases against the complete vocals, refines word timings, builds a time-domain mask, and writes `karaoke.mp3` + `timings.json` + `lyrics.lrc`. Unmatched words remain available for repair in the editor.
- **Phase 2 (`heartbeam-video`)** — video. Consumes `karaoke.mp3` + `timings.json` + a `style.toml`, generates an ASS subtitle file with per-word karaoke (`\k`) tags, and renders the final MP4 via `ffmpeg` + `libass`.

Re-running Phase 2 with a different style does not re-run the slow ML pipeline.

---

## Install with a local coding agent

The recommended route is a GitHub checkout plus the repository setup script. Give Claude Code or Codex the repository and [INSTALL-WITH-AN-AGENT.md](INSTALL-WITH-AN-AGENT.md). The agent must run on the PC where HeartBeam will be installed. An AI subscription is setup assistance, not a requirement for running HeartBeam.

**Windows x64 / Python 3.12 is the maintained setup baseline.**

The repository is private. Friends first accept a GitHub invitation, then clone
`https://github.com/thevampiresocialclub/HeartBeam.git` into a permanent folder.
From that checkout:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install.ps1
.\scripts\create_shortcut.ps1 -VenvDir .\.venv
.\scripts\start.ps1
```

The script defaults to `<checkout>\.venv`, pins the known dependency versions, checks FFmpeg/FFprobe and reports installation failures. It uses an editable installation, so keep the checkout in a permanent folder. See the agent guide for custom install paths, model downloads, diagnostics, updates and the required smoke test.

| Setup variant | Purpose |
| --- | --- |
| `Auto` (default) | GPU when NVIDIA is detected; otherwise Editor with an explicit limitation |
| `GPU` | Full preparation on a compatible NVIDIA GPU; CUDA 12.8 Torch wheels |
| `Editor` | Edit and export already-prepared projects without ML packages or models |
| `CPU` | Experimental local ML via the CLI with `--allow-cpu`; not a supported GUI preparation workflow |

Without a graphics card, an agent subscription does not supply compute. A remote ML bridge and hosted service are ideas only and are not included in this build.

For GPU setup, download the default models before testing a song:

```powershell
.\.venv\Scripts\python.exe scripts\fetch_models.py --presets pop --whisper medium --language en
.\.venv\Scripts\python.exe -m heartbeam.doctor --variant GPU
```

Rock and metal models can be added later. Allow several GB for dependencies and models plus space for songs, stems and exports. Installed size and runtime vary; old development estimates are not clean-machine guarantees.

### Projects and output folders

The **File** menu opens, saves and names project copies. Preparation is saved automatically in numbered folders such as `Documents/HeartBeam/Sessions/1`; **Save as** creates a readable name under `Documents/HeartBeam/Projects`. Existing projects stay in place. The File and Tracks menus open their folders directly. Exports belong to the project, default to `input_filename_karaoke.mp4`, and include **Show video in folder** after rendering. See [Files and distribution](docs/FILES-AND-DISTRIBUTION.md).

### Hardware and other installation routes

The verified development GPU is an RTX 5070 using Torch 2.8.0+cu128. Setup performs a CUDA calculation, but a real song test is required to validate another card, its memory and model execution. Do not downgrade RTX 50-series installations to `cu121`.

HeartBeam uses CUDA for its supported ML path. Other GPU backends and macOS/Linux installation are not validated by the Windows setup work. `scripts/install.sh` remains a legacy advanced-user route; do not treat it as the same constrained installation. FFmpeg with libass, libx264, libmp3lame and AAC support is required for decoding and export.

The existing [Inno Setup recipe](installer/README.md) is retained for future packaging, but a standalone installer is not the current distribution deliverable. For maintenance, use the agent guide and [distribution status](docs/DISTRIBUTION-PLAN.md).

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

Opens a local Streamlit app at <http://localhost:8501> with four steps:

1. **Prepare audio:** choose a song, paste its lyrics and pick a genre profile.
   Preparation saves the separated tracks and suggested lyric timing without
   building the removal mix. Choose **Save project and review timing**.
2. **Review timing:** play the original or vocal tracks with the waveform and
   lyric preview. Make any timing corrections in **Timing**. In **Build karaoke**,
   set **Backing vocals (%)** and select **Build karaoke and continue**.
   Missing word timings and conflicts warn without blocking this step.
   Missing words get labelled timing estimates from their neighbors or phrase
   window, preserving raw and manual timings. Individual word approval is optional.
   The new mix uses saved instrumental, lead and backing tracks across the whole
   song; it does not rerun separation or depend on lyric timing to mute vocals.
3. **Edit video:** the desktop workstation keeps Play/Pause, video preview and
   waveform together on the left. The right pane has live lyric selection and
   **Appearance**, **Lyrics**, **Timing** and **Vocals** tabs. Each
   pane scrolls independently. A single Play button drives audio, highlighting,
   video backgrounds and the waveform.
   **Vocals → Instrumental volume** retains optional, reversible volume lifts
   for a passage you choose. Existing saved adjustments remain editable there.
4. **Export:** go directly from video editing to Export. Use **Save project**
   in the top bar to keep edits, then render a passage or the full MP4. Export
   uses your saved vocal levels and any explicitly applied volume adjustments.

The automatic thin-spot detector and experimental instrument recovery are
archived after listening did not demonstrate useful improvement. See
`docs/ARCHIVED-INSTRUMENT-RECOVERY.md` for the preserved technique and evidence.

In either editing page, **click or drag the waveform to seek**. The playhead,
played portion, lyrics, video and time display follow the same audio clock.
Scrubbing keeps audio playing if it was playing, or leaves it paused. **Follow
playback** keeps a zoomed playhead in view; turn it off to inspect another area.
The lyric blocks below the waveform still edit word timing. With the waveform
focused, arrows seek one second (Shift: 0.1 second), Home/End jump to the song
boundaries, and Space plays/pauses. Seeking outside a selected loop exits it.
Play/Pause and the time display stay visible as you scroll through the monitor.

Prepared projects reopen in timing review. Approved projects and older projects
without phrase matching reopen in video editing. Video export uses current
lyric timing and the saved audio mix, warning about timing issues without
requiring another approval or audio build. The step buttons
let you return to preparation without losing the loaded project. On narrow screens
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

This describes the batch CLI and legacy selective mixer. New GUI builds use
the independent stem mixer described above, so missing lyric timing cannot
switch the original vocals back on.

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
timings. Missing words and timing conflicts show warnings and allow rendering.

The **Playback preview** controls play or pause the shared song clock, restart at
the beginning, and jump to the previous or next lyric display boundary. Use them
to review timing, highlighting, font and placement together before rendering.

Above the video preview, **Lead vocals** and **Backing vocals** each offer
0–100% sliders and exact numeric percentages. Try 1–5% lead for a quiet guide;
backing can be muted, halfway or full. These are independent gains on the saved
stems. The instrumental is included once, and the combined result is mastered
once for export. Mixing the original MP3 back in would also change instruments.

Under **Section vocals**, target a lyric line, multiple lines, a named section,
or a time range. Regions override the lead default without changing backing.
Overlapping regions replace existing portions; they do not stack gains.
**Refit to source lyrics** explicitly follows later lyric timing corrections.

Older projects retain their previous clean-to-original mix until you choose
**Vocals → Use separate lead and backing tracks**. This requires the saved
lossless stems and does not run ML. Without stems, the calibrated legacy mix
still works: 0% is the processed reference and 100% restores its original.
Link the generation cache or prepare references from matching saved audio;
a normalized karaoke MP3 cannot supply independent lead/backing controls.

In **Export → Audio and timing downloads**, choose **Prepare current audio
download** for MP3 and WAV with your current mix settings. The separately
labelled initial build download retains the original build. Video export uses
the current mix automatically and retains a revision-specific project snapshot.

The renderer and fonts are bundled; ordinary users need no Node installation
or browser CDN access. See [BUILD-STATUS.md](BUILD-STATUS.md) for verified
behavior and limits, and [HANDOFF.md](HANDOFF.md) for the continuation guide.

## Lyric placement and styling

In the saved project's **Appearance** tab, choose **Whole song** to edit the
defaults, or **Selected lyric line / Lyric lines** for exceptions. Select a word
or use **Preview line**, then drag the lyric box on the video. Exact X/Y,
anchor, alignment, width and margin controls are available below it. Focused
handles also accept arrow keys (1 design pixel, or 10 with Shift).

Choose a font, size, **Letter spacing (kerning)**, **Line height**, bold/italic,
unsung and sung colours, outline colour and thickness, and shadow. Whole-word
highlighting changes at onset; sweep mode fills during the word. Missing words
use labelled timing estimates where nearby words or phrase timing give bounds.
Turn **Timing → Estimate missing word timing** off to leave them plain instead.
Fully unanchored phrases still need a rough window. Sung words
retain their colour. Zero removes the outline or shadow. The wrapping box
inserts display breaks without changing timing.

**Lyric reading timing** offers 2–4 lines on screen. The current phrase is on
top with upcoming phrases below. When it finishes, the next phrase rises into
the top position and another enters below. **Rise duration** controls that
movement; zero changes lines instantly. The whole stack shares the chosen
placement anchor. Wrapped phrases may occupy more than one physical row.

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
