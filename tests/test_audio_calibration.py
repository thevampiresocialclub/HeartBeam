import numpy as np
import pytest

from heartbeam.audio_calibration import calibrate_partition


def test_common_gain_recovers_source_and_preserves_component_balance():
    t = np.arange(8000, dtype=np.float32) / 8000
    instrumental = .2 * np.sin(2 * np.pi * 220 * t)
    vocals = .1 * np.sin(2 * np.pi * 331 * t)
    original = instrumental + vocals
    scaled = {"instrumental": instrumental / 1.25, "vocals": vocals / 1.25}
    result, report = calibrate_partition(original, scaled)
    assert report.applied and report.gain == pytest.approx(1.25, rel=1e-6)
    np.testing.assert_allclose(result["instrumental"] + result["vocals"], original, atol=1e-6)
    np.testing.assert_allclose(result["instrumental"], instrumental, atol=1e-6)
    np.testing.assert_allclose(result["vocals"], vocals, atol=1e-6)


def test_calibration_rejects_silent_partition_without_inventing_audio():
    original = np.ones((100, 2), dtype=np.float32)
    silent = np.zeros_like(original)
    result, report = calibrate_partition(original, {"instrumental": silent})
    assert not report.applied and report.gain == 1
    np.testing.assert_array_equal(result["instrumental"], silent)


def test_calibration_rejects_misaligned_or_nonfinite_audio():
    with pytest.raises(ValueError, match="sample basis"):
        calibrate_partition(np.ones(8), {"part": np.ones(7)})
    with pytest.raises(ValueError, match="finite"):
        calibrate_partition(np.ones(8), {"part": np.full(8, np.nan)})
