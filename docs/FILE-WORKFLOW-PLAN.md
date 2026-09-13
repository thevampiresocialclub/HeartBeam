# HeartBeam file workflow update

Owner request, 13 September 2026. Sol implements; Astra reviews and verifies.

## Intended experience

- Sessions have integer folder names (`1`, `2`, `3`) and display as `Session 1 · Song name`. Preserve internal project/word/line IDs.
- File exposes Open, Save, Save as and Close. Open offers named projects and prepared sessions with human labels; Browse opens the Windows project-file picker. Advanced path input remains available for recovery and older locations.
- Save writes the current project. Save as accepts a project name and defaults to `Documents/HeartBeam/Projects/Song name`, using `Song name (2)` for an existing destination. No overwrite of another project. Saving a copy preserves the existing portable-copy semantics.
- New preparation sessions keep their project manifest directly in `Documents/HeartBeam/Sessions/1`; processing output can remain in its `out` subfolder. The app saves automatically after preparation. Continuing to timing review does not require typing a folder path or making a redundant copy. File > Save as creates a named copy when wanted.
- File has direct buttons for Sessions, Projects and the current project folder. It never deletes files itself. Opening Sessions enables the owner to manage them in Explorer.
- A compact Tracks menu is available next to File whenever a project has tracks. Offer instrumental, lead vocals, backing vocals, complete vocals and original as applicable, with reveal/download for a chosen existing asset and an Open tracks folder button. Do not add a second playback clock.
- Export completion clearly names the video and provides Show video in folder beside Download. Reopened projects keep a working reveal action. Keep immutable export-job output and snapshots intact; users no longer need to navigate those internal folders manually.
- The header uses compact content-width controls grouped on the left, aligned on one center line with consistent height. Preserve the preview workspace and native keyboard focus. At narrower widths wrap predictably without overlaps.

## Storage and compatibility

All new defaults use the existing Documents/HeartBeam root (including redirected Documents and HEARTBEAM_DATA_ROOT). Sessions contain numbered working projects; Projects contain named copies. Assets, timing edits and exports belong to their project. No automatic migration, renaming or deletion of older folders. Discover old `session/out/project` layouts as well as new direct session manifests. Accept a project folder or its project.json when opening.

Use atomic session directory reservation and durable sequence state so concurrent starts cannot collide and deleting a session does not casually recycle its number. Allocate names without changing working directories or invoking a shell. Invalid/missing locations produce actionable messages. Folder actions run only on an explicit button click. Browse may be unsupported on a non-desktop host; preserve the manual-path fallback. Keep write leases, autosave recovery, stable IDs, dirty state and conflict checks.

## Build responsibilities

Sol owns application changes, tests, and updates to README / FILES-AND-DISTRIBUTION. Expected touch points: paths.py, gui.py, workstation.css, project_video_ui.py, a small desktop helper, and relevant file/project/export tests. Root owns this plan and final BUILD-STATUS / HANDOFF evidence. No ML, timing algorithm, mixer or export-encoder changes are needed.

## Verification

1. Focused tests: concurrent/non-reused session allocation, old/new discovery, safe names and collisions, Save/Save as identity and state, moved portable assets, missing/corrupt folders, desktop helper arguments/errors, exact completed-export reveal target.
2. Existing Python regression suite and JavaScript component suite after implementation.
3. Browser: header at desktop and narrow widths, File menu with no project and loaded project, Open/Save/Save as, Tracks, completed export button. Confirm no second playback control or rerun loop.
4. Use isolated data/test projects. Never rerun ML or change the owner's open projects just to test these controls.
5. Review changes, integrate the tested code into the original checkout and provide the updated app plus verification limits.

## Delivery evidence — 13 September 2026

Implemented by Sol and reviewed by Astra. Final checks: **405 Python tests and
29 JavaScript tests passed**. The browser opened named, numbered and legacy
projects, created a collision-safe copy with its own identity and audio, and
saved an appearance edit through Save and close. The Tracks menu selected the
saved lead stem. A new four-second 640x360 H.264/AAC render completed and exposed
the saved filename and folder action; reopened projects also exposed prior exports.

The desktop header's title and button centers agree within 0.01 px at 1440 px;
866 px and 480 px were checked without horizontal page overflow. Browser errors
were absent during these checks. Test data stayed in the isolated
`heartbeam-file-ui-proof` workspace, outside the repository and the owner's songs.
Native Explorer/picker interaction and Firefox were not visually retested;
automated desktop-helper tests verify exact arguments, missing paths and Unicode
picker output. Real project discovery also exposed redundant long labels in old
folders; these now show a compact distinguishing suffix while retaining the
original paths. No ML/timing algorithm or mix changes belong to this update.
