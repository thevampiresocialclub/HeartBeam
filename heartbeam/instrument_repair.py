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
from scipy import signal

from . import project as P


def recorded_reallocation(instrumental: np.ndarray, lead: np.ndarray,
                          backing: np.ndarray, alternate_instrumental,
                          sample_rate: int, *, start_sample: int = 0,
                          end_sample: int | None = None, strength: float = 1.0,
                          fade_ms: int = 120, fft_size: int = 2048,
                          hop_size: int = 512) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict]:
    """Move alternate-model-supported material out of removed vocal stems.

    The donor is always filtered from the current lead/backing recordings. The
    alternate estimate supplies evidence and never gets mixed into the song,
    which preserves the original performance and exact stem accounting.
    """
    alternate_values = (list(alternate_instrumental)
                        if isinstance(alternate_instrumental, (list, tuple))
                        else [alternate_instrumental])
    if not alternate_values:
        raise P.ProjectError("Recovery needs at least one alternate instrumental estimate.")
    arrays = [np.asarray(value, dtype=np.float32)
              for value in (instrumental, lead, backing, *alternate_values)]
    if any(value.shape != arrays[0].shape for value in arrays[1:]) or arrays[0].ndim not in (1, 2):
        raise P.ProjectError("Recovery tracks must share one mono or multichannel sample basis.")
    if not arrays[0].size or any(not np.isfinite(value).all() for value in arrays):
        raise P.ProjectError("Recovery tracks must be non-empty and finite.")
    if sample_rate <= 0 or not 0.0 <= strength <= 1.0:
        raise P.ProjectError("Recovery sample rate or strength is invalid.")
    if (type(fft_size) is not int or fft_size < 2 or type(hop_size) is not int
            or not 0 < hop_size <= fft_size // 2 or not 0 <= fade_ms <= 2000):
        raise P.ProjectError("Recovery window, hop or fade is invalid.")
    n = len(arrays[0]); end_sample = n if end_sample is None else end_sample
    if not 0 <= start_sample < end_sample <= n:
        raise P.ProjectError("Recovery range is outside the audio.")
    if strength == 0:
        return arrays[0].copy(), arrays[1].copy(), arrays[2].copy(), {
            "version": 2, "donor_rms": 0.0, "active_fraction": 0.0,
            "strength": 0.0, "alternate_model_count": len(alternate_values),
        }

    was_mono = arrays[0].ndim == 1
    work = [value[:, None] if value.ndim == 1 else value for value in arrays]
    music, lead_audio, backing_audio, *alternates = work
    donors_l, donors_b, active = [], [], []
    nperseg = min(fft_size, max(2, n))
    if n == 1:
        work = [np.pad(value, ((0, 1), (0, 0))) for value in work]
        music, lead_audio, backing_audio, *alternates = work
    noverlap = nperseg - min(hop_size, max(1, nperseg // 2))
    for channel in range(music.shape[1]):
        spectra = []
        for value in (music, lead_audio, backing_audio, *alternates):
            _, times, z = signal.stft(value[:, channel], fs=sample_rate,
                                      nperseg=nperseg, noverlap=noverlap,
                                      boundary="zeros", padded=True)
            spectra.append(z)
        zi, zl, zb, *alternate_spectra = spectra
        zv = zl + zb
        ai, av = np.abs(zi), np.abs(zv)
        donor_available = np.abs(zl) + np.abs(zb)
        masks = []
        for za in alternate_spectra:
            aa = np.abs(za)
            # Every alternate accompaniment must exceed the current one and
            # agree in phase with material actually recorded in removed stems.
            excess = np.maximum(aa - 1.15 * ai, 0.0)
            coherence = np.clip(np.real(za * np.conj(zv)) /
                                np.maximum(aa * av, 1e-10), 0.0, 1.0)
            # Bound the transferred amplitude by the actual alternate excess.
            # Dividing by aa amplifies tiny shared model leaks: a 10% vocal
            # residue could otherwise authorize moving 85% of the full vocal.
            # Use the sum of donor magnitudes so cancellation between lead and
            # backing cannot hide large transfers on independent faders.
            candidate = np.clip(excess * coherence ** 2 /
                                np.maximum(donor_available, 1e-8), 0.0, .85)
            alternate_floor = np.maximum(1e-6, np.max(aa, axis=0, keepdims=True) * 1e-3)
            candidate *= aa >= alternate_floor
            masks.append(candidate)
        # Intersection is intentionally conservative: one dissenting model
        # removes the bin instead of averaging a guess into the accompaniment.
        mask = np.minimum.reduce(masks)
        frame_samples = np.rint(times * sample_rate).astype(np.int64)
        mask[:, (frame_samples < start_sample) | (frame_samples >= end_sample)] = 0.0
        donors = []
        for stem in (zl, zb):
            _, donor = signal.istft(stem * mask, fs=sample_rate,
                                    nperseg=nperseg, noverlap=noverlap,
                                    input_onesided=True, boundary=True)
            donors.append(np.pad(donor[:n], (0, max(0, n - len(donor))))[:n])
        donors_l.append(donors[0]); donors_b.append(donors[1])
        active.append(float(np.mean(mask > .05)))
    donor_l = np.stack(donors_l, axis=1)
    donor_b = np.stack(donors_b, axis=1)
    support = np.zeros(n, dtype=np.float64); support[start_sample:end_sample] = 1.0
    width = min(round(fade_ms * sample_rate / 1000), (end_sample - start_sample) // 2)
    if width:
        phase = np.linspace(0.0, math.pi, width, endpoint=False)
        ramp = .5 - .5 * np.cos(phase)
        support[start_sample:start_sample + width] = ramp
        support[end_sample - width:end_sample] = ramp[::-1]
    donor_l *= (support * strength)[:, None]
    donor_b *= (support * strength)[:, None]
    donor = donor_l + donor_b
    repaired_i = music[:n].astype(np.float64) + donor
    repaired_l = lead_audio[:n].astype(np.float64) - donor_l
    repaired_b = backing_audio[:n].astype(np.float64) - donor_b
    result = [value.astype(np.float32) for value in (repaired_i, repaired_l, repaired_b)]
    if was_mono:
        result = [value[:, 0] for value in result]
    diagnostics = {
        "version": 2,
        "donor_rms": float(np.sqrt(np.mean(donor ** 2))),
        "lead_donor_rms": float(np.sqrt(np.mean(donor_l ** 2))),
        "backing_donor_rms": float(np.sqrt(np.mean(donor_b ** 2))),
        "active_fraction": float(np.mean(active)),
        "strength": strength,
        "alternate_model_count": len(alternates),
    }
    return *result, diagnostics


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
