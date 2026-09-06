"""Smoke tests for the preset → CLI default fallback wiring."""
from heartbeam.cli import _apply_preset_defaults, _build_parser
from heartbeam.models import PRESETS, PRIMARY_PRESETS, GLOBAL_DEFAULTS


def _parse(argv: list[str]):
    args = _build_parser().parse_args(argv)
    _apply_preset_defaults(args, PRESETS[args.separator])
    return args


def test_pop_preset_defaults_replace_strategy():
    args = _parse(["song.mp3", "lyrics.txt", "--separator", "pop"])
    assert args.mix_strategy == "replace"
    assert args.pad_ms == 120.0
    assert args.crossfade_ms == 60.0
    assert args.energy_threshold == 0.05
    assert args.target_lufs == -14.0


def test_rock_preset_defaults_subtract_with_overshoot():
    args = _parse(["song.mp3", "lyrics.txt", "--separator", "rock"])
    assert args.mix_strategy == "subtract"
    assert args.vocal_gain == 1.5
    assert args.pad_ms == 180.0
    assert args.crossfade_ms == 100.0
    assert args.merge_gap_ms == 350.0
    assert args.energy_threshold == 0.03
    assert args.target_lufs == -14.0


def test_metal_preset_matches_rock_tuning():
    """Genre challenges overlap; metal preset reuses rock's mix/mask config."""
    rock = _parse(["song.mp3", "lyrics.txt", "--separator", "rock"])
    metal = _parse(["song.mp3", "lyrics.txt", "--separator", "metal"])
    for attr in ("mix_strategy", "vocal_gain", "backing_boost", "pad_ms",
                 "crossfade_ms", "merge_gap_ms", "energy_threshold", "target_lufs"):
        assert getattr(rock, attr) == getattr(metal, attr), \
            f"rock and metal differ on {attr}: {getattr(rock, attr)} vs {getattr(metal, attr)}"


def test_user_flag_overrides_preset():
    args = _parse(["song.mp3", "lyrics.txt", "--separator", "rock", "--pad-ms", "200"])
    assert args.pad_ms == 200.0
    # Other rock defaults still apply
    assert args.vocal_gain == 1.5


def test_no_lufs_disables_preset_target():
    args = _parse(["song.mp3", "lyrics.txt", "--separator", "rock", "--no-lufs"])
    assert args.target_lufs is None


def test_global_default_used_when_preset_has_no_value():
    # bs-roformer preset has only mix_strategy/vocal_gain/target_lufs set; others
    # should fall through to GLOBAL_DEFAULTS.
    args = _parse(["song.mp3", "lyrics.txt", "--separator", "bs-roformer"])
    assert args.pad_ms == GLOBAL_DEFAULTS.pad_ms
    assert args.crossfade_ms == GLOBAL_DEFAULTS.crossfade_ms


def test_primary_presets_constant():
    assert PRIMARY_PRESETS == ("pop", "rock", "metal")
    for name in PRIMARY_PRESETS:
        assert name in PRESETS
