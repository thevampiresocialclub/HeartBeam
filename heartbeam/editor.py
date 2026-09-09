"""Python side of the timing editor component (P03).

Owns the bridge between the saved project and the browser timeline: what goes
out (words, waveform peaks, audio), and what comes back (committed timing
edits, selection).

**Why this shape.** The contract requires that high-frequency interaction --
playback, dragging, the playhead -- never trigger a Python rerun, and that only
committed changes cross the bridge. So the component receives a self-contained
snapshot and sends back one message per finished gesture. A drag that moves
through 200 mouse positions produces exactly one `timing_edit` trigger and
therefore one undo step.

**No build step.** `st.components.v2.component` accepts raw HTML/CSS/JS strings,
so the frontend is plain ES-module JavaScript in `editor_assets/`. There is no
React, no bundler and no Node dependency -- which is what makes the packaging
requirement ("ordinary users must not need Node.js") satisfiable at all. The
assets ship as package data.
"""
from __future__ import annotations

from pathlib import Path
import copy
import hashlib
from typing import Any

from .project import Project, WordTiming

ASSET_DIR = Path(__file__).parent / "editor_assets"

#: Below this score a word is drawn as low-confidence. Matches the aligner's
#: own threshold so the two views agree about which words look uncertain.
LOW_CONFIDENCE = 0.3

class EditorAssetError(RuntimeError):
    pass


def _read_asset(name: str) -> str:
    path = ASSET_DIR / name
    if not path.exists():
        raise EditorAssetError(
            f"editor asset missing: {path}. The package data may not have been "
            "installed; reinstall with scripts/install.ps1."
        )
    return path.read_text(encoding="utf-8")


def words_payload(project: Project) -> list[dict[str, Any]]:
    """Flatten the project's words into what the timeline needs to draw.

    Unresolved words are included with null times rather than dropped: they are
    exactly the words the user opened the editor to fix, so they must remain
    visible and selectable.
    """
    out: list[dict[str, Any]] = []
    for line, word in project.iter_words():
        if word.non_sung:
            continue
        timing = project.effective_timing(word.id)
        start = timing.start_ms if timing else None
        end = timing.end_ms if timing else None
        score = timing.score if timing and timing.score is not None else 1.0
        out.append({
            "id": word.id,
            "text": word.text,
            "line_id": line.id,
            "start_ms": start,
            "end_ms": end,
            "low_confidence": bool(score < LOW_CONFIDENCE),
            "estimated": bool(timing and timing.estimated),
            "edited": word.id in project.timing_edits,
            "reviewed": project.reviewed.get(word.id, False),
        })
    return out


def build_payload(project: Project, sources: list[dict], duration_ms: int,
                  selected_id: str | None = None) -> dict[str, Any]:
    return {
        "project_id": project.id,
        "frontend_version": hashlib.sha256((_read_asset("timeline.js") + _read_asset("audio_transport.js") + _read_asset("presentation.js") + _read_asset("timeline.css") + _read_asset("workstation.js")).encode()).hexdigest()[:12],
        "revision": project.revision,
        "words": words_payload(project),
        "sources": sources,
        "duration_ms": duration_ms,
        "selected_id": selected_id,
    }


def apply_timing_edit(project: Project, edit: dict[str, Any],
                      audio_duration_ms: int | None = None) -> tuple[bool, str]:
    """Commit one dragged boundary. Returns (ok, message).

    Validates before writing. The contract requires resolved words to satisfy
    0 <= start < end <= duration, and an invalid edit must be reported rather
    than silently clamped into a different song.
    """
    word_id = edit.get("word_id")
    if not word_id or project.find_word(word_id) is None:
        return False, f"unknown word id: {word_id!r}"
    try:
        if any(type(edit[k]) is not int for k in ("start_ms", "end_ms")):
            return False, "Timing must use whole milliseconds."
        start = int(edit["start_ms"])
        end = int(edit["end_ms"])
    except (KeyError, TypeError, ValueError):
        return False, "timing edit is missing usable start_ms/end_ms"

    if start < 0:
        return False, f"start ({start} ms) is before the beginning of the song"
    if end <= start:
        return False, f"end ({end} ms) must be after start ({start} ms)"
    if audio_duration_ms is not None and end > audio_duration_ms:
        return False, (f"end ({end} ms) is past the end of the audio "
                       f"({audio_duration_ms} ms)")

    existing = project.effective_timing(word_id)
    score = existing.score if existing else None
    candidate = copy.deepcopy(project)
    candidate.timing_edits[word_id] = WordTiming(
        start_ms=start, end_ms=end, score=score)
    error = new_conflict(project, candidate)
    if error:
        return False, error
    project.timing_edits[word_id] = candidate.timing_edits[word_id]
    project.reviewed[word_id] = True
    word = project.find_word(word_id)
    return True, f"{word.text}: {start} - {end} ms"


def nudge(project: Project, word_id: str, delta_ms: int, *,
          edge: str = "both", audio_duration_ms: int | None = None) -> tuple[bool, str]:
    """Shift a word's timing by an exact number of milliseconds.

    Exact, not approximate: a 10 ms nudge must change the persisted value by
    precisely 10 ms, which is an acceptance criterion and the reason this is
    integer arithmetic on stored values rather than anything routed through the
    pixel space of a drag.
    """
    timing = project.effective_timing(word_id)
    if timing is None or not timing.resolved:
        return False, "this word has no timing yet; set it before nudging"
    start, end = timing.start_ms, timing.end_ms
    if edge in ("both", "start"):
        start += delta_ms
    if edge in ("both", "end"):
        end += delta_ms
    return apply_timing_edit(
        project, {"word_id": word_id, "start_ms": start, "end_ms": end},
        audio_duration_ms=audio_duration_ms)


def set_manual_timing(project: Project, word_id: str, start_ms: int, end_ms: int,
                      audio_duration_ms: int | None = None) -> tuple[bool, str]:
    """Give an unresolved word a timing by hand."""
    return apply_timing_edit(
        project, {"word_id": word_id, "start_ms": start_ms, "end_ms": end_ms},
        audio_duration_ms=audio_duration_ms)


def next_unresolved(project: Project, after_word_id: str | None = None) -> str | None:
    """ID of the next word needing timing, wrapping around."""
    ids = [w.id for _, w in project.iter_words() if not w.non_sung]
    unresolved = {w.id for _, w, _ in project.unresolved_words()}
    if not unresolved:
        return None
    start = ids.index(after_word_id) + 1 if after_word_id in ids else 0
    for wid in ids[start:] + ids[:start]:
        if wid in unresolved:
            return wid
    return None


def next_low_confidence(project: Project, after_word_id: str | None = None,
                        threshold: float = LOW_CONFIDENCE) -> str | None:
    """ID of the next word the model was unsure about.

    Model confidence and user review are different things: correcting a word
    does not raise the model's score, so a reviewed word is skipped by virtue of
    having a manual edit, not by having its score rewritten.
    """
    ids = [w.id for _, w in project.iter_words() if not w.non_sung]
    candidates = set()
    for _, word in project.iter_words():
        timing = project.effective_timing(word.id)
        manual = word.id in project.timing_edits and timing and timing.resolved and not timing.estimated
        if word.non_sung or project.reviewed.get(word.id, manual):
            continue  # already reviewed by hand
        if timing and timing.score is not None and timing.score < threshold:
            candidates.add(word.id)
    if not candidates:
        return None
    start = ids.index(after_word_id) + 1 if after_word_id in ids else 0
    for wid in ids[start:] + ids[:start]:
        if wid in candidates:
            return wid
    return None


def timeline_component():
    """Register the component. Import streamlit lazily so this module stays
    usable (and testable) without a Streamlit runtime."""
    import streamlit as st

    return st.components.v2.component(
        "heartbeam_timeline",
        css=_read_asset("timeline.css"),
        js=_read_asset("vendor/subtitles-octopus.js") + "\n" +
           _read_asset("audio_transport.js") + "\n" + _read_asset("presentation.js") + "\n" + _read_asset("workstation.js") + "\n" + _read_asset("timeline.js"),
    )


def inspector_component():
    """Right-pane host for live lyric/vocal controls, with no second player."""
    import streamlit as st
    return st.components.v2.component(
        "heartbeam_inspector", css=_read_asset("timeline.css"),
        js=_read_asset("workstation.js") + "\nexport default hbMountInspector;",
    )


def timing_conflicts(project: Project) -> dict[tuple[str, str], int]:
    """Report ordering/overlap conflicts without rewriting imported proposals."""
    timed = [(w, project.effective_timing(w.id)) for _, w in project.iter_words()
             if not w.non_sung]
    # Estimates can borrow an onset interval already occupied by a known word.
    # Continue checking all known words against each other across those estimates.
    timed = [(w, t) for w, t in timed if t and t.resolved and not t.estimated]
    return {(a.id, b.id): ta.end_ms - tb.start_ms
            for (a, ta), (b, tb) in zip(timed, timed[1:]) if ta.end_ms > tb.start_ms}


def new_conflict(before, after):
    previous = timing_conflicts(before)
    for pair, overlap in timing_conflicts(after).items():
        if overlap > previous.get(pair, 0):
            words = [after.find_word(w).text for w in pair]
            return f"This would overlap or reverse ‘{words[0]}’ and ‘{words[1]}’ by {overlap} ms."
    return None


def shift_timing(project: Project, word_id: str, delta_ms: int, scope: str,
                 duration_ms: int):
    if type(delta_ms) is not int or scope not in ("word", "line", "song"):
        return False, "Choose a timing scope and a whole millisecond offset."
    selected_line = next((ln for ln, w in project.iter_words() if w.id == word_id), None)
    if scope != "song" and selected_line is None:
        return False, "Select a word first."
    candidate = copy.deepcopy(project)
    changed = 0
    for line, word in candidate.iter_words():
        if word.non_sung or (scope == "word" and word.id != word_id) or (
                scope == "line" and line.id != selected_line.id):
            continue
        t = candidate.effective_timing(word.id)
        if t is None or not t.resolved:
            continue
        if t.start_ms + delta_ms < 0 or t.end_ms + delta_ms > duration_ms:
            return False, "The shifted timing would go outside the song."
        candidate.timing_edits[word.id] = WordTiming(t.start_ms + delta_ms,
                                                    t.end_ms + delta_ms, t.score)
        candidate.reviewed[word.id] = True
        changed += 1
    error = new_conflict(project, candidate)
    if error:
        return False, error
    if not changed:
        return False, "There are no resolved words in this selection."
    project.timing_edits = candidate.timing_edits
    project.reviewed = candidate.reviewed
    return True, f"Shifted {changed} word(s) by {delta_ms} ms."
