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
