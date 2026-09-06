"""LUFS loudness measurement and normalization via pyloudnorm.

LUFS (Loudness Units relative to Full Scale) is the ITU-R BS.1770 standard for
perceptual loudness. Karaoke output should typically target −14 LUFS (streaming
norm) with a true peak ≤ −1 dBTP to avoid clipping on playback.

pyloudnorm is the standard Python implementation; pure-Python aside from numpy.
"""
from __future__ import annotations

import numpy as np


def measure_lufs(samples: np.ndarray, sr: int) -> float:
    """Integrated LUFS (BS.1770) over the whole signal.

    samples: shape (N,) or (N, C). Returns −inf-like very negative for silence.
    """
    import pyloudnorm as pyln  # deferred — optional dependency

    # pyloudnorm expects (N,) mono or (N, channels) — same as ours.
    meter = pyln.Meter(sr)
    return float(meter.integrated_loudness(samples.astype(np.float32, copy=False)))


def normalize_to_lufs(
    samples: np.ndarray,
    sr: int,
    target_lufs: float = -14.0,
    true_peak_dbtp: float = -1.0,
) -> np.ndarray:
    """Gain-stage samples to hit target integrated LUFS, then peak-limit so the
    true peak doesn't exceed `true_peak_dbtp` dBTP.

    target_lufs:    -14 = streaming/karaoke standard; -23 = broadcast (EBU R128).
    true_peak_dbtp: -1 dBTP gives headroom for inter-sample peaks on consumer DACs.

    Returns float32 array same shape as input. Silent input is returned unchanged.
    """
    import pyloudnorm as pyln

    meter = pyln.Meter(sr)
    current = meter.integrated_loudness(samples.astype(np.float32, copy=False))
    if not np.isfinite(current):
        return samples.astype(np.float32, copy=False)
    gain_db = target_lufs - current
    gain = 10.0 ** (gain_db / 20.0)
    out = samples.astype(np.float32, copy=True) * gain

    # Peak limiter — soft brickwall at the target true peak.
    peak_limit = 10.0 ** (true_peak_dbtp / 20.0)
    peak = float(np.max(np.abs(out)))
    if peak > peak_limit and peak > 0.0:
        out = out * (peak_limit / peak)
    return out.astype(np.float32, copy=False)
