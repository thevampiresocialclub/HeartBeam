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


def _lyrics_key(at) -> str:
    """The project lyric box carries a version suffix; find it by prefix."""
    return next(t.key for t in at.text_area if t.key.startswith("lyrics_edit_"))


def test_new_session_starts_with_no_project():
    at = _fresh_app()
    assert not at.exception
    assert at.session_state["project"] is None
    labels = [s.value for s in at.subheader]
    assert "Karaoke video" not in labels, "video controls need a song first"
    assert at.session_state["workflow_step"] == "separation"
    assert at.button(key="step_video").disabled


def test_repair_range_survives_scan_revision_and_is_applied_to_requested_passage(tmp_path, monkeypatch):
    from heartbeam import editor as ED, timing_review as T
    from tests.test_timing_review import pending
    root = tmp_path/'repair-draft'; root.mkdir()
    project, *_ = pending(root)
    T.approve_and_build(project, root, allow_incomplete=True, separate_tracks=True)
    P.save_project(project, root)
    monkeypatch.setattr(ED, 'timeline_component', lambda: lambda **kw: None)
    at = _fresh_app()
    at.text_input(key='open_project_path').set_value(str(root))
    at.button(key='open_project_btn').click().run()
    at.button(key='step_repair').click().run()
    next(w for w in at.number_input if w.label=='Start (ms)').set_value(100)
    next(w for w in at.number_input if w.label=='End (ms)').set_value(800)
    at.button(key=f'scan_music_{project.id}').click().run()
    assert not at.exception
    assert next(w for w in at.number_input if w.label=='Start (ms)').value == 100
    assert next(w for w in at.number_input if w.label=='End (ms)').value == 800
    next(b for b in at.button if b.label=='Apply repair').click().run()
    assert not at.exception
    repair = at.session_state['project'].music_repair.repairs[0]
    assert (repair.start_ms, repair.end_ms) == (100, 800)


def test_prepared_song_requires_review_and_explicit_build_before_video(tmp_path,monkeypatch):
    from heartbeam import editor as ED, timing_review as R
    from tests.test_timing_review import pending
    root=tmp_path/'review';root.mkdir()
    project,*_=pending(root);P.save_project(project,root)
    payload={}
    def component(**kwargs):
        payload.update(kwargs['data'])
        return None
    monkeypatch.setattr(ED,'timeline_component',lambda:component)
    at=_fresh_app()
    at.text_input(key='open_project_path').set_value(str(root))
    at.button(key='open_project_btn').click().run()
    assert not at.exception
    assert at.session_state['workflow_step']=='review'
    assert at.button(key='step_video').disabled
    assert not at.button(key='approve_timing_build').disabled
    assert payload['sources'][0]['id']=='original' and payload['mix'] is None
    assert not any(b.label=='Render video' for b in at.button)
    at.button(key='approve_timing_build').click().run()
    assert not at.exception
    assert at.session_state['workflow_step']=='video'
    assert R.approved(P.load_project(root))
    assert not any(b.label=='Render video' for b in at.button)
    assert at.button(key='step_export').disabled
    at.button(key='step_repair').click().run()
    assert at.session_state['workflow_step']=='repair'
    assert not at.button(key='step_export').disabled
    at.button(key=f'repair_to_export_{project.id}').click().run()
    assert at.session_state['workflow_step']=='export'
    assert any(b.label=='Render video' for b in at.button)
    at.button(key='step_review').click().run()
    for widget in at.text_input:
        assert widget.id in at.session_state, (widget.label, widget.id)
    p=at.session_state['project'];at.session_state['selected_word_id']=p.word_ids()[0]
    at.run()
    at.button(key='nudge_fwd').click().run()
    assert not at.exception
    assert at.session_state['workflow_step']=='review'
    assert not at.button(key='approve_timing_build').disabled
    assert at.button(key='step_video').disabled


def test_missing_first_word_can_select_repeat_and_continue_to_removal(tmp_path,monkeypatch):
    from heartbeam import editor as ED, timing_review as R
    from tests.test_timing_review import pending
    root=tmp_path/'partial';root.mkdir();p,*_=pending(root);line=p.lines[0]
    p.timing_edits[line.words[0].id]=P.WordTiming(reason='needs timing')
    p.alignment['phrases']={line.id:{'word_ids':[w.id for w in line.words], 'anchor':{'start_s':.1,'end_s':.9}}}
    P.save_project(p,root);payload={}
    def component(**kwargs):payload.update(kwargs['data'])
    monkeypatch.setattr(ED,'timeline_component',lambda:component)
    at=_fresh_app();at.text_input(key='open_project_path').set_value(str(root));at.button(key='open_project_btn').click().run()
    before=at.session_state['project'].to_dict()
    at.button(key=f'review_line_{line.id}').click().run()
    first=payload['lyric_navigation'];assert first['start_ms']==100 and first['word_id']==line.words[0].id
    at.button(key=f'review_line_{line.id}').click().run()
    assert payload['lyric_navigation']['id']!=first['id']
    assert at.session_state['project'].to_dict()==before
    assert not at.button(key='approve_timing_build').disabled
    at.button(key='approve_timing_build').click().run()
    assert not at.exception and at.session_state['workflow_step']=='video'
    saved=P.load_project(root);assert R.approved(saved) and saved.effective_timing(line.words[0].id).estimated
    assert not saved.raw_timing(line.words[0].id).resolved
    assert not any(saved.reviewed.values())


def test_online_search_keeps_draft_until_user_chooses_result(monkeypatch):
    from heartbeam import lyrics_lookup_ui
    candidate=dict(id=1,title='Song',artist='Artist',album='',duration=4.,lyrics='new lyrics',synced_lines=[])
    monkeypatch.setattr(lyrics_lookup_ui,'lookup',lambda *a,**k:dict(status='Found lyrics',candidates=[candidate]))
    at=_fresh_app()
    at.text_area(key='lyrics_text').set_value('my existing draft').run()
    before=at.session_state['lyrics_text']
    next(b for b in at.button if b.label == 'Find lyrics').click().run()
    assert not at.exception
    assert at.session_state['lyrics_text'] == before
    at.button(key='lookup_use_generate_empty').click().run()
    assert not at.exception
    assert at.session_state['lyrics_text'] == 'new lyrics'


def test_selected_phrase_bounds_use_shared_audition_without_editing_project(tmp_path):
    project_dir=_existing_song_project(tmp_path)
    at=_fresh_app()
    at.text_input(key='open_project_path').set_value(str(project_dir))
    at.button(key='open_project_btn').click().run()
    project=at.session_state['project'];line=project.lines[0]
    at.session_state['selected_word_id']=line.words[0].id
    at.selectbox(key='alignment_scope').set_value('Selected lines').run()
    at.checkbox(key=f'anchor_{line.id}').set_value(True).run()
    before=at.session_state['project'].to_dict()
    at.button(key='audition_phrase').click().run()
    assert not at.exception
    assert at.session_state['project'].to_dict() == before
    event=at.session_state[f'phrase_audition_{project.id}']
    assert event['start_ms'] == 500 and event['end_ms'] == 2500


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

    # The song resumes in video editing, then passes through Music Repair before export.
    assert at.session_state["workflow_step"] == "video"
    assert at.button(key="step_export").disabled
    at.button(key="step_repair").click().run()
    assert "Music repair" in [s.value for s in at.subheader]
    at.button(key=f"repair_to_export_{project.id}").click().run()
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


@pytest.mark.skipif(_ffmpeg_missing(), reason="needs a playable imported song")
def test_selection_arriving_with_a_nudge_targets_the_new_word(tmp_path, monkeypatch):
    from heartbeam import editor as ED
    project_dir = _existing_song_project(tmp_path)
    result = {}
    monkeypatch.setattr(ED, "timeline_component", lambda: lambda **kwargs: result)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    first, second = at.session_state["project"].word_ids()
    result["selection"] = {"word_id": first, "nonce": "first"}
    at.run()
    before = at.session_state["project"].to_dict()
    at.run()  # an unchanged selection must neither dirty nor edit the song
    assert at.session_state["project"].to_dict() == before
    result["selection"] = {"word_id": second, "nonce": "second"}
    at.button(key="nudge_fwd").click().run()
    assert not at.exception
    project = at.session_state["project"]
    assert project.effective_timing(first).start_ms == 500
    assert project.effective_timing(second).start_ms == 1510
    # Review navigation must win over the now-old persistent component value.
    project.original_alignment.pop(first)
    project.timing_edits[first] = P.WordTiming(reason="needs timing")
    at.button(key="next_untimed").click().run()
    assert at.session_state["selected_word_id"] == first
    at.run()
    assert at.session_state["selected_word_id"] == first


@pytest.mark.skipif(_ffmpeg_missing(), reason="needs a real playable imported song")
def test_link_cached_audition_tracks_through_the_gui(tmp_path):
    import numpy as np
    from heartbeam import audio_cache as AC

    project_dir = _existing_song_project(tmp_path)
    folder = tmp_path / "cached_run"
    AC.write_cache(folder, {role: np.zeros((32000, 2), dtype=np.float32)
                            for role in AC.ROLES}, sample_rate=8000,
                   source_sha256="fixture-source", settings={})
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    ids = at.session_state["project"].word_ids()
    next(t for t in at.text_input if t.label == "Audio cache folder").set_value(str(folder))
    next(b for b in at.button if b.label == "Link cached tracks").click().run()
    assert not at.exception, at.exception
    reopened = P.load_project(project_dir)
    assert reopened.word_ids() == ids
    assert all(reopened.asset_by_role(role) is not None
               for role in ("original_audio", "lead_stem", "clean_audio"))
    assert len(at.get("audio")) == 0, "the timing editor owns the only song transport"
    assert at.session_state["out_dir"] is None
    assert at.session_state["workflow_step"] == "video"
    assert not any(t.key == "lyrics_text" for t in at.text_area)
    assert not any(b.label == "Prepare audio and match lyrics" for b in at.button)

def test_finished_separation_saves_to_chosen_folder_and_enters_workstation(tmp_path):
    _existing_song_project(tmp_path)
    at = _fresh_app()
    at.session_state["out_dir"] = tmp_path / "yesterday"
    at.session_state["song_name"] = "Completed song"
    at.session_state["running"] = True
    at.session_state["status"] = {"progress": 1., "label": "Done", "done": True, "returncode": 0}
    at.run()
    assert not at.exception
    assert at.session_state["workflow_step"] == "separation"
    project = at.session_state["project"]
    original_ids = project.word_ids()
    original_timing = project.original_alignment.copy()
    assert at.button(key="save_and_edit")
    destination = tmp_path / "keep-my-song"
    next(t for t in at.text_input if t.label == "Save project folder").set_value(str(destination))
    at.button(key="save_and_edit").click().run()
    assert not at.exception
    assert at.session_state["workflow_step"] == "video"
    saved = P.load_project(destination)
    assert saved.word_ids() == original_ids
    assert saved.original_alignment == original_timing
    assert saved.asset_by_role("karaoke_audio").resolve(destination).is_file()
    assert any(s.value == "Video preview" for s in at.subheader)
    assert any(s.value == "Lyric controls" for s in at.subheader)
    assert not any(b.label == "Prepare audio and match lyrics" for b in at.button)
    assert len(at.get("audio")) == 0
    at.button(key="step_separation").click().run()
    assert at.session_state["workflow_step"] == "separation"
    assert at.session_state["project"].word_ids() == original_ids
    at.button(key="step_video").click().run()
    assert at.session_state["workflow_step"] == "video"
    at.button(key="close_project").click().run()


def test_preparation_without_mp3_saves_and_enters_timing_review(tmp_path):
    import numpy as np
    from heartbeam import audio_cache as AC, timing_review as R
    run=tmp_path/'prepared';run.mkdir()
    to_json(_timings(),run/'timings.json')
    (run/'timing-review-required.json').write_text('{"required":true}')
    AC.write_cache(run/'cache',{role:np.zeros((32000,2),dtype='float32') for role in AC.ROLES},
                   sample_rate=8000,source_sha256='fixture',settings={'mix_strategy':'replace','pending_timing_review':True})
    at=_fresh_app()
    at.session_state['out_dir']=run;at.session_state['running']=True
    at.session_state['status']={'progress':1.,'label':'Ready','done':True,'returncode':0}
    at.run()
    assert not at.exception
    assert not R.approved(at.session_state['project'])
    assert at.session_state['project'].asset_by_role('karaoke_audio') is None
    target=tmp_path/'saved'
    next(t for t in at.text_input if t.label=='Save project folder').set_value(str(target))
    at.button(key='save_and_edit').click().run()
    assert not at.exception
    assert at.session_state['workflow_step']=='review'
    saved=P.load_project(target)
    assert saved.asset_by_role('original_audio').resolve(target).is_file()
    assert not R.approved(saved) and at.button(key='step_video').disabled
    assert len(at.get("audio")) == 0
    at.button(key="step_separation").click().run()
    assert at.session_state["workflow_step"] == "separation"
    assert at.session_state["project"].word_ids() == saved.word_ids()
    assert at.button(key="step_video").disabled
    at.button(key="step_review").click().run()
    assert at.session_state["workflow_step"] == "review"
    at.button(key="close_project").click().run()


def test_failed_save_keeps_separation_result_and_does_not_enter_editor(tmp_path):
    root = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(root))
    at.button(key="open_project_btn").click().run()
    at.button(key="step_separation").click().run()
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    (occupied / "keep.txt").write_text("keep")
    shutil.copy2(root / P.MANIFEST_NAME, occupied / P.MANIFEST_NAME)
    next(t for t in at.text_input if t.label == "Save project folder").set_value(str(occupied))
    at.button(key="save_and_edit").click().run()
    assert not at.exception
    assert at.session_state["workflow_step"] == "separation"
    assert at.session_state["project_dir"] == root
    assert any("Could not save" in e.value for e in at.error)
    assert (occupied / "keep.txt").read_text() == "keep"
    at.button(key="close_project").click().run()


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
    assert at.session_state["workflow_step"] == "video"
    at.button(key="step_repair").click().run()
    at.button(key=f"repair_to_export_{project.id}").click().run()
    assert "Karaoke video" in [s.value for s in at.subheader]


@pytest.mark.parametrize("save_key", ["save_project", "workstation_save"])
def test_saving_marks_the_project_clean(tmp_path, save_key):
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    at.session_state["project"].name = "Edited"
    at.run()
    assert any("unsaved changes" in c.value for c in at.caption)

    at.button(key=save_key).click().run()
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

    project = at.session_state["project"]
    at.button(key="step_repair").click().run()
    at.button(key=f"repair_to_export_{project.id}").click().run()

    next(b for b in at.button if b.label == "Render video").click().run()
    assert not at.exception, at.exception
    assert [e.value for e in at.error] == []

    # P06 renders outside Streamlit's request so the editor remains usable and
    # cancellation can be processed. AppTest has no browser timer, so drive the
    # page while the real browser uses the status fragment's automatic timer.
    import time
    until = time.time() + 20
    outputs = []
    while time.time() < until and not outputs:
        time.sleep(.05); at.run()
        outputs = list((project_dir / P.EXPORTS_DIR).glob("rev-*/karaoke.mp4"))
    assert len(outputs) == 1
    out = outputs[0]
    assert (out.parent / "project-snapshot.json").exists()
    assert (out.parent / "timings.json").exists()
    assert out.exists(), "video should land in the project's exports folder"
    duration = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True).stdout.strip())
    assert 3.5 < duration < 5.0
    at.run()
    project = at.session_state["project"]
    assert f"export_job_{project.id}" not in at.session_state
    assert at.session_state[f"last_video_{project.id}"][1] == str(out)
    assert next(b for b in at.button if b.label == "Render video").disabled is False
    # A post-export edit still works and can be saved without regenerating audio.
    at.session_state["project"].name = "After export"
    at.button(key="save_project").click().run()
    assert not at.exception
    assert P.load_project(project_dir).name == "After export"


def test_p05_appearance_preset_override_save_reopen(tmp_path, monkeypatch):
    from heartbeam import editor as ED, presentation as S
    from heartbeam.vocal_mix import mix_key
    project_dir = _existing_song_project(tmp_path)
    result = {}
    monkeypatch.setattr(ED, "timeline_component", lambda: lambda **kw: result)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    p = at.session_state["project"]
    original = p.original_alignment.copy(); audio_key = mix_key(p)
    result["selection"] = {"word_id": p.word_ids()[0], "nonce": "p05-select"}
    at.run()
    next(n for n in at.number_input if n.label == "Lyric font size").set_value(90.)
    next(n for n in at.number_input if n.label == "Letter spacing (kerning)").set_value(4.)
    next(n for n in at.number_input if n.label == "Line height").set_value(1.8)
    next(t for t in at.text_input if t.label == "Sung colour code").set_value("#55CCAA")
    next(b for b in at.button if b.label == "Apply lyric appearance").click().run()
    assert not at.exception and not at.error
    p = at.session_state["project"]
    assert S.resolved_style(p)["font"]["size_px"] == 90
    assert S.resolved_style(p)["font"]["letter_spacing_px"] == 4
    assert S.resolved_style(p)["font"]["line_height"] == 1.8
    assert S.resolved_style(p)["colour"]["highlight"] == "#55CCAA"
    next(t for t in at.text_input if t.label == "Preset name").set_value("Mint song")
    next(b for b in at.button if b.label == "Save named style preset").click().run()
    next(s for s in at.selectbox if s.label == "Style scope").select("Selected lyric line").run()
    next(n for n in at.number_input if n.label == "Outline thickness").set_value(0.)
    next(b for b in at.button if b.label == "Apply lyric appearance").click().run()
    assert not at.exception and not at.error
    p = at.session_state["project"]
    assert p.original_alignment == original and mix_key(p) == audio_key
    assert p.presentation.line_overrides[p.lines[0].id] == {"box": {"outline_px": 0.}}
    appearance = p.presentation
    at.button(key="save_project").click().run()
    at.button(key="close_project").click().run()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    assert not at.exception
    p = at.session_state["project"]
    assert p.presentation == appearance
    assert S.resolved_style(p, p.lines[0].id)["box"]["outline_px"] == 0
    assert "Mint song" in p.presentation.presets
    at.button(key="close_project").click().run()


def test_p05_invalid_colour_does_not_change_project(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()
    before = at.session_state["project"].to_dict()
    next(t for t in at.text_input if t.label == "Unsung colour code").set_value("bad")
    next(b for b in at.button if b.label == "Apply lyric appearance").click().run()
    assert not at.exception
    assert any("#RRGGBB" in e.value for e in at.error)
    assert at.session_state["project"].to_dict() == before
    at.button(key="close_project").click().run()


# ---------------------------------------------------------------------------
# P02: lyrics text box and in-project editing
# ---------------------------------------------------------------------------


def test_lyrics_can_be_pasted_without_choosing_a_file():
    """P02.1 acceptance: no .txt required to prepare a song."""
    at = _fresh_app()
    assert not at.exception
    box = at.text_area(key="lyrics_text")
    assert box is not None, "there must be a lyrics text area"

    # Nothing pasted: generation stays disabled and the empty state explains why.
    generate = next(b for b in at.button if b.label == "Prepare audio and match lyrics")
    assert generate.disabled
    assert any("No lyrics yet" in c.value for c in at.caption)

    box.set_value("alpha bravo\ncharlie delta\n").run()
    assert any("2 sung lines, 4 words" in c.value for c in at.caption)


def test_editing_project_lyrics_preserves_timing(tmp_path):
    """P02.2 acceptance, through the UI: a typo fix must not cost timing."""
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    project = at.session_state["project"]
    before_ids = project.word_ids()
    first_id = before_ids[0]
    before_start = project.effective_timing(first_id).start_ms

    at.text_area(key=_lyrics_key(at)).set_value("Hello there!\n").run()
    at.button(key="apply_lyrics").click().run()
    assert not at.exception, at.exception

    edited = at.session_state["project"]
    assert edited.word_ids() == before_ids, "punctuation is not a new word"
    assert edited.effective_timing(first_id).start_ms == before_start


def test_adding_a_word_gets_labelled_estimated_timing(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    project = at.session_state["project"]
    at.text_area(key=_lyrics_key(at)).set_value("hello right there\n").run()
    at.button(key="apply_lyrics").click().run()
    assert not at.exception

    edited = at.session_state["project"]
    estimated = {edited.find_word(wid).text for wid in edited.estimated_word_ids()}
    assert estimated == {"right"}
    assert any('estimated timing' in c.value for c in at.caption)


def test_undo_restores_the_previous_lyrics(tmp_path):
    project_dir = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key="open_project_path").set_value(str(project_dir))
    at.button(key="open_project_btn").click().run()

    project = at.session_state["project"]
    before_ids = project.word_ids()
    at.text_area(key=_lyrics_key(at)).set_value("hello\n").run()
    at.button(key="apply_lyrics").click().run()
    assert at.session_state["project"].word_ids() != before_ids

    at.button(key="undo_lyrics").click().run()
    assert not at.exception
    assert at.session_state["project"].word_ids() == before_ids


def test_vocal_commands_save_reopen_and_export_current_mix(tmp_path, monkeypatch):
    import numpy as np
    from heartbeam import audio_cache as AC, editor_media as EM, editor as ED
    project_dir = _existing_song_project(tmp_path)
    cache = tmp_path / 'cache'
    samples = np.sin(np.arange(32000) * .12).astype(np.float32)[:, None].repeat(2, axis=1) * .2
    arrays = {role: samples.copy() for role in AC.ROLES}
    arrays['clean'] *= .1
    AC.write_cache(cache, arrays, sample_rate=8000, source_sha256='test-original', settings={'mix_strategy':'subtract'})
    p = P.load_project(project_dir); EM.attach_cached_audio(p, project_dir, cache); P.save_project(p, project_dir)
    result = {}
    monkeypatch.setattr(ED, 'timeline_component', lambda: lambda **kw: result)
    at = _fresh_app()
    at.text_input(key='open_project_path').set_value(str(project_dir))
    at.button(key='open_project_btn').click().run()
    for i, value in enumerate([.2, 0., 1.]):
        p = at.session_state['project']
        result['command'] = {'id':f'vocal-{i}', 'base_revision':p.revision, 'kind':'vocal',
                             'payload':{'start_ms':i*1000,'end_ms':(i+1)*1000,'value':value}}
        at.run()
        assert not at.exception
    at.button(key='save_project').click().run()
    at.button(key='close_project').click().run()
    at.text_input(key='open_project_path').set_value(str(project_dir))
    at.button(key='open_project_btn').click().run()
    p = at.session_state['project']
    assert [r.value for r in p.vocal_mix.regions] == [.2,0.,1.]
    next(b for b in at.button if b.label=='Prepare final mix for audition and download').click().run()
    assert not at.exception and not at.error
    from heartbeam.vocal_mix import mix_key
    audio_key, path = at.session_state[f'final_mix_{p.id}']
    assert audio_key == mix_key(p) and Path(path).exists()


def test_second_gui_opens_readonly_and_does_not_steal_the_writer(tmp_path):
    from heartbeam.project_lock import WriterLease
    root = _existing_song_project(tmp_path)
    with WriterLease(root):
        at = _fresh_app()
        at.text_input(key='open_project_path').set_value(str(root))
        at.button(key='open_project_btn').click().run()
        assert not at.exception
        assert at.session_state['project_readonly'] is True
        assert at.button(key='save_project').disabled
        assert not any(t.label=='Edit lyrics' for t in at.text_area)
