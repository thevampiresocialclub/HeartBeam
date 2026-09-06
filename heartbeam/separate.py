"""
3-stem source separation. Wraps audio-separator.

Returns a dict with instrumental, lead, and backing stems as float32 ndarrays,
all sharing the same sample rate as the original audio.

The audio-separator library auto-downloads model checkpoints into a local cache
on first use. ML imports are deferred so the rest of the package (timings,
mask, mix, ASS writer) can be imported and tested without torch.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from .io import load_audio
from .models import PRESETS
from .paths import separator_dir

log = logging.getLogger(__name__)

# Cache one Separator instance per (model(s), device) — re-running is much faster.
_SEPARATOR_CACHE: dict[tuple, Any] = {}


def release_models() -> None:
    """Drop cached separator instances and free CUDA memory.

    Call this between heavy ML stages (e.g. after separation, before alignment) on
    low-VRAM GPUs to avoid OOM when the next stage's model loads.
    """
    _SEPARATOR_CACHE.clear()
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()
    except ImportError:
        pass


def _get_separator(
    model_filename: str | tuple[str, ...],
    device: str,
    output_dir: str,
    ensemble_algorithm: str = "uvr_max_spec",
):
    from audio_separator.separator import Separator  # deferred import

    key = (model_filename if isinstance(model_filename, str) else tuple(model_filename),
           device)
    if key not in _SEPARATOR_CACHE:
        # Pin the checkpoint cache. audio-separator's default is the literal
        # POSIX string "/tmp/audio-separator-models/", which on Windows resolves
        # against the *current drive* — so a pre-seeded cache is missed (and ~2 GB
        # re-downloaded) whenever the working directory moves to another volume.
        model_dir = separator_dir()
        model_dir.mkdir(parents=True, exist_ok=True)
        kwargs: dict[str, Any] = dict(
            output_dir=output_dir,
            output_format="WAV",
            log_level=logging.WARNING,
            model_file_dir=str(model_dir),
        )
        if not isinstance(model_filename, str):
            kwargs["ensemble_algorithm"] = ensemble_algorithm
        sep = Separator(**kwargs)
        # Separator has no device argument — it picks one in setup_torch_device().
        # Report what it actually chose, since on a CPU-only machine this is the
        # difference between 90 seconds and 45 minutes.
        log.info("separator device: %s (models in %s)",
                 getattr(sep, "torch_device", "unknown"), model_dir)
        # audio-separator accepts a list for ensemble mode.
        sep.load_model(
            model_filename=list(model_filename) if not isinstance(model_filename, str)
            else model_filename
        )
        _SEPARATOR_CACHE[key] = sep
    else:
        _SEPARATOR_CACHE[key].output_dir = output_dir
    return _SEPARATOR_CACHE[key]


def _classify_outputs(paths: list[str]) -> dict[str, str]:
    """Map audio-separator output filenames to logical stem names by keyword."""
    out: dict[str, str] = {}
    for p in paths:
        name = Path(p).name.lower()
        # Instrumental keywords first (must beat the vocals branch on '(No Vocals)').
        if "instrumental" in name or "no_vocals" in name or "no vocals" in name:
            out["instrumental"] = p
        elif "lead" in name or "main_vocal" in name:
            out["lead"] = p
        elif "back" in name or "harmon" in name:
            out["backing"] = p
        elif "vocals" in name or "vocal" in name:
            out["vocals"] = p
        # htdemucs 4-stem: capture bass/drums/other so the caller can sum them.
        elif "(bass)" in name or "_bass" in name:
            out["bass"] = p
        elif "(drums)" in name or "_drums" in name:
            out["drums"] = p
        elif "(other)" in name or "_other" in name:
            out["other"] = p
    return out


def _synthesize_instrumental_from_4stem(
    classified: dict[str, str], out_dir: str, sr: int
) -> str:
    """htdemucs returns Bass/Drums/Other/Vocals — sum the non-vocal stems to a wav."""
    parts = []
    for key in ("bass", "drums", "other"):
        if key not in classified:
            raise RuntimeError(
                f"htdemucs path: missing '{key}' stem in {list(classified)}"
            )
        s, _ = load_audio(classified[key], sr=sr, mono=False)
        parts.append(s)
    n = min(len(p) for p in parts)
    instrumental = sum(p[:n] for p in parts)
    out_path = str(Path(out_dir) / "instrumental_summed.wav")
    from .io import write_wav  # local import keeps top-level ML-free
    write_wav(out_path, instrumental, sr)
    return out_path


def separate(
    audio_path: str | Path,
    preset_name: str = "demucs",
    device: str = "auto",
    sr: int = 44100,
) -> dict[str, np.ndarray | int | str]:
    """
    Returns:
        {
            "instrumental": np.ndarray (N, 2),
            "lead":         np.ndarray (N, 2),
            "backing":      np.ndarray (N, 2),
            "sr":           int,
            "preset":       str,
        }
    """
    if preset_name not in PRESETS:
        raise ValueError(f"unknown separator preset: {preset_name}. Options: {list(PRESETS)}")
    preset = PRESETS[preset_name]
    audio_path = str(audio_path)
    log.info("separation: preset=%s instrumental=%s karaoke=%s", preset.name,
             preset.instrumental_model, preset.karaoke_model)

    with tempfile.TemporaryDirectory(prefix="heartbeam_sep_") as tmp:
        def _resolve(paths: list[str]) -> list[str]:
            # audio-separator can return either bare filenames (relative to output_dir)
            # or absolute paths depending on version. Normalise.
            return [str(Path(p) if Path(p).is_absolute() else Path(tmp) / p) for p in paths]

        # Pass 1: vocals vs instrumental. preset.instrumental_model may be a tuple
        # (ensemble) or a single filename.
        sep_a = _get_separator(
            preset.instrumental_model, device, tmp,
            ensemble_algorithm=preset.ensemble_algorithm,
        )
        out_a = _resolve(sep_a.separate(audio_path))
        classified_a = _classify_outputs(out_a)
        if "vocals" not in classified_a:
            raise RuntimeError(f"first-pass separation produced no vocals stem: {out_a}")
        if "instrumental" not in classified_a:
            # htdemucs splits into 4 stems (Bass/Drums/Other/Vocals); synthesize instrumental.
            if {"bass", "drums", "other"} <= classified_a.keys():
                classified_a["instrumental"] = _synthesize_instrumental_from_4stem(
                    classified_a, tmp, sr
                )
            else:
                raise RuntimeError(
                    f"first-pass separation produced unexpected outputs: {out_a}"
                )

        # Pass 2: lead vs backing on the vocals stem.
        sep_b = _get_separator(preset.karaoke_model, device, tmp)
        out_b_paths = _resolve(sep_b.separate(classified_a["vocals"]))
        # Karaoke-model output naming conventions differ:
        #   UVR_MDXNET_KARA_2  → "(Vocals)" = lead (lead-vocal extractor)
        #   UVR-BVE-4B         → "(Vocals)" = backing (backing-vocal extractor)
        # Rather than maintain a per-model lookup, decide by RMS: in pop/rock recordings
        # the lead is almost always mixed louder than the backing. Self-calibrating.
        if len(out_b_paths) != 2:
            raise RuntimeError(
                f"second-pass separation produced unexpected number of outputs: {out_b_paths}"
            )
        s0, _ = load_audio(out_b_paths[0], sr=sr, mono=False)
        s1, _ = load_audio(out_b_paths[1], sr=sr, mono=False)
        rms0 = float(np.sqrt(np.mean(s0.astype(np.float64) ** 2)))
        rms1 = float(np.sqrt(np.mean(s1.astype(np.float64) ** 2)))
        if rms0 >= rms1:
            lead, backing = s0, s1
            lead_path, backing_path = out_b_paths[0], out_b_paths[1]
        else:
            lead, backing = s1, s0
            lead_path, backing_path = out_b_paths[1], out_b_paths[0]
        log.info("Pass 2 assignment by RMS: lead=%s (rms=%.4f) backing=%s (rms=%.4f)",
                 Path(lead_path).name, max(rms0, rms1),
                 Path(backing_path).name, min(rms0, rms1))

        instrumental, _ = load_audio(classified_a["instrumental"], sr=sr, mono=False)

    n = min(len(instrumental), len(lead), len(backing))
    return {
        "instrumental": instrumental[:n],
        "lead": lead[:n],
        "backing": backing[:n],
        "sr": sr,
        "preset": preset.name,
    }
