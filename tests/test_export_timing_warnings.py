"""Export follows the preview despite missing/estimated/overlapping word timing."""
import copy
import json
from pathlib import Path

import pytest

from heartbeam import project as P, presentation as S, export_jobs as J, editor as E
from heartbeam.project_preview import current_timings
from heartbeam.timing_review import approved
from tests.test_export_jobs import _audio, _wait


def uncertain_song():
    p = P.Project('warning-export', 'Export timing warnings')
    p.lines = [P.Line('a', [P.Word('a0', 'Sing'), P.Word('a1', 'this'), P.Word('a2', 'line')]),
               P.Line('b', [P.Word('b0', 'Keep'), P.Word('b1', 'singing')]),
               P.Line('c', [P.Word('c0', 'Carry'), P.Word('c1', 'on')]),
               P.Line('plain', [P.Word(f'u{i}', w) for i, w in enumerate(
                   'These eight words stay visible without individual wordtimes'.split())],
                   display_start_ms=5000, display_end_ms=7500)]
    p.original_alignment = {wid: P.WordTiming(start, end, .8) for wid, start, end in [
        ('a0', 500, 1200), ('a2', 1000, 1800), ('b0', 2100, 3000),
        ('b1', 2800, 3500), ('c0', 3900, 4500), ('c1', 4200, 4800)]}
    p.alignment['review'] = {'required': True}
    S.apply_style(p, {'video': {'resolution': '320x180'}})
    return p


def test_preflight_warns_for_the_reported_eight_missing_and_three_conflicts(tmp_path):
    p = uncertain_song(); before = copy.deepcopy(p.to_dict())
    assert len(p.unresolved_words()) == 8 and len(E.timing_conflicts(p)) == 3
    assert p.estimated_word_ids() == ['a1']
    audio = _audio(tmp_path/'audio.wav')
    _, warnings = J.preflight(p, tmp_path, audio)
    assert any('8 word(s) still have no timing' in w for w in warnings)
    assert any('3 timing conflict(s)' in w for w in warnings)
    assert any('estimated timing' in w for w in warnings)
    assert any('not been approved' in w for w in warnings)
    assert S.compile_project(p, 8000, draft=True)['ass'] == S.compile_project(p, 8000, allow_timing_issues=True)['ass']
    assert p.to_dict() == before and not approved(p)
    with pytest.raises(P.ProjectError, match='untimed'):
        current_timings(p, 8000)
    with pytest.raises(P.ProjectError, match='untimed'):
        J.preflight(p, tmp_path, audio, allow_timing_issues=False)


@pytest.mark.media
@pytest.mark.parametrize('selection', [None, (300, 7800)])
def test_full_and_passage_video_render_with_warnings_and_plain_text(tmp_path, selection):
    p = uncertain_song(); before = copy.deepcopy(p.to_dict())
    audio = _audio(tmp_path/'audio.wav')
    done = _wait(J.start(p, tmp_path, audio, selection).id)
    assert done.status == 'complete', done.error
    folder = Path(done.output_path).parent
    manifest = json.loads((folder/'export-manifest.json').read_text())
    assert manifest['allow_timing_issues'] and manifest['warnings'] == done.warnings
    assert any('8 word(s)' in w for w in done.warnings) and any('3 timing conflict(s)' in w for w in done.warnings)
    ass = (folder/'lyrics.ass').read_text()
    assert 'wordtimes' in ass and '\\kt' in ass and 'this' in ass
    snapshot = json.loads((folder/'project-snapshot.json').read_text())
    assert len(snapshot['lines'][-1]['words']) == 8
    assert (folder/'timings.json').is_file() and Path(done.output_path).stat().st_size > 1000
    assert p.to_dict() == before and not approved(p)


def test_unanchored_lines_warn_and_passages_without_lyrics_can_render(tmp_path):
    p = uncertain_song(); p.lines = p.lines[-1:]
    p.lines[0].display_start_ms = p.lines[0].display_end_ms = None
    audio = _audio(tmp_path/'audio.wav')
    _, warnings = J.preflight(p, tmp_path, audio)
    assert any('will not appear' in w for w in warnings)
    _, warnings = J.preflight(p, tmp_path, audio, (2000, 4000))
    assert any('no usable lyric window' in w for w in warnings)


def test_plain_phrase_window_shifts_with_a_passage_without_estimating_words():
    p = uncertain_song(); p.lines = p.lines[-1:]; line = p.lines[0]
    line.display_start_ms = line.display_end_ms = None
    p.alignment['estimate_missing_words'] = False
    p.alignment['phrases'] = {line.id: {'word_ids': p.word_ids(), 'anchor': {'start_s': 5., 'end_s': 7.5}}}
    clip = J._trim_snapshot(p, 4500, 7800, allow_timing_issues=True)
    compiled = S.compile_project(clip, 3300, allow_timing_issues=True)
    assert compiled['lines'][0]['seek_ms'] == 500
    assert len(clip.unresolved_words()) == 8 and 'wordtimes' in compiled['ass']


def test_warn_only_timing_does_not_disable_media_or_font_validation(tmp_path):
    p = uncertain_song(); audio = _audio(tmp_path/'audio.wav')
    with pytest.raises(P.ProjectError, match='karaoke audio'):
        J.preflight(p, tmp_path, tmp_path/'missing.wav')
    p.lines[0].words[0].display_text = '\U0010ffff'
    with pytest.raises(P.ProjectError, match='lacks characters'):
        J.preflight(p, tmp_path, audio)
