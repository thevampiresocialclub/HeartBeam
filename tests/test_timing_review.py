"""The user reviews the current lyrics before a removal mix can be built."""
import copy
import numpy as np
import pytest
import soundfile as sf
from heartbeam import timing_review as R, project as P, editor as E, vocal_mix as V
from heartbeam.commands import History
from heartbeam.project_preview import current_timings
from tests.test_editor_completion import calibrated


def pending(tmp_path):
    p,clean,original,sr = calibrated(tmp_path)
    p.alignment['review'] = {'required':True}
    p.vocal_mix.references['recipe']['pending_timing_review'] = True
    return p,clean,original,sr


def test_pending_review_allows_preview_but_blocks_removal_and_export(tmp_path):
    p,*_=pending(tmp_path)
    assert current_timings(p,4000,draft=True).lines
    with pytest.raises(P.ProjectError,match='Review and approve'):
        current_timings(p,4000)
    with pytest.raises(P.ProjectError,match='Review and approve'):
        V.rebuild_clean(p,tmp_path)


def test_approval_build_survives_save_copy_and_undo_but_changes_need_review(tmp_path):
    p,*_=pending(tmp_path);h=History()
    source=p.asset_by_role('original_audio').sha256
    h.execute(p,lambda c:R.approve_and_build(c,tmp_path,keep_backing=False))
    assert R.approved(p) and current_timings(p,4000).lines
    assert p.asset_by_role('karaoke_audio').resolve(tmp_path).is_file()
    assert not p.asset_by_role('karaoke_audio').external
    assert p.asset_by_role('original_audio').sha256==source
    assert 'pending_timing_review' not in p.vocal_mix.references['recipe']
    P.save_project(p,tmp_path)
    assert R.approved(P.load_project(tmp_path))
    copied=P.save_project_as(p,tmp_path/'copy',src_dir=tmp_path)
    assert R.approved(copied)
    assert h.undo(p) and not R.approved(p)
    assert h.redo(p) and R.approved(p)
    q=copy.deepcopy(p);q.lines[0].words[0].text='changed';assert not R.approved(q)
    q=copy.deepcopy(p);q.asset_by_role('original_audio').sha256='changed';assert not R.approved(q)
    q=copy.deepcopy(p);q.name='Renamed';q.reviewed[q.word_ids()[0]]=True;assert R.approved(q)
    E.nudge(p,p.word_ids()[0],10)
    assert not R.approved(p)


def test_failed_build_does_not_approve_or_mutate_live_project(tmp_path,monkeypatch):
    p,*_=pending(tmp_path);before=p.to_dict();h=History()
    def fail(*a,**k):raise RuntimeError('encoder failed')
    from heartbeam import io
    monkeypatch.setattr(io,'write_mp3',fail)
    with pytest.raises(RuntimeError,match='encoder failed'):
        h.execute(p,lambda c:R.approve_and_build(c,tmp_path))
    assert p.to_dict()==before and not R.approved(p) and not h.can_undo


def test_instrumental_option_excludes_the_lead_leaking_into_backing(tmp_path):
    p,clean,original,sr=pending(tmp_path)
    backing=p.asset_by_role('backing_stem')
    sf.write(backing.resolve(tmp_path),original*.3,sr,subtype='FLOAT')
    backing.sha256=P.file_sha256(backing.resolve(tmp_path))
    p.vocal_mix.references['recipe'].update(mix_strategy='replace',crossfade_ms=0)
    a=copy.deepcopy(p);b=copy.deepcopy(p)
    R.approve_and_build(a,tmp_path,keep_backing=True)
    R.approve_and_build(b,tmp_path,keep_backing=False)
    with_back=sf.read(a.asset_by_role('clean_audio').resolve(tmp_path))[0]
    without=sf.read(b.asset_by_role('clean_audio').resolve(tmp_path))[0]
    i=int(.2*sr)  # inside the first approved word
    np.testing.assert_allclose(with_back[i],clean[i]+original[i]*.3,atol=1e-7)
    np.testing.assert_allclose(without[i],clean[i],atol=1e-7)
    np.testing.assert_allclose(without[int(.45*sr)],original[int(.45*sr)],atol=1e-7)


def test_phrase_projects_require_review_but_legacy_projects_still_open(tmp_path):
    p,*_=calibrated(tmp_path)
    assert R.approved(p)
    p.alignment['phrases']={'line':{'state':'ready'}}
    assert R.required(p) and not R.approved(p)


def test_changed_audio_and_missing_word_cannot_be_approved(tmp_path):
    p,*_=pending(tmp_path);h=History();before=p.to_dict()
    lead=p.asset_by_role('lead_stem').resolve(tmp_path)
    samples,sr=sf.read(lead);sf.write(lead,samples*.5,sr,subtype='FLOAT')
    with pytest.raises(P.ProjectError,match='track changed'):
        h.execute(p,lambda c:R.approve_and_build(c,tmp_path))
    assert p.to_dict()==before and not R.approved(p)
    p.asset_by_role('lead_stem').sha256=P.file_sha256(lead)
    p.timing_edits[p.word_ids()[0]]=P.WordTiming(reason='needs timing')
    with pytest.raises(P.ProjectError,match='untimed'):
        h.execute(p,lambda c:R.approve_and_build(c,tmp_path))
    assert not R.approved(p)
