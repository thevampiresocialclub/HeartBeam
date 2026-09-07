"""P02 tests: lyric editing that preserves identity and timing.

Each test maps to an acceptance criterion in 02-LYRICS-EDITOR.md. The criteria
are all variations on one demand: edits must not silently destroy timing work,
and identical text in different places must stay distinct.
"""
from __future__ import annotations

import pytest

from heartbeam import lyrics as L
from heartbeam import project as P

CHORUS = "we are so far from you"


def _project(text: str, tmp_path) -> P.Project:
    proj = P.create_project(tmp_path, "test")
    L.apply_lyrics_edit(proj, text)
    return proj


def _time_everything(proj: P.Project, step: int = 500) -> None:
    """Give every word a distinct, resolved original alignment."""
    t = 0
    for _, w in proj.iter_words():
        proj.original_alignment[w.id] = P.WordTiming(
            start_ms=t, end_ms=t + step - 50, score=0.9)
        t += step
    proj.timing_edits.clear()


def _timing_by_text(proj: P.Project) -> dict[str, tuple[int | None, int | None]]:
    out = {}
    for _, w in proj.iter_words():
        t = proj.effective_timing(w.id)
        out[w.text] = (t.start_ms, t.end_ms) if t else (None, None)
    return out


# ---------------------------------------------------------------------------
# parsing and counts
# ---------------------------------------------------------------------------


def test_paste_preserves_phrase_breaks(tmp_path):
    proj = _project("alpha bravo\ncharlie delta\n\necho foxtrot\n", tmp_path)
    assert [ln.text for ln in proj.lines] == [
        "alpha bravo", "charlie delta", "echo foxtrot"]


def test_counts_report_sung_lines_and_words():
    assert L.count_lyrics("alpha bravo\ncharlie\n") == (2, 3)
    assert L.count_lyrics("# Chorus\nalpha bravo\n") == (1, 2)
    assert L.count_lyrics("") == (0, 0)


def test_brackets_are_lyrics_not_headings(tmp_path):
    """Bracketed text is often real lyrics; guessing would eat them."""
    proj = _project("[you know it]\nalpha bravo\n", tmp_path)
    assert [ln.text for ln in proj.lines] == ["[you know it]", "alpha bravo"]
    assert proj.sections == []


def test_section_labels_are_explicit(tmp_path):
    proj = _project("# Verse 1\nalpha bravo\n# Chorus\n" + CHORUS + "\n", tmp_path)
    assert [s.name for s in proj.sections] == ["Verse 1", "Chorus"]
    assert [ln.text for ln in proj.lines] == ["alpha bravo", CHORUS]
    verse, chorus = proj.sections
    assert len(verse.line_ids) == 1 and len(chorus.line_ids) == 1
    assert proj.lines[0].section_id == verse.id
    assert proj.lines[1].section_id == chorus.id


def test_export_round_trips_without_exposing_ids(tmp_path):
    src = "# Verse 1\nalpha bravo\n\n# Chorus\n" + CHORUS + "\n"
    proj = _project(src, tmp_path)
    text = L.to_text(proj)
    assert "line_" not in text and "w_" not in text
    again = _project(text, tmp_path / "second")
    assert [ln.text for ln in again.lines] == [ln.text for ln in proj.lines]
    assert [s.name for s in again.sections] == [s.name for s in proj.sections]


# ---------------------------------------------------------------------------
# identity preservation
# ---------------------------------------------------------------------------


def test_reediting_identical_text_changes_nothing(tmp_path):
    proj = _project("alpha bravo\ncharlie delta\n", tmp_path)
    _time_everything(proj)
    before_ids = proj.word_ids()
    before_timing = _timing_by_text(proj)

    result = L.apply_lyrics_edit(proj, "alpha bravo\ncharlie delta\n")
    assert not result.changed
    assert proj.word_ids() == before_ids
    assert _timing_by_text(proj) == before_timing


def test_inserting_a_word_keeps_neighbours_timed(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    _time_everything(proj)
    alpha_id, bravo_id = proj.word_ids()

    result = L.apply_lyrics_edit(proj, "alpha inserted bravo\n")
    assert len(result.new_word_ids) == 1
    ids = proj.word_ids()
    assert ids[0] == alpha_id and ids[2] == bravo_id

    assert proj.effective_timing(alpha_id).start_ms == 0
    assert proj.effective_timing(bravo_id).start_ms == 500
    new_word = proj.find_word(ids[1])
    assert new_word.text == "inserted"
    timing = proj.effective_timing(new_word.id)
    assert not timing.resolved
    assert "needs timing" in timing.reason


def test_punctuation_fix_preserves_sung_timing(tmp_path):
    proj = _project("dont stop me\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()

    result = L.apply_lyrics_edit(proj, "Don't stop me!\n")
    assert result.new_word_ids == set(), "punctuation is not a new word"
    assert proj.word_ids() == ids
    assert proj.effective_timing(ids[0]).start_ms == 0
    assert proj.lines[0].words[0].text == "Don't", "authored spelling is kept"


def test_smart_apostrophe_matches_straight_one(tmp_path):
    proj = _project("don't stop\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    result = L.apply_lyrics_edit(proj, "don" + chr(0x2019) + "t stop\n")
    assert result.new_word_ids == set()
    assert proj.word_ids() == ids


def test_splitting_a_line_keeps_every_word_timed(tmp_path):
    proj = _project("alpha bravo charlie delta\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    before = _timing_by_text(proj)

    result = L.apply_lyrics_edit(proj, "alpha bravo\ncharlie delta\n")
    assert result.new_word_ids == set(), "splitting invents no words"
    assert proj.word_ids() == ids
    assert len(proj.lines) == 2
    assert _timing_by_text(proj) == before


def test_merging_lines_keeps_every_word_timed(tmp_path):
    proj = _project("alpha bravo\ncharlie delta\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    before = _timing_by_text(proj)

    result = L.apply_lyrics_edit(proj, "alpha bravo charlie delta\n")
    assert result.new_word_ids == set()
    assert proj.word_ids() == ids
    assert len(proj.lines) == 1
    assert _timing_by_text(proj) == before


def test_deleting_a_middle_word_leaves_the_rest_intact(tmp_path):
    proj = _project("alpha bravo charlie\n", tmp_path)
    _time_everything(proj)
    alpha_id, bravo_id, charlie_id = proj.word_ids()

    result = L.apply_lyrics_edit(proj, "alpha charlie\n")
    assert result.removed_word_ids == {bravo_id}
    assert proj.word_ids() == [alpha_id, charlie_id]
    assert proj.effective_timing(charlie_id).start_ms == 1000
    assert bravo_id not in proj.original_alignment, "removed word takes its timing"


# ---------------------------------------------------------------------------
# repeated choruses -- the case text matching gets wrong
# ---------------------------------------------------------------------------


def test_editing_the_second_chorus_leaves_the_first_alone(tmp_path):
    text = f"{CHORUS}\nverse one here\n{CHORUS}\n"
    proj = _project(text, tmp_path)
    _time_everything(proj)
    first_ids = [w.id for w in proj.lines[0].words]
    second_ids = [w.id for w in proj.lines[2].words]
    assert first_ids != second_ids, "identical text must have distinct IDs"
    first_timing = [proj.effective_timing(i).start_ms for i in first_ids]

    edited = f"{CHORUS}\nverse one here\nwe are so very far from you\n"
    result = L.apply_lyrics_edit(proj, edited)

    assert [w.id for w in proj.lines[0].words] == first_ids
    assert [proj.effective_timing(i).start_ms for i in first_ids] == first_timing
    assert len(result.new_word_ids) == 1
    changed = proj.lines[2]
    assert changed.words[3].text == "very"
    assert not proj.effective_timing(changed.words[3].id).resolved


def test_repeated_word_within_a_line_keeps_distinct_identities(tmp_path):
    proj = _project("no no no stop\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    assert len(set(ids)) == 4

    result = L.apply_lyrics_edit(proj, "no no no go\n")
    assert len(result.new_word_ids) == 1
    assert proj.word_ids()[:3] == ids[:3]
    assert proj.effective_timing(ids[1]).start_ms == 500


# ---------------------------------------------------------------------------
# undo
# ---------------------------------------------------------------------------


def test_undo_restores_ids_and_timing(tmp_path):
    proj = _project("alpha bravo charlie\n", tmp_path)
    _time_everything(proj)
    before_ids = proj.word_ids()
    before_timing = _timing_by_text(proj)

    stack = L.UndoStack()
    stack.commit(proj)
    L.apply_lyrics_edit(proj, "alpha charlie\n")
    assert proj.word_ids() != before_ids

    assert stack.undo(proj)
    assert proj.word_ids() == before_ids
    assert _timing_by_text(proj) == before_timing


def test_redo_reapplies_the_edit(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    _time_everything(proj)
    stack = L.UndoStack()
    stack.commit(proj)
    L.apply_lyrics_edit(proj, "alpha\n")
    edited_ids = proj.word_ids()

    stack.undo(proj)
    assert len(proj.word_ids()) == 2
    assert stack.redo(proj)
    assert proj.word_ids() == edited_ids


def test_undo_on_an_empty_stack_is_a_no_op(tmp_path):
    proj = _project("alpha\n", tmp_path)
    stack = L.UndoStack()
    assert not stack.can_undo
    assert stack.undo(proj) is False


# ---------------------------------------------------------------------------
# persistence
# ---------------------------------------------------------------------------


def test_edits_survive_save_and_reopen(tmp_path):
    proj = _project("# Verse\nalpha bravo\ncharlie delta\n", tmp_path)
    _time_everything(proj)
    L.apply_lyrics_edit(proj, "# Verse\nalpha bravo\ncharlie echo\n")
    P.save_project(proj, tmp_path)

    reloaded = P.load_project(tmp_path)
    assert reloaded.word_ids() == proj.word_ids()
    assert [s.name for s in reloaded.sections] == ["Verse"]
    assert L.to_text(reloaded) == L.to_text(proj)

    unresolved = {w.text for _, w, _ in reloaded.unresolved_words()}
    assert unresolved == {"echo"}, "review flags must survive a reopen"


def test_new_words_are_listed_for_review_with_a_reason(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    _time_everything(proj)
    L.apply_lyrics_edit(proj, "alpha bravo charlie\n")
    reasons = {w.text: r for _, w, r in proj.unresolved_words()}
    assert set(reasons) == {"charlie"}
    assert "needs timing" in reasons["charlie"]


@pytest.mark.parametrize("text", ["", "   ", "\n\n\n"])
def test_empty_lyrics_produce_no_lines(text, tmp_path):
    proj = _project(text, tmp_path)
    assert proj.lines == []
    assert L.count_lyrics(text) == (0, 0)


# ---------------------------------------------------------------------------
# P02.3: applying alignment without destroying manual work
# ---------------------------------------------------------------------------

from heartbeam.timings import Line as TLine  # noqa: E402
from heartbeam.timings import Word as TWord  # noqa: E402


def _aligned(pairs):
    """pairs: [(text, start_s, end_s)] -> one timings.Line"""
    words = [TWord(text=t, start_s=s, end_s=e, score=0.9) for t, s, e in pairs]
    return [TLine(index=0, text=" ".join(p[0] for p in pairs),
                  start_s=pairs[0][1], end_s=pairs[-1][2], words=words)]


def test_alignment_fills_unresolved_words(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    stats = L.apply_alignment(proj, _aligned([("alpha", 0.0, 0.5),
                                              ("bravo", 0.6, 1.0)]))
    assert stats["filled"] == 2
    ids = proj.word_ids()
    assert proj.effective_timing(ids[0]).start_ms == 0
    assert proj.effective_timing(ids[1]).end_ms == 1000
    assert proj.unresolved_words() == []


def test_realignment_protects_manual_corrections(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    proj.timing_edits[ids[0]] = P.WordTiming(start_ms=1234, end_ms=1500)

    stats = L.apply_alignment(proj, _aligned([("alpha", 9.0, 9.5),
                                              ("bravo", 9.6, 10.0)]))
    assert stats["skipped_manual"] == 2, "both already had timing"
    assert proj.effective_timing(ids[0]).start_ms == 1234, "manual edit survives"


def test_explicit_realignment_replaces_proposals_but_not_manual_edits(tmp_path):
    proj = _project("alpha bravo\n", tmp_path)
    _time_everything(proj)
    ids = proj.word_ids()
    proj.timing_edits[ids[0]] = P.WordTiming(start_ms=1234, end_ms=1500)

    L.apply_alignment(proj, _aligned([("alpha", 9.0, 9.5), ("bravo", 9.6, 10.0)]),
                      only_unresolved=False)
    assert proj.effective_timing(ids[0]).start_ms == 1234, "manual edit still wins"
    assert proj.original_alignment[ids[1]].start_ms == 500, "original proposal retained"
    assert proj.alignment_proposals[ids[1]].start_ms == 9600, "new proposal retained separately"
    assert proj.effective_timing(ids[1]).start_ms == 9600


def test_partial_alignment_leaves_missing_words_unresolved(tmp_path):
    proj = _project("alpha bravo charlie\n", tmp_path)
    stats = L.apply_alignment(proj, _aligned([("alpha", 0.0, 0.5),
                                              ("charlie", 1.0, 1.5)]))
    assert stats["filled"] == 2 and stats["unmatched"] == 1
    unresolved = {w.text: r for _, w, r in proj.unresolved_words()}
    assert set(unresolved) == {"bravo"}
    assert "did not return this word" in unresolved["bravo"]
    # And the words that did align kept their own identities.
    ids = proj.word_ids()
    assert proj.effective_timing(ids[2]).start_ms == 1000


def test_alignment_after_an_edit_fills_only_the_new_word(tmp_path):
    """The realistic loop: align, edit a word, realign."""
    proj = _project("alpha bravo\n", tmp_path)
    L.apply_alignment(proj, _aligned([("alpha", 0.0, 0.5), ("bravo", 0.6, 1.0)]))
    L.apply_lyrics_edit(proj, "alpha bravo charlie\n")
    assert len(proj.unresolved_words()) == 1

    stats = L.apply_alignment(proj, _aligned([("alpha", 0.0, 0.5),
                                              ("bravo", 0.6, 1.0),
                                              ("charlie", 1.1, 1.6)]))
    assert stats["filled"] == 1, "only the new word needed timing"
    assert stats["skipped_manual"] == 2
    assert proj.unresolved_words() == []
