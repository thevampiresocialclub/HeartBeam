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
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import streamlit as st

from heartbeam import project as prj
from heartbeam.models import PRESETS, PRIMARY_PRESETS, resolve_default
from heartbeam.style import toml_string

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
        st.session_state.project_dir = path
        _mark_saved(recovered)
        return True, (
            f"{exc}. Recovered revision {recovered.revision} from autosave - "
            "save to make that recovery permanent."
        )
    st.session_state.project = project
    st.session_state.project_dir = path
    _mark_saved(project)
    return True, f"Opened '{project.name}' (revision {project.revision})"


def _project_media(project, project_dir: Path):
    """Resolve the karaoke audio and timings a project can render from.

    This is what lets an opened project reach the video controls without
    rerunning separation: both files are already on disk from the original run.
    """
    audio = None
    asset = project.asset_by_role("karaoke_audio")
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


def _adopt_run_into_project(out_dir: Path, song_name: str) -> None:
    """Turn a finished generation run into a saved project.

    Imports the run's own timings.json rather than re-deriving it, so the
    aligner's proposal is preserved verbatim as the immutable original.
    """
    timings_json = out_dir / "timings.json"
    karaoke = out_dir / "karaoke.mp3"
    if not timings_json.exists() or not karaoke.exists():
        return
    project_dir = out_dir / "project"
    try:
        project = prj.import_legacy_timings(
            project_dir, timings_json, karaoke,
            name=song_name or "Untitled song", audio_role="karaoke_audio",
        )
    except prj.ProjectError as exc:
        st.session_state.project_message = f"Could not create project: {exc}"
        return
    st.session_state.project = project
    st.session_state.project_dir = project_dir
    _mark_saved(project)


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
        if st.button("Relink", key=f"relink_btn_{a.id}"):
            try:
                if not new_path:
                    raise prj.ProjectError("Enter the full path to the file first.")
                prj.relink_asset(project, project_dir, a.id, new_path)
                st.success("Relinked.")
            except prj.ProjectError as exc:
                st.error(str(exc))


def _project_controls() -> None:
    """Sidebar: New / Open / Save / Save As, plus state and missing assets."""
    with st.sidebar:
        st.subheader("Project")
        project = st.session_state.get("project")
        project_dir = st.session_state.get("project_dir")

        if project is None:
            st.caption(
                "No project open. Generate a song below, or open an existing "
                "project folder."
            )
        else:
            state = "unsaved changes" if _is_dirty() else "saved"
            st.markdown(f"**{project.name}**")
            st.caption(f"revision {project.revision} - {state}")
            st.caption(str(project_dir))
            _render_missing_assets(project, project_dir)

            cols = st.columns(2)
            with cols[0]:
                if st.button("Save", key="save_project"):
                    prj.save_project(project, project_dir)
                    _mark_saved(project)
                    st.success(f"Saved revision {project.revision}")
            with cols[1]:
                if st.button("Close", key="close_project"):
                    st.session_state.project = None
                    st.session_state.project_dir = None

            save_as = st.text_input(
                "Save As (new folder)", key="save_as_path",
                placeholder="full path to a new folder",
            )
            if st.button("Save a copy", key="save_as_btn"):
                if not save_as:
                    st.error("Enter a destination folder first.")
                try:
                    if not save_as:
                        raise OSError("no destination folder given")
                    copy = prj.save_project_as(project, Path(save_as), src_dir=project_dir)
                    st.session_state.project = copy
                    st.session_state.project_dir = Path(save_as)
                    _mark_saved(copy)
                    st.success(f"Saved a copy to {save_as}")
                except OSError as exc:
                    st.error(f"Could not save a copy: {exc}")

        st.divider()
        open_path = st.text_input(
            "Open project folder", key="open_project_path",
            placeholder="full path to a project folder",
        )
        # The button always renders and validates on click. Gating it on the
        # text field makes it appear mid-keystroke and is impossible to drive
        # from a test.
        if st.button("Open", key="open_project_btn"):
            if not open_path:
                st.error("Enter the path to a project folder first.")
            else:
                ok, message = _open_project(Path(open_path))
                if ok:
                    # Rerun so the sidebar redraws with the project's name,
                    # revision and any missing assets. Without this the panel
                    # lags one interaction behind what is actually loaded.
                    st.session_state.project_message = message
                    st.rerun()
                else:
                    st.error(message)

        with st.expander("Import existing timings + audio"):
            st.caption("Enter an existing song without rerunning separation.")
            t_path = st.text_input("timings.json", key="import_timings")
            a_path = st.text_input("karaoke audio (optional)", key="import_audio")
            d_path = st.text_input("new project folder", key="import_dest")
            if st.button("Import", key="import_btn"):
                if not t_path or not d_path:
                    st.error("A timings.json and a destination folder are required.")
                else:
                    try:
                        imported = prj.import_legacy_timings(
                            Path(d_path), Path(t_path),
                            Path(a_path) if a_path else None,
                        )
                        st.session_state.project = imported
                        st.session_state.project_dir = Path(d_path)
                        _mark_saved(imported)
                        st.session_state.project_message = f"Imported '{imported.name}'"
                        st.rerun()
                    except prj.ProjectError as exc:
                        st.error(str(exc))

        message = st.session_state.pop("project_message", None)
        if message:
            st.info(message)


def main() -> None:
    st.set_page_config(page_title="HeartBeam", page_icon=":microphone:", layout="centered")
    st.title("HeartBeam")
    st.caption("Lyrics-aware karaoke generator — strip lead vocals, keep harmonies.")

    if "log_lines" not in st.session_state:
        st.session_state.log_lines = []
        st.session_state.status = {"progress": 0.0, "label": "Idle", "done": False, "returncode": None}
        st.session_state.out_dir = None
        st.session_state.running = False
        st.session_state.project = None
        st.session_state.project_dir = None
        st.session_state.project_saved_snapshot = None

    _project_controls()

    # --- Inputs ---
    song_up = st.file_uploader("Song (mp3 / wav / flac / ogg)", type=["mp3", "wav", "flac", "ogg", "m4a"])
    lyrics_up = st.file_uploader("Lyrics (txt, one phrase per line)", type=["txt"])

    primary = list(PRIMARY_PRESETS)
    genre = st.selectbox(
        "Genre profile",
        options=primary,
        index=primary.index("pop"),
        help="Each profile picks the right separator stack AND mix/mask tuning for that genre.",
    )
    st.markdown(_format_preset_summary(genre))

    # --- Advanced ---
    extra_flags: list[str] = []
    with st.expander("Advanced (overrides preset defaults)"):
        cols = st.columns(2)
        with cols[0]:
            align_device = st.selectbox(
                "Alignment device",
                options=["cpu", "auto", "cuda"],
                index=0,
                help="WhisperX device. cpu avoids OOM on small GPUs.",
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
    ready = song_up is not None and lyrics_up is not None
    run_clicked = st.button(
        "Generate karaoke", type="primary", disabled=not ready or st.session_state.running,
    )

    if run_clicked and ready and not st.session_state.running:
        # Drop uploads into a per-run dir under the system temp.
        run_root = Path(tempfile.mkdtemp(prefix="heartbeam_gui_"))
        song_path = run_root / song_up.name
        lyrics_path = run_root / lyrics_up.name
        out_dir = run_root / "out"
        out_dir.mkdir()
        song_path.write_bytes(song_up.getbuffer())
        lyrics_path.write_bytes(lyrics_up.getbuffer())

        st.session_state.log_lines = []
        st.session_state.status = {"progress": 0.0, "label": "Starting", "done": False, "returncode": None}
        st.session_state.out_dir = out_dir
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
        st.progress(status["progress"], text=f"{status['label']} ({status['progress'] * 100:.0f}%)")
        with st.expander("Live log", expanded=False):
            st.code("".join(st.session_state.log_lines[-200:]), language="text")
        if status["done"]:
            st.session_state.running = False
            if status["returncode"] == 0:
                # Persist the run immediately. Until this exists, closing the
                # browser loses the reference to a 45-minute separation.
                _adopt_run_into_project(
                    st.session_state.out_dir,
                    st.session_state.get("song_name", "") or "Untitled song",
                )
                st.success("Karaoke ready - saved as a project.")
            else:
                st.error(f"heartbeam exited with code {status['returncode']}. See log above.")
            st.rerun()
        else:
            time.sleep(1.0)
            st.rerun()

    # --- Results (from this session's run, or from an opened project) ---
    # Resolving the media from either source is what fulfils P01.4: an existing
    # song reaches the video controls without rerunning separation.
    karaoke_path: Path | None = None
    timings_path: Path | None = None
    work_dir: Path | None = None
    if not st.session_state.running:
        run_dir = st.session_state.out_dir
        if run_dir is not None and (run_dir / "karaoke.mp3").exists():
            karaoke_path = run_dir / "karaoke.mp3"
            timings_path = run_dir / "timings.json"
            work_dir = run_dir
        elif st.session_state.get("project") is not None:
            audio, timings = _project_media(
                st.session_state.project, st.session_state.project_dir)
            if audio is not None and timings is not None:
                karaoke_path = audio
                timings_path = timings
                work_dir = st.session_state.project_dir / prj.EXPORTS_DIR

    if karaoke_path is not None and work_dir is not None:
        out_dir: Path = work_dir
        st.divider()
        st.subheader("Result")
        st.audio(str(karaoke_path))
        with open(karaoke_path, "rb") as f:
            st.download_button(
                "Download karaoke.mp3",
                data=f.read(),
                file_name="karaoke.mp3",
                mime="audio/mpeg",
            )
        with st.expander("Other outputs (timings, stems)"):
            for name in ["timings.json", "lyrics.lrc", "stems/lead.wav",
                         "stems/backing.wav", "stems/instrumental.wav"]:
                p = karaoke_path.parent / name
                if p.exists():
                    with open(p, "rb") as f:
                        st.download_button(
                            f"Download {name}",
                            data=f.read(),
                            file_name=p.name,
                            mime="application/octet-stream",
                            key=name,
                        )


        # --- Step 2: karaoke video ---
        st.divider()
        st.subheader("Karaoke video")
        st.caption(
            "Renders in seconds — the slow ML work is already done, so you can "
            "restyle as often as you like without re-running the separation."
        )

        vcols = st.columns(2)
        with vcols[0]:
            bg_kind = st.selectbox("Background", ["solid", "image", "video"], index=0)
            bg_value = ""
            if bg_kind == "solid":
                bg_value = st.color_picker("Background colour", "#101820")
            else:
                bg_up = st.file_uploader(
                    f"Background {bg_kind}",
                    type=["png", "jpg", "jpeg"] if bg_kind == "image"
                    else ["mp4", "mov", "mkv", "webm"],
                    key="bg_upload",
                )
                if bg_up is not None:
                    bg_path = out_dir / f"background_{bg_up.name}"
                    bg_path.write_bytes(bg_up.getbuffer())
                    bg_value = str(bg_path)
            resolution = st.selectbox(
                "Resolution", ["1920x1080", "1280x720", "3840x2160"], index=0
            )
        with vcols[1]:
            text_colour = st.color_picker("Text (not yet sung)", "#FFFFFF")
            highlight_colour = st.color_picker("Highlight (being sung)", "#FFD700")
            font_size = st.slider("Font size (px)", 32, 140, 72, step=4)
            position = st.selectbox("Position", ["bottom", "center", "top"], index=0)

        video_path = out_dir / "karaoke.mp4"
        can_render = bg_kind == "solid" or bool(bg_value)
        if not can_render:
            st.info(f"Upload a background {bg_kind}, or switch back to a solid colour.")

        if st.button("Render video", type="primary", disabled=not can_render):
            out_dir.mkdir(parents=True, exist_ok=True)
            style_path = out_dir / "style.toml"
            _write_style_toml(
                style_path,
                font_size=font_size,
                text_colour=text_colour,
                highlight_colour=highlight_colour,
                position=position,
                resolution=resolution,
                background_kind=bg_kind,
                background_value=bg_value or "#101820",
            )
            with st.spinner("Rendering with ffmpeg + libass…"):
                rc, video_path = _render_video(
                    karaoke_path, timings_path, out_dir, style_path,
                    st.session_state.log_lines,
                )
            if rc != 0:
                st.error(f"heartbeam-video exited with code {rc}.")
                st.code("".join(st.session_state.log_lines[-40:]), language="text")

        if video_path.exists():
            st.video(str(video_path))
            with open(video_path, "rb") as f:
                st.download_button(
                    "Download karaoke.mp4",
                    data=f.read(),
                    file_name="karaoke.mp4",
                    mime="video/mp4",
                    key="dl_video",
                )


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
