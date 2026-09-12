import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from heartbeam import paths, project as P
from heartbeam.export_names import default_video_filename, video_filename
from tests.test_export_jobs import _audio, _wait
from tests.test_presentation import song


def test_sessions_and_projects_follow_user_data_root(tmp_path, monkeypatch):
    monkeypatch.setenv('HEARTBEAM_DATA_ROOT', str(tmp_path / 'User songs'))
    one = paths.new_session('CON')
    two = paths.new_session('CON')
    assert one != two and one.is_dir() and two.is_dir()
    assert one.parent == tmp_path / 'User songs' / 'Sessions'
    assert one.name.startswith('_CON-')
    assert paths.projects_dir() == tmp_path / 'User songs' / 'Projects'


@pytest.mark.parametrize('value', ['', '../escape', r'C:\movie.mp4', 'folder/movie',
    'CON.mp4', 'NUL.txt.mp4', 'bad:name', '..', 'a' * 190, 'trail.'])
def test_custom_export_rejects_paths_and_invalid_filenames(value):
    with pytest.raises(ValueError):
        video_filename(value)


def test_default_name_uses_original_input_and_reads_old_projects(tmp_path):
    p = song()
    p.provenance.settings['input_filename'] = r'C:\Music\Artist - My song.mp3'
    assert default_video_filename(p, tmp_path) == 'Artist - My song_karaoke.mp4'
    p.provenance.settings.clear()
    p.imported_timings_path = 'legacy.json'
    (tmp_path / 'legacy.json').write_text(json.dumps({'source': {'audio_path': '/music/Original title.mp3'}}))
    assert default_video_filename(p, tmp_path) == 'Original title_karaoke.mp4'
    assert video_filename('  Café karaoke  ') == 'Café karaoke.mp4'


def test_replacing_lyric_upload_loads_new_text_but_keeps_later_edits():
    def app():
        import io
        import streamlit as st
        from heartbeam.gui import _lyrics_input
        raw = st.session_state.get('test_upload')
        _lyrics_input(io.BytesIO(raw) if raw is not None else None)
    at = AppTest.from_function(app).run()
    at.session_state['test_upload'] = b'first file'
    at.run()
    assert at.text_area(key='lyrics_text').value == 'first file'
    at.text_area(key='lyrics_text').set_value('edited first file').run()
    assert at.text_area(key='lyrics_text').value == 'edited first file'
    at.session_state['test_upload'] = b'second file'
    at.run()
    assert at.text_area(key='lyrics_text').value == 'second file'
    at.session_state['test_upload'] = None
    at.run()
    assert at.text_area(key='lyrics_text').value == 'second file'


def test_custom_export_name_survives_editing_on_another_page(tmp_path):
    from tests.test_gui_project_workflow import _fresh_app, _existing_song_project
    root = _existing_song_project(tmp_path)
    at = _fresh_app()
    at.text_input(key='open_project_path').set_value(str(root))
    at.button(key='open_project_btn').click().run()
    at.button(key='step_export').click().run()
    name = next(t for t in at.text_input if t.label == 'Video filename')
    name.set_value('My rehearsal mix').run()
    at.button(key='step_video').click().run()
    at.button(key='step_export').click().run()
    assert next(t for t in at.text_input if t.label == 'Video filename').value == 'My rehearsal mix'
    at.button(key='close_project').click().run()


@pytest.mark.media
def test_named_video_survives_export_recovery_and_project_reopen(tmp_path):
    from heartbeam import export_jobs as J, presentation as S
    from heartbeam.gui import _latest_project_video
    p = song(); p.id = P.new_id('named-video')
    S.apply_style(p, {'video': {'resolution': '320x180'}})
    audio = _audio(tmp_path / 'audio.wav')
    done = _wait(J.start(p, tmp_path, audio, output_name='My custom song').id)
    assert done.status == 'complete', done.error
    output = Path(done.output_path)
    assert output.name == 'My custom song.mp4' and output.is_file()
    assert J.recover(tmp_path)[0]['output_path'] == str(output)
    assert _latest_project_video(p, tmp_path) == (p.revision, str(output))
