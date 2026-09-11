# Presentation contract (P05)

`presentation.compile_project(project, duration_ms, root, draft=False)` is the
single project presentation compiler. `project_preview.preview_payload` serves
its ASS and concrete fonts to browser libass. `presentation.render_project`
freezes the same output, fonts and background for native FFmpeg. The older CLI
still accepts legacy timings/TOML; importing TOML into a project converts it once.

## Saved data

Version-1 projects remain readable. `Presentation` adds optional `fonts` and
`presets` collections to the existing design canvas, `song_style` and
`line_overrides` fields. Empty defaults resolve to Noto Sans, 72 units, bold,
white unsung/gold sung, black outline 3 and shadow 2, bottom center with a
horizontal margin of 60 and vertical margin of 80. The canvas is 1920 × 1080.

Style groups and supported fields:

| Group | Fields |
|---|---|
| `font` | `family`, `size_px`, `bold`, `italic`, `letter_spacing_px` (−10 to 40, default 0), `line_height` (1 to 4, default 1.4) |
| `colour` | `primary` (unsung), `highlight` (sung), `outline`, `shadow`; all `#RRGGBB` |
| `box` | `x`, `y`, `width_px`, `anchor`, `alignment`, `wrap`, `outline_px`, `shadow_px`, legacy `position`, `margin_h_px`, `margin_v_px` |
| `highlight` | `mode`: `word` or `sweep` |
| `background` | `kind`: `solid`, `image`, `video`; `value` for colour/legacy path, `asset_id` for project media |
| `video` | `resolution`, `fps`, `codec`, `crf`, `audio_bitrate` |

Only absent keys inherit. Zero and false are real overrides; null is not an
inheritance marker. Line overrides are keyed by stable line ID and can contain
the four text groups (`font`, `colour`, `box`, `highlight`) plus `break_before`,
a list of word IDs beginning new display rows. Background/output settings are
song-wide. Word `display_text` remains separate from sung text and timing.

Example line exception:

```json
{
  "line_abc": {
    "box": {"x": 960, "y": 700, "outline_px": 0},
    "colour": {"highlight": "#F2AAC8"},
    "highlight": {"mode": "sweep"},
    "break_before": ["w_second_row"]
  }
}
```

The inspector writes only changed fields. Editing a line's colour must not
freeze its inherited font or position. Reset removes the line's exception,
including its explicit wrapping. Preset application replaces song text defaults
while retaining line exceptions and any background/output settings not supplied
by the preset. Every application/reset/drag is one shared History command.

## Geometry and timing

Coordinates, widths, font sizes, outline and shadow distances use design units.
The anchor is one of the nine combinations of `top/center/bottom` and
`left/center/right`. It places the full lyric stack at X/Y. Horizontal text
alignment is independent: it places left/center/right-aligned text within the
chosen width. `lyric_scene.py` measures explicit breaks or wraps to that width
using the resolved font and letter spacing. Each physical row gets an ASS event
with `\q2`, so preview and export use the same wrapping. Row pitch is font size
times `line_height`; letter spacing feeds ASS's Spacing field.

“Place inside margins” derives X/Y and width from the chosen anchor/margins.
Other placement actions store explicit coordinates. CSS-scaled dragging converts
pointer deltas back to design units and sends one command on release. Keyboard
arrows on a handle change placement, never word timing. Five-percent safe-area
guides, labels and handles exist only in the browser DOM.

ASS PlayRes remains the design canvas at every output size.
`ScaledBorderAndShadow: yes` scales the outline with the text. Exports must share
the canvas aspect ratio; the UI offers 1280×720, 1920×1080 and 3840×2160.

The compiler uses `effective_timing()` through shared timing validation.
Display windows may extend beyond words; they do not alter audio or vocal
regions. GUI exports use `allow_timing_issues=True`: missing/conflicting/out-of-range
timing, stale timing approval and invalid display windows produce warnings rather
than blocking encoding. Labelled estimates use the shared word/sweep highlighting
path. Raw model/manual timings are preserved. Untimed words stay plain in a known
word/phrase window, or an authored display window. Fully unanchored lines are
omitted with warnings. Invalid display windows fall back to available lyric timing.
Font/glyph, background and audio-integrity validation stay strict. Low-level
compiler/render APIs retain strict defaults for callers needing validation.
Passage exports preserve plain words in intersecting lyric windows, shift phrase
anchors to clip time, and freeze estimates before cropping away their neighbors.
Absolute millisecond boundaries are rounded once to ASS centiseconds (10 ms).
`\kt` sets each word's onset relative to its event; `\k` switches a word at onset
and `\kf` sweeps during its duration. This keeps gaps, overlaps and continuing
sweeps correct when movement splits a line into events. Negative onsets preserve
already-started words in later segments. Completed words retain the sung colour.
A third active-word colour is outside P05.

Display scheduling accepts 2, 3 or 4 logical phrases, each potentially wrapped.
The current phrase is on top and future phrases appear below. The tallest phrase
determines a fixed slot height, preserving the top position even at the song's
end. When the current phrase's last sung word ends, the next phrase rises by one
slot; a new phrase enters below while the outgoing phrase rises and fades out.
`transition_ms` defaults to 220 and accepts 0–1000; zero disables movement.
Overlapping phrases keep independent word highlights even before promotion.
Browser placement handles follow the compiled movement segments.

The automatic lead controls the first stack's entrance and hold controls the
last stack's exit. Intermediate stacks remain visible across gaps and promote
at sung phrase ends. Manual display windows are validated for compatibility;
the rolling scene uses the first start and last end. Legacy `show_upcoming` and
signed `upcoming_offset_y` fields remain readable but no longer control the
rolling layout. The editor's previous/next lyric buttons seek display boundaries;
selecting a line in the dropdown or review list seeks its singing/phrase start.

Literal braces use libass's brace escapes. Literal backslashes receive a
zero-width WORD JOINER so `\N`, `\n`, and `\h` in authored text remain visible
text. Authored words never become ASS override instructions.

## Font and background assets

Added font/background files live under `assets/<role>/<sha256>.<extension>`.
Assets retain IDs and hashes; replacement does not overwrite bytes still needed
by undo/recovery. Font records contain `asset_id`, actual `family`, `bold` and
`italic`, read with fontTools. The UI can import static TTF/OTF or copy matching
installed faces. Variable fonts and collections require a static face first.

Every requested font face resolves to a concrete file. An absent/changed face
produces a visible warning and resolves to the corresponding bundled Noto Sans
face for both renderers. Relink or reimport restores it. A font lacking required
characters warns in preview and blocks final export, avoiding hidden native-only
fallbacks. Bundled faces and licenses are documented in `editor_assets/vendor`.

New backgrounds are copied into project assets. Old saved external paths still
resolve for compatibility. Missing/changed backgrounds use a reported solid
placeholder in preview and block export. Image/video backgrounds use a centered
cover crop. The browser video remains paused and samples frames from the single
AudioContext song clock modulo its duration. It has no independent running clock
and is always muted. Native export explicitly maps the karaoke audio stream.

Presets have `format="heartbeam-style"`, `version=1`, `name`, and `defaults`.
They may contain the four text groups and a solid background. They contain no
lyric IDs, timings, vocal settings, media paths, font files, or output jobs.
Named presets persist in the project; download/upload reuses them across songs.
Font family references resolve against the receiving project's available faces.

## Invalidation and continuation

Visual edits change the content revision and make older video snapshots stale.
They do not change effective timing, rebuild stems/clean audio, move vocal
regions, or invalidate the content-addressed final mix. Browser mix preparation
ignores presentation-only revision changes when its audio/template inputs match.
Selection and guides are transient and do not dirty the manifest.

Lyric edits match line identity by surviving word membership. Split children
inherit their source appearance, and one retains its ID. Merges retain the
largest source line's style and report conflicting styles; Undo restores both.
Break references are filtered to surviving words. Completely replaced lines
without surviving words start from song defaults.

Exports retain `project-snapshot.json`, `presentation.json`, `lyrics.ass`, exact
font files, a copied background, warnings and effective `timings.json` (the GUI
adapter writes timing JSON). P06's background jobs call this exact path from a
deep-copied project revision. `export-manifest.json` records the source revision,
audio hash, asset IDs/hashes, export kind and optional passage range.

## Verification and limits

`tests/test_presentation.py`, the P05 GUI tests and `tests/presentation.test.mjs`
cover inheritance, zero overrides, stable line styles, preset portability,
fonts, undo/stale commands, display literals, audio independence, real native
highlight pixels, three-size placement and quoted Windows project folders.
`scripts/p05_proof.py <new-output-folder> --render [--background]` builds an
eight-second original lyric/audio fixture and native videos/frames at all three
sizes, suitable for a real browser comparison. No ML or downloaded song is used.

Guides/overflow warnings use font metrics and are estimates; libass renders the
actual text. Automatic shrinking is never applied. Browser/native decoding,
colour management and rasterization are not claimed pixel-identical. Video
background preview requires a browser-supported codec (H.264 MP4 is verified).
Registered media remains in Streamlit RAM and audio uses decoded whole buffers.
Undo is session-local; Save persists content. Export jobs survive ordinary editor
reruns; a process exit labels an unfinished saved job as interrupted. Refer to
BUILD-STATUS.md for the measured verification record.

Primary references: [ASS tags](https://aegisub.org/docs/latest/ass_tags/),
[libass parsing](https://github.com/libass/libass/blob/master/libass/ass_parse.c),
[fontTools TTFont](https://fonttools.readthedocs.io/en/latest/ttLib/ttFont.html),
[browser libass](https://github.com/libass/JavascriptSubtitlesOctopus).
