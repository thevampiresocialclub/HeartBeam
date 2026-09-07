"""Section restoration, shared sample-based envelope, and calibrated offline mix.

The compiler keeps knot positions independent of levels. Browser audition can
therefore interpolate two compiled templates while dragging a slider, with no
second implementation of region overlap or transition rules.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from . import project as P


def _ms(value, label):
    if type(value) is not int or value < 0:
        raise P.ProjectError(f"{label} must be non-negative whole milliseconds.")
    return value


def level(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise P.ProjectError("Vocal level must be between 0% and 100%.")
    return float(value)


def validate(mix, duration_ms):
    level(mix.default_value)
    _ms(mix.transition_ms, "Transition")
    if mix.restoration_mode != "clean_to_original":
        raise P.ProjectError("Unsupported vocal restoration mode.")
    end, ids = 0, set()
    for region in sorted(mix.regions, key=lambda r: r.start_ms):
        _ms(region.start_ms, "Start")
        _ms(region.end_ms, "End")
        _ms(region.transition_ms, "Transition")
        level(region.value)
        if not end <= region.start_ms < region.end_ms <= duration_ms or region.id in ids:
            raise P.ProjectError("Vocal regions must have unique IDs, stay inside the audio, and not overlap.")
        end = region.end_ms
        ids.add(region.id)


def insert_region(mix, region, duration_ms):
    """Replace the intersecting range, retaining both outside fragments."""
    candidate = copy.deepcopy(mix)
    kept = []
    for old in candidate.regions:
        if old.id == region.id:
            continue
        if old.end_ms <= region.start_ms or old.start_ms >= region.end_ms:
            kept.append(old)
            continue
        if old.start_ms < region.start_ms:
            left = copy.deepcopy(old)
            left.end_ms = region.start_ms
            kept.append(left)
        if old.end_ms > region.end_ms:
            right = copy.deepcopy(old)
            right.start_ms = region.end_ms
            if old.start_ms < region.start_ms:
                right.id = P.new_id("vr")
            kept.append(right)
    candidate.regions = sorted(kept + [copy.deepcopy(region)], key=lambda r: r.start_ms)
    validate(candidate, duration_ms)
    mix.regions = candidate.regions


def lyric_range(project, *, word_ids=(), line_ids=(), section_id=None):
    chosen = set(word_ids)
    lines = set(line_ids)
    if section_id:
        section = next((s for s in project.sections if s.id == section_id), None)
        if section is None:
            raise P.ProjectError("That lyric section no longer exists.")
        lines.update(section.line_ids)
    chosen.update(w.id for ln, w in project.iter_words() if ln.id in lines and not w.non_sung)
    words = [w for _, w in project.iter_words() if w.id in chosen and not w.non_sung]
    if not words or any(not project.effective_timing(w.id) or not project.effective_timing(w.id).resolved for w in words):
        raise P.ProjectError("Give every selected word a timing before creating a vocal region.")
    times = [project.effective_timing(w.id) for w in words]
    return min(t.start_ms for t in times), max(t.end_ms for t in times), [w.id for w in words]


def refit(project, region_id, duration_ms):
    region = next((r for r in project.vocal_mix.regions if r.id == region_id), None)
    if region is None:
        raise P.ProjectError("Select a vocal region to refit.")
    region = copy.deepcopy(region)
    # Word provenance survives line rewrapping. Deleted words require a new
    # explicit selection, rather than silently shrinking a region.
    if region.source_word_ids and any(project.find_word(w) is None for w in region.source_word_ids):
        raise P.ProjectError("Some source lyrics were deleted. Select the replacement lyrics and create a new region.")
    start, end, words = lyric_range(project, word_ids=region.source_word_ids,
                                    line_ids=() if region.source_word_ids else region.source_line_ids,
                                    section_id=None if region.source_word_ids else region.source_section_id)
    region.start_ms, region.end_ms, region.source_word_ids = start, end, words
    insert_region(project.vocal_mix, region, duration_ms)


def compile_envelope(mix, sample_rate, sample_count):
    """Return [sample_position, coefficient] knots, continuous and bounded.

    Each shared boundary gets the larger adjacent transition, centred there.
    Each half-ramp is capped at half the adjacent span; short regions retain
    a centre value, with no overlapping ramps. Zero requests a one-sample
    transition. Start/end use their inside value (no invented outside audio).
    """
    if sample_count <= 0 or sample_rate <= 0:
        raise P.ProjectError("The audio reference is empty.")
    duration_ms = (sample_count * 1000 + sample_rate - 1) // sample_rate
    validate(mix, duration_ms)
    spans, cursor = [], 0
    for r in sorted(mix.regions, key=lambda r: r.start_ms):
        start = min(sample_count, round(r.start_ms * sample_rate / 1000))
        end = min(sample_count, round(r.end_ms * sample_rate / 1000))
        if start > cursor:
            spans.append((cursor, start, mix.default_value, mix.transition_ms))
        if end > start:
            spans.append((start, end, r.value, r.transition_ms))
        cursor = end
    if cursor < sample_count:
        spans.append((cursor, sample_count, mix.default_value, mix.transition_ms))
    knots = [[0, float(spans[0][2])]]
    for left, right in zip(spans, spans[1:]):
        boundary = left[1]
        half = max(1, max(left[3], right[3]) * sample_rate / 1000) / 2
        a = boundary - min(half, (left[1] - left[0]) / 2)
        b = boundary + min(half, (right[1] - right[0]) / 2)
        knots += [[a, float(left[2])], [b, float(right[2])]]
    knots.append([sample_count, float(spans[-1][2])])
    # Coincident knots are the same value (two ramps meet at a short span's
    # centre). Remove duplicates without changing slope or level.
    return [p for i, p in enumerate(knots) if i == 0 or p[0] != knots[i - 1][0]]


def envelope_array(knots, sample_count):
    return np.interp(np.arange(sample_count), np.array(knots)[:, 0],
                     np.array(knots)[:, 1]).astype(np.float32)


def mix_arrays(clean, original, mix, sample_rate):
    if clean.shape != original.shape or clean.ndim not in (1, 2) or not clean.size:
        raise P.ProjectError("Clean and original references must share a non-empty sample basis.")
    if not np.isfinite(clean).all() or not np.isfinite(original).all():
        raise P.ProjectError("An audio reference contains non-finite samples.")
    env = envelope_array(compile_envelope(mix, sample_rate, len(clean)), len(clean))
    if clean.ndim == 2:
        env = env[:, None]
    # Float64 intermediate avoids subtract/add cancellation at the endpoints.
    out = clean.astype(np.float64) + env * (original.astype(np.float64) - clean)
    return out.astype(np.float32)


def timing_hash(project):
    pairs = [(w.id, asdict(t) if t else None) for _, w in project.iter_words()
             if not w.non_sung for t in [project.effective_timing(w.id)]]
    return hashlib.sha256(json.dumps(pairs, sort_keys=True).encode()).hexdigest()


@lru_cache(maxsize=24)
def _file_info(path, size, mtime):
    info = sf.info(path)
    return info.samplerate, info.channels, info.frames, P.file_sha256(path), info.format


def checked_references(project, root):
    refs = project.vocal_mix.references
    if not refs or not refs.get("source_sha256"):
        raise P.ProjectError("Vocal mixing needs calibrated clean and original audio. Link this song's audio cache or prepare references from its saved stems; the normalized karaoke MP3 cannot be used as the clean reference.")
    result, basis = {}, None
    for role in ("clean_audio", "original_audio"):
        asset = project.asset_by_role(role)
        if not asset or not asset.resolve(root).is_file():
            raise P.ProjectError(f"The {role.replace('_', ' ')} file is missing. Relink the matching reference.")
        path = asset.resolve(root)
        stat = path.stat()
        sr, channels, count, digest, fmt = _file_info(str(path), stat.st_size, stat.st_mtime_ns)
        expected = refs.get(role, {})
        if fmt not in ("WAV", "WAVEX", "FLAC") or expected.get("sha256") != digest or (basis and basis != (sr, channels, count)):
            raise P.ProjectError("Audio calibration no longer matches these files. Prepare or link matching lossless references again.")
        basis = (sr, channels, count)
        result[role] = path
    if not basis[2]:
        raise P.ProjectError("Audio references are empty.")
    return result, basis


def bind_references(project, *, source_sha256, recipe=None):
    refs = {"source_sha256": source_sha256, "timing_hash": timing_hash(project),
            "timing_revision": project.revision, "recipe": recipe or {}}
    for role in ("clean_audio", "original_audio"):
        asset = project.asset_by_role(role)
        if asset is None:
            raise P.ProjectError("Both original and clean references are required.")
        refs[role] = {"asset_id": asset.id, "sha256": asset.sha256}
    project.vocal_mix.references = refs


def preview_payload(project, root, register, selection=None):
    paths, (sr, channels, count) = checked_references(project, root)
    mix = project.vocal_mix
    data = {"revision": project.revision, "sample_rate": sr, "sample_count": count,
            "clean": register(paths["clean_audio"], f"mix/{project.id}/clean"),
            "original": register(paths["original_audio"], f"mix/{project.id}/original"),
            "knots": compile_envelope(mix, sr, count), "regions": [asdict(r) for r in mix.regions],
            "default_value": mix.default_value, "selection": selection}
    if selection:
        templates = []
        for value in (0., 1.):
            candidate = copy.deepcopy(mix)
            if selection.get("song"):
                candidate.default_value = value
                candidate.transition_ms = selection.get("transition_ms", candidate.transition_ms)
            else:
                region = P.VocalRegion(selection.get("region_id") or "preview", selection["start_ms"],
                                       selection["end_ms"], value, selection.get("transition_ms", 40))
                insert_region(candidate, region, P.seconds_to_ms(count / sr))
            templates.append(compile_envelope(candidate, sr, count))
        data["templates"] = templates
    return data


def rebuild_clean(project, root, recipe=None):
    """Rebuild from cached stems and effective timing. Never runs separation."""
    from . import mask as M
    from .mix import mix, mix_replace
    from .project_preview import current_timings
    recipe = recipe or project.vocal_mix.references.get("recipe")
    if not recipe:
        raise P.ProjectError("This older cache has no saved mix recipe. Choose a recipe explicitly when preparing references.")
    arrays, basis = {}, None
    for role in ("original_audio", "lead_stem", "backing_stem", "instrumental_stem"):
        asset = project.asset_by_role(role)
        if asset is None or not asset.resolve(root).is_file():
            raise P.ProjectError(f"Rebuilding needs the saved {role.replace('_', ' ')}.")
        arr, sr = sf.read(str(asset.resolve(root)), dtype="float32", always_2d=True)
        if basis and (sr, arr.shape) != basis:
            raise P.ProjectError("Saved stems and original must have the same sample rate, channels and sample count.")
        basis = (sr, arr.shape)
        arrays[role] = arr
    sr, shape = basis
    timed = current_timings(project, P.seconds_to_ms(shape[0] / sr))
    words = [w for ln in timed.lines for w in ln.words]
    mask = M.build_mask(words, shape[0], sr, recipe.get("pad_ms", 120),
                        recipe.get("crossfade_ms", 60), recipe.get("merge_gap_ms", 500))
    if recipe.get("energy_threshold", 0) > 0:
        energy = M.build_energy_mask(arrays["lead_stem"], sr,
                    window_ms=recipe.get("energy_window_ms", 30),
                    threshold_rel=recipe["energy_threshold"],
                    xfade_ms=recipe.get("crossfade_ms", 60))
        mask = M.combine_masks(mask, energy)
    if recipe.get("mix_strategy", "subtract") == "replace":
        clean = mix_replace(arrays["original_audio"], arrays["instrumental_stem"], arrays["backing_stem"], mask, clip=False)
    else:
        clean = mix(arrays["original_audio"], arrays["lead_stem"], mask,
                    recipe.get("vocal_gain", 1), arrays["backing_stem"], recipe.get("backing_boost", 0), clip=False)
    digest = hashlib.sha256(clean.tobytes()).hexdigest()
    path = root / P.AUDIO_DIR / f"clean-{digest[:20]}.wav"
    if not path.exists():
        sf.write(str(path), clean, sr, subtype="FLOAT")
    # Content-addressed files remain available to undo and recovery snapshots.
    project.assets = [a for a in project.assets if a.role != "clean_audio"]
    asset = P.add_asset(project, root, path, "clean_audio", copy_into_project=False)
    asset.path, asset.external = str(path.relative_to(root)), False
    asset.sample_rate, asset.channels, asset.sample_count = sr, shape[1], shape[0]
    asset.duration_ms = P.seconds_to_ms(shape[0] / sr)
    original = project.asset_by_role("original_audio")
    bind_references(project, source_sha256=original.sha256, recipe=recipe)
    return path


def master(samples, sr, *, target_lufs=-16., peak_db=-1.):
    """One final loudness/4x oversampled peak stage, after the whole mix."""
    import pyloudnorm as pyln
    from scipy.signal import resample_poly
    out = samples.astype(np.float64)
    gain = 1.
    if target_lufs is not None and len(out) >= int(.4 * sr) and np.any(out):
        loudness = pyln.Meter(sr).integrated_loudness(out)
        if math.isfinite(loudness):
            gain = 10 ** ((target_lufs - loudness) / 20)
    peak = float(np.max(np.abs(resample_poly(out, 4, 1, axis=0)))) if out.size else 0.
    if peak:
        gain = min(gain, 10 ** (peak_db / 20) / peak)
    return (out * gain).astype(np.float32)


def render_mix(project, root, *, mastered=True):
    paths, (sr, _, _) = checked_references(project, root)
    spec = {"references": project.vocal_mix.references, "mix": asdict(project.vocal_mix), "mastered": mastered}
    key = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:24]
    destination = root / P.CACHE_DIR / f"vocal-mix-{key}.wav"
    if not destination.exists():
        clean = sf.read(str(paths["clean_audio"]), dtype="float32", always_2d=True)[0]
        original = sf.read(str(paths["original_audio"]), dtype="float32", always_2d=True)[0]
        result = mix_arrays(clean, original, project.vocal_mix, sr)
        if mastered:
            result = master(result, sr)
        destination.parent.mkdir(parents=True, exist_ok=True)
        import os, tempfile
        fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".wav")
        os.close(fd)
        try:
            sf.write(temporary, result, sr, subtype="FLOAT")
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return destination
