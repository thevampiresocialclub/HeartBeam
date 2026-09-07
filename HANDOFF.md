# HeartBeam handoff

**Updated:** 6 September 2026 by Codex, continuing Claude's handoff.
**Repo:** `C:\Users\young\Documents\GitHub\HeartBeam\HeartBeam`
**Continuation base:** `2ae7ab1` (P03.2); use `git log -1` for the new commit.

Read **BUILD-STATUS.md first**. It is the authoritative record of completion,
tests, measured performance and remaining validation limits. This handoff
explains how to continue without breaking the working editor.

P03 and P04 are implemented. Next is **P05, the visual lyric editor**, followed
by P06 export jobs and P07 quality/release work. The original program is in
`C:\Users\young\Documents\Codex\2026-09-06\run\outputs\heartbeam-claude-handoff`.
Read `05-PLACEMENT-STYLING.md`,
`08-SHARED-CONTRACT.md` and `09-RELEASE-CHECKLIST.md` before continuing.

## Run and verify

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
node --test tests/audio_transport.test.mjs
.venv\Scripts\heartbeam-gui.exe
# Or use an explicit local port:
.venv\Scripts\python.exe -m streamlit run heartbeam/gui.py --server.address=127.0.0.1 --server.port=8503 --server.headless=true
```

The Node command is optional development verification, not an application build
step or an end-user dependency. The WASM renderer and fonts ship in the wheel.
The Windows venv uses Store Python; an automation sandbox may fail to launch it
even when it works outside that sandbox. Do not rebuild a healthy environment
or downgrade torch on that evidence alone. Verified environment and warnings
are recorded in BUILD-STATUS. RTX 5070 requires the existing cu128 build;
cu121 does not support its sm_120 kernels. Keep the model sweep parked.

Claude's server may still exist on 8501. The continuation used a separate server
on 8503. Do not kill a server without establishing which task owns it.

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
- `lyrics.py`: sequence-aware reconciliation, now preserving section identity
  from surviving word membership. Renaming a heading is not a new identity;
  repeated heading text is not an identity key. Regions retain explicit times.
- `editor.py`: integer timing validation, word/line/song shifts, conflict
  reporting, review navigation and component payload. Imported conflicts remain
  visible; edits may repair them but must not introduce/worsen conflicts.
- `editor_ui.py`: project-aware controls and the shared command dispatch path.
  Consumes selection before timing actions. P05 should use this same history.
- `editor_media.py`: the isolated adapter to Streamlit's served media manager.
  Re-register media each rerun; references are cleared between script runs.
  Returned URLs are not base64, but the server still holds media in RAM.
- `editor_assets/audio_transport.js`: one AudioContext clock, source buffers,
  compiled envelope buffers, native loops and short graph-change crossfades.
  The waveform, active words and ASS preview read this clock. Do not add a
  separate audio player to the editing view. Final mix audition is another
  source on the same transport.
- `editor_assets/timeline.js`: local drag/selection/zoom, ASS canvas, live vocal
  slider, optimistic feedback and command acknowledgements. A gesture sends
  one command with a unique ID and base revision. Late pre-command snapshots
  cannot snap the display back while waiting for its acknowledgement.
- `vocal_mix.py`: the only region/transition compiler. Inserting a region splits
  overlapping regions in one lane. `compile_envelope` yields sample-position
  knots; browser slider templates and `mix_arrays` use these same knots.
  `render_mix` caches the current mix by content and masters it once at the end.
- `reference_prepare.py`: explicit legacy migration from original audio and
  saved stems. This uses the chosen recipe; it does not infer calibration from
  normalized MP3. Content-addressed files are retained for undo and recovery.
- `project_preview.py`: current project -> effective timings -> existing ASS
  compiler, shared by preview/export. Unresolved timing blocks final export;
  the labelled draft preview can omit untimed words. Bundled Noto Sans is used
  by browser libass and native FFmpeg. Do not duplicate ASS event compilation
  in a new presentation editor.
- `project_align.py`: explicit CUDA alignment of the saved lead track. It is
  imported only by that action, writes a new result artifact and preserves
  manual corrections when applying proposals. Transport edits load no models.
- `gui.py`: revision-specific video output folders retain the exact project,
  timing and style snapshot. P06 can replace the synchronous job UX while
  keeping the current export inputs. `render.py` explicitly bounds video by
  audio duration; `-shortest` alone produced an observed encoder tail.

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

## Next: P05

The owner wants screen placement, font choices, highlight colours and font
outlining. Existing basic style controls and the real ASS preview give P05 a
working starting point, not a finished presentation editor. Add visual handles,
font selection/availability, outline controls and presentation persistence
through the shared history/compiler. Browser image/video background preview is
still future work; it currently previews lyrics on a solid canvas.

Keep P04's first version labelled **Vocal level**: 0% is the saved processed mix,
100% restores its original reference. Avoid claims of perfect lead separation or
unchanged harmonies. Measured sample accuracy and numerical smoothness do not
substitute for a subjective listening verdict; evidence and an audition sample
are listed in BUILD-STATUS.

The standing user preference is to distinguish uncertainty from verified facts.
Update BUILD-STATUS with commands, observations and limits after the next phase;
do not replace that evidence with a confident summary.
