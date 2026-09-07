"""Lyric document editing that preserves identity and timing.

Implements P02.1-P02.2. The problem this solves: a user pastes a song, aligns
it, spends twenty minutes correcting word timing, then fixes a typo -- and must
not lose the other nineteen minutes of work.

**Why not match on text.** Repeated choruses are normal, and so are repeated
words within a line. Any scheme keyed on word text, or on a global text search,
will happily retime the wrong chorus. Reconciliation is therefore *sequence*
aware: it diffs positions, so the second occurrence of a chorus matches the
second occurrence, not the first.

**How an edit is reconciled.**

1. Diff the sung lines old-vs-new with `difflib.SequenceMatcher`. Equal runs keep
   their line IDs and every word ID inside them, untouched.
2. Around the changed regions, flatten the old and new words into flat sequences
   and diff those. Word IDs survive across line boundaries, which is what makes
   splitting and merging lines non-destructive -- a naive line-pairing approach
   would orphan every word after a split.
3. Words that survive keep their ID, their original alignment and any manual
   timing edit. Genuinely new words get fresh IDs and an explicit unresolved
   timing carrying a reason, never an invented time.

**Display versus sung text.** Words compare on a normalised form (casefolded,
surrounding punctuation stripped). So changing `dont` to `don't`, or re-wrapping
a line, keeps the timing: the sung word did not change. The authored spelling is
still stored verbatim.

Section labels are explicit. A line beginning with `#` is a section label and is
never sung. Bracketed text is left alone: `[Chorus]` may be a heading, but
brackets also appear in real lyrics, so guessing is not safe.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable

from .project import Line, Project, Section, Word, WordTiming, new_id

#: Prefix marking a section label line. Chosen because it is rare in sung lyrics
#: and unambiguous, unlike brackets.
SECTION_PREFIX = "#"

#: Reason recorded against words introduced by an edit.
REASON_NEW_TEXT = "inserted or replaced by a lyric edit; needs timing"

_PUNCT_STRIP = re.compile(r"^[^\w']+|[^\w']+$", flags=re.UNICODE)


def normalize_word(token: str) -> str:
    """Comparison key for a word.

    Casefolds, normalises unicode so smart and straight apostrophes agree,
    strips surrounding punctuation, then removes apostrophes entirely.

    Dropping apostrophes is a deliberate trade. It means "dont" and "don't"
    compare equal, so correcting that typo keeps the word's timing -- which is
    the stated acceptance criterion. The cost is that "were" and "we're" also
    compare equal, so changing one into the other keeps the old timing instead
    of flagging it for review. That is the better failure: the two occupy the
    same slot in the line, and silently *keeping* correct-enough timing is far
    less damaging than silently discarding a user's timing work over an
    apostrophe.
    """
    t = unicodedata.normalize("NFKC", token)
    t = t.replace(chr(0x2019), "'")
    t = _PUNCT_STRIP.sub("", t)
    return t.replace("'", "").casefold()


def tokenize(line: str) -> list[str]:
    return line.split()


@dataclass
class ParsedLine:
    text: str
    is_section: bool = False

    @property
    def label(self) -> str:
        return self.text.lstrip(SECTION_PREFIX).strip()


def parse_lyrics(text: str) -> list[ParsedLine]:
    """Split pasted text into sung lines and section labels.

    Blank lines are separators and are not preserved as empty lyric lines; the
    line list is the sung structure, not a verbatim buffer.
    """
    out: list[ParsedLine] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        out.append(ParsedLine(text=stripped,
                              is_section=stripped.startswith(SECTION_PREFIX)))
    return out


def count_lyrics(text: str) -> tuple[int, int]:
    """(sung lines, sung words) for the UI's counter."""
    parsed = [p for p in parse_lyrics(text) if not p.is_section]
    return len(parsed), sum(len(tokenize(p.text)) for p in parsed)


@dataclass
class ReconcileResult:
    lines: list[Line]
    sections: list[Section]
    kept_word_ids: set[str] = field(default_factory=set)
    new_word_ids: set[str] = field(default_factory=set)
    removed_word_ids: set[str] = field(default_factory=set)

    @property
    def changed(self) -> bool:
        return bool(self.new_word_ids or self.removed_word_ids)


def _flatten(lines: Iterable[Line]) -> list[Word]:
    return [w for ln in lines for w in ln.words]


def _match_words(old_words: list[Word], new_tokens: list[str]) -> list[Word]:
    """Map new tokens onto old words, preserving IDs where the word survives.

    Sequence-aware: `difflib` aligns by position within the sequence, so a word
    repeated three times in a line keeps its own identity rather than collapsing
    onto the first occurrence.
    """
    old_keys = [normalize_word(w.text) for w in old_words]
    new_keys = [normalize_word(t) for t in new_tokens]
    matcher = difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)

    result: list[Word | None] = [None] * len(new_tokens)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            old = old_words[i1 + offset]
            j = j1 + offset
            # Keep the ID and timing; adopt the newly authored spelling.
            result[j] = Word(id=old.id, text=new_tokens[j],
                             display_text=old.display_text,
                             non_sung=old.non_sung)
    for j, slot in enumerate(result):
        if slot is None:
            result[j] = Word(id=new_id("w"), text=new_tokens[j])
    return [w for w in result if w is not None]


def reconcile(old_lines: list[Line], new_text: str,
              old_sections: list[Section] | None = None) -> ReconcileResult:
    """Rebuild the line list from edited text, preserving what did not change."""
    parsed = parse_lyrics(new_text)

    # Section labels are positional markers; sung lines carry the identity work.
    sung_parsed: list[ParsedLine] = []
    section_at: dict[int, str] = {}   # index into sung_parsed -> label
    for p in parsed:
        if p.is_section:
            section_at.setdefault(len(sung_parsed), p.label)
        else:
            sung_parsed.append(p)

    old_texts = [ln.text for ln in old_lines]
    new_texts = [p.text for p in sung_parsed]
    old_keys = [" ".join(normalize_word(t) for t in tokenize(t_)) for t_ in old_texts]
    new_keys = [" ".join(normalize_word(t) for t in tokenize(t_)) for t_ in new_texts]

    matcher = difflib.SequenceMatcher(a=old_keys, b=new_keys, autojunk=False)
    new_lines: list[Line | None] = [None] * len(new_texts)
    kept: set[str] = set()

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            # Unchanged sung content: keep line and word IDs verbatim, but adopt
            # any punctuation or capitalisation the user just typed.
            for offset in range(i2 - i1):
                old_line = old_lines[i1 + offset]
                j = j1 + offset
                tokens = tokenize(new_texts[j])
                words = _match_words(old_line.words, tokens)
                new_lines[j] = Line(
                    id=old_line.id, words=words,
                    section_id=old_line.section_id,
                    display_start_ms=old_line.display_start_ms,
                    display_end_ms=old_line.display_end_ms,
                )
                kept.update(w.id for w in words)
        elif tag in ("replace", "delete", "insert"):
            # Changed region: diff the WORDS across the whole block rather than
            # pairing lines. This is what lets a line split or merge without
            # orphaning the timing of every word after the boundary.
            old_block = _flatten(old_lines[i1:i2])
            block_tokens: list[str] = []
            spans: list[tuple[int, int]] = []
            for j in range(j1, j2):
                toks = tokenize(new_texts[j])
                spans.append((len(block_tokens), len(block_tokens) + len(toks)))
                block_tokens.extend(toks)
            matched = _match_words(old_block, block_tokens)
            for offset, (start, end) in enumerate(spans):
                j = j1 + offset
                words = matched[start:end]
                new_lines[j] = Line(id=new_id("line"), words=words)
                kept.update(w.id for w in words)

    lines = [ln for ln in new_lines if ln is not None]

    # Match membership, never the heading text: repeated choruses are distinct.
    old_members = {s.id: {w.id for ln in old_lines if ln.id in s.line_ids
                          for w in ln.words} for s in (old_sections or [])}
    for line in lines:
        line.section_id = None
    sections: list[Section] = []
    for index in sorted(section_at):
        label = section_at[index]
        member_ids = [ln.id for ln in lines[index:]]
        sections.append(Section(id=new_id("sec"), name=label, line_ids=member_ids))
    # Trim membership so each section owns only the lines up to the next one.
    for pos, sec in enumerate(sections):
        if pos + 1 < len(sections):
            following = set(sections[pos + 1].line_ids)
            sec.line_ids = [lid for lid in sec.line_ids if lid not in following]
    candidates = []
    for pos, sec in enumerate(sections):
        members = {w.id for ln in lines if ln.id in sec.line_ids for w in ln.words}
        for sid, old in old_members.items():
            overlap = len(members & old)
            if overlap:
                candidates.append((-overlap, pos, sid))
    assigned, used = set(), set()
    for _, pos, sid in sorted(candidates):
        if pos not in assigned and sid not in used:
            sections[pos].id = sid
            assigned.add(pos)
            used.add(sid)
    for sec in sections:
        for lid in sec.line_ids:
            line = next((l for l in lines if l.id == lid), None)
            if line is not None:
                line.section_id = sec.id

    old_ids = {w.id for w in _flatten(old_lines)}
    surviving = {w.id for w in _flatten(lines)}
    return ReconcileResult(
        lines=lines,
        sections=sections,
        kept_word_ids=surviving & old_ids,
        new_word_ids=surviving - old_ids,
        removed_word_ids=old_ids - surviving,
    )


def apply_lyrics_edit(project: Project, new_text: str) -> ReconcileResult:
    """Commit edited lyric text to a project, in one undoable step.

    Timing for surviving words is untouched. Removed words take their timing
    with them. New words get an explicit unresolved entry with a reason rather
    than a plausible-looking guess.
    """
    result = reconcile(project.lines, new_text, project.sections)
    project.lines = result.lines
    project.sections = result.sections

    for wid in result.removed_word_ids:
        project.original_alignment.pop(wid, None)
        project.timing_edits.pop(wid, None)
        project.alignment_proposals.pop(wid, None)
        project.reviewed.pop(wid, None)
    for wid in result.new_word_ids:
        project.timing_edits[wid] = WordTiming(reason=REASON_NEW_TEXT)
    return result


def to_text(project: Project) -> str:
    """Render a project's lyrics back to plain text, with no internal IDs."""
    by_section: dict[str, str] = {s.id: s.name for s in project.sections}
    out: list[str] = []
    seen_sections: set[str] = set()
    for line in project.lines:
        if line.section_id and line.section_id not in seen_sections:
            seen_sections.add(line.section_id)
            label = by_section.get(line.section_id)
            if label:
                if out:
                    out.append("")
                out.append(f"{SECTION_PREFIX} {label}")
        out.append(line.text)
    return "\n".join(out) + ("\n" if out else "")


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------


@dataclass
class _Snapshot:
    lines: list[Line]
    sections: list[Section]
    original_alignment: dict[str, WordTiming]
    timing_edits: dict[str, WordTiming]


class UndoStack:
    """Snapshot undo for lyric commands.

    Snapshots rather than inverse operations: a lyric edit touches the line
    list, both timing maps and section membership at once, and a wrong inverse
    would silently corrupt identity. Per the shared contract, undo history is
    in-memory only; saved content and recovery are the durable guarantees.
    """

    def __init__(self, limit: int = 50) -> None:
        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._limit = limit

    @staticmethod
    def _capture(project: Project) -> _Snapshot:
        import copy

        return _Snapshot(
            lines=copy.deepcopy(project.lines),
            sections=copy.deepcopy(project.sections),
            original_alignment=copy.deepcopy(project.original_alignment),
            timing_edits=copy.deepcopy(project.timing_edits),
        )

    @staticmethod
    def _restore(project: Project, snap: _Snapshot) -> None:
        project.lines = snap.lines
        project.sections = snap.sections
        project.original_alignment = snap.original_alignment
        project.timing_edits = snap.timing_edits

    def commit(self, project: Project) -> None:
        """Record the state BEFORE a command so it can be restored."""
        self._undo.append(self._capture(project))
        del self._undo[:-self._limit]
        self._redo.clear()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self, project: Project) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._capture(project))
        self._restore(project, self._undo.pop())
        return True

    def redo(self, project: Project) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._capture(project))
        self._restore(project, self._redo.pop())
        return True


# ---------------------------------------------------------------------------
# Applying alignment results to a project
# ---------------------------------------------------------------------------


def apply_alignment(project: Project, aligned_lines, *,
                    only_unresolved: bool = True) -> dict[str, int]:
    """Map an aligner's output onto project word IDs.

    `aligned_lines` is a list of `timings.Line`. Matching is sequence-based over
    the flattened word streams, so a partial alignment attaches each word to its
    own occurrence instead of shifting later words onto earlier ones.

    `only_unresolved=True` is the default and the safe one: it fills words that
    have no timing yet and leaves every manual correction alone. Re-running
    alignment must never silently retime work the user did by hand. Passing
    False is the explicit "realign everything" choice; it replaces the original
    proposals but still does not touch `timing_edits`, so manual corrections
    survive either way and can be dropped deliberately elsewhere.

    Returns counts: filled, skipped_manual, unmatched.
    """
    project_words = [w for _, w in project.iter_words() if not w.non_sung]
    incoming = [w for line in aligned_lines for w in line.words]

    want = [normalize_word(w.text) for w in project_words]
    got = [normalize_word(w.text) for w in incoming]
    matcher = difflib.SequenceMatcher(a=want, b=got, autojunk=False)

    filled = skipped = 0
    matched_ids: set[str] = set()
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            target = project_words[i1 + offset]
            source = incoming[j1 + offset]
            matched_ids.add(target.id)

            has_manual = target.id in project.timing_edits and \
                project.timing_edits[target.id].resolved
            if has_manual:
                skipped += 1
                continue
            existing = project.effective_timing(target.id)
            if only_unresolved and existing is not None and existing.resolved:
                skipped += 1
                continue

            from .project import seconds_to_ms
            proposals = (project.alignment_proposals if target.id in project.original_alignment
                         else project.original_alignment)
            proposals[target.id] = WordTiming(
                start_ms=seconds_to_ms(source.start_s),
                end_ms=seconds_to_ms(source.end_s),
                score=float(source.score),
            )
            # A word that was flagged as needing timing no longer is.
            edit = project.timing_edits.get(target.id)
            if edit is not None and not edit.resolved:
                del project.timing_edits[target.id]
            filled += 1
            project.reviewed.pop(target.id, None)

    unmatched = [w for w in project_words if w.id not in matched_ids]
    for word in unmatched:
        existing = project.effective_timing(word.id)
        if existing is not None and existing.resolved:
            # Already timed, just absent from this alignment pass. Leave it.
            continue
        # Replace any earlier unresolved reason: after an alignment run, "the
        # aligner did not return this word" is the useful explanation, not a
        # stale "inserted by an edit" from three actions ago.
        project.timing_edits[word.id] = WordTiming(
            reason="the aligner did not return this word; needs timing")
    return {"filled": filled, "skipped_manual": skipped,
            "unmatched": len(unmatched)}
