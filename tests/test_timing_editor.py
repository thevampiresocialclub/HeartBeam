"""P03 tests: the timing editor's Python side.

The browser half is verified by driving a real browser (results recorded in
BUILD-STATUS). These cover the logic that decides what a committed gesture
means, which is where correctness actually lives.
"""
from __future__ import annotations

import numpy as np
import pytest

from heartbeam import editor as ed
from heartbeam import lyrics as L
from heartbeam import project as P
from heartbeam import waveform as wf

DURATION_MS = 10_000


def _project(tmp_path, text="alpha bravo charlie\n"):
    proj = P.create_project(tmp_path, "timing")
    L.apply_lyrics_edit(proj, text)
    t = 0
    for _, w in proj.iter_words():
        proj.original_alignment[w.id] = P.WordTiming(
            start_ms=t, end_ms=t + 400, score=0.9)
        t += 500
    proj.timing_edits.clear()
    return proj


# ---------------------------------------------------------------------------
# waveform peaks
# ---------------------------------------------------------------------------


def test_peaks_capture_both_extremes():
    """Min AND max: an RMS-only waveform hides where a word actually starts."""
    sr = 1000
    samples = np.concatenate([np.zeros(500, np.float32),
                              np.ones(500, np.float32) * 0.8]).astype(np.float32)
    peaks = wf.compute_peaks(samples, sr, buckets=2)
    assert peaks.buckets == 2
    assert peaks.maxs[0] == 0
    assert peaks.maxs[1] == pytest.approx(102, abs=2)
    assert peaks.duration_ms == 1000


def test_peaks_handle_stereo_and_empty():
    stereo = np.zeros((100, 2), np.float32)
    stereo[:, 0] = 0.5
    peaks = wf.compute_peaks(stereo, 100, buckets=4)
    assert len(peaks.mins) == len(peaks.maxs) == 4
    empty = wf.compute_peaks(np.zeros(0, np.float32), 44100, buckets=10)
    assert empty.mins == []
    assert empty.duration_ms == 0


def test_peaks_cache_avoids_recomputing(tmp_path):
    calls = {"n": 0}

    def provider():
        calls["n"] += 1
        return np.ones(1000, np.float32) * 0.5

    a = wf.load_or_compute(tmp_path, "src-hash", provider, 1000, buckets=10)
    b = wf.load_or_compute(tmp_path, "src-hash", provider, 1000, buckets=10)
    assert calls["n"] == 1, "a cache hit must not touch the audio"
    assert a.maxs == b.maxs

    wf.load_or_compute(tmp_path, "DIFFERENT", provider, 1000, buckets=10)
    assert calls["n"] == 2, "a changed source must recompute"


# ---------------------------------------------------------------------------
# committed edits
# ---------------------------------------------------------------------------


def test_nudge_changes_the_persisted_value_by_exactly_that_many_ms(tmp_path):
    """Acceptance: a 10 ms nudge moves the stored value by exactly 10 ms."""
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    before = proj.effective_timing(wid)
    ok, _ = ed.nudge(proj, wid, 10, audio_duration_ms=DURATION_MS)
    assert ok
    after = proj.effective_timing(wid)
    assert after.start_ms == before.start_ms + 10
    assert after.end_ms == before.end_ms + 10


@pytest.mark.parametrize("delta", [-25, -10, -1, 1, 10, 250])
def test_nudge_is_exact_in_both_directions(tmp_path, delta):
    proj = _project(tmp_path)
    wid = proj.word_ids()[1]
    before = proj.effective_timing(wid)
    ed.nudge(proj, wid, delta, audio_duration_ms=DURATION_MS)
    after = proj.effective_timing(wid)
    assert after.start_ms - before.start_ms == delta
    assert after.end_ms - before.end_ms == delta


def test_nudge_one_edge_only(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    before = proj.effective_timing(wid)
    ed.nudge(proj, wid, 30, edge="end", audio_duration_ms=DURATION_MS)
    after = proj.effective_timing(wid)
    assert after.start_ms == before.start_ms
    assert after.end_ms == before.end_ms + 30


def test_nudging_an_untimed_word_is_refused(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    proj.original_alignment.pop(wid)
    proj.timing_edits[wid] = P.WordTiming(reason="needs timing")
    ok, message = ed.nudge(proj, wid, 10)
    assert not ok
    assert "no timing yet" in message


def test_edits_go_to_the_edit_layer_leaving_the_proposal_intact(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    original = proj.original_alignment[wid].start_ms
    ed.apply_timing_edit(proj, {"word_id": wid, "start_ms": 111, "end_ms": 222},
                         DURATION_MS)
    assert proj.original_alignment[wid].start_ms == original
    assert proj.timing_edits[wid].start_ms == 111
    assert proj.effective_timing(wid).start_ms == 111


# ---------------------------------------------------------------------------
# validation -- an invalid edit is refused, never clamped
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("start,end,needle", [
    (-5, 100, "before the beginning"),
    (500, 500, "must be after"),
    (600, 500, "must be after"),
    (0, DURATION_MS + 1, "past the end"),
])
def test_invalid_timing_is_rejected_with_a_reason(tmp_path, start, end, needle):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    before = proj.effective_timing(wid).start_ms
    ok, message = ed.apply_timing_edit(
        proj, {"word_id": wid, "start_ms": start, "end_ms": end}, DURATION_MS)
    assert not ok
    assert needle in message
    assert proj.effective_timing(wid).start_ms == before, "must not be clamped"


def test_edit_for_an_unknown_word_is_rejected(tmp_path):
    proj = _project(tmp_path)
    ok, message = ed.apply_timing_edit(
        proj, {"word_id": "w_nope", "start_ms": 0, "end_ms": 10}, DURATION_MS)
    assert not ok
    assert "unknown word" in message


def test_malformed_edit_is_rejected(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    ok, message = ed.apply_timing_edit(proj, {"word_id": wid}, DURATION_MS)
    assert not ok
    assert "missing usable" in message


def test_manual_timing_resolves_an_untimed_word(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    proj.original_alignment.pop(wid)
    proj.timing_edits[wid] = P.WordTiming(reason="needs timing")
    assert len(proj.unresolved_words()) == 1

    ok, _ = ed.set_manual_timing(proj, wid, 1000, 1400, DURATION_MS)
    assert ok
    assert proj.unresolved_words() == []
    assert proj.effective_timing(wid).resolved


# ---------------------------------------------------------------------------
# review navigation
# ---------------------------------------------------------------------------


def test_next_unresolved_cycles_through_untimed_words(tmp_path):
    proj = _project(tmp_path, "alpha bravo charlie delta\n")
    ids = proj.word_ids()
    for wid in (ids[1], ids[3]):
        proj.original_alignment.pop(wid)
        proj.timing_edits[wid] = P.WordTiming(reason="needs timing")

    first = ed.next_unresolved(proj)
    assert first == ids[1]
    assert ed.next_unresolved(proj, first) == ids[3]
    assert ed.next_unresolved(proj, ids[3]) == ids[1], "wraps around"


def test_next_unresolved_returns_none_when_all_timed(tmp_path):
    proj = _project(tmp_path)
    assert ed.next_unresolved(proj) is None


def test_next_low_confidence_skips_words_already_reviewed(tmp_path):
    """A manual correction does not raise the model's score, but it does mean
    the word has been reviewed and should not be offered again."""
    proj = _project(tmp_path, "alpha bravo charlie\n")
    ids = proj.word_ids()
    for wid in ids:
        proj.original_alignment[wid] = P.WordTiming(
            start_ms=0, end_ms=100, score=0.1)

    assert ed.next_low_confidence(proj) == ids[0]
    ed.nudge(proj, ids[0], 5, audio_duration_ms=DURATION_MS)   # reviewed by hand
    assert ed.next_low_confidence(proj) == ids[1]
    assert proj.original_alignment[ids[0]].score == 0.1, "score is not rewritten"


# ---------------------------------------------------------------------------
# component payload
# ---------------------------------------------------------------------------


def test_payload_includes_untimed_words_so_they_stay_findable(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[1]
    proj.original_alignment.pop(wid)
    proj.timing_edits[wid] = P.WordTiming(reason="needs timing")

    payload = ed.words_payload(proj)
    assert len(payload) == 3
    entry = next(w for w in payload if w["id"] == wid)
    assert entry["start_ms"] is None
    assert entry["end_ms"] is None


def test_payload_flags_low_confidence(tmp_path):
    proj = _project(tmp_path)
    wid = proj.word_ids()[0]
    proj.original_alignment[wid] = P.WordTiming(
        start_ms=0, end_ms=100, score=0.05)
    payload = {w["id"]: w for w in ed.words_payload(proj)}
    assert payload[wid]["low_confidence"] is True
    assert payload[proj.word_ids()[1]]["low_confidence"] is False


def test_non_sung_words_are_not_sent_to_the_timeline(tmp_path):
    proj = _project(tmp_path)
    proj.lines[0].words[0].non_sung = True
    assert len(ed.words_payload(proj)) == 2


def test_editor_assets_are_present_and_need_no_build_step():
    """The frontend ships as package data; there is no bundler involved."""
    js = ed._read_asset("timeline.js")
    css = ed._read_asset("timeline.css")
    assert "export default function" in js, "must be an ES module entry point"
    assert "setTriggerValue" in js, "must talk back to Python"
    assert ".hb-editor" in css


def test_the_display_does_not_depend_on_requestAnimationFrame_alone():
    """Regression: rAF does not fire in a background tab or a non-compositing
    embed, and audio keeps playing regardless. Verified in a real browser where
    rAF never fired: the clock still tracked the audio to within 33 ms."""
    js = ed._read_asset("timeline.js")
    assert "setInterval" in js, "an interval fallback must drive the display"
    assert "requestAnimationFrame" in js, "rAF is still the smooth path"


def test_a_no_op_drag_is_not_treated_as_an_edit():
    """Regression: clicking a word's edge without moving it used to commit an
    unchanged timing, dirtying the project and consuming an undo step."""
    js = ed._read_asset("timeline.js")
    assert "drag.origStart" in js and "drag.origEnd" in js, (
        "commitDrag must compare against the drag origin before sending"
    )
