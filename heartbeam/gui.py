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


def _run_heartbeam(
    song: Path, lyrics: Path, out_dir: Path,
    separator: str,
    align_device: str,
    extra_flags: list[str],
    log_lines: list[str], status_state: dict,
) -> int:
    """Subprocess heartbeam.exe, stream output into log_lines, update status_state."""
    exe = shutil.which("heartbeam") or shutil.which("heartbeam.exe")
    if exe is None:
        # Fall back to the venv hosting THIS process (since gui runs inside it).
        exe = str(Path(sys.executable).with_name("heartbeam.exe"))
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


def cli_entry() -> None:
    """Entry point: `heartbeam-gui` from pyproject.toml's [project.scripts].

    Runs Streamlit in headless mode so it doesn't ask for an email on first
    launch, then opens the browser ourselves once the server is up.
    """
    import webbrowser
    from streamlit.web.cli import main as st_main
    # Open browser shortly after server starts.
    port = "8501"
    url = f"http://localhost:{port}"
    threading.Timer(2.5, lambda: webbrowser.open(url)).start()
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
