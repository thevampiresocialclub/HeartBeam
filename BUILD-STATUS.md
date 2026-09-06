# BUILD-STATUS

Tracks the build program in `heartbeam-claude-handoff/`. Update after every project.

## Summary

| Project | Status |
|---|---|
| P01.1 Baseline repair | **Verified** |
| P01.2 Project store | Not started |
| P01.3 Lossless artifacts | Not started |
| P01.4 Visible project workflow | Not started |
| P02-P07 | Not started |

**P01 as a whole is NOT complete.** Only its first phase is done. The saved-project
format, the lossless audio cache and the Open/Save workflow are still absent, so
the GUI still cannot reopen yesterday's song.

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

## Next: P01.2 - define and implement the project store

Prerequisites met. Read `08-SHARED-CONTRACT.md` section 1 before starting.

Outstanding for P01 completion:

- P01.2 versioned project schema, atomic save, Save As, reopen, missing-asset
  relinking, autosave recovery, legacy `timings.json` importer.
- P01.3 persist original PCM, stems and an unnormalized clean reference with
  hashes and provenance; invalidate dependent caches on mismatch.
- P01.4 New/Open/Save/Save As in the GUI; enter with an existing
  instrumental/timing pair without rerunning separation.

Note for P01.3: `separate.py` currently discards stems into a `TemporaryDirectory`
unless `--keep-stems` is passed, and the mix path normalizes and encodes to MP3
before anything is persisted. Retaining an unnormalized lossless reference will
require changing where that pipeline writes, which is the substance of P01.3.
