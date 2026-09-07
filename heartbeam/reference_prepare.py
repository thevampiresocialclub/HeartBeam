"""Explicit migration of legacy stems to a common, pre-mastering basis."""
import hashlib
from pathlib import Path
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly
from math import gcd
from . import project as P
from .vocal_mix import rebuild_clean


def prepare_legacy(project, root, original_path, stems_dir, recipe):
    sources = {"original_audio": original_path, "lead_stem": stems_dir / "lead.wav",
               "backing_stem": stems_dir / "backing.wav", "instrumental_stem": stems_dir / "instrumental.wav"}
    arrays, sr, channels = {}, None, None
    for role in ("lead_stem", "backing_stem", "instrumental_stem", "original_audio"):
        path = sources[role]
        if not path.is_file():
            raise P.ProjectError(f"Missing {role.replace('_', ' ')}: {path}")
        audio, actual_sr = sf.read(str(path), dtype="float32", always_2d=True)
        sr = sr or actual_sr
        channels = channels or audio.shape[1]
        if audio.shape[1] != channels or not np.isfinite(audio).all():
            raise P.ProjectError("Original and stems must have matching channels and finite samples.")
        if actual_sr != sr:
            divisor = gcd(actual_sr, sr)
            audio = resample_poly(audio, sr // divisor, actual_sr // divisor, axis=0).astype(np.float32)
        arrays[role] = audio
    lengths = [len(a) for a in arrays.values()]
    if not min(lengths) or max(lengths) - min(lengths) > round(.030 * sr):
        raise P.ProjectError("Original and stems differ by more than 30 ms. Choose matching files from the same run.")
    count = min(lengths)
    for role, audio in arrays.items():
        audio = audio[:count]
        digest = hashlib.sha256(audio.tobytes()).hexdigest()[:20]
        path = root / P.AUDIO_DIR / f"{role}-{digest}.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            sf.write(str(path), audio, sr, subtype="FLOAT")
        project.assets = [a for a in project.assets if a.role != role]
        asset = P.add_asset(project, root, path, role, copy_into_project=False)
        asset.path, asset.external = str(path.relative_to(root)), False
        asset.sample_rate, asset.channels, asset.sample_count = sr, channels, count
        asset.duration_ms = P.seconds_to_ms(count / sr)
    project.provenance.settings["legacy_reference_preparation"] = {
        "source_sha256": P.file_sha256(original_path), "trimmed_tail_samples": max(lengths) - count,
        "sample_rate": sr, "recipe": recipe}
    return rebuild_clean(project, root, recipe)
