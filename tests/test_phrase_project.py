import copy
import json
import numpy as np
import pytest
import soundfile as sf
from heartbeam import project as P, lyrics as L
from heartbeam.commands import History, CommandError
from heartbeam.phrase_project import apply_result, vocal_audio, review_lines
from heartbeam.timings import AlignmentResult, Timings, Source, Models, Line, to_json


def song(tmp_path):
    p = P.create_project(tmp_path/'song','Song')
    L.apply_lyrics_edit(p,'hello there\nhello there')
    return p


def result(p, index=1):
    line = p.lines[index]
    words = [dict(text=w.text,start_s=5.+i,end_s=5.5+i,score=.9,reason=None) for i,w in enumerate(line.words)]
    return AlignmentResult([], 'en',0,2,dict(input_lines={str(index):line.id},
        input_words={str(index):[[w.id,w.text] for w in line.words]},
        phrases=[dict(index=index,text=line.text,words=words,anchor=None,issues=[],state='ready')]))


def test_selected_duplicate_line_preserves_other_occurrence_and_manual_edit(tmp_path):
    p=song(tmp_path)
    first=p.lines[0].words[0].id
    manual=p.lines[1].words[0].id
    p.timing_edits[first]=P.WordTiming(100,400)
    p.timing_edits[manual]=P.WordTiming(5100,5600)
    h=History()
    before=copy.deepcopy(p.to_dict())
    h.execute(p,lambda candidate:apply_result(candidate,result(candidate)))
    assert p.effective_timing(first).start_ms == 100
    assert p.effective_timing(manual).start_ms == 5100
    assert p.effective_timing(p.lines[1].words[1].id).start_ms == 6000
    h.undo(p)
    assert p.alignment == before['alignment']
    assert p.effective_timing(p.lines[1].words[1].id).start_ms is None
    h.redo(p)
    P.save_project(p,tmp_path/'song')
    assert P.load_project(tmp_path/'song').alignment == p.alignment


def test_changed_lyrics_reject_stale_result_without_mutation(tmp_path):
    p=song(tmp_path); proposed=result(p)
    L.apply_lyrics_edit(p,'hello there\nhello changed')
    before=p.to_dict()
    with pytest.raises(P.ProjectError,match='Lyrics changed'):
        History().execute(p,lambda candidate:apply_result(candidate,proposed))
    assert before == p.to_dict()


def test_unreliable_new_result_replaces_bad_automatic_time_with_unresolved(tmp_path):
    p=song(tmp_path); proposed=result(p)
    wid=p.lines[1].words[0].id
    p.timing_edits.pop(wid,None)
    p.original_alignment[wid]=P.WordTiming(22000,22100)
    proposed.diagnostics['phrases'][0]['words'][0].update(start_s=None,end_s=None,score=None,reason='Needs matching')
    apply_result(p,proposed)
    assert not p.effective_timing(wid).resolved
    assert p.original_alignment[wid].start_ms == 22000


def test_full_vocal_fallback_includes_backing(tmp_path):
    p=song(tmp_path)
    for role,name,value in [('lead_stem','lead.wav',.1),('backing_stem','backing.wav',.2)]:
        path=tmp_path/name
        sf.write(path,np.full((800,2),value,dtype='float32'),8000,subtype='FLOAT')
        P.add_asset(p,tmp_path/'song',path,role,copy_into_project=True)
    samples,sr,source=vocal_audio(p,tmp_path/'song')
    assert sr == 8000 and np.allclose(samples,.3)
    assert 'backing' in source


def test_changed_vocal_asset_is_not_silently_used(tmp_path):
    p=song(tmp_path)
    path=tmp_path/'vocals.wav'
    sf.write(path,np.zeros((800,2),dtype='float32'),8000,subtype='FLOAT')
    asset=P.add_asset(p,tmp_path/'song',path,'vocals_stem',copy_into_project=True)
    sf.write(asset.resolve(tmp_path/'song'),np.ones((800,2),dtype='float32'),8000,subtype='FLOAT')
    with pytest.raises(P.ProjectError,match='has changed'):
        vocal_audio(p,tmp_path/'song')


def test_partial_generation_import_keeps_every_source_token(tmp_path):
    words=[dict(text='hello',start_s=1.,end_s=1.5,score=.9,reason=None),
           dict(text='there',start_s=None,end_s=None,score=None,reason='Needs matching')]
    from heartbeam.timings import Word
    t=Timings(Source('song','lyrics',8000,4),Models('pop','phrase'),
       [Line(0,'hello there',1,1.5,[Word('hello',1,1.5,.9)])],
       alignment=dict(version=1,phrases=[dict(index=0,text='hello there',words=words,anchor=None,issues=['Some words need timing'],state='check')]))
    path=tmp_path/'timings.json';to_json(t,path)
    p=P.import_legacy_timings(tmp_path/'imported',path)
    assert [w.text for _,w in p.iter_words()] == ['hello','there']
    assert len(p.unresolved_words()) == 1
    assert len(review_lines(p)) == 1


def test_only_missing_keeps_existing_automatic_timing(tmp_path):
    p=song(tmp_path); proposed=result(p)
    wid=p.lines[1].words[1].id
    p.timing_edits.pop(wid,None)
    p.original_alignment[wid]=P.WordTiming(1000,1500)
    apply_result(p,proposed,only_unresolved=True)
    assert p.effective_timing(wid).start_ms == 1000
