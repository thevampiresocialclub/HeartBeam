"""Model registry + pipeline profiles.

A preset bundles three things:
  1. Which separator models to use (Pass-1 vocals/instr, Pass-2 lead/backing).
  2. Recommended *mix/mask* tuning for that genre (pad, crossfade, gain, etc.).
  3. A description for the CLI help.

The CLI applies a preset's `defaults` to any flag the user did NOT pass on the
command line. Per-flag overrides still work — pass `--pad-ms 200` and the user
value wins.

audio-separator auto-downloads checkpoints into its cache on first use (except
the `metal` preset's Rifforge ckpt, which is not in the registry — see
scripts/install_metal_model.py).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PipelineDefaults:
    """Per-preset recommended values for mask/mix tuning.

    None means "no recommendation — fall back to the CLI's global default."
    """
    mix_strategy: str | None = None        # "subtract" or "replace"
    vocal_gain: float | None = None        # only when mix_strategy=subtract
    backing_boost: float | None = None     # only when mix_strategy=subtract
    pad_ms: float | None = None
    crossfade_ms: float | None = None
    merge_gap_ms: float | None = None
    energy_threshold: float | None = None
    energy_window_ms: float | None = None
    target_lufs: float | None = None


@dataclass(frozen=True)
class SeparatorPreset:
    name: str
    # First pass: vocal/instrumental split. Either a single model filename, or a
    # tuple of filenames for ensemble separation (combined via ensemble_algorithm).
    instrumental_model: str | tuple[str, ...]
    # Second pass on the vocal stem: split lead from backing vocals.
    karaoke_model: str
    description: str
    # Only used when instrumental_model is a tuple — passed to audio-separator's
    # Separator. "uvr_max_spec" = per-frequency-bin max magnitude across models.
    ensemble_algorithm: str = "uvr_max_spec"
    # Per-preset mix/mask tuning. CLI overrides win; otherwise these become the
    # active defaults when `--separator <name>` is selected.
    defaults: PipelineDefaults = field(default_factory=PipelineDefaults)


# ---------- Global fallbacks (used when no preset and no user flag) ----------
GLOBAL_DEFAULTS = PipelineDefaults(
    mix_strategy="replace",
    vocal_gain=1.0,
    backing_boost=0.0,
    pad_ms=120.0,
    crossfade_ms=60.0,
    merge_gap_ms=500.0,
    energy_threshold=0.05,
    energy_window_ms=30.0,
    target_lufs=None,  # off by default
)


# ---------- User-facing presets (pop / rock / metal) ----------
# These are the three the README + GUI surface as primary choices. Internal /
# experimental presets follow below.
PRESETS: dict[str, SeparatorPreset] = {
    # Pop — Youka's open-source default. MDX23C vocal/instr split + UVR-BVE-4B
    # backing extractor. Good for clean studio pop productions; doesn't try to
    # preserve elaborate harmony stacks.
    "pop": SeparatorPreset(
        name="pop",
        instrumental_model="MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
        karaoke_model="UVR-BVE-4B_SN-44100-1.pth",
        description="MDX23C + UVR-BVE-4B. Pop / general — fastest single-model path.",
        defaults=PipelineDefaults(
            mix_strategy="replace",
            pad_ms=120.0,
            crossfade_ms=60.0,
            merge_gap_ms=500.0,
            energy_threshold=0.05,
            energy_window_ms=30.0,
            target_lufs=-14.0,
        ),
    ),
    # Rock — ensemble Pass-1 (BS-RoFormer + MDX23C + MDX-Inst-HQ3, MAX SPEC) +
    # Mel-RoFormer karaoke Pass-2. Preserves gang vocals, doubled leads, and
    # harmony stacks that UVR-BVE-4B strips. Subtract strategy with overshoot
    # preserves the original mix's distorted guitar texture better than replace.
    "rock": SeparatorPreset(
        name="rock",
        instrumental_model=(
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
            "UVR-MDX-NET-Inst_HQ_3.onnx",
        ),
        karaoke_model="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        description="Ensemble + Mel-RoFormer karaoke. Preserves gang vocals/harmonies on rock.",
        ensemble_algorithm="uvr_max_spec",
        defaults=PipelineDefaults(
            mix_strategy="subtract",
            vocal_gain=1.5,
            backing_boost=0.0,
            pad_ms=180.0,
            crossfade_ms=100.0,
            merge_gap_ms=350.0,
            energy_threshold=0.03,
            energy_window_ms=30.0,
            target_lufs=-14.0,
        ),
    ),
    # Metal — Mesk's Rifforge MelRoFormer (community fine-tune, trained on metal
    # material) for Pass-1, same Mel-RoFormer karaoke Pass-2 as rock. Requires
    # one-time install via scripts/install_metal_model.py. Same tuning as rock,
    # since the genre challenges (screamed vocals, distorted guitar in vocal band,
    # gang vocals) overlap.
    "metal": SeparatorPreset(
        name="metal",
        instrumental_model="rifforge_full_sdr_14.2436.ckpt",
        karaoke_model="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        description="Mesk Rifforge (metal-tuned) + Mel-RoFormer karaoke. For screamed/distorted vocals.",
        defaults=PipelineDefaults(
            mix_strategy="subtract",
            vocal_gain=1.5,
            backing_boost=0.0,
            pad_ms=180.0,
            crossfade_ms=100.0,
            merge_gap_ms=350.0,
            energy_threshold=0.03,
            energy_window_ms=30.0,
            target_lufs=-14.0,
        ),
    ),

    # ---------- Internal / experimental — kept for A/B testing ----------
    # Ensemble Pass-1 with the pop-style UVR-BVE-4B Pass-2. Useful for songs that
    # don't have prominent harmonies — gives the cleanest single-vocal extraction.
    "ensemble": SeparatorPreset(
        name="ensemble",
        instrumental_model=(
            "model_bs_roformer_ep_317_sdr_12.9755.ckpt",
            "MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
            "UVR-MDX-NET-Inst_HQ_3.onnx",
        ),
        karaoke_model="UVR-BVE-4B_SN-44100-1.pth",
        description="Ensemble Pass-1 + UVR-BVE-4B Pass-2 (experimental).",
        ensemble_algorithm="uvr_max_spec",
        defaults=PipelineDefaults(
            mix_strategy="subtract",
            vocal_gain=1.5,
            target_lufs=-14.0,
        ),
    ),
    # Single BS-RoFormer (lighter than ensemble) + UVR-BVE-4B. Reference single-model.
    "bs-roformer": SeparatorPreset(
        name="bs-roformer",
        instrumental_model="model_bs_roformer_ep_317_sdr_12.9755.ckpt",
        karaoke_model="UVR-BVE-4B_SN-44100-1.pth",
        description="BS-RoFormer + UVR-BVE-4B (experimental, single-model SOTA).",
    ),
    # Legacy aliases — point users back to `pop` if they hit them
    "mdx23c": SeparatorPreset(  # alias for backwards compatibility
        name="mdx23c",
        instrumental_model="MDX23C-8KFFT-InstVoc_HQ_2.ckpt",
        karaoke_model="UVR-BVE-4B_SN-44100-1.pth",
        description="DEPRECATED — alias for 'pop'.",
    ),
    "demucs": SeparatorPreset(
        name="demucs",
        instrumental_model="htdemucs.yaml",
        karaoke_model="UVR_MDXNET_KARA_2.onnx",
        description="LEGACY — original demucs preset, kept for A/B.",
    ),
    "mel-roformer-karaoke": SeparatorPreset(
        name="mel-roformer-karaoke",
        instrumental_model="htdemucs.yaml",
        karaoke_model="mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
        description="LEGACY — pre-rock experimental preset.",
    ),
}


# User-facing presets that the CLI shows prominently; the rest are advanced.
PRIMARY_PRESETS = ("pop", "rock", "metal")


def resolve_default(preset: SeparatorPreset, field_name: str):
    """Return a preset's default for `field_name`, falling back to GLOBAL_DEFAULTS."""
    val = getattr(preset.defaults, field_name)
    if val is not None:
        return val
    return getattr(GLOBAL_DEFAULTS, field_name)


DEFAULT_WHISPER_MODEL = "medium"
SUPPORTED_WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
