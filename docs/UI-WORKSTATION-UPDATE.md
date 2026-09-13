# Workstation UI update

## Plan and acceptance criteria

1. **File menu.** Replace the Project sidebar with a File popover in the top bar.
   Keep open, save, save a copy, close, import and relink available. Show the
   current project and save state without a permanent sidebar.
2. **Prepare from top to bottom.** Put single audio and optional lyric uploads
   together, followed by title/artist, online search and its small Options menu,
   then the editable lyrics. Search results and adoption appear in a dialog.
   Put progress and Tracks are ready directly below Prepare audio and match
   lyrics. Put genre (Pop) and Advanced options below that. Use automatic device
   selection, retaining the engine's GPU memory checks.
3. **Use the editing space.** Remove the repeated preview heading and tutorial.
   Match Play to Restart, preserve one playback clock, and size the preview to
   both its aspect ratio and available viewport height. Keep a three-row lyric
   selector above independently scrolling settings. Stack panes on narrow screens.
4. **Name exports.** Default to the input filename plus `_karaoke.mp4`. Offer a
   custom name beside Render video. Retain immutable export folders, old exports
   and recovery after reopening. Reject paths and invalid filenames.
5. **Separate app and user data.** Keep new preparation sessions and saved
   projects in a documented user-data folder, outside the app and system temp.
   Preserve existing projects and model caches. Document what to distribute and
   what to back up; never bundle private songs or test output in the app package.

## Build boundaries

Preserve stable IDs, integer timing, estimates, undo, the shared preview/export
compiler, and lead/backing mixing. The instrument recovery experiment stays
archived. This change does not replace the separator or alter audio processing.

## Verification

- Automated: search adopts only on explicit choice; replacing a lyric upload
  works without overwriting later edits; File actions preserve project data;
  export default/custom names survive rendering and reopening; invalid names
  cannot escape an export folder; user folders do not depend on the app cwd.
- Browser: prepare layout and search dialog; desktop and narrow/zoom-sized
  workstations; exactly three lyric rows; settings scroll while lyrics stay put;
  preview aspect ratios; play/pause, waveform seeking and word selection.
- Regression: run the Python suite and browser-independent JavaScript tests.
  State explicitly which browsers were actually exercised.

## Verification record

Implemented 12 September 2026.

- Full Python suite: **372 passed in 29.77 seconds**. The final targeted GUI,
  file and export run also passed 50 checks before the last full run.
- JavaScript: **28 passed**, covering playback, seeking, placement, shared
  control mounting and aspect/pixel-density-aware preview sizing.
- Live in-app Chromium browser: File open and save-copy, search status dialog,
  timing and video pages, word selection, waveform seek, custom full video
  render and its matching download filename. A waveform click put both clocks
  at 12,000 ms; selecting a word put both at 8,300 ms. Next-line navigation
  scrolled the lyric selector to the next three rows without increasing height.
- At 1280×720 both panes ended at y=708. Settings scrolled 424 px while the
  inspector remained at y=148.78 and the settings top at y=292.71. Lyric rows
  measured 36 px each inside a 108 px window.
- Responsive checks: 1600×900 (preview expanded to 646×363.38), 1050×650
  (preview shrank to 202×113.63 and both panes stayed within y=638), and
  768×900 (stacked panes, no document-width overflow). Viewport override reset.
- CUDA confirmed: torch 2.8.0+cu128, RTX 5070, 11.9 GiB total device memory.
  No separator/model-quality claim is made by this UI update.
- Local wheel built successfully; its 72 entries include the editor CSS/JS
  and renderer WASM, with no user audio/video, tests, virtualenv or bytecode.
- Firefox was **not** exercised in this pass. Native browser zoom was not driven;
  smaller viewports and pixel-density logic were checked. A clean-machine Inno
  installer/upgrade/uninstall run remains required before distribution.

The existing font/theme conventions are retained. See
`FILES-AND-DISTRIBUTION.md` for user storage and packaging boundaries. The
instrument recovery archive remains untouched.

## Compact workspace revision, 12 September 2026

The desktop workflow title, File menu and four stages now occupy the existing
60 px Streamlit header band beside Deploy. Below 1000 px they return to normal
document flow so the controls can wrap without colliding. Phrase, Listen to and
Speed share one responsive row above the preview. The waveform retains separate
waveform and timing-edit lanes at 112 px total height, down from 150 px. The
three-row lyric selector remains three rows but uses 28 px rows, reducing its
window from 108 px to 84 px.

Headless Chrome at 1500×900 measured the workflow at y=5.6–46.4 inside the
60 px header, ending 13 px before Deploy. The reclaimed workspace produced a
789×443.8 preview, with all three playback options aligned at y=153. The
waveform and lyric selector measured 112 px and 84 px. At 760×900 the panes
stacked without horizontal overflow. Real pointer clicks still sought through
the shortened waveform and compact lyric selector. The focused Python workflow
suite passed 57 tests and the JavaScript suite passed all 29 tests.
