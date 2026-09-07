"""P05 presentation commands and the single project-to-ASS compiler.

All geometry is in the saved design canvas, independently of output size.
Only absent keys inherit; zero, False and empty break lists are real values.
"""
from __future__ import annotations
import copy
from dataclasses import asdict
import json
import math
from pathlib import Path
import re
import shutil

from . import project as P
from . import ass_writer as A
from .style import Style
from . import presentation_fonts as F

DEFAULTS = asdict(Style())
DEFAULTS["font"]["family"] = "Noto Sans"
DEFAULTS["box"].update(wrap="explicit")
DEFAULTS["highlight"] = {"mode": "word"}
ANCHORS = [f"{v} {h}" for v in ("top", "center", "bottom") for h in ("left", "center", "right")]
ALIGNMENTS = ["left", "center", "right"]
TEXT_GROUPS = {"font", "colour", "box", "highlight"}


def merge(base, patch):
    result = copy.deepcopy(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def resolved_style(project, line_id=None):
    style = merge(DEFAULTS, project.presentation.song_style)
    if line_id:
        override = project.presentation.line_overrides.get(line_id, {})
        style = merge(style, {k: v for k, v in override.items() if k in TEXT_GROUPS})
    w, h = project.presentation.design_width, project.presentation.design_height
    validate_style(style, w, h)
    box = style["box"]
    box.setdefault("anchor", f"{box['position']} {box['alignment']}")
    vertical, horizontal = box["anchor"].split()
    box.setdefault("width_px", w - 2 * box["margin_h_px"])
    box.setdefault("x", {"left": box["margin_h_px"], "center": w / 2, "right": w - box["margin_h_px"]}[horizontal])
    box.setdefault("y", {"top": box["margin_v_px"], "center": h / 2, "bottom": h - box["margin_v_px"]}[vertical])
    return style


def _number(value, low, high, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise P.ProjectError(f"{label} must be between {low:g} and {high:g}.")


def validate_style(style, width=1920, height=1080):
    if not isinstance(style, dict):
        raise P.ProjectError("Style must be an object.")
    known = {k: set(v) for k, v in DEFAULTS.items()}
    known["box"] |= {"x", "y", "width_px", "anchor"}
    known["background"].add("asset_id")
    for group, values in style.items():
        if group not in known or not isinstance(values, dict) or set(values) - known[group]:
            raise P.ProjectError(f"Unsupported style field in {group}.")
    full = merge(DEFAULTS, style)
    font, box = full["font"], full["box"]
    if not isinstance(font["family"], str) or not font["family"].strip() or any(c in font["family"] for c in ",{}\\\n\r"):
        raise P.ProjectError("Choose a valid font family.")
    for flag in ("bold", "italic"):
        if type(font[flag]) is not bool:
            raise P.ProjectError(f"Font {flag} must be true or false.")
    _number(font["size_px"], 8, 400, "Font size")
    for key in ("outline_px", "shadow_px"):
        _number(box[key], 0, 40, key.replace("_", " "))
    for key, limit in (("margin_h_px", width / 2 - 1), ("margin_v_px", height / 2), ("x", width), ("y", height), ("width_px", width)):
        if key in box:
            _number(box[key], 1 if key == "width_px" else 0, limit, key)
    if box.get("anchor", "bottom center") not in ANCHORS or box["alignment"] not in ALIGNMENTS or box["position"] not in ("top", "center", "bottom"):
        raise P.ProjectError("Choose a valid anchor and alignment.")
    if box["wrap"] not in ("explicit", "auto") or full["highlight"]["mode"] not in ("word", "sweep"):
        raise P.ProjectError("Choose explicit/automatic wrapping and word/sweep highlighting.")
    for colour in full["colour"].values():
        if not isinstance(colour, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", colour):
            raise P.ProjectError("Colours must use #RRGGBB.")
    bg = full["background"]
    if bg["kind"] not in ("solid", "image", "video"):
        raise P.ProjectError("Choose a solid, image or video background.")
    if bg["kind"] == "solid" and not re.fullmatch(r"#[0-9a-fA-F]{6}", str(bg["value"])):
        raise P.ProjectError("Background colour must use #RRGGBB.")
    video = full["video"]
    if not re.fullmatch(r"\d+x\d+", str(video["resolution"])):
        raise P.ProjectError("Invalid output resolution.")
    vw, vh = map(int, video["resolution"].split("x"))
    if not (16 <= vw <= 7680 and 16 <= vh <= 4320 and vw * height == vh * width and vw % 2 == vh % 2 == 0):
        raise P.ProjectError("Use an even-sized export with the same aspect ratio as the design canvas.")
    _number(video["fps"], 1, 120, "Frame rate")
    _number(video["crf"], 0, 51, "Video quality")


def apply_style(project, patch, line_ids=None):
    """Patch song defaults or specific lines, retaining unrelated exceptions."""
    validate_style(patch, project.presentation.design_width, project.presentation.design_height)
    if line_ids is None:
        candidate = merge(project.presentation.song_style, patch)
        validate_style(candidate, project.presentation.design_width, project.presentation.design_height)
        project.presentation.song_style = candidate
    else:
        valid = {line.id for line in project.lines}
        if not line_ids or set(line_ids) - valid:
            raise P.ProjectError("Select existing lyric lines first.")
        if set(patch) - TEXT_GROUPS:
            raise P.ProjectError("Background and export settings apply to the whole song.")
        for line_id in line_ids:
            existing = project.presentation.line_overrides.get(line_id, {})
            project.presentation.line_overrides[line_id] = merge(existing, patch)
    return True, "Appearance updated. Save to keep it."


def reset_lines(project, line_ids):
    for line_id in line_ids:
        project.presentation.line_overrides.pop(line_id, None)


def placement_command(project, data):
    scope = data.get("scope")
    if scope not in ("song", "lines"):
        raise P.ProjectError("Choose a placement scope.")
    return apply_style(project, {"box": {"x": data.get("x"), "y": data.get("y")}},
                       None if scope == "song" else data.get("line_ids", []))


def inside_margins(width, height, anchor, horizontal, vertical):
    _number(horizontal, 0, width / 2 - 1, "Horizontal margin")
    _number(vertical, 0, height / 2, "Vertical margin")
    row, col = anchor.split()
    return {"box": {"anchor": anchor, "margin_h_px": horizontal, "margin_v_px": vertical,
            "width_px": width - 2 * horizontal,
            "x": {"left": horizontal, "center": width / 2, "right": width - horizontal}[col],
            "y": {"top": vertical, "center": height / 2, "bottom": height - vertical}[row]}}


def display_text(word):
    return word.text if word.display_text is None else word.display_text


DISPLAY_DEFAULTS = {
    "automatic": False,
    "advance_ms": 1500,
    "hold_ms": 600,
    "show_upcoming": False,
    "upcoming_offset_y": -180,
}


def display_settings(project):
    saved = getattr(project.presentation, "display", {})
    if set(saved) - set(DISPLAY_DEFAULTS):
        raise P.ProjectError("Unknown lyric display setting.")
    value = {**DISPLAY_DEFAULTS, **saved}
    if not isinstance(value["automatic"], bool) or not isinstance(value["show_upcoming"], bool):
        raise P.ProjectError("Automatic and upcoming lyric display settings must be on or off.")
    for key, low, high in (("advance_ms", 0, 10000), ("hold_ms", 0, 10000),
                           ("upcoming_offset_y", -1080, 1080)):
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not low <= item <= high:
            raise P.ProjectError(f"Invalid lyric display setting: {key}.")
        value[key] = round(item)
    return value


def set_display_settings(project, values):
    if set(values) - set(DISPLAY_DEFAULTS):
        raise P.ProjectError("Unknown lyric display setting.")
    candidate = {**display_settings(project), **values}
    old = getattr(project.presentation, "display", None)
    project.presentation.display = candidate
    try:
        project.presentation.display = display_settings(project)
    except Exception:
        if old is None:
            delattr(project.presentation, "display")
        else:
            project.presentation.display = old
        raise
    return True, "Lyric reading timing updated. Save to keep it."


def wrapped_text(project, line):
    breaks = project.presentation.line_overrides.get(line.id, {}).get("break_before", [])
    return "".join(("\n" if w.id in breaks else " " if i else "") + display_text(w)
                   for i, w in enumerate(line.words))


def set_line_breaks(project, line_id, text):
    line = next((line for line in project.lines if line.id == line_id), None)
    if line is None:
        raise P.ProjectError("Select a lyric line first.")
    tokens = [display_text(w) for w in line.words]
    if text.split() != tokens:
        raise P.ProjectError("This box only changes wrapping. Keep the same words; edit wording in the lyrics editor.")
    breaks, index = [], 0
    for row in text.splitlines():
        words = row.split()
        if words and index:
            breaks.append(line.words[index].id)
        index += len(words)
    project.presentation.line_overrides.setdefault(line_id, {})["break_before"] = breaks


def preset_document(name, style):
    """Portable defaults. Deliberately exclude media references and line IDs."""
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise P.ProjectError("Give the preset a name of 1 to 80 characters.")
    validate_style(style)
    defaults = {k: copy.deepcopy(v) for k, v in style.items() if k in TEXT_GROUPS}
    if style.get("background", {}).get("kind") == "solid":
        defaults["background"] = {k: style["background"][k] for k in ("kind", "value")}
    return {"format": "heartbeam-style", "version": 1, "name": name.strip(), "defaults": defaults}


def read_preset(data):
    if not isinstance(data, dict) or set(data) != {"format", "version", "name", "defaults"} or data["format"] != "heartbeam-style" or data["version"] != 1:
        raise P.ProjectError("This is not a supported HeartBeam style preset.")
    clean = preset_document(data["name"], data["defaults"])
    if clean != data:
        raise P.ProjectError("Presets contain appearance defaults only, with no media files or export settings.")
    return clean


def apply_preset(project, document):
    data = read_preset(document)
    # Replace presentation defaults while retaining the song's background media
    # and export settings if the preset does not specify a solid background.
    keep = {k: v for k, v in project.presentation.song_style.items() if k in ("background", "video")}
    project.presentation.song_style = merge(keep, data["defaults"])
    project.presentation.presets[data["name"]] = data
    return True, f"Applied {data['name']}. Line exceptions were preserved."


def import_legacy_style(project, root, style):
    data = asdict(style)
    if data["background"]["kind"] != "solid":
        asset = F.copy_asset(project, root, Path(data["background"]["value"]), "background")
        data["background"] = {"kind": style.background.kind, "asset_id": asset.id, "value": "#101820"}
    # Old sizes were expressed in the output canvas. Convert once on import.
    old_w, old_h = map(int, style.video.resolution.split("x"))
    if old_w * project.presentation.design_height != old_h * project.presentation.design_width:
        raise P.ProjectError("Legacy style must have the same aspect ratio as the design canvas.")
    scale = project.presentation.design_width / old_w
    data["font"]["size_px"] *= scale
    for key in ("margin_h_px", "margin_v_px", "outline_px", "shadow_px"):
        data["box"][key] *= scale
    data["box"]["wrap"] = "auto"
    validate_style(data, project.presentation.design_width, project.presentation.design_height)
    family = data["font"]["family"]
    if family != "Noto Sans" and family in F.installed_fonts():
        F.import_fonts(project, root, F.installed_fonts()[family])
    project.presentation.song_style = data


def background(project, root, *, strict=False):
    bg = resolved_style(project)["background"]
    if bg["kind"] == "solid":
        return bg, []
    asset = next((a for a in project.assets if a.id == bg.get("asset_id")), None)
    # Backward-compatible read of P03/P04 saved external backgrounds. P05's
    # importer/chooser copies new files to assets and records their IDs.
    path = asset.resolve(Path(root)) if asset and root is not None else Path(bg["value"])
    if path.is_file() and (not asset or P.file_sha256(path) == asset.sha256):
        return {"kind": bg["kind"], "value": str(path)}, []
    message = "Background is missing or changed. Relink it or choose a new background before export."
    if strict:
        raise P.ProjectError(message)
    return {"kind": "solid", "value": "#101820"}, [message]


def as_legacy_style(spec):
    style = Style()
    for group in ("font", "colour", "box", "background", "video"):
        for key, value in spec.get(group, {}).items():
            if hasattr(getattr(style, group), key):
                setattr(getattr(style, group), key, value)
    return style


def _layout(spec, line, breaks, face):
    """Guide and overflow estimate; actual glyph rendering always uses libass."""
    box, size = spec["box"], spec["font"]["size_px"]
    info = F.font_info(face)
    measure = lambda text: sum(info["advances"].get(ord(c), .6) * size for c in text)
    rows, current = [], ""
    for word in line.words:
        text = display_text(word)
        candidate = current + (" " if current else "") + text
        if current and (word.id in breaks or (box["wrap"] == "auto" and measure(candidate) > box["width_px"])):
            rows.append(current); current = text
        else:
            current = candidate
    rows.append(current)
    height = size * info["line_height"] * len(rows)
    vertical, horizontal = box["anchor"].split()
    left = box["x"] - {"left": 0, "center": .5, "right": 1}[horizontal] * box["width_px"]
    top = box["y"] - {"top": 0, "center": .5, "bottom": 1}[vertical] * height
    return {"x": box["x"], "y": box["y"], "left": left, "top": top,
            "width": box["width_px"], "height": height,
            "text_width": max(map(measure, rows), default=0)}


def compile_project(project, duration_ms, root=None, *, draft=False):
    """The sole presentation compiler for preview and project exports."""
    from .project_preview import current_timings
    current_timings(project, duration_ms, draft=draft)  # common timing validation
    width, height = project.presentation.design_width, project.presentation.design_height
    base = resolved_style(project)
    validate_style(base, width, height)
    script_style = as_legacy_style(base)
    script_style.video.resolution = f"{width}x{height}"
    header = A._build_script_info(script_style)
    styles, events, layouts, warnings, fonts, compiled_lines = [], [], [], [], set(), []
    schedule = display_settings(project)
    scheduled = {}
    if schedule["automatic"]:
        for line in project.lines:
            spans = [project.effective_timing(word.id) for word in line.words if not word.non_sung]
            spans = [timing for timing in spans if timing and timing.resolved and
                     0 <= timing.start_ms < timing.end_ms <= duration_ms]
            if spans:
                first, last = min(t.start_ms for t in spans), max(t.end_ms for t in spans)
                scheduled[line.id] = {"start": max(0, first - schedule["advance_ms"]),
                                      "end": min(duration_ms, last + schedule["hold_ms"]),
                                      "first": first, "last": last}
        windows = [scheduled[line.id] for line in project.lines if line.id in scheduled]
        shortened = False
        for left, right in zip(windows, windows[1:]):
            if left["end"] <= right["start"]:
                continue
            if left["last"] <= right["first"]:
                # One shared boundary avoids two current lines in the same slot.
                # Prefer the requested lead where the real inter-phrase gap fits;
                # otherwise the earlier phrase remains through its final word.
                boundary = max(left["last"], right["start"])
                left["end"] = boundary
                right["start"] = boundary
                shortened = True
            else:
                warnings.append("Adjacent sung phrases overlap in time. Both highlights remain visible; place those lines in separate screen positions if they collide.")
        if shortened:
            warnings.append("A lead/hold was shortened between adjacent phrases so two current lyrics do not occupy the same slot.")
    for index, line in enumerate(project.lines):
        spec = resolved_style(project, line.id)
        validate_style(spec, width, height)
        face, family, messages = F.resolve_face(project, root, spec["font"])
        warnings.extend(messages); fonts.add(face)
        spec["font"]["family"] = family
        breaks = project.presentation.line_overrides.get(line.id, {}).get("break_before", [])
        layout = _layout(spec, line, breaks, face)
        if layout["text_width"] > layout["width"] + 1 or layout["left"] < 0 or layout["top"] < 0 or layout["left"] + layout["width"] > width + 1 or layout["top"] + layout["height"] > height + 1:
            warnings.append(f"Line {index + 1} may overflow its text box or canvas. Inspect the preview; reduce size, move it or add a line break.")
        glyphs = F.font_info(face)["advances"]
        missing = sorted({c for word in line.words for c in display_text(word) if not c.isspace() and ord(c) not in glyphs})
        if missing:
            message = f"Line {index + 1}: {family} lacks characters {''.join(missing[:12])!r}. Choose a font containing these characters."
            if not draft:
                raise P.ProjectError(message)
            warnings.append(message)
        words = []
        for word in line.words:
            timing = project.effective_timing(word.id)
            if not word.non_sung and timing and timing.resolved and 0 <= timing.start_ms < timing.end_ms <= duration_ms:
                words.append((word, timing))
        if not words:
            continue
        first_sung, last_sung = min(t.start_ms for _, t in words), max(t.end_ms for _, t in words)
        if schedule["automatic"]:
            start, end = scheduled[line.id]["start"], scheduled[line.id]["end"]
        else:
            start = line.display_start_ms if line.display_start_ms is not None else first_sung
            end = line.display_end_ms if line.display_end_ms is not None else last_sung
        if not 0 <= start <= min(t.start_ms for _, t in words) < max(t.end_ms for _, t in words) <= end <= duration_ms:
            if not draft:
                raise P.ProjectError(f"Line {index + 1} has an invalid display window.")
            warnings.append(f"Line {index + 1}: invalid display window; preview uses word timing.")
            start, end = min(t.start_ms for _, t in words), max(t.end_ms for _, t in words)
        layouts.append({**layout, "line_id": line.id, "ass_name": f"Line{index}", "word_id": words[0][0].id,
                        "start_ms": start, "end_ms": end, "label": line.text,
                        "style": spec, "exception": bool(project.presentation.line_overrides.get(line.id))})
        overrides = project.presentation.line_overrides.get(line.id, {}).get("box", {})
        layouts[-1]["placement_exception"] = "x" in overrides or "y" in overrides
        style = as_legacy_style(spec)
        box = spec["box"]
        vertical = box["anchor"].split()[0]
        style.box.position = vertical
        style.box.margin_h_px = max(0, round((width - box["width_px"]) / 2))
        name = f"Line{index}"
        block = A._build_styles_block(style).replace("Style: Default,", f"Style: {name},")
        styles.append(block if not styles else block.splitlines()[-1] + "\n")
        text_x = layout["left"] + {"left": 0, "center": .5, "right": 1}[box["alignment"]] * box["width_px"]
        tags = f"{{\\pos({text_x:g},{box['y']:g})\\q{1 if box['wrap'] == 'auto' else 2}}}"
        parts, previous = [], round(start / 10)
        for i, (word, timing) in enumerate(words):
            begin, finish = round(timing.start_ms / 10), round(timing.end_ms / 10)
            gap = max(0, begin - previous)
            if i:
                parts.append(r"\N" if word.id in breaks else " ")
            if gap:
                parts.append(f"{{\\k{gap}}}")
            tag = "kf" if spec["highlight"]["mode"] == "sweep" else "k"
            span = max(1, finish - begin)
            parts.append(f"{{\\{tag}{span}}}" + A.escape_text(display_text(word)))
            previous = max(previous, begin) + span
        events.append(f"Dialogue: 0,{A._fmt_ass_time(start / 1000)},{A._fmt_ass_time(end / 1000)},{name},,0,0,0,,{tags}{''.join(parts)}")
        compiled_lines.append({"line": line, "name": name, "start": start, "end": end,
                               "first_sung": first_sung, "spec": spec, "layout": layout})
    if schedule["show_upcoming"]:
        # A line is upcoming only until its own current-line event begins. This
        # gives a deterministic two-slot policy without double-displaying it.
        for current, upcoming in zip(compiled_lines, compiled_lines[1:]):
            begin, finish = current["start"], min(current["end"], upcoming["start"])
            if finish <= begin:
                continue
            box = upcoming["spec"]["box"]
            y = max(0, min(height, box["y"] + schedule["upcoming_offset_y"]))
            text_x = upcoming["layout"]["left"] + {"left": 0, "center": .5, "right": 1}[box["alignment"]] * box["width_px"]
            text = A.escape_text(wrapped_text(project, upcoming["line"])).replace("\n", r"\N")
            tags = f"{{\\pos({text_x:g},{y:g})\\q{1 if box['wrap'] == 'auto' else 2}}}"
            events.append(f"Dialogue: 0,{A._fmt_ass_time(begin / 1000)},{A._fmt_ass_time(finish / 1000)},{upcoming['name']},,0,0,0,,{tags}{text}")
    # Always register a known fallback, including empty/untimed projects.
    fallback, _, messages = F.resolve_face(project, root, {"family": "Noto Sans", "bold": False, "italic": False})
    fonts.add(fallback); warnings.extend(messages)
    ass = header + "\n" + ("".join(styles) or A._build_styles_block(script_style)) + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n" + "\n".join(events) + "\n"
    bg, messages = background(project, root, strict=not draft)
    warnings.extend(messages)
    return {"ass": ass, "fonts": sorted(fonts), "fallback_font": fallback, "lines": layouts,
            "warnings": list(dict.fromkeys(warnings)), "background": bg,
            "width": width, "height": height}


def render_project(project, root, audio, destination, *, progress=None, cancel=None):
    """Render an immutable project snapshot with its exact ASS and font files."""
    from .render import render, _audio_duration
    destination = Path(destination)
    compiled = compile_project(project, P.seconds_to_ms(_audio_duration(Path(audio))), root)
    destination.mkdir(parents=True, exist_ok=True)
    font_dir = destination / "fonts"
    font_dir.mkdir(exist_ok=True)
    for font in compiled["fonts"]:
        shutil.copy2(font, font_dir / (P.file_sha256(font) + font.suffix))
    style = as_legacy_style(resolved_style(project))
    bg = compiled["background"]
    if bg["kind"] != "solid":
        source = Path(bg["value"])
        dest = destination / ("background" + source.suffix.lower())
        shutil.copy2(source, dest)
        bg = {**bg, "value": str(dest.resolve())}
    style.background.kind, style.background.value = bg["kind"], bg["value"]
    ass_path = destination / "lyrics.ass"
    ass_path.write_text(compiled["ass"], encoding="utf-8")
    (destination / "presentation.json").write_text(json.dumps(asdict(project.presentation), indent=2), encoding="utf-8")
    (destination / "presentation-warnings.json").write_text(json.dumps(compiled["warnings"], indent=2), encoding="utf-8")
    (destination / "project-snapshot.json").write_text(json.dumps(project.to_dict(), indent=2), encoding="utf-8")
    output = destination / "karaoke.mp4"
    render(audio, ass_path, output, style, font_dir=font_dir, progress=progress, cancel=cancel)
    return output
