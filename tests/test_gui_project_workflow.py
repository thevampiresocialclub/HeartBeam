"""P01.4 tests: the visible project workflow.

The acceptance criterion is behavioural rather than structural -- "close and
reopen the app and resume the same song without repeating separation" -- so
these drive the real Streamlit script through AppTest rather than calling
helpers directly. A previous run is simulated by building a project on disk,
then a *fresh* app session opens it with no run history at all.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from heartbeam import project as P
from heartbeam.timings import Line as TLine
from heartbeam.timings import Models, Source, Timings
from heartbeam.timings import Word as TWord
from heartbeam.timings import to_json

GUI = str(Path(__file__).resolve().parent.parent / "heartbeam" / "gui.py")


def _ffmpeg_missing() -> bool:
    return shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None


def _timings() -> Timings:
    return Timings(
        source=Source(audio_path="karaoke.mp3", lyrics_path="l.txt",
                      sample_rate=44100, duration_s=4.0),
        models=Models(separator="rock", aligner="whisperx"),
        lines=[TLine(index=0, text="hello there", start_s=0.5, end_s=2.5, words=[
            TWord(text="hello", start_s=0.5, end_s=1.4, score=0.9),
            TWord(text="there", start_s=1.5, end_s=2.5, score=0.8),
        ])],
    )


def _make_audio(path: Path) -> Path:
    """Real 4s mp3 when ffmpeg is available, otherwise a stub."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if _ffmpeg_missing():
        path.write_bytes(b"stub-audio")
        return path
    subprocess.run(
        ["ffmpeg", "-nostdin", "-y", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=frequency=330:duration=4",
         "-c:a", "libmp3lame", str(path)],
        check=True, capture_output=True)
    return path


def _existing_song_project(tmp_path: Path) -> Path:
    """A project as it would exist after yesterday's generation run."""
    legacy = tmp_path / "yesterday"
    legacy.mkdir()
    tj = legacy / "timings.json"
    to_json(_timings(), tj)
    audio = _make_audio(legacy / "karaoke.mp3")

    project_dir = tmp_path / "saved_project"
    P.import_legacy_timings(project_dir, tj, audio, name="Yesterdays Song")
    return project_dir


def _fresh_app() -> AppTest:
    at = AppTest.from_file(GUI, default_timeout=120)
    at.run()
    return at


def test_new_session_starts_with_no_project():
    at = _fresh_app()
    assert not at.exception
    assert at.session_state["project"] is None
    labels = [s.value for s in at.subheader]
    assert "Karaoke video" not in labels, "video controls need a song first"


def test_opening_a_project_resumes_the_song_without_a_run(tmp_path):
    """The P01.4 acceptance criterion, end to end."""
    project_dir = _existing_song_project(tmp_path)

    at = _fresh_app()
    assert at.session_state["out_dir"] is None, "no generation run in this session"

    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    assert not at.exception, at.exception

    project = at.session_state["project"]
    assert project is not None
    assert project.name == "Yesterdays Song"
    assert [ln.text for ln in project.lines] == ["hello there"]

    # Timing came back from the saved project, not from a fresh alignment.
    first_word = project.lines[0].words[0]
    assert project.effective_timing(first_word.id).start_ms == 500

    # And the video controls are reachable with no separation run.
    assert "Karaoke video" in [s.value for s in at.subheader]
    assert any(b.label == "Render video" for b in at.button)
    assert at.session_state["out_dir"] is None


def test_opening_a_nonexistent_project_reports_an_error(tmp_path):
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(tmp_path / "nope"))
    at.button(key="open_project_btn").click().run()
    assert not at.exception
    assert at.session_state["project"] is None
    assert any("Could not open" in e.value for e in at.error)


def test_opening_a_corrupt_project_recovers_from_autosave(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    proj = P.load_project(project_dir)
    proj.name = "Recovered Name"
    P.save_project(proj, project_dir)
    (project_dir / P.MANIFEST_NAME).write_text("{ broken", encoding="utf-8")

    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    assert not at.exception
    assert at.session_state["project"] is not None
    assert at.session_state["project"].name == "Recovered Name"
    # The message is carried across the post-open rerun and shown via st.info.
    messages = [m.value for m in at.info] + [m.value for m in at.success]
    assert any("autosave" in m for m in messages), messages


def test_import_existing_timings_and_audio_enters_editing(tmp_path):
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    tj = legacy / "timings.json"
    to_json(_timings(), tj)
    audio = _make_audio(legacy / "karaoke.mp3")
    dest = tmp_path / "imported_project"

    at = _fresh_app()
    at.text_input(key="import_timings").set_value(str(tj))
    at.text_input(key="import_audio").set_value(str(audio))
    at.text_input(key="import_dest").set_value(str(dest))
    at.button(key="import_btn").click().run()
    assert not at.exception, at.exception

    project = at.session_state["project"]
    assert project is not None
    assert (dest / P.MANIFEST_NAME).exists()
    assert tj.exists(), "the user's original timings file must survive import"
    assert "Karaoke video" in [s.value for s in at.subheader]


def test_saving_marks_the_project_clean(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    at.session_state["project"].name = "Edited"
    at.run()
    assert any("unsaved changes" in c.value for c in at.caption)

    at.button(key="save_project").click().run()
    assert not at.exception
    assert any("saved" in c.value and "unsaved" not in c.value for c in at.caption)
    assert P.load_project(project_dir).name == "Edited"


def test_missing_asset_is_surfaced_with_a_relink_control(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    proj = P.load_project(project_dir)
    asset = proj.asset_by_role("karaoke_audio")
    asset.resolve(project_dir).unlink()

    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    assert not at.exception
    assert any("Missing files" in w.value for w in at.warning)
    assert any(ti.key == f"relink_{asset.id}" for ti in at.text_input)


@pytest.mark.media
@pytest.mark.skipif(_ffmpeg_missing(), reason="ffmpeg/ffprobe not on PATH")
def test_rendering_a_video_from_an_opened_project(tmp_path):
    """Restyling an existing song must not require regenerating its audio."""
    project_dir = _existing_song_project(tmp_path)

    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    next(b for b in at.button if b.label == "Render video").click().run()
    assert not at.exception, at.exception
    assert [e.value for e in at.error] == []

    out = project_dir / P.EXPORTS_DIR / "karaoke.mp4"
    assert out.exists(), "video should land in the project's exports folder"
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True).stdout.strip())
    assert 3.5 < duration < 5.0
