import json
from pathlib import Path

from heartbeam.timings import (
    Line,
    Models,
    Source,
    Timings,
    Word,
    from_json,
    to_json,
    to_lrc,
)


def _sample_timings() -> Timings:
    return Timings(
        source=Source(
            audio_path="song.mp3",
            lyrics_path="lyrics.txt",
            sample_rate=44100,
            duration_s=198.42,
        ),
        models=Models(separator="demucs", aligner="whisperx-medium"),
        lines=[
            Line(
                index=0,
                text="Hello darkness my old friend",
                start_s=12.30,
                end_s=14.61,
                words=[
                    Word("Hello", 12.30, 12.72, 0.94),
                    Word("darkness", 12.74, 13.31, 0.91),
                    Word("my", 13.33, 13.55, 0.88),
                    Word("old", 13.57, 13.92, 0.93),
                    Word("friend", 13.94, 14.61, 0.95),
                ],
            ),
            Line(
                index=2,
                text="I've come to talk with you again",
                start_s=15.10,
                end_s=18.20,
                words=[
                    Word("Ive", 15.10, 15.42, 0.85),
                    Word("come", 15.45, 15.75, 0.92),
                ],
            ),
        ],
    )


def test_json_round_trip(tmp_path: Path):
    t = _sample_timings()
    p = tmp_path / "timings.json"
    to_json(t, p)
    t2 = from_json(p)
    assert t2.source.audio_path == t.source.audio_path
    assert t2.models.separator == t.models.separator
    assert len(t2.lines) == 2
    assert t2.lines[0].text == "Hello darkness my old friend"
    assert t2.lines[0].words[0].text == "Hello"
    assert abs(t2.lines[0].words[0].start_s - 12.30) < 1e-3


def test_lrc_export_emits_line_per_lyric_line(tmp_path: Path):
    t = _sample_timings()
    p = tmp_path / "lyrics.lrc"
    to_lrc(t, p)
    content = p.read_text(encoding="utf-8").strip().splitlines()
    assert len(content) == 2
    assert content[0].startswith("[00:12.30]")
    assert "Hello darkness my old friend" in content[0]
    assert content[1].startswith("[00:15.10]")


def test_schema_version_in_json(tmp_path: Path):
    t = _sample_timings()
    p = tmp_path / "timings.json"
    to_json(t, p)
    raw = json.loads(p.read_text(encoding="utf-8"))
    assert raw["schema_version"] == 1


def test_lrc_zero_padded_minutes_and_seconds(tmp_path: Path):
    # Word at 65.07s → should be [01:05.07]
    t = Timings(
        source=Source("a.mp3", "a.txt", 44100, 70.0),
        models=Models("demucs", "whisperx-medium"),
        lines=[Line(index=0, text="one", start_s=65.07, end_s=65.5, words=[Word("one", 65.07, 65.5, 1.0)])],
    )
    p = tmp_path / "out.lrc"
    to_lrc(t, p)
    assert p.read_text(encoding="utf-8").strip() == "[01:05.07]one"
