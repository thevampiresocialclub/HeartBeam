"""P01.1 regression tests: each case fails on the pre-fix code.

Grouped by the defect it pins down, so a future change that reintroduces one
tells you which behaviour broke rather than just "a test failed".
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from heartbeam.ass_writer import _fmt_ass_time
from heartbeam.style import Style, toml_escape, toml_string
from heartbeam.timings import (
    Line,
    Models,
    Source,
    TimingsValidationError,
    Timings,
    Word,
)

BACKSLASH = chr(92)


# --------------------------------------------------------------------------
# TOML serialisation of Windows paths
# --------------------------------------------------------------------------

WINDOWS_PATHS = [
    "C:" + BACKSLASH + "Users" + BACKSLASH + "young" + BACKSLASH + "Pictures" + BACKSLASH + "bg.png",
    "C:" + BACKSLASH + "Users" + BACKSLASH + "My Photos" + BACKSLASH + "back drop.png",
    "C:" + BACKSLASH + "temp" + BACKSLASH + "na" + chr(239) + "ve.png",
    "C:" + BACKSLASH + "music" + BACKSLASH + "don't stop.mp4",
    "D:" + BACKSLASH + "n" + BACKSLASH + "t" + BACKSLASH + "u" + BACKSLASH + "x.png",
]


@pytest.mark.parametrize("raw", WINDOWS_PATHS)
def test_windows_paths_round_trip_through_toml(raw, tmp_path):
    """Raw interpolation broke drive paths: one failed to parse, another gained a TAB."""
    f = tmp_path / "style.toml"
    f.write_text(
        "[background]" + chr(10)
        + "kind = " + toml_string("image") + chr(10)
        + "value = " + toml_string(raw) + chr(10),
        encoding="utf-8",
    )
    parsed = tomllib.loads(f.read_text(encoding="utf-8"))
    assert parsed["background"]["value"] == raw


def test_toml_escape_handles_quotes_and_controls():
    assert toml_escape(chr(9)) == BACKSLASH + "t"
    assert toml_escape(chr(10)) == BACKSLASH + "n"
    assert toml_escape(chr(1)) == BACKSLASH + "u0001"
    assert toml_escape('a"b') == "a" + BACKSLASH + '"b'
    assert toml_escape("plain") == "plain"


def test_gui_style_writer_survives_windows_background(tmp_path):
    """The GUI writes this file; Style.from_toml must read it back unchanged."""
    from heartbeam.gui import _write_style_toml

    raw = WINDOWS_PATHS[0]
    f = tmp_path / "s.toml"
    _write_style_toml(
        f, font_size=72, text_colour="#FFFFFF", highlight_colour="#FFD700",
        position="bottom", resolution="1920x1080",
        background_kind="image", background_value=raw,
    )
    style = Style.from_toml(f)
    assert style.background.value == raw
    assert style.font.size_px == 72


# --------------------------------------------------------------------------
# ASS timestamp rollover
# --------------------------------------------------------------------------

@pytest.mark.parametrize("seconds,expected", [
    (0.0, "0:00:00.00"),
    (1.5, "0:00:01.50"),
    (59.994, "0:00:59.99"),
    (59.999, "0:01:00.00"),    # was 0:00:60.00
    (119.999, "0:02:00.00"),   # was 0:01:60.00
    (3599.999, "1:00:00.00"),  # was 0:59:60.00
])
def test_ass_timestamps_carry_correctly(seconds, expected):
    assert _fmt_ass_time(seconds) == expected


def test_ass_timestamp_fields_are_always_in_range():
    """No component may reach 60; ASS parsers reject 0:00:60.00."""
    t = 0.0
    while t < 130.0:
        _, mm, rest = _fmt_ass_time(t).split(":")
        ss, cc = rest.split(".")
        assert int(mm) < 60 and int(ss) < 60 and int(cc) < 100, (t, _fmt_ass_time(t))
        t += 0.001


# --------------------------------------------------------------------------
# Timing validation
# --------------------------------------------------------------------------

def _timings_dict(word_overrides):
    w = {"text": "alpha", "start_s": 0.0, "end_s": 1.0, "score": 0.9}
    w.update(word_overrides)
    return {
        "schema_version": 1,
        "source": {"audio_path": "a.mp3", "lyrics_path": "l.txt",
                   "sample_rate": 44100, "duration_s": 10.0},
        "models": {"separator": "pop", "aligner": "whisperx"},
        "lines": [{"index": 0, "text": "alpha", "start_s": 0.0, "end_s": 1.0,
                   "words": [w]}],
    }


@pytest.mark.parametrize("override,needle", [
    ({"start_s": 5.0, "end_s": 1.0}, "precedes"),
    ({"start_s": -1.0}, "negative"),
    ({"end_s": float("inf")}, "not finite"),
    ({"start_s": float("nan")}, "not finite"),
    ({"score": float("nan")}, "score"),
])
def test_invalid_word_timing_is_rejected_and_named(override, needle):
    with pytest.raises(TimingsValidationError) as exc:
        Timings.from_dict(_timings_dict(override))
    msg = str(exc.value)
    assert needle in msg
    assert "alpha" in msg, "error must identify the offending word"


def test_valid_timings_still_load():
    t = Timings.from_dict(_timings_dict({}))
    assert len(t.lines) == 1 and t.lines[0].words[0].text == "alpha"


# --------------------------------------------------------------------------
# ffmpeg stream selection
# --------------------------------------------------------------------------

def test_render_maps_streams_explicitly(tmp_path, monkeypatch):
    """Without -map, a background video's own audio can become the soundtrack."""
    import heartbeam.render as render_mod

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        class R:
            returncode = 0
            stderr = b""
        return R()

    monkeypatch.setattr(render_mod.subprocess, "run", fake_run)
    monkeypatch.setattr(render_mod, "_ffmpeg_path", lambda: "ffmpeg")

    ass = tmp_path / "x.ass"
    ass.write_text("", encoding="utf-8")
    bg = tmp_path / "bg.mp4"
    bg.write_bytes(b"\x00")

    render_mod.render(
        audio_path=tmp_path / "karaoke.mp3",
        ass_path=ass,
        out_path=tmp_path / "out.mp4",
        style=Style.default(),
        background_override=str(bg),
    )
    cmd = captured["cmd"]
    assert "-map" in cmd, "stream mapping must be explicit"
    # Video from the background (input 0), audio from the karaoke file (input 1).
    pairs = [(cmd[i], cmd[i + 1]) for i, a in enumerate(cmd) if a == "-map"]
    assert ("-map", "0:v:0") in pairs
    assert ("-map", "1:a:0") in pairs
    assert "-shortest" in cmd, "render must be bounded by the audio program"


# --------------------------------------------------------------------------
# End-to-end media regression (needs ffmpeg)
# --------------------------------------------------------------------------

pytestmark_media = pytest.mark.media


def _ffmpeg_missing() -> bool:
    return shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None


@pytest.mark.media
@pytest.mark.skipif(_ffmpeg_missing(), reason="ffmpeg/ffprobe not on PATH")
def test_background_audio_never_becomes_the_soundtrack(tmp_path):
    """A background video carrying its own audio must not supply the export.

    Pre-fix this did two things: it took the background's soundtrack, and with a
    looping background it never terminated at all (-shortest bound itself to the
    infinitely looped background audio). The render is capped here so a
    regression fails the test instead of hanging the suite.
    """
    import numpy as np

    from heartbeam.ass_writer import write_ass
    from heartbeam.render import render

    bg = tmp_path / "bg.mp4"
    karaoke = tmp_path / "karaoke.mp3"
    # Background: 12s of video carrying a 1000 Hz tone.
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x240:r=10:d=12",
         "-f", "lavfi", "-i", "sine=frequency=1000:duration=12",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
         "-shortest", str(bg)], check=True, capture_output=True)
    # Karaoke: 4s of 220 Hz -- clearly distinguishable from the background.
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=220:duration=4",
         "-c:a", "libmp3lame", str(karaoke)], check=True, capture_output=True)

    style = Style.default()
    style.video.resolution = "320x240"
    style.video.fps = 10

    timings = Timings(
        source=Source(audio_path=str(karaoke), lyrics_path="l.txt",
                      sample_rate=44100, duration_s=4.0),
        models=Models(separator="pop", aligner="whisperx"),
        lines=[Line(index=0, text="test tone", start_s=0.5, end_s=3.5,
                    words=[Word(text="test", start_s=0.5, end_s=1.5, score=1.0),
                           Word(text="tone", start_s=1.6, end_s=3.5, score=1.0)])],
    )
    ass = tmp_path / "t.ass"
    write_ass(timings, style, ass)
    out = tmp_path / "out.mp4"

    render(audio_path=karaoke, ass_path=ass, out_path=out,
           style=style, background_override=str(bg))
    assert out.exists()

    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True).stdout.strip())
    assert 3.5 < duration < 5.0, f"render must follow the 4s song, got {duration}s"

    raw = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(out),
         "-f", "f32le", "-ac", "1", "-ar", "44100", "-"],
        capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    segment = samples[len(samples) // 4: len(samples) // 4 + 44100]
    spectrum = np.abs(np.fft.rfft(segment * np.hanning(len(segment))))
    dominant = np.fft.rfftfreq(len(segment), 1 / 44100)[int(np.argmax(spectrum))]

    assert abs(dominant - 220) < 15, (
        f"expected the 220 Hz karaoke tone, got {dominant:.0f} Hz "
        "(1000 Hz means the background audio hijacked the soundtrack)"
    )


@pytest.mark.media
@pytest.mark.skipif(_ffmpeg_missing(), reason="ffmpeg/ffprobe not on PATH")
def test_render_creates_missing_output_directory(tmp_path):
    """-o into a directory that does not exist yet used to fail writing the ASS."""
    out = tmp_path / "does" / "not" / "exist" / "karaoke.mp4"
    audio = tmp_path / "a.mp3"
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:a", "libmp3lame", str(audio)], check=True, capture_output=True)

    timings = Timings(
        source=Source(audio_path=str(audio), lyrics_path="l.txt",
                      sample_rate=44100, duration_s=1.0),
        models=Models(separator="pop", aligner="whisperx"),
        lines=[Line(index=0, text="hi", start_s=0.1, end_s=0.9,
                    words=[Word(text="hi", start_s=0.1, end_s=0.9, score=1.0)])],
    )
    tj = tmp_path / "timings.json"
    from heartbeam.timings import to_json
    to_json(timings, tj)

    from heartbeam.cli_video import main as video_main
    rc = video_main([str(audio), str(tj), "-o", str(out)])
    assert rc == 0
    assert out.exists()
