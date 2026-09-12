# BUILD-STATUS

Tracks the build program in `heartbeam-claude-handoff/`. Update after every project.

## Summary

| Project | Status |
|---|---|
| P01.1 Baseline repair | **Verified** |
| P01.2 Project store | **Verified** |
| P01.3 Lossless artifacts | **Verified** |
| P01.4 Visible project workflow | **Verified** |
| **P01 overall** | **Complete** |
| **P02 Lyrics editor** | **Verified** |
| **P03.1 Architecture proof** | **Verified** |
| **P03.2 Transport and waveform** | **Implemented; Python and browser checks below** |
| P03.3-P03.4 Timing and review | **Complete; verification below** |
| **P03 overall** | **Complete** |
| **P04 Section vocals** | **Complete; verification and limits below** |
| **P05 Visual lyric placement and styling** | **Complete; verification and limits below** |
| **P06 Preview and export** | **Complete; verification and limits below** |
| P07/R0 Reliable audio baseline | **Implemented; verification below** |
| P07/R1 Find possible thinning | **Archived by owner decision, 12 September** |
| P07/R2 Recorded-instrument recovery | **Archived by owner decision, 12 September** |

**P01 through P06 are implemented.** See the latest sections below for current verification; earlier sections are historical snapshots.

**7 September timing follow-up:** Online lyrics lookup, phrase-first matching,
and timing approval before the removal mix are implemented.
**Latest full Python run: 372 passed. Current JavaScript tests: 28 passed.** See
`docs/TIMING_SYSTEM.md` and the verification section below. Automatic timing
accuracy across songs remains unverified; uncertain words are retained for review.

**8 September editor follow-up:** current lyrics appear above upcoming lines,
which rise into place at phrase completion. Letter spacing and line height are
editable. Partial lines retain timed-word highlights. **Build karaoke and continue**
warns about missing word timing/conflicts without requiring individual approval;
known phrase windows cover missing words during removal. See the final section
for browser evidence and remaining limits.

**8 September follow-up:** missing words receive labelled estimates from
neighbors/phrase windows by default. New builds expose independent lead and
backing gains above the preview, including 1–5% guide vocals. Current MP3/WAV and
video exports share that mix; old projects can explicitly enable separate tracks.
See the final section for current evidence; earlier descriptions are historical.

**Latest 10 September follow-up:** video exports warn and continue for missing,
estimated, conflicting or out-of-range word timing and stale timing approval.
They follow the preview, keep plain text within usable lyric windows, and report
unanchored lines that cannot appear. Audio/font/background validation remains.

**P01 and P02 foundation:** A song can be generated, saved, closed, reopened
and restyled without rerunning separation; lyrics can be pasted rather than
uploaded and edited without losing timing work; and the lossless audio the
section mixer will need is retained with provenance.

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

## P01.3 - Lossless processing artifacts: VERIFIED

`heartbeam/audio_cache.py` persists five roles on a common sample basis:
`original`, `lead`, `backing`, `instrumental`, and `clean` -- the processed
karaoke mix **before** loudness normalisation and **before** clipping.

`clean` is the one the old pipeline threw away and the one P04 depends on. The
section mixer blends `clean + restore * (original - clean)`, which only reaches
the original at restore=1 if `clean` sits at the same gain reference as
`original`. Reconstructing it from the normalised MP3 would make the scale
inconsistent and add encoding loss.

To capture it, `mix()` and `mix_replace()` gained `clip=False`. The pipeline now
mixes once unclipped, caches that, and clips a copy for the MP3 deliverable.
Default behaviour is unchanged: `clip=True` is exactly the previous code path.

Validity is two-part: the source audio hash and a fingerprint of the settings
that determine the audio. Style, placement and export settings are deliberately
excluded from that fingerprint, so restyling never invalidates the stems. The
manifest is written last and a stale manifest is removed first, so an interrupted
or failed write reads as *absent* rather than as valid-but-wrong.

### Validation

16 unit tests in `tests/test_audio_cache.py`, plus a real pipeline run on the
3:27 fixture:

```
heartbeam tests/fixtures/Helena.mp3 tests/fixtures/lyrics.txt -o <tmp> --separator pop
-> 2m14s, cache written (344 MB, wav)
-> mask coverage lyric=77.9% energy=89.5% combined=91.1%   (identical to the
   pre-change run, confirming the clip refactor changed no output)
-> loudness normalize -11.1 -> -14.0 LUFS  (identical)
```

Cache checks against that real run:

| Check | Result |
|---|---|
| same source + same settings | `(True, 'valid')` |
| changed `vocal_gain` | rejected: processing settings changed |
| changed separator preset | rejected: processing settings changed |
| changed source audio | rejected: source audio changed |
| `clean` peak | 1.103 -- confirmed unclipped |
| `clean + 1.0*(original-clean) == original` | exact |

That last row is the P04 identity: at restore=1 the blend returns the original
sample-for-sample.

### Known limitations

- **Size.** 344 MB per song at wav/float32, roughly 100 MB per minute. `--cache-format
  flac` is about 40% of that but is 24-bit rather than bit-exact float.
  `--no-audio-cache` disables it. No pruning policy exists yet.
- A cache write failure is logged and swallowed rather than failing the run: a
  completed separation must not be lost to a full disk. The consequence is that
  later remixing would need a rerun, which the warning says.
- The GUI does not yet read from the cache. Nothing consumes it until P04; P01.3
  only requires that it exists, is valid and is readable.
- `read_role` loads a whole stem into memory. Streaming/windowed reads are a P03
  or P04 concern.

### Changed files

`heartbeam/audio_cache.py` (new), `heartbeam/cli.py` (cache wiring, two flags),
`heartbeam/mix.py` (optional clipping), `tests/test_audio_cache.py` (new).

---

## P02 - Lyrics text editor and alignment preservation: VERIFIED

### P02.1 direct text entry

The mandatory `.txt` upload is gone. `gui.py` now offers a lyrics text area with
live line/word counts and an empty-state message; the file uploader remains as an
optional way to seed the box. The CLI still wants a path, so the GUI writes a
temp `lyrics.txt` itself -- that is an implementation detail, not the user's
problem.

Section labels are explicit: a line starting with `#` is a label and is never
sung. Bracketed text is deliberately NOT auto-detected as a heading, because
`[...]` appears in real lyrics and guessing would silently eat them.

### P02.2 edits preserve identity

`heartbeam/lyrics.py` reconciles edited text against the existing document:

1. Diff the sung lines. Equal runs keep their line and word IDs untouched.
2. Around changed regions, flatten old and new words and diff *those*. Word IDs
   therefore survive across line boundaries, which is what makes splitting and
   merging non-destructive -- naive line pairing would orphan every word after a
   split.
3. Surviving words keep their timing. New words get fresh IDs and an explicit
   unresolved entry with a reason, never an invented time.

Matching is sequence-based, never text-keyed, so the second occurrence of a
chorus matches the second occurrence. Words compare on a normalised form, so
punctuation and capitalisation fixes keep their timing.

One deliberate trade is recorded in `normalize_word`: apostrophes are stripped,
so "dont" and "don't" compare equal. The cost is that "were" and "we're" also
compare equal and keep the old timing rather than being flagged. That is the
better failure -- they occupy the same slot in the line, and silently keeping
correct-enough timing beats silently discarding the user's timing work over an
apostrophe.

Undo/redo is snapshot-based and in-memory, per contract section 4 (durable undo
history is optional; saved content and recovery are not).

### P02.3 all words survive alignment

Fixed the positional regrouping bug the review reproduced. `align.py` used to
truncate the line-index list to a prefix when the aligner dropped words, so one
missing word shifted every later word onto its neighbour's line -- `charlie`
landed on line 0. It now sequence-matches the aligner's output against the exact
source tokens, so each word keeps its own line and dropped words simply go
missing instead of corrupting their successors.

`apply_alignment()` maps results onto project word IDs and **protects manual
corrections by default**: it fills only words with no timing. `only_unresolved=False`
is the explicit "realign everything" choice, and even then a manual edit still
wins over the new proposal.

### P02.4 persistence

Text, sections, IDs, review flags and timing overrides all round-trip through
save/reopen (covered by `test_edits_survive_save_and_reopen`). Export writes
plain text with no internal IDs.

### Validation

```
pytest -m "not slow"  -> 139 passed
pytest -m media       -> 3 passed
```

New: `tests/test_lyrics_editor.py` (27), `tests/test_alignment_mapping.py` (10),
plus 4 GUI tests. Every acceptance criterion in `02-LYRICS-EDITOR.md` has a test,
including the review's exact case: with `bravo` dropped from `alpha bravo /
charlie delta`, `charlie` stays on its own line and `bravo` remains visible as
unresolved.

### Not verified

- No human has typed in the box in a real browser; coverage is AppTest.
- `apply_alignment` is tested against synthesised aligner output. Nothing calls
  it from the UI yet -- re-alignment of an existing project arrives with P03.
- Section membership is rebuilt on each edit rather than diffed, so section IDs
  are not stable across edits. Line and word IDs are, which is what timing and
  vocal regions depend on. Worth revisiting when P04 attaches regions to sections.

---

## P03.1 - Prove the interactive architecture: VERIFIED

The gate this project opens with. Result: **the approach works, with two real
defects found and fixed, and three limitations recorded.**

### The architecture, and why it clears the packaging constraint

Streamlit 1.57 ships `st.components.v2.component(name, html=, css=, js=)`, which
accepts **raw HTML/CSS/JS strings**. The frontend is therefore plain ES-module
JavaScript in `heartbeam/editor_assets/`, shipped as package data. There is no
React, no bundler and **no Node.js anywhere** -- which is what makes the
contract's requirement ("ordinary users must not need Node.js") satisfiable
rather than aspirational. Pinned: `streamlit==1.57.0`, API `components.v2`.

Data flows in through `data=`; committed gestures come back through
`setTriggerValue`. Playback, dragging, hover, zoom and the playhead never cross
the bridge. One drag equals one trigger equals one undo step.

### Verified by driving a real browser

AppTest cannot execute JavaScript, so this was checked against a running server
with a real 245-word project (Helena, 3:24):

| Check | Result |
|---|---|
| Waveform renders from Python-computed peaks | Yes, 702x150 canvas |
| Component instances after several reruns | **1** (see defect 1) |
| Click a word body | Selects, seeks to 2.12 s, does NOT play, does NOT dirty |
| Selection reaches Python | `Long - 2122 to 4384 ms` |
| 10 ms nudge | 2122/4384 -> **2132/4394**, exactly +10 ms |
| Assign timing to an untimed word | `hearse - 7000 to 7600 ms`; untimed 2 -> 1 |
| Save, then reopen from disk | revision 3, edit persisted, proposal untouched |
| Audio playback | `paused: false`, advanced 2.02 s in 2.0 s wall time |
| On-screen clock vs audio element | **33 ms** drift (one tick, see defect 2) |

### Defects the proof found

1. **A click near a word edge committed a no-op edit.** It started a
   zero-distance drag; mouseup committed unchanged values, marking the project
   dirty and consuming an undo step. This directly violated "selection changes
   should not unintentionally commit an edit". `commitDrag` now compares against
   the drag origin and treats an unmoved gesture as a selection.

2. **The display depended on `requestAnimationFrame` alone.** In the automated
   browser rAF never fired, and audio kept playing while the playhead and clock
   sat frozen at 0:00 -- silent desynchronisation from what you hear. Although
   the non-compositing pane is a test artifact, the same freeze happens in a
   background tab or an occluded window. The component now drives its display
   from rAF **and** a 60 ms interval, whichever fires, with a 25 ms guard so the
   two do not double-draw. Measured drift afterwards: 33 ms, with rAF still not
   firing at all.

3. **Every rerun stacked another timeline.** Streamlit re-invokes the module
   against the same parent element, and the code appended a fresh root (and a
   fresh `<audio>`) each time. It now removes its previous root and aborts the
   old mount's window listeners via `AbortController`. Confirmed: one editor on
   the page after many reruns.

Also fixed while diagnosing: `@st.cache_resource` on the component registration
broke mounting with "Component is not registered" -- registration populates a
per-run registry, so it must happen every run. And the `<audio>` element is now
attached to the DOM (hidden) instead of detached, because an inspectable element
is the difference between "playback is broken" and knowing why.

### Limitations recorded

Historical P03.1 limitations follow. P03.2 supersedes the inline-audio,
source-switching and fixed-peak limitations; ASS preview remains outstanding.

- **Audio is inlined as a base64 data URL** (6.5 MB for a 5 MB MP3). Streamlit
  offers no static route an `<audio>` element can point at, so this is the
  proof's main cost. Capped at 40 MB with a clear error. A served URL or chunked
  delivery is the obvious P03.2 improvement.
- **Source switching (original / lead / karaoke) is not implemented**, so its
  30 ms acceptance target is untested. It belongs to P03.2 and the P01.3 cache
  already holds the stems it needs.
- **No ASS lyric preview yet.** The P03.1 brief lists it; SubtitlesOctopus
  remains a candidate, not a dependency, and has not been evaluated.
- Peaks are computed at a fixed 2000 buckets; zoom stretches them rather than
  recomputing at higher resolution.

### Validation

```
pytest -m "not slow"  -> 168 passed
pytest -m media       -> 3 passed
```

`tests/test_timing_editor.py` (29) covers peak extraction and caching, exact
nudges in both directions, refusal of invalid timings without clamping, manual
timing for untimed words, review navigation that distinguishes model confidence
from user review, and the payload. Two of them are regression guards asserting
the frontend keeps its interval fallback and its no-op-drag check.

---

## P03.2 - One transport and waveform

Continued from `02e78cd` on 6 September 2026. The existing 168-test suite passed
before changes. The complete suite now passes **182 tests**, including 14 new
checks for media delivery, source/cache adoption and selection ordering.

### Delivered

- Original / lead vocal / karaoke audition uses one audio element and preserves
  song position, playback state and speed across source switches. Missing or
  incompatible tracks remain disabled with a reason.
- Audio and waveform JSON use Streamlit's existing same-origin `/media` route.
  Its real handler is tested for byte-range responses, HEAD and JSON delivery.
  Registration runs on every script run so Streamlit retains session references.
  The private adapter is isolated in `editor_media.py`; `streamlit==1.57.0` is
  now explicitly pinned in the GUI extra as well as tested on this machine.
- Existing projects can use **Missing audition tracks > Link cached tracks**.
  New generation results adopt the matching run's cache automatically. All five
  cached roles are copied into project audio assets, retaining metadata and
  provenance; Save As carries these assets. Linking validates file presence,
  common sample basis and duration, and refuses filename collisions/duplicate
  roles before copying. It does not run separation or alignment.
- Cached 2k / 8k / 32k / 64k min/max levels are fetched according to zoom. Cache
  misses decode each source once. File size/mtime changes invalidate the cache.
  Peak extraction now includes the tail that the previous reshape discarded.
- The canvas is viewport-sized at every zoom; a wider scroll track supplies the
  timeline coordinates. A 20x zoom no longer allocates a 20x-wide canvas.
- A lyric list selects/seeks by stable word ID, shows untimed words and current
  singing position, and preserves keyboard focus across reruns. Source, speed,
  zoom, selection and playback survive normal component data updates.
- Persistent, nonce-tagged component selection replaces the one-shot selection
  trigger. A fast lyric selection followed by a Python nudge could otherwise
  consume the nudge against the previous word. Selection is consumed before
  edits/controls; old messages cannot override Next untimed/uncertain navigation.
  Drag edits still emit one committed event and one undo step.
- The separate `st.audio` player is removed for open projects. Playhead, lyric
  highlight, position slider and loop read the same audio clock. Space is scoped
  to the editor and does not intercept typing or native button/selector keys.

### Evidence and limits

Real browser: local server on 127.0.0.1:8502, existing Helena MP3 plus original
fixture and float32 lead WAV. The source MP3 is 8 ms longer than the karaoke;
both are within the 30 ms admission tolerance. Began with 245 words, then used
the lyric text box to append 15 untimed verification words: **260 total**. The
fixture is isolated under the Codex workspace, not the user's original project.

| Check | Observed result |
|---|---|
| Audio delivery | `/media/...` URLs, including a 72 MB float32 lead WAV; no base64 cap |
| Serialized 245-word bridge payload | 39,227 bytes using representative media URLs, vs the prior ~6.5 MB audio data URL alone |
| Source switches, paused and playing at 0.75x | Measured seek error **0.000 ms** at the captured song position |
| Source loading time | Samples **16.7-79.8 ms** initially; **49.8 ms lead / 19.9 ms original** in the later 260-word check |
| Display clock vs audio clock | Samples ~0.5-24 ms apart, both reading the audio clock |
| Zoom 1x -> 20x | 2,000 -> 32,000 peaks at a 547 px viewport; canvas stays 547 px, scroll track 10,940 px |
| Lyric selection and reruns | Selection reaches Python; source, speed, zoom and play position retained; one editor/audio instance |
| Loop + untimed navigation | Word loop runs at 0.75x; selecting an untimed word cancels the loop without inventing timing |
| Keyboard focus | Lyric button focus retained after a selection rerun |
| Fast selection followed immediately by nudge | Correctly changed Long from 2122/4384 to **2132/4394 ms**, including the reproduced previous-word race |
| Direct canvas drag and undo | Long end **4394 -> 4207 ms**; one Undo restored **4394 ms**, retaining lead source, 0.75x speed, 20x zoom and position |
| Project save | Browser Save persisted revision 3 with 260 words, confirmed from disk; reopened as revision 3 |

The 30 ms result is **seek accuracy**, not gapless switching: playback pauses
while the new source loads, then resumes at the captured song position. Loading
latency is separately reported above. Audio-device/output latency and a listening
quality review were not measured. The transport does not modify saved timings.

Streamlit still holds registered files in RAM and reads/hashes media during
registration. This removes base64/websocket duplication; it is not disk streaming
or a bounded-memory media server. No full-song committed-drag <100 ms benchmark
is claimed here; that P03 acceptance check remains to measure with P03.3.
Background timers can be throttled by a browser; rAF plus a 60 ms fallback avoids
the known rAF-only freeze but is not a hard real-time loop guarantee.

Legacy projects do not prove which cache belongs to which song. Explicit cache
selection plus duration/basis checks catch common mistakes, not same-length wrong
songs. Source provenance is recorded when linking. Cached FLAC is still the P01
24-bit representation; it does not gain float32 bit-exactness by being linked.

Validation command (installed repo environment):

```powershell
.venv\Scripts\python.exe -m pytest tests -m "not slow" -q -p no:cacheprovider
# 182 passed; includes the real ffmpeg media tests
```

The desktop shell sandbox could not launch Store Python directly; the same
installed venv succeeded through the approved native execution path. No package
installation or model/GPU sweep was needed. AppTest still cannot validate JS;
browser observations above are a separate check. Fresh-page reload is required
after editing the JS because a mounted component retains its existing closure.

### Still open

ASS preview remains the uncompleted part of the original P03.1 brief. P03.3 owns
word/phrase/global edit scopes, robust command handling, undo/redo and the measured
interaction performance gate. P03.4 owns review/alignment UI. Section identity and
concurrent-write handling remain gaps listed in HANDOFF.md; do not start P04
section attachments on unstable section IDs.

---

## Parked: model A/B sweep (belongs to P07)

Tooling is ready and deliberately unused. `scripts/sweep.py` renders one song
through six configurations and prints a mask-coverage table; `models.py` carries
`rock-becruily` and `rock-gabox2`, which differ from `rock` only in the Pass-2
karaoke splitter, so a comparison changes one variable. All five separator models
plus faster-whisper large-v3 are downloaded (9.3 GB under ~/.heartbeam/models).

Deferred on purpose:

- The build program schedules model evaluation as P07 and states it must not
  delay a usable editor.
- P04's section vocal mixer changes what "good separation" has to mean. Once a
  verse can be dialled to 20% lead by hand, a mediocre separation is a two-slider
  fix rather than a model-choice problem. Tuning defaults now would optimise
  against a problem the editor is about to reshape.
- One six-way listen on one song is not evidence enough to move a default. The
  review is explicit that neither "rock is always best" nor "more subtraction
  gain removes more vocal" holds as a rule, and that mask coverage and checkpoint
  filenames are not sound-quality scores.

Interim guidance for a bad-sounding song: switch the genre dropdown from pop to
rock and regenerate. Rock's models are on disk.

When P07 arrives: compare short passages at matched loudness, listen separately
for lead residue, lost backing vocals and instrument damage, and reuse a common
first separation pass when comparing second-pass models.

---

## Next: P03.3 - timing edit scopes



Read `03-PLAYBACK-TIMING.md` and `08-SHARED-CONTRACT.md` section 5 before starting.

P03 is the largest project in the programme and owns the shared transport: one
playback clock that the waveform, lyric preview and (later) vocal mixer all
subscribe to. It also carries the bounded integration proof for the browser
component approach -- if that cannot meet the acceptance checks, the contract
requires documenting the evidence and choosing the smallest viable alternative
rather than pressing on.

What P02 hands it: stable word IDs, `unresolved_words()` with reasons,
`apply_alignment(only_unresolved=True)` for filling gaps without touching manual
work, and the P01.3 cache so auditioning original/lead/karaoke needs no rerun.

The old note saying P01.3 still needed to persist pre-mastering audio was stale.
P01.3 already writes that cache; P03.2 now links its roles into saved projects.


---

## P03 and P04 continuation — 6 September 2026

P03.1's missing ASS proof, P03.3, P03.4, and P04 are now implemented. This
section supersedes older "not started", "no ASS preview", "unstable section
IDs", and "no alignment UI" notes elsewhere in this historical log.

### What works

- One AudioContext clock drives source playback, sample-accurate selection
  loops, waveform position, current-word feedback and a local libass WASM ASS
  preview. Browser and native rendering use the same ASS compiler and bundled
  Noto Sans fonts. ASS converts absolute boundaries to centiseconds so per-word
  rounding does not accumulate across a phrase.
- Move a whole word or either edge; assign or edit exact numeric times; nudge
  word, lyric line or whole song independently. Arrow keys nudge 10 ms, Shift
  changes that to 100 ms. Text/native inputs retain their normal key handling.
  Loop context is configurable. Imported overlaps are reported, not flattened;
  edits may repair them but cannot introduce or worsen a conflict.
- Explicit reviewed flags, next-untimed/uncertain navigation, saved-result
  alignment import, and an explicit GPU alignment action on the saved lead
  stem. Manual corrections win; original proposals remain immutable and later
  alignment proposals have their own layer. Ordinary editing loads no models.
- Shared atomic command history covers lyrics, timing, review, vocal levels,
  reference preparation/rebuild and basic preview style. Unique command IDs and
  base revisions reject duplicate/stale browser messages. Undo/redo advance the
  content revision; saving alone does not create another editor content edit.
- Section IDs follow surviving word membership, including renamed headings and
  line rewrapping; repeated headings retain distinct IDs.
- Song default plus one non-overlapping vocal lane. Target a lyric line, several
  lines, a named section, explicit time range, existing region, or song default.
  Region insertion splits/replaces overlaps in one undo step. The live slider,
  numeric entry, region reset, source-lyric refit and selection loop are wired.
- Restoration is `clean + value * (original - clean)` before mastering. One
  continuous linear envelope compiler feeds both offline rendering and browser
  audition templates. Short spans cap adjacent ramps; touching spans share a
  transition. Slider movement stays in the browser and commits once per gesture.
  Compiled envelopes run as audio buffers, so looping does not depend on rAF or
  a foreground JavaScript timer. Graph changes have a short audition crossfade.
- Calibrated lossless references are checked by hash, sample rate, channels and
  sample count. Legacy normalized MP3s cannot masquerade as clean references.
  Explicit preparation from matching original/stems stores its chosen recipe;
  new pipeline caches retain the full recipe. Rebuilding the clean audio from
  corrected timing is explicit and undoable, retaining prior referenced files.
  Vocal regions keep their stored times until explicitly refitted.
- Final mix rendering is cached by content, blends first, and then applies one
  loudness / 4x oversampled peak stage. It is available on the same transport
  and as a WAV download. Stale final auditions are hidden after content changes;
  stale asynchronous browser preparation cannot replace the current revision.
- Video export now uses **effective project timing and the edited vocal mix**.
  It writes revision-specific output folders with timing, style and project
  snapshots. The old GUI incorrectly rendered the immutable imported timing
  file. Export rejects unresolved/conflicting timing. Explicit audio duration
  also fixes an observed 1.9-second encoder tail without cutting the soundtrack
  to a rounded video frame.
- OS writer leases make a second GUI read-only, with an independent copy route.
  Atomic saves also check the last-read manifest hash under a short save lock,
  preventing a stale writer from silently replacing a newer manifest.

### Verification

Commands: `.venv\Scripts\python.exe -m pytest -q -m "not slow"` and
`node --test tests/audio_transport.test.mjs`. Node is a development test tool;
the installed application has no Node build/runtime requirement.

The final suite passed: 216 Python tests and 5 focused JavaScript playback tests.
It covers the old regressions, timing scopes, conflict repair, persistent review,
stable sections, atomic/duplicate/stale commands, undo/redo, writer leases and
stale saves, 0/20/100% mixes, overlap splitting, short/boundary/stereo envelopes,
preview/offline coefficient agreement, explicit refit/rebuild, missing or
replaced references, final mastering, effective-timing export, real video
duration, and GUI save/reopen of vocal commands. The JS tests include the actual
transport class with a controlled audio clock, stale preparation races, shared
loop starts, and selection preserving the existing audible mix.

Real browser evidence (260-word Helena fixture, current in-app browser):

- libass worker ready, fonts rendered; the visible `Long ago` preview matched
  the native FFmpeg frame in wording, highlight, layout and font. This was a
  visual comparison, not a pixel-identity claim across rasterizers.
- Single slider drag produced one revision and a 20% vocal region. Whole-word
  dragging moved both boundaries by -73 ms while retaining duration; one Undo
  restored 2132–4394 ms. The saved vocal region retained its original times.
- Observed visible commit paints: 0.7–4.1 ms. Streamlit command acknowledgements:
  668–690 ms. These are different measurements: the UI responds optimistically
  within the 100 ms target; server confirmation is not sub-100 ms.
- Cached source switches: 0.1–0.2 ms loading interval and 0.000 ms position
  error. Initial audio decode was 346–405 ms. These are local observations,
  not cross-device latency guarantees. Source, selection and zoom survived
  ordinary command reruns; entering text did not issue timing commands.
- A second session opened read-only; Save was disabled. Save a copy produced
  an independent editable project through the real UI.
- The mix remained playing in its selection loop while a separate blank tab
  was foreground for several minutes. On inspection, waveform/ASS clocks both
  read 2986 ms inside the selected loop, with playback active and zoom 20 retained.

Real media / model evidence:

- Stereo 44.1 kHz, 204.745578-second reference pair. 0% and 100% endpoint maximum
  absolute sample error: **0.0** for each. Compiled coefficients remained in
  [0,1]; maximum adjacent coefficient change for the 40 ms proof transitions:
  0.0005668998. 20/0/100% regions were rendered in a full-song proof video.
- Full video: H.264 960×540 + AAC stereo 44.1 kHz; audio duration 204.745011 s,
  video duration 204.733333 s (within one 30 fps frame). Latest render/preview
  extraction took about 4.5 seconds locally.
- Explicit saved-lead alignment ran on CUDA in **53.08 seconds**: 260 aligned
  words, 244 proposals applied, all **16 manual timings preserved**, 0 unmatched
  words. This checks integration and mapping, not perceptual alignment accuracy.
  The existing TorchCodec warning did not prevent the in-memory audio path.
- An offline wheel was built and inspected: all renderer JS/WASM, font and
  license files were included with matching hashes. The upstream npm tarball
  integrity was checked. Sources and hashes are in `editor_assets/vendor/README.md`.

Local evidence files are under
`C:\Users\young\Documents\Codex\2026-09-06\run\work\p034-verification`:
`evidence.json`, `alignment-evidence.json`, `native-preview.png`,
`karaoke-proof.mp4`, and `vocal-levels-0-20-100.wav`. The latter compares the
same four-second phrase at 0%, 20% and 100%. Audio files are not committed.
The fixture was prepared from existing stems with an explicitly chosen recipe;
it is not claimed to reproduce the historical normalized karaoke MP3 exactly.

### Limits and next work

- This validates implementation, numerical continuity and browser interaction;
  no human listening or subjective separation-quality verdict is claimed.
  0% means the saved processed mix, and 100% restores the original reference;
  neither guarantees perfect lead isolation or unchanged harmonies.
- Browser lyric preview currently uses a solid canvas. Full visual placement,
  richer font/outline controls, image/video background preview and presentation
  editing remain P05. Long export-job management remains P06; the model sweep
  stays parked for P07.
- Streamlit stores served media in RAM and browser audition decodes whole
  buffers. Large songs/multiple projects can consume substantial memory; this
  is not disk-streaming playback. ASS presentation has 10 ms time resolution.
- Close the project to release its writer lease promptly. A disconnected
  browser session may retain its lease until Streamlit disposes that session;
  read-only / Save a copy prevents data loss meanwhile.
- Undo history is session-local. Content and recovery snapshots are durable
  after Save; closing without saving intentionally does not publish unsaved edits.


---

## P05 - Visual lyric placement and styling: COMPLETE

Completed 7 September 2026 on top of `2876706` (P03/P04).

### Delivered

- One project presentation compiler resolves song defaults and sparse line
  overrides into ASS for browser preview and native export. The separate GUI
  video-style state is removed. Legacy TOML imports into project defaults,
  converting its canvas-sized metrics once.
- Whole-song scope is the default; selected-line and multiple-line scopes create
  exceptions. Direct dragging, exact X/Y, nine anchors, independent alignment,
  box width, margins and keyboard movement are available. One gesture commits
  one shared command and one Undo. Guides and handles never enter the export.
- Font family/size, bold/italic, unsung/sung colours, outline colour/thickness,
  and shadow controls. Colour codes provide keyboard access alongside swatches.
  Zero outline/shadow and false font flags remain valid overrides.
- Explicit display wrapping and optional box-width wrapping, without changing
  sung timing. Display spelling remains separate. Whole-word onset and word
  sweep both retain the sung colour after a word finishes. Literal braces and
  backslashes survive ASS output; Unicode uses the chosen font.
- Font files are copied into project assets, with actual family/face metadata.
  Installed font browsing and static TTF/OTF import are wired. The compiler
  supplies the same concrete font files to both renderers, including all four
  bundled Noto faces. Missing/changed faces warn and use Noto; absent glyphs
  warn in preview and block final export.
- Persistent solid/image/video backgrounds. Image/video use a centered cover
  crop; video preview samples the existing audio clock and loops silently.
  Missing/changed background assets block final export.
- Named, saved/downloadable/uploadable style presets contain defaults only.
  Applying them is undoable and preserves line exceptions. Reset paths are
  available. Presets do not contain timings, vocals, media paths or font files.
- Appearance, Timing and Vocals tabs share one editor/history. Visual changes
  stale older video snapshots while leaving content-addressed final audio and
  prepared stems intact. Browser audio preparation ignores style-only revisions.
- Line IDs now follow surviving membership through text edits; split children
  inherit source appearance. Conflicting merges report that the largest source
  style was kept. Rewrapping for display uses word IDs and changes no timing.
- Native exports freeze project, presentation, ASS, fonts, background, warnings
  and effective timing artifacts. Safe filter basenames handle quoted/punctuated
  Windows project directories. P06 retains responsibility for export job UX.

### Verification

Final commands:

```powershell
.venv\Scripts\python.exe -m pytest -q -m "not slow"
node --test tests/audio_transport.test.mjs tests/presentation.test.mjs
```

**249 Python tests passed** (15.75 s for the final run), plus **9 JavaScript
tests passed**. The Python suite includes real FFmpeg/native-frame tests and
Streamlit AppTest. The JS suite exercises the actual transport and placement
methods with controlled clocks/DOM doubles; it is not a substitute for the
real-browser observations below.

New checks cover inheritance/zero/reset, colour-only exceptions, atomic invalid
commands, stale/duplicate drags, cancel/keyboard behavior, explicit breaks and
Unicode/ASS literals, display windows, font copying/relinking/fallback/coverage,
imported Noto precedence, preset portability, audio-cache independence, styles
through lyric split/merge, and GUI appearance/preset save/reopen. Native pixel
checks verify word-onset colour changes, mid-word sweep, retained sung colour,
and normalized placement bounds at 720p/1080p/4K. A real export succeeds in an
`Artist's [live], mix` folder.

Real browser (in-app browser, original eight-word/eight-second fixture):

- libass worker loaded and rendered literal `{stars}`, literal `\N`, accented
  Latin, Greek and Cyrillic. Explicit wrapping and bold italic sweep were
  compared visually with native proof frames. This is not a pixel-identity claim.
- A drag over a 599 × 336.9375 CSS-pixel preview moved X/Y from 960/850 to
  **1088/706**, exactly the expected design-coordinate rounding for a +40/-45
  CSS-pixel delta. Revision advanced once. One Undo restored 960/850.
- Observed optimistic paint: **3.8 ms**; command acknowledgement **247.3 ms**.
  Undo acknowledgement was 269.6 ms. These measure different stages and are
  local observations, not a general latency guarantee.
- Font-size and zero-outline changes applied through the form without changing
  the paused 5500 ms song position. Installed-font browsing copied four Arial
  faces through the UI. Font persistence/resolution is also covered by tests.
- At song position **5500 ms**, ASS read 5500 ms and the two-second background
  video read **1500 ms**. The browser crop matched the native proof's composition.
- A selected-line override was set through the UI to Y=700, outline=0 and
  sung colour `#F2AAC8`. Save, Close, Open and reselecting line scope restored
  those exact values at revision 3. Song defaults remained Y=850/outline=4/gold.
- The reopened project rendered through the actual **Render video** button,
  producing `rev-3-video_71be3043b421/karaoke.mp4` with no presentation warnings.

Reproducible media: `scripts/p05_proof.py <new-folder> --render [--background]`
creates original lyrics and synthesized tones, with no separation/alignment or
downloaded song. Solid-background and video-background proofs were each rendered
at 1280×720, 1920×1080 and 3840×2160, with lead-in/word/sweep frame extractions.

Local proof folders:
- `C:\Users\young\Documents\Codex\2026-09-06\run\work\p05-verification`
- `C:\Users\young\Documents\Codex\2026-09-06\run\work\p05-background-proof-2`

The final offline wheel was built and its bundled JS/font/renderer/license files
compared byte-for-byte with source. It declares the added fontTools dependency.
Wheel: `work/p05-wheel/heartbeam-0.1.0-py3-none-any.whl` under the task folder.
SHA-256: `0d680e1c8b806d237d29f2f451a76486bfd68e607b56fe6b78e996992a64571f`.

### Practical limits and continuation

- Guides and overflow detection use font-metric estimates. Actual text is always
  rendered by libass; the editor does not silently shrink it.
- Browser/native rasterization, decode and colour management are not claimed
  pixel-identical. H.264 MP4 video backgrounds were verified; browser-unsupported
  codecs need conversion. Static TTF/OTF faces are supported, not variable-font
  axes or font collections.
- Missing faces produce an explicit fallback warning. Missing required glyphs
  need a font with those characters before final export.
- Streamlit still stores served media in RAM, and audio audition uses full decoded
  buffers. Undo is session-local; Save persists content. Export is synchronous.
- P06 preview/export jobs and P07 quality/model work remain. Use the compiler
  described in `docs/PRESENTATION.md`; do not introduce a second saved style or
  subtitle implementation.


---

## P06 - Preview, export and release integration: COMPLETE

Completed 7 September 2026 on top of `d770ca2` (P05).

### Delivered

- Saved singer-facing line scheduling can show a phrase before its first word,
  hold it after the final word and optionally show the next phrase in a second
  vertical slot. Song-start lead-in clamps to zero. Display scheduling changes
  neither effective word timing nor vocal regions. Upcoming events end exactly
  when that line becomes current. Adjacent phrases share a clean display boundary
  when lead and hold do not both fit; actual overlapping vocals remain intact and
  are reported rather than truncating a sung highlight.
- Full and up-to-60-second passage renders run as background jobs from a deep
  copy of the current project. Preflight checks FFmpeg, audio/reference integrity,
  final lyric timing, fonts/glyphs and backgrounds before starting the encode.
- FFmpeg reports encoded-media progress. The UI supports refresh and cancellation,
  labels the frozen source revision and keeps the editor usable while rendering.
- Each job writes to its own hidden temporary directory and atomically promotes
  the directory only after success. Failure/cancellation cleans that directory
  and preserves every completed output. Saved unfinished jobs are labeled
  interrupted after an app restart.
- `export-manifest.json` records the source revision, full/passage kind, passage
  range, exact audio hash, project asset IDs/hashes and compiler warnings. Existing
  ASS, timings, presentation, project snapshot, concrete fonts and copied
  background artifacts remain alongside the MP4.
- The legacy `heartbeam-video` CLI and Windows GUI launcher import path remain
  operational. End users still need no Node.js or frontend development server.

### Verification

`257` Python tests pass with `-m "not slow"`, including real FFmpeg renders and
Streamlit AppTest. `9` JavaScript transport/placement tests pass. New tests cover
display lead/hold/upcoming boundaries, persisted settings, invalid preflight,
clip-relative timing without source mutation, frozen revision/style inputs,
successful promotion, encoder failure, cancellation and last-good retention.

Real browser, eight-second project with looping H.264 background:

- Enabled a 1200 ms lead, 500 ms hold and upcoming line slot. The preview updated
  at revision 4 without changing the audio clock or surfacing an application error.
- A final-quality 0–3.5 second passage job visibly entered the 8% encoding state,
  then completed with its revision-4 download while the revision-3 full video
  remained available. This found and fixed FFmpeg's initial `out_time=N/A` case.
- A full revision-4 video then completed through the same browser controls. The
  small eight-second job finished before the attempted cancellation; cancellation
  and last-good retention are verified by the controlled job test.

Full-song project proof used the existing local 204.745-second, 245-word artifacts
without rerunning separation or alignment. The corrected proof rendered in about
5.0 seconds on the
reference machine to H.264 960×540 plus AAC stereo 44.1 kHz. The MP4 duration is
204.745011 seconds; the frozen manifest records revision 2 and audio SHA-256
`a9e44366ca87485cf44153139b4113df30e705051ed8ed0e835570faba76f542`.
Frames at 2.2, 86.0 and 190.0 seconds confirmed readable start, middle and end
layouts after the adjacent-window correction; these are visual checks, not a
pixel-identity claim against the browser canvas.
The same full song also rendered through `heartbeam-video` at 320×180, confirming
the compatibility route.

Local evidence:

- `C:\Users\young\Documents\Codex\2026-09-06\run\work\p06-full-song-2` (final corrected frames)
- `C:\Users\young\Documents\Codex\2026-09-06\run\work\p06-cli`
- `C:\Users\young\Documents\Codex\2026-09-06\run\work\p06-wheel-2`

The offline wheel contains the new export manager plus the bundled JS, CSS,
fonts, WASM renderer and licenses. SHA-256:
`af911beb773edee6eacd52a385ddf0af388c45fe4d2e7231c76b5eb378463ee5`.

### Limits and next work

- The UI uses an explicit refresh button for export progress; it does not force
  periodic whole-app reruns while the user is editing.
- Cancellation is cooperative at the FFmpeg encode stage. If a new vocal mix must
  first be materialized, cancellation takes effect after that bounded preparation.
- Browser/native rasterization and colour management remain allowed to differ;
  both use the same ASS, design dimensions and concrete fonts.
- P07 owns controlled vocal-removal model comparisons and subjective listening.
  Keep existing project defaults stable until reproducible A/B evidence supports
  a preset change.

---

## Post-P06 multi-line playback refinement: COMPLETE

Completed 7 September 2026 on top of `0baecf8`.

- **Lines on screen** is saved with the project and accepts 2, 3 or 4. The current
  lyric plus upcoming rows use one continuous stack; future rows move down at the
  exact current-line boundary and retain their resolved unsung colour.
- Long gaps no longer blank the stack. Competing lead/hold windows still shorten
  at a shared boundary without changing any sung word, vocal region or audio time.
- A prominent **Playback preview** group provides Play/Pause, Restart, Previous
  lyric and Next lyric. Navigation seeks to the compiler's display starts and the
  existing AudioContext remains the only song clock.

Verification passed all 261 non-ML Python tests and 11 JavaScript transport,
placement and navigation tests. A real browser check on the 204.745-second,
245-word project selected four rows, confirmed white upcoming lyrics, gold active
highlighting, Restart at zero, and exact next-lyric display navigation without an
application error. A fresh native full-song export produced H.264 960×540 plus AAC
stereo at the exact 204.745011-second audio duration; its 6-second frame contains
four rows with only the sung portion highlighted. Evidence is under
`C:\Users\young\Documents\Codex\2026-09-06\run\work\p06-multiline-preview`.
The offline wheel under `work\multiline-preview-wheel` contains the updated JS and
CSS byte-for-byte. SHA-256:
`12d748282c63057043143f4f1a9e21d020dc9c11f11382b462f48e29a7da06c5`.

---

## Two-step workflow and editing workstation: COMPLETE

Completed 7 September 2026 on top of `4c8383b`.

- Separation inputs live on step 1. A completed run offers an audio audition,
  a durable destination folder and **Save project and edit video**. The temporary
  recovery project still exists as soon as generation completes. A failed save
  stays on step 1 and does not replace an existing project.
- Opening or importing a project enters step 2 directly. The editor resolves
  media from that project, even if the session contains an earlier generation run.
- A wide desktop workstation puts the prominent Play/Pause, source/speed,
  preview, seek/loop and waveform on the left. Live lyric selection and the
  Appearance, Lyrics, Timing, Vocals and Export tabs occupy a separately scrolling
  right pane. Save and step navigation are available in the top bar. Below 1000px
  viewport width the panes stack for usable controls.
- The inspector hosts the same lyric/vocal controls and event handlers. Only
  the monitor owns an AudioContext. Leaving the editor disposes that context;
  returning mounts one fresh player and one inspector without duplicated roots.

Verification: 264 Python tests and 14 JavaScript tests pass. New application
tests simulate a completed separation, save and reopen its audio/timing/IDs from
a chosen folder, exercise both page transitions, and reject saving over another
project. Separation itself was not rerun for this UI change.

The real Chrome proof ran on both the development server and the normal launcher
address, `http://localhost:8501/`. At 1500×1000 it verified adjacent panes and
independent inspector scrolling. Play advanced to 1504ms while the background
sampled 1.504s; waveform and lyric canvases changed on navigation. Applying font
settings while playing retained the same monitor and AudioContext and advanced
to 4760ms. Right-pane lyric selection sought the shared player to 500ms, and the
live vocal slider applied 100% through the same transport. Narrow layout, pause,
page disposal/remount and absence of browser errors also passed.

Browser evidence and screenshots:
`C:\Users\young\Documents\Codex\2026-09-06\run\work\workstation-proof\launcher-evidence`.

The offline wheel in `work\workstation-wheel` includes both workstation assets
and the updated timeline assets, checked against source. SHA-256:
`da124d4112c6c50098f0d70c3a8e6a129153c01d5d8ad5cd9f6374edd453f9e5`.

## Follow-up: online lyrics and phrase-first timing — 7 September 2026

Implemented the owner's two-source timing workflow. LRCLIB lookup previews
lyrics before adoption; a saved project can retain its text and adopt only
timing hints. Lookup failures use cached results or local matching. Only song
metadata is sent online. Complete vocals are retained in new separation caches;
older projects combine saved lead/backing tracks and expose that result as an
audition source.

The proportional lyric-to-ASR allocation is removed. Full-song sequence matching
finds phrase anchors before words are refined. Online cues require distributed
acoustic corroboration; incorrect recording length/order is rejected. Selected
lines keep whole-song context to disambiguate repeated choruses. Recognition is
cached independently of lyric edits. A manually bounded phrase skips recognition.
Missing words remain in the lyrics and review list. Plain draft phrase rendering
does not manufacture word highlights; final export retains its timing checks.

Timing proposals retain stable line/word IDs, original proposals and manual
corrections, and use the existing undo/revision system. New timing JSON sidecars
are validated before import. Generation catches timing-model failure and saves
completed audio plus unresolved lyrics for later repair. Per-phrase refinement
failure does not throw away other phrases.

Verification:

- Full Python suite: **299 passed in 18.45 seconds**. Covers matching, dropped
  words, repeated occurrences, cache reuse, manual windows without recognition,
  malformed timing input, provider outages, saved-audio integrity, preserved
  manual edits, undo/reopen and generation recovery. Two Streamlit AppTest flows
  verify explicit lookup adoption and non-mutating phrase audition.
- Existing browser logic suite: **14 passed** for transport, preview placement,
  lyric navigation and workstation component lifecycles.
- Live LRCLIB query for the owner's song returned record 25227215. Its duration
  metadata is 152.48 s, but its sung timestamps extend to 176.02 s. With source
  audio at 152.50 s, HeartBeam displays the mismatch and falls back locally.
- A real WhisperX CPU run on complete saved vocals produced 209 of 266 word
  proposals; 30 of 38 lines require review. The first chorus proposal starts
  around 66 s instead of being forced into the preceding verse. These are
  changes in proposal placement, not manually verified accuracy measurements.
- Real in-app browser at **http://localhost:8505/** opened the independent
  `frost-hybrid-proof` copy, ran whole-song matching and saved it. Complete vocals
  became available in the shared source selector. A 0.241–5.000 s phrase loop
  played with the waveform/lyric preview: the displayed clock and song position
  advanced to about 4.4 s and wrapped to about 1.4 s. Pause worked. No second
  player or extra audio clock was added.
- The same browser ran a repair of just the first phrase within the explicit
  window; its review state updated and the test repair was undone. The saved
  proof copy retains the whole-song proposal for listening review. No browser
  console errors were reported during these checks.

The original project under the user's temporary generation folder was not
overwritten. Proof copies and lookup evidence are in
`C:\Users\young\Documents\Codex\2026-09-06\run` under `frost-phrase-proof`,
`frost-hybrid-proof`, and `lookup-proof`. `scripts/timing_proof.py` reproduces
saved-audio matching into a new folder. The implementation and continuation
details are in `docs/TIMING_SYSTEM.md` and `HANDOFF.md`.

Limits: the problem song remains a review draft with 57 untimed words after the
whole-song run. There is no broad annotated timing benchmark or verified held
note endpoint accuracy. Lead/backing RMS assignment and separation models were
not changed. SOFA was not installed or evaluated. The existing torch/CUDA setup
was preserved. Runtime libraries still emit the previously documented optional
TorchCodec/checkpoint warnings; the tested alignment path completed successfully.

### Upload metadata dependency fix

The owner found an upload crash because `mutagen` had been declared in
`pyproject.toml` but was absent from the existing launcher environment. The
earlier browser checks exercised saved-project matching, not fresh song upload.
Installed mutagen 1.48.1 in the repository `.venv`, which the running launchers
use. Moved its import inside the metadata fallback so missing metadata support
cannot prevent song upload. The upload stream is rewound after either outcome.

New regression tests simulate the missing package and read a real in-memory WAV
with the installed package. Full Python suite: **301 passed in 18.32 seconds**.
The JavaScript files are unchanged from the earlier 14 passing checks. Existing
app sessions can use Rerun; no server restart or project reset is required.

### Timing approval and the early Frost Children phrase (7 September)

The GUI now has Prepare audio → Review timing → Edit video. Preparation retains
stems and lyric proposals, but does not construct a removal mask, mix or karaoke
MP3. The prepared project can be saved before review. Original audio, vocal
audition, waveform, rendered lyrics and timing controls share the existing
transport. A user must fix unresolved/conflicting timing, confirm they listened,
and explicitly approve/build before entering video editing. Approval is tied to
the current lyrics, effective timing and source asset identities. Changes require
review again; appearance changes do not. Existing phrase-matched projects need
review too; old imports without phrase metadata remain usable.

The current problem recording was found in `heartbeam_gui_nw665fed/out/project`.
Its first reported line had a stalled recognized prefix at 28.484–32.226 seconds,
while `cross-town`, `train`, and `again` had acoustic evidence near 34–36.5 seconds.
Refinement nevertheless moved the phrase to 28.494–31.416. A new consistency
check retries inside supported words and leaves continued disagreement unresolved.
Using the saved complete vocals, the retry placed the first word at 33.330,
cross-town at 33.951–34.914, train at 34.974–35.575 and again at 35.616–36.377.
The article `the` remains unresolved. The second line still begins around 36.84;
its exact perceptual onset has not been manually verified.

The original project's backing-stem excerpt also transcribed both reported
phrases. Existing masks already cover approximately 91% and 98% of the two
examined windows due to the energy mask, so timing alone does not explain the
residual singing. The build option can now exclude backing from replacement
regions, sacrificing its harmonies. This does not guarantee perfect separation
or remove leakage already present in the instrumental stem.

Verification:

- Full Python suite: **312 passed in 20.49 seconds**.
- Playback/presentation/workstation JavaScript: **14 passed**.
- New regressions cover preparation without any mask/mix/MP3 calls (including
  failed alignment), saving and reopening a prepared project, gated export and
  build, explicit approval, later-edit invalidation, save/copy/undo/redo,
  encoder failure, changed audio, unresolved words, backing exclusion, and the
  stalled-prefix retry and rejection paths.
- Real browser on port 8505: synthetic prepared project opens in Review timing;
  Original is selected, Play advances the shared clock from 200 to 4000 ms,
  video/build are disabled until confirmation, and approved building saves an
  MP3 and opens the video workstation with Karaoke selected. Preview rendering
  and the two-pane layout were visually inspected at 1280 × 720.
- The corrected song is a separate review copy, never silently approved:
  `C:/Users/young/Documents/Codex/2026-09-06/run/verse-review-proof`.
  Diagnostics and excerpt measurements are in the neighboring `verse-audit`
  directory. The user's source project was not overwritten.

The test server on 8505 was restarted to load all modules together. Older
running servers may need a restart for this cross-module workflow change.
No new ML separation or broad model-quality benchmark was performed.

### Waveform seeking and editing continuity (7 September)

The waveform replaces the separate song-position slider in both review and
video editing. Click or drag its upper lane to seek, with pointer capture for
continuous scrubbing and cancellation handling. The lower lyric blocks retain
their timing gestures. The playhead, played-region shading, numeric time field,
ASS preview and background video use one sampled HBTransport time. Paused seeks
remain paused; playing seeks continue. Zoomed playback follows the playhead by
default, with a Follow playback toggle for inspecting elsewhere. Seeking outside
the current loop exits that loop. Keyboard seeking is isolated from word nudges.
Play/Pause and the clock remain visible when scrolling down to the waveform;
the browser proof verifies their position inside the monitor viewport.

Removed the transient `st.empty()` workstation wrapper introduced with timing
approval. It recreated the player after timing edits and undo. Approval callbacks
and distinct tab keys already handle the page transitions; the persistent
workstation now retains playback through ordinary edit transactions.

Verification:

- **312 Python tests passed in 23.11 seconds**, including all 25 GUI workflows.
- **21 JavaScript tests passed**, including zoom/scroll/CSS coordinate mapping,
  pointer cancellation, capture release, keyboard isolation, follow boundaries,
  and preserving Play/Pause across repeated seeks.
- `scripts/waveform_browser_proof.mjs` passed against a synthetic eight-second
  MP3 project with a moving video background. Real browser mouse drags sought
  while held, while paused and while playing. A paused click landed at 2800 ms;
  the drag reached 5200 ms. The waveform and ASS clock matched the transport
  exactly at the sampled checkpoints; the numeric field rounded to 10 ms.
- Browser checks also covered source switching among MP3/original/vocal mix,
  20× zoom following, disabling follow, seeking out of a loop, timing edits and
  undo while playing, and the review page. Scrubbing left the project revision
  and saved manifest unchanged. Lower-lane dragging made one undoable edit.
- Evidence: `C:/Users/young/Documents/Codex/2026-09-06/run/waveform-playback-proof/browser-proof/`.
  The original song project and its timing approval were not changed.

No new models, separation runs or end-user dependencies are required.

### Firefox playback seeking correction (7 September)

The preceding browser proof used Chrome. The owner reported that Firefox
received waveform clicks but did not seek the playing audio. Reproduced with
the installed Firefox **155.0.1** in an isolated headless profile: a paused click
worked, but seeking during playback threw
`TypeError: this.output.gain.cancelAndHoldAtTime is not a function`. The displayed
clock moved while the old audio source continued playing from its old offset.

HBTransport now uses `cancelScheduledValues` and a shortened linear ramp to
hold the known fade-in level before fading the old source out. This preserves
the 15 ms crossfade, including repeated seeks before a fade-in has finished,
without relying on `cancelAndHoldAtTime` (see its
[limited browser availability](https://developer.mozilla.org/en-US/docs/Web/API/AudioParam/cancelAndHoldAtTime)).
The transport test double intentionally omits that unsupported method.

Verification:

- **22 JavaScript tests passed**, including short-interval seek fades, mix
  headroom, source restart offsets, pause/resume, rate changes and loops.
- Actual Firefox pointer input against a standalone harness using the production
  transport and waveform gesture classes: paused click at 2.8 s, playing click
  restarting the audio source at 5.6 s, held drag ending at 2.4 s, paused seek
  and resume at 4.8 s. Audio-node start offsets were recorded independently of
  the displayed clock. The pre-fix harness failed; the fixed harness passed
  without JavaScript errors. This was a focused transport test, not a full
  Firefox workstation or export certification.
- Full Chrome workstation proof passed again: MP3 waveform seeking, drag,
  clock/ASS/video synchronization, editing/undo during playback, source changes,
  looping and both editing pages. Project manifest remained unchanged by seeks.
- Evidence: `C:/Users/young/Documents/Codex/2026-09-06/run/firefox-seek-before/`,
  `firefox-seek-after/` and `firefox-fix-chrome-proof/`; the standalone harness is
  `firefox-seek-proof.mjs` in that workspace.

Existing browser tabs need a Streamlit rerun to load the updated transport.
Saving the project and refreshing also loads it. No server restart is required.

### Rolling lyrics, Firefox selection and optional word review (8 September)

The preceding restart note applies to the transport-only change. This update
changes Python modules too, so already-running servers need a restart after
saving pending edits. Verification used a separate test server on 8506.

Implemented:

- Current phrase on top, next 1–3 phrases below. At its sung end the current
  phrase exits upward and future lines rise together, with the next unseen line
  entering from below. Movement defaults to 220 ms and can be disabled. Explicit
  wrapping or measured width wrapping uses the same scene in both renderers.
- Letter spacing (kerning) and line height, with sparse overrides, presets,
  undo and saved-project round trips. The chosen anchor places the entire stack.
- Missing words stay plain while known words highlight. Independent absolute
  ASS onsets preserve gaps, overlaps and sweeps across movement event splits.
- Review-list selection explicitly seeks the phrase even when its first word
  is untimed, including repeated clicks. Decoded duration handles absent asset
  metadata. A focused native dropdown is no longer reset every frame, and stale
  navigation cannot override a later selection when entering video editing.
- The audio build button needs no all-words-fixed or all-words-reviewed gate.
  It warns, then builds with current word/phrase timing. The fallback policy and
  phrase fingerprint persist for rebuilds without fabricating word times or
  review flags. A failed build cannot approve the live project.

Verification:

- Full Python suite: **322 passed in 31.27 seconds**. Transport/presentation/
  waveform/workstation JavaScript: **24 passed**.
- Real native render pixels verify three ordered rows, halfway/settled rise,
  increased letter/row spacing, and a 30%-complete word sweep continuing through
  a movement boundary. Existing three-resolution placement checks also pass.
- Actual Firefox **155.0.1**, isolated headless profile, real app on 8506:
  known-word highlight pixels beside an untimed word; first/repeated review
  selection seeking to 100 ms; native dropdown selection seeking to 1100 ms;
  playing waveform seek restarting the audio node at 1.001 seconds; moving
  handles; build with an unresolved word and zero review flags; selection
  preserved across page transition; spacing increment buttons, Apply and Save.
  Saved letter spacing is 4 and line height 1.8; the missing timing stays null.
  No JavaScript errors were captured. Evidence:
  `C:/Users/young/Documents/Codex/2026-09-06/run/firefox-workstation-final-verified/`.
- Full Chrome workstation proof passes after these changes: both editing pages,
  waveform/ASS/video synchronization, source switching, loop exit, timing edits
  and undo during playback. Separate native input/Tab/Apply/Save checks confirm
  both spacing values persist. Evidence: `text-chrome-workstation-proof/` and
  `chrome-appearance.png` in the same workspace.

Limits: the raw Firefox headless harness did not deliver normal input focus/blur
events, so typed numeric entry was not certified there; increment-button edits
were verified. Chrome typed entry and Python form persistence passed. Mozilla
documents related [background focus limitations](https://bugzilla.mozilla.org/show_bug.cgi?id=1398111).
This is not a claim of complete Firefox or accessibility certification.

Partially timed audio can now be built, but final video export still rejects
unresolved/conflicting words. Unanchored phrases cannot be scheduled or covered
by a phrase fallback. Existing energy-mask settings still apply. Tall or heavily
wrapped stacks can overflow; warnings are shown and no automatic shrinking occurs.
No new model sweep, separation run, song timing benchmark or guarantee of complete
vocal removal is part of this change. The owner's song was not silently built
or marked reviewed during testing.

## Follow-up: estimated highlights and independent vocal tracks — 8 September 2026

The owner explicitly requested estimated highlights for missing word matches,
an independent backing track, and a fine lead-vocal restoration slider.

- `timing_estimates.py` derives labelled integer-ms times inside a lyric line
  from neighboring words or valid phrase anchors. Character-weighted runs have
  at least 10 ms per word. Touching neighbors may share a labelled overlap while
  known timings remain unchanged. Known-known conflicts are still reported.
  Estimates default on, can be disabled in Timing, and appear with dotted
  underlines, tooltips and a count. They are never marked reviewed automatically.
- `effective_timing()` is still the shared editor/ASS/export path. Raw missing
  timings remain missing; save/reopen and anchor edits recompute estimates.
  Both alignment application paths use raw timing for fill-only mode, so acoustic
  matching can replace an estimate while preserving actual manual corrections.
- New GUI builds use `separated_stems`: instrumental once, plus independently
  controlled lead and backing. Both sliders and numeric inputs accept 0–100% in
  1% steps. Existing section regions override only lead. Saved legacy projects
  retain their previous mix until **Use separate lead and backing tracks**.
- Preview shares one audio clock and fixed headroom. Final WAV/MP3/video use the
  current mix followed by one mastering stage. Current audio downloads are
  explicitly prepared and cached per mix identity; the initial build MP3 has a
  separate, accurate label. No ML pass is needed to change levels.
- Passage snapshots freeze estimated times before removing surrounding words.
  Their approval is derived only from an already-approved source snapshot;
  cropping cannot approve an unapproved project.

Verification:

- `.venv/Scripts/python.exe -m pytest -q -m "not slow"`: **335 passed**, 24.20 s.
- `node --test tests/*.test.mjs`: **27 passed**, including three new transport
  tests for separate backing gain, 1–5% lead, region overrides, synchronized
  starts/loops, fixed headroom and rejection of mismatched track lengths.
- Real Chrome and Firefox **155.0.1**, separate original-tone/lyric projects on
  8506: a raw untimed word produces **706 highlighted pixels** at 0.5 s; build
  succeeds; lead **3%** and backing **50%** can be typed while playing; waveform,
  ASS and audio clock stay synchronized. Save/reopen retains both levels and
  selects the current vocal mix. Raw missing timing remains null. No captured
  JavaScript errors. Firefox waveform click restarted audio at 5.006 s and kept
  playing. These are actual native keyboard/pointer actions through WebDriver BiDi.
- Synthetic 200/400/800 Hz tracks isolate the three gains: unmastered amplitudes
  are **0.2000000 / 0.0090000 / 0.0500000** at lead 3%, backing 50%. Actual MP3,
  20-second MP4 and 3-second passage MP4 decode to lead/instrumental and
  backing/instrumental ratios **0.045 / 0.25**, within 0.3%. Both videos retain
  estimated-word timings and warning, mix settings and immutable project snapshot.
- Final live-server Chrome check on 8505 also prepares both current MP3/WAV
  download buttons, keeps the faders through reruns, and saves/reopens at 3%/50%.
  Evidence: `track-live-evidence/`. A separate media regression verifies that an
  older stem-only project exports the current mix even without legacy clean/
  original reference metadata or an initial karaoke MP3.
- Repeated GUI export checks exposed Windows `WinError 5` while job progress
  replaced a JSON file still open in the recovery reader. Recovery reads now
  share the existing writer lock. The failing GUI case plus ten export/stem
  tests passed, followed by the full 335-test run above.
- Evidence lives under `C:/Users/young/Documents/Codex/2026-09-06/run/`:
  `track-browser-evidence/`, `firefox-track-evidence/`, `track-export-evidence/`.
  Reproducers there are `build_track_fixture.py`, `track-browser-proof.mjs`,
  `firefox-track-proof.mjs` and `track-export-proof.py`; each guards its synthetic
  fixture identity. The actual saved song was inspected without modification.

Limits: the saved Frost Children review copy has 56 raw missing words. Eight
can now be estimated inside timed phrases. The other 48 occupy nine whole lines
(30–38) with no raw timings or phrase anchors; this change does not place those
verses arbitrarily in the recording. They need rough phrase bounds or alignment.
Final video still blocks remaining unanchored words and known timing conflicts;
audio building does not. Percentages are stem amplitudes, not calibrated
perceptual loudness. Lead leakage within the backing stem remains when backing
is audible. No new separation-quality or perceptual listening benchmark is claimed.

The owner's 8505 server was restarted to load these modules, after confirming
the current in-app session had no project open. Health endpoint returned `ok`.
No owner project was saved, built or approved by the verification scripts.

## Follow-up: timing warnings allow video export, 10 September 2026

The owner reported that **Render video** stopped at “Fix 8 untimed word(s) and
3 timing conflict(s) before export” and explicitly requested a warning instead.
Derived estimates were already accepted, but remaining missing words, known-word
conflicts and stale approval still stopped the shared strict compiler.

Export jobs now default to `allow_timing_issues=True` and freeze that policy with
the job. Preflight, final timing JSON and the final ASS renderer all use it;
changing just preflight would still have failed during encoding. The UI shows
warnings while encoding and keeps them with the completed video. The old preview
and Timing-tab messages claiming export was blocked were corrected.

Estimated and known timings highlight as in the preview. Other words remain
plain within a known word/phrase window or an authored display window. Completely
unanchored lines are omitted with warnings. Invalid display windows fall back to
available lyric timing. Passage snapshots preserve plain words in intersecting
windows, shift phrase anchors, and retain estimated timings before cropping.
An audio-only passage with no usable lyric window can also render with a warning.
Raw lyrics/timing/review state are not rewritten or marked approved by export.

Low-level compiler/timing APIs keep their strict defaults; audio construction
still requires its existing approval. Export callers can explicitly select
strict timing checks with `allow_timing_issues=False`. Font glyph coverage,
missing/changed audio or backgrounds and invalid clip bounds remain validated.

Verified:

- Full Python suite: **341 passed in 24.43 seconds**.
- JavaScript suite: **27 passed**. `git diff --check` passed.
- Six new timing-warning tests include the exact **8 missing / 3 conflict** case,
  estimated highlights, current preview/ASS agreement, unchanged source project
  and review flags, full and passage MP4 encoding, plain phrase-window shifts,
  unanchored-line warnings, and retained font/audio checks.
- Real in-app browser, existing server **http://localhost:8505/**: isolated
  **Export warning proof** opened with eight untimed words and three conflicts.
  Clicking **Render video** displayed those warnings, reached **100% / Video
  ready**, and exposed **Download karaoke.mp4**. The final preview wording was
  confirmed after Streamlit's **Rerun**, retaining the loaded test project.
- Evidence: `C:/Users/young/Documents/Codex/2026-09-06/run/export-warning-proof/`
  includes `exports/rev-1-full-export_5964f4cecd6c/karaoke.mp4`, the matching job
  record, ASS, full project snapshot and warning manifests. The synthetic fixture
  generator is `build_export_warning_fixture.py` in that workspace.

The running server loaded the change through its source watcher. No restart,
owner-project overwrite or new ML pass was needed. The test browser tab was
closed after verification; the owner's tab remains open.

## Follow-up: editor recovery after export, 10 September 2026

The owner reported HeartBeam was broken after exporting. The server remained
healthy and their latest full video (`export_4d18085f91cb`, Paloma Faith revision
21) was complete. No owner-session crash traceback was found. In an isolated
copy of revision 22, the old UI stayed at 2% even after the job failed at 96%:
Windows denied replacement of its progress JSON. This demonstrates two defects;
it does not establish every symptom in the owner's separate browser session.

- Export status now polls in a one-second Streamlit fragment. Only progress and
  cancellation rerender during encoding. Completion triggers one full refresh,
  consumes the job, restores downloads and stops the polling fragment.
- Progress saves retry brief Windows permission failures and avoid duplicate
  writes from FFmpeg's two timestamp fields. Persistent progress-storage failures
  report a warning and preserve encoding/completed output. Initial job creation
  must still succeed; a rejected write no longer leaves a phantom active job.
- Project manifests, audio preparation, timing policy and renderer input
  snapshots are unchanged. Completed export folders remain recovery sources if
  progress records could not be updated.

Verification: **344 Python tests passed in 147.94 seconds**, including simulated
Windows file locks, persistent status-storage failure through a real MP4 render,
failed-start recovery, and saving edits after export. The focused export/editor
run passed all 40 tests. No JavaScript changed; its previous 27-test result stands.
`git diff --check` passed.

Live browser verification on 8505 used
`C:/Users/young/Documents/Codex/2026-09-06/run/post-export-review/` (a copy of the
owner's project). The repaired full 3:50 song export completed automatically as
`exports/rev-22-full-export_099e13e5e336/karaoke.mp4`. Playback and waveform position
continued during rendering, an appearance edit advanced only the editing copy
to revision 23, and waveform clicking sought playback after completion. The
export retained revision 22 and the download remained available. No browser
console errors were observed. A second render was cancelled in the browser;
the status automatically changed to cancelled and kept the previous download.
Firefox was not directly exercised in this turn.
The server was not restarted; another user-started audio preparation was active.

## Follow-up: separate Music Repair stage and audio baseline, 11 September 2026

HeartBeam now uses five explicit stages: **Prepare Audio → Review Timing → Edit
Video → Repair Music → Export**. Video Editing no longer embeds export controls.
Export becomes available from Music Repair, where the user can scan, review,
skip, apply a bounded local level correction, undo it, or continue with a
warning. Unreviewed suggestions do not change audio and do not block export.

R0 records and applies one least-squares gain to the complete instrumental plus
vocals partition after separation. The same factor is applied to nested lead and
backing stems, preserving their balance. The calibration result is retained in
cache provenance. One saved mastering policy now identifies and drives approved
audio, final preview mixes and video export.

R1's first CPU detector compares 200 ms instrumental energy with its local
context while requiring the original recording to remain steadier. It rejects
shared rests and ranks possible passages for listening; its score is not a
damage probability. The existing Paloma review copy produced the same 11
volume-only candidates as the prior research probe, headed by 182.55–183.20 s.
That agreement proves reproducibility, not that all 11 passages are damaged.

Accepted local-level repairs are stored on schema 2 with immutable source asset
identity, hash, sample basis, millisecond and sample bounds, method, strength,
fade and provenance. Schema-1 projects migrate on read; the first save preserves
`project.schema-1.backup.json`. Applied repairs create a content-addressed
lossless instrumental derivative. Browser preview and export resolve that same
derivative through the shared stem mixer. Source changes and overlapping applied
repairs fail clearly.

Verification at this checkpoint: full Python suite **355 passed in 25.58
seconds**; the focused repair/workflow suite passed **36 tests**. JavaScript transport
suite **27 passed** and `git diff --check` passed. No
listening test has yet shown that local gain restores a missing instrument. R2
must compare complementary separator evidence and conservative reallocation;
the UI labels gain repair accordingly and does not claim reconstruction.

Live browser verification on 8505 opened the isolated
`music-repair-ui-proof-589ca94` project. Video Editing showed Export disabled;
Music Repair retained the one synchronized workstation transport and exposed
**Find thin spots**, a manual range, bounded lift/fade controls and **Continue to
export**. The real 230.5-second tracks produced 11 ranked passages. Continuing
with all 11 unreviewed opened the separate Export page, displayed the warning,
kept **Render video** enabled and did not apply or save any suggestion.

R2 now has an offline two-model consensus prototype and
`tools/benchmark_instrument_repair.py`. BS-RoFormer and UVR MDX Inst HQ3 each
estimate accompaniment from a short source excerpt. A time-frequency
intersection retains only material both models support and filters that donor
from the current lead/backing recordings; alternate model audio is never mixed
into the performance. The donor is added to instrumental and subtracted from
the originating vocal stem. Synthetic tests verify model veto, range support,
zero-strength identity and exact stem-sum conservation.

On the highest Paloma volume flag (182.55–183.20 seconds), the two-model donor
has about the same RMS as the quiet baseline accompaniment inside the focus
range (0.008 dB donor/baseline ratio). A non-flagged 60.00–60.65-second control
produced a donor 26.69 dB below its baseline. Full-fader stem accounting on the
candidate differs by at most `7.45e-9`. These are encouraging pilot measurements,
not evidence that the donor contains no vocal. Lossless comparison packs and
model hashes live in `heartbeam-audio-research/r2-paloma-consensus-v2`, with a
second candidate and a control beside it. R2 remains experimental pending
listening and unrelated-song/ground-truth tests.

## Follow-up: Music Repair acceptance and failed R2 quality gate, 11 September 2026

The full Python suite passed **361 tests in 26.29 seconds** after six new
regressions; the JavaScript suite passed **27 tests**. Additional direct signal
checks exercised stereo, seven short input lengths, range boundaries, full-stem
sum conservation, and lead/backing gains at 0%, 1%, 3%, 5%, 50% and 100%.

Testing found and fixed these defects:

- Solo **Instrumental** audition resolved the raw stem after a repair. It now
  resolves the same repaired derivative as the live mix and export; Undo restores
  the raw asset. A broken repair is displayed as unavailable, not silently bypassed.
- An unfinished repair range could reset during a scan/playback rerun. Draft
  controls now persist separately from Streamlit's disposable widget state.
  Only Apply commits a project repair. The ready range is displayed explicitly.
- A legacy clean/original mix could accept an instrumental repair and then ignore
  it. Apply now requires separate tracks, and rendering rejects an incompatible
  saved recipe rather than silently omitting its repairs.
- The experimental recovery mask divided by the alternate model's magnitude.
  A 10% shared vocal residue could therefore move approximately **85%** of the
  original vocal into the instrumental. Version 2 bounds the transfer by the
  alternate excess relative to the sum of donor magnitudes. The same controlled
  case now transfers at most approximately 10%; this prevents amplification but
  does not prove that shared vocal residue is safe to transfer.
- Benchmark version 4 checks source hashes, rejects short alternate outputs,
  calibrates the legacy partition in memory before comparison, and uses the
  product's smooth instrumental-only +2 dB envelope as its level baseline.

Chrome and installed **Firefox 155.0.1**, both headless on isolated port **8511**,
passed: the separate stage and export gate, scan, apply while playing, synchronized
waveform/ASS clocks, repaired solo playback, Undo, save/reopen, warning-only
continuation, actual video rendering, and playback after export. Browser errors
were empty. The played instrumental buffer measured `0.0226606574` amplitude for
the expected `.018 * 10**(2/20)` repaired tone in both browsers.
Firefox numeric typing was committed with **Enter**. Tab-only entry did not
commit in that test; the page now instructs Enter and displays the accepted range.
The first Firefox harness also required corrected selectors to distinguish the
visible repair inputs from identically named hidden Timing-tab fields.

Actual full and passage MP4 exports were decoded and measured. A +6 dB local
repair multiplied the instrument by `1.9952623`, with lead/backing unchanged to
about `1e-8` relative gain in the raw mix. Decoded AAC vocal/instrument ratios
matched the expected mix within the test tolerance; WAV preview and export used
the same repaired stem. Decoded durations include 32 ms of AAC frame padding.
The original instrumental asset was unchanged.

R2 **has not passed the quality gate**. Calibrated two-model experiments ran on
two real songs and a control: Paloma at 182.550–183.200 s, Frost Children at
97.450–97.950 s, and Paloma at 60.000–60.650 s. Recovered-only RMS relative to
baseline was **-44.55 dB**, **-29.81 dB**, and **-42.05 dB**, respectively.
The earlier strong Paloma donor result is superseded: it used the flawed mask
and an uncalibrated legacy baseline. Current numbers do not establish a useful
musical repair or absence of words/breaths. No perceptual listening verdict is
claimed. A controlled legitimate instrumental rest with continuing vocals also
triggered the energy detector, proving why flags must remain optional hints.

Evidence lives under `C:/Users/young/Documents/Codex/2026-09-06/run/`:
`repair-validation-acceptance/` (Chrome, signal and decoded exports),
`repair-validation-firefox-final/firefox-enter/` (Firefox), and
`repair-validation-20260911/` (before/after and calibrated real-song packs).
Reproducers and the detailed report are in `heartbeam-audio-research/`.
No owner project or model weights were changed by these experiments.

## Follow-up: removed-vocal screening and MP3 comparisons, 12 September 2026

The offline R2 experiment now runs each cached separator on the removed
lead+backing audio as well as the original mix. Version 3 of
`recorded_reallocation()` supports an optional 80% instrumental-purity veto.
One arm adds this veto to full-mix consensus; another lets the removed-vocal
passes propose the recovery themselves. Actual transferred audio still comes
from the recorded donor stems and is subtracted from the respective vocal stem.
This is not integrated into the product's accepted repair methods.

Controlled orthogonal-tone trials with 1%, 3%, 5% and 10% shared voice residue
returned about 85% of a deliberately misplaced instrument and less than
`1e-7` of the vocal amplitude. A deliberately incorrect model classification
of the entire voice returned about 85% of that voice. The gate therefore fixes
the weak-residue example, but cannot certify model semantics or voice-free audio.
An indistinguishable 50/50 shared-waveform case abstains. Stereo tests verify
range support, full-stem conservation and independent vocal-fader accounting.

Three real-song trials used seven seconds of context on each side and muted
both vocal stems in memory. These differ from the earlier three-second-context
experiments; their numeric differences are not evidence of improvement.

| Passage | Consensus donor/baseline RMS | With vocal screening | Donor-first screening |
|---|---:|---:|---:|
| Paloma 182.550–183.200 s | -37.04 dB | zero | -98.98 dB |
| Frost Children 97.450–97.950 s | -24.90 dB | zero | -100.93 dB |
| Paloma control 60.000–60.650 s | -44.47 dB | zero | zero |

The screened candidates therefore establish abstention, not useful repair.
No real-song perceptual improvement or absence of returned vocals is claimed.
The maximum full-fader stem-sum error across variants was `1.20e-7`.
Four model calls per passage took 45.37, 28.02 and 26.93 seconds, including model
loading/calibration but excluding MP3 output. ONNX ran without CUDA acceleration.
Existing cached weights were used; no audio was uploaded or new weights fetched.

`heartbeam/listening_pack.py` creates 320 kbps MP3s with one common gain and a
separate matched-loudness set. It records gains and source hashes, uses common
peak protection without a per-condition limiter, and decodes every output to
verify samples, duration and oversampled peak. The 66-file listening pack includes
seven conditions per song, original context, boosted donor-only diagnostics and
known 0/1/3/5% lead-stem controls. All decoded durations were exact (14.65 s for
Paloma, 14.50 s for Frost), maximum decoded peak was -1.99 dBFS, and matched
condition loudness spread was below 0.004 LU. The ZIP passed integrity checks.
Project manifests were unchanged during the experiments and input hashes checked.

Verification: **368 Python tests passed in 34.49 seconds**, including seven new
screening/MP3 regressions; `git diff --check` passed. No browser or JavaScript code
changed. The prior 27-test JavaScript and Chrome/Firefox acceptance evidence
remains the last UI verification; it was not rerun for this offline experiment.

Evidence and user-openable audio: `heartbeam-listening-20260912/` and
`HeartBeam-MP3-Comparisons-20260912.zip` under the shared run workspace.
`heartbeam-audio-research/R2-SCREENING-REPORT.md` records the next decision gate.
The owner explicitly requests comparison MP3 outputs with future audio-quality
work. Do not substitute test metrics or WAV-only references for those files.

## Owner decision: archive recovery and restore direct export, 12 September 2026

The owner listened to the comparisons and reported little audible difference;
the selected current-separation examples already sounded acceptable. Instrument
recovery is **parked**, with no perceptual benefit established by these trials.
Do not automatically continue R2 or infer a general detector accuracy score from
this small listening sample. The owner requested a selective rollback that keeps
useful fixes and the recoverable technique.

The active workflow is now **Prepare Audio → Review Timing → Edit Video → Export**.
The Music Repair stage, automatic thin-spot detector, consensus/donor-screening
algorithm and experiment runner are removed from active code. Sessions left on
the old repair page resume in video editing. Saved unreviewed suggestions remain
serialized for compatibility and neither alter audio nor gate/warn on export.

Retained: common stem calibration and shared mastering; optional manual passage
lifts under **Vocals → Instrumental volume**; persistent drafts and Apply/Undo;
effective instrumental consistency across solo audition, preview and export;
legacy-mix validation; schema-1 backup/migration and existing schema-2 repairs;
reusable verified MP3 comparison tools. Previous timing, Firefox transport and
export reliability fixes are unchanged. Owner projects were not rewritten.

The pre-rollback checkpoint `02c1543` is pinned by tag
`archive/instrument-recovery-2026-09-12`. A verified standalone Git bundle, source
ZIP, and **1,962 evidence files** (including all 66 current MP3 comparisons) are
stored in `C:/Users/young/Documents/Codex/HeartBeam-Archives/instrument-recovery-2026-09-12/`.
The 443,300,520-byte evidence ZIP was read back and every member hash checked;
source ZIP integrity and complete bundle history were verified. The archive
records package SHA-256 values and restore instructions. Original evidence files
remain in place. Claude handoffs are explicitly marked parked and their packager
is pinned to the archived experimental source rather than the active app.

Final verification: **358 Python tests passed in 27.28 seconds**, including
real video generation in the application workflow suite. The focused workflow,
manual repair, stem mix, calibration and MP3 suite passed **45 tests**. Eleven
detector/reallocation cases moved with their archived code; one new compatibility
case verifies old repair-page sessions and suggestions do not block direct export.
The retained draft test now exercises playback reruns, leaving/returning to the
editor, Apply, save and disabling an adjustment. The first run hit a test-only
selector that assumed every widget had a key; the corrected selector passed.
`git diff --check` passed. JavaScript was unchanged and its prior 27-test evidence
was not rerun; no new live-browser playback claim is made by this checkpoint.

See `docs/ARCHIVED-INSTRUMENT-RECOVERY.md` for retained lessons and re-entry rules.

## Workstation UI update, 12 September 2026

Implemented the owner's notes in `docs/UI-WORKSTATION-UPDATE.md`: a File popover,
sequential uploads/metadata/search/lyrics/preparation, search feedback and result
adoption in a separate dialog, Pop and automatic device defaults, and preparation
progress/results immediately below the action. The editor removes repeated
headings, gives Play the same compact sizing as Restart, fits its preview to
available space, and keeps three lyric rows above independently scrolling settings.
Next-line navigation reveals the selected row without enlarging that panel.

Custom export names start with the original input basename plus `_karaoke.mp4`.
They survive page changes and the immutable export path retains/reopens named
outputs. New sessions/projects use Documents/HeartBeam outside the app and system
temp, with a data-root override; existing folders and model caches stay put.
`docs/FILES-AND-DISTRIBUTION.md` describes storage, backups and package boundaries.
The installer excludes Python cache files and its GPU label now matches cu128.

Final full suite: **372 Python tests passed in 29.77 seconds**. JavaScript:
**28 passed**. A live in-app Chromium session verified File open/save-copy,
search feedback dialog, word selection, synchronized waveform seeking, fixed
three-row lyrics and independent settings scrolling, desktop/stacked layouts,
and a complete named video export with matching download. See the UI plan for
measured geometry and clock values. CUDA was confirmed on the RTX 5070.

A local wheel build included all required editor/renderer files and no user
media or development output. Firefox, native browser-zoom controls and a clean
Windows installer lifecycle were not exercised; responsive viewport and
pixel-density sizing checks are recorded separately. Instrument recovery stays
archived; no audio-quality or ML accuracy change is claimed.

## Lyric-pane seek reliability, 12 September 2026

Lyric word clicks now always use a deliberate navigation target. Resolved words
seek to their exact start. An unresolved word inside a timed lyric line receives
a browser-only position interpolated between its surrounding resolved words or
the line display boundaries. That hint does not create timing, approve the word,
or make it highlight. A malformed partial timing also falls back to the line hint.

A live in-app Chromium test used a five-word line with two deliberately untimed
words. Clicking them sought to 2,533 ms and 3,467 ms, kept both words unresolved,
updated the preview clock, and preserved active playback through the Streamlit
selection rerun. Resolved-word seeking remained exact. No browser warnings or
errors appeared. Firefox was not available for direct automation in this pass;
the repaired path uses native button clicks and the shared transport seek method.

Final verification: **373 Python tests passed in 27.45 seconds** and **29
JavaScript tests passed**. The added tests cover unresolved navigation without
fake timing, exact-time priority, malformed partial timing, and missing hints.
`git diff --check` passed.
