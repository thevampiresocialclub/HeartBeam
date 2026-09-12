import numpy as np

from heartbeam.audio_analysis import find_thin_spots


def test_finds_instrumental_only_drop_and_rejects_shared_rest():
    sr = 1000
    t = np.arange(10000, dtype=np.float32) / sr
    original = .2 * np.sin(2 * np.pi * 37 * t)
    instrumental = original.copy()
    instrumental[4000:4800] *= .15
    found = find_thin_spots(original, instrumental, sr, edge_ms=500)
    assert found
    assert found[0].start_ms < 4400 < found[0].end_ms
    assert found[0].metrics["instrumental_local_dip_db"] >= 6

    both = original.copy(); both[4000:4800] *= .15
    assert not find_thin_spots(both, both, sr, edge_ms=500)


def test_short_audio_has_no_suggestions_and_invalid_shapes_fail():
    assert find_thin_spots(np.zeros(10), np.zeros(10), 1000) == []
    try:
        find_thin_spots(np.zeros(1000), np.zeros((1000, 2)), 1000)
    except ValueError as exc:
        assert "sample basis" in str(exc)
    else:
        raise AssertionError("shape mismatch must fail")

