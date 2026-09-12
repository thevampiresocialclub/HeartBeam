"""Fast, conservative hints for passages where accompaniment may be thin."""
from __future__ import annotations

import math
import numpy as np
from scipy.ndimage import median_filter

from . import project as P


ANALYSIS_VERSION = 1


def _mono_power(samples: np.ndarray) -> np.ndarray:
    value = np.asarray(samples, dtype=np.float32)
    if value.ndim not in (1, 2) or not value.size or not np.isfinite(value).all():
        raise ValueError("audio must be a non-empty finite mono or multichannel array")
    return np.mean(np.square(value, dtype=np.float64), axis=1) if value.ndim == 2 else np.square(value, dtype=np.float64)


def _window_db(power: np.ndarray, starts: np.ndarray, window: int) -> np.ndarray:
    total = np.concatenate(([0.0], np.cumsum(power, dtype=np.float64)))
    mean = (total[starts + window] - total[starts]) / window
    return 10.0 * np.log10(np.maximum(mean, 1e-20))


def find_thin_spots(
    original: np.ndarray,
    instrumental: np.ndarray,
    sample_rate: int,
    *,
    window_ms: int = 200,
    hop_ms: int = 50,
    local_context_ms: int = 2050,
    min_dip_db: float = 6.0,
    max_original_dip_db: float = 3.0,
    min_original_dbfs: float = -45.0,
    min_duration_ms: int = 150,
    edge_ms: int = 2000,
    limit: int = 20,
) -> list[P.RepairSuggestion]:
    """Rank local level mismatches without claiming that damage is proven.

    A flag requires the instrumental to fall relative to its own local context
    while the original recording stays comparatively steady. This catches the
    useful volume clue but rejects shared rests. Listening remains the decision.
    """
    if sample_rate <= 0:
        raise ValueError("sample_rate must be positive")
    source, music = np.asarray(original), np.asarray(instrumental)
    if source.shape != music.shape:
        raise ValueError("original and instrumental must share one sample basis")
    source_power, music_power = _mono_power(source), _mono_power(music)
    window = max(1, round(sample_rate * window_ms / 1000))
    hop = max(1, round(sample_rate * hop_ms / 1000))
    if len(source_power) < window:
        return []
    starts = np.arange(0, len(source_power) - window + 1, hop, dtype=np.int64)
    source_db = _window_db(source_power, starts, window)
    music_db = _window_db(music_power, starts, window)
    context_frames = max(3, round(local_context_ms / hop_ms))
    if context_frames % 2 == 0:
        context_frames += 1
    source_base = median_filter(source_db, size=context_frames, mode="nearest")
    music_base = median_filter(music_db, size=context_frames, mode="nearest")
    source_dip, music_dip = source_base - source_db, music_base - music_db
    centers_ms = (starts + window / 2) * 1000.0 / sample_rate
    duration_ms = len(source_power) * 1000.0 / sample_rate
    suspect = ((music_dip >= min_dip_db) & (source_dip < max_original_dip_db)
               & (source_db > min_original_dbfs) & (centers_ms >= edge_ms)
               & (centers_ms <= duration_ms - edge_ms))

    groups: list[list[int]] = []
    merge_frames = max(1, round(150 / hop_ms))
    for index in np.flatnonzero(suspect):
        if not groups or index - groups[-1][-1] > merge_frames:
            groups.append([int(index)])
        else:
            groups[-1].append(int(index))

    found = []
    minimum_frames = max(1, math.ceil(min_duration_ms / hop_ms))
    for group in groups:
        if len(group) < minimum_frames:
            continue
        peak = max(group, key=lambda i: music_dip[i])
        start_ms = max(0, round(centers_ms[group[0]] - window_ms / 2))
        end_ms = min(round(duration_ms), round(centers_ms[group[-1]] + window_ms / 2))
        # Original stability raises confidence; this remains a review ranking,
        # not a probability or an automatic repair decision.
        score = float(max(0.0, music_dip[peak] - max(0.0, source_dip[peak])))
        found.append(P.RepairSuggestion(
            id=P.new_id("hint"), start_ms=start_ms, end_ms=end_ms,
            score=round(score, 3),
            reason="The instrumental drops relative to nearby music while the original stays steadier.",
            metrics={
                "instrumental_local_dip_db": round(float(music_dip[peak]), 3),
                "original_local_dip_db": round(float(source_dip[peak]), 3),
                "instrumental_dbfs": round(float(music_db[peak]), 3),
                "original_dbfs": round(float(source_db[peak]), 3),
            },
        ))
    found.sort(key=lambda item: item.score, reverse=True)
    return found[:max(0, limit)]

