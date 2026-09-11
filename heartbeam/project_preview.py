"""One effective-timing and ASS compilation path for browser and native export."""
from pathlib import Path
from . import timings as T
from .project import ProjectError

VENDOR = Path(__file__).parent / "editor_assets" / "vendor"


def timing_warnings(project, duration_ms):
    """Export diagnostics; accepting them never edits or approves lyric data."""
    from .editor import timing_conflicts
    from .timing_review import approved
    messages = []
    missing, conflicts = len(project.unresolved_words()), len(timing_conflicts(project))
    if missing:
        messages.append(f'{missing} word(s) still have no timing. Export will continue: they stay plain within a usable lyric window; lines without a window are omitted.')
    if conflicts:
        messages.append(f'{conflicts} timing conflict(s). Export will continue with the current overlapping word timings.')
    invalid = sum(1 for _, w in project.iter_words() if not w.non_sung
                  for t in [project.effective_timing(w.id)] if t and t.resolved
                  and not 0 <= t.start_ms < t.end_ms <= duration_ms)
    if invalid:
        messages.append(f'{invalid} word timing(s) fall outside the audio or have invalid duration. Those words will not highlight.')
    if not approved(project):
        messages.append('Current lyric timing has not been approved. Export will use the current lyrics and saved audio mix.')
    return messages


def line_window(project, line, duration_ms):
    """Known words, phrase anchor, then an authored display window for plain text."""
    from .phrase_project import phrase_window
    times = [t for w in line.words if not w.non_sung
             for t in [project.effective_timing(w.id)]
             if t and t.resolved and 0 <= t.start_ms < t.end_ms <= duration_ms]
    windows = [(t.start_ms, t.end_ms) for t in times]
    phrase = phrase_window(project, line, duration_ms)
    if phrase:
        windows.append(phrase)
    if windows:
        return min(w[0] for w in windows), max(w[1] for w in windows)
    start, end = line.display_start_ms, line.display_end_ms
    if start is not None and end is not None and 0 <= start < end <= duration_ms:
        return start, end
    return None


def current_timings(project, duration_ms, *, draft=False, allow_timing_issues=False):
    from .editor import timing_conflicts
    missing = project.unresolved_words()
    conflicts = timing_conflicts(project)
    if not (draft or allow_timing_issues) and (missing or conflicts):
        raise ProjectError(f"Fix {len(missing)} untimed word(s) and {len(conflicts)} timing conflict(s) before export.")
    if not (draft or allow_timing_issues):
        from .timing_review import require_approved
        require_approved(project)
    lines = []
    for line in project.lines:
        words = []
        for word in line.words:
            t = project.effective_timing(word.id)
            if word.non_sung or not t or not t.resolved:
                continue
            if not (0 <= t.start_ms < t.end_ms <= duration_ms):
                if draft or allow_timing_issues:
                    continue
                raise ProjectError(f"‘{word.text}’ is outside the audio or has an invalid duration.")
            words.append(T.Word(word.text if word.display_text is None else word.display_text, t.start_ms / 1000,
                                t.end_ms / 1000, t.score if t.score is not None else 1))
        if words:
            lines.append(T.Line(len(lines), " ".join(w.text for w in words),
                                min(w.start_s for w in words), max(w.end_s for w in words), words))
    return T.Timings(T.Source("project", "project", 44100, duration_ms / 1000),
                     T.Models(project.provenance.separator_preset or "saved", "edited"), lines)


def preview_style(project):
    from .presentation import resolved_style, as_legacy_style
    return as_legacy_style(resolved_style(project))


def preview_payload(project, duration_ms, register, root=None):
    from .editor import timing_conflicts
    from .presentation import compile_project
    compiled = compile_project(project, duration_ms, root, draft=True)
    fonts = [register(path, f"preview/fonts/{path.name}") for path in compiled.pop("fonts")]
    fallback = register(compiled.pop("fallback_font"), "preview/fallback")
    bg = compiled.pop("background")
    if bg["kind"] != "solid":
        bg["src"] = register(Path(bg["value"]), f"preview/background/{project.id}")
    # Worker uses a relative WASM filename. Serve a tiny bootstrap with an
    # explicit locateFile mapping because Streamlit media URLs are hashed.
    return {**compiled,
            "worker": register(VENDOR / "subtitles-octopus-worker.js", "preview/worker"),
            "wasm": register(VENDOR / "subtitles-octopus-worker.wasm", "preview/wasm"),
            "fonts": fonts, "background": bg,
            "fallback_font": fallback,
            "draft": bool(project.unresolved_words()),
            "conflicts": len(timing_conflicts(project))}
