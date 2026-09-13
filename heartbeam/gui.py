"""Streamlit GUI for HeartBeam.

Runs the existing CLI in a subprocess so we don't have to refactor the engine.
Streams stdout into the UI, recognises milestone log lines for progress.

Launch:
    heartbeam-gui          # via entry point (see pyproject.toml)
    python -m heartbeam.gui  # equivalent

That opens http://localhost:8501 in your browser.
"""
from __future__ import annotations

import json
import hashlib
import html
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import streamlit as st

from heartbeam import editor as ed
from heartbeam import editor_media as em
from heartbeam import desktop
from heartbeam import lyrics as lyr
from heartbeam import project as prj
from heartbeam import editor_ui as ui
from heartbeam.project_lock import WriterLease
from heartbeam.models import PRESETS, PRIMARY_PRESETS, resolve_default
from heartbeam.style import toml_string
from heartbeam.paths import (new_session, projects_dir, reserve_project_dir,
                             session_project_dirs, sessions_dir,
                             suggested_project_dir, data_root)

# Milestone log-line patterns -> (progress 0-1, friendly label)
_MILESTONES: list[tuple[re.Pattern, float, str]] = [
    (re.compile(r"loading original audio"),               0.05, "Loading audio"),
    (re.compile(r"running source separation"),            0.10, "Source separation (slow)"),
    (re.compile(r"Pass 2 assignment by RMS"),             0.55, "Splitting lead vs. backing"),
    (re.compile(r"running.*forced alignment"),            0.65, "Aligning lyrics to audio"),
    (re.compile(r"alignment:\s+\d+\s+words"),             0.80, "Aligned"),
    (re.compile(r"building lyric mask"),                  0.83, "Building mask"),
    (re.compile(r"building energy mask"),                 0.86, "Building mask"),
    (re.compile(r"mask coverage:"),                       0.90, "Mask done"),
    (re.compile(r"mixing karaoke output"),                0.93, "Mixing karaoke"),
    (re.compile(r"loudness normalize"),                   0.97, "Loudness normalize"),
    (re.compile(r"wrote.*karaoke\.mp3"),                  0.99, "Wrote karaoke.mp3"),
    (re.compile(r"^Done\."),                              1.00, "Done"),
]


def _find_exe(name: str) -> str:
    """Locate a heartbeam console script.

    Falls back to the venv hosting THIS process, since the GUI runs inside it
    and its Scripts/ dir is not necessarily on PATH (Start Menu shortcuts do not
    activate the venv).
    """
    exe = shutil.which(name) or shutil.which(f"{name}.exe")
    if exe is None:
        exe = str(Path(sys.executable).with_name(f"{name}.exe"))
    return exe


def _write_style_toml(path: Path, *, font_size: int, text_colour: str,
                      highlight_colour: str, position: str, resolution: str,
                      background_kind: str, background_value: str) -> None:
    """Serialise the video controls into a style.toml heartbeam-video can read.

    Only the fields the GUI exposes are written; Style.from_toml fills the rest
    from its dataclass defaults, so a partial file is valid.

    Every string goes through toml_string(). Uploaded background paths are
    native Windows paths, and interpolating one raw into a quoted TOML string
    either fails to parse or silently corrupts the path (see toml_escape).
    """
    text_colour_t = toml_string(text_colour)
    highlight_colour_t = toml_string(highlight_colour)
    position_t = toml_string(position)
    background_kind_t = toml_string(background_kind)
    background_value_t = toml_string(background_value)
    resolution_t = toml_string(resolution)
    path.write_text(
f'''[font]
family = "Noto Sans"
size_px = {font_size}
bold    = true

[colour]
primary   = {text_colour_t}
highlight = {highlight_colour_t}

[box]
position = {position_t}

[background]
kind  = {background_kind_t}
value = {background_value_t}

[video]
resolution = {resolution_t}
''',
        encoding="utf-8",
    )


def _render_video(audio_path: Path, timings_path: Path, out_dir: Path,
                  style_path: Path, log_lines: list[str]) -> tuple[int, Path]:
    """Run Phase 2. Synchronous: rendering is seconds, not minutes.

    Phase 1 needs the background-thread-and-poll dance because it runs for tens
    of minutes; ffmpeg burning subtitles onto a solid background does not.

    The media paths are explicit because they no longer share a directory: a
    generation run keeps both in its output folder, while an opened project
    stores audio under audio/ and the imported timings under assets/.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    video_path = out_dir / "karaoke.mp4"
    cmd = [
        _find_exe("heartbeam-video"),
        str(audio_path),
        str(timings_path),
        "-o", str(video_path),
        "--style", str(style_path),
    ]
    log_lines.append(f"$ {' '.join(cmd)}\n")
    proc = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace",
    )
    log_lines.append(proc.stdout or "")
    return proc.returncode, video_path


def _run_heartbeam(
    song: Path, lyrics: Path, out_dir: Path,
    separator: str,
    align_device: str,
    extra_flags: list[str],
    log_lines: list[str], status_state: dict,
) -> int:
    """Subprocess heartbeam.exe, stream output into log_lines, update status_state."""
    exe = _find_exe("heartbeam")
    cmd = [
        exe,
        str(song), str(lyrics),
        "-o", str(out_dir),
        "--separator", separator,
        "--align-device", align_device,
        "--keep-stems",
        "-v",
    ] + extra_flags
    log_lines.append(f"$ {' '.join(cmd)}\n")
    # Everything below runs on a worker thread. Any escaping exception would
    # kill the thread silently, leaving status_state["done"] False forever and
    # the UI pinned on a progress bar that never finishes. Report the failure
    # through the same channel a non-zero exit uses, so the app stays usable.
    try:
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
        )
    except OSError as exc:
        log_lines.append(
            f"failed to launch {cmd[0]}: {type(exc).__name__}: {exc}\n"
            "The heartbeam executable could not be started. Check that the venv "
            "is intact and that scripts/install.ps1 completed.\n"
        )
        status_state["label"] = "Failed to start"
        status_state["returncode"] = -1
        status_state["done"] = True
        return -1

    try:
        for line in proc.stdout:  # type: ignore[union-attr]
            log_lines.append(line)
            for pat, pct, label in _MILESTONES:
                if pat.search(line):
                    status_state["progress"] = pct
                    status_state["label"] = label
                    break
        proc.wait()
        status_state["returncode"] = proc.returncode
        return proc.returncode
    except Exception as exc:  # noqa: BLE001 - must not strand the UI
        log_lines.append(f"worker error: {type(exc).__name__}: {exc}\n")
        status_state["label"] = "Failed"
        status_state["returncode"] = -1
        return -1
    finally:
        # Whatever happened, the UI must stop waiting.
        status_state["done"] = True


def _format_preset_summary(name: str) -> str:
    p = PRESETS[name]
    bits = [f"**{name}** — {p.description}"]
    pieces = []
    mix = resolve_default(p, "mix_strategy")
    pieces.append(f"mix={mix}")
    if mix == "subtract":
        pieces.append(f"gain={resolve_default(p, 'vocal_gain'):.2f}")
        boost = resolve_default(p, "backing_boost")
        if boost:
            pieces.append(f"boost={boost:.2f}")
    pieces.append(f"pad={resolve_default(p, 'pad_ms'):.0f}ms")
    pieces.append(f"xfade={resolve_default(p, 'crossfade_ms'):.0f}ms")
    pieces.append(f"merge={resolve_default(p, 'merge_gap_ms'):.0f}ms")
    pieces.append(f"energy={resolve_default(p, 'energy_threshold'):.2f}")
    lufs = resolve_default(p, "target_lufs")
    if lufs is not None:
        pieces.append(f"LUFS={lufs}")
    bits.append("  `" + "  ".join(pieces) + "`")
    return "\n".join(bits)


def _project_snapshot(project) -> str:
    """Comparable form of a project, ignoring fields that move on every save.

    Used only to decide whether to show "unsaved changes"; revision and
    modified_at advance on save and would make everything look permanently dirty.
    """
    d = project.to_dict()
    d.pop("modified_at", None)
    d.pop("revision", None)
    d.pop("command_ids", None)
    return json.dumps(d, sort_keys=True)


def _mark_saved(project) -> None:
    st.session_state.project_saved_snapshot = _project_snapshot(project)


def _is_dirty() -> bool:
    project = st.session_state.get("project")
    if project is None:
        return False
    return _project_snapshot(project) != st.session_state.get("project_saved_snapshot")


def _open_project(path: Path) -> tuple[bool, str]:
    """Load a project folder into session state. Returns (ok, message).

    A corrupt manifest falls back to the newest parseable autosave rather than
    failing outright: losing the last save is annoying, losing the song is not
    acceptable.
    """
    try:
        project = prj.load_project(path)
    except prj.ProjectError as exc:
        recovered = prj.recover_latest_autosave(path)
        if recovered is None:
            return False, f"Could not open: {exc}"
        st.session_state.project = recovered
        recovered._disk_hash = prj.file_sha256(path / prj.MANIFEST_NAME) if (path / prj.MANIFEST_NAME).exists() else None
        st.session_state.project_dir = path
        _activate_writer(path)
        _mark_saved(recovered)
        st.session_state.project_saved_snapshot = ""
        st.session_state.history_project = None
        from heartbeam.timing_review import approved
        st.session_state.workflow_step = "video" if approved(recovered) else "review"
        st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1
        return True, (
            f"{exc}. Recovered revision {recovered.revision} from autosave - "
            "save to make that recovery permanent."
        )
    st.session_state.project = project
    st.session_state.history_project = None
    st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1
    st.session_state.project_dir = path
    st.session_state[f"last_video_{project.id}"] = _latest_project_video(project, path)
    _activate_writer(path)
    _mark_saved(project)
    from heartbeam.timing_review import approved
    st.session_state.workflow_step = "video" if approved(project) else "review"
    return True, f"Opened '{project.name}' (revision {project.revision})"


def _latest_project_video(project, root):
    """Restore a completed export from its saved snapshot after reopening."""
    files = sorted((root / prj.EXPORTS_DIR).glob("rev-*/*.mp4"),
                   key=lambda p: p.stat().st_mtime_ns, reverse=True)
    for path in files:
        try:
            export_manifest = path.parent / "export-manifest.json"
            if export_manifest.exists() and json.loads(export_manifest.read_text(encoding="utf-8")).get("kind") != "full":
                continue
            snapshot = json.loads((path.parent / "project-snapshot.json").read_text(encoding="utf-8"))
            if snapshot.get("id") == project.id:
                return snapshot["revision"], str(path)
        except (OSError, ValueError, KeyError):
            continue
    return None


def _activate_writer(path):
    old = st.session_state.get("writer_lease")
    if old and st.session_state.get("writer_root") == str(path.resolve()):
        return
    if old:
        old.close()
    st.session_state.writer_lease = None
    st.session_state.writer_root = str(path.resolve())
    try:
        st.session_state.writer_lease = WriterLease(path)
        st.session_state.project_readonly = False
    except prj.ProjectError:
        st.session_state.project_readonly = True


def _project_media(project, project_dir: Path):
    """Resolve the karaoke audio and timings a project can render from.

    This is what lets an opened project reach the video controls without
    rerunning separation: both files are already on disk from the original run.
    """
    audio = None
    from heartbeam.timing_review import approved
    asset = project.asset_by_role("karaoke_audio") if approved(project) else None
    asset = asset or project.asset_by_role("original_audio")
    if asset is not None:
        candidate = asset.resolve(project_dir)
        if candidate.exists():
            audio = candidate
    timings = None
    if project.imported_timings_path:
        candidate = project_dir / project.imported_timings_path
        if candidate.exists():
            timings = candidate
    return audio, timings


def _adopt_run_into_project(out_dir: Path, song_name: str) -> bool:
    """Turn a finished generation run into a saved project.

    Imports the run's own timings.json rather than re-deriving it, so the
    aligner's proposal is preserved verbatim as the immutable original.
    """
    timings_json = out_dir / "timings.json"
    karaoke = out_dir / "karaoke.mp3"
    prepared = (out_dir / "timing-review-required.json").is_file()
    if not timings_json.exists() or (not prepared and not karaoke.exists()):
        st.session_state.project_message = f"Separation did not produce both audio and timings. Check the output folder: {out_dir}"
        return False
    # New sessions are working projects themselves: Sessions/1/project.json.
    # A bare output folder is still accepted for older runs and test fixtures.
    project_dir = out_dir.parent if out_dir.name.casefold() == "out" else out_dir
    try:
        project = prj.import_legacy_timings(
            project_dir, timings_json, karaoke if not prepared else None,
            name=song_name or "Untitled song", audio_role="karaoke_audio",
        )
    except (prj.ProjectError, OSError) as exc:
        st.session_state.project_message = f"Could not create project: {exc}"
        return False
    if prepared:
        project.alignment['review'] = {'required': True}
        prj.save_project(project, project_dir)
    if (out_dir / "cache" / "audio_cache.json").is_file():
        try:
            em.attach_cached_audio(project, project_dir, out_dir / "cache")
            prj.save_project(project, project_dir)
        except (OSError, prj.ProjectError) as exc:
            st.session_state.project_message = f"Project created; audition tracks were not linked: {exc}"
    st.session_state.project = project
    st.session_state.project_dir = project_dir
    _activate_writer(project_dir)
    _mark_saved(project)
    st.session_state.history_project = None
    st.session_state.separation_project_id = project.id
    return True


def _render_missing_assets(project, project_dir: Path) -> None:
    missing = prj.missing_assets(project, project_dir)
    if not missing:
        return
    st.warning("Missing files: " + ", ".join(
        f"{a.role} ({Path(a.path).name})" for a in missing))
    for a in missing:
        new_path = st.text_input(
            f"Relink {a.role}", key=f"relink_{a.id}",
            placeholder="full path to the file",
        )
        if st.button("Relink", key=f"relink_btn_{a.id}", disabled=st.session_state.get("project_readonly", False)):
            try:
                if not new_path:
                    raise prj.ProjectError("Enter the full path to the file first.")
                ui.history(project).execute(project, lambda p: prj.relink_asset(p, project_dir, a.id, new_path))
                st.success("Relinked.")
            except prj.ProjectError as exc:
                st.error(str(exc))


def _known_projects() -> list[tuple[str, Path]]:
    """Named copies first, then direct and legacy preparation sessions."""
    choices: list[tuple[str, Path]] = []
    root = projects_dir()
    try:
        folders = sorted(root.iterdir(), key=lambda p: p.name.casefold()) if root.is_dir() else []
    except OSError:
        folders = []
    for folder in folders:
        try:
            if not folder.is_dir() or not (folder / prj.MANIFEST_NAME).is_file():
                continue
            try:
                name = prj.load_project(folder).name
            except prj.ProjectError:
                name = folder.name
            detail = f" — {folder.name}" if name.casefold() != folder.name.casefold() else ""
            choices.append((f"Project · {name}{detail}", folder))
        except OSError:
            continue
    for number, folder in session_project_dirs():
        try:
            name = prj.load_project(folder).name
        except (prj.ProjectError, OSError):
            name = folder.name
        if number is not None:
            label = f"Session {number} · {name}"
        else:
            session_folder = folder.parents[1] if folder.parent.name.casefold() == "out" else folder
            label = f"Session · {name} — {session_folder.name}"
        choices.append((label, folder))
    return choices


def _open_from_file_control(path: Path, *, discard_dirty=False) -> tuple[bool, str]:
    path = path.expanduser().resolve()
    if path.name.casefold() == prj.MANIFEST_NAME:
        path = path.parent
    current = st.session_state.get("project_dir")
    if _is_dirty() and not discard_dirty:
        return False, "Save your changes first, or confirm that you want to discard them."
    if current is not None and path == Path(current).resolve() and not _is_dirty():
        return True, f"'{st.session_state.project.name}' is already open."
    return _open_project(path)


def _finish_open(path: Path, *, discard_dirty=False) -> None:
    ok, message = _open_from_file_control(path, discard_dirty=discard_dirty)
    if ok:
        st.session_state.project_message = message
        st.rerun()
    st.error(message)


@st.dialog("Open project")
def _open_project_dialog() -> None:
    choices = _known_projects()
    discard = False
    if _is_dirty():
        st.warning("The current project has unsaved changes.")
        discard = st.checkbox("Discard unsaved changes and open another project")
    if choices:
        chosen = st.selectbox("Projects and sessions", range(len(choices)), key="known_project",
                              format_func=lambda index: choices[index][0])
        if st.button("Open selected", type="primary", disabled=_is_dirty() and not discard,
                     key="open_known_project"):
            _finish_open(choices[chosen][1], discard_dirty=discard)
    else:
        st.caption("No saved projects or prepared sessions were found yet.")
    if st.button("Browse…", disabled=_is_dirty() and not discard, key="browse_project"):
        try:
            chosen_file = desktop.choose_project_file(projects_dir())
            if chosen_file:
                _finish_open(chosen_file, discard_dirty=discard)
        except desktop.DesktopError as exc:
            st.error(str(exc))
    with st.expander("Advanced path"):
        open_path = st.text_input("Project folder or project.json", key="dialog_open_project_path")
        if st.button("Open path", disabled=_is_dirty() and not discard, key="dialog_open_project_btn"):
            if not open_path:
                st.error("Enter a project folder or project.json path.")
            else:
                _finish_open(Path(open_path), discard_dirty=discard)


@st.dialog("Save as")
def _save_as_dialog() -> None:
    project = st.session_state.get("project")
    source = st.session_state.get("project_dir")
    if project is None or source is None:
        st.error("Open or prepare a project first.")
        return
    name = st.text_input("Project name", value=project.name, key="save_as_name")
    suggested = suggested_project_dir(name or project.name)
    st.caption(f"Default: Projects / {suggested.name}")
    with st.expander("Choose another folder"):
        custom = st.text_input("Custom empty folder", key="save_as_path",
                               placeholder="Leave blank to use Projects")
    if st.button("Save as", type="primary", key="save_as_btn"):
        try:
            copy, destination = _save_as_copy(project, source, name, custom)
            st.session_state.project = copy
            st.session_state.project_dir = destination
            _activate_writer(destination)
            _mark_saved(copy)
            st.session_state.project_message = f"Saved as '{copy.name}' in {destination}"
            st.rerun()
        except (OSError, prj.ProjectError) as exc:
            st.error(f"Could not save as: {exc}")


def _save_as_copy(project, source: Path, name: str,
                  custom: str = "") -> tuple[object, Path]:
    """Create the independent named copy used by the Save as dialog."""
    if not name.strip():
        raise prj.ProjectError("Enter a project name.")
    reserved = not custom.strip()
    destination = (Path(custom).expanduser().resolve() if custom.strip()
                   else reserve_project_dir(name))
    try:
        copy = prj.save_project_as(project, destination, src_dir=source)
        copy.name = name.strip()
        prj.save_project(copy, destination, bump=False)
        return copy, destination
    except BaseException:
        if reserved:
            try:
                destination.rmdir()
            except OSError:
                pass
        raise


@st.dialog("Unsaved changes")
def _close_project_dialog() -> None:
    st.warning("Save this project before closing, or explicitly discard the unsaved changes.")
    actions = st.columns(2)
    if actions[0].button("Save and close", type="primary", key="save_and_close"):
        try:
            prj.save_project(st.session_state.project, st.session_state.project_dir, bump=False)
            _mark_saved(st.session_state.project)
            _close_project()
        except (prj.ProjectError, OSError) as exc:
            st.error(str(exc))
    if actions[1].button("Discard and close", key="discard_and_close"):
        _close_project()


def _close_project() -> None:
    if st.session_state.get("writer_lease"):
        st.session_state.writer_lease.close()
    st.session_state.writer_lease = None
    st.session_state.project = None
    st.session_state.project_dir = None
    st.session_state.workflow_step = "separation"
    st.session_state.out_dir = None
    st.rerun()


def _open_folder_button(label: str, path: Path, key: str, *, create=False) -> None:
    if st.button(label, key=key):
        try:
            if create:
                path.mkdir(parents=True, exist_ok=True)
            desktop.open_folder(path)
        except (OSError, desktop.DesktopError) as exc:
            st.error(str(exc))


def _project_controls() -> None:
    """Compact File menu backed by durable project and session discovery."""
    with st.popover("File", width="content", disabled=st.session_state.get('running', False)):
        project = st.session_state.get("project")
        project_dir = st.session_state.get("project_dir")
        state = "unsaved changes" if _is_dirty() else "saved"
        if project is None:
            st.caption("No project open")
        else:
            st.markdown(f"**{project.name}**")
            st.caption(state.capitalize())
            if st.session_state.get("project_readonly"):
                st.info("Read only: another editor has this project open.")

        if st.button("Open…", key="file_open", use_container_width=True):
            _open_project_dialog()
        if st.button("Save", key="save_project", use_container_width=True,
                disabled=project is None or st.session_state.get("project_readonly", False)):
            try:
                prj.save_project(project, project_dir, bump=False)
                _mark_saved(project)
                st.success(f"Saved revision {project.revision}")
            except (prj.ProjectError, OSError) as exc:
                st.error(str(exc))
        if st.button("Save as…", key="file_save_as", use_container_width=True,
                     disabled=project is None):
            _save_as_dialog()
        if st.button("Close", key="close_project", use_container_width=True,
                     disabled=project is None):
            if _is_dirty():
                _close_project_dialog()
            else:
                _close_project()

        st.divider()
        locations = st.columns(2)
        with locations[0]:
            _open_folder_button("Sessions", sessions_dir(), "open_sessions_folder", create=True)
        with locations[1]:
            _open_folder_button("Projects", projects_dir(), "open_projects_folder", create=True)
        if project_dir is not None:
            _open_folder_button("Project folder", Path(project_dir), "open_current_folder")

        if project is not None:
            with st.expander("Project files and relinking"):
                st.caption(f"Revision {project.revision}")
                st.caption(str(project_dir))
                _render_missing_assets(project, project_dir)

        with st.expander("Advanced open and import"):
            open_path = st.text_input("Project folder or project.json", key="open_project_path",
                                      placeholder="full path for an older or recovered project")
            if st.button("Open path", key="open_project_btn"):
                if not open_path:
                    st.error("Enter a project folder or project.json path first.")
                else:
                    _finish_open(Path(open_path))
            st.divider()
            st.caption("Import existing timings and audio without rerunning separation.")
            t_path = st.text_input("timings.json", key="import_timings")
            a_path = st.text_input("karaoke audio (optional)", key="import_audio")
            d_path = st.text_input("new project folder", key="import_dest")
            discard_for_import = (not _is_dirty() or st.checkbox(
                "Discard current unsaved changes when importing", key="discard_for_import"))
            if st.button("Import", key="import_btn"):
                if not discard_for_import:
                    st.error("Save the current project, or confirm that its unsaved changes can be discarded.")
                elif not t_path or not d_path:
                    st.error("A timings.json and a destination folder are required.")
                else:
                    try:
                        imported = prj.import_legacy_timings(Path(d_path), Path(t_path),
                            Path(a_path) if a_path else None)
                        st.session_state.project = imported
                        st.session_state.project_dir = Path(d_path)
                        _activate_writer(Path(d_path))
                        _mark_saved(imported)
                        st.session_state.workflow_step = "video"
                        st.session_state.project_message = f"Imported '{imported.name}'"
                        st.rerun()
                    except prj.ProjectError as exc:
                        st.error(str(exc))

        message = st.session_state.pop("project_message", None)
        if message:
            st.info(message)


_TRACK_LABELS = {
    "instrumental_stem": "Instrumental",
    "lead_stem": "Lead vocals",
    "backing_stem": "Backing vocals",
    "vocals_stem": "Complete vocals",
    "original_audio": "Original",
}


def _available_tracks(project, root: Path) -> list[tuple[str, object, Path]]:
    result = []
    for role, label in _TRACK_LABELS.items():
        asset = project.asset_by_role(role)
        if asset is not None:
            path = asset.resolve(root)
            if path.is_file():
                result.append((label, asset, path))
    return result


def _track_controls(project, root: Path) -> None:
    tracks = _available_tracks(project, root)
    if not tracks:
        return
    with st.popover("Tracks", width="content"):
        labels = [label for label, _, _ in tracks]
        chosen = st.selectbox("Track", labels, label_visibility="collapsed",
                              key=f"chosen_track_{project.id}")
        label, asset, path = next(item for item in tracks if item[0] == chosen)
        st.caption(path.name)
        actions = st.columns(2)
        if actions[0].button("Show in folder", key=f"reveal_track_{asset.id}"):
            try:
                desktop.reveal_file(path)
            except desktop.DesktopError as exc:
                st.error(str(exc))
        actions[1].download_button("Download", lambda p=path: p.read_bytes(), path.name,
            mime="audio/wav", key=f"download_track_{asset.id}", on_click="ignore")
        _open_folder_button("Open tracks folder", root / prj.AUDIO_DIR,
                            f"open_tracks_folder_{project.id}")


def _lyrics_input(imported=None) -> str:
    """Lyrics text area, with optional .txt import.

    P02.1: typing or pasting must be enough. The file uploader stays as a
    convenience for people who already keep .txt files, and only seeds the box.
    The CLI still wants a path, but writing that temp file is our problem, not
    the user's.
    """
    fingerprint = (getattr(imported, 'file_id', None), hashlib.sha256(imported.getvalue()).hexdigest()) if imported is not None else None
    if imported is not None and fingerprint != st.session_state.get("lyrics_import_fingerprint"):
        try:
            st.session_state.lyrics_text = imported.getvalue().decode("utf-8")
        except UnicodeDecodeError:
            st.session_state.lyrics_text = imported.getvalue().decode(
                "latin-1", errors="replace")
    st.session_state.lyrics_import_fingerprint = fingerprint

    text = st.text_area(
        "One phrase per line", key="lyrics_text", height=220,
        placeholder=(
            "Paste the lyrics here, one sung phrase per line.\n\n"
            "Lines starting with # are section labels and are never sung:\n"
            "# Chorus"
        ),
    )
    lines, words = lyr.count_lyrics(text or "")
    if lines == 0:
        st.caption("No lyrics yet. Paste or type them above to enable generation.")
    else:
        st.caption(f"{lines} sung lines, {words} words")
    return text or ""


def _lyrics_editor(project, project_dir: Path) -> None:
    """Edit an open project's lyrics without losing timing (P02.2).

    Kept separate from the creation-time box: this one reconciles against
    existing word IDs and reports exactly what the edit cost.
    """
    stack = ui.history(project)
    from heartbeam.lyrics_lookup_ui import controls as lookup_controls
    candidate = lookup_controls(project.id, project.alignment.get('metadata', {'title': project.name}),
                                project_dir / 'cache' / 'lyrics')
    if candidate:
        st.session_state[f'lookup_pending_{project.id}'] = candidate
    pending = st.session_state.get(f'lookup_pending_{project.id}')
    if pending:
        st.caption('A lyrics result is ready. Choose whether to use its text or keep your current lyrics.')
        cols = st.columns(2)
        def adopt(p, replace_text):
            if replace_text:
                lyr.apply_lyrics_edit(p, pending['lyrics'])
            p.alignment['online_candidate'] = pending
            p.alignment['metadata'] = {k:pending[k] for k in ('title','artist','album','duration')}
        if cols[0].button('Use text and timing hints', key='adopt_online_text'):
            st.session_state.pop(f'lookup_pending_{project.id}', None)
            ui.change(project, lambda p: adopt(p, True))
        if cols[1].button('Keep my text; use timing hints', key='adopt_online_timing'):
            st.session_state.pop(f'lookup_pending_{project.id}', None)
            ui.change(project, lambda p: adopt(p, False))

    current = lyr.to_text(project)
    # Streamlit forbids writing st.session_state[key] once that widget exists,
    # so undo/redo cannot simply overwrite the box. Version the key instead:
    # bumping it retires the old widget and mounts a fresh one seeded from the
    # project, which is the supported way to push new content into a text area.
    version = st.session_state.setdefault("lyrics_editor_version", 0)
    key = f"lyrics_edit_{project.id}_{version}"

    edited = st.text_area(
        "Edit lyrics", value=current, key=key, height=240,
        help="Unchanged words keep their timing. New or replaced words are "
             "listed below as needing timing.",
    )
    lines, words = lyr.count_lyrics(edited or "")
    st.caption(f"{lines} sung lines, {words} words")

    cols = st.columns(3)
    with cols[0]:
        if st.button("Apply edits", key="apply_lyrics",
                     disabled=(edited or "") == current):
            result = stack.execute(project, lambda p: lyr.apply_lyrics_edit(p, edited or ""))
            if result.presentation_notices:
                st.session_state.project_message = " ".join(result.presentation_notices)
            if result.changed:
                st.success(
                    f"{len(result.kept_word_ids)} words kept their timing; "
                    f"{len(result.new_word_ids)} new, "
                    f"{len(result.removed_word_ids)} removed."
                )
            else:
                st.success("Text updated; all timing preserved.")
            st.session_state.lyrics_editor_version = version + 1
            st.rerun()
    with cols[1]:
        if st.button("Undo", key="undo_lyrics", disabled=not stack.can_undo):
            stack.undo(project)
            st.session_state.lyrics_editor_version = version + 1
            st.rerun()
    with cols[2]:
        if st.button("Redo", key="redo_lyrics", disabled=not stack.can_redo):
            stack.redo(project)
            st.session_state.lyrics_editor_version = version + 1
            st.rerun()

    st.download_button(
        "Export lyrics.txt", data=lyr.to_text(project),
        file_name="lyrics.txt", mime="text/plain", key="export_lyrics",
    )

    unresolved = project.unresolved_words()
    if unresolved:
        with st.expander(f"Needs timing ({len(unresolved)})", expanded=False):
            st.caption(
                "These words still lack enough timing context to estimate. Enable "
                "Estimate missing word timing in Timing to fill supported gaps. "
                "You can continue to vocal removal without fixing every word."
            )
            for line, word, reason in unresolved[:50]:
                st.markdown(f"- **{word.text}** in *{line.text}* - {reason}")
            if len(unresolved) > 50:
                st.caption(f"...and {len(unresolved) - 50} more.")


def _timeline_component():
    """Register the component.

    Deliberately NOT cached. Registration populates Streamlit's per-run
    component registry, so caching the returned renderer skips registration on
    later runs and the mount fails with "Component ... is not registered".
    Registering each run is the supported pattern; only the assets are cached.
    """
    return ed.timeline_component()


def _timing_editor(project, project_dir: Path, karaoke_path: Path, *, stage="video") -> None:
    review = stage == "review"
    ui.render(project, project_dir, karaoke_path,
              lyrics_editor=_lyrics_editor,
              export_controls=_review_controls if review else None,
              timing_review=review)


def main() -> None:
    st.set_page_config(page_title="HeartBeam", page_icon=":microphone:", layout="wide",
                       initial_sidebar_state="collapsed")
    css = (Path(__file__).parent / "editor_assets" / "workstation.css").read_text(encoding="utf-8")
    st.html(f"<style>{css}</style>")
    if "log_lines" not in st.session_state:
        st.session_state.log_lines = []
        st.session_state.status = {"progress": 0.0, "label": "Idle", "done": False, "returncode": None}
        st.session_state.out_dir = None
        st.session_state.running = False
        st.session_state.project = None
        st.session_state.project_dir = None
        st.session_state.project_saved_snapshot = None

    project = st.session_state.get("project")
    from heartbeam.timing_review import approved
    step = st.session_state.setdefault("workflow_step", "video" if project else "separation")
    if step == "repair":
        # A session open during the rollback resumes in the existing editor.
        step = st.session_state.workflow_step = "video" if project else "separation"
    if project and step in ("video", "export") and not approved(project):
        step = st.session_state.workflow_step = "review"
    with st.container(key="hb_workflow"):
        has_tracks = bool(project and st.session_state.get("project_dir") and
                          _available_tracks(project, Path(st.session_state.project_dir)))
        columns = st.columns([1.2, .55] + ([.7] if has_tracks else []) +
                             [1.1, 1.2, 1.1, .9], vertical_alignment="center")
        title, file_menu, *controls = columns
        with title:
            st.title("HeartBeam")
        with file_menu:
            _project_controls()
        if has_tracks:
            tracks, *controls = controls
            with tracks:
                _track_controls(project, Path(st.session_state.project_dir))
        back, review_step, next_step, export_step = controls
        if back.button("1 · Prepare audio", key="step_separation", disabled=step == "separation" or st.session_state.running):
            st.session_state.workflow_step = "separation"
            st.rerun()
        if review_step.button("2 · Review timing", key="step_review", disabled=not project or step == "review" or st.session_state.running):
            st.session_state.workflow_step = "review"
            st.rerun()
        if next_step.button("3 · Edit video", key="step_video", disabled=not project or not approved(project) or step == "video" or st.session_state.running):
            st.session_state.workflow_step = "video"
            st.rerun()
        if export_step.button("4 · Export", key="step_export", disabled=not project or not approved(project) or step == "export" or st.session_state.running):
            st.session_state.workflow_step = "export"
            st.rerun()
    if step in ("video", "review") and project:
        name = html.escape(project.name, quote=True)
        state = 'Unsaved changes' if _is_dirty() else 'Saved'
        st.html(f'<div class="hb-project-status" role="status"><span title="{name}">{name}</span><span>{state}</span></div>')
        audio, _ = _project_media(project, st.session_state.project_dir)
        if not audio:
            st.warning("Relink the original audio in the File menu to load playback.")
            if not st.session_state.get("project_readonly"):
                _lyrics_editor(project, st.session_state.project_dir)
        elif st.session_state.get("project_readonly"):
            st.info("This project is open in another editor. Use Save a copy in the File menu to edit independently.")
            st.audio(str(audio))
        else:
            _timing_editor(project, st.session_state.project_dir, audio, stage=step)
    elif step == "export" and project:
        st.caption(f"{project.name} · Export · {'Unsaved changes' if _is_dirty() else 'Saved'}")
        audio, _ = _project_media(project, st.session_state.project_dir)
        if not audio:
            st.warning("Relink the karaoke audio before exporting.")
        else:
            _editor_exports(project, st.session_state.project_dir, audio)
    else:
        with st.container(key="hb_separation"):
            st.subheader("1 · Prepare audio")
            _separation_page()


def _separation_page() -> None:

    # --- Inputs ---
    uploads = st.columns(2)
    song_up = uploads[0].file_uploader("Song audio", type=["mp3", "wav", "flac", "ogg", "m4a"], accept_multiple_files=False, key="song_upload")
    imported = uploads[1].file_uploader("Lyrics file (optional)", type=["txt"], accept_multiple_files=False, key="lyrics_import",
                                      help="You can paste or type lyrics below instead.")
    from heartbeam.lyrics_lookup_ui import controls as lookup_controls
    from heartbeam.lyrics_lookup import audio_metadata
    upload_key = f'{song_up.name}_{song_up.size}' if song_up else 'empty'
    defaults = audio_metadata(song_up) if song_up else {}
    if song_up and not defaults.get('title'):
        name = Path(song_up.name).stem
        if ' - ' in name:
            artist, title = name.split(' - ', 1)
            defaults.update(artist=artist, title=re.sub(r'\s*\(Official.*?\)', '', title, flags=re.I))
        else:
            defaults['title'] = name
    candidate = lookup_controls(f'generate_{upload_key}', defaults, inline=True)
    if candidate:
        st.session_state.lyrics_text = candidate['lyrics']
        st.session_state.generation_candidate = (upload_key, candidate)
        st.rerun()
    lyrics_text = _lyrics_input(imported)

    lyric_line_count, _ = lyr.count_lyrics(lyrics_text)
    ready = song_up is not None and lyric_line_count > 0
    run_clicked = st.button("Prepare audio and match lyrics", type="primary",
                            disabled=not ready or st.session_state.running)
    progress_slot = st.container(key="hb_prepare_result")
    with progress_slot:
        _separation_result()

    primary = list(PRIMARY_PRESETS)
    genre = st.selectbox(
        "Genre profile",
        options=primary,
        index=primary.index("pop"),
        help="Each profile picks the right separator stack AND mix/mask tuning for that genre.",
    )

    # --- Advanced ---
    extra_flags: list[str] = ["--prepare-only"]
    with st.expander("Advanced settings"):
        st.caption("Automatic uses the available NVIDIA GPU, with CPU alignment on small GPUs to avoid running out of memory.")
        st.markdown(_format_preset_summary(genre))
        cols = st.columns(2)
        with cols[0]:
            align_device = st.selectbox(
                "Alignment device",
                options=["auto", "cuda", "cpu"],
                index=0,
                format_func=lambda value: {"auto": "Automatic (recommended)", "cuda": "NVIDIA GPU (CUDA)", "cpu": "CPU"}[value],
                help="Automatic chooses the device and checks available GPU memory.",
            )
            override_strategy = st.selectbox(
                "Mix strategy",
                options=["(preset default)", "replace", "subtract"],
                index=0,
            )
            if override_strategy != "(preset default)":
                extra_flags += ["--mix-strategy", override_strategy]
        with cols[1]:
            override_lufs = st.number_input(
                "Target LUFS (0 to disable)", value=0.0, step=1.0, format="%.1f",
                help="0 = use preset default. Typical values: -14 (streaming/karaoke), -23 (broadcast).",
            )
            if override_lufs == 0.0:
                pass  # use preset
            elif override_lufs < -1:
                extra_flags += ["--target-lufs", str(override_lufs)]
            else:
                extra_flags += ["--no-lufs"]

        override_pad = st.slider("pad_ms override (-1 = preset)", -1, 400, -1)
        if override_pad >= 0:
            extra_flags += ["--pad-ms", str(override_pad)]
        override_xfade = st.slider("crossfade_ms override (-1 = preset)", -1, 400, -1)
        if override_xfade >= 0:
            extra_flags += ["--crossfade-ms", str(override_xfade)]
        override_gain = st.slider("vocal_gain override (-1 = preset)", -1.0, 2.5, -1.0, step=0.1)
        if override_gain >= 0:
            extra_flags += ["--vocal-gain", str(override_gain)]
        override_boost = st.slider("backing_boost override (-1 = preset)", -1.0, 1.5, -1.0, step=0.05)
        if override_boost >= 0:
            extra_flags += ["--backing-boost", str(override_boost)]

    # --- Run ---
    if run_clicked and ready and not st.session_state.running:
        try:
            run_root = new_session(Path(song_up.name).stem)
            song_path = run_root / Path(song_up.name).name
            song_path.write_bytes(song_up.getbuffer())
            # Materialising the CLI's lyric file is our job, not the user's.
            lyrics_path = run_root / "lyrics.txt"
            out_dir = run_root / "out"
            out_dir.mkdir()
            lyrics_path.write_text(lyrics_text, encoding="utf-8")
            selected_candidate = st.session_state.get('generation_candidate')
            if selected_candidate and selected_candidate[0] == upload_key:
                candidate_path = run_root / 'lyrics-candidate.json'
                candidate_path.write_text(json.dumps(selected_candidate[1]), encoding='utf-8')
                extra_flags += ['--lyrics-candidate', str(candidate_path)]
        except OSError as exc:
            progress_slot.error(f"Could not store this song in {data_root()}: {exc}")
            return

        st.session_state.log_lines = []
        st.session_state.status = {"progress": 0.0, "label": "Starting", "done": False, "returncode": None}
        st.session_state.pop('prepare_error', None)
        st.session_state.out_dir = out_dir
        st.session_state.song_name = Path(song_up.name).stem
        st.session_state.separation_project_id = None
        st.session_state.running = True

        # Launch the subprocess on a background thread; the UI polls session_state.
        t = threading.Thread(
            target=_run_heartbeam,
            args=(song_path, lyrics_path, out_dir, genre, align_device, extra_flags,
                  st.session_state.log_lines, st.session_state.status),
            daemon=True,
        )
        t.start()
        st.rerun()

    # --- Progress / Output ---
    if st.session_state.running:
        status = st.session_state.status
        progress_slot.progress(status["progress"], text=f"{status['label']} ({status['progress'] * 100:.0f}%)")
        with progress_slot.expander("Live log", expanded=False):
            st.code("".join(st.session_state.log_lines[-200:]), language="text")
        if status["done"]:
            st.session_state.running = False
            if status["returncode"] == 0:
                # Persist the run immediately. Until this exists, closing the
                # browser loses the reference to a 45-minute separation.
                adopted = _adopt_run_into_project(
                    st.session_state.out_dir,
                    st.session_state.get("song_name", "") or "Untitled song",
                )
                if adopted:
                    st.session_state.project_message = "Audio tracks are ready. Save your project and review lyric timing."
            else:
                st.session_state.prepare_error = f"Audio preparation stopped (code {status['returncode']}). See the preparation log."
            st.rerun()
        else:
            time.sleep(1.0)
            st.rerun()

def _separation_result() -> None:
    failure = st.session_state.get('prepare_error')
    if failure:
        st.error(failure)
        with st.expander('Preparation log'):
            st.code(''.join(st.session_state.log_lines[-200:]), language='text')
        return
    project = st.session_state.get("project")
    if not project or st.session_state.running:
        return
    root = st.session_state.project_dir
    audio, _ = _project_media(project, root)
    with st.container(border=True):
        from heartbeam.timing_review import approved
        pending = not approved(project)
        st.subheader("Your tracks are ready" if pending else "Your song is ready")
        st.write(project.name)
        if audio:
            st.audio(str(audio))
        generated = st.session_state.get("separation_project_id") == project.id
        if generated:
            try:
                relative = root.resolve().relative_to(sessions_dir().resolve())
                st.caption(f"Saved automatically as Session {relative.parts[0]}")
            except ValueError:
                st.caption(f"Saved automatically in {root}")
        if st.button("Review timing" if pending else "Edit video", key="save_and_edit",
                     type="primary", disabled=st.session_state.get("project_readonly", False)):
            try:
                prj.save_project(project, root, bump=False)
                _mark_saved(project)
                st.session_state.workflow_step = "review" if pending else "video"
                st.session_state.separation_project_id = None
                st.rerun()
            except (prj.ProjectError, OSError) as exc:
                st.error(f"Could not save the project: {exc}")


def _review_controls(project, root, audio_path):
    st.subheader("Build karaoke audio")
    missing = len(project.unresolved_words())
    conflicts = len(ed.review_conflicts(project))
    if missing or conflicts:
        st.warning(f"{missing} words still have no timing and {conflicts} timing conflicts remain. You can continue with separate vocal tracks; word timing controls the lyric highlights.")
    estimated = len(project.estimated_word_ids())
    if estimated:
        st.caption(f'{estimated} words use estimated timing from nearby words or phrases.')
    st.caption("Build with your current edits and continue to video editing. Individual word review is optional; you can adjust timings and vocal levels later.")
    backing_level = st.slider('Backing vocals (%)', 0, 100, round(project.vocal_mix.backing_value * 100),
        key=f'build_backing_{project.id}', help='0 mutes backing vocals; 100 keeps the saved backing track. Adjust it later with the song sliders.')
    st.button("Build karaoke and continue", type="primary", key="approve_timing_build",
              disabled=st.session_state.get('project_readonly', False),
              on_click=_approve_timing_build, args=(project, root, backing_level / 100))


def _approve_timing_build(project, root, backing_level):
    from heartbeam import timing_review as review
    try:
        with st.spinner("Building karaoke from the saved tracks…"):
            ui.history(project).execute(project, lambda p: review.approve_and_build(p, root,
                keep_backing=backing_level > 0, allow_incomplete=True, separate_tracks=True, backing_level=backing_level))
            prj.save_project(project, root, bump=False)
        _mark_saved(project)
        st.session_state.workflow_step = "video"
        st.session_state.timing_message = ("ok", "Karaoke audio is ready. You can keep editing word timing and vocal levels.")
    except (prj.ProjectError, OSError, ValueError, RuntimeError) as exc:
        st.session_state.timing_message = ("err", f"Could not build karaoke audio: {exc}")


def _editor_exports(project, root, karaoke_path):
    from heartbeam.project_video_ui import render_controls
    from heartbeam.vocal_mix import configured
    render_controls(project, root, karaoke_path)
    with st.expander("Audio and timing downloads"):
        if configured(project):
            st.caption("Prepare an MP3 and WAV with your current lead, backing and section levels. Video exports use those levels automatically.")
            if st.button("Prepare current audio download"):
                ui.prepare_final_mix(project, root)
        st.download_button("Download initial karaoke build.mp3", karaoke_path.read_bytes(), "karaoke-initial.mp3", mime="audio/mpeg")
        if project.imported_timings_path:
            from heartbeam.project_preview import current_timings
            from heartbeam.render import _audio_duration
            try:
                current = current_timings(project, round(_audio_duration(karaoke_path) * 1000), allow_timing_issues=True)
                st.download_button("Download timings.json", json.dumps(current.to_dict(), ensure_ascii=False, indent=2), "timings.json", mime="application/json")
            except prj.ProjectError as exc:
                st.caption(str(exc))
        for role in ("lead_stem", "backing_stem", "instrumental_stem"):
            asset = project.asset_by_role(role)
            if asset and asset.resolve(root).is_file():
                path = asset.resolve(root)
                st.download_button(f"Download {role.replace('_', ' ')}", path.read_bytes(), f"{role}{path.suffix}", mime="audio/wav", key=f"download_{role}")


def cli_entry() -> None:
    """Entry point: `heartbeam-gui` from pyproject.toml's [project.scripts].

    Runs Streamlit in headless mode so it doesn't ask for an email on first
    launch, then opens the browser ourselves once the server is up.
    """
    import webbrowser
    from streamlit.web.cli import main as st_main

    port = 8501
    url = f"http://localhost:{port}"

    def _already_serving() -> bool:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            return False

    # Launching twice is the common case: the app runs windowless under pythonw,
    # so there is nothing on screen to tell you it is already up. Without this,
    # the second launch dies on "port 8501 is already in use" with no console to
    # show the error -- indistinguishable from the app simply not working. Just
    # surface the tab that already exists.
    if _already_serving():
        webbrowser.open(url)
        return

    def _open_when_ready(timeout_s: float = 120.0) -> None:
        """Open the browser once the server actually accepts connections.

        A fixed delay races the server: on a cold start this process still has
        to import torch (via heartbeam.models), which can take far longer than
        any constant worth hardcoding, and the user lands on a connection error
        and assumes the app is broken.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                    break
            except OSError:
                time.sleep(0.25)
        webbrowser.open(url)

    threading.Thread(target=_open_when_ready, daemon=True).start()
    sys.argv = [
        "streamlit", "run", os.path.abspath(__file__),
        # headless also suppresses the first-run "enter your email" prompt.
        "--server.headless=true",
        f"--server.port={port}",
        "--browser.gatherUsageStats=false",
        # This is a local single-user tool, not a deployment target. 'minimal'
        # drops Streamlit's toolbar nags — the "Deploy to Streamlit Community
        # Cloud" button and the developer rerun/clear-cache menu — and hides the
        # hamburger entirely once nothing is left in it. Use 'viewer' instead if
        # you want the Settings/theme menu back without the deploy button.
        "--client.toolbarMode=minimal",
    ]
    sys.exit(st_main())


if __name__ == "__main__":
    main()
