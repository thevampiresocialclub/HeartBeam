"""
Emit an ASS (Advanced SubStation Alpha) subtitle file with per-word karaoke (\\k) tags.

This is the rendering contract for Phase 2: timings.json + style.toml → lyrics.ass.
libass (via ffmpeg's `ass` filter) burns the result onto the video.
"""
from __future__ import annotations

import math

from pathlib import Path

from .style import Style, ass_alignment, hex_to_ass_colour
from .timings import Timings


def _fmt_ass_time(t: float) -> str:
    """ASS H:MM:SS.cc with centiseconds.

    Round to whole centiseconds BEFORE splitting into fields. Formatting the
    seconds component directly with %05.2f rounds during formatting, so 59.999
    renders as the invalid "0:00:60.00" instead of carrying into the next
    minute; likewise 3599.999 -> "0:59:60.00".
    """
    if not math.isfinite(t) or t < 0:
        t = 0.0
    total_cs = int(round(t * 100))
    h, rem = divmod(total_cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _build_script_info(style: Style) -> str:
    w, h = style.video.resolution.split("x")
    return (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "YCbCr Matrix: TV.709\n"
    )


def _build_styles_block(style: Style) -> str:
    bold = -1 if style.font.bold else 0
    italic = -1 if style.font.italic else 0
    # ASS inverts the intuitive naming, so map these by MEANING, not by name:
    # PrimaryColour is the fill a syllable takes AFTER the \k sweep reaches it
    # (i.e. already sung), and SecondaryColour is its colour before that. Our
    # style.toml names them from the reader's point of view instead —
    # 'primary' = not yet sung, 'highlight' = being sung — so the two cross over
    # here. Assigning them name-to-name renders the karaoke backwards: the line
    # starts gold and turns white as it is sung.
    primary = hex_to_ass_colour(style.colour.highlight)
    secondary = hex_to_ass_colour(style.colour.primary)
    outline = hex_to_ass_colour(style.colour.outline)
    shadow = hex_to_ass_colour(style.colour.shadow)
    alignment = ass_alignment(style.box.position, style.box.alignment)

    header = (
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, "
        "Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )
    style_line = (
        f"Style: Default,{style.font.family},{style.font.size_px},"
        f"{primary},{secondary},{outline},{shadow},"
        f"{bold},{italic},0,0,100,100,0,0,1,"
        f"{style.box.outline_px},{style.box.shadow_px},{alignment},"
        f"{style.box.margin_h_px},{style.box.margin_h_px},{style.box.margin_v_px},1\n"
    )
    return header + style_line


def _build_events_block(timings: Timings) -> str:
    header = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = []
    for ln in timings.lines:
        if not ln.words:
            continue
        # Build karaoke text: {\k<centiseconds>}word with spaces between.
        # \k uses the duration of each syllable/word in centiseconds (1/100 sec).
        parts = []
        prev_end_cs = int(round(ln.start_s * 100))
        for w in ln.words:
            # Insert silent gap before word if there's a gap from prev_end.
            start_cs, end_cs = int(round(w.start_s * 100)), int(round(w.end_s * 100))
            gap_cs = max(0, start_cs - prev_end_cs)
            if gap_cs > 0:
                parts.append(f"{{\\k{gap_cs}}}")
            dur_cs = max(1, end_cs - start_cs)
            # Escape ASS-special chars sparingly (curly braces, backslash).
            text = w.text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")
            parts.append(f"{{\\k{dur_cs}}}{text} ")
            prev_end_cs = max(prev_end_cs, start_cs) + dur_cs
        karaoke_text = "".join(parts).rstrip()
        start = _fmt_ass_time(ln.start_s)
        end = _fmt_ass_time(ln.end_s)
        lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{karaoke_text}"
        )
    return header + "\n".join(lines) + ("\n" if lines else "")


def write_ass(timings: Timings, style: Style, out_path: str | Path) -> None:
    out_text = (
        _build_script_info(style)
        + "\n"
        + _build_styles_block(style)
        + "\n"
        + _build_events_block(timings)
    )
    Path(out_path).write_text(out_text, encoding="utf-8")


def render_ass_to_string(timings: Timings, style: Style) -> str:
    return (
        _build_script_info(style)
        + "\n"
        + _build_styles_block(style)
        + "\n"
        + _build_events_block(timings)
    )
