import copy

import pytest

from heartbeam import editor as E, project as P
from heartbeam.alignment_match import word_review
from heartbeam.project_preview import timing_warnings, current_timings


def song(start=923, end=1500):
    p = P.Project('overlap', 'Boundary overlap')
    p.lines = [P.Line('line', [P.Word('a', 'accent'), P.Word('b', 'She')])]
    p.original_alignment = {'a': P.WordTiming(500, 1000, .9),
                            'b': P.WordTiming(start, end, .9)}
    return p


@pytest.mark.parametrize('overlap, warned', [(1, False), (77, False), (100, False), (101, True), (300, True)])
def test_overlap_warning_threshold_is_consistent_and_does_not_retime(overlap, warned):
    p = song(1000-overlap)
    before = copy.deepcopy(p.to_dict())
    assert E.timing_conflicts(p) == {('a', 'b'): overlap}
    assert bool(E.review_conflicts(p)) is warned
    assert bool(timing_warnings(p, 2000)) is warned
    words = [dict(start_s=t.start_ms/1000, end_s=t.end_ms/1000, score=.9)
             for t in p.original_alignment.values()]
    assert ('Overlapping words' in word_review(words)) is warned
    assert p.to_dict() == before


def test_backwards_order_is_warned_even_when_overlap_is_only_77_ms():
    p = song(923)
    p.original_alignment['a'] = P.WordTiming(950, 1000, .9)
    assert E.review_conflicts(p) == {('a', 'b'): 77}
    assert 'Overlapping words' in word_review([
        dict(start_s=.95, end_s=1., score=.9), dict(start_s=.923, end_s=1.5, score=.9)])


def test_review_tolerance_does_not_relax_edit_validation_or_strict_export():
    p = song(1000)
    q = song(999)
    assert E.new_conflict(p, q)
    assert not E.review_conflicts(q)
    with pytest.raises(P.ProjectError, match='conflict'):
        current_timings(q, 2000)
    assert current_timings(q, 2000, allow_timing_issues=True).lines
