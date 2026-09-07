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
Separation and editing are separate pages. Completed separation offers a named
project save followed by video editing. The desktop editor is a workstation with
playback, video and waveform on the left and independently scrolling lyric,
appearance, timing, vocal and export controls on the right. Play must be visible
at the top and all preview surfaces must follow the same audio clock.
Lyric timing has two sources: optional LRCLIB lookup, checked against the actual
recording, and local matching against complete vocals. Match sung phrases before
words. Missing or ambiguous words stay visible for review. A user can bound and
loop one phrase, retry selected lines, and keep manual timing corrections. The
number of lyric rows on screen remains a presentation setting. Model failure
must not discard completed separation or lyric text.
P07 covers broader controlled audio-quality/model evaluation.
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
