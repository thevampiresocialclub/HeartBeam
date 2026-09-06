"""
Audio I/O — the only module in the engine that touches the filesystem or shells out to ffmpeg.

Decode (any format ffmpeg understands → float32 ndarray) uses ffmpeg over a pipe.
Encode to WAV uses soundfile directly. Encode to MP3 shells out to ffmpeg.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import soundfile as sf


def _ffmpeg_path() -> str:
    p = shutil.which("ffmpeg")
    if not p:
        raise RuntimeError(
            "ffmpeg not found on PATH. Install ffmpeg (built with libass for Phase 2) "
            "and ensure it is on PATH."
        )
    return p


def load_audio(path: str | Path, sr: int = 44100, mono: bool = False) -> tuple[np.ndarray, int]:
    """
    Decode any audio file to a float32 ndarray.
    Returns (samples, sample_rate) where samples is shape (N,) mono or (N, C) stereo+.
    """
    path = str(path)
    channels = 1 if mono else 2
    cmd = [
        _ffmpeg_path(),
        "-nostdin",
        "-loglevel", "error",
        "-i", path,
        "-f", "f32le",
        "-acodec", "pcm_f32le",
        "-ac", str(channels),
        "-ar", str(sr),
        "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg decode failed for {path}:\n{proc.stderr.decode('utf-8', errors='replace')}"
        )
    raw = np.frombuffer(proc.stdout, dtype=np.float32)
    if channels == 1:
        return raw.copy(), sr
    return raw.reshape(-1, channels).copy(), sr


def write_wav(path: str | Path, samples: np.ndarray, sr: int) -> None:
    sf.write(str(path), samples, sr, subtype="FLOAT")


def write_mp3(path: str | Path, samples: np.ndarray, sr: int, bitrate: str = "192k") -> None:
    """Encode float32 ndarray to MP3 via ffmpeg stdin."""
    path = str(path)
    if samples.ndim == 1:
        channels = 1
    else:
        channels = samples.shape[1]
    buf = np.ascontiguousarray(samples, dtype=np.float32).tobytes()
    cmd = [
        _ffmpeg_path(),
        "-nostdin",
        "-loglevel", "error",
        "-y",
        "-f", "f32le",
        "-ar", str(sr),
        "-ac", str(channels),
        "-i", "-",
        "-c:a", "libmp3lame",
        "-b:a", bitrate,
        path,
    ]
    proc = subprocess.run(cmd, input=buf, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg mp3 encode failed for {path}:\n{proc.stderr.decode('utf-8', errors='replace')}"
        )
