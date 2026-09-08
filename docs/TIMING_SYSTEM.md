# Lyric lookup and phrase timing

Implemented 7 September 2026. See BUILD-STATUS.md for the verification record.

## User workflow

1. Choose a recording. Paste lyrics or use **Find lyrics online**. Searching
   never overwrites the current text. A selected result is a candidate, not
   verified timing. Saved projects offer text-plus-hints or hints-only adoption.
2. Separation keeps the complete vocal stem as well as lead, backing and
   instrumental tracks. Timing matches against complete vocals. Older projects
   combine compatible saved lead/backing tracks; original audio is the fallback.
3. Save the prepared project and open **Review timing**. Original audio is the
   default listening source; karaoke mixing and video export wait for approval.
   **Timing → Match lyric timing** matches phrases, then refines words. Review
   missing, uncertain, compressed, overlapping and ambiguous repeated phrases.
4. Choose **Selected lines** or **Lines needing review** to repair a subset.
   For one line, set approximate boundaries, **Loop this phrase**, press **Play**,
   and run matching. Explicit boundaries skip recognition and constrain the
   word aligner. Playback, waveform and video keep the existing single clock.
   Click or drag the waveform itself to seek, including during playback. The
   playhead follows zoomed playback; lyric blocks beneath it remain separate
   timing-edit targets. Scrubbing never writes timing or invalidates approval.
5. In **Build karaoke**, choose **Keep backing vocals** or turn it off to exclude
   lead leakage in that stem, at the cost of its harmonies during removal. Press
   **Build karaoke and continue** with your current edits. Missing word timings
   and conflicts show a warning; they do not require individual fixes or approval
   before this step. The saved tracks produce a clean reference and MP3, and the
   app opens video editing. Known phrase windows cover missing words during
   removal. Portions with no usable word or phrase timing may retain vocals.
6. Manual corrections, phrase evidence and stable IDs survive undo/redo and
   reopening. Changes to lyrics, effective word timing or linked source identity
   invalidate approval, as do changes to phrase windows used for removal. Refit existing lyric-attached vocal regions explicitly
   when their intended section boundaries change.

The 2–4 visible lyric rows and visual wrapping are independent of sung phrase
boundaries. In a partially timed phrase, untimed words remain plain while timed
words highlight. HeartBeam does not invent word timings to animate it or mark
them reviewed when building audio. Final video export still requires resolved
words, corrected conflicts and approval for the current timing.

## Approval and preparation contract

The GUI passes `--prepare-only` to the CLI. It writes lossless tracks, timing/LRC
proposals and `timing-review-required.json`, and returns before mask construction,
removal mixing or MP3 encoding. The temporary clean cache equals the original;
it is only a calibration placeholder, never an approved karaoke source.
The default batch CLI remains automatic for compatibility.

`timing_review.py` fingerprints effective timings, lyric IDs/text and source
asset identities. With incomplete timing allowed, the timing hash also includes
valid current phrase windows. Generated asset duration metadata is not part of
that key; actual source bounds are checked when building the mask. Presentation
styling does not invalidate timing approval.

The GUI explicitly calls `approve_and_build(..., allow_incomplete=True)`.
Valid word intervals plus phrase windows for partially timed lines feed the
existing mask merger. Word edits, unresolved values and review flags remain
unchanged. The approval flag and removal recipe persist this policy for rebuilds.
`require_approved` still guards source/timing changes, and the default API policy
remains strict for callers that do not opt in. Final video exports still use
`current_timings(draft=False)`. Approval/build uses command history; a failed build cannot
approve the live project. Audio is content addressed, and MP3 publication is
atomic so failed encoding cannot poison a retry. Existing phrase-matched projects
also need review; older imports without phrase metadata remain compatible.

## Matching sequence

`lyrics_lookup.py` queries LRCLIB with title, artist, optional album and duration.
Only metadata leaves the computer. Results are cached for one day and retained
as a fallback during outages. Plain and synchronized lyrics are both supported.
LRC parsing handles repeated timestamps, empty cues and offset tags. Word-timed
provider formats are not currently imported.

`alignment_engine.py` resamples complete vocals to 16 kHz mono. WhisperX recognizes
the recording, then aligns that recognized text acoustically. This analysis is
cached by audio fingerprint, model, language, device and algorithm version.

`alignment_match.py` matches the supplied lyric token sequence to the recognized
sequence in order. Missing tokens are skipped, not allocated proportionally.
Phrase anchors require actual token coverage and reject large internal gaps.
Word refinement is also compared against at least two sufficiently scored,
non-stalled recognized words. A displacement over 1.5 seconds triggers a retry
inside a narrower evidence-based window. Continued disagreement leaves the phrase
unresolved. Long sung words remain allowed; they do not independently pin retry
boundaries. This is a conservative check, not proof of perceptually exact timing.
The whole lyric sequence remains context when only selected lines are refined,
so repeated choruses retain their occurrence. Ambiguous repetitions are flagged.

Online timestamps are broader search hints. Their lyric tokens are reconciled
across different line wrapping. Acceptance requires at least three acoustic
anchors, 80% agreement within 1.5 seconds of a median offset, and corroboration
spanning at least 45% of the song. Local evidence wins at an anchored line;
accepted online cues fill gaps. Conflicting lines are omitted. Nonempty cues
beyond the recording, invalid times and out-of-order cues reject the sheet.
A single short gap between two anchors may be refined, but remains flagged for
listening review. Multiple missing phrases are never spread across a gap.

WhisperX refines words inside each phrase window. Missing/invalid boundaries,
nonfinite scores or confidence below 0.1 leave that word unresolved. Confidence
below 0.3, words under 40 ms, overlaps and long internal gaps need review. These
are heuristics, not calibrated accuracy probabilities. A per-phrase refinement
failure retains that phrase's text and does not discard other phrases.

## Storage and application

- `Timings.alignment` is an additive version-1 sidecar: full canonical words,
  nullable proposals, phrase windows, source and model details, provider choice,
  review reasons and recognition-cache identity. Old timing files still load.
  Sidecar words and boundaries are validated on import.
- `Project.alignment` stores entries keyed by stable line IDs with word membership.
  `effective_timing()` remains the only timing resolver; project timing stays in
  integer milliseconds. Draft phrase windows never become synthetic word times.
- `phrase_project.py` checks saved audio hashes, retains full-song context, emits
  identity-bearing result artifacts and applies proposals by line/word IDs.
  Changed lyric membership or a stale project revision rejects application.
  Manual resolved edits remain authoritative; the original model output remains
  immutable. Replacing poor automatic timings may deliberately reveal unresolved
  words. Use **Fill only untimed words** to keep existing automatic proposals too.
- Candidate adoption and timing application use the existing command history.
  Model caches and generated audio assets are reusable files outside undo state.
  Word-timing changes mark dependent mix work stale through existing hashes.
- If generation's timing model fails, the CLI continues saving separated audio,
  the draft mix and every source lyric as unresolved timing. The editor exposes
  the failure and a retry path. SOFA remains an explicit legacy CLI adapter;
  the new saved-project matching workflow uses WhisperX.

## Verification and limits

Automated checks cover missing verses, dropped words, repeated occurrences,
selective matching, cached recognition, manual-boundary repair without ASR,
wrong-recording rejection, lookup outages, import validation, per-line failure,
save-after-model-failure, stable IDs, manual edits, undo/redo and plain draft
preview. Streamlit AppTest exercises lookup adoption and non-mutating audition.
Real browser checks are recorded in BUILD-STATUS.md.

The owner's Frost Children recording was tested through an independent project
copy. LRCLIB result 25227215 advertises 152.48 seconds but contains sung cues as
late as 176.02 seconds (plus an empty cue at 179.70). The source audio is 152.50
seconds. The sheet is rejected with an explicit recording-length explanation.
The local run supplies 209 of 266 word proposals and flags 30 of 38 lines for
review. That count measures proposal coverage, **not timing accuracy**. No manual
ground-truth timing benchmark has been completed, and repeated choruses still
need human review. The original project was not overwritten.

This implementation does not change the lead/backing model's whole-song RMS
assignment or claim to eliminate residual vocals. Separation quality and timing
quality are distinct; complete-vocal matching prevents backing-assigned words
from being excluded from recognition. Singing-specific model evaluation, held
note endpoint accuracy and a broader annotated song benchmark remain follow-up
work. Do not downgrade the existing CUDA environment to install another aligner.

Reproduce a real-audio run into a **new** folder:

```powershell
.venv\Scripts\python.exe scripts/timing_proof.py SOURCE_PROJECT NEW_COPY_FOLDER
# Optional third argument: saved lookup candidate JSON or lookup-result JSON.
```

Provider interface reference: [LRCLIB architecture](https://github.com/tranxuanthang/lrclib/blob/main/ARCHITECTURE.md).
