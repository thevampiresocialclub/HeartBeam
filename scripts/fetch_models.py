"""Pre-download every model HeartBeam needs, into one portable folder.

The point is to do the multi-GB downloading on a machine with a fast connection
(or a fast GPU you were using anyway), then copy a single folder to the target
machine so the first run there is instant and works offline.

    # On the machine that already has the models:
    python scripts/fetch_models.py --presets pop rock --whisper medium

    # Or stage them somewhere you can copy from:
    python scripts/fetch_models.py --root E:\\heartbeam-models

Then copy that folder to the target machine and point HeartBeam at it (only
needed if you put it somewhere other than the default ~/.heartbeam/models):

    setx HEARTBEAM_MODEL_ROOT "D:\\heartbeam-models"

heartbeam/paths.py resolves that variable for all three caches, so nothing needs
to be re-downloaded and no library falls back to a network check.

Sizes (approximate, per preset):
    pop    641 MB   MDX23C + UVR-BVE-4B
    rock   1.5 GB   BS-Roformer + MDX-Inst-HQ3 + Mel-Roformer-Karaoke (+ MDX23C, shared)
    whisper medium 1.46 GB | small 464 MB | large-v3 2.9 GB
    aligner (en)   360 MB
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from heartbeam import paths  # noqa: E402
from heartbeam.models import PRESETS  # noqa: E402


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:,.1f} {unit}"
        n /= 1024.0
    return f"{n} B"


def _dir_size(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def preset_models(names: list[str]) -> list[str]:
    """Flatten the (possibly ensemble) model filenames for the given presets."""
    out: list[str] = []
    for name in names:
        if name not in PRESETS:
            raise SystemExit(f"unknown preset {name!r}. Options: {', '.join(PRESETS)}")
        preset = PRESETS[name]
        instrumental = preset.instrumental_model
        if isinstance(instrumental, str):
            out.append(instrumental)
        else:
            out.extend(instrumental)
        out.append(preset.karaoke_model)
    # Dedupe, preserve order — presets share models (rock and pop both use MDX23C).
    seen, unique = set(), []
    for m in out:
        if m not in seen:
            seen.add(m)
            unique.append(m)
    return unique


def fetch_separator_models(names: list[str]) -> None:
    from audio_separator.separator import Separator

    target = paths.separator_dir()
    target.mkdir(parents=True, exist_ok=True)
    wanted = preset_models(names)
    print(f"\n=== Separator models -> {target} ===")
    # info_only keeps this from allocating inference buffers or touching a GPU;
    # we only want the downloader.
    sep = Separator(model_file_dir=str(target), info_only=True)
    for model in wanted:
        if model.endswith(".yaml"):
            print(f"  - {model}: config resolved with its checkpoint, skipping")
            continue
        print(f"  - {model}")
        try:
            sep.download_model_files(model)
        except Exception as exc:  # noqa: BLE001 — one bad model shouldn't kill the run
            print(f"    FAILED: {exc}")
            print("    (the 'metal' preset's Rifforge ckpt is not in the public "
                  "registry — use scripts/install_metal_model.py for that one)")


def fetch_whisper(model_name: str) -> None:
    from faster_whisper.utils import download_model

    print(f"\n=== faster-whisper '{model_name}' -> {paths.hf_home()} ===")
    download_model(model_name)


def fetch_aligner(language: str) -> None:
    print(f"\n=== wav2vec2 aligner ({language}) -> {paths.torch_home()} ===")
    import whisperx

    whisperx.load_align_model(language_code=language, device="cpu")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Pre-download HeartBeam's model weights into one portable folder."
    )
    p.add_argument("--root", type=Path, default=None,
                   help=f"cache root (default: ${paths.ROOT_ENV} or {paths.model_root()})")
    p.add_argument("--presets", nargs="+", default=["pop", "rock"],
                   help="separator presets to fetch models for (default: pop rock)")
    p.add_argument("--whisper", default="medium",
                   help="whisper model: tiny/base/small/small.en/medium/large-v3 (default: medium)")
    p.add_argument("--language", default="en", help="alignment model language (default: en)")
    p.add_argument("--skip-separator", action="store_true")
    p.add_argument("--skip-whisper", action="store_true")
    args = p.parse_args()

    if args.root:
        os.environ[paths.ROOT_ENV] = str(args.root)
    # Force real files rather than symlinks in the HF cache: a plain folder copy
    # (Explorer, Compress-Archive, Copy-Item) dereferences symlinks and silently
    # doubles the size on disk.
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS", "1")
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
    paths.apply_env()

    root = paths.model_root()
    print(f"Cache root: {root}")

    if not args.skip_separator:
        fetch_separator_models(args.presets)
    if not args.skip_whisper:
        fetch_whisper(args.whisper)
    fetch_aligner(args.language)

    print("\n=== Done ===")
    total = 0
    for label, path in (("separator", paths.separator_dir()),
                        ("whisper (hf)", paths.hf_home()),
                        ("aligner (torch)", paths.torch_home())):
        size = _dir_size(path)
        total += size
        print(f"  {label:<16} {_human(size):>12}  {path}")
    print(f"  {'TOTAL':<16} {_human(total):>12}")

    print(f"""
Copy '{root}' to the target machine, then set one variable there:

  PowerShell:  [Environment]::SetEnvironmentVariable('{paths.ROOT_ENV}','<path>','User')
  bash:        export {paths.ROOT_ENV}=<path>

Verify with the network off - if it runs, the transplant is complete.""")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
