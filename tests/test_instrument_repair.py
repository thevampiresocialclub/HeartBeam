import json

import numpy as np
import pytest
import soundfile as sf

from heartbeam import instrument_repair as R, project as P, stem_mix as M, vocal_mix as V


def _project(root, sr=1000, count=4000):
    p = P.Project("repair-test", "Repair test")
    for role, value in (("instrumental_stem", .1), ("lead_stem", .02), ("backing_stem", .03)):
        path = root / f"{role}.wav"
        sf.write(path, np.full((count, 2), value, np.float32), sr, subtype="FLOAT")
        asset = P.add_asset(p, root, path, role, copy_into_project=False)
        asset.sample_rate, asset.channels, asset.sample_count = sr, 2, count
    return p


def test_level_repair_is_bounded_reversible_and_used_by_stem_resolver(tmp_path):
    p = _project(tmp_path)
    repair = R.create_level_repair(p, tmp_path, 1000, 2000, gain_db=6, fade_ms=100)
    p.music_repair.repairs.append(repair)
    paths, basis = M.checked(p, tmp_path)
    raw = sf.read(p.asset_by_role("instrumental_stem").resolve(tmp_path), dtype="float32")[0]
    fixed = sf.read(paths["instrumental_stem"], dtype="float32")[0]
    assert basis == (1000, 2, 4000)
    np.testing.assert_array_equal(fixed[:1000], raw[:1000])
    np.testing.assert_array_equal(fixed[2000:], raw[2000:])
    assert fixed[1500, 0] == pytest.approx(raw[1500, 0] * 10 ** (6 / 20), rel=2e-5)
    repair.status = "disabled"
    assert M.checked(p, tmp_path)[0]["instrumental_stem"] == p.asset_by_role("instrumental_stem").resolve(tmp_path)


def test_repairs_reject_overlap_and_wrong_basis(tmp_path):
    p = _project(tmp_path)
    first = R.create_level_repair(p, tmp_path, 500, 1500, gain_db=3)
    p.music_repair.repairs.append(first)
    with pytest.raises(P.ProjectError, match="overlaps"):
        R.create_level_repair(p, tmp_path, 1000, 1800, gain_db=3)
    wrong = P.InstrumentRepair(**{**first.__dict__, "id": "wrong", "sample_count": 2})
    with pytest.raises(P.ProjectError, match="sample basis"):
        R.apply_repairs(np.zeros((4000, 2), np.float32), [wrong], 1000)


def test_preview_and_export_mix_resolve_the_same_repaired_instrumental(tmp_path):
    p = _project(tmp_path)
    p.vocal_mix.restoration_mode = M.MODE
    repair = R.create_level_repair(p, tmp_path, 1000, 2000, gain_db=6, fade_ms=0)
    p.music_repair.repairs.append(repair)
    rendered = V.render_mix(p, tmp_path, mastered=False)
    audio, sr = sf.read(rendered, dtype="float32", always_2d=True)
    assert sr == 1000
    assert audio[500, 0] == pytest.approx(.13, abs=2e-6)
    assert audio[1500, 0] == pytest.approx(.1 * 10 ** (6 / 20) + .03, abs=2e-6)


def test_schema_one_migrates_and_keeps_recoverable_backup(tmp_path):
    p = _project(tmp_path)
    P.save_project(p, tmp_path)
    manifest = tmp_path / P.MANIFEST_NAME
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    raw["project_schema_version"] = 1
    raw.pop("music_repair", None)
    manifest.write_text(json.dumps(raw), encoding="utf-8")
    migrated = P.load_project(tmp_path)
    assert migrated.schema_version == 2 and migrated.music_repair.repairs == []
    P.save_project(migrated, tmp_path, bump=False)
    assert (tmp_path / "project.schema-1.backup.json").is_file()
    assert json.loads(manifest.read_text(encoding="utf-8"))["project_schema_version"] == 2


def test_recorded_reallocation_recovers_supported_leak_and_conserves_stem_sum():
    sr = 8000
    t = np.arange(sr * 3, dtype=np.float32) / sr
    stable = .10 * np.sin(2 * np.pi * 220 * t)
    leaked_instrument = .05 * np.sin(2 * np.pi * 440 * t)
    vocal = .08 * np.sin(2 * np.pi * 713 * t)
    instrumental = stable
    lead = vocal + leaked_instrument
    backing = np.zeros_like(lead)
    alternate = stable + leaked_instrument
    ri, rl, rb, diagnostics = R.recorded_reallocation(
        instrumental, lead, backing, alternate, sr, start_sample=sr // 2,
        end_sample=sr * 5 // 2, fade_ms=50)
    before = instrumental + lead + backing
    np.testing.assert_allclose(ri + rl + rb, before, atol=2e-7)
    center = slice(sr, sr * 2)
    donor = ri - instrumental
    recovered = abs(np.vdot(donor[center], leaked_instrument[center]))
    vocal_leak = abs(np.vdot(donor[center], vocal[center]))
    assert recovered > vocal_leak * 20
    assert diagnostics["donor_rms"] > 0
    assert diagnostics["alternate_model_count"] == 1
    np.testing.assert_array_equal(ri[:sr // 2], instrumental[:sr // 2])
    zero = R.recorded_reallocation(instrumental, lead, backing, alternate, sr, strength=0)
    np.testing.assert_array_equal(zero[0], instrumental)

    # A second model that does not support the leaked instrument should veto it.
    conservative = R.recorded_reallocation(
        instrumental, lead, backing, [alternate, stable], sr,
        start_sample=sr // 2, end_sample=sr * 5 // 2, fade_ms=50)
    assert conservative[3]["alternate_model_count"] == 2
    assert conservative[3]["donor_rms"] < diagnostics["donor_rms"] * .05


@pytest.mark.parametrize('leak', [.01, .1, .5])
def test_shared_model_vocal_leak_cannot_authorize_a_larger_transfer(leak):
    sr = 16000
    t = np.arange(sr * 3) / sr
    music = .1 * np.sin(2 * np.pi * 220 * t)
    vocal = .08 * np.sin(2 * np.pi * 713 * t)
    alternate = music + leak * vocal
    fixed, _, _, _ = R.recorded_reallocation(
        music, vocal, np.zeros_like(vocal), [alternate, alternate], sr,
        start_sample=sr // 2, end_sample=sr * 5 // 2)
    center = slice(sr, sr * 2)
    returned = abs(np.vdot((fixed - music)[center], vocal[center]) /
                   np.vdot(vocal[center], vocal[center]))
    assert returned <= leak * 1.01


def test_solo_instrumental_follows_apply_and_undo(tmp_path):
    from heartbeam import editor_media as EM
    p = _project(tmp_path)
    p.vocal_mix.restoration_mode = M.MODE
    raw = p.asset_by_role('instrumental_stem').resolve(tmp_path)
    before = P.file_sha256(raw)
    p.music_repair.repairs.append(R.create_level_repair(p, tmp_path, 500, 1500, gain_db=3))
    solo = lambda: next(s for s in EM.source_files(p, tmp_path, raw) if s['id'] == 'instrumental')
    assert solo()['path'] == M.checked(p, tmp_path)[0]['instrumental_stem'] != raw
    p.music_repair.repairs[0].status = 'disabled'
    assert solo()['path'] == raw and P.file_sha256(raw) == before


def test_legacy_mix_cannot_silently_ignore_an_applied_repair(tmp_path):
    from heartbeam import repair_ui as UI
    p = _project(tmp_path)
    with pytest.raises(P.ProjectError, match='separate lead and backing'):
        UI._add_repair(p, tmp_path, 500, 1500, 3, 120)
    assert not p.music_repair.repairs
    p.music_repair.repairs.append(R.create_level_repair(p, tmp_path, 500, 1500, gain_db=3))
    with pytest.raises(P.ProjectError, match='separate lead and backing'):
        V.checked_references(p, tmp_path)
