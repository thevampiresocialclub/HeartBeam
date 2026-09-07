# HeartBeam handoff

**Updated:** 7 September 2026 by Codex, completing P06.
**Repo:** `C:\Users\young\Documents\GitHub\HeartBeam\HeartBeam`
**Continuation base:** use `git log -1`; P03 through P06 are committed milestones.

Read **BUILD-STATUS.md first**. It is the authoritative record of completion,
tests, measured performance and remaining validation limits. This handoff
explains how to continue without breaking the working editor.

P03, P04, P05 and **P06, dependable preview/export**, are implemented. Next is
P07 controlled audio-quality/model work. The original program is in
`C:\Users\young\Documents\Codex\2026-09-06\run\outputs\heartbeam-claude-handoff`.
Read `06-PREVIEW-EXPORT.md`, `docs/PRESENTATION.md`,
`08-SHARED-CONTRACT.md` and `09-RELEASE-CHECKLIST.md` before continuing.

## Run and verify

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
node --test tests/audio_transport.test.mjs tests/presentation.test.mjs
.venv\Scripts\heartbeam-gui.exe
# Or use an explicit local port:
.venv\Scripts\python.exe -m streamlit run heartbeam/gui.py --server.address=127.0.0.1 --server.port=8504 --server.headless=true
# Original eight-second fixture, no ML or downloaded song:
.venv\Scripts\python.exe scripts/p05_proof.py C:/temp/heartbeam-p05-proof --render --background
# Full saved-project/export proof from existing local artifacts (new folder only):
.venv\Scripts\python.exe scripts/p06_full_song_proof.py C:/temp/heartbeam-p06-proof out/timings.json out/karaoke.mp3
```

The Node command is optional development verification, not an application build
step or an end-user dependency. The WASM renderer and fonts ship in the wheel.
The Windows venv uses Store Python; an automation sandbox may fail to launch it
even when it works outside that sandbox. Do not rebuild a healthy environment
or downgrade torch on that evidence alone. Verified environment and warnings
are recorded in BUILD-STATUS. RTX 5070 requires the existing cu128 build;
cu121 does not support its sm_120 kernels. Keep the model sweep parked.

Claude's server may still exist on 8501; P03/P04 used 8503. P05 used a separate
server on 8504. Do not kill a server without establishing which task owns it.

## Code map and contracts

- `project.py`: serialized project, IDs, asset metadata, effective timing and
  atomic saves. New fields are optional when reading existing version-1 projects.
  `effective_timing()` resolves manual edit, latest alignment proposal, then
  immutable original proposal. Do not duplicate that decision in a renderer.
- `commands.py`: `History.execute(project, action, command_id=..., base_revision=...)`
  applies an action to a candidate, then commits one reversible content change.
  Failed validation changes neither live content nor history. Undo/redo cover
  the complete manifest content, including vocal references and provenance.
  Save uses `bump=False` after editor commands; saving is not another edit.
- `project_lock.py`: OS writer lease, released by Close or process exit. The
  second GUI opens read-only and can save an independent copy. `save_project`
  separately checks the loaded manifest hash while holding a short save lock.
- `lyrics.py`: sequence-aware reconciliation, preserving line and section identity
  from surviving word membership. Renaming a heading is not a new identity;
  repeated heading text is not an identity key. Split children inherit source
  appearance; one retains the original line ID. Merges keep the largest source
  style and report conflicting styles. Regions retain explicit times.
- `editor.py`: integer timing validation, word/line/song shifts, conflict
  reporting, review navigation and component payload. Imported conflicts remain
  visible; edits may repair them but must not introduce/worsen conflicts.
- `editor_ui.py`: project-aware controls and the shared command dispatch path.
  Consumes selection before timing actions. Appearance, Timing and Vocals tabs
  use the same history. Keep a stable placeholder for command feedback: inserting
  it conditionally left stale numeric widgets during a selection/nudge rerun.
- `editor_media.py`: the isolated adapter to Streamlit's served media manager.
  Re-register media each rerun; references are cleared between script runs.
  Returned URLs are not base64, but the server still holds media in RAM.
- `editor_assets/audio_transport.js`: one AudioContext clock, source buffers,
  compiled envelope buffers, native loops and short graph-change crossfades.
  The waveform, active words and ASS preview read this clock. Do not add a
  separate audio player to the editing view. Final mix audition is another
  source on the same transport.
- `editor_assets/timeline.js`: local timing drag/selection/zoom, live vocal
  slider, optimistic feedback and command acknowledgements. A gesture sends
  one command with a unique ID and base revision. Late pre-command snapshots
  cannot snap the display back while waiting for its acknowledgement.
- `editor_assets/presentation.js`: browser libass, fonts, background frames,
  placement handles and safe-area guides. Dragging stays local until release;
  numeric controls and handle keys give alternative access. Video backgrounds
  remain paused and sample the AudioContext clock. Do not add a playback clock.
- `presentation.py`: the one project presentation compiler. Resolves song
  defaults and sparse line overrides, anchors/alignment/wrapping, colours,
  fonts, word/sweep tags, presets and export snapshots. `compile_project` drives
  preview and native export; `render_project` freezes actual fonts/backgrounds.
- `presentation_fonts.py`: actual font metadata/coverage, explicit installed-font
  copying and content-addressed assets. A missing face warns and uses Noto in both
  renderers. A missing glyph blocks final export. Imported Noto faces override
  bundled faces, including the fallback, without loading duplicate versions.
- `presentation_ui.py`: scope, appearance form, wrapping, display spelling,
  margins, fonts, backgrounds and presets. It writes only changed fields so a
  colour exception does not freeze an inherited font. Colour code inputs provide
  keyboard access alongside Streamlit's mouse-oriented swatches.
- `vocal_mix.py`: the only region/transition compiler. Inserting a region splits
  overlapping regions in one lane. `compile_envelope` yields sample-position
  knots; browser slider templates and `mix_arrays` use these same knots.
  `render_mix` caches the current mix by content and masters it once at the end.
- `reference_prepare.py`: explicit legacy migration from original audio and
  saved stems. This uses the chosen recipe; it does not infer calibration from
  normalized MP3. Content-addressed files are retained for undo and recovery.
- `project_preview.py`: common effective timing validation plus the browser
  media adapter for `presentation.compile_project`. Unresolved timing blocks
  final export; labelled drafts omit untimed words. Do not reintroduce a second
  project ASS compiler or use legacy timing JSON to render edited projects.
- `project_align.py`: explicit CUDA alignment of the saved lead track. It is
  imported only by that action, writes a new result artifact and preserves
  manual corrections when applying proposals. Transport edits load no models.
- `project_video_ui.py`: passage/full export controls, revision labels, progress,
  cancellation, stale-result display and recovery notices. It has no separate
  style or timing state.
- `export_jobs.py`: immutable deep-copied export inputs, preflight, passage trimming,
  atomically saved job state and private temporary output promotion. A failed,
  cancelled or interrupted job never replaces the last completed video.
  Revision folders retain exact project/presentation/ASS/timing, font files,
  background, warnings and `export-manifest.json` asset/audio identities.
  `render.py` explicitly bounds video by audio duration; `-shortest` alone produced
  an encoder tail. P05 exports resolve safe filter basenames from the export
  directory so quoted/punctuated Windows project folder names work.

## Traps and decisions worth preserving

1. Never cache component registration with `st.cache_resource`; registration
   must occur on every Streamlit script run. Cached registration fails mounting.
2. Streamlit components update against the same parent. Reuse the mounted root
   for ordinary reruns; remove old roots/listeners/workers on replacement.
   A frontend content hash now remounts after source-code changes during
   development. Source/selection/zoom persist through normal content updates.
3. A Streamlit widget key cannot be assigned after that widget was created in
   the current run. Version lyric/numeric widget keys when changing their seed
   values. Persistent selection must be consumed before an adjacent nudge.
4. AppTest cannot run the component JavaScript. Keep real-browser evidence and
   the transport tests; Python-only checks cannot prove audio/ASS behavior.
5. rAF pauses in background tabs. Audio and envelope loops run on the audio
   thread; display refresh has a timer fallback. Never use display timers as
   the source of song time or as the only audio-loop mechanism.
6. Browser mix preparation uses a generation token. A stale decode/template
   task cannot publish over a newer revision. Selecting a range does not apply
   its candidate constant level; only actual slider/numeric editing does.
7. Clean and original must share their pre-mastering sample/gain basis. Blend
   `clean + restore * (original - clean)` before one final mastering stage.
   Linear coefficients avoid the correlated-audio bump of equal-power mixing.
8. Timing corrections do not rebuild clean audio or move saved vocal regions.
   Refit and rebuild are separate explicit, undoable actions. Preserve all
   referenced versions of content-addressed audio for undo/recovery.
9. Keep integer milliseconds in editor state. ASS has 10 ms resolution; round
   absolute boundaries once, not each word/gap independently and cumulatively.
10. Use TOML escaping for Windows paths. Avoid shell heredoc/quoting assumptions
    from Unix. Store Python redirects LOCALAPPDATA; use the existing cache code.
11. Writer leases can outlive a disconnected browser until Streamlit disposes
    its session. Close the project for prompt release, or use Save a copy.
    Never bypass a live lease or discard a stale-save error.
12. Ignore revision, modified time and command-ID bookkeeping when deciding
    whether content is dirty. Undo back to saved content should show saved.

## Next: P06

The owner now has direct placement, font/colour/outline controls, explicit
wrapping, named presets, saved backgrounds and the same ASS in preview/export.
P06 should build preview/export jobs around immutable snapshots, cancellation,
progress, actionable failures and stale results. Read its roadmap for the full
acceptance criteria. Keep the synchronous adapter usable while jobs are added.

Visual revisions must not invalidate audio. `vocal_mix.mix_key()` identifies
final audio by content; the browser ignores revision-only changes when audio
inputs/templates match. Safe-area guides and selection never enter exports.
Preset JSON contains defaults only; it is not a project or a portable media
bundle. Font/background relinking and Save a copy remain available.

Deliberate limits: static TTF/OTF faces only; missing glyphs block final output;
box/overflow guides are metric estimates, with libass providing actual text;
no pixel identity claim across rasterizers/colour management. Browser video
preview needs a supported codec. Media still occupies RAM, and undo history
remains session-local. P06 job controls and the P07 model sweep are not done.

Keep P04's first version labelled **Vocal level**: 0% is the saved processed mix,
100% restores its original reference. Avoid claims of perfect lead separation or
unchanged harmonies. Measured sample accuracy and numerical smoothness do not
substitute for a subjective listening verdict; evidence and an audition sample
are listed in BUILD-STATUS.

The standing user preference is to distinguish uncertainty from verified facts.
Update BUILD-STATUS with commands, observations and limits after the next phase;
do not replace that evidence with a confident summary.
