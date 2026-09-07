"""P02.3 tests: every source word survives a partial alignment.

The review reproduced this failure directly: for source lines `alpha bravo` and
`charlie delta`, an aligned result that omits `bravo` put `charlie` on the FIRST
line. The old fallback truncated the line-index list to a prefix, so one dropped
word shifted every later word onto its neighbour's line.

These tests exercise the pure regrouping logic. No model is loaded -- the aligner
output is synthesised, which is the only way to reproduce a dropped word
deterministically.
"""
from __future__ import annotations

import pytest

from heartbeam.align import _group_words_into_lines, _remap_line_indices


def _aligned(word: str, start: float, end: float, score: float = 0.9) -> dict:
    return {"word": word, "start": start, "end": end, "score": score}


def test_dropped_middle_word_keeps_later_words_on_their_own_line():
    """The exact case from the review."""
    user_lines = [(0, "alpha bravo"), (1, "charlie delta")]
    seg_line_indices = [[0, 0, 1, 1]]
    expected_tokens = ["alpha", "bravo", "charlie", "delta"]
    # The aligner dropped "bravo".
    aligned = [
        _aligned("alpha", 0.0, 0.5),
        _aligned("charlie", 1.0, 1.5),
        _aligned("delta", 1.6, 2.0),
    ]

    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected_tokens)

    by_index = {ln.index: [w.text for w in ln.words] for ln in lines}
    assert by_index[0] == ["alpha"], "line 0 keeps only its own surviving word"
    assert by_index[1] == ["charlie", "delta"], (
        "charlie must stay on line 1; the old code moved it to line 0"
    )


def test_dropped_first_word_does_not_shift_the_rest():
    user_lines = [(0, "alpha bravo"), (1, "charlie delta")]
    seg_line_indices = [[0, 0, 1, 1]]
    expected = ["alpha", "bravo", "charlie", "delta"]
    aligned = [
        _aligned("bravo", 0.5, 0.9),
        _aligned("charlie", 1.0, 1.5),
        _aligned("delta", 1.6, 2.0),
    ]
    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected)
    by_index = {ln.index: [w.text for w in ln.words] for ln in lines}
    assert by_index[0] == ["bravo"]
    assert by_index[1] == ["charlie", "delta"]


def test_multiple_dropped_words_across_lines():
    user_lines = [(0, "one two three"), (1, "four five six")]
    seg_line_indices = [[0, 0, 0, 1, 1, 1]]
    expected = ["one", "two", "three", "four", "five", "six"]
    aligned = [
        _aligned("one", 0.0, 0.3),
        _aligned("three", 0.7, 1.0),
        _aligned("five", 1.4, 1.7),
    ]
    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected)
    by_index = {ln.index: [w.text for w in ln.words] for ln in lines}
    assert by_index[0] == ["one", "three"]
    assert by_index[1] == ["five"]


def test_nothing_dropped_is_unaffected():
    user_lines = [(0, "alpha bravo"), (1, "charlie delta")]
    seg_line_indices = [[0, 0, 1, 1]]
    expected = ["alpha", "bravo", "charlie", "delta"]
    aligned = [
        _aligned("alpha", 0.0, 0.4), _aligned("bravo", 0.5, 0.9),
        _aligned("charlie", 1.0, 1.5), _aligned("delta", 1.6, 2.0),
    ]
    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected)
    by_index = {ln.index: [w.text for w in ln.words] for ln in lines}
    assert by_index[0] == ["alpha", "bravo"]
    assert by_index[1] == ["charlie", "delta"]


def test_repeated_words_map_to_their_own_occurrence():
    """A repeated chorus must not collapse onto its first occurrence."""
    user_lines = [(0, "no no no"), (1, "no no no")]
    seg_line_indices = [[0, 0, 0, 1, 1, 1]]
    expected = ["no"] * 6
    # The aligner dropped the fourth "no" -- the first of the second line.
    aligned = [_aligned("no", i * 0.5, i * 0.5 + 0.3) for i in range(5)]
    mapped = _remap_line_indices(aligned, [0, 0, 0, 1, 1, 1], expected)
    assert len(mapped) == 5
    assert mapped.count(0) == 3, "line 0 keeps three words"
    assert mapped.count(1) == 2, "line 1 keeps the two that survived"


def test_punctuation_and_case_differences_still_match():
    user_lines = [(0, "Don't stop"), (1, "me now")]
    seg_line_indices = [[0, 0, 1, 1]]
    expected = ["Don't", "stop", "me", "now"]
    aligned = [
        _aligned("dont", 0.0, 0.4), _aligned("STOP,", 0.5, 0.9),
        _aligned("me", 1.0, 1.2), _aligned("now!", 1.3, 1.6),
    ]
    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected)
    by_index = {ln.index: [w.text for w in ln.words] for ln in lines}
    assert by_index[0] == ["dont", "STOP,"]
    assert by_index[1] == ["me", "now!"]


def test_unmatchable_word_is_dropped_not_misfiled():
    """A hallucinated word with no source counterpart must not claim a line."""
    user_lines = [(0, "alpha bravo")]
    seg_line_indices = [[0, 0]]
    expected = ["alpha", "bravo"]
    aligned = [
        _aligned("alpha", 0.0, 0.4),
        _aligned("zzzz", 0.45, 0.5),
        _aligned("bravo", 0.5, 0.9),
    ]
    lines, _ = _group_words_into_lines(
        aligned, seg_line_indices, user_lines, expected_tokens=expected)
    assert [w.text for w in lines[0].words] == ["alpha", "bravo"]


def test_without_expected_tokens_it_degrades_rather_than_inventing():
    """No source tokens available: fall back, but never fabricate a mapping."""
    mapped = _remap_line_indices(
        [_aligned("a", 0, 1), _aligned("b", 1, 2), _aligned("c", 2, 3)],
        [0, 0], None,
    )
    assert mapped[:2] == [0, 0]
    assert mapped[2] is None, "an extra aligned word gets no line, not a guess"


@pytest.mark.parametrize("threshold,expected_low", [(0.3, 1), (0.95, 2)])
def test_low_confidence_counting_is_unchanged(threshold, expected_low):
    user_lines = [(0, "alpha bravo")]
    aligned = [_aligned("alpha", 0.0, 0.4, score=0.2),
               _aligned("bravo", 0.5, 0.9, score=0.9)]
    _, low = _group_words_into_lines(
        aligned, [[0, 0]], user_lines, score_threshold=threshold,
        expected_tokens=["alpha", "bravo"])
    assert low == expected_low
