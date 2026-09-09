import copy
import pytest
from heartbeam import project as P, editor as E, presentation as S
from heartbeam.commands import History


def phrase():
    p = P.Project('estimate-test', 'Original test')
    p.lines = [P.Line('line', [P.Word(str(i), text) for i, text in enumerate(['Sing', 'the', 'next', 'word'])])]
    p.original_alignment = {'0': P.WordTiming(100, 300), '3': P.WordTiming(1000, 1500)}
    return p


def test_estimates_fill_a_run_without_mutating_sources_and_follow_anchor_edits(tmp_path):
    p = phrase(); before = copy.deepcopy(p.to_dict())
    a, b = p.effective_timing('1'), p.effective_timing('2')
    assert a.estimated and b.estimated and 300 == a.start_ms < a.end_ms == b.start_ms < b.end_ms == 1000
    assert p.to_dict() == before and not p.reviewed
    assert E.next_low_confidence(p) == '1'
    p.timing_edits['1'] = P.WordTiming(reason='No acoustic match')
    assert E.next_low_confidence(p) == '1'
    p.timing_edits.clear()
    assert not E.timing_conflicts(p)
    assert 'estimated timing' in ' '.join(S.compile_project(p, 2000)['warnings'])
    P.save_project(p, tmp_path); q = P.load_project(tmp_path)
    assert q.effective_timing('1') == a and q.raw_timing('1') is None
    h = History(); h.execute(q, lambda c: c.timing_edits.__setitem__('0', P.WordTiming(100, 500)))
    assert q.effective_timing('1').start_ms == 500
    h.undo(q); assert q.effective_timing('1') == a
    h.execute(q, lambda c: c.timing_edits.__setitem__('1', P.WordTiming(350, 450)))
    assert not q.effective_timing('1').estimated
    assert q.effective_timing('2').start_ms == 450


def test_touching_neighbours_allow_a_labelled_overlap_without_retiming_known_words():
    p = phrase(); p.original_alignment['0'].end_ms = 1000
    assert p.effective_timing('1').estimated
    assert 100 < p.effective_timing('1').start_ms < p.effective_timing('2').end_ms == 1000
    assert p.effective_timing('0').end_ms == 1000 and not E.timing_conflicts(p)
    p.original_alignment['0'].end_ms = 1200
    assert E.timing_conflicts(p) == {('0', '3'): 200}


def test_phrase_edges_and_entire_anchored_phrase_can_estimate_but_stale_membership_cannot():
    p = phrase(); p.original_alignment.clear()
    assert not p.estimated_word_ids() and len(p.unresolved_words()) == 4
    p.alignment['phrases'] = {'line': {'word_ids': p.word_ids(), 'anchor': {'start_s': .2, 'end_s': 1.6}}}
    assert len(p.estimated_word_ids()) == 4
    assert p.effective_timing('0').start_ms == 200 and p.effective_timing('3').end_ms == 1600
    p.lines[0].words.append(P.Word('new', 'added'))
    assert not p.estimated_word_ids()


def test_estimation_can_be_disabled_and_cannot_exceed_the_recording():
    p = phrase(); p.alignment['estimate_missing_words'] = False
    assert p.effective_timing('1') is None and len(p.unresolved_words()) == 2
    p.alignment['estimate_missing_words'] = True
    p.assets = [P.Asset('a', 'original_audio', 'unused.wav', duration_ms=500)]
    assert p.effective_timing('2') is None


def test_passage_export_freezes_estimates_before_removing_neighbours():
    from heartbeam.export_jobs import _trim_snapshot
    p = phrase(); original = p.effective_timing('1')
    q = _trim_snapshot(p, original.start_ms, original.end_ms)
    t = q.effective_timing('1')
    assert t.estimated and t.start_ms == 0 and t.end_ms == original.end_ms - original.start_ms


def test_cropping_preserves_only_existing_source_approval():
    from heartbeam.export_jobs import _trim_snapshot
    from heartbeam.timing_review import approved, fingerprint
    p = phrase(); p.alignment['review'] = {'required': True}
    assert not approved(_trim_snapshot(p, 400, 600))
    p.alignment['review']['approved_fingerprint'] = fingerprint(p)
    clip = _trim_snapshot(p, 400, 600)
    assert approved(clip) and clip.alignment['review']['source_fingerprint'] == fingerprint(p)
    p.timing_edits['0'] = P.WordTiming(100, 350)
    assert not approved(_trim_snapshot(p, 400, 600))


def test_acoustic_alignment_can_replace_estimates_in_fill_only_mode():
    from heartbeam import lyrics as L, timings as T
    p = phrase()
    incoming = [T.Line(0, 'Sing the next word', .1, 1.5, [
        T.Word(w.text, .1 + i * .3, .3 + i * .3, .9)
        for i, w in enumerate(p.lines[0].words)])]
    stats = L.apply_alignment(p, incoming, only_unresolved=True)
    assert stats['filled'] == 2
    assert p.effective_timing('0').end_ms == 300
    assert p.effective_timing('1').start_ms == 400 and not p.effective_timing('1').estimated


def test_phrase_alignment_replaces_estimates_and_keeps_manual_anchors():
    from heartbeam.phrase_project import apply_result, review_lines
    from tests.test_phrase_project import result
    p = phrase(); p.timing_edits['1'] = P.WordTiming(reason='No match')
    p.timing_edits['0'] = P.WordTiming(100, 300)
    assert review_lines(p)
    proposal = result(p, index=0)
    apply_result(p, proposal, only_unresolved=True)
    assert p.raw_timing('1').start_ms == 6000 and not p.effective_timing('1').estimated
    assert p.effective_timing('0').end_ms == 300 and p.effective_timing('3').start_ms == 1000
