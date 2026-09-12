# HeartBeam handoff

**Updated:** 10 September 2026 by Codex, including warning-only video export for
estimated, missing and conflicting timing. Independent lead/backing mixing remains.
**Repo:** `C:\Users\young\Documents\GitHub\HeartBeam\HeartBeam`
**Continuation base:** use `git log -1`; P03 through P06 are committed milestones.

Read **BUILD-STATUS.md first**. It is the authoritative record of completion,
tests, measured performance and remaining validation limits. This handoff
explains how to continue without breaking the working editor.

P03, P04, P05 and **P06, dependable preview/export**, are implemented. The owner's
follow-up timing system is now implemented too; read `docs/TIMING_SYSTEM.md`.
It adds optional LRCLIB lookup, complete-vocal matching, phrase-local refinement,
selective/manual-window repair, cached recognition and honest unresolved words.
The GUI prepares tracks, saves a project and opens timing review. The owner can
make any corrections, then choose **Build karaoke and continue** without fixing
or approving every word. Missing timings/conflicts warn. Missing words can now
highlight using labelled estimates within their phrase; raw word values and
review flags remain unchanged. This is the owner's explicit new policy, replacing
the earlier requirement to keep every uncertain word plain. Estimates are enabled
by default, opt-out in Timing, and do not replace acoustic/manual evidence.
New GUI builds select independent instrumental/lead/backing mixing. Both vocal
tracks have 0–100% controls in 1% steps; regions override only the lead default.
See `docs/TIMING_SYSTEM.md` for algorithms, legacy compatibility and approval.
Video export now accepts estimates, missing words, overlaps and stale timing
approval with warnings. It uses current preview timing and the saved audio mix.
Untimed words stay plain in known lyric/display windows; wholly unanchored lines
are omitted with warnings. Lyric/timing/source edits still invalidate audio-build
approval, but do not force a rebuild just to render a video.
Export status now updates automatically without rerunning the playback editor
each second. Windows progress-file lock failures retry, then warn instead of
aborting encoding; completed export folders remain recoverable even if status
bookkeeping could not be persisted. See BUILD-STATUS.md for the post-export
reproduction, full-song browser check and 344-test Python result.
The Frost Children stalled-prefix regression now retries near the recognized
suffix instead of accepting a plausible score four seconds early. The backing
stem also contains recognized lead phrases; timing alone cannot resolve that.
Zero backing gain excludes that stem for the whole song; its leakage cannot be
removed independently from its harmonies by these controls.
Broader P07 audio-quality/model evaluation remains. The original program is in
`C:\Users\young\Documents\Codex\2026-09-06\run\outputs\heartbeam-claude-handoff`.
Read `06-PREVIEW-EXPORT.md`, `docs/PRESENTATION.md`,
`08-SHARED-CONTRACT.md` and `09-RELEASE-CHECKLIST.md` before continuing.

## Run and verify

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
node --test tests/audio_transport.test.mjs tests/presentation.test.mjs tests/timeline_navigation.test.mjs tests/workstation.test.mjs tests/waveform_seek.test.mjs
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
The waveform now replaces the separate song-position slider. Pointer scrubbing,
keyboard seeking, auto-follow and the time field share HBTransport's clock.
Firefox does not implement `AudioParam.cancelAndHoldAtTime`: calling it during
a playing seek left the old audio running while the displayed clock jumped.
HBTransport now reconstructs its known fade-in ramp using `cancelScheduledValues`
and `linearRampToValueAtTime`. Keep this Firefox-compatible path and its
short-interval seek regression test. See BUILD-STATUS for the before/after
Firefox transport evidence and the separate full Chrome workstation proof.
The full Firefox editor now also has measured line-selection, native dropdown,
partial-highlight, spacing-stepper and warning-only audio-build checks. Review
line clicks send an explicit navigation nonce so repeated clicks seek again.
Use the decoded audio duration, since imported asset metadata can omit it.
Do not overwrite a focused native dropdown each animation frame: Firefox's
intermediate selection was being reset before it could commit. Discard an old
navigation request when a new page mounts with a different current selection.
Do not wrap the workstation in `st.empty().container()`: clearing that container
recreates the audio player on ordinary timing edits and undo. Page approval is
already handled before rendering, and tabs have separate stable keys for each
editing mode. The full GUI workflow tests cover those transitions.
`scripts/waveform_browser_proof.mjs` is an optional Playwright proof against a
disposable MP3/video project named `Waveform playback test`. It verifies both
editing pages, dragging, synchronization, timing edits/undo while playing, loops,
and source switching. `HEARTBEAM_PLAYWRIGHT` can select a bundled installation;
Playwright is not an end-user dependency. The script closes its project to release
the writer lease before disconnecting the test browser.
The Windows venv uses Store Python; an automation sandbox may fail to launch it
even when it works outside that sandbox. Do not rebuild a healthy environment
or downgrade torch on that evidence alone. Verified environment and warnings
are recorded in BUILD-STATUS. RTX 5070 requires the existing cu128 build;
cu121 does not support its sm_120 kernels. Keep the model sweep parked.

Claude's server may still exist on 8501; P03/P04 used 8503. P05 used a separate
server on 8504. Do not kill a server without establishing which task owns it.
This timing implementation was browser-tested on its own server at 8505, using
`C:\Users\young\Documents\Codex\2026-09-06\run\frost-hybrid-proof`.
The owner's original temporary project was not changed. The copy is a review
draft, not a completed karaoke timing track: 57 words remain untimed after the
whole-song proposal. The matching LRCLIB record has cues past the actual audio
end despite apparently matching duration metadata; the new guard rejects it.

The most important new regression is selected repeated lyrics: keep the entire
song's text as matching context, then refine/apply only selected IDs. Matching
just the selected text globally can silently choose a different chorus. Never
restore the removed proportional lyric-to-ASR allocation. Manual boundaries
skip recognition; automatic missing-line recovery remains bounded and flagged.

## Code map and contracts

- `project.py`: serialized project, IDs, asset metadata, effective timing and
  atomic saves. New fields are optional when reading existing version-1 projects.
  `raw_timing()` resolves manual edit, latest alignment proposal, then immutable
  original proposal. `effective_timing()` fills missing raw values with labelled
  estimates from `timing_estimates.py`. Renderers must use the shared resolver.
  Fill-only acoustic alignment uses raw timing so estimates remain replaceable.
- `stem_mix.py`: validated independent instrumental/lead/backing summation.
  `VocalMix.backing_value` is additive and defaults to 1. Existing projects keep
  `clean_to_original` until the user enables separate tracks; new GUI builds use
  `separated_stems`. Track level commands share undo, save and export settings.
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
- `presentation.py`: presentation defaults, sparse overrides, validation,
  presets and export snapshots. `compile_project` delegates to `lyric_scene.py`
  for both preview and native export; `render_project` freezes fonts/backgrounds.
- `lyric_scene.py`: deterministic top-to-bottom rolling scene, explicit or
  measured wrapping, letter/row spacing and movement segments for handles.
  Timed words use individual absolute `\kt` onsets, preserving gaps, overlaps
  and ongoing sweeps across event splits. Missing words keep plain colours;
  they must not disable highlighting for an entire otherwise-timed phrase.
  A fixed tallest-phrase slot keeps the top position stable through the song.
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
  final export; drafts retain untimed words as plain text in anchored phrases.
  Do not reintroduce a second
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
7. Audio tracks must share their pre-mastering sample/gain basis. Legacy mode
   blends `clean + restore * (original - clean)`. Separated mode uses
   `instrumental + lead * lead_envelope + backing * backing_value`. One final
   mastering stage follows the whole mix; never add the instrumental twice.
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

## Current continuation point

The GUI has preparation, timing-review, video-editing, music-repair and export
pages, with a save-folder transition after preparation. Pending projects reopen
in review; built projects open in video editing. Export is reached through the
optional Music Repair review. Individual word or repair-suggestion review does
not block the relevant continue button.
The desktop monitor and inspector are separate scroll containers. The right-pane
component hosts the existing live lyric/vocal DOM controls through
`editor_assets/workstation.js`; it never creates another transport. Preserve
Streamlit's style nodes when mounting hosts. `scripts/workstation_browser_proof.cjs`
checks this against an eight-second synthetic project, using development-only
Playwright and installed Chrome. It creates its own disposable project copy.

P06 is complete. The editor now also saves 2–4 visible lyric rows and provides a
prominent playback preview with Play/Pause, Restart and previous/next lyric jumps.
Those jumps use compiled display starts; the same ASS and concrete fonts still
drive browser preview and native export. The current phrase is on top, future
phrases below, and promotion starts at the current phrase's last sung end.
Rise duration defaults to 220 ms; zero disables animation. Overlapping future
words can highlight before promotion. Letter spacing and line height persist
through styles, overrides, presets, save/reopen and undo. Legacy signed upcoming
offset fields are readable but ignored; see `docs/PRESENTATION.md`.

Visual revisions must not invalidate audio. `vocal_mix.mix_key()` identifies
final audio by content; the browser ignores revision-only changes when audio
inputs/templates match. Safe-area guides and selection never enter exports.
Preset JSON contains defaults only; it is not a project or a portable media
bundle. Font/background relinking and Save a copy remain available.

Deliberate limits: static TTF/OTF faces only; missing glyphs block final output;
box/overflow guides are metric estimates, with libass providing actual text;
no pixel identity claim across rasterizers/colour management. Browser video
preview needs a supported codec. Media still occupies RAM, and undo history
remains session-local. P07 R0 and the first R1 product pass are implemented.
`audio_calibration.py` puts new separator outputs on the decoded source basis;
`audio_analysis.py` ranks local instrumental drops; `instrument_repair.py`
applies only explicit, reversible level corrections; `repair_ui.py` owns the new
step between video editing and export. Project schema 2 migrates schema 1 and
keeps a pre-migration backup on first save. R2's controlled complementary-model
and reallocation experiment is next. A volume dip is a review clue, not evidence
of what musical content belongs there; do not auto-apply suggestions or call
local gain missing-instrument reconstruction.
Restart after cross-module updates so Streamlit cannot retain old imports.
The owner already explicitly authorized restarting without saving in this session;
do not repeat that approval request. The latest update was tested on isolated
fixtures at 8506 before activation at 8505. Check BUILD-STATUS for final evidence.

Label lead/backing percentages as stem gain in separated mode. Legacy **Vocal
level** still goes from the processed reference to the original. Avoid claims
of perfect lead separation or unchanged harmonies. Measured sample accuracy and numerical smoothness do not
substitute for a subjective listening verdict; evidence and an audition sample
are listed in BUILD-STATUS.

The standing user preference is to distinguish uncertainty from verified facts.
Update BUILD-STATUS with commands, observations and limits after the next phase;
do not replace that evidence with a confident summary.
