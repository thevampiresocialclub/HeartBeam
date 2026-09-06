"""
Build a per-sample time-domain mask from word intervals.

mask[i] = 1.0  → sample i is INSIDE a sung-word interval (lead vocal will be subtracted)
mask[i] = 0.0  → sample i is OUTSIDE (original audio passes through untouched)
Edges are half-cosine cross-faded to avoid clicks.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Interval:
    start_s: float
    end_s: float


def _merge_intervals(intervals: list[Interval]) -> list[Interval]:
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda i: i.start_s)
    merged = [Interval(intervals[0].start_s, intervals[0].end_s)]
    for iv in intervals[1:]:
        last = merged[-1]
        if iv.start_s <= last.end_s:
            last.end_s = max(last.end_s, iv.end_s)
        else:
            merged.append(Interval(iv.start_s, iv.end_s))
    return merged


def _half_cosine_ramp(n: int, rising: bool) -> np.ndarray:
    """n-sample half-cosine: rising 0→1 or falling 1→0."""
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    t = np.arange(n, dtype=np.float32) / n
    if rising:
        return (0.5 - 0.5 * np.cos(np.pi * t)).astype(np.float32)
    return (0.5 + 0.5 * np.cos(np.pi * t)).astype(np.float32)


def _bridge_short_gaps(intervals: list[Interval], max_gap_s: float) -> list[Interval]:
    """Join adjacent intervals whose inter-gap is shorter than max_gap_s."""
    if not intervals or max_gap_s <= 0:
        return intervals
    bridged = [Interval(intervals[0].start_s, intervals[0].end_s)]
    for iv in intervals[1:]:
        last = bridged[-1]
        if iv.start_s - last.end_s <= max_gap_s:
            last.end_s = max(last.end_s, iv.end_s)
        else:
            bridged.append(Interval(iv.start_s, iv.end_s))
    return bridged


def build_mask(
    words: list,
    total_samples: int,
    sr: int,
    pad_ms: float = 120.0,
    xfade_ms: float = 60.0,
    merge_gap_ms: float = 500.0,
) -> np.ndarray:
    """
    words: list of objects with .start_s and .end_s attrs (e.g. timings.Word).
    total_samples: number of samples the mask should span.
    sr: sample rate.
    pad_ms: how far to extend each word interval on both sides before merging.
    xfade_ms: half-cosine ramp length at each interval edge.
    merge_gap_ms: after padding, also bridge adjacent intervals whose remaining gap
        is shorter than this. Prevents the lead vocal leaking through short
        inter-word pauses inside a sung phrase. Set to 0 to disable.

    Returns float32 mask shape (total_samples,).
    """
    mask = np.zeros(total_samples, dtype=np.float32)
    if not words or total_samples <= 0:
        return mask

    pad_s = pad_ms / 1000.0
    xfade_n = max(1, int(round(xfade_ms / 1000.0 * sr)))

    raw = [Interval(max(0.0, w.start_s - pad_s), w.end_s + pad_s) for w in words]
    merged = _merge_intervals(raw)
    merged = _bridge_short_gaps(merged, merge_gap_ms / 1000.0)

    for iv in merged:
        start = int(round(iv.start_s * sr))
        end = int(round(iv.end_s * sr))
        start = max(0, start)
        end = min(total_samples, end)
        if end <= start:
            continue

        region_len = end - start
        # Cap ramp length so two ramps fit inside the region.
        ramp_n = min(xfade_n, region_len // 2)
        if ramp_n <= 0:
            mask[start:end] = np.maximum(mask[start:end], 1.0)
            continue

        # Rising edge
        mask[start : start + ramp_n] = np.maximum(
            mask[start : start + ramp_n], _half_cosine_ramp(ramp_n, rising=True)
        )
        # Plateau
        plateau_start = start + ramp_n
        plateau_end = end - ramp_n
        if plateau_end > plateau_start:
            mask[plateau_start:plateau_end] = 1.0
        # Falling edge
        mask[end - ramp_n : end] = np.maximum(
            mask[end - ramp_n : end], _half_cosine_ramp(ramp_n, rising=False)
        )

    return mask


def build_energy_mask(
    lead_stem: np.ndarray,
    sr: int,
    window_ms: float = 30.0,
    threshold_rel: float = 0.05,
    xfade_ms: float = 30.0,
    min_active_ms: float = 40.0,
) -> np.ndarray:
    """Mask wherever the lead stem has audible energy.

    Catches anything WhisperX missed: held-vowel tails, ad-libs not in the lyrics
    file, breaths into a phrase. Threshold is relative to the lead stem's own peak
    RMS so it's self-calibrating per song.

    lead_stem: shape (N,) or (N, C) float32 — the isolated lead stem from separation
    window_ms: RMS smoothing window — too small flickers, too large blurs onsets
    threshold_rel: fraction of peak RMS to call "active" (0.05 = 5% of peak)
    xfade_ms: half-cosine ramp at active-region edges
    min_active_ms: drop any active island shorter than this (kills single-frame blips)

    Returns float32 mask shape (N,).
    """
    if lead_stem.ndim == 2:
        mono = lead_stem.mean(axis=1)
    else:
        mono = lead_stem
    n = mono.shape[0]
    if n == 0:
        return np.zeros(0, dtype=np.float32)

    # Smoothed RMS via cumulative-sum moving average (O(N)). Trailing-aligned
    # rms_short[i] = RMS of samples [i, i+win-1]; we center-align it within the
    # n-length output by padding edges with the nearest valid value, so a held
    # note at the start or end of the signal still gets a sensible estimate.
    win = max(1, min(int(round(window_ms / 1000.0 * sr)), n))
    sq = mono.astype(np.float32) ** 2
    cs = np.concatenate(([0.0], np.cumsum(sq, dtype=np.float64)))
    rms_short = np.sqrt(np.maximum((cs[win:] - cs[:-win]) / win, 0.0)).astype(np.float32)
    rms = np.empty(n, dtype=np.float32)
    if rms_short.size == 0:
        rms.fill(0.0)
    else:
        half = (win - 1) // 2
        rms[:half] = rms_short[0]
        rms[half : half + rms_short.size] = rms_short
        rms[half + rms_short.size:] = rms_short[-1]

    peak = float(rms.max()) if rms.size else 0.0
    if peak <= 0.0:
        return np.zeros(n, dtype=np.float32)
    active = rms >= (threshold_rel * peak)

    # Drop tiny islands.
    min_active_n = max(1, int(round(min_active_ms / 1000.0 * sr)))
    if min_active_n > 1 and active.any():
        # Find runs of True and zero out short ones.
        edges = np.diff(active.astype(np.int8), prepend=0, append=0)
        starts = np.where(edges == 1)[0]
        ends = np.where(edges == -1)[0]
        for s, e in zip(starts, ends):
            if e - s < min_active_n:
                active[s:e] = False

    # Cross-fade edges so the mask isn't a hard gate. Use np.maximum so adjacent
    # islands' falling/rising ramps overlap correctly rather than overwriting
    # each other to lower values.
    energy_mask = active.astype(np.float32)
    xfade_n = max(1, int(round(xfade_ms / 1000.0 * sr)))
    if xfade_n > 1 and active.any():
        edges = np.diff(active.astype(np.int8), prepend=0, append=0)
        starts = np.where(edges == 1)[0]
        ends = np.where(edges == -1)[0]
        for s, e in zip(starts, ends):
            region = e - s
            ramp = min(xfade_n, region // 2)
            if ramp <= 0:
                continue
            rising = _half_cosine_ramp(ramp, rising=True)
            falling = _half_cosine_ramp(ramp, rising=False)
            energy_mask[s : s + ramp] = np.maximum(energy_mask[s : s + ramp], rising)
            energy_mask[e - ramp : e] = np.maximum(energy_mask[e - ramp : e], falling)
    return energy_mask


def combine_masks(*masks: np.ndarray) -> np.ndarray:
    """Combine multiple (N,) masks with element-wise maximum (logical OR for [0,1])."""
    if not masks:
        raise ValueError("need at least one mask")
    out = masks[0].astype(np.float32, copy=True)
    for m in masks[1:]:
        if m.shape != out.shape:
            raise ValueError(f"mask shape mismatch: {m.shape} vs {out.shape}")
        np.maximum(out, m.astype(np.float32, copy=False), out=out)
    return out
