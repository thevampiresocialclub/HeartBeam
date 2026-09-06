"""SOFA (Singing-Oriented Forced Aligner) adapter.

SOFA outperforms WhisperX on sung audio because it was trained on singing data
and aligns at the *phoneme* level instead of CTC-character. Sustained vowels,
vibrato, and held notes get accurate boundaries rather than the consonant-tight
estimates WhisperX produces.

SOFA cannot live in our main venv: it pins numpy~=1.24, pandas~=2.0.3,
librosa<0.10 and prefers Python 3.8, which all conflict with whisperx/torch
requirements. We therefore call its CLI via subprocess from a sidecar conda or
venv. See docs/SOFA_SETUP.md for one-time setup; we look up the SOFA python and
checkpoint paths from CLI flags or the HEARTBEAM_SOFA_* environment variables.

Flow:
  1. Write lead-stem audio + lyrics text into a temp folder pair (name.wav, name.lab).
  2. Invoke `<sofa_python> <SOFA_REPO>/infer.py --ckpt … --folder … --dictionary …
     --out_formats TextGrid`.
  3. Parse the TextGrid output back into our Word/Line dataclasses.
"""
from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .timings import AlignmentResult, Line, Word

log = logging.getLogger(__name__)


@dataclass
class SOFAConfig:
    """Locations the SOFA subprocess needs. Resolved from CLI flags or env."""
    python_bin: str          # path to the sidecar venv's python
    repo_dir: str            # path to a cloned qiuqiao/SOFA checkout
    ckpt_path: str           # path to a downloaded SOFA .ckpt
    dictionary_path: str     # path to the phoneme dictionary

    @classmethod
    def from_env_or_args(
        cls,
        python_bin: str | None = None,
        repo_dir: str | None = None,
        ckpt_path: str | None = None,
        dictionary_path: str | None = None,
    ) -> "SOFAConfig":
        return cls(
            python_bin=python_bin or os.environ["HEARTBEAM_SOFA_PYTHON"],
            repo_dir=repo_dir or os.environ["HEARTBEAM_SOFA_REPO"],
            ckpt_path=ckpt_path or os.environ["HEARTBEAM_SOFA_CKPT"],
            dictionary_path=dictionary_path or os.environ["HEARTBEAM_SOFA_DICT"],
        )


def _write_wav(samples: np.ndarray, sr: int, path: str) -> None:
    import soundfile as sf
    if samples.ndim == 2:
        samples = samples.mean(axis=1)
    sf.write(path, samples.astype(np.float32), sr, subtype="FLOAT")


def _split_lyrics(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


# Contraction expansion — SOFA's English dictionary (tgm_sofa_dict.txt) keys words
# without apostrophes, so any contraction needs to be expanded before .lab write.
# Conservative: only the contractions actually present in common English pop lyrics.
_CONTRACTIONS = {
    "i'm": "i am", "i've": "i have", "i'd": "i would", "i'll": "i will",
    "you're": "you are", "you've": "you have", "you'd": "you would", "you'll": "you will",
    "he's": "he is", "she's": "she is", "it's": "it is",
    "he'd": "he would", "she'd": "she would", "it'd": "it would",
    "he'll": "he will", "she'll": "she will", "it'll": "it will",
    "we're": "we are", "we've": "we have", "we'd": "we would", "we'll": "we will",
    "they're": "they are", "they've": "they have", "they'd": "they would", "they'll": "they will",
    "what's": "what is", "what're": "what are", "what've": "what have", "what'd": "what did",
    "that's": "that is", "that'd": "that would", "that'll": "that will",
    "there's": "there is", "there're": "there are", "there'd": "there would",
    "here's": "here is",
    "where's": "where is", "where'd": "where did", "when's": "when is",
    "who's": "who is", "who'd": "who would", "who've": "who have",
    "how's": "how is", "how'd": "how did", "how'll": "how will",
    "isn't": "is not", "aren't": "are not", "wasn't": "was not", "weren't": "were not",
    "hasn't": "has not", "haven't": "have not", "hadn't": "had not",
    "don't": "do not", "doesn't": "does not", "didn't": "did not",
    "won't": "will not", "wouldn't": "would not",
    "can't": "cannot", "couldn't": "could not",
    "shouldn't": "should not", "mustn't": "must not", "shan't": "shall not",
    "let's": "let us", "ain't": "is not",
    "gonna": "going to", "wanna": "want to", "gotta": "got to", "gimme": "give me",
}


def _expand_contractions(text: str) -> str:
    """Expand common English contractions; leave any unmatched apostrophes for the
    fallback strip step to handle."""
    def repl(m: re.Match) -> str:
        word = m.group(0)
        lower = word.lower()
        if lower in _CONTRACTIONS:
            expanded = _CONTRACTIONS[lower]
            return expanded[0].upper() + expanded[1:] if word[0].isupper() else expanded
        return word
    return re.sub(r"[A-Za-z]+'[A-Za-z]+", repl, text)


def _clean_for_alignment(line: str) -> str:
    """Prepare one lyric line for SOFA: drop parens, expand contractions, strip
    remaining punctuation that the dictionary won't tokenize, collapse whitespace."""
    line = _expand_contractions(line)
    line = re.sub(r"[(),.!?;:\"]", " ", line)
    # Drop any straggler apostrophes (possessives like "John's" → "Johns").
    line = line.replace("'", "")
    return re.sub(r"\s+", " ", line).strip()


def _word_tokens(line: str) -> list[str]:
    return [w for w in re.split(r"\s+", _clean_for_alignment(line)) if w]


_TG_ITEM_RE = re.compile(r"item \[\d+\]:")
_TG_NAME_RE = re.compile(r'name = "(?P<n>[^"]+)"')
_TG_INTERVAL_RE = re.compile(
    r"xmin = (?P<xmin>[0-9.eE+-]+)\s+"
    r"xmax = (?P<xmax>[0-9.eE+-]+)\s+"
    r'text = "(?P<text>[^"]*)"'
)
_TG_SILENCE = {"", "sil", "sp", "<sil>", "<sp>", "pau", "<pau>"}


def _parse_textgrid(textgrid_path: str) -> list[tuple[str, float, float]]:
    """Parse SOFA's TextGrid and return the words-tier intervals.

    Robust to TextGrid header fields and tier ordering: splits on "item [N]:"
    blocks and matches the block whose `name` field starts with "word". Falls
    back to the first interval-bearing block if no name matches.
    """
    text = Path(textgrid_path).read_text(encoding="utf-8")
    # parts[0] is the header (preamble + global xmin/xmax); parts[1..] are tier blocks.
    parts = _TG_ITEM_RE.split(text)
    if len(parts) < 2:
        raise RuntimeError(f"no item blocks in TextGrid {textgrid_path}")

    word_block: str | None = None
    for sec in parts[1:]:
        name_m = _TG_NAME_RE.search(sec)
        if name_m and name_m.group("n").lower().startswith("word"):
            word_block = sec
            break
    if word_block is None:
        # Fallback: first block that actually contains intervals.
        word_block = next(
            (sec for sec in parts[1:] if _TG_INTERVAL_RE.search(sec)),
            parts[1],
        )

    out: list[tuple[str, float, float]] = []
    for m in _TG_INTERVAL_RE.finditer(word_block):
        word = m.group("text").strip()
        if word.lower() in _TG_SILENCE:
            continue
        out.append((word, float(m.group("xmin")), float(m.group("xmax"))))
    return out


def align(
    vocal_samples: np.ndarray,
    sr: int,
    lyrics_text: str,
    sofa: SOFAConfig,
    matching_mode: bool = True,
) -> AlignmentResult:
    """Subprocess SOFA and return word/line timings in our schema.

    matching_mode (-m) tells SOFA to find the best contiguous match for the given
    phoneme sequence inside the audio — robust to extra audio at song
    intro/outro where no lyrics are sung. Strongly recommended.
    """
    user_lines = _split_lyrics(lyrics_text)
    if not user_lines:
        raise ValueError("lyrics file is empty")

    with tempfile.TemporaryDirectory(prefix="heartbeam_sofa_") as tmp:
        seg_dir = Path(tmp) / "segments" / "song"
        seg_dir.mkdir(parents=True)
        wav_path = seg_dir / "song.wav"
        lab_path = seg_dir / "song.lab"
        _write_wav(vocal_samples, sr, str(wav_path))
        # SOFA accepts space-separated words on a single .lab line (its dictionary
        # handles g2p). We expand contractions and strip punctuation so every
        # token matches the dictionary's keys.
        lab_text = " ".join(_clean_for_alignment(ln) for ln in user_lines)
        lab_path.write_text(lab_text, encoding="utf-8")
        # Keep a mapping back to original line indices for grouping later.
        word_to_line: list[int] = []
        for idx, ln in enumerate(user_lines):
            for _w in _word_tokens(ln):
                word_to_line.append(idx)

        out_dir = Path(tmp) / "out"
        out_dir.mkdir()

        cmd = [
            sofa.python_bin,
            str(Path(sofa.repo_dir) / "infer.py"),
            "--ckpt", sofa.ckpt_path,
            "--folder", str(Path(tmp) / "segments"),
            "--dictionary", sofa.dictionary_path,
            "--out_formats", "TextGrid",
        ]
        if matching_mode:
            cmd.append("-m")
        log.info("invoking SOFA: %s", " ".join(cmd))
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False,
                              cwd=sofa.repo_dir)
        if proc.returncode != 0:
            raise RuntimeError(
                f"SOFA failed (exit {proc.returncode}):\nSTDOUT:\n{proc.stdout}\n"
                f"STDERR:\n{proc.stderr}"
            )

        # SOFA writes TextGrid files into a "TextGrid" sibling folder near segments/.
        # Find it pragmatically — search the temp tree for *.TextGrid.
        textgrids = list(Path(tmp).rglob("*.TextGrid"))
        if not textgrids:
            raise RuntimeError(
                f"SOFA produced no TextGrid. stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        intervals = _parse_textgrid(str(textgrids[0]))

    # Reassemble word→line mapping. SOFA returns words in lyrics order; if counts
    # mismatch we degrade gracefully (best-effort grouping).
    if len(intervals) != len(word_to_line):
        log.warning(
            "SOFA returned %d words, expected %d from lyrics — alignment may be partial",
            len(intervals), len(word_to_line),
        )

    lines_by_idx: dict[int, list[Word]] = {}
    for i, (w, start, end) in enumerate(intervals):
        line_idx = word_to_line[i] if i < len(word_to_line) else word_to_line[-1]
        lines_by_idx.setdefault(line_idx, []).append(
            Word(text=w, start_s=start, end_s=end, score=1.0)
        )

    lines: list[Line] = []
    for idx in sorted(lines_by_idx):
        words = lines_by_idx[idx]
        lines.append(Line(
            index=idx,
            text=user_lines[idx],
            start_s=min(w.start_s for w in words),
            end_s=max(w.end_s for w in words),
            words=words,
        ))
    return AlignmentResult(
        lines=lines,
        language="en",  # SOFA dictionary is language-specific; assume English for now
        low_confidence_count=0,  # SOFA doesn't expose per-word confidence in TextGrid
        total_words=sum(len(ln.words) for ln in lines),
    )
