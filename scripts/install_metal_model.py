"""One-time installer for the `metal` separator preset (Mesk's Rifforge MelRoFormer).

Why: Mesk's metal-tuned Mel-Band RoFormer is the only OSS music-source-separation
model trained on heavy material, but it's not in audio-separator's default model
registry. This script does the three things needed to make `--separator metal` work:

  1. Download `rifforge_full_sdr_14.2436.ckpt` (~2 GB) + companion YAML from
     HuggingFace into audio-separator's cache directory.
  2. Patch audio-separator's bundled `models.json` so `Separator.load_model(
     model_filename="rifforge_full_sdr_14.2436.ckpt")` doesn't ValueError.
  3. Verify the install by importing audio_separator and listing the registry.

Idempotent: re-running won't re-download, won't double-add the registry entry.

LICENCE CAVEAT: Mesk's HF repo (meskvlla33/rifforge) has no LICENSE and no model
card. Treat as personal-use; contact Mesk before any commercial usage.

Usage:
    python scripts/install_metal_model.py
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

REGISTRY_KEY = "Roformer Model: Rifforge MelBand (Mesk, metal)"
CKPT_NAME = "rifforge_full_sdr_14.2436.ckpt"
YAML_NAME = "config_rifforge_full_mesk.yaml"
CKPT_URL = f"https://huggingface.co/meskvlla33/rifforge/resolve/main/{CKPT_NAME}"
YAML_URL = f"https://huggingface.co/meskvlla33/rifforge/resolve/main/{YAML_NAME}"


def _audio_separator_models_json() -> Path:
    import audio_separator
    return Path(audio_separator.__file__).parent / "models.json"


def _cache_dir() -> Path:
    """Resolve audio-separator's cache dir. Honour AUDIO_SEPARATOR_MODEL_DIR; otherwise
    fall back to the broken-but-real default that audio-separator hardcodes."""
    env = os.environ.get("AUDIO_SEPARATOR_MODEL_DIR")
    if env:
        return Path(env)
    # audio-separator's hardcoded default. On Windows this resolves to C:\tmp\... etc.
    return Path("/tmp/audio-separator-models")


def _download(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        size_mb = dest.stat().st_size / (1024 * 1024)
        print(f"  [skip] {dest.name} already exists ({size_mb:.1f} MB)")
        return
    print(f"  [get ] {url}")
    print(f"  [to  ] {dest}")

    def progress(blocks: int, block_size: int, total: int) -> None:
        if total <= 0:
            return
        done = blocks * block_size
        pct = min(100, 100 * done / total)
        mb_done = done / (1024 * 1024)
        mb_total = total / (1024 * 1024)
        bar = "#" * int(pct / 2) + "-" * (50 - int(pct / 2))
        print(f"\r  [{bar}] {pct:5.1f}% ({mb_done:7.1f} / {mb_total:7.1f} MB)", end="", flush=True)

    tmp = dest.with_suffix(dest.suffix + ".part")
    urllib.request.urlretrieve(url, tmp, reporthook=progress)
    print()
    tmp.replace(dest)


def _patch_registry(models_json: Path) -> bool:
    """Add the Rifforge entry to roformer_download_list. Returns True if changed."""
    with open(models_json, encoding="utf-8") as f:
        data = json.load(f)
    roformer = data.setdefault("roformer_download_list", {})
    if REGISTRY_KEY in roformer:
        existing = roformer[REGISTRY_KEY]
        if existing == {CKPT_NAME: YAML_NAME}:
            print(f"  [skip] registry entry already present: {REGISTRY_KEY!r}")
            return False
    roformer[REGISTRY_KEY] = {CKPT_NAME: YAML_NAME}
    with open(models_json, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    print(f"  [ok  ] patched registry: {REGISTRY_KEY!r}")
    return True


def main() -> int:
    print("\n=== Install metal preset (Mesk Rifforge) ===\n")

    cache = _cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    print(f"cache dir: {cache}")

    print("\nStep 1/3: download model files")
    _download(CKPT_URL, cache / CKPT_NAME)
    _download(YAML_URL, cache / YAML_NAME)

    print("\nStep 2/3: patch audio-separator registry")
    models_json = _audio_separator_models_json()
    print(f"registry: {models_json}")
    _patch_registry(models_json)

    print("\nStep 3/3: verify")
    try:
        from audio_separator.separator import Separator  # noqa: F401
        with open(models_json, encoding="utf-8") as f:
            data = json.load(f)
        if REGISTRY_KEY not in data.get("roformer_download_list", {}):
            print("  [FAIL] registry entry missing after patch", file=sys.stderr)
            return 2
        ckpt_path = cache / CKPT_NAME
        yaml_path = cache / YAML_NAME
        if not ckpt_path.exists():
            print(f"  [FAIL] missing ckpt: {ckpt_path}", file=sys.stderr)
            return 2
        if not yaml_path.exists():
            print(f"  [FAIL] missing yaml: {yaml_path}", file=sys.stderr)
            return 2
        size_gb = ckpt_path.stat().st_size / (1024 ** 3)
        print(f"  [ok  ] ckpt present ({size_gb:.2f} GB), yaml present, registry patched")
    except Exception as e:
        print(f"  [FAIL] verification error: {e}", file=sys.stderr)
        return 2

    print("\nDone. You can now run:")
    print("  heartbeam song.mp3 lyrics.txt --separator metal --mix-strategy subtract \\")
    print("    --vocal-gain 1.5 --pad-ms 180 --crossfade-ms 100 --merge-gap-ms 350 \\")
    print("    --energy-threshold 0.03 --target-lufs -14 --align-device cpu -v")
    return 0


if __name__ == "__main__":
    sys.exit(main())
