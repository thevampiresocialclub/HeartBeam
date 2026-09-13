"""Model-boundary contracts, without downloading models or using the GPU."""
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from heartbeam.alignment_engine import align, unresolved_result
from heartbeam.timings import Timings, Source, Models, TimingsValidationError


def fake_models(monkeypatch):
    calls = dict(recognition=0, refinement=[])
    recognized = [dict(word=word, start=at+i*.5, end=at+i*.5+.4, score=.9)
                  for at in (1., 21.) for i,word in enumerate(['hello','there'])]
    def transcribe(*args, **kwargs):
        calls['recognition'] += 1
        return dict(language='en', segments=[dict(text='recognition', start=0, end=24)])
    def refine(segments, *args, **kwargs):
        if segments[0]['text'] == 'recognition':
            return dict(word_segments=recognized)
        calls['refinement'].append(segments)
        at = segments[0]['start'] + .1
        return dict(word_segments=[dict(word=w, start=at+i*.5, end=at+i*.5+.4, score=.9)
                                   for i,w in enumerate(segments[0]['text'].split())])
    monkeypatch.setitem(sys.modules, 'whisperx', SimpleNamespace(
        load_model=lambda *a,**k:SimpleNamespace(transcribe=transcribe),
        load_align_model=lambda **k:(None,None), align=refine))
    return calls


def test_selected_repeated_phrase_uses_whole_song_context_and_cached_recognition(tmp_path, monkeypatch):
    calls = fake_models(monkeypatch)
    audio=np.zeros(30*16000, dtype='float32')
    first=align(audio,16000,'hello there\nhello there',target_indices=[0],cache_dir=tmp_path)
    second=align(audio,16000,'hello there\nhello there',target_indices=[1],cache_dir=tmp_path)
    assert calls['recognition'] == 1
    assert first.lines[0].start_s < 2 and second.lines[0].start_s > 20
    assert len(first.lines) == len(second.lines) == 1


def test_manual_phrase_repair_skips_recognition(monkeypatch):
    calls=fake_models(monkeypatch)
    result=align(np.zeros(30*16000,dtype='float32'),16000,'hello there\nhello there',
                 target_indices=[1],manual_anchors={1:(10.,14.)})
    assert calls['recognition'] == 0
    assert result.lines[0].index == 1
    assert 10 <= result.lines[0].start_s < result.lines[0].end_s <= 14


@pytest.mark.parametrize('coherent', [True, False])
def test_gap_search_cannot_stamp_one_phrase_on_opposite_sides_of_a_long_break(monkeypatch, coherent):
    fake_models(monkeypatch)
    original = sys.modules['whisperx'].align
    def refine(segments, *a, **k):
        if segments[0]['text'] == 'stay with me now':
            times = [8., 8.5, 9., 9.5] if coherent else [3.1, 3.6, 17., 17.5]
            return dict(word_segments=[dict(word=w, start=t, end=t+.3, score=.9)
                        for w,t in zip(segments[0]['text'].split(), times)])
        return original(segments, *a, **k)
    sys.modules['whisperx'].align = refine
    result = align(np.zeros(30*16000, dtype='float32'), 16000,
        'hello there\nstay with me now\nhello there', manual_anchors={0:(1.,3.), 2:(18.,21.)})
    phrase = result.diagnostics['phrases'][1]
    if coherent:
        assert phrase['anchor']['source'] == 'gap' and len(result.lines[1].words) == 4
    else:
        assert phrase['anchor'] is None and not result.lines[1].words
        assert phrase['rejected_gap']['source'] == 'gap'
        assert phrase['state'] == 'match_needed'


@pytest.mark.parametrize('score',[None,.01])
def test_unreliable_refined_word_remains_in_lyric_with_no_timing(monkeypatch,score):
    fake_models(monkeypatch)
    sys.modules['whisperx'].align=lambda *a,**k:dict(word_segments=[
        dict(word='hello',start=10.1,end=10.5,score=.9),
        dict(word='there',start=10.6,end=11.,score=score)])
    result=align(np.zeros(30*16000,dtype='float32'),16000,'hello there',manual_anchors={0:(10.,14.)})
    phrase=result.diagnostics['phrases'][0]
    assert [w['text'] for w in phrase['words']] == ['hello','there']
    assert phrase['words'][1]['start_s'] is None and phrase['state'] == 'check'
    assert len(result.lines[0].words) == 1


def test_one_refinement_failure_does_not_discard_other_phrases(monkeypatch):
    fake_models(monkeypatch)
    original=sys.modules['whisperx'].align
    def refine(segments,*args,**kwargs):
        if segments[0]['start'] < 15:
            raise RuntimeError('phrase failed')
        return original(segments,*args,**kwargs)
    sys.modules['whisperx'].align=refine
    result=align(np.zeros(30*16000,dtype='float32'),16000,'hello there\nhello there',
                 manual_anchors={0:(10.,14.),1:(20.,24.)})
    assert not result.lines[0].words and len(result.lines[1].words) == 2


def test_failed_generation_preserves_lyrics_and_nullable_boundaries():
    result=unresolved_result('hello there\n# chorus\nback again','model unavailable')
    t=Timings(Source('song','lyrics',16000,30),Models('pop','phrase'),result.lines,alignment=result.diagnostics)
    loaded=Timings.from_dict(t.to_dict())
    assert len(loaded.alignment['phrases']) == 2
    assert len([w for p in loaded.alignment['phrases'] for w in p['words']]) == 4
    assert not any(line.words for line in loaded.lines)


@pytest.mark.parametrize('patch', [dict(start_s=1,end_s=None),dict(start_s=1,end_s=50,score=.9),
    dict(start_s=float('nan'),end_s=2,score=.9),dict(text='changed')])
def test_import_rejects_invalid_phrase_sidecar(patch):
    result=unresolved_result('hello there','needs timing')
    data=Timings(Source('song','lyrics',16000,30),Models('pop','phrase'),result.lines,alignment=result.diagnostics).to_dict()
    data['alignment']['phrases'][0]['words'][0].update(patch)
    with pytest.raises(TimingsValidationError):
        Timings.from_dict(data)


@pytest.mark.parametrize('prepare_only', [False, True])
def test_cli_saves_separation_when_alignment_fails(tmp_path, monkeypatch, prepare_only):
    from heartbeam import cli, align as align_mod, io, separate, project as P, timings as T
    monkeypatch.setattr(cli, '_preflight_gpu', lambda *a,**k:None)
    monkeypatch.setattr(cli, '_resolve_device', lambda *a:'cpu')
    signal=np.zeros((44100,2), dtype='float32')
    monkeypatch.setattr(io, 'load_audio', lambda *a,**k:(signal,44100))
    monkeypatch.setattr(io, 'write_mp3', lambda path,*a,**k:path.write_bytes(b'test audio'))
    monkeypatch.setattr(separate, 'separate', lambda *a,**k:{k:signal for k in ('instrumental','lead','backing','vocals')})
    monkeypatch.setattr(separate, 'release_models', lambda:None)
    def unavailable(*a,**k):
        raise RuntimeError('model unavailable')
    monkeypatch.setattr(align_mod, 'align', unavailable)
    song=tmp_path/'song.wav';song.write_bytes(b'test song')
    lyrics=tmp_path/'lyrics.txt';lyrics.write_text('hello there')
    out=tmp_path/'out'
    if prepare_only:
        from heartbeam import mask, mix
        def forbidden(*a, **k):
            pytest.fail('Preparation must not run the removal mask, mixer, or MP3 encoder')
        monkeypatch.setattr(mask, 'build_mask', forbidden)
        monkeypatch.setattr(mix, 'mix', forbidden)
        monkeypatch.setattr(mix, 'mix_replace', forbidden)
        monkeypatch.setattr(io, 'write_mp3', forbidden)
    assert cli.main([str(song),str(lyrics),'-o',str(out),'--device','cpu','--no-lufs'] +
                    (['--prepare-only'] if prepare_only else [])) == 0
    assert (out/'karaoke.mp3').exists() is not prepare_only
    assert (out/'timing-review-required.json').exists() is prepare_only
    t=T.from_json(out/'timings.json')
    assert 'model unavailable' in t.alignment['failure']
    assert (out/'cache'/'vocals.wav').is_file()
    p=P.import_legacy_timings(tmp_path/'project',out/'timings.json')
    assert [w.text for _,w in p.iter_words()] == ['hello','there']
    assert len(p.unresolved_words()) == 2


@pytest.mark.parametrize('retry_succeeds', [True, False])
def test_stalled_prefix_cannot_drag_supported_phrase_four_seconds_early(monkeypatch, retry_succeeds):
    fake_models(monkeypatch)
    observed = [dict(word="I'm",start=28.484,end=32.226,score=.812),
                dict(word='on',start=32.246,end=32.286,score=.002),
                dict(word='a',start=33.347,end=33.767,score=.694),
                dict(word='crosstown',start=33.967,end=34.928,score=.767),
                dict(word='train',start=35.008,end=35.568,score=.711),
                dict(word='again',start=35.648,end=36.529,score=.491)]
    windows=[]
    def refine(segments,*a,**k):
        segment=segments[0]
        if segment['text']=='recognition': return dict(word_segments=observed)
        windows.append(segment['start'])
        at=33. if len(windows)>1 and retry_succeeds else 28.5
        return dict(word_segments=[dict(word=w,start=at+i*.5,end=at+i*.5+.4,score=.8)
                    for i,w in enumerate(segment['text'].split())])
    sys.modules['whisperx'].align=refine
    result=align(np.zeros(45*16000,dtype='float32'),16000,"I'm on the cross-town train again")
    assert len(windows)==2 and windows[0]<29 and windows[1]>32
    if retry_succeeds:
        assert result.lines[0].start_s>=33 and len(result.lines[0].words)==6
    else:
        assert not result.lines[0].words
        assert result.diagnostics['phrases'][0]['state']=='check'
