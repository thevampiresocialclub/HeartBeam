"""Validated, reversible local repairs on the saved instrumental stem."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf

from . import project as P


def _applied(project) -> list[P.InstrumentRepair]:
    return sorted((item for item in project.music_repair.repairs if item.status == "applied"),
                  key=lambda item: (item.start_sample, item.end_sample, item.id))


def create_level_repair(project, root, start_ms: int, end_ms: int, *, gain_db: float,
                        strength: float = 1.0, fade_ms: int = 120) -> P.InstrumentRepair:
    """Create a repair record after resolving milliseconds onto the stem basis."""
    asset = project.asset_by_role("instrumental_stem")
    if not asset or not asset.resolve(root).is_file() or not asset.sha256:
        raise P.ProjectError("Music repair needs the saved lossless instrumental track.")
    from .vocal_mix import _file_info
    path = asset.resolve(root); stat = path.stat()
    sr, channels, count, digest, fmt = _file_info(str(path), stat.st_size, stat.st_mtime_ns)
    if digest != asset.sha256 or fmt not in ("WAV", "WAVEX", "FLAC"):
        raise P.ProjectError("The instrumental track changed or is not lossless. Relink it before repairing music.")
    duration_ms = round(count * 1000 / sr)
    if not 0 <= start_ms < end_ms <= duration_ms:
        raise P.ProjectError("Choose a repair range inside the song.")
    if not 0.0 <= strength <= 1.0 or not 0.0 <= gain_db <= 12.0 or not 0 <= fade_ms <= 2000:
        raise P.ProjectError("Repair level, strength or fade is outside its supported range.")
    start_sample = round(start_ms * sr / 1000)
    end_sample = round(end_ms * sr / 1000)
    if any(start_sample < old.end_sample and end_sample > old.start_sample for old in _applied(project)):
        raise P.ProjectError("That range overlaps an applied repair. Disable it first or choose a separate range.")
    return P.InstrumentRepair(
        id=P.new_id("repair"), source_asset_id=asset.id, source_sha256=digest,
        sample_rate=sr, channels=channels, sample_count=count,
        start_ms=int(start_ms), end_ms=int(end_ms), start_sample=start_sample,
        end_sample=end_sample, gain_db=float(gain_db), strength=float(strength),
        fade_ms=int(fade_ms), source_revision=project.revision,
        provenance={"method_version": 1, "description": "bounded local level correction"},
    )


def apply_repairs(samples: np.ndarray, repairs: list[P.InstrumentRepair], sample_rate: int) -> np.ndarray:
    """Apply smooth gain envelopes; zero gain/strength is an exact bypass."""
    source = np.asarray(samples, dtype=np.float32)
    if source.ndim not in (1, 2) or not source.size or not np.isfinite(source).all():
        raise P.ProjectError("The instrumental track is empty or invalid.")
    out = source.astype(np.float64, copy=True)
    for item in sorted((r for r in repairs if r.status == "applied"), key=lambda r: r.start_sample):
        if item.sample_rate != sample_rate or item.sample_count != len(source):
            raise P.ProjectError("A music repair belongs to a different audio sample basis.")
        start, end = item.start_sample, item.end_sample
        if not 0 <= start < end <= len(source):
            raise P.ProjectError("A music repair range is outside the instrumental track.")
        gain = (10.0 ** (item.gain_db / 20.0) - 1.0) * item.strength
        if gain == 0:
            continue
        width = min(round(item.fade_ms * sample_rate / 1000), (end - start) // 2)
        envelope = np.ones(end - start, dtype=np.float64)
        if width:
            phase = np.linspace(0.0, math.pi, width, endpoint=False)
            ramp = .5 - .5 * np.cos(phase)
            envelope[:width] = ramp
            envelope[-width:] = ramp[::-1]
        factor = 1.0 + gain * envelope
        out[start:end] *= factor[:, None] if out.ndim == 2 else factor
    return out.astype(np.float32)


def effective_instrumental(project, root, source_path: Path, sample_rate: int) -> Path:
    """Return the raw stem or a content-addressed repaired derivative."""
    repairs = _applied(project)
    if not repairs:
        return source_path
    asset = project.asset_by_role("instrumental_stem")
    if not asset or P.file_sha256(source_path) != asset.sha256:
        raise P.ProjectError("The instrumental track changed after its repairs were created.")
    for item in repairs:
        if item.source_asset_id != asset.id or item.source_sha256 != asset.sha256:
            raise P.ProjectError("A music repair belongs to an older instrumental track. Disable it or restore that track.")
    identity = hashlib.sha256(json.dumps([asdict(r) for r in repairs], sort_keys=True).encode()).hexdigest()[:24]
    target = Path(root) / P.CACHE_DIR / f"instrumental-repaired-{identity}.wav"
    if target.is_file():
        return target
    samples, sr = sf.read(str(source_path), dtype="float32", always_2d=True)
    if sr != sample_rate:
        raise P.ProjectError("The instrumental sample rate changed while preparing its repair.")
    result = apply_repairs(samples, repairs, sr)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=target.parent, suffix=".wav"); os.close(fd)
    try:
        sf.write(temporary, result, sr, subtype="FLOAT")
        os.replace(temporary, target)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return target
