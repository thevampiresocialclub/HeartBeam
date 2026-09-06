"""
Forced alignment of user-supplied lyrics to the isolated vocal stem.

Strategy:
1. Run WhisperX ASR to discover where in the song people are singing (rough
   segment start/end times).
2. Distribute the user's lyrics across those segments proportionally to
   ASR-detected word counts. This pins user words to the right region of audio
   without trusting Whisper's actual transcribed text.
3. Run WhisperX's CTC alignment to snap each user word to its exact onset/offset.
4. Re-group the resulting word timings into the user's original lyric lines
   (preserving phrasing for the Phase-2 video renderer).

ML imports are deferred so the rest of the package stays importable without torch.
"""
from __future__ import annotations

import logging

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


def _distribute_lyrics_to_segments(
    user_lines: list[tuple[int, str]],
    asr_segments: list[dict],
) -> list[dict]:
    """
    Build alignment-input segments by proportionally assigning user words to ASR segment time spans.

    Each output segment carries 'line_indices' so we can re-group after alignment.
    """
    if not asr_segments:
        raise RuntimeError("WhisperX ASR found no speech segments in the vocal stem.")

    # Flatten user words with their source line index.
    flat: list[tuple[str, int]] = []
    for orig_idx, line in user_lines:
        for w in line.split():
            flat.append((w, orig_idx))
    if not flat:
        raise ValueError("lyrics file contains no words after stripping")

    # Allocation proportional to ASR words-per-segment.
    asr_word_counts = [max(1, len(s.get("text", "").split())) for s in asr_segments]
    total_asr_words = sum(asr_word_counts)
    n_user = len(flat)

    allocations: list[int] = []
    running = 0.0
    for count in asr_word_counts:
        share = n_user * count / total_asr_words
        running += share
        allocations.append(int(round(running)) - sum(allocations))
    # Patch any drift.
    drift = n_user - sum(allocations)
    allocations[-1] += drift

    new_segments: list[dict] = []
    cursor = 0
    for seg, take in zip(asr_segments, allocations):
        if take <= 0:
            continue
        chunk = flat[cursor : cursor + take]
        cursor += take
        if not chunk:
            continue
        new_segments.append(
            {
                "text": " ".join(w for w, _ in chunk),
                "start": float(seg["start"]),
                "end": float(seg["end"]),
                # Sidecar: which user-line index does each word in this segment belong to?
                "_line_indices": [li for _, li in chunk],
            }
        )
    if cursor < n_user:
        # Stragglers go to the last segment.
        leftover = flat[cursor:]
        if new_segments:
            new_segments[-1]["text"] += " " + " ".join(w for w, _ in leftover)
            new_segments[-1]["_line_indices"].extend(li for _, li in leftover)
        else:
            new_segments.append(
                {
                    "text": " ".join(w for w, _ in leftover),
                    "start": 0.0,
                    "end": float(asr_segments[-1]["end"]),
                    "_line_indices": [li for _, li in leftover],
                }
            )
    return new_segments


def _group_words_into_lines(
    aligned_words: list[dict],
    seg_line_indices: list[list[int]],
    user_lines: list[tuple[int, str]],
    score_threshold: float = 0.3,
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
        # Length mismatch: WhisperX dropped some words it couldn't align.
        # Fall back to best-effort: keep the prefix that matches.
        log.warning(
            "alignment dropped %d words (got %d aligned, expected %d)",
            len(flat_line_idx) - len(aligned_words),
            len(aligned_words),
            len(flat_line_idx),
        )
        flat_line_idx = flat_line_idx[: len(aligned_words)]

    # Group aligned words by source line index.
    by_line: dict[int, list[Word]] = {}
    low_conf = 0
    for w, li in zip(aligned_words, flat_line_idx):
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
) -> AlignmentResult:
    """
    vocal_samples: float32 ndarray, mono or stereo, range ~[-1, 1].
    """
    import whisperx  # deferred

    audio = _resample_to_16k_mono(vocal_samples, sr)

    compute_type = "float16" if device == "cuda" else "int8"
    log.info("loading whisperx ASR model: %s (device=%s)", whisper_model, device)
    asr = whisperx.load_model(whisper_model, device, compute_type=compute_type)
    asr_result = asr.transcribe(audio, batch_size=8, language=language)
    lang = asr_result.get("language", language or "en")

    user_lines = _split_lyrics(lyrics_text)
    if not user_lines:
        raise ValueError("lyrics file is empty")

    new_segments = _distribute_lyrics_to_segments(user_lines, asr_result["segments"])
    seg_line_indices = [s.pop("_line_indices") for s in new_segments]

    log.info("loading whisperx alignment model (language=%s)", lang)
    align_model, metadata = whisperx.load_align_model(language_code=lang, device=device)
    aligned = whisperx.align(
        new_segments, align_model, metadata, audio, device, return_char_alignments=False
    )

    word_segments = aligned.get("word_segments", [])
    lines, low_conf = _group_words_into_lines(
        word_segments, seg_line_indices, user_lines
    )
    return AlignmentResult(
        lines=lines,
        language=lang,
        low_confidence_count=low_conf,
        total_words=sum(len(ln.words) for ln in lines),
    )
