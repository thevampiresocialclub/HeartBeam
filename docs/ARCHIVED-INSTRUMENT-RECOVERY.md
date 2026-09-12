# Instrument recovery — parked 12 September 2026

The owner listened to the MP3 comparisons and heard little difference. The
selected current-separation passages already sounded acceptable. We have not
demonstrated a perceptually useful repair, and a numerical volume dip alone is
not a reason to interrupt editing or change the audio. This feedback concerns
the supplied examples; it does not establish detector accuracy across all music.

The owner requested archiving the technique, rolling back the feature, and
retaining useful fixes. **Do not resume the recovery roadmap automatically.**
Revisit it only for a clearly audible problem and an explicit new request.

## Active behavior

Prepare Audio → Review Timing → Edit Video → Export. Automatic thin-spot scanning,
the separate Music Repair step, and offline consensus/donor-screening code have
been removed from the active source. Old repair-page sessions resume in the
editor. Old suggestion records are retained for compatibility, but neither
display review warnings nor gate export, and they never alter audio.

These useful pieces remain:

- Common-gain calibration of the full separated partition, without independently
  normalizing stems and disrupting their relative balance.
- Optional manual passage lifts under **Vocals → Instrumental volume**, with
  persistent drafts, Apply/Undo, source checks and smooth edges.
- The same effective instrumental for solo audition, combined preview and export;
  legacy incompatible mixes cannot silently ignore an applied adjustment.
- Schema-1 migration/backup and schema-2 reading/writing. Existing saved
  adjustments keep their effect and can be disabled; no owner project is rewritten.
- The reusable MP3 comparison utility and its encode/decode, loudness and clipping
  checks. Continue supplying openable MP3 comparisons for future audio work.
- Earlier timing warnings, independent vocal controls, Firefox playback fixes,
  and resilient export progress handling.

The fixes to experimental vocal-amplification and donor screening remain in the
archive with their tests. They are not carried as dormant runtime code.

## Recoverable archive

Permanent local folder:
`C:/Users/young/Documents/Codex/HeartBeam-Archives/instrument-recovery-2026-09-12/`

- `README.md`: owner verdict, retained fixes, restoration instructions and limits.
- `heartbeam-experiment.bundle`: standalone Git history, verified as complete.
- `source-02c1543.zip`: ordinary source snapshot including experiment and tests.
- `research-audio-and-test-evidence.zip`: all 1,962 files from the research,
  listening and three acceptance/evaluation folders, including the 66 current
  comparison MP3s. Every archived file was read back and SHA-256 checked.
- `snapshot-files.json` and `SHA256.json`: per-file and package integrity records.

The source checkpoint is `02c15437f1bf029ba165dcf1391cf911fa90e80b`, pinned by
`archive/instrument-recovery-2026-09-12`. Rollback is a new forward commit; it
does not reset or erase the experiment's history. Work in a separate checkout
when revisiting the technique rather than restoring it over the active app.

## Lessons to keep

The energy detector can flag legitimate musical rests; its selected examples
were not compelling to the listener. Establish an audible defect first and
compare at matched loudness. Treat listening preference separately from signal
metrics. A louder donor does not prove restoration or absence of vocals.

Small common vocal residue must not authorize a large transfer. Calibration
errors and excerpt context can also change apparent results substantially.
The conservative donor screen rejects weak residue in controlled tones, but
abstained on these real songs and fails if both models misclassify an entire
voice. A second pass with the same model is not independent verification.

Future trials need named audible defects, intact-arrangement controls and
recorded ground truth. Generative reconstruction is not justified merely by
finding a volume dip. Never replace a musical-quality gate with passing tests.
