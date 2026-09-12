"""Put separated stems on the decoded source's sample and gain basis."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np


CALIBRATION_VERSION = 1


@dataclass(frozen=True)
class Calibration:
    version: int
    gain: float
    gain_db: float
    raw_error_db: float
    corrected_error_db: float
    applied: bool
    reason: str

    def to_dict(self) -> dict[str, float | int | bool | str]:
        return asdict(self)


def _relative_error_db(error: np.ndarray, reference: np.ndarray) -> float:
    error_power = float(np.mean(np.square(error, dtype=np.float64)))
    reference_power = float(np.mean(np.square(reference, dtype=np.float64)))
    if reference_power <= 0:
        return float("-inf") if error_power <= 0 else float("inf")
    return 10.0 * math.log10(max(error_power / reference_power, 1e-30))


def calibrate_partition(
    original: np.ndarray,
    components: dict[str, np.ndarray],
    *,
    max_abs_gain_db: float = 12.0,
) -> tuple[dict[str, np.ndarray], Calibration]:
    """Fit one gain to a complete stem partition and apply it to every stem.

    A single factor preserves the separator's internal balance and keeps nested
    lead/backing stems on the same basis as their parent vocals estimate.  The
    fit is accepted only when inputs are finite, aligned and improve the sum.
    """
    source = np.asarray(original, dtype=np.float32)
    if not components:
        raise ValueError("at least one component is required")
    arrays = {name: np.asarray(value, dtype=np.float32) for name, value in components.items()}
    if not source.size or any(not value.size for value in arrays.values()):
        raise ValueError("source and components must be non-empty")
    if any(value.shape != source.shape for value in arrays.values()):
        raise ValueError("source and components must share one sample basis")
    if not np.isfinite(source).all() or any(not np.isfinite(value).all() for value in arrays.values()):
        raise ValueError("source and components must contain only finite samples")

    estimate = np.zeros(source.shape, dtype=np.float64)
    for value in arrays.values():
        estimate += value
    source64 = source.astype(np.float64, copy=False)
    denominator = float(np.vdot(estimate.ravel(), estimate.ravel()).real)
    raw_error = _relative_error_db(source64 - estimate, source64)
    if denominator <= 1e-20:
        result = Calibration(CALIBRATION_VERSION, 1.0, 0.0, raw_error, raw_error,
                             False, "component sum is silent")
        return {name: value.copy() for name, value in arrays.items()}, result

    gain = float(np.vdot(source64.ravel(), estimate.ravel()).real / denominator)
    gain_db = 20.0 * math.log10(gain) if gain > 0 else float("-inf")
    corrected_error = _relative_error_db(source64 - gain * estimate, source64)
    accepted = (gain > 0 and abs(gain_db) <= max_abs_gain_db
                and corrected_error < raw_error - 1e-6)
    reason = "least-squares common gain improved reconstruction" if accepted else (
        "common gain outside safe range" if gain <= 0 or abs(gain_db) > max_abs_gain_db
        else "common gain did not improve reconstruction"
    )
    if not accepted:
        gain, gain_db, corrected_error = 1.0, 0.0, raw_error
    calibrated = {name: (value * gain).astype(np.float32) for name, value in arrays.items()}
    return calibrated, Calibration(CALIBRATION_VERSION, gain, gain_db, raw_error,
                                   corrected_error, accepted, reason)
