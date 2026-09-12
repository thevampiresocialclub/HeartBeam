"""Build a local, lossless listening pack for recorded-instrument recovery.

This is an offline experiment. It never edits the project and never promotes a
candidate into the product's accepted repair recipe.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np
import soundfile as sf

from heartbeam import audio_analysis as A, audio_calibration as C
from heartbeam import instrument_repair as R, project as P, separate as S, vocal_mix as V
from heartbeam.io import load_audio
from heartbeam.paths import separator_dir


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alternate(excerpt: np.ndarray, sr: int, model: str) -> tuple[np.ndarray, dict]:
    with tempfile.TemporaryDirectory(prefix="heartbeam_repair_benchmark_") as raw:
        folder = Path(raw)
        source = folder / "excerpt.wav"
        sf.write(source, excerpt, sr, subtype="FLOAT")
        separator = S._get_separator(model, "auto", str(folder))
        outputs = [str(Path(value) if Path(value).is_absolute() else folder / value)
                   for value in separator.separate(str(source))]
        classified = S._classify_outputs(outputs)
        if "instrumental" not in classified or "vocals" not in classified:
            raise RuntimeError(f"alternate model produced unexpected outputs: {outputs}")
        instrumental, _ = load_audio(classified["instrumental"], sr=sr, mono=False)
        vocals, _ = load_audio(classified["vocals"], sr=sr, mono=False)
        n = min(len(excerpt), len(instrumental), len(vocals))
        if n != len(excerpt):
            raise RuntimeError("Alternate separator returned incomplete audio; no candidate was produced.")
        calibrated, report = C.calibrate_partition(
            excerpt[:n], {"instrumental": instrumental[:n], "vocals": vocals[:n]})
        result = np.zeros_like(excerpt)
        result[:n] = calibrated["instrumental"]
        model_path = separator_dir() / model
        return result, {
            "model": model,
            "model_sha256": _hash(model_path) if model_path.is_file() else None,
            "calibration": report.to_dict(),
            "output_samples": n,
        }


def _comparison_match(reference: np.ndarray, candidate: np.ndarray, context: np.ndarray) -> tuple[np.ndarray, float]:
    r = float(np.mean(np.square(reference[context], dtype=np.float64)))
    c = float(np.mean(np.square(candidate[context], dtype=np.float64)))
    gain = np.sqrt(r / c) if r > 0 and c > 0 else 1.0
    gain = float(np.clip(gain, 10 ** (-3 / 20), 10 ** (3 / 20)))
    return (candidate * gain).astype(np.float32), gain


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--model", action="append",
                        help="repeat for conservative multi-model consensus")
    parser.add_argument("--start-ms", type=int)
    parser.add_argument("--end-ms", type=int)
    parser.add_argument("--context-ms", type=int, default=3000)
    parser.add_argument("--strength", type=float, default=1.0)
    args = parser.parse_args(argv)
    project = P.load_project(args.project)
    roles = {}
    sr = None
    for role in ("original_audio", "instrumental_stem", "lead_stem", "backing_stem"):
        asset = project.asset_by_role(role)
        if not asset or not asset.resolve(args.project).is_file():
            raise P.ProjectError(f"project is missing {role}")
        if P.file_sha256(asset.resolve(args.project)) != asset.sha256:
            raise P.ProjectError(f"project audio changed: {role}")
        value, rate = sf.read(asset.resolve(args.project), dtype="float32", always_2d=True)
        if sr is not None and (rate != sr or value.shape != roles["original_audio"].shape):
            raise P.ProjectError("project audio does not share one sample basis")
        sr = rate; roles[role] = value
    if args.start_ms is None or args.end_ms is None:
        hints = A.find_thin_spots(roles["original_audio"], roles["instrumental_stem"], sr, limit=1)
        if not hints:
            raise RuntimeError("the detector found no candidate range")
        start_ms, end_ms = hints[0].start_ms, hints[0].end_ms
    else:
        start_ms, end_ms = args.start_ms, args.end_ms
    song_samples = len(roles["original_audio"])
    focus_start = round(start_ms * sr / 1000); focus_end = round(end_ms * sr / 1000)
    pad = round(args.context_ms * sr / 1000)
    excerpt_start, excerpt_end = max(0, focus_start - pad), min(song_samples, focus_end + pad)
    excerpt = {key: value[excerpt_start:excerpt_end] for key, value in roles.items()}
    # Legacy projects can predate common-gain calibration. Normalize their
    # complete partition in memory before comparing it with alternate models.
    calibrated, baseline_calibration = C.calibrate_partition(
        excerpt["original_audio"],
        {role: excerpt[role] for role in ("instrumental_stem", "lead_stem", "backing_stem")})
    if baseline_calibration.corrected_error_db > -20:
        raise P.ProjectError("Saved stems do not reconstruct the source closely enough for a calibrated recovery comparison.")
    excerpt.update(calibrated)
    models = args.model or ["model_bs_roformer_ep_317_sdr_12.9755.ckpt"]
    alternates, model_info = [], []
    for model in models:
        value, info = _alternate(excerpt["original_audio"], sr, model)
        alternates.append(value); model_info.append(info)
        S.release_models()
    local_start, local_end = focus_start - excerpt_start, focus_end - excerpt_start
    ri, rl, rb, diagnostics = R.recorded_reallocation(
        excerpt["instrumental_stem"], excerpt["lead_stem"], excerpt["backing_stem"],
        alternates, sr, start_sample=local_start, end_sample=local_end,
        strength=args.strength)
    envelope = V.envelope_array(V.compile_envelope(project.vocal_mix, sr, song_samples), song_samples)[excerpt_start:excerpt_end, None]
    baseline = (excerpt["instrumental_stem"] + excerpt["lead_stem"] * envelope
                + excerpt["backing_stem"] * project.vocal_mix.backing_value).astype(np.float32)
    repaired = (ri + rl * envelope + rb * project.vocal_mix.backing_value).astype(np.float32)
    # Compare the same smooth instrumental-only lift offered in the product.
    lift = P.InstrumentRepair(
        id="benchmark-lift", source_asset_id="benchmark", source_sha256="benchmark",
        sample_rate=sr, channels=excerpt["instrumental_stem"].shape[1],
        sample_count=len(baseline), start_ms=round(local_start * 1000 / sr),
        end_ms=round(local_end * 1000 / sr), start_sample=local_start,
        end_sample=local_end, gain_db=2.0, fade_ms=120)
    local_music = R.apply_repairs(excerpt["instrumental_stem"], [lift], sr)
    local = (local_music + excerpt["lead_stem"] * envelope
             + excerpt["backing_stem"] * project.vocal_mix.backing_value).astype(np.float32)
    context = np.ones(len(baseline), dtype=bool); context[local_start:local_end] = False
    repaired, repaired_gain = _comparison_match(baseline, repaired, context)
    matched_alternates = [_comparison_match(baseline, value, context) for value in alternates]
    args.out.mkdir(parents=True, exist_ok=True)
    files = {
        "original-context.wav": excerpt["original_audio"],
        "baseline.wav": baseline,
        "level-plus-2db.wav": local,
        "reallocated.wav": repaired,
        "recorded-donor.wav": ri - excerpt["instrumental_stem"],
    }
    for index, (value, _) in enumerate(matched_alternates, 1):
        files[f"alternate-{index}-instrumental.wav"] = value
    for name, value in files.items():
        sf.write(args.out / name, value, sr, subtype="FLOAT")
    focus = slice(local_start, local_end)
    donor = ri - excerpt["instrumental_stem"]
    donor_rms = float(np.sqrt(np.mean(np.square(donor[focus], dtype=np.float64))))
    baseline_rms = float(np.sqrt(np.mean(np.square(baseline[focus], dtype=np.float64))))
    original_sum = excerpt["instrumental_stem"] + excerpt["lead_stem"] + excerpt["backing_stem"]
    repaired_sum = ri + rl + rb
    manifest = {
        "format": "heartbeam-instrument-repair-benchmark", "version": 4,
        "project_id": project.id, "project_revision": project.revision,
        "source_sha256": project.asset_by_role("original_audio").sha256,
        "focus_ms": [start_ms, end_ms], "excerpt_ms": [round(excerpt_start * 1000 / sr), round(excerpt_end * 1000 / sr)],
        "models": model_info, "reallocation": diagnostics,
        "baseline_calibration": baseline_calibration.to_dict(),
        "focus_metrics": {
            "baseline_rms": baseline_rms, "donor_rms": donor_rms,
            "donor_to_baseline_db": float(20 * np.log10(max(donor_rms / baseline_rms, 1e-12))) if baseline_rms else None,
            "max_full-fader_stem_sum_error": float(np.max(np.abs(repaired_sum - original_sum))),
        },
        "comparison_gains": {"reallocated": repaired_gain,
                             "alternates": [gain for _, gain in matched_alternates]},
        "files": {name: P.file_sha256(args.out / name) for name in files},
        "warning": "Experimental listening material; no candidate was applied to the project.",
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
