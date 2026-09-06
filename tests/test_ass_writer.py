from heartbeam.ass_writer import render_ass_to_string
from heartbeam.ass_writer import _build_styles_block
from heartbeam.style import Style, hex_to_ass_colour, ass_alignment
from heartbeam.timings import Line, Models, Source, Timings, Word


def _sample_timings() -> Timings:
    return Timings(
        source=Source("song.mp3", "lyrics.txt", 44100, 4.0),
        models=Models("demucs", "whisperx-medium"),
        lines=[
            Line(
                index=0,
                text="hello world",
                start_s=1.00,
                end_s=2.50,
                words=[
                    Word("hello", 1.00, 1.50, 0.95),
                    Word("world", 1.55, 2.50, 0.93),
                ],
            ),
        ],
    )


def test_hex_to_ass_colour_rgb_byte_swap():
    assert hex_to_ass_colour("#FFD700") == "&H0000D7FF&"
    assert hex_to_ass_colour("#FFFFFF") == "&H00FFFFFF&"
    assert hex_to_ass_colour("#000000") == "&H00000000&"


def test_alignment_numpad():
    assert ass_alignment("bottom", "center") == 2
    assert ass_alignment("top", "left") == 7
    assert ass_alignment("center", "right") == 6


def test_ass_output_contains_script_info_and_styles():
    out = render_ass_to_string(_sample_timings(), Style())
    assert "[Script Info]" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out


def test_ass_dialogue_has_karaoke_tag_per_word():
    out = render_ass_to_string(_sample_timings(), Style())
    # "hello" lasts 0.50s = 50cs, "world" lasts 0.95s = 95cs.
    # There is also a 5cs gap (1.50 → 1.55) inserted between them.
    assert "{\\k50}hello" in out
    assert "{\\k5}{\\k95}world" in out or "{\\k95}world" in out
    # Dialogue line shows correct start/end times
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Default" in out


def test_ass_dialogue_escapes_braces():
    t = Timings(
        source=Source("a.mp3", "a.txt", 44100, 1.0),
        models=Models("demucs", "whisperx-medium"),
        lines=[
            Line(
                index=0, text="{weird}", start_s=0.1, end_s=0.5,
                words=[Word("{weird}", 0.1, 0.5, 0.9)],
            )
        ],
    )
    out = render_ass_to_string(t, Style())
    # Curly braces in lyrics text should not appear unescaped (would be parsed as ASS override tags).
    assert "{weird}" not in out.split("[Events]")[1]
    assert "(weird)" in out


def test_karaoke_colours_are_mapped_by_meaning_not_by_name():
    """PrimaryColour must be the *sung* colour, SecondaryColour the unsung one.

    ASS names these the opposite way round from how a reader thinks about them,
    so a name-to-name mapping renders the karaoke backwards: every line starts
    gold and turns white as it is sung. Regression test for exactly that.
    """
    style = Style.default()
    style.colour.primary = "#FFFFFF"    # not yet sung
    style.colour.highlight = "#FFD700"  # sung

    style_line = next(
        ln for ln in _build_styles_block(style).splitlines()
        if ln.startswith("Style: ")
    )
    fields = style_line[len("Style: "):].split(",")
    # Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, ...
    primary_colour, secondary_colour = fields[3], fields[4]

    assert primary_colour == hex_to_ass_colour("#FFD700"), "sung text must use the highlight colour"
    assert secondary_colour == hex_to_ass_colour("#FFFFFF"), "unsung text must use the primary colour"
