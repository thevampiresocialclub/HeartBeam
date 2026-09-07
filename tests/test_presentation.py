"""P05 contracts: one compiler, durable presentation, and audio independence."""
import copy
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from heartbeam import project as P, presentation as S, presentation_fonts as F
from heartbeam.commands import History, CommandError


def song():
    p = P.Project(id="p05-original", name="Bright stars")
    for i, text in enumerate(["Bright {stars} guide us", "Café Ω Привет \\N"]):
        line = P.Line(f"line{i}", [P.Word(f"w{i}-{j}", t) for j, t in enumerate(text.split())],
                      display_start_ms=i * 4000, display_end_ms=(i + 1) * 4000)
        p.lines.append(line)
        for j, word in enumerate(line.words):
            p.original_alignment[word.id] = P.WordTiming(i * 4000 + 500 + j * 700, i * 4000 + 1100 + j * 700, .99)
    return p


def test_defaults_and_zero_override_inherit_reset_undo():
    p, h = song(), History()
    h.execute(p, lambda q: S.apply_style(q, {"font": {"size_px": 88}, "box": {"outline_px": 8}}))
    h.execute(p, lambda q: S.apply_style(q, {"box": {"outline_px": 0}, "font": {"bold": False}}, ["line0"]))
    assert S.resolved_style(p, "line0")["box"]["outline_px"] == 0
    assert S.resolved_style(p, "line0")["font"] == {"family": "Noto Sans", "size_px": 88, "bold": False, "italic": False}
    h.execute(p, lambda q: S.reset_lines(q, ["line0"]))
    assert S.resolved_style(p, "line0")["box"]["outline_px"] == 8
    h.undo(p)
    assert S.resolved_style(p, "line0")["box"]["outline_px"] == 0


def test_colour_exception_does_not_freeze_song_font_or_placement():
    p = song()
    S.apply_style(p, {"colour": {"highlight": "#ABCDEF"}}, ["line0"])
    S.apply_style(p, {"font": {"size_px": 96}, "box": {"x": 200}})
    assert S.resolved_style(p, "line0")["font"]["size_px"] == 96
    assert S.resolved_style(p, "line0")["box"]["x"] == 200
    assert S.resolved_style(p, "line0")["colour"]["highlight"] == "#ABCDEF"


def test_line_styles_follow_split_and_merge_membership_with_undo():
    from heartbeam.lyrics import apply_lyrics_edit
    p = song(); p.lines = p.lines[:1]
    S.apply_style(p, {"colour": {"highlight": "#ABCDEF"}, "box": {"outline_px": 0}}, ["line0"])
    h = History(); h.execute(p, lambda q: apply_lyrics_edit(q, "Bright {stars}\nguide us"))
    assert p.lines[0].id == "line0"
    assert len({line.id for line in p.lines}) == 2
    for line in p.lines:
        assert S.resolved_style(p, line.id)["colour"]["highlight"] == "#ABCDEF"
    S.apply_style(p, {"font": {"size_px": 120}}, [p.lines[1].id])
    result = h.execute(p, lambda q: apply_lyrics_edit(q, "Bright {stars} guide us"))
    assert result.presentation_notices and p.lines[0].id == "line0"
    h.undo(p)
    assert len(p.lines) == 2 and S.resolved_style(p, p.lines[1].id)["font"]["size_px"] == 120


def test_margin_placement_has_explicit_reproducible_coordinates():
    p = song()
    S.apply_style(p, S.inside_margins(1920, 1080, "bottom right", 100, 90))
    box = S.resolved_style(p)["box"]
    assert (box["x"], box["y"], box["width_px"]) == (1820, 990, 1720)


@pytest.mark.parametrize("patch", [{"box": {"x": float('nan')}}, {"box": {"outline_px": -1}},
    {"font": {"family": r"bad\fnInjected"}}, {"font": {"bold": 0}}, {"colour": {"primary": "red"}},
    {"video": {"resolution": "1920x720"}}, {"box": {"anchor": "oops"}}, {"other": {}},
    {"highlight": {"mode": "active-only"}}, {"box": {"x": None}}])
def test_invalid_command_is_atomic(patch):
    p = song(); before = p.to_dict()
    with pytest.raises((P.ProjectError, ValueError)):
        History().execute(p, lambda q: S.apply_style(q, patch))
    assert p.to_dict() == before


def test_placement_command_scope_revision_and_undo():
    p, h = song(), History()
    before = copy.deepcopy(p.original_alignment)
    data = {"scope": "lines", "line_ids": ["line0"], "x": 340, "y": 120}
    revision = p.revision
    h.execute(p, lambda q: S.placement_command(q, data), command_id="drag1", base_revision=revision)
    assert p.revision == revision + 1
    assert S.resolved_style(p, "line0")["box"]["y"] == 120
    assert S.resolved_style(p, "line1")["box"]["y"] == 1000
    with pytest.raises(CommandError):
        h.execute(p, lambda q: S.placement_command(q, data), command_id="drag1", base_revision=revision)
    h.undo(p)
    assert S.resolved_style(p, "line0")["box"]["y"] == 1000
    assert p.original_alignment == before


def test_breaks_unicode_literals_and_display_window_are_compiled():
    p = song()
    S.set_line_breaks(p, "line0", "Bright {stars}\nguide us")
    text = S.compile_project(p, 8000)["ass"]
    assert r"\{stars\}" in text and "Café" in text and "Привет" in text
    assert "\\\u2060N" in text  # literal slash + N, not a forced break
    assert r"\N{\k10}{\k60}guide" in text
    assert "Dialogue: 0,0:00:00.00,0:00:04.00,Line0" in text
    assert r"{\k50}{\k60}Bright" in text  # unsung lead-in follows display window


def test_word_and_sweep_keep_sung_colour_and_absolute_gap_timing():
    p = song(); word = S.compile_project(p, 8000)["ass"]
    S.apply_style(p, {"highlight": {"mode": "sweep"}}, ["line1"])
    swept = S.compile_project(p, 8000)["ass"]
    assert r"{\k60}Café" in word
    assert r"{\kf60}Café" in swept
    assert r"{\k10}{\kf60}Ω" in swept
    assert "&H0000D7FF&,&H00FFFFFF&" in swept
    assert r"{\k60}Bright" in swept


def test_automatic_display_lead_hold_and_upcoming_slot_do_not_shift_audio_timing():
    p = song()
    before = copy.deepcopy(p.original_alignment)
    S.set_display_settings(p, {"automatic": True, "advance_ms": 300,
                               "hold_ms": 400, "show_upcoming": True,
                               "upcoming_offset_y": -160})
    compiled = S.compile_project(p, 8000)
    # First sung word is 500ms, so the first line appears at 200ms. The first
    # line's final word ends at 3200ms. The stack remains until the next line's
    # 4200ms reading boundary, avoiding a blank gap between lyric groups.
    assert "Dialogue: 0,0:00:00.20,0:00:04.20,Line0" in compiled["ass"]
    # The next line appears in its second slot only until its current event
    # starts at 4.2s, so a line never occupies both roles simultaneously.
    assert r"\pos(960,840)" in compiled["ass"]
    upcoming = [row for row in compiled["ass"].splitlines()
                if row.startswith("Dialogue") and "Café" in row]
    assert len(upcoming) == 2
    assert any("0:00:00.20,0:00:04.20" in row for row in upcoming)
    assert any("0:00:04.20,0:00:07.60" in row for row in upcoming)
    assert p.original_alignment == before


def test_display_settings_roundtrip_and_reject_invalid_values(tmp_path):
    p = song()
    S.set_display_settings(p, {"automatic": True, "advance_ms": 1250,
                               "hold_ms": 750, "show_upcoming": False})
    P.save_project(p, tmp_path)
    assert S.display_settings(P.load_project(tmp_path)) == S.display_settings(p)
    with pytest.raises(P.ProjectError, match="display setting"):
        S.set_display_settings(p, {"advance_ms": -1})


def test_adjacent_automatic_windows_share_a_boundary_without_cutting_words():
    p = song()
    S.set_display_settings(p, {"automatic": True, "advance_ms": 1200,
                               "hold_ms": 500, "show_upcoming": True})
    compiled = S.compile_project(p, 8000)
    rows = [row for row in compiled["ass"].splitlines() if row.startswith("Dialogue")]
    current0 = next(row for row in rows if ",Line0," in row and "Bright" in row)
    current1 = next(row for row in rows if ",Line1," in row and r"{\k" in row)
    assert "0:00:00.00,0:00:03.30" in current0
    assert "0:00:03.30,0:00:07.70" in current1
    assert any("shortened" in warning for warning in compiled["warnings"])
    assert p.effective_timing("w0-3").end_ms == 3200
    assert p.effective_timing("w1-0").start_ms == 4500


@pytest.mark.parametrize("visible", [2, 3, 4])
def test_two_to_four_line_stack_has_exact_slots_and_no_boundary_duplicates(visible):
    p = P.Project(id="stack", name="Line stack")
    for index in range(5):
        word = P.Word(f"stack-{index}", f"Row{index + 1}")
        p.lines.append(P.Line(f"stack-line-{index}", [word]))
        p.original_alignment[word.id] = P.WordTiming(1000 + index * 2000, 1600 + index * 2000)
    S.set_display_settings(p, {"automatic": True, "advance_ms": 500,
        "hold_ms": 200, "visible_lines": visible, "upcoming_offset_y": -150})
    compiled = S.compile_project(p, 10000)
    first_window = [row for row in compiled["ass"].splitlines()
                    if row.startswith("Dialogue") and "0:00:00.50,0:00:02.50" in row]
    assert len(first_window) == visible
    for distance in range(1, visible):
        assert f"\\pos(960,{1000 - 150 * distance})" in first_window[distance]
        assert r"\1c&H00FFFFFF&" in first_window[distance]
    # At the next current boundary Row2 has one event ending and one beginning.
    row2 = [row for row in compiled["ass"].splitlines() if row.startswith("Dialogue") and "Row2" in row]
    assert sum("0:00:02.50" in row for row in row2) == 2


def test_line_stack_rejects_values_outside_two_to_four():
    p = song()
    for value in (1, 5, 2.5, True):
        with pytest.raises(P.ProjectError, match="2, 3 or 4"):
            S.set_display_settings(p, {"visible_lines": value})


def test_alignment_independent_of_box_anchor_and_scale():
    p = song()
    S.apply_style(p, {"box": {"anchor": "top left", "x": 200, "y": 100, "width_px": 600, "alignment": "right"}})
    assert r"\pos(800,100)" in S.compile_project(p, 8000)["ass"]
    original = S.compile_project(p, 8000)["ass"]
    for resolution in ("1280x720", "1920x1080", "3840x2160"):
        S.apply_style(p, {"video": {"resolution": resolution}})
        assert S.compile_project(p, 8000)["ass"] == original


def test_overflow_warns_without_shrinking_and_wrong_break_text_rejected():
    p = song()
    S.apply_style(p, {"box": {"width_px": 80}, "font": {"size_px": 100}})
    compiled = S.compile_project(p, 8000)
    assert any("overflow" in item for item in compiled["warnings"])
    assert "Noto Sans,100," in compiled["ass"]
    with pytest.raises(P.ProjectError, match="same words"):
        S.set_line_breaks(p, "line0", "Bright changed stars")


def test_presets_have_no_song_media_or_timing_and_preserve_exceptions(tmp_path):
    p = song()
    S.apply_style(p, {"box": {"y": 800}, "colour": {"highlight": "#33FFAA"}})
    preset = S.preset_document("Mint", S.resolved_style(p))
    assert not ({"video", "assets", "timing", "line_overrides"} & set(preset["defaults"]))
    S.apply_style(p, {"box": {"outline_px": 0}}, ["line0"])
    h = History(); h.execute(p, lambda q: S.apply_preset(q, preset))
    P.save_project(p, tmp_path)
    reopened = P.load_project(tmp_path)
    assert reopened.presentation == p.presentation
    assert S.compile_project(reopened, 8000, tmp_path)["ass"] == S.compile_project(p, 8000, tmp_path)["ass"]
    assert reopened.presentation.line_overrides["line0"]["box"]["outline_px"] == 0
    fresh = song(); S.apply_preset(fresh, preset)
    assert S.resolved_style(fresh)["box"]["y"] == 800
    h.undo(p); assert not p.presentation.presets


def test_untrusted_preset_cannot_smuggle_media_or_timing():
    for extra in ({"video": {"resolution": "1280x720"}}, {"background": {"kind": "image", "value": "C:/private.png"}}, {"timing": {}}):
        data = {"format": "heartbeam-style", "version": 1, "name": "bad", "defaults": extra}
        with pytest.raises(P.ProjectError):
            S.read_preset(data)


def test_audio_cache_key_and_timings_do_not_change_with_style_or_wrapping():
    from heartbeam.vocal_mix import mix_key, timing_hash
    p = song(); audio, timing = mix_key(p), timing_hash(p)
    S.apply_style(p, {"box": {"outline_px": 0}, "font": {"italic": True}})
    S.set_line_breaks(p, "line0", "Bright\n{stars} guide us")
    p.lines[0].words[0].display_text = "BRIGHT"
    assert mix_key(p) == audio
    assert timing_hash(p) == timing


def test_missing_fonts_warn_and_same_concrete_fallback_is_used():
    p = song(); S.apply_style(p, {"font": {"family": "Missing Fixture Font", "italic": True}})
    result = S.compile_project(p, 8000)
    assert any("Missing or changed font" in warning for warning in result["warnings"])
    assert "Noto Sans,72" in result["ass"]
    assert F.VENDOR / "NotoSans-BoldItalic.ttf" in result["fonts"]


def test_explicitly_imported_noto_face_is_used_without_duplicate_family(tmp_path):
    p = song()
    F.import_fonts(p, tmp_path, [F.VENDOR / "NotoSans-Regular.ttf"])
    S.apply_style(p, {"font": {"bold": False}})
    result = S.compile_project(p, 8000, tmp_path)
    asset = next(a for a in p.assets if a.role == "font")
    assert result["fonts"] == [asset.resolve(tmp_path)]
    assert result["fallback_font"] == asset.resolve(tmp_path)


def test_font_copy_relink_and_missing_glyphs(tmp_path):
    from fontTools.ttLib import TTFont
    source = tmp_path / "fixture.ttf"
    with TTFont(F.VENDOR / "NotoSans-Regular.ttf") as font:
        for record in font["name"].names:
            if record.nameID in (1, 4, 6, 16):
                record.string = "HeartBeam Fixture".encode(record.getEncoding())
        font.save(source)
    p = song(); F.import_fonts(p, tmp_path, [source])
    S.apply_style(p, {"font": {"family": "HeartBeam Fixture", "bold": False}})
    compiled = S.compile_project(p, 8000, tmp_path)
    assert not compiled["warnings"]
    asset = next(a for a in p.assets if a.role == "font")
    assert asset.resolve(tmp_path) in compiled["fonts"] and not asset.external
    asset.resolve(tmp_path).unlink()
    assert any("Missing or changed" in w for w in S.compile_project(p, 8000, tmp_path)["warnings"])
    F.import_fonts(p, tmp_path, [source])
    assert not S.compile_project(p, 8000, tmp_path)["warnings"]
    p.lines[0].words[0].display_text = "漢"
    assert any("lacks characters" in w for w in S.compile_project(p, 8000, tmp_path, draft=True)["warnings"])
    with pytest.raises(P.ProjectError, match="lacks characters"):
        S.compile_project(p, 8000, tmp_path)


def test_background_assets_and_legacy_style_import(tmp_path):
    from heartbeam.style import Style
    source = tmp_path / "background.png"; source.write_bytes(b"image fixture")
    p = song(); old = Style(); old.video.resolution = "1280x720"
    old.font.size_px = 48; old.box.outline_px = 2
    old.background.kind, old.background.value = "image", str(source)
    S.import_legacy_style(p, tmp_path, old)
    assert S.resolved_style(p)["font"]["size_px"] == 72
    assert S.resolved_style(p)["box"]["outline_px"] == 3
    asset = next(a for a in p.assets if a.role == "background")
    assert S.background(p, tmp_path)[0]["value"] == str(asset.resolve(tmp_path))
    asset.resolve(tmp_path).unlink()
    assert S.background(p, tmp_path)[1]
    with pytest.raises(P.ProjectError, match="Background"):
        S.background(p, tmp_path, strict=True)


@pytest.mark.media
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
@pytest.mark.parametrize("resolution", ["1280x720", "1920x1080", "3840x2160"])
def test_native_placement_scales_uniformly(tmp_path, resolution):
    """Measure rendered ink bounds, not just ASS text or UI approximations."""
    from PIL import Image
    import numpy as np
    from heartbeam.render import _escape_path_for_ass_filter
    p = song(); p.lines = p.lines[:1]
    S.apply_style(p, {"box": {"anchor": "top left", "x": 300, "y": 200, "alignment": "left", "outline_px": 0, "shadow_px": 0},
                      "font": {"size_px": 100}, "colour": {"primary": "#FFFFFF", "highlight": "#FFFFFF"}})
    ass = tmp_path / "proof.ass"; ass.write_text(S.compile_project(p, 8000)["ass"], encoding="utf-8")
    image = tmp_path / "proof.png"
    vf = f"ass='{_escape_path_for_ass_filter(ass)}':fontsdir='{_escape_path_for_ass_filter(F.VENDOR.resolve())}'"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={resolution}:d=1",
                    "-vf", vf, "-frames:v", "1", "-y", str(image)], capture_output=True, check=True)
    pixels = np.asarray(Image.open(image).convert("RGB"))
    ys, xs = np.where(pixels.max(axis=2) > 150)
    scale = int(resolution.split("x")[0]) / 1920
    # Noto's left bearing and top ascender offset are stable design metrics.
    assert 300 <= xs.min() / scale <= 313
    assert 210 <= ys.min() / scale <= 250
    assert 500 < (xs.max() - xs.min()) / scale < 1200


@pytest.mark.media
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_project_export_handles_quoted_windows_folder_names(tmp_path):
    import numpy as np
    import soundfile as sf
    root = tmp_path / "Artist's [live], mix"; root.mkdir()
    audio = root / "audio.wav"
    sf.write(audio, np.sin(np.arange(32000) * .2).astype(np.float32) * .1, 8000)
    p = song(); p.lines = p.lines[:1]
    S.apply_style(p, {"video": {"resolution": "320x180"}})
    out = S.render_project(p, root, audio, root / "export")
    assert out.is_file()
    assert (out.parent / "lyrics.ass").read_text(encoding="utf-8") == S.compile_project(p, 4000, root)["ass"]
    assert list((out.parent / "fonts").glob("*.ttf"))


@pytest.mark.media
@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
def test_native_word_onset_sweep_and_sung_persistence(tmp_path):
    from PIL import Image
    import numpy as np
    from heartbeam.render import _escape_path_for_ass_filter
    p = song(); p.lines = [P.Line("test", [P.Word("test-word", "MMMMMM")], display_start_ms=0, display_end_ms=4000)]
    p.original_alignment["test-word"] = P.WordTiming(1000, 2000)
    S.apply_style(p, {"font": {"size_px": 200}, "box": {"outline_px": 0, "shadow_px": 0},
                      "colour": {"primary": "#FFFFFF", "highlight": "#00FF00"}})
    def green_fraction(mode, seconds):
        S.apply_style(p, {"highlight": {"mode": mode}})
        ass = tmp_path / "highlight.ass"; ass.write_text(S.compile_project(p, 4000)["ass"], encoding="utf-8")
        frame = tmp_path / "highlight.png"
        vf = f"setpts=PTS+{seconds}/TB,ass='{_escape_path_for_ass_filter(ass)}':fontsdir='{_escape_path_for_ass_filter(F.VENDOR.resolve())}'"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=black:s=960x540:d=1",
                        "-vf", vf, "-frames:v", "1", "-y", str(frame)], capture_output=True, check=True)
        pixels = np.asarray(Image.open(frame).convert("RGB"), dtype=np.float32)
        ink = pixels.max(axis=2) > 180
        green = (pixels[:, :, 1] > pixels[:, :, 0] * 1.5) & ink
        return green.sum() / ink.sum()
    assert green_fraction("word", .5) < .01
    assert green_fraction("word", 1.05) > .98
    assert .3 < green_fraction("sweep", 1.5) < .7
    assert green_fraction("sweep", 2.5) > .98
