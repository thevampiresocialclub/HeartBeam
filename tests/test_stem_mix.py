import copy
import numpy as np
import pytest
import soundfile as sf
from heartbeam import project as P, vocal_mix as V, stem_mix as M, timing_review as R
from heartbeam.commands import History
from heartbeam.editor_ui import track_action
from tests.test_timing_review import pending


def test_independent_tracks_preserve_instrumental_and_precise_low_lead_levels():
    sr = 8000; t = np.arange(sr) / sr
    instrumental = (.2 * np.sin(2 * np.pi * 200 * t)).astype(np.float32)
    lead = (.3 * np.sin(2 * np.pi * 400 * t)).astype(np.float32)
    backing = (.1 * np.sin(2 * np.pi * 800 * t)).astype(np.float32)
    mix = P.VocalMix(restoration_mode=M.MODE, default_value=.03, backing_value=.5)
    result = M.mix_arrays(instrumental, lead, backing, mix, sr)
    np.testing.assert_allclose(result, instrumental + .03 * lead + .5 * backing, atol=3e-8)
    amplitudes = np.abs(np.fft.rfft(result)) * 2 / sr
    np.testing.assert_allclose(amplitudes[[200, 400, 800]], [.2, .009, .05], atol=1e-8)
    mix.default_value = mix.backing_value = 0
    np.testing.assert_array_equal(M.mix_arrays(instrumental, lead, backing, mix, sr), instrumental)
    mix.default_value = mix.backing_value = 1
    np.testing.assert_allclose(M.mix_arrays(instrumental, lead, backing, mix, sr), instrumental + lead + backing, atol=6e-8)


def test_lead_regions_do_not_change_backing_track():
    mix = P.VocalMix(restoration_mode=M.MODE, default_value=.03, backing_value=.4,
                    regions=[P.VocalRegion('r', 200, 500, .8)])
    a = np.ones(8000, dtype=np.float32)
    output = M.mix_arrays(a * .1, a * .2, a * .3, mix, 8000)
    assert output[100] == pytest.approx(.1 + .2 * .03 + .3 * .4)
    assert output[2800] == pytest.approx(.1 + .2 * .8 + .3 * .4)


def test_build_controls_save_undo_export_and_cache_use_the_same_tracks(tmp_path):
    p, clean, original, sr = pending(tmp_path); before = copy.deepcopy(p.original_alignment)
    h = History()
    h.execute(p, lambda c: R.approve_and_build(c, tmp_path, allow_incomplete=True, separate_tracks=True, backing_level=.5))
    assert p.vocal_mix.restoration_mode == M.MODE and R.approved(p)
    assert p.vocal_mix.backing_value == .5
    h.execute(p, lambda c: track_action(c, {'track': 'lead', 'value': .03}))
    h.execute(p, lambda c: track_action(c, {'track': 'backing', 'value': .4}))
    first_key = V.mix_key(p)
    path = V.render_mix(p, tmp_path, mastered=False)
    rendered = sf.read(path, dtype='float32', always_2d=True)[0]
    np.testing.assert_allclose(rendered, clean + .03 * (original - clean), atol=2e-8)
    P.save_project(p, tmp_path); q = P.load_project(tmp_path)
    assert V.mix_key(q) == first_key and R.approved(q) and q.original_alignment == before
    payload = V.preview_payload(q, tmp_path, lambda path, coord: str(path))
    assert payload['mode'] == M.MODE and payload['backing_value'] == .4 and payload['default_value'] == .03
    assert payload['original'] is None and payload['lead'] and payload['backing']
    h.undo(p); assert p.vocal_mix.backing_value == .5 and V.mix_key(p) != first_key
    h.redo(p); assert V.mix_key(p) == first_key


def test_replaced_or_mismatched_stems_are_rejected(tmp_path):
    p, *_ = pending(tmp_path); M.enable(p, tmp_path)
    asset = p.asset_by_role('backing_stem')
    sf.write(asset.resolve(tmp_path), np.zeros((500, 2)), 8000, subtype='FLOAT')
    with pytest.raises(P.ProjectError, match='changed'):
        V.render_mix(p, tmp_path)
    asset.sha256 = P.file_sha256(asset.resolve(tmp_path))
    with pytest.raises(P.ProjectError, match='same sample rate'):
        V.render_mix(p, tmp_path)


@pytest.mark.media
def test_stem_only_project_exports_the_mix_without_legacy_references(tmp_path):
    import json
    from pathlib import Path
    from heartbeam import export_jobs as J, presentation as S
    from tests.test_export_jobs import _wait
    p, *_ = pending(tmp_path)
    p.alignment['review'] = {'required': False}
    p.vocal_mix.references = {}
    M.enable(p, tmp_path, backing=.5)
    track_action(p, {'track': 'lead', 'value': .03})
    S.apply_style(p, {'video': {'resolution': '320x180'}})
    done = _wait(J.start(p, tmp_path, tmp_path/'missing-initial.mp3').id)
    assert done.status == 'complete', done.error
    manifest = json.loads((Path(done.output_path).parent/'export-manifest.json').read_text())
    assert manifest['audio_sha256'] == P.file_sha256(V.render_mix(p, tmp_path))
