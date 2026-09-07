"""
Forced alignment of user-supplied lyrics to the isolated vocal stem.

The active phrase-first pipeline lives in alignment_engine.py. Recognized
phrases provide acoustic anchors, verified online timing can fill gaps, and
individual words are refined inside their own phrase. Older regrouping helpers
remain available for importing legacy results.

ML imports are deferred so the rest of the package stays importable without torch.
"""
from __future__ import annotations

import difflib
import logging
import unicodedata

import numpy as np

from .timings import AlignmentResult, Line, Word  # AlignmentResult re-exported

log = logging.getLogger(__name__)


def _resample_to_16k_mono(samples: np.ndarray, sr: int) -> np.ndarray:
    """WhisperX expects 16 kHz mono float32 in [-1, 1]."""
    from scipy.signal import resample_poly

    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    samples = samples.astype(np.float32, copy=False)
    if sr == 16000:
        return samples
    # rational resampling
    from math import gcd
    g = gcd(sr, 16000)
    return resample_poly(samples, 16000 // g, sr // g).astype(np.float32)


def _split_lyrics(text: str) -> list[tuple[int, str]]:
    """Returns (line_index, line_text) for non-empty lines, preserving original index."""
    out = []
    for i, raw in enumerate(text.splitlines()):
        stripped = raw.strip()
        if stripped:
            out.append((i, stripped))
    return out


def _normalise_token(token: str) -> str:
    """Loose comparison key for matching aligner output back to source words."""
    import re as _re

    t = unicodedata.normalize("NFKC", str(token)).replace(chr(0x2019), "'")
    t = _re.sub(r"[^\w']+", "", t)
    return t.replace("'", "").casefold()


def _remap_line_indices(
    aligned_words: list[dict],
    flat_line_idx: list[int],
    expected_tokens: list[str] | None,
) -> list[int | None]:
    """Map each aligned word back to the source line it actually came from.

    Returns one entry per aligned word: its source line index, or None when the
    word cannot be matched to the source at all. Sequence alignment rather than
    positional truncation is what keeps a dropped middle word from shifting
    everything after it.
    """
    if not expected_tokens or len(expected_tokens) != len(flat_line_idx):
        # No usable source tokens to match against; degrade to the old prefix
        # behaviour rather than inventing associations.
        return list(flat_line_idx[: len(aligned_words)]) +             [None] * max(0, len(aligned_words) - len(flat_line_idx))

    got = [_normalise_token(w.get("word", "")) for w in aligned_words]
    want = [_normalise_token(t) for t in expected_tokens]
    matcher = difflib.SequenceMatcher(a=want, b=got, autojunk=False)

    mapped: list[int | None] = [None] * len(aligned_words)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "equal":
            continue
        for offset in range(i2 - i1):
            mapped[j1 + offset] = flat_line_idx[i1 + offset]
    return mapped


def _group_words_into_lines(
    aligned_words: list[dict],
    seg_line_indices: list[list[int]],
    user_lines: list[tuple[int, str]],
    score_threshold: float = 0.3,
    expected_tokens: list[str] | None = None,
) -> tuple[list[Line], int]:
    """
    Re-attach each aligned word to its source line via the sidecar line_indices,
    then build Line objects in the user's original line order.
    """
    # Flatten the per-segment line_indices to a single list aligned 1-to-1 with aligned_words.
    flat_line_idx: list[int] = []
    for li in seg_line_indices:
        flat_line_idx.extend(li)

    if len(flat_line_idx) != len(aligned_words):
        # WhisperX dropped words it could not align. Truncating to a prefix (the
        # old fallback) is wrong: a word missing from the MIDDLE shifts every
        # later word onto its neighbour's line, so "charlie" silently lands in
        # the line above. Align the two sequences instead, so each aligned word
        # keeps its true source position and only the dropped words go missing.
        log.warning(
            "alignment dropped %d words (got %d aligned, expected %d); "
            "re-matching by sequence so later words keep their own lines",
            len(flat_line_idx) - len(aligned_words),
            len(aligned_words),
            len(flat_line_idx),
        )
        flat_line_idx = _remap_line_indices(
            aligned_words, flat_line_idx, expected_tokens
        )

    # Group aligned words by source line index. A None index means the word
    # could not be matched back to the source at all; drop it rather than
    # guessing a line for it.
    by_line: dict[int, list[Word]] = {}
    low_conf = 0
    for w, li in zip(aligned_words, flat_line_idx):
        if li is None:
            continue
        if w.get("start") is None or w.get("end") is None:
            continue
        score = float(w.get("score", 0.5))
        if score < score_threshold:
            low_conf += 1
        by_line.setdefault(li, []).append(
            Word(
                text=str(w["word"]).strip(),
                start_s=float(w["start"]),
                end_s=float(w["end"]),
                score=score,
            )
        )

    lines: list[Line] = []
    for orig_idx, line_text in user_lines:
        words = by_line.get(orig_idx, [])
        if not words:
            continue
        lines.append(
            Line(
                index=orig_idx,
                text=line_text,
                start_s=min(w.start_s for w in words),
                end_s=max(w.end_s for w in words),
                words=words,
            )
        )
    return lines, low_conf


def align(
    vocal_samples: np.ndarray,
    sr: int,
    lyrics_text: str,
    whisper_model: str = "medium",
    device: str = "cpu",
    language: str | None = None,
    **options,
) -> AlignmentResult:
    """
    vocal_samples: float32 ndarray, mono or stereo, range ~[-1, 1].
    """
    from .alignment_engine import align as phrase_align
    return phrase_align(vocal_samples, sr, lyrics_text, whisper_model, device, language, **options)
