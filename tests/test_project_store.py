"""P01.2 tests: the saved-project store.

Acceptance criteria under test (from 01-FOUNDATION.md):
  - save/reopen preserves IDs and settings; Save As does not alter the original
  - a moved project with internal relative assets still opens
  - missing external assets can be relinked
  - a failed/interrupted save leaves the last-saved project recoverable
  - legacy import round-trips without losing IDs or settings, and does not
    modify the user's files
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from heartbeam import project as P
from heartbeam.timings import Line as TLine
from heartbeam.timings import Models, Source, Timings
from heartbeam.timings import Word as TWord
from heartbeam.timings import to_json


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _legacy_timings() -> Timings:
    return Timings(
        source=Source(audio_path="song.mp3", lyrics_path="lyrics.txt",
                      sample_rate=44100, duration_s=12.0),
        models=Models(separator="rock", aligner="whisperx"),
        lines=[
            TLine(index=0, text="hello there world", start_s=1.0, end_s=3.5, words=[
                TWord(text="hello", start_s=1.0, end_s=1.5, score=0.9),
                TWord(text="there", start_s=1.6, end_s=2.0, score=0.8),
                TWord(text="world", start_s=2.1, end_s=3.5, score=0.95),
            ]),
            TLine(index=1, text="hello again", start_s=4.0, end_s=5.25, words=[
                TWord(text="hello", start_s=4.0, end_s=4.5, score=0.7),
                TWord(text="again", start_s=4.6, end_s=5.25, score=0.6),
            ]),
        ],
    )


def _fake_audio(path: Path, payload: bytes = b"RIFFfake-audio-data") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


# ---------------------------------------------------------------------------
# ms conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seconds,expected", [
    (0.0, 0), (1.0, 1000), (1.0005, 1001), (1.0004, 1000),
    (2.5, 2500), (59.999, 59999), (0.0001, 0),
])
def test_seconds_to_ms_rounds_half_away_from_zero(seconds, expected):
    assert P.seconds_to_ms(seconds) == expected


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_seconds_to_ms_rejects_non_finite(bad):
    with pytest.raises(ValueError):
        P.seconds_to_ms(bad)


# ---------------------------------------------------------------------------
# round trip
# ---------------------------------------------------------------------------


def test_new_project_round_trips_with_stable_ids(tmp_path):
    proj = P.create_project(tmp_path, "My Song")
    P.set_lyrics_from_text(proj, "hello there world\nhello again\n")
    original_word_ids = proj.word_ids()
    original_line_ids = [ln.id for ln in proj.lines]

    P.save_project(proj, tmp_path)
    reloaded = P.load_project(tmp_path)

    assert reloaded.id == proj.id
    assert reloaded.name == "My Song"
    assert reloaded.word_ids() == original_word_ids
    assert [ln.id for ln in reloaded.lines] == original_line_ids
    assert reloaded.lines[0].text == "hello there world"


def test_repeated_words_get_distinct_ids(tmp_path):
    """Text is not identity: 'hello' appears in both lines."""
    proj = P.create_project(tmp_path, "dupes")
    P.set_lyrics_from_text(proj, "hello there\nhello again\n")
    ids = proj.word_ids()
    assert len(ids) == len(set(ids)) == 4


def test_save_bumps_revision_and_reopen_preserves_settings(tmp_path):
    proj = P.create_project(tmp_path, "s")
    proj.presentation.song_style = {"font": {"size_px": 96}}
    proj.vocal_mix.default_value = 0.25
    P.save_project(proj, tmp_path)
    first = proj.revision
    P.save_project(proj, tmp_path)
    assert proj.revision == first + 1

    reloaded = P.load_project(tmp_path)
    assert reloaded.presentation.song_style["font"]["size_px"] == 96
    assert reloaded.vocal_mix.default_value == 0.25


def test_effective_timing_prefers_edit_over_original(tmp_path):
    proj = P.create_project(tmp_path, "t")
    P.set_lyrics_from_text(proj, "alpha bravo\n")
    a, b = proj.word_ids()
    proj.original_alignment[a] = P.WordTiming(start_ms=0, end_ms=500, score=0.4)
    proj.original_alignment[b] = P.WordTiming(start_ms=500, end_ms=900, score=0.4)
    proj.timing_edits[a] = P.WordTiming(start_ms=100, end_ms=450)

    assert proj.effective_timing(a).start_ms == 100      # edit wins
    assert proj.effective_timing(b).start_ms == 500      # falls back to original

    P.save_project(proj, tmp_path)
    reloaded = P.load_project(tmp_path)
    assert reloaded.effective_timing(a).start_ms == 100
    assert reloaded.original_alignment[a].start_ms == 0, "original must stay immutable"


def test_unresolved_words_are_listed_not_invented(tmp_path):
    proj = P.create_project(tmp_path, "u")
    P.set_lyrics_from_text(proj, "alpha bravo charlie\n")
    a, b, c = proj.word_ids()
    proj.original_alignment[a] = P.WordTiming(start_ms=0, end_ms=100)
    proj.timing_edits[b] = P.WordTiming(reason="aligner dropped this word")

    unresolved = proj.unresolved_words()
    ids = {w.id for _, w, _ in unresolved}
    assert ids == {b, c}
    reasons = {w.id: r for _, w, r in unresolved}
    assert reasons[b] == "aligner dropped this word"


def test_non_sung_words_are_not_flagged_for_review(tmp_path):
    proj = P.create_project(tmp_path, "n")
    P.set_lyrics_from_text(proj, "CHORUS\n")
    proj.lines[0].words[0].non_sung = True
    assert proj.unresolved_words() == []


# ---------------------------------------------------------------------------
# schema versioning
# ---------------------------------------------------------------------------


def test_unknown_schema_version_is_refused(tmp_path):
    proj = P.create_project(tmp_path, "v")
    P.save_project(proj, tmp_path)
    manifest = tmp_path / P.MANIFEST_NAME
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["project_schema_version"] = 999
    manifest.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(P.ProjectError) as exc:
        P.load_project(tmp_path)
    assert "999" in str(exc.value)


def test_corrupt_manifest_reports_clearly(tmp_path):
    P.create_project(tmp_path, "c")
    (tmp_path / P.MANIFEST_NAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(P.ProjectError):
        P.load_project(tmp_path)


# ---------------------------------------------------------------------------
# assets, moving and relinking
# ---------------------------------------------------------------------------


def test_moved_project_with_internal_assets_still_opens(tmp_path):
    src = tmp_path / "proj"
    proj = P.create_project(src, "movable")
    audio = _fake_audio(tmp_path / "external" / "song.mp3")
    P.add_asset(proj, src, audio, "karaoke_audio", copy_into_project=True)
    P.save_project(proj, src)

    moved = tmp_path / "somewhere" / "else"
    moved.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(moved))

    reloaded = P.load_project(moved)
    asset = reloaded.asset_by_role("karaoke_audio")
    assert asset is not None and not asset.external
    assert asset.resolve(moved).exists(), "relative asset must survive the move"
    assert P.missing_assets(reloaded, moved) == []


def test_external_asset_goes_missing_and_can_be_relinked(tmp_path):
    root = tmp_path / "proj"
    proj = P.create_project(root, "ext")
    audio = _fake_audio(tmp_path / "ext" / "song.mp3")
    asset = P.add_asset(proj, root, audio, "original_audio", copy_into_project=False)
    P.save_project(proj, root)
    assert P.missing_assets(proj, root) == []

    audio.unlink()
    missing = P.missing_assets(proj, root)
    assert [a.id for a in missing] == [asset.id]

    moved = _fake_audio(tmp_path / "new_home" / "song.mp3")
    P.relink_asset(proj, root, asset.id, moved)
    assert P.missing_assets(proj, root) == []
    assert proj.asset_by_role("original_audio").id == asset.id, "ID must survive relink"


def test_adding_same_role_twice_replaces_not_duplicates(tmp_path):
    root = tmp_path / "p"
    proj = P.create_project(root, "roles")
    a1 = _fake_audio(tmp_path / "a1.mp3", b"one")
    a2 = _fake_audio(tmp_path / "a2.mp3", b"two")
    P.add_asset(proj, root, a1, "karaoke_audio")
    P.add_asset(proj, root, a2, "karaoke_audio")
    roles = [a.role for a in proj.assets]
    assert roles.count("karaoke_audio") == 1


# ---------------------------------------------------------------------------
# Save As
# ---------------------------------------------------------------------------


def test_save_as_leaves_the_original_untouched(tmp_path):
    src = tmp_path / "orig"
    proj = P.create_project(src, "original")
    P.set_lyrics_from_text(proj, "alpha bravo\n")
    _fake_audio(tmp_path / "song.mp3")
    P.add_asset(proj, src, tmp_path / "song.mp3", "karaoke_audio")
    P.save_project(proj, src)
    before = (src / P.MANIFEST_NAME).read_text(encoding="utf-8")

    dest = tmp_path / "copy"
    copy = P.save_project_as(proj, dest, src_dir=src)

    assert (src / P.MANIFEST_NAME).read_text(encoding="utf-8") == before
    assert copy.id != proj.id, "the copy needs its own identity"
    assert copy.word_ids() == proj.word_ids(), "content IDs must carry over"
    assert (dest / "audio" / "song.mp3").exists(), "assets travel with the copy"

    # Editing the copy must not touch the original.
    copy.name = "renamed copy"
    P.save_project(copy, dest)
    assert P.load_project(src).name == "original"


def test_save_as_rejects_an_unrelated_nonempty_folder(tmp_path):
    source = tmp_path / "source"
    project = P.create_project(source, "safe")
    P.save_project(project, source)
    destination = tmp_path / "occupied"
    destination.mkdir()
    kept = destination / "song.wav"
    kept.write_bytes(b"do not replace")

    with pytest.raises(P.ProjectError, match="not empty"):
        P.save_project_as(project, destination, src_dir=source)

    assert kept.read_bytes() == b"do not replace"
    assert not (destination / P.MANIFEST_NAME).exists()


# ---------------------------------------------------------------------------
# atomicity and recovery
# ---------------------------------------------------------------------------


def test_interrupted_save_leaves_last_good_manifest(tmp_path, monkeypatch):
    proj = P.create_project(tmp_path, "safe")
    P.set_lyrics_from_text(proj, "first version\n")
    P.save_project(proj, tmp_path)
    good = (tmp_path / P.MANIFEST_NAME).read_text(encoding="utf-8")

    proj.name = "half written"

    def boom(src, dst):
        raise OSError("simulated crash during rename")

    monkeypatch.setattr(P.os, "replace", boom)
    with pytest.raises(OSError):
        P.save_project(proj, tmp_path)

    assert (tmp_path / P.MANIFEST_NAME).read_text(encoding="utf-8") == good
    assert P.load_project(tmp_path).name == "safe"
    leftovers = list(tmp_path.glob(".tmp_*"))
    assert leftovers == [], f"temp files left behind: {leftovers}"


def test_autosave_recovers_when_manifest_is_destroyed(tmp_path):
    proj = P.create_project(tmp_path, "recoverable")
    P.set_lyrics_from_text(proj, "alpha\n")
    P.save_project(proj, tmp_path)
    proj.name = "second revision"
    P.save_project(proj, tmp_path)

    (tmp_path / P.MANIFEST_NAME).write_text("corrupted", encoding="utf-8")
    with pytest.raises(P.ProjectError):
        P.load_project(tmp_path)

    recovered = P.recover_latest_autosave(tmp_path)
    assert recovered is not None
    assert recovered.name == "second revision"


def test_autosave_recovery_skips_a_truncated_newest_snapshot(tmp_path):
    proj = P.create_project(tmp_path, "first")
    P.save_project(proj, tmp_path)
    proj.name = "second"
    P.save_project(proj, tmp_path)

    snaps = sorted((tmp_path / P.AUTOSAVE_DIR).glob("rev_*.json"))
    snaps[-1].write_text('{"project_schema_version": 1, "id"', encoding="utf-8")

    recovered = P.recover_latest_autosave(tmp_path)
    assert recovered is not None and recovered.name == "first"


# ---------------------------------------------------------------------------
# legacy import
# ---------------------------------------------------------------------------


def test_legacy_import_round_trips_and_leaves_originals_alone(tmp_path):
    legacy_dir = tmp_path / "legacy_out"
    legacy_dir.mkdir()
    tj = legacy_dir / "timings.json"
    to_json(_legacy_timings(), tj)
    audio = _fake_audio(legacy_dir / "karaoke.mp3")
    before_timings = tj.read_bytes()
    before_audio = audio.read_bytes()

    root = tmp_path / "project"
    proj = P.import_legacy_timings(root, tj, audio, name="Imported")

    # Originals untouched.
    assert tj.read_bytes() == before_timings
    assert audio.read_bytes() == before_audio

    assert proj.name == "Imported"
    assert [ln.text for ln in proj.lines] == ["hello there world", "hello again"]
    assert proj.provenance.separator_preset == "rock"
    assert proj.provenance.aligner == "whisperx"

    # Seconds converted once, at the boundary.
    first_word = proj.lines[0].words[0]
    t = proj.effective_timing(first_word.id)
    assert (t.start_ms, t.end_ms) == (1000, 1500)
    assert proj.timing_edits == {}, "import produces proposals, not edits"

    # A verbatim copy of the imported artifact is retained.
    kept = root / proj.imported_timings_path
    assert kept.exists() and kept.read_bytes() == before_timings

    reloaded = P.load_project(root)
    assert reloaded.word_ids() == proj.word_ids()
    assert reloaded.effective_timing(first_word.id).start_ms == 1000


def test_legacy_import_without_audio_still_gives_an_editable_project(tmp_path):
    tj = tmp_path / "timings.json"
    to_json(_legacy_timings(), tj)
    root = tmp_path / "proj"
    proj = P.import_legacy_timings(root, tj, None)
    assert len(proj.lines) == 2
    assert proj.asset_by_role("karaoke_audio") is None
    assert P.load_project(root).word_ids() == proj.word_ids()


def test_legacy_import_rejects_a_missing_file(tmp_path):
    with pytest.raises(P.ProjectError):
        P.import_legacy_timings(tmp_path / "p", tmp_path / "nope.json", None)
