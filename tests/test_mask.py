from dataclasses import dataclass

import numpy as np

from heartbeam.mask import build_mask


@dataclass
class W:
    text: str
    start_s: float
    end_s: float
    score: float = 1.0


def test_empty_words_returns_zeros():
    mask = build_mask([], total_samples=44100, sr=44100)
    assert mask.shape == (44100,)
    assert np.all(mask == 0.0)


def test_single_word_interior_is_one():
    sr = 44100
    words = [W("hello", 1.0, 2.0)]
    mask = build_mask(words, total_samples=3 * sr, sr=sr, pad_ms=0, xfade_ms=10)
    # Middle of [1.0, 2.0] should be exactly 1.0
    center = int(1.5 * sr)
    assert mask[center] == 1.0
    # Far outside should be 0
    assert mask[0] == 0.0
    assert mask[int(2.5 * sr)] == 0.0


def test_crossfade_is_monotonic_on_edges():
    sr = 44100
    words = [W("x", 1.0, 2.0)]
    mask = build_mask(words, total_samples=3 * sr, sr=sr, pad_ms=0, xfade_ms=20)
    # Rising edge: window of 20ms before the inside-region should be increasing.
    edge_start = int(1.0 * sr)
    rising = mask[edge_start : edge_start + int(0.02 * sr)]
    assert np.all(np.diff(rising) >= -1e-6)
    # Falling edge
    edge_end = int(2.0 * sr)
    falling = mask[edge_end - int(0.02 * sr) : edge_end]
    assert np.all(np.diff(falling) <= 1e-6)


def test_overlapping_intervals_merge():
    sr = 1000
    words = [W("a", 0.1, 0.5), W("b", 0.4, 0.8)]  # overlap
    mask = build_mask(words, total_samples=sr, sr=sr, pad_ms=0, xfade_ms=10)
    # Inside merged region [0.1, 0.8] should reach 1.0.
    assert mask[int(0.5 * sr)] == 1.0
    assert mask[int(0.3 * sr)] == 1.0


def test_padding_extends_interval():
    sr = 1000
    words = [W("a", 0.5, 0.6)]
    mask_padded = build_mask(words, total_samples=sr, sr=sr, pad_ms=100, xfade_ms=0)
    # With 100ms padding, the interval becomes [0.4, 0.7].
    assert mask_padded[int(0.45 * sr)] == 1.0
    assert mask_padded[int(0.65 * sr)] == 1.0


def test_mask_clipped_to_total_samples():
    sr = 1000
    words = [W("z", 2.0, 3.0)]  # past end of audio
    mask = build_mask(words, total_samples=sr, sr=sr, pad_ms=0, xfade_ms=0)
    assert mask.shape == (sr,)
    assert np.all(mask == 0.0)
