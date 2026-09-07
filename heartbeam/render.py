"""
Phase 2 video renderer.

Composition is delegated to ffmpeg + libass: we generate a .ass subtitle file
from timings + style, then ffmpeg burns it onto a background video/image/solid
colour synced with the karaoke audio. No Python video compositing.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import json
import os
from pathlib import Path

from .style import Style

log = logging.getLogger(__name__)


def _ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg built with libass enabled."
        )
    return p


def _solid_colour_to_ffmpeg(hex_str: str) -> str:
    """libavfilter `color=` accepts 0xRRGGBB or named colours."""
    return "0x" + hex_str.lstrip("#")


def _audio_duration(path: Path) -> float:
    """Bound video frames explicitly; -shortest alone can retain encoder tail."""
    import soundfile as sf
    try:
        return sf.info(str(path)).duration
    except (RuntimeError, ValueError):
        probe = shutil.which("ffprobe") or str(Path(_ffmpeg_path()).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe"))
        result = subprocess.run([probe, "-v", "error", "-select_streams", "a:0",
                "-show_entries", "stream=duration:format=duration", "-of", "json", str(path)],
                capture_output=True, check=True, text=True)
        data = json.loads(result.stdout)
        value = next((s.get("duration") for s in data.get("streams", []) if s.get("duration") not in (None, "N/A")), data.get("format", {}).get("duration"))
        return float(value)


def _escape_path_for_ass_filter(path: Path) -> str:
    """
    The ass filter's filename argument is sensitive on Windows: backslashes and
    colons in C:\\ paths need escaping. Use forward slashes and escape the colon.
    """
    s = str(path).replace("\\", "/")
    # Escape the drive-letter colon: C:/... → C\:/...
    if len(s) >= 2 and s[1] == ":":
        s = s[0] + "\\:" + s[2:]
    return s


def render(
    audio_path: str | Path,
    ass_path: str | Path,
    out_path: str | Path,
    style: Style,
    background_override: str | Path | None = None,
    font_dir: str | Path | None = None,
) -> None:
    """
    audio_path: karaoke.mp3 (or any ffmpeg-readable audio)
    ass_path:   path to the .ass subtitle file
    out_path:   karaoke.mp4
    style:      Style (resolution, fps, codec, crf, audio_bitrate, background)
    background_override: optional path or hex (#RRGGBB) to override style.background
    """
    audio_path = Path(audio_path).resolve()
    ass_path = Path(ass_path).resolve()
    out_path = Path(out_path).resolve()

    width, height = style.video.resolution.split("x")
    fps = style.video.fps

    # Resolve background.
    bg = style.background
    if background_override is not None:
        bo = str(background_override)
        if bo.startswith("#") or (len(bo) in (6, 7) and all(c in "0123456789abcdefABCDEF#" for c in bo)):
            bg_kind, bg_value = "solid", bo
        else:
            p = Path(bo)
            if not p.exists():
                raise FileNotFoundError(f"background not found: {p}")
            suffix = p.suffix.lower()
            if suffix in (".mp4", ".mov", ".mkv", ".webm", ".avi"):
                bg_kind, bg_value = "video", str(p)
            else:
                bg_kind, bg_value = "image", str(p)
    else:
        bg_kind, bg_value = bg.kind, bg.value

    # Generated project exports use safe basenames (lyrics.ass and fonts).
    # Resolve the filter from that directory so apostrophes in a user's project
    # folder never enter FFmpeg's nested filter-string grammar.
    work_dir = ass_path.parent
    ass_filter_path = _escape_path_for_ass_filter(Path(ass_path.name))
    vf = f"ass='{ass_filter_path}'"
    if font_dir is not None:
        font_path = Path(font_dir).resolve()
        try:
            font_path = Path(os.path.relpath(font_path, work_dir))
        except ValueError:  # separate Windows drives
            pass
        vf += f":fontsdir='{_escape_path_for_ass_filter(font_path)}'"
    elif style.font.family == "Noto Sans":
        from .project_preview import VENDOR
        vf += f":fontsdir='{_escape_path_for_ass_filter(VENDOR.resolve())}'"

    cmd = [_ffmpeg_path(), "-nostdin", "-y", "-loglevel", "error"]

    if bg_kind == "solid":
        cmd += [
            "-f", "lavfi",
            "-i", f"color=c={_solid_colour_to_ffmpeg(bg_value)}:s={width}x{height}:r={fps}",
            "-i", str(audio_path),
        ]
    elif bg_kind == "image":
        cmd += [
            "-loop", "1", "-r", str(fps), "-i", str(Path(bg_value).resolve()),
            "-i", str(audio_path),
        ]
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},{vf}"
    elif bg_kind == "video":
        cmd += [
            "-stream_loop", "-1", "-i", str(Path(bg_value).resolve()),
            "-i", str(audio_path),
        ]
        vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},{vf},fps={fps}"
    else:
        raise ValueError(f"unknown background kind: {bg_kind}")

    cmd += [
        "-vf", vf,
        # Choose streams explicitly. Without -map, ffmpeg picks automatically:
        # it takes the "best" audio across ALL inputs, so a background video
        # carrying its own soundtrack silently replaces the karaoke audio in the
        # export. Input 0 is always the background, input 1 always the karaoke
        # audio. https://ffmpeg.org/ffmpeg.html#Stream-selection
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", style.video.codec,
        "-crf", str(style.video.crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", style.video.audio_bitrate,
        # Explicit duration bounds the looping background without letting the
        # last rounded video frame truncate the audio via -shortest.
        "-t", f"{_audio_duration(audio_path):.9f}",
        str(out_path),
    ]
    log.debug("ffmpeg cmd: %s", " ".join(cmd))
    proc = subprocess.run(cmd, cwd=work_dir, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg render failed:\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr: {proc.stderr.decode('utf-8', errors='replace')}"
        )
