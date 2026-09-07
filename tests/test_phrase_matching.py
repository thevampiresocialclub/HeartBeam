from heartbeam.alignment_match import token_pairs, phrase_anchors, online_anchors, word_review
from heartbeam.lyrics_lookup import lookup, parse_lrc


def spoken(text, start=0):
    return [dict(word=w, start=start+i*.5, end=start+i*.5+.4) for i,w in enumerate(text.split())]


def test_missing_verse_is_not_allocated_to_intro():
    lines = [(0,'what is forever for'),(1,'what is forever for'),(2,'cross town train again'),(3,'downtown girl uptown accent')]
    words = spoken(lines[0][1], 0)+spoken(lines[1][1], 8)+spoken(lines[3][1], 30)
    anchors = phrase_anchors(lines, words, 50)
    assert 2 not in anchors
    assert anchors[3]['onset_s'] == 30
    assert anchors[1]['onset_s'] == 8


def test_dropped_recognition_does_not_shift_later_phrases():
    pairs = token_pairs('alpha bravo charlie delta'.split(), 'alpha charlie delta'.split())
    assert pairs == [(0,0),(2,1),(3,2)]


def test_case_punctuation_and_slight_asr_mishearing():
    assert token_pairs(["Don't", 'forever'], ['dont', 'forever!']) == [(0,0),(1,1)]


def test_22_second_gap_does_not_become_phrase_anchor():
    words = spoken('what',65)+spoken('is forever for',88)
    assert not phrase_anchors([(0,'what is forever for')],words,100)


def test_two_refrains_get_separate_intervals():
    lines = [(0,'we come home'),(1,'we come home')]
    anchors = phrase_anchors(lines, spoken('we come home',10)+spoken('we come home',50),70)
    assert anchors[0]['onset_s'] == 10
    assert anchors[1]['onset_s'] == 50


def test_database_offset_needs_distributed_evidence():
    lines = [(0,'alpha bravo'),(1,'charlie delta'),(2,'echo foxtrot')]
    lrc = [dict(text=t,start_s=s) for (_,t),s in zip(lines,[10,40,80])]
    audio = phrase_anchors(lines, spoken('alpha bravo',12)+spoken('charlie delta',42)+spoken('echo foxtrot',82),100)
    anchors, note = online_anchors(lines,lrc,audio,100)
    assert len(anchors) == 3 and '+2.00' in note
    anchors, _ = online_anchors(lines,lrc,{0:audio[0]},100)
    assert not anchors


def test_database_wrong_arrangement_is_rejected():
    lines = [(0,'alpha bravo'),(1,'charlie delta'),(2,'echo foxtrot')]
    lrc = [dict(text=t,start_s=s) for (_,t),s in zip(lines,[10,40,80])]
    audio = phrase_anchors(lines, spoken('alpha bravo',12)+spoken('charlie delta',55)+spoken('echo foxtrot',82),100)
    assert not online_anchors(lines,lrc,audio,100)[0]


def test_database_lying_duration_is_rejected_even_if_early_phrases_match():
    lines=[(0,'alpha bravo'),(1,'charlie delta'),(2,'echo foxtrot')]
    audio=phrase_anchors(lines,spoken(lines[0][1],10)+spoken(lines[1][1],40)+spoken(lines[2][1],80),100)
    cues=[dict(text=t,start_s=s) for (_,t),s in zip(lines,[10,40,80])]
    cues.append(dict(text='another missing chorus',start_s=125))
    anchors,note=online_anchors(lines,cues,audio,100)
    assert not anchors and '125.0s' in note and '100.0s' in note


def test_different_line_breaks_keep_phrase_identity():
    lines = [(0,'alpha bravo charlie delta'),(1,'echo foxtrot'),(2,'golf hotel')]
    lrc = [dict(text=t,start_s=s) for t,s in [('alpha bravo',10),('charlie delta',12),('echo foxtrot',40),('golf hotel',80)]]
    audio = phrase_anchors(lines, spoken(lines[0][1],10)+spoken(lines[1][1],40)+spoken(lines[2][1],80),100)
    anchors,_ = online_anchors(lines,lrc,audio,100)
    assert anchors[0]['start_s'] == 9.5


def test_lrc_offsets_empty_breaks_and_repeated_stamps():
    lines = parse_lrc('[ar:artist]\n[offset:500]\n[00:01.20][00:10.20]hello\n[00:04.00]\n[00:99]bad')
    assert lines == [dict(start_s=1.7,text='hello'),dict(start_s=4.5,text=''),dict(start_s=10.7,text='hello')]


def test_lookup_cache_survives_offline(tmp_path):
    metadata = dict(title='Song',artist='Artist',duration=50)
    def request(route, params):
        return dict(id=1,trackName='Song',artistName='Artist',duration=50,plainLyrics='hello',syncedLyrics='[00:02]hello')
    first = lookup(metadata,tmp_path,request=request)
    def offline(*args):
        raise OSError('offline')
    cached = lookup(metadata,tmp_path,request=offline)
    assert first['candidates'] == cached['candidates']
    assert 'saved' in cached['status']


def test_lookup_offline_with_no_cache_is_actionable(tmp_path):
    def offline(*args):
        raise OSError('offline')
    result = lookup(dict(title='Song',artist='Artist'),tmp_path,request=offline)
    assert result['candidates'] == []
    assert 'local timing' in result['status']


def test_plain_text_result_has_no_fabricated_timing(tmp_path):
    def request(route, params):
        item = dict(id=1,trackName='Song',artistName='Artist',duration=50,plainLyrics='hello',syncedLyrics=None)
        return item if route == 'get' else [item]
    result = lookup(dict(title='Song',artist='Artist'),tmp_path,request=request)
    assert result['candidates'][0]['synced_lines'] == []


def test_review_catches_compressed_word_and_long_gap():
    assert 'Very short word timing' in word_review([dict(start_s=1,end_s=1.02,score=.8)])
    assert 'Long gap inside the phrase' in word_review([dict(start_s=1,end_s=2,score=.8),dict(start_s=25,end_s=26,score=.8)])
