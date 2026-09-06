"""
Master timing artifact: the contract between Phase 1 (audio engine) and Phase 2 (video renderer).

This module is pure Python — no audio, no ML deps. Dataclasses + JSON + LRC.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class Word:
    text: str
    start_s: float
    end_s: float
    score: float = 1.0

    @property
    def duration_s(self) -> float:
        return max(0.0, self.end_s - self.start_s)


@dataclass
class Line:
    index: int
    text: str
    start_s: float
    end_s: float
    words: list[Word] = field(default_factory=list)


@dataclass
class AlignmentResult:
    """Output of any aligner (WhisperX, SOFA, …) — consumed by the masking step."""
    lines: list[Line]
    language: str
    low_confidence_count: int
    total_words: int


@dataclass
class Source:
    audio_path: str
    lyrics_path: str
    sample_rate: int
    duration_s: float


@dataclass
class Models:
    separator: str
    aligner: str


@dataclass
class Timings:
    source: Source
    models: Models
    lines: list[Line] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source": asdict(self.source),
            "models": asdict(self.models),
            "lines": [
                {
                    "index": ln.index,
                    "text": ln.text,
                    "start_s": round(ln.start_s, 3),
                    "end_s": round(ln.end_s, 3),
                    "words": [
                        {
                            "text": w.text,
                            "start_s": round(w.start_s, 3),
                            "end_s": round(w.end_s, 3),
                            "score": round(w.score, 3),
                        }
                        for w in ln.words
                    ],
                }
                for ln in self.lines
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Timings":
        src = Source(**d["source"])
        mdl = Models(**d["models"])
        lines = [
            Line(
                index=ln["index"],
                text=ln["text"],
                start_s=float(ln["start_s"]),
                end_s=float(ln["end_s"]),
                words=[Word(**w) for w in ln["words"]],
            )
            for ln in d["lines"]
        ]
        sv = int(d.get("schema_version", SCHEMA_VERSION))
        if sv != SCHEMA_VERSION:
            raise ValueError(f"unsupported timings schema_version: {sv}")
        return cls(source=src, models=mdl, lines=lines, schema_version=sv)


def to_json(timings: Timings, path: str | Path) -> None:
    Path(path).write_text(json.dumps(timings.to_dict(), indent=2), encoding="utf-8")


def from_json(path: str | Path) -> Timings:
    return Timings.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _fmt_lrc_ts(t: float) -> str:
    if t < 0:
        t = 0.0
    minutes = int(t // 60)
    seconds = t - minutes * 60
    return f"[{minutes:02d}:{seconds:05.2f}]"


def to_lrc(timings: Timings, path: str | Path) -> None:
    """Emit a standard LRC sidecar — one line per source-lyric line, timestamped at line start."""
    out_lines = []
    for ln in timings.lines:
        out_lines.append(f"{_fmt_lrc_ts(ln.start_s)}{ln.text}")
    Path(path).write_text("\n".join(out_lines) + "\n", encoding="utf-8")
