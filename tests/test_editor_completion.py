import copy
import json
from pathlib import Path
import numpy as np
import pytest
import soundfile as sf

from heartbeam import project as P, lyrics as L, editor as E, vocal_mix as V
from heartbeam.commands import History, CommandError
from heartbeam.project_lock import WriterLease
from heartbeam.project_preview import current_timings


def song(tmp_path):
    p = P.create_project(tmp_path, "Editor test")
    L.apply_lyrics_edit(p, "# Verse\nalpha bravo\n# Chorus\ncharlie delta\n# Chorus\necho foxtrot\n")
    for i, wid in enumerate(p.word_ids()):
        p.original_alignment[wid] = P.WordTiming(100 + i * 500, 400 + i * 500, .1)
        p.timing_edits.pop(wid, None)
    return p


def calibrated(tmp_path):
    p = song(tmp_path)
    sr = 8000
    t = np.arange(sr * 4) / sr
    original = np.stack([np.sin(2 * np.pi * 220 * t), np.cos(2 * np.pi * 330 * t)], axis=1).astype(np.float32) * .4
    clean = original * .2
    for role, data in [("original_audio", original), ("clean_audio", clean),
                        ("lead_stem", original - clean), ("backing_stem", clean * 0), ("instrumental_stem", clean)]:
        path = tmp_path / f"{role}.wav"
        sf.write(path, data, sr, subtype="FLOAT")
        P.add_asset(p, tmp_path, path, role)
    V.bind_references(p, source_sha256="fixture", recipe={"mix_strategy": "subtract", "pad_ms": 0, "crossfade_ms": 20, "merge_gap_ms": 0})
    return p, clean, original, sr


def test_atomic_commands_reject_duplicate_stale_and_failed_changes(tmp_path):
    p = song(tmp_path); h = History(); wid = p.word_ids()[0]
    before = p.to_dict()
    with pytest.raises(CommandError):
        h.execute(p, lambda c: E.set_manual_timing(c, wid, 0, 800, 4000), command_id="bad", base_revision=0)
    assert p.to_dict() == before and not h.can_undo
    h.execute(p, lambda c: E.nudge(c, wid, 10), command_id="a", base_revision=0)
    assert p.revision == 1 and p.effective_timing(wid).start_ms == 110
    for cid, rev in [("a", 1), ("b", 0)]:
        with pytest.raises(CommandError):
            h.execute(p, lambda c: E.nudge(c, wid, 10), command_id=cid, base_revision=rev)
    h.undo(p); assert p.revision == 2 and p.effective_timing(wid).start_ms == 100
    h.redo(p); assert p.revision == 3 and p.effective_timing(wid).start_ms == 110


def test_undo_to_saved_content_is_not_dirty_just_because_command_ids_changed(tmp_path):
    from heartbeam.gui import _project_snapshot
    p=song(tmp_path); h=History(); before=_project_snapshot(p)
    h.execute(p,lambda c:E.nudge(c,c.word_ids()[0],10))
    assert _project_snapshot(p)!=before
    h.undo(p)
    assert _project_snapshot(p)==before


@pytest.mark.parametrize("value", [True, 1.2, float("nan"), float("inf"), "20", None])
def test_timing_requires_integer_milliseconds(tmp_path, value):
    p = song(tmp_path)
    assert not E.set_manual_timing(p, p.word_ids()[0], value, 300, 4000)[0]


def test_word_line_and_song_scope_are_independent(tmp_path):
    p = song(tmp_path); ids = p.word_ids()
    assert E.shift_timing(p, ids[0], 10, "word", 4000)[0]
    assert E.shift_timing(p, ids[0], 20, "line", 4000)[0]
    assert E.shift_timing(p, ids[0], 30, "song", 4000)[0]
    assert [p.effective_timing(w).start_ms for w in ids[:3]] == [160, 650, 1130]
    assert p.original_alignment[ids[0]].start_ms == 100


def test_imported_conflicts_can_be_repaired_without_hiding_them(tmp_path):
    p = song(tmp_path); a,b,c = p.word_ids()[:3]
    p.original_alignment[a].end_ms = 650
    p.original_alignment[b].end_ms = 1150
    assert len(E.timing_conflicts(p)) == 2
    assert E.set_manual_timing(p, a, 100, 600, 4000)[0]
    assert len(E.timing_conflicts(p)) == 1
    assert not E.set_manual_timing(p, b, 600, 1200, 4000)[0]


def test_section_identity_survives_rename_rewrap_and_repeated_headings(tmp_path):
    p = song(tmp_path); ids = [s.id for s in p.sections]; words = p.word_ids()
    L.apply_lyrics_edit(p, "# Intro\nalpha\nbravo\n# Chorus\ncharlie delta\n# Chorus\necho foxtrot\n")
    assert [s.id for s in p.sections] == ids and p.word_ids() == words
    L.apply_lyrics_edit(p, "alpha bravo\n# Chorus\ncharlie delta\n# Chorus\necho foxtrot\n")
    assert p.lines[0].section_id is None and [s.id for s in p.sections] == ids[1:]


def test_review_persists_without_changing_model_score(tmp_path):
    p = song(tmp_path); wid = p.word_ids()[0]
    p.reviewed[wid] = True
    P.save_project(p,tmp_path)
    q=P.load_project(tmp_path)
    assert E.next_low_confidence(q) != wid and q.effective_timing(wid).score == .1
    q.reviewed[wid]=False
    assert E.next_low_confidence(q)==wid


def test_single_writer_and_stale_save(tmp_path):
    p=song(tmp_path); P.save_project(p,tmp_path)
    first=P.load_project(tmp_path); second=P.load_project(tmp_path)
    with WriterLease(tmp_path):
        with pytest.raises(P.ProjectError): WriterLease(tmp_path)
    with WriterLease(tmp_path): pass
    first.name="new"; P.save_project(first,tmp_path)
    second.name="stale"
    with pytest.raises(P.ProjectError, match="changed"): P.save_project(second,tmp_path)
    assert P.load_project(tmp_path).name=="new"


@pytest.mark.parametrize("value", [0.,1.])
def test_vocal_endpoints_are_exact(tmp_path, value):
    p,clean,original,sr=calibrated(tmp_path)
    p.vocal_mix.default_value=value
    output=V.mix_arrays(clean,original,p.vocal_mix,sr)
    assert np.max(np.abs(output-(clean if value==0 else original))) < 1e-6


def test_region_replacement_splits_without_stacking_and_undoes(tmp_path):
    p=song(tmp_path); h=History()
    V.insert_region(p.vocal_mix,P.VocalRegion('a',100,2000,.2),4000)
    h.execute(p,lambda c: V.insert_region(c.vocal_mix,P.VocalRegion('b',500,1000,1),4000))
    assert [(r.start_ms,r.end_ms,r.value) for r in p.vocal_mix.regions]==[(100,500,.2),(500,1000,1),(1000,2000,.2)]
    assert len({r.id for r in p.vocal_mix.regions})==3
    h.undo(p); assert [r.id for r in p.vocal_mix.regions]==['a']
    h.redo(p); assert len(p.vocal_mix.regions)==3


@pytest.mark.parametrize("regions", [[], [(0,1,1),(1,2,0),(2,3,.2)],[(0,1000,.2),(1000,2000,1),(2000,4000,0)],[(3999,4000,1)]])
def test_continuous_bounded_envelope_handles_edges_and_short_regions(regions):
    mix=P.VocalMix(regions=[P.VocalRegion(str(i),a,b,v,80) for i,(a,b,v) in enumerate(regions)])
    knots=V.compile_envelope(mix,8000,32000)
    assert knots[0][0]==0 and knots[-1][0]==32000
    assert all(a[0]<b[0] for a,b in zip(knots,knots[1:]))
    env=V.envelope_array(knots,32000)
    assert np.isfinite(env).all() and env.min()>=0 and env.max()<=1
    for pos,value in knots[1:-1]:
        epsilon=1e-5
        nearby=np.interp([pos-epsilon,pos+epsilon],np.array(knots)[:,0],np.array(knots)[:,1])
        assert abs(nearby[0]-nearby[1])<1e-4


def test_preview_templates_and_offline_use_identical_envelope(tmp_path):
    p,clean,original,sr=calibrated(tmp_path)
    V.insert_region(p.vocal_mix,P.VocalRegion('old',300,1200,.7),4000)
    selection={'start_ms':600,'end_ms':2500,'transition_ms':100,'value':.2}
    data=V.preview_payload(p,tmp_path,lambda path,coord:str(path),selection)
    zero,one=[V.envelope_array(k,len(clean)) for k in data['templates']]
    V.insert_region(p.vocal_mix,P.VocalRegion('new',600,2500,.2,100),4000)
    exact=V.envelope_array(V.compile_envelope(p.vocal_mix,sr,len(clean)),len(clean))
    np.testing.assert_allclose(zero+.2*(one-zero),exact,atol=1e-7)


def test_saved_twenty_zero_hundred_regions_render_again(tmp_path):
    p,clean,original,sr=calibrated(tmp_path)
    for i,value in enumerate([.2,0.,1.]):
        V.insert_region(p.vocal_mix,P.VocalRegion(str(i),i*1000,(i+1)*1000,value),4000)
    P.save_project(p,tmp_path); p=P.load_project(tmp_path)
    rendered=V.render_mix(p,tmp_path,mastered=False)
    audio,rate=sf.read(rendered,dtype='float32',always_2d=True)
    assert rate==sr
    for i,v in enumerate([.2,0.,1.]):
        at=int((i+.5)*sr)
        np.testing.assert_allclose(audio[at],clean[at]+v*(original[at]-clean[at]),atol=1e-6)
    assert V.render_mix(p,tmp_path,mastered=False)==rendered


def test_lyric_edits_do_not_move_vocal_times_until_refit(tmp_path):
    p=song(tmp_path); ids=p.word_ids()[:2]
    a,b,words=V.lyric_range(p,word_ids=ids)
    V.insert_region(p.vocal_mix,P.VocalRegion('r',a,b,.2,40,source_word_ids=words),4000)
    assert E.shift_timing(p,ids[0],100,'line',4000)[0]
    assert p.vocal_mix.regions[0].start_ms==a
    V.refit(p,'r',4000)
    assert p.vocal_mix.regions[0].start_ms==a+100


def test_reference_rebuild_is_explicit_undoable_and_uses_current_timing(tmp_path):
    p,_,_,_=calibrated(tmp_path); h=History(); old=copy.deepcopy(p.vocal_mix.references)
    h.execute(p,lambda c: E.shift_timing(c,c.word_ids()[0],20,'song',4000))
    assert p.vocal_mix.references==old
    h.execute(p,lambda c: V.rebuild_clean(c,tmp_path))
    new_path=p.asset_by_role('clean_audio').resolve(tmp_path)
    assert new_path.exists() and p.vocal_mix.references['timing_hash']==V.timing_hash(p)
    h.undo(p); assert p.vocal_mix.references==old and new_path.exists()
    V.checked_references(p,tmp_path)


@pytest.mark.parametrize('strategy', ['subtract', 'replace'])
def test_rebuild_matches_pipeline_recipe_including_energy_transitions(tmp_path, strategy):
    from heartbeam import mask as M, mix as mixing
    p,clean,original,sr=calibrated(tmp_path)
    recipe={'mix_strategy':strategy,'vocal_gain':1.,'backing_boost':0.,'pad_ms':0,
            'crossfade_ms':120,'merge_gap_ms':0,'energy_window_ms':30,'energy_threshold':.1}
    lead=original-clean
    words=[w for ln in current_timings(p,4000).lines for w in ln.words]
    # Existing pipeline's two-mask recipe is the reference, independently of
    # the project preparation/persistence path being tested.
    mask=M.combine_masks(M.build_mask(words,len(clean),sr,pad_ms=0,xfade_ms=120,merge_gap_ms=0),
                         M.build_energy_mask(lead,sr,window_ms=30,threshold_rel=.1,xfade_ms=120))
    expected=(mixing.mix(original,lead,mask,clip=False) if strategy=='subtract' else
              mixing.mix_replace(original,clean,np.zeros_like(clean),mask,clip=False))
    output=V.rebuild_clean(p,tmp_path,recipe)
    actual=sf.read(output,dtype='float32',always_2d=True)[0]
    np.testing.assert_allclose(actual,expected,atol=1e-7)


def test_missing_or_replaced_reference_cannot_silently_change_gain_basis(tmp_path):
    p,_,_,_=calibrated(tmp_path)
    original=p.asset_by_role('original_audio').resolve(tmp_path)
    sf.write(original,np.zeros((32000,2),np.float32),8000,subtype='FLOAT')
    with pytest.raises(P.ProjectError,match='calibration'): V.checked_references(p,tmp_path)
    p.vocal_mix.references={}
    with pytest.raises(P.ProjectError,match='normalized'): V.checked_references(p,tmp_path)


def test_export_uses_current_timing_and_blocks_unresolved(tmp_path):
    p=song(tmp_path); wid=p.word_ids()[0]
    E.nudge(p,wid,10)
    assert current_timings(p,4000).lines[0].words[0].start_s==.11
    L.apply_lyrics_edit(p,L.to_text(p)+'new word\n')
    with pytest.raises(P.ProjectError,match='untimed'): current_timings(p,4000)
    assert len(current_timings(p,4000,draft=True).lines)==3


def test_reopening_discovers_the_matching_export_snapshot(tmp_path):
    from heartbeam.gui import _latest_project_video
    p=song(tmp_path)
    folder=tmp_path/P.EXPORTS_DIR/'rev-0-video-proof'; folder.mkdir(parents=True)
    (folder/'karaoke.mp4').write_bytes(b'fixture')
    (folder/'project-snapshot.json').write_text(json.dumps(p.to_dict()))
    assert _latest_project_video(p,tmp_path)==(0,str(folder/'karaoke.mp4'))
    p.id='different-song'
    assert _latest_project_video(p,tmp_path) is None


def test_final_master_has_bounded_oversampled_peak_and_handles_short_silence():
    from scipy.signal import resample_poly
    a=np.tile(np.array([.9,.9,-.9,-.9]),(8000,1)).reshape(-1,1).repeat(2,axis=1)
    out=V.master(a,8000)
    assert np.max(np.abs(resample_poly(out,4,1,axis=0)))<=10**(-1/20)+1e-6
    assert np.isfinite(V.master(np.zeros((20,2)),8000)).all()


def test_ass_quantization_does_not_accumulate_word_duration_rounding():
    import re
    from heartbeam import timings as T
    from heartbeam.ass_writer import render_ass_to_string
    from heartbeam.style import Style
    words=[T.Word(str(i),i*.035,i*.035+.015) for i in range(10)]
    t=T.Timings(T.Source('', '', 8000, 1),T.Models('',''),[T.Line(0,'',0,words[-1].end_s,words)])
    ass=render_ass_to_string(t,Style())
    assert sum(map(int,re.findall(r'\\k(\d+)',ass)))==round(words[-1].end_s*100)


@pytest.mark.media
def test_video_does_not_keep_an_encoder_tail_after_audio_ends(tmp_path):
    import shutil, subprocess
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('ffmpeg and ffprobe required')
    from heartbeam.render import render
    from heartbeam.ass_writer import write_ass
    from heartbeam.project_preview import preview_style
    p=song(tmp_path)
    audio=tmp_path/'long.wav'; sf.write(audio,np.zeros(17*8000+2568,np.float32),8000)
    ass=tmp_path/'lyrics.ass'; style=preview_style(p); style.video.resolution='320x180'
    write_ass(current_timings(p,17321),style,ass)
    output=tmp_path/'proof.mp4'; render(audio,ass,output,style)
    result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(output)],capture_output=True,text=True,check=True)
    assert abs(float(json.loads(result.stdout)['format']['duration'])-17.321)<1/30+.005
