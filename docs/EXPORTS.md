# Video export and recovery

HeartBeam exports the exact project revision shown when a job starts. Later edits
do not alter that job. The snapshot includes lyric timing and wording, appearance,
font files, background, vocal levels, selected audio hash and source asset hashes.

## Recommended workflow

After separation, choose **Save project and edit video**. Opened projects go
straight to this workstation. Playback and the waveform remain in the left pane;
the **Export** tab in the right pane contains the following rendering controls.

1. Save the project after editing lyrics, timing, placement and vocal levels.
2. Under **Lyric reading timing**, enable automatic scheduling and choose how
   early a phrase appears, the final hold, 2–4 visible lyric lines, and their
   vertical spacing. The current stack stays visible between non-overlapping
   phrases and hands off at one exact boundary. Actual overlapping vocals keep
   both highlights and are reported.
3. Use **Playback preview** to play/pause, restart, or jump between lyric display
   boundaries while checking the final timing, font, highlighting and placement.
4. Use **Render a short passage first** to encode up to 60 seconds with the final
   font, background, audio mix and encoder.
5. Choose **Render video**. Use **Refresh export status** to read encoded-media
   progress. **Cancel export** stops the current encode.
6. Download the completed MP4. If its revision is older than the editor, HeartBeam
   labels it as stale rather than implying it contains later edits.

## Files and recovery

Completed outputs live under `exports/rev-<revision>-<kind>-<job-id>/`. The MP4
appears there only after FFmpeg succeeds. A private `.job-<id>.tmp` directory is
removed after success, failure or cancellation. Cleanup targets that job only;
older output folders remain intact.

Each completed folder contains `karaoke.mp4`, `lyrics.ass`, `timings.json`,
`presentation.json`, `presentation-warnings.json`, `project-snapshot.json`,
`export-manifest.json`, and the exact font files used. Image/video backgrounds
are copied into the folder. Passage exports also retain their lossless clipped
audio so the result can be audited.

Job status is atomically saved under `exports/jobs/`. If the app process closes
during an export, the next session labels that job interrupted. Start it again;
the previous completed video remains available. Invalid timing, missing karaoke
audio, changed background assets, missing glyphs, uncalibrated vocal regions and
missing FFmpeg are checked before a job begins.

The legacy `heartbeam-video` command remains available for `karaoke.mp3` plus
`timings.json` workflows. Saved projects use the richer revision snapshot route.
