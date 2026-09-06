"""Streamlit GUI for HeartBeam.

Runs the existing CLI in a subprocess so we don't have to refactor the engine.
Streams stdout into the UI, recognises milestone log lines for progress.

Launch:
    heartbeam-gui          # via entry point (see pyproject.toml)
    python -m heartbeam.gui  # equivalent

That opens http://localhost:8501 in your browser.
"""
from __future__ import annotations

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

from heartbeam.models import PRESETS, PRIMARY_PRESETS, resolve_default

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
    """
    path.write_text(
        f'''[font]
size_px = {font_size}
bold    = true

[colour]
primary   = "{text_colour}"
highlight = "{highlight_colour}"

[box]
position = "{position}"

[background]
kind  = "{background_kind}"
value = "{background_value}"

[video]
resolution = "{resolution}"
''',
        encoding="utf-8",
    )


def _render_video(out_dir: Path, style_path: Path, log_lines: list[str]) -> tuple[int, Path]:
    """Run Phase 2. Synchronous: rendering is seconds, not minutes.

    Phase 1 needs the background-thread-and-poll dance because it runs for tens
    of minutes; ffmpeg burning subtitles onto a solid background does not.
    """
    video_path = out_dir / "karaoke.mp4"
    cmd = [
        _find_exe("heartbeam-video"),
        str(out_dir / "karaoke.mp3"),
        str(out_dir / "timings.json"),
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
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", bufsize=1,
    )
    for line in proc.stdout:  # type: ignore[union-attr]
        log_lines.append(line)
        for pat, pct, label in _MILESTONES:
            if pat.search(line):
                status_state["progress"] = pct
                status_state["label"] = label
                break
    proc.wait()
    status_state["returncode"] = proc.returncode
    status_state["done"] = True
    return proc.returncode


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


def main() -> None:
    st.set_page_config(page_title="HeartBeam", page_icon=":microphone:", layout="centered")
    st.title("HeartBeam")
    st.caption("Lyrics-aware karaoke generator — strip lead vocals, keep harmonies.")

    if "log_lines" not in st.session_state:
        st.session_state.log_lines = []
        st.session_state.status = {"progress": 0.0, "label": "Idle", "done": False, "returncode": None}
        st.session_state.out_dir = None
        st.session_state.running = False

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
                st.success("Karaoke ready.")
            else:
                st.error(f"heartbeam exited with code {status['returncode']}. See log above.")
            st.rerun()
        else:
            time.sleep(1.0)
            st.rerun()

    # --- Results (after a completed run) ---
    if (not st.session_state.running
            and st.session_state.out_dir is not None
            and (st.session_state.out_dir / "karaoke.mp3").exists()):
        out_dir: Path = st.session_state.out_dir  # type: ignore[assignment]
        st.divider()
        st.subheader("Result")
        karaoke_path = out_dir / "karaoke.mp3"
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
                p = out_dir / name
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
                    out_dir, style_path, st.session_state.log_lines
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
