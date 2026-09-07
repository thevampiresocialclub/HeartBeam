"""
Phase 1 CLI: heartbeam song.mp3 lyrics.txt -o out/

Orchestrates load → separate → align → mask → mix → write outputs.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from . import paths
from .models import (
    PRESETS,
    PRIMARY_PRESETS,
    SUPPORTED_WHISPER_MODELS,
    DEFAULT_WHISPER_MODEL,
    resolve_default,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="heartbeam",
        description="Strip lead vocals from an MP3 using a lyrics file. Keeps backing vocals "
                    "and instrumental breaks intact. Writes a karaoke MP3, separated stems, "
                    "and a timings.json artifact consumable by `heartbeam-video`.",
    )
    p.add_argument("song", type=Path, help="path to input MP3 (or any ffmpeg-readable audio)")
    p.add_argument("lyrics", type=Path, help="path to plain-text lyrics file (one phrase per line)")
    p.add_argument("-o", "--out", type=Path, default=Path("out"), help="output directory (default: ./out)")
    primary = ", ".join(PRIMARY_PRESETS)
    p.add_argument(
        "--separator",
        choices=list(PRESETS.keys()),
        default="pop",
        help=f"genre profile. Primary choices: {primary}. Each profile sets recommended "
             f"separator models AND mix/mask tuning; per-flag overrides still win. "
             f"Default: pop.",
    )
    p.add_argument(
        "--whisper-model",
        choices=SUPPORTED_WHISPER_MODELS,
        default=DEFAULT_WHISPER_MODEL,
        help=f"WhisperX ASR model size (default: {DEFAULT_WHISPER_MODEL})",
    )
    # Numeric mask/mix flags default to None so we can detect "user didn't pass"
    # and fall back to the preset's recommended value via resolve_default().
    p.add_argument("--pad-ms", type=float, default=None,
                   help="mask padding around each word in ms (preset default)")
    p.add_argument("--crossfade-ms", type=float, default=None,
                   help="mask edge crossfade in ms (preset default)")
    p.add_argument("--merge-gap-ms", type=float, default=None,
                   help="bridge adjacent word intervals separated by less than this ms (0 to disable, preset default)")
    p.add_argument("--energy-threshold", type=float, default=None,
                   help="energy-mask threshold as fraction of lead-stem peak RMS (0 to disable, preset default)")
    p.add_argument("--energy-window-ms", type=float, default=None,
                   help="RMS smoothing window for energy mask in ms (preset default)")
    p.add_argument("--mix-strategy", choices=["replace", "subtract"], default=None,
                   help="replace: (1-m)·original + m·(instrumental+backing). "
                        "subtract: original - vocal_gain·mask·lead. (preset default)")
    p.add_argument("--vocal-gain", type=float, default=None,
                   help="(subtract only) overshoot factor on lead subtraction (preset default)")
    p.add_argument("--backing-boost", type=float, default=None,
                   help="(subtract only) add backing_boost*mask*backing_stem (preset default)")
    p.add_argument("--target-lufs", type=float, default=None,
                   help="normalize final output to this LUFS (e.g. -14). Use --no-lufs to override "
                        "a preset that enables it. (preset default)")
    p.add_argument("--no-lufs", action="store_true",
                   help="disable LUFS normalization even if the preset enables it")
    p.add_argument("--no-audio-cache", action="store_true",
                   help="skip writing the lossless audio cache (original/stems/clean "
                        "reference). The cache is what lets later edits remix without "
                        "rerunning separation; it costs roughly 100 MB per minute of song.")
    p.add_argument("--cache-format", choices=["wav", "flac"], default="wav",
                   help="lossless cache format. wav is float32 and bit-exact; flac is "
                        "24-bit and about 40%% of the size (default: wav)")
    p.add_argument("--keep-stems", action="store_true", help="also write stems/lead.wav, backing.wav, instrumental.wav")
    p.add_argument("--device", choices=["auto", "cuda", "cpu"], default="auto", help="(default: auto)")
    p.add_argument(
        "--allow-cpu",
        action="store_true",
        help="run without an NVIDIA GPU. Supported target is GTX 1050 / RTX xx50 and up; "
             "on CPU a single song takes 20-75 minutes.",
    )
    p.add_argument(
        "--align-device",
        choices=["auto", "cuda", "cpu"],
        default="auto",
        help="override device for WhisperX alignment only. Use 'cpu' to free VRAM on low-memory "
             "GPUs where separation models leave residual allocations. Default: same as --device.",
    )
    p.add_argument(
        "--aligner",
        choices=["whisperx", "sofa"],
        default="whisperx",
        help="alignment backend. whisperx (default): speech-trained CTC aligner. "
             "sofa: singing-trained forced aligner, runs in a sidecar venv via subprocess. "
             "See docs/SOFA_SETUP.md for one-time install.",
    )
    p.add_argument("--sofa-python", default=None, help="path to SOFA sidecar python (or HEARTBEAM_SOFA_PYTHON)")
    p.add_argument("--sofa-repo", default=None, help="path to cloned SOFA repo (or HEARTBEAM_SOFA_REPO)")
    p.add_argument("--sofa-ckpt", default=None, help="path to SOFA .ckpt (or HEARTBEAM_SOFA_CKPT)")
    p.add_argument("--sofa-dict", default=None, help="path to SOFA dictionary file (or HEARTBEAM_SOFA_DICT)")
    p.add_argument("--language", default=None, help="force ASR/alignment language (e.g. 'en'); auto-detect if omitted")
    p.add_argument('--lyrics-candidate', type=Path, help='Optional saved online lyrics candidate to verify against this audio')
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def _resolve_device(requested: str) -> str:
    if requested != "auto":
        return requested
    try:
        import torch  # deferred
        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


#: Minimum VRAM (GB) below which WhisperX alignment is pushed to the CPU. The
#: xx50 tier runs as low as 4 GB (RTX 3050 laptop), and separation already holds
#: a multi-GB model when alignment tries to load its own.
_LOW_VRAM_GB = 6.0


def _preflight_gpu(log, allow_cpu: bool) -> str | None:
    """Verify this build of torch can actually drive the installed GPU.

    Returns an error string, or None if we are good to go. Catches the two
    failure modes that otherwise surface as confusing mid-run crashes:
    no CUDA at all, and a torch built for older architectures than the card.
    """
    try:
        import torch
    except ImportError:
        return ("PyTorch is not installed. Run scripts\\install.ps1 (Windows) or "
                "scripts/install.sh to set up the GPU build.")

    if not torch.cuda.is_available():
        if allow_cpu:
            log.warning("no CUDA device - running on CPU. Expect 20-75 min per song.")
            return None
        return (
            "No CUDA device found. HeartBeam targets NVIDIA GPUs (GTX 1050 / RTX xx50 "
            "and up).\n"
            "  - If you have an NVIDIA card, your torch is probably the CPU build. "
            "Reinstall with scripts\\install.ps1 -Variant GPU.\n"
            "  - To run on CPU anyway (20-75 min per song), pass --allow-cpu."
        )

    props = torch.cuda.get_device_properties(torch.cuda.current_device())
    arch = f"sm_{props.major}{props.minor}"
    supported = torch.cuda.get_arch_list()
    if supported and arch not in supported:
        return (
            f"{props.name} is compute capability {arch}, but this PyTorch "
            f"({torch.__version__}, CUDA {torch.version.cuda}) only has kernels for "
            f"{', '.join(supported)}.\n"
            "Running would fail with 'no kernel image is available for execution on "
            "the device'.\n"
            "Fix: reinstall with the cu128 wheels —\n"
            "  pip install --index-url https://download.pytorch.org/whl/cu128 "
            "torch torchaudio torchvision"
        )

    vram_gb = props.total_memory / 1024 ** 3
    log.info("GPU: %s (%s, %.1f GB VRAM, CUDA %s, torch %s)",
             props.name, arch, vram_gb, torch.version.cuda, torch.__version__)
    return None


_PRESET_TUNABLES = (
    "pad_ms", "crossfade_ms", "merge_gap_ms",
    "energy_threshold", "energy_window_ms",
    "mix_strategy", "vocal_gain", "backing_boost",
    "target_lufs",
)


def _apply_preset_defaults(args, preset) -> None:
    """For each tunable that the user did NOT pass (still None), fill in the
    preset's recommended value (or fall back to GLOBAL_DEFAULTS)."""
    for name in _PRESET_TUNABLES:
        if getattr(args, name) is None:
            setattr(args, name, resolve_default(preset, name))
    if getattr(args, "no_lufs", False):
        args.target_lufs = None


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("heartbeam")

    # Pin every model cache before the first ML import — these libraries read
    # their cache env vars at import time, and audio-separator's own default is
    # drive-relative on Windows (see heartbeam/paths.py).
    for key, value in paths.apply_env().items():
        log.debug("%s=%s", key, value)

    # audio-separator has no device parameter — it calls torch.cuda.is_available()
    # internally and takes the GPU whenever there is one. Hiding the devices before
    # torch is imported is the only way to make `--device cpu` mean anything for
    # the separation stage.
    if args.device == "cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    # Fold preset's recommended tuning into any arg the user left unset.
    preset_obj = PRESETS[args.separator]
    _apply_preset_defaults(args, preset_obj)
    log.info(
        "preset=%s  mix=%s pad=%.0fms xfade=%.0fms gap=%.0fms energy=%.2f gain=%.2f boost=%.2f target_lufs=%s",
        args.separator, args.mix_strategy, args.pad_ms, args.crossfade_ms,
        args.merge_gap_ms, args.energy_threshold, args.vocal_gain, args.backing_boost,
        args.target_lufs if args.target_lufs is not None else "off",
    )

    if not args.song.exists():
        log.error("song not found: %s", args.song)
        return 2
    if not args.lyrics.exists():
        log.error("lyrics not found: %s", args.lyrics)
        return 2

    args.out.mkdir(parents=True, exist_ok=True)
    stems_dir = args.out / "stems"
    if args.keep_stems:
        stems_dir.mkdir(exist_ok=True)

    error = _preflight_gpu(log, allow_cpu=args.allow_cpu or args.device == "cpu")
    if error:
        log.error("%s", error)
        return 3

    device = _resolve_device(args.device)
    log.info("device=%s", device)

    # On the low end of the supported range (4-6 GB xx50 cards) the separator's
    # model is still resident when WhisperX loads its own, which OOMs. Push
    # alignment to the CPU there — it costs well under a minute.
    if args.align_device == "auto" and device == "cuda":
        import torch
        vram_gb = torch.cuda.get_device_properties(
            torch.cuda.current_device()).total_memory / 1024 ** 3
        if vram_gb < _LOW_VRAM_GB:
            log.info("only %.1f GB VRAM — aligning on CPU to avoid OOM "
                     "(override with --align-device cuda)", vram_gb)
            args.align_device = "cpu"

    # Deferred imports so --help / arg errors don't pay torch import cost.
    from . import align as align_mod
    from . import io as io_mod
    from . import mask as mask_mod
    from . import mix as mix_mod
    from . import separate as separate_mod
    from . import timings as timings_mod

    lyrics_text = args.lyrics.read_text(encoding="utf-8")

    log.info("loading original audio: %s", args.song)
    original, sr = io_mod.load_audio(args.song, sr=44100, mono=False)
    duration_s = original.shape[0] / sr

    log.info("running source separation (preset=%s)…", args.separator)
    stems = separate_mod.separate(args.song, preset_name=args.separator, device=device, sr=sr)
    instrumental = stems["instrumental"]
    lead = stems["lead"]
    backing = stems["backing"]
    vocals = stems.get('vocals', lead + backing)

    # Trim everything to common length.
    n = min(len(original), len(lead), len(backing), len(instrumental), len(vocals))
    original = original[:n]
    lead = lead[:n]
    backing = backing[:n]
    instrumental = instrumental[:n]
    vocals = vocals[:n]

    if args.keep_stems:
        io_mod.write_wav(stems_dir / "lead.wav", lead, sr)
        io_mod.write_wav(stems_dir / "backing.wav", backing, sr)
        io_mod.write_wav(stems_dir / "instrumental.wav", instrumental, sr)
        io_mod.write_wav(stems_dir / 'vocals.wav', vocals, sr)
        log.info("wrote stems to %s", stems_dir)

    # Free separator VRAM before loading WhisperX (matters on ≤4 GB cards).
    separate_mod.release_models()

    align_device = device if args.align_device == "auto" else args.align_device
    online = None
    aligner_id = f"{args.aligner}-{args.whisper_model}"
    try:
        if args.lyrics_candidate:
            online = json.loads(args.lyrics_candidate.read_text(encoding='utf-8'))
        if args.aligner == "sofa":
            from . import align_sofa
            sofa_cfg = align_sofa.SOFAConfig.from_env_or_args(
                python_bin=args.sofa_python, repo_dir=args.sofa_repo,
                ckpt_path=args.sofa_ckpt, dictionary_path=args.sofa_dict,
            )
            log.info("running SOFA forced alignment (sidecar venv=%s)…", sofa_cfg.python_bin)
            ar = align_sofa.align(vocals, sr=sr, lyrics_text=lyrics_text, sofa=sofa_cfg)
            aligner_id = f"sofa-{Path(sofa_cfg.ckpt_path).stem}"
        else:
            log.info("matching lyric phrases against complete vocals (device=%s)…", align_device)
            ar = align_mod.align(
                vocals, sr=sr, lyrics_text=lyrics_text,
                whisper_model=args.whisper_model, device=align_device, language=args.language,
                cache_dir=args.out / 'cache' / 'alignment', online=online,
            )
    except Exception as exc:  # Preserve completed separation when timing models fail.
        from .alignment_engine import unresolved_result
        reason = f'{type(exc).__name__}: {exc}'
        log.warning('Separation finished, but timing could not finish: %s. '
                    'Saving audio and lyrics for timing repair in the editor.', reason)
        ar = unresolved_result(lyrics_text, reason, language=args.language, online=online)
        aligner_id += '-incomplete'
    log.info(
        "alignment: %d words across %d lines (%d low-confidence, lang=%s)",
        ar.total_words, len(ar.lines), ar.low_confidence_count, ar.language,
    )

    # Build the lyric-aware mask from all aligned words.
    all_words = [w for ln in ar.lines for w in ln.words]
    log.info("building lyric mask (pad=%.0fms xfade=%.0fms gap=%.0fms)…",
             args.pad_ms, args.crossfade_ms, args.merge_gap_ms)
    m_lyric = mask_mod.build_mask(
        all_words, total_samples=n, sr=sr,
        pad_ms=args.pad_ms, xfade_ms=args.crossfade_ms, merge_gap_ms=args.merge_gap_ms,
    )

    if args.energy_threshold > 0.0:
        log.info("building energy mask from lead stem (threshold=%.2f peak, window=%.0fms)…",
                 args.energy_threshold, args.energy_window_ms)
        m_energy = mask_mod.build_energy_mask(
            lead, sr=sr,
            window_ms=args.energy_window_ms,
            threshold_rel=args.energy_threshold,
            xfade_ms=args.crossfade_ms,
        )
        m = mask_mod.combine_masks(m_lyric, m_energy)
        lyric_pct = float((m_lyric > 0).mean()) * 100
        energy_pct = float((m_energy > 0).mean()) * 100
        combined_pct = float((m > 0).mean()) * 100
        log.info("mask coverage: lyric=%.1f%% energy=%.1f%% combined=%.1f%%",
                 lyric_pct, energy_pct, combined_pct)
    else:
        m = m_lyric

    # Mix once WITHOUT clipping. That unclipped, un-normalised result is the
    # "clean reference" the section mixer later blends towards the original, so
    # it has to be captured at the same gain reference as the source. The
    # clipped copy below is only for the MP3 deliverable.
    if args.mix_strategy == "replace":
        log.info("mixing karaoke output (replace: (1-m)·original + m·(instrumental+backing))…")
        clean_reference = mix_mod.mix_replace(original, instrumental, backing, m, clip=False)
    else:
        log.info(
            "mixing karaoke output (subtract: original − %.2f·m·lead + %.2f·m·backing)…",
            args.vocal_gain, args.backing_boost,
        )
        clean_reference = mix_mod.mix(
            original, lead, m,
            vocal_gain=args.vocal_gain,
            backing_stem=backing if args.backing_boost != 0.0 else None,
            backing_boost=args.backing_boost,
            clip=False,
        )
    import numpy as _np
    karaoke = _np.clip(clean_reference, -1.0, 1.0).astype(_np.float32, copy=False)

    if not args.no_audio_cache:
        from . import audio_cache as cache_mod
        cache_dir = args.out / "cache"
        cache_settings = {
            "separator": args.separator,
            "aligner": aligner_id,
            "whisper_model": args.whisper_model,
            "mix_strategy": args.mix_strategy,
            "vocal_gain": args.vocal_gain,
            "backing_boost": args.backing_boost,
            "pad_ms": args.pad_ms,
            "crossfade_ms": args.crossfade_ms,
            "merge_gap_ms": args.merge_gap_ms,
            "energy_threshold": args.energy_threshold,
            "energy_window_ms": args.energy_window_ms,
            "sample_rate": sr,
        }
        try:
            manifest = cache_mod.write_cache(
                cache_dir,
                {
                    "original": original,
                    "lead": lead,
                    "backing": backing,
                    "instrumental": instrumental,
                    "clean": clean_reference,
                    "vocals": vocals,
                },
                sample_rate=sr,
                source_sha256=cache_mod.file_sha256(args.song),
                settings=cache_settings,
                provenance={
                    "separator_preset": args.separator,
                    "aligner": aligner_id,
                    "whisper_model": args.whisper_model,
                },
                audio_format=args.cache_format,
            )
            size_mb = cache_mod.cache_size_bytes(cache_dir, manifest) / (1024 * 1024)
            log.info("wrote lossless audio cache: %s (%.0f MB, format=%s)",
                     cache_dir, size_mb, args.cache_format)
        except Exception as exc:  # noqa: BLE001 - the cache is an optimisation
            # A cache failure must not lose the user a completed separation.
            log.warning("could not write the audio cache (%s: %s). The karaoke "
                        "output is unaffected; later remixing will need a rerun.",
                        type(exc).__name__, exc)

    if args.target_lufs is not None:
        from . import lufs as lufs_mod
        before = lufs_mod.measure_lufs(karaoke, sr)
        karaoke = lufs_mod.normalize_to_lufs(karaoke, sr, target_lufs=args.target_lufs)
        after = lufs_mod.measure_lufs(karaoke, sr)
        log.info("loudness normalize: %.1f LUFS -> %.1f LUFS (target %.1f)",
                 before, after, args.target_lufs)

    karaoke_path = args.out / "karaoke.mp3"
    io_mod.write_mp3(karaoke_path, karaoke, sr)
    log.info("wrote %s", karaoke_path)

    timings = timings_mod.Timings(
        source=timings_mod.Source(
            audio_path=str(args.song),
            lyrics_path=str(args.lyrics),
            sample_rate=sr,
            duration_s=round(duration_s, 3),
        ),
        models=timings_mod.Models(
            separator=args.separator,
            aligner=aligner_id,
        ),
        lines=ar.lines,
        alignment=ar.diagnostics,
    )
    timings_path = args.out / "timings.json"
    lrc_path = args.out / "lyrics.lrc"
    timings_mod.to_json(timings, timings_path)
    timings_mod.to_lrc(timings, lrc_path)
    log.info("wrote %s and %s", timings_path, lrc_path)

    print(f"\nDone. Outputs in {args.out.resolve()}:")
    print(f"  karaoke.mp3   ({karaoke_path.stat().st_size // 1024} KB)")
    print(f"  timings.json  ({len(ar.lines)} lines, {ar.total_words} words)")
    print(f"  lyrics.lrc")
    if args.keep_stems:
        print(f"  stems/        (lead.wav, backing.wav, instrumental.wav)")
    unresolved = sum(w['start_s'] is None for p in ar.diagnostics.get('phrases', []) for w in p['words'])
    if unresolved:
        print(f'\n{unresolved} words still need timing. Open the saved result in the editor to match and review them.')
    else:
        print(f"\nTo render a karaoke video:")
        print(f"  heartbeam-video {karaoke_path} {timings_path} -o {args.out / 'karaoke.mp4'}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
