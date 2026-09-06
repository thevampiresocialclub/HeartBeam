# BUILD-STATUS

Tracks the build program in `heartbeam-claude-handoff/`. Update after every project.

## Summary

| Project | Status |
|---|---|
| P01.1 Baseline repair | **Verified** |
| P01.2 Project store | **Verified** |
| P01.3 Lossless artifacts | Not started |
| P01.4 Visible project workflow | **Verified** |
| P02-P07 | Not started |

**P01 is NOT complete: P01.3 remains.** The project format and the visible
Open/Save workflow are done, so the GUI can now reopen yesterday's song and
restyle it without rerunning separation. The lossless audio cache is still
missing, which is what P04's section vocal mixer will need.

**Phases were completed in the order P01.1, P01.2, P01.4, P01.3.** P01.4 was
brought forward because its acceptance criterion -- reopen a song without
repeating separation -- depends only on the P01.2 store plus the already-persisted
karaoke MP3, not on the lossless cache. Doing it earlier put a working
save/reopen loop in front of the user sooner. P01.3 is unaffected by the swap.

---

## P01.1 - Establish and repair the baseline: VERIFIED

### Environment baseline

Contrary to the review session's experience, this environment is healthy:

- `.venv` launcher works. Python 3.12.10, torch 2.8.0+cu128, CUDA available.
- GPU: RTX 5070, sm_120, 11.9 GB. Preflight passes.
- ffmpeg 8.1.1-full_build on PATH, `--enable-libass` confirmed, `ass` and
  `subtitles` filters present.
- Test command: `.venv\Scripts\python.exe -m pytest tests/ -m "not slow" -q`

The review's note that the venv launcher could not find its Microsoft Store base
Python did not reproduce here. Its ffmpeg-unavailable note also did not apply.

Pre-existing uncommitted work was preserved: the `models.py` additions
(`rock-becruily`, `rock-gabox2`) and `scripts/sweep.py` are intact and committed.

### Defects fixed

Each was reproduced before fixing and is now covered by a regression test.

1. **Windows background paths corrupted TOML.** `_write_style_toml` interpolated
   raw paths into quoted TOML. `C:\Users\...` raised `Invalid hex value` (`\U`
   begins a unicode escape); `C:\temp\...` parsed but silently became
   `C:<TAB>emp`. Added `toml_escape()`/`toml_string()` to `style.py` and routed
   every GUI-written string through them.

2. **Background video audio could replace the karaoke soundtrack.** `render.py`
   passed two inputs with no `-map`. Added explicit `-map 0:v:0 -map 1:a:0`.
   Worse than the review recorded: with `-stream_loop -1` the pre-fix command did
   not merely take the wrong audio, it **never terminated** -- `-shortest` bound
   itself to the infinitely looped background audio. Observed producing 128 MB
   over 5 minutes before being killed.

3. **ASS timestamps did not carry.** `_fmt_ass_time` formatted the seconds field
   with `%05.2f`, rounding during formatting: 59.999 became the invalid
   `0:00:60.00`, and 3599.999 became `0:59:60.00`. Now rounds to whole
   centiseconds before splitting fields.

4. **ASS written before its directory existed.** `cli_video` wrote the subtitle
   file next to the output, then created the output directory afterwards, so
   `-o new_dir/karaoke.mp4` failed. Both parents are now created first.

5. **Invalid timings were accepted silently.** Reversed, negative, NaN and
   infinite times flowed into the mask builder and ASS writer. `Timings.from_dict`
   now validates and raises `TimingsValidationError` naming the line, word index,
   word text and field.

6. **A failed worker stranded the GUI.** If `subprocess.Popen` raised, the worker
   thread died without setting `done`, leaving the progress bar running forever
   with no console to show why. Launch failures are now reported through the
   normal status channel in a `finally` block.

### Validation

```
.venv\Scripts\python.exe -m pytest tests/ -m "not slow" -q     -> 46 passed
.venv\Scripts\python.exe -m pytest tests/ -m media -v          -> 2 passed
```

23 pre-existing tests still pass. 23 added in `tests/test_p01_foundation.py`,
including two real-media regressions gated on ffmpeg availability behind a new
`media` marker.

The soundtrack regression is a genuine media test, not a schema check: it builds
a 12 s background carrying a 1000 Hz tone plus 4 s of 220 Hz karaoke audio,
renders, then FFTs the decoded output. It asserts the dominant frequency is
220 Hz and the duration follows the 4 s song. Measured: 220 Hz, 4.000 s.

### Not verified

- No full-song render or listening comparison was made against this work.
- The GUI fixes were exercised through `AppTest` and unit tests, not by a human
  clicking through a browser session.
- Duration bounding is proven for a looping video background; an image
  background with an unusually long audio file was not separately tested.

### Changed files

`heartbeam/style.py` (TOML escaping), `heartbeam/gui.py` (escaping + worker
failure handling), `heartbeam/render.py` (stream mapping), `heartbeam/ass_writer.py`
(timestamps), `heartbeam/cli_video.py` (directory creation), `heartbeam/timings.py`
(validation), `tests/test_p01_foundation.py` (new), `pyproject.toml` (media marker).

No schema change, no migration, no new dependency.

---

## P01.2 - Saved-project store: VERIFIED

`heartbeam/project.py`, stdlib-only (28 ms import, no streamlit/torch), so the
CLI, GUI and tests share one store and opening a project never pays an ML import.

Three decisions carry the design:

- **Stable generated IDs** for sections, lines and words. Text, ordinal position
  and text hashes are not identities -- repeated choruses and duplicate words are
  normal -- so timing and vocal regions reference IDs that survive insertion,
  deletion and re-wrapping.
- **One place resolves timing.** `effective_timing()` is the only code that
  decides whether a user edit or the aligner's immutable proposal wins, so no
  third copy of "current" timing can drift.
- **Integer milliseconds** throughout, converted once at the importer boundary
  (round half away from zero).

Implemented: create, atomic save, load, Save As, autosave snapshots with
recovery, asset add/relink, missing-asset detection, legacy import. Saves write a
sibling temp file then `os.replace`, so an interrupted save leaves the previous
manifest intact.

Unresolved words keep absent times plus a review reason rather than invented
values; non-sung tokens are excluded from review.

Validation: 28 tests in `tests/test_project_store.py` covering every P01.2
acceptance criterion, including an interrupted save leaving the last good
manifest with no temp files behind, autosave recovery skipping a truncated newest
snapshot, a moved project with relative assets still opening, relink preserving
the asset ID, and legacy import leaving the user's files byte-identical.

---

## P01.4 - Visible project workflow: VERIFIED

Sidebar with project name, revision, saved/unsaved state, missing-asset warnings
with per-asset relink fields, Save, Close, Save As, Open, and an "Import existing
timings + audio" panel for entering a song without rerunning separation.

A completed generation run is now adopted into a saved project automatically.
Until this existed, closing the browser lost the only reference to a 45-minute
separation.

The results and video sections now resolve their media from either this session's
run or an opened project. `_render_video` takes explicit audio and timings paths
because the two sources no longer share a directory: a run keeps both in its
output folder, a project stores audio under `audio/` and the imported timings
under `assets/`. Project renders land in `exports/`.

Two UI fixes found while testing: sidebar buttons no longer appear mid-keystroke
(they render always and validate on click), and opening or importing now triggers
a rerun so the sidebar reflects the loaded project immediately instead of lagging
one interaction behind.

Validation: 8 tests in `tests/test_gui_project_workflow.py` driving the real
Streamlit script through `AppTest`. The acceptance test opens a project in a
session with no run history and asserts the video controls are reachable, the
timing came from the saved project, and `out_dir` is still None. A media-marked
test renders an MP4 from that opened project and probes its duration.

### Not verified

- No human has clicked through the sidebar in a browser; coverage is AppTest.
- Save As, relink and Close were exercised through tests, not manual use.
- Concurrent editing of one project by two sessions is not handled at all
  (contract section 4 requires detection; deferred with P02).

---

## Next: P01.3 - retain lossless processing artifacts


Prerequisites met. Read `08-SHARED-CONTRACT.md` sections 6 and 8 before starting.

The only phase left in P01: persist original PCM, separated stems and an
unnormalized/unclipped processed reference on a common sample basis, with audio
hashes, sample rate, channels, sample count, model identities and settings
recorded. A mismatch must invalidate dependent caches rather than silently
reusing them, and interrupted jobs must not masquerade as valid caches.

Note for P01.3: `separate.py` currently discards stems into a `TemporaryDirectory`
unless `--keep-stems` is passed, and the mix path normalizes and encodes to MP3
before anything is persisted. Retaining an unnormalized lossless reference will
require changing where that pipeline writes, which is the substance of P01.3.
