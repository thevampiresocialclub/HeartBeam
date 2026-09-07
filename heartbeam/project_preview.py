"""One effective-timing and ASS compilation path for browser and native export."""
from pathlib import Path
from . import timings as T
from .ass_writer import render_ass_to_string
from .style import Style
from .project import ProjectError

VENDOR = Path(__file__).parent / "editor_assets" / "vendor"


def current_timings(project, duration_ms, *, draft=False):
    from .editor import timing_conflicts
    missing = project.unresolved_words()
    conflicts = timing_conflicts(project)
    if not draft and (missing or conflicts):
        raise ProjectError(f"Fix {len(missing)} untimed word(s) and {len(conflicts)} timing conflict(s) before export.")
    lines = []
    for line in project.lines:
        words = []
        for word in line.words:
            t = project.effective_timing(word.id)
            if word.non_sung or not t or not t.resolved:
                continue
            if not (0 <= t.start_ms < t.end_ms <= duration_ms):
                if draft:
                    continue
                raise ProjectError(f"‘{word.text}’ is outside the audio or has an invalid duration.")
            words.append(T.Word(word.display_text or word.text, t.start_ms / 1000,
                                t.end_ms / 1000, t.score if t.score is not None else 1))
        if words:
            lines.append(T.Line(len(lines), " ".join(w.text for w in words),
                                min(w.start_s for w in words), max(w.end_s for w in words), words))
    return T.Timings(T.Source("project", "project", 44100, duration_ms / 1000),
                     T.Models(project.provenance.separator_preset or "saved", "edited"), lines)


def preview_style(project):
    style = Style()
    style.font.family = "Noto Sans"
    for group in ("font", "colour", "box", "background", "video"):
        for key, value in project.presentation.song_style.get(group, {}).items():
            if hasattr(getattr(style, group), key):
                setattr(getattr(style, group), key, value)
    return style


def preview_payload(project, duration_ms, register):
    from .editor import timing_conflicts
    style = preview_style(project)
    fonts = [register(VENDOR / name, f"preview/{name}")
             for name in ("NotoSans-Regular.ttf", "NotoSans-Bold.ttf")]
    # Worker uses a relative WASM filename. Serve a tiny bootstrap with an
    # explicit locateFile mapping because Streamlit media URLs are hashed.
    return {"ass": render_ass_to_string(current_timings(project, duration_ms, draft=True), style),
            "worker": register(VENDOR / "subtitles-octopus-worker.js", "preview/worker"),
            "wasm": register(VENDOR / "subtitles-octopus-worker.wasm", "preview/wasm"),
            "fonts": fonts, "width": int(style.video.resolution.split("x")[0]),
            "height": int(style.video.resolution.split("x")[1]),
            "background": style.background.value if style.background.kind == "solid" else "#101820",
            "draft": bool(project.unresolved_words()),
            "conflicts": len(timing_conflicts(project))}
