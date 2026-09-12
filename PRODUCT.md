# HeartBeam product context

## Register

product

## Users and purpose

The owner creates karaoke videos on a Windows desktop. They want to paste and
edit lyrics in the application, correct word timing, place text on screen,
select fonts and highlight/outline colours, and control the remaining vocal
level by lyric section. This scope is confirmed in the existing build program
and the owner's request to continue HANDOFF.md.

## Current task

P03 timing/playback/review, P04 section vocals, P05 visual lyric placement and
styling, and P06 dependable preview/export are implemented. Preserve the existing
Streamlit shell, single audio clock, shared command history, presentation compiler
and immutable export-job path. The current editor supports 2–4 visible lyric lines
and playback controls for reviewing timing, highlighting, font and placement.
The current phrase sits on top, with upcoming phrases below rising into place
when it finishes. Letter spacing and line height are editable. Missing word
timings are estimated from surrounding words or a valid phrase window by default,
with visible labels and an opt-out. Raw model data and manual timings stay intact.
Entirely unanchored phrases still need a rough window before they can highlight.
Preparation, timing review, video editing, optional music repair and export are
separate pages. Preparation
saves the separated tracks and timing proposals; the removal mix waits for the
user's explicit **Build karaoke and continue** action. A named project can be
saved before review. Individual word approval is optional: unresolved words and
conflicts warn. New builds mix saved instrumental, lead and backing tracks, so
missing lyric timing does not switch vocals back on. Lead and backing each have
a 0–100% slider with 1% steps; lyric regions override the lead default only.
Preview, current MP3/WAV downloads and video export share those settings.
Video export warns about estimated, missing, overlapping and out-of-range timings
and continues with the available preview timing. Remaining untimed words stay
plain inside known lyric/display windows; wholly unanchored lines are omitted
with warnings. Timing approval is not required to render the saved audio mix.
Never present estimated timing as an acoustic match or automatic user approval. Lyric, timing,
phrase-window or linked-source changes invalidate that build approval. The desktop editor is a workstation with
playback, video and waveform on the left and independently scrolling lyric,
appearance, timing, vocal and music-repair controls on the right. Export has its
own final page. Play must be visible
at the top and all preview surfaces must follow the same audio clock.
The waveform is the song-position control: click or drag to seek without
changing lyric timing. Its playhead follows playback, including when zoomed,
and ordinary timing edits and undo preserve the player's position and state.
Lyric timing has two sources: optional LRCLIB lookup, checked against the actual
recording, and local matching against complete vocals. Match sung phrases before
words. Missing or ambiguous words stay visible for review. A user can bound and
loop one phrase, retry selected lines, and keep manual timing corrections. The
number of lyric rows on screen remains a presentation setting. Model failure
must not discard completed separation or lyric text.
P07 R0 and the first R1 pass add calibrated stem gain, one mastering policy, a
CPU thin-spot scan and explicit local level repair. The experimental R2
recorded-component reallocation remains outside the product until listening
tests show musical improvement without returned vocals.
Read BUILD-STATUS.md for the current verification record.

## Product character and principles

Direct, practical, candid. Familiar controls and precise feedback serve repeated
editing. Text input should not require creating an external file. Timing and
selection use stable IDs and integer milliseconds. Manual edits must survive
save/reopen. Ordinary playback and selection must not dirty the project or run
ML. Show missing assets and errors clearly. Never label unverified behavior as
verified.

## Boundaries

Avoid decorative redesign, a second playback clock, silent retiming, and claims
of perfect vocal separation. Keep the model sweep parked for P07. Treat the
existing roadmap and shared contract as the source of feature scope; no new
marketing identity is implied by this context file.

## Accessibility and inclusion

Retain native labels, keyboard focus, numeric alternatives and meaningful
disabled-control explanations. Playback shortcuts must not consume text input
or native control keyboard actions. Highlight state must also be identifiable
from selection text and labels. No formal accessibility compliance claim has
been verified.
