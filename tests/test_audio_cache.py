"""P01.3 tests: the lossless audio cache.

Acceptance criterion: "subsequent read/preview operations reuse valid cached
audio and detect an altered source or setting."
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from heartbeam import audio_cache as AC

SR = 8000


def _tone(freq: float, seconds: float = 0.25, channels: int = 2) -> np.ndarray:
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    mono = np.sin(2 * np.pi * freq * t).astype(np.float32)
    if channels == 1:
        return mono
    return np.stack([mono, mono * 0.5], axis=1)


def _arrays() -> dict[str, np.ndarray]:
    return {
        "original": _tone(220),
        "lead": _tone(440),
        "backing": _tone(330),
        "instrumental": _tone(110),
        # Deliberately beyond +/-1 so the "unclipped" promise is testable.
        "clean": _tone(220) * 1.4,
    }


SETTINGS = {"separator": "rock", "vocal_gain": 1.5, "pad_ms": 180.0}


def _write(tmp_path, **kw):
    return AC.write_cache(
        tmp_path, _arrays(), sample_rate=SR,
        source_sha256=kw.pop("source_sha256", "abc123"),
        settings=kw.pop("settings", SETTINGS), **kw,
    )


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


def test_write_then_load_round_trips(tmp_path):
    manifest = _write(tmp_path)
    loaded = AC.load_cache(tmp_path)
    assert loaded is not None
    assert loaded.source_sha256 == manifest.source_sha256
    assert set(loaded.entries) == set(AC.ROLES)
    assert loaded.sample_rate == SR


def test_cached_audio_reads_back_accurately(tmp_path):
    arrays = _arrays()
    AC.write_cache(tmp_path, arrays, sample_rate=SR,
                   source_sha256="h", settings=SETTINGS)
    manifest = AC.load_cache(tmp_path)
    for role, original in arrays.items():
        data, sr = AC.read_role(tmp_path, manifest, role)
        assert sr == SR
        assert data.shape == original.shape
        np.testing.assert_allclose(data, original, atol=1e-6)


def test_clean_reference_is_stored_unclipped(tmp_path):
    """The section mixer needs headroom above 0 dBFS preserved."""
    AC.write_cache(tmp_path, _arrays(), sample_rate=SR,
                   source_sha256="h", settings=SETTINGS)
    manifest = AC.load_cache(tmp_path)
    clean, _ = AC.read_role(tmp_path, manifest, "clean")
    assert float(np.max(np.abs(clean))) > 1.0, "clean reference must not be clipped"


def test_flac_format_is_supported(tmp_path):
    AC.write_cache(tmp_path, {"original": _tone(220)}, sample_rate=SR,
                   source_sha256="h", settings=SETTINGS, audio_format="flac")
    manifest = AC.load_cache(tmp_path)
    assert manifest.audio_format == "flac"
    assert (tmp_path / "original.flac").exists()
    data, _ = AC.read_role(tmp_path, manifest, "original")
    np.testing.assert_allclose(data, _tone(220), atol=1e-4)


def test_unknown_format_is_rejected(tmp_path):
    with pytest.raises(AC.CacheError):
        AC.write_cache(tmp_path, {"original": _tone(1)}, sample_rate=SR,
                       source_sha256="h", settings=SETTINGS, audio_format="mp3")


# ---------------------------------------------------------------------------
# validity
# ---------------------------------------------------------------------------


def test_valid_cache_is_reused(tmp_path):
    _write(tmp_path)
    manifest = AC.load_cache(tmp_path)
    ok, reason = AC.is_valid(manifest, source_sha256="abc123",
                             settings=SETTINGS, cache_dir=tmp_path)
    assert ok, reason


def test_altered_source_invalidates_the_cache(tmp_path):
    _write(tmp_path)
    manifest = AC.load_cache(tmp_path)
    ok, reason = AC.is_valid(manifest, source_sha256="DIFFERENT",
                             settings=SETTINGS, cache_dir=tmp_path)
    assert not ok
    assert "source audio changed" in reason


def test_changed_settings_invalidate_the_cache(tmp_path):
    _write(tmp_path)
    manifest = AC.load_cache(tmp_path)
    changed = dict(SETTINGS, vocal_gain=1.7)
    ok, reason = AC.is_valid(manifest, source_sha256="abc123",
                             settings=changed, cache_dir=tmp_path)
    assert not ok
    assert "processing settings changed" in reason


def test_settings_fingerprint_ignores_key_order(tmp_path):
    a = AC.settings_fingerprint({"a": 1, "b": 2})
    b = AC.settings_fingerprint({"b": 2, "a": 1})
    assert a == b


def test_missing_file_on_disk_invalidates_the_cache(tmp_path):
    _write(tmp_path)
    manifest = AC.load_cache(tmp_path)
    (tmp_path / manifest.entries["lead"].path).unlink()
    ok, reason = AC.is_valid(manifest, source_sha256="abc123",
                             settings=SETTINGS, cache_dir=tmp_path)
    assert not ok
    assert "missing on disk" in reason


def test_missing_role_invalidates_the_cache(tmp_path):
    AC.write_cache(tmp_path, {"original": _tone(220)}, sample_rate=SR,
                   source_sha256="h", settings=SETTINGS)
    manifest = AC.load_cache(tmp_path)
    ok, reason = AC.is_valid(manifest, source_sha256="h", settings=SETTINGS)
    assert not ok
    assert "missing roles" in reason


# ---------------------------------------------------------------------------
# interruption
# ---------------------------------------------------------------------------


def test_interrupted_write_does_not_look_like_a_valid_cache(tmp_path):
    """A run killed mid-write leaves audio but no manifest."""
    _write(tmp_path)
    (tmp_path / AC.MANIFEST_NAME).unlink()
    assert (tmp_path / "lead.wav").exists(), "audio files remain on disk"
    assert AC.load_cache(tmp_path) is None
    ok, reason = AC.is_valid(None, source_sha256="abc123", settings=SETTINGS)
    assert not ok and "no cache manifest" in reason


def test_failed_rewrite_does_not_leave_the_old_manifest(tmp_path, monkeypatch):
    """A rewrite that dies partway must not leave a manifest describing stale audio."""
    _write(tmp_path)
    assert AC.load_cache(tmp_path) is not None

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(AC.sf, "write", boom)
    with pytest.raises(OSError):
        AC.write_cache(tmp_path, _arrays(), sample_rate=SR,
                       source_sha256="new", settings=SETTINGS)
    assert AC.load_cache(tmp_path) is None, (
        "the stale manifest must be gone, so the cache reads as absent"
    )


def test_corrupt_manifest_reads_as_absent(tmp_path):
    _write(tmp_path)
    (tmp_path / AC.MANIFEST_NAME).write_text("{ not json", encoding="utf-8")
    assert AC.load_cache(tmp_path) is None


def test_unknown_schema_version_reads_as_absent(tmp_path):
    _write(tmp_path)
    path = tmp_path / AC.MANIFEST_NAME
    data = json.loads(path.read_text(encoding="utf-8"))
    data["schema_version"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    assert AC.load_cache(tmp_path) is None


def test_read_role_rejects_an_unknown_role(tmp_path):
    _write(tmp_path)
    manifest = AC.load_cache(tmp_path)
    with pytest.raises(AC.CacheError):
        AC.read_role(tmp_path, manifest, "vocals_but_not_really")
