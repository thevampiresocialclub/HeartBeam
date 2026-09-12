# Files, projects and distribution

## User files

New GUI work uses the user's Documents folder (including Windows folder
redirection), under **HeartBeam**:

```text
Documents/HeartBeam/
  Projects/                   named projects created by Save project
    Song-name-project-id/
      project.json
      audio/                  copied audio and separated tracks
      assets/                 timing source, backgrounds and other assets
      cache/                  derived preview and mix files
      exports/
        jobs/                 recoverable export status
        rev-...-full-.../      one immutable render and its snapshot
          Song-name_karaoke.mp4
          export-manifest.json
  Sessions/                   durable preparation runs, including failed runs
    Song-name-random-id/
      uploaded song
      lyrics.txt
      out/project/            automatically saved when preparation completes
```

`File > File locations` shows the actual paths. `Save project and review timing`
copies a completed session into Projects by default; its folder field and
`File > Save a copy` accept a different location. Existing project folders are
not moved. Open older projects from File as before.

Set `HEARTBEAM_DATA_ROOT` before starting HeartBeam to put Projects and Sessions
under another folder or drive. This changes defaults for new work only.
Preparation sessions are retained across restart and OS temporary-file cleanup.
They are not auto-deleted: remove a session yourself after verifying its named
project has all the audio you need. A failed run keeps its partial files.

Back up the entire project folder, not only project.json. Copied project assets
move with the folder; externally linked assets still require their source files.
Exports are always inside their owning project. The filename next to Render
video starts with the original input basename plus `_karaoke.mp4`; it can be
edited. Passage renders append `_passage`. Rendering again creates a new folder
and keeps earlier videos. The browser download uses the same filename and your
browser's download-folder preference.

## Application and caches

- **Application:** installed Python package, editor JavaScript/CSS, bundled
  renderer assets and launchers. Never store user songs in the installation.
- **Models:** existing `~/.heartbeam/models`, or `HEARTBEAM_MODEL_ROOT`. Existing
  library-specific cache overrides remain supported. These large downloads are
  independent of project backups and app upgrades.
- **Online lyric cache:** existing `~/.heartbeam/lyrics-cache`; project-specific
  lookups can use the project's cache. This is separate from saved lyric edits.
- **Development:** tests, proof runs, archives, `.venv`, `.git` and `out/` belong
  to the development checkout and are not a portable app distribution.

These profile locations avoid Microsoft Store Python's LocalAppData cache
redirection for user work and model downloads. Uninstalling app files must leave
projects, sessions and model caches intact.

## Distribution route

Use the existing Inno Setup recipe in `installer/` for a Windows installer. It
ships application source and setup scripts; the target PC installs Python,
FFmpeg and dependencies. The GPU choice uses CUDA 12.8 wheels; the ordinary
setup path detects NVIDIA automatically. Model weights are downloaded separately.
For Python distribution, build a wheel from `pyproject.toml`. Package discovery
includes only `heartbeam*`; its package data includes the editor and renderer.

Before publishing an installer, build it and test on a clean Windows account:
install, launch, prepare a short song, save/reopen, render, upgrade, and uninstall.
Confirm that Documents/HeartBeam and model caches survive uninstall. Check the
first-run GPU/driver check and the explanation on unsupported hardware. An
installer is not release-verified by local UI or unit tests alone.
