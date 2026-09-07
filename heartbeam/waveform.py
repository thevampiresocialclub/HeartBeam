"""Waveform peak extraction for the timing editor.

Drawing a waveform in the browser does not require the browser to have the
audio. It requires min/max pairs per horizontal pixel bucket, which is a few
kilobytes even for a long song -- against ~40 MB of PCM. Computing them in
Python and shipping only the peaks is what keeps the editor responsive.

Peaks are cached next to the audio cache and keyed by the source hash plus the
bucket count, so zooming to a new resolution recomputes only that resolution and
a changed source invalidates everything.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

PEAKS_SCHEMA_VERSION = 1

#: Peaks are quantised to signed bytes for transport. 8 bits is plenty for a
#: waveform a few hundred pixels tall, and it keeps the JSON payload small.
_SCALE = 127


@dataclass
class Peaks:
    """Min/max pairs per bucket, quantised to [-127, 127]."""
    buckets: int
    duration_ms: int
    sample_rate: int
    mins: list[int]
    maxs: list[int]

    def to_dict(self) -> dict:
        return {
            "schema_version": PEAKS_SCHEMA_VERSION,
            "buckets": self.buckets,
            "duration_ms": self.duration_ms,
            "sample_rate": self.sample_rate,
            "mins": self.mins,
            "maxs": self.maxs,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Peaks":
        return cls(
            buckets=int(d["buckets"]),
            duration_ms=int(d["duration_ms"]),
            sample_rate=int(d["sample_rate"]),
            mins=list(d["mins"]),
            maxs=list(d["maxs"]),
        )


def compute_peaks(samples: np.ndarray, sample_rate: int, buckets: int = 2000) -> Peaks:
    """Reduce audio to `buckets` min/max pairs.

    Min AND max, not RMS: a waveform drawn from RMS alone loses the asymmetry
    and transients that make it possible to see where a word actually starts,
    which is the entire point of showing it to someone fixing timing.
    """
    if buckets <= 0:
        raise ValueError("buckets must be positive")
    mono = samples if samples.ndim == 1 else samples.mean(axis=1)
    mono = np.ascontiguousarray(mono, dtype=np.float32)
    n = mono.shape[0]
    duration_ms = int(round(n / sample_rate * 1000)) if sample_rate else 0
    if n == 0:
        return Peaks(buckets=0, duration_ms=0, sample_rate=sample_rate,
                     mins=[], maxs=[])

    buckets = min(buckets, n)
    # Trim to a whole number of buckets so the reshape is exact; the discarded
    # tail is at most one bucket, i.e. sub-pixel on screen.
    per = n // buckets
    usable = per * buckets
    block = mono[:usable].reshape(buckets, per)

    mins = np.clip(block.min(axis=1) * _SCALE, -_SCALE, _SCALE)
    maxs = np.clip(block.max(axis=1) * _SCALE, -_SCALE, _SCALE)
    return Peaks(
        buckets=buckets,
        duration_ms=duration_ms,
        sample_rate=sample_rate,
        mins=[int(v) for v in np.rint(mins)],
        maxs=[int(v) for v in np.rint(maxs)],
    )


def _cache_name(source_key: str, buckets: int) -> str:
    digest = hashlib.sha256(f"{source_key}:{buckets}".encode("utf-8")).hexdigest()[:16]
    return f"peaks_{buckets}_{digest}.json"


def load_or_compute(cache_dir: str | Path, source_key: str,
                    samples_provider, sample_rate: int,
                    buckets: int = 2000) -> Peaks:
    """Return cached peaks, computing them only on a miss.

    `samples_provider` is a zero-argument callable so a cache hit never has to
    read or decode the audio at all.
    """
    root = Path(cache_dir)
    path = root / _cache_name(source_key, buckets)
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if int(data.get("schema_version", -1)) == PEAKS_SCHEMA_VERSION:
                return Peaks.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError):
            pass  # fall through and recompute

    peaks = compute_peaks(samples_provider(), sample_rate, buckets=buckets)
    root.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(peaks.to_dict()), encoding="utf-8")
    return peaks
