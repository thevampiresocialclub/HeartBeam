# Handoff — HeartBeam build program

**For:** Astra (or whoever picks this up next)
**From:** Claude; continued by Codex, 6 September 2026
**Repo:** `C:\Users\young\Documents\GitHub\HeartBeam\HeartBeam`
**Continuation base:** `02e78cd`; P03.2 changes follow that handoff.

Read `BUILD-STATUS.md` first — it is the authoritative record of what is done,
what is verified, and what is merely assumed. This document is the part that
does not fit there: how to run things, what bit me, and what to do next.

The build program itself lives outside the repo at
`C:\Users\young\Documents\Codex\2026-09-06\run\outputs\heartbeam-claude-handoff\`.
Start with `00-START-HERE.md` and `08-SHARED-CONTRACT.md`. Do not skip the
contract; it is what stops the seven projects producing incompatible editors.

---

## Where the work stands

| | |
|---|---|
| P01 Foundation | Complete (all four phases verified) |
| P02 Lyrics editor | Verified |
| P03.1 Architecture proof | Verified |
| P03.2 Transport and waveform | Implemented; evidence and limits in BUILD-STATUS |
| **P03.3 — next** | Timing edit scopes |
| P04–P07 | Not started |

182 tests pass in the current installed environment. Run `git status --short`
for the current tree state rather than relying on a historical clean-tree claim.

The product works end to end today: generate or import a song, paste and edit
lyrics without losing timing, correct word timing on a waveform, and render a
karaoke video — closing the app and reopening resumes all of it without rerunning
separation.

---

## Running it

```powershell
# tests (the fast suite; ~14 s)
.venv\Scripts\python.exe -m pytest tests\ -m "not slow" -q

# tests that render real audio/video through ffmpeg
.venv\Scripts\python.exe -m pytest tests\ -m media -q

# the app
.venv\Scripts\heartbeam-gui.exe          # or the desktop "HeartBeam" shortcut
```

The commands are **not on PATH** — they live in the venv. Activate it
(`.venv\Scripts\Activate.ps1`) or use full paths.

**Environment as verified on this machine:** Python 3.12.10, torch 2.8.0+cu128,
RTX 5070 (sm_120, 11.9 GB), ffmpeg 8.1.1 with libass, streamlit 1.57.0.
~11 GB of models cached at `~/.heartbeam/models`.

A Streamlit server may still be listening on port 8501 from Claude's session.
The continuation used a separate server on 127.0.0.1:8502. The original server
was not stopped. If 8502 is unavailable, use the app command above.

### A test project with real audio

Several checks need a real project rather than a synthetic one:

```powershell
.venv\Scripts\python.exe -c "from heartbeam import project as P; P.import_legacy_timings(r'<dest>', 'out/timings.json', 'out/karaoke.mp3', name='Helena')"
```

That builds a 245-word, 3:24 project from artifacts already in `out/`.

The continuation's separate browser fixture is at
`C:\Users\young\Documents\Codex\2026-09-06\run\work\p032-browser-project`.
It has 260 words (Helena plus 15 clearly labeled untimed verification words),
and saved original/lead/karaoke assets. The extra words are for verification,
not part of the song. Do not mistake their lack of timing for an alignment bug.

---

## Traps I hit, so you do not have to

**Streamlit component registration cannot be cached.** `@st.cache_resource` on
`components.v2.component(...)` breaks mounting with *"Component is not
registered"* — registration populates a per-run registry, so it must happen every
script run. Cache the assets, never the registration.

**A component updates against the same parent element.** Appending blindly
stacks another root/audio. P03.2 preserves the existing instance on that parent
and updates its data/bridge callbacks; destroying it on every update loses
position, source and zoom. Destroy only on project change or disconnection.
After changing frontend code during development, reload the page: an existing
instance still owns its previous JS closure even if registration reads new code.

**Selection must survive nearby reruns.** A one-shot `selected` trigger could
be lost when the user selected a lyric and immediately pressed a Python nudge.
P03.2 uses persistent `selection` component state with a nonce. Consume a new
selection before controls; ignore the same nonce on later runs so it cannot
override Python review navigation. Timing drags remain committed triggers.

**Media registration cannot be skipped on a rerun.** Streamlit clears session
media references each run. Register audio AND peak files each time even when
their URLs have not changed; cached URL-only registration can lead to 404s.
`editor_media.register_media()` isolates the private API. The real range/HEAD
handler is tested and Streamlit is pinned to 1.57.0. Files still consume server
RAM; do not describe this as a disk-streaming implementation.

**`st.session_state[key]` cannot be written after that widget exists.** Undo/redo
that needs to push new text into a `text_area` must version the widget key
instead. See `_lyrics_editor` in `gui.py`.

**Buttons gated on a text field are untestable** and jump around as you type.
Render them always; validate on click.

**AppTest cannot execute JavaScript.** Anything in `editor_assets/` must be
verified by driving a real browser. AppTest passing proves nothing about the
timeline.

**`requestAnimationFrame` does not fire in the automated browser** (and not in a
background tab either), while audio keeps playing. Do not build a display that
depends on rAF alone — the clock silently desynchronises from what you hear.

**Windows paths break naive TOML and Python string handling.** `C:\Users` fails
to parse (`\U` starts a unicode escape) and `C:\temp` silently becomes
`C:<TAB>emp`. Use `style.toml_string()`. This also bit me repeatedly when writing
Python through shell heredocs — build backslashes with `chr(92)` or write files
directly.

**`%LOCALAPPDATA%` is not a safe cache root here.** Microsoft Store Python
redirects those writes into an MSIX sandbox while still reporting the nominal
path. Everything goes under `~/.heartbeam` via `heartbeam/paths.py`.

**cu121 is wrong for this machine.** Its kernels stop at sm_90; the RTX 5070 is
sm_120. The GPU build must come from the cu128 index, and `heartbeam` preflights
this and refuses to start on a mismatch.

---

## Module map

Engine (unchanged by the build program, mostly):
`cli.py` `cli_video.py` `separate.py` `align.py` `mask.py` `mix.py` `io.py`
`lufs.py` `render.py` `ass_writer.py` `style.py` `timings.py` `models.py`

Added by P01–P03:
- `paths.py` — one cache root for every model download
- `project.py` — the saved-project store. Stdlib only, no Streamlit or torch.
- `audio_cache.py` — lossless original/stems/clean reference with provenance
- `lyrics.py` — reconciliation, undo, alignment application
- `waveform.py` — peak extraction and caching
- `editor_media.py` — cached audio adoption, source validation, served audio/peaks
- `editor.py` + `editor_assets/` — the timing editor bridge and frontend
- `gui.py` — the Streamlit shell that wires it together

Three ideas hold the data model together, and breaking any of them will cause
subtle corruption rather than a crash:

1. **Stable IDs.** Never key anything on word text or position. Repeated choruses
   are normal.
2. **One place resolves timing.** `Project.effective_timing()` decides whether a
   user edit or the aligner's immutable proposal wins. Do not cache a second
   copy of "current" timing anywhere.
3. **Integer milliseconds**, converted once at the importer boundary.

---

## Next: P03.3 — timing edit scopes

Read `03-PLAYBACK-TIMING.md` and section 5 of the shared contract.

The four P03.2 priorities above are now implemented: served audio, source
switching, multi-resolution peaks and lyric-list selection. See BUILD-STATUS
for measured seek accuracy and source-loading delays. Switching pauses briefly
to load; it does not promise gapless audio.

Continue with distinct word/phrase/global timing commands and undo/redo, then
P03.4 review flow. Preserve the working transport and its frontend state across
Python updates. Validate finite/integer inputs and bounds before changing the
project. Measure the full-song committed-interaction target instead of treating
passing Python tests as browser performance evidence.

The original P03.1 ASS-preview requirement is still unproved. Resolve that
integration decision explicitly before calling all of P03 complete. The lyric
list's current-word highlight is not an ASS video preview.

### Deliberately left undone

- **No ASS preview.** SubtitlesOctopus is a candidate the contract says to
  validate, not adopt. Unevaluated.
- **Section IDs are rebuilt on each lyric edit**, so they are not stable across
  edits. Line and word IDs are, which is what timing depends on — but fix this
  before P04 attaches vocal regions to sections.
- **`apply_alignment()` has no UI.** Re-aligning an existing project belongs to
  P03; the function exists and protects manual corrections by default.
- **Concurrent editing is unhandled.** Contract section 4 wants conflict
  detection; two sessions on one project will last-write-wins today.
- **The model A/B sweep is parked as P07 work.** Tooling and models are ready.
  See the "Parked" section of BUILD-STATUS for why it should stay parked until
  the section vocal mixer exists.

---

## How to leave it for the next person

The build program asks for `BUILD-STATUS.md` to be updated after every project
with what was delivered, the exact validation commands and results, what could
not be verified, and the next project. I have tried to keep the "not verified"
sections honest and specific — please keep doing that. The most useful thing in
this file is not what works; it is knowing exactly which claims have evidence
behind them.

One standing note from the user: they want to be told when something is
uncertain rather than given a confident summary that turns out to be wrong.
