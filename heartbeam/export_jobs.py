"""Background video exports with immutable inputs and recoverable outputs."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field, fields
import json
import os
from pathlib import Path
import shutil
import threading
import time

from . import project as P, presentation as S, vocal_mix as V


@dataclass
class ExportJob:
    id: str
    project_id: str
    revision: int
    kind: str
    status: str = "queued"
    progress: float = 0.0
    message: str = "Waiting to start…"
    output_path: str | None = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    selection_ms: tuple[int, int] | None = None
    warnings: list[str] = field(default_factory=list)
    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)

    def public(self):
        return {item.name: copy.deepcopy(getattr(self, item.name)) for item in fields(self)
                if item.name != "_cancel"}


_jobs: dict[str, ExportJob] = {}
_lock = threading.Lock()


def _state_path(root, job_id):
    return Path(root) / P.EXPORTS_DIR / "jobs" / f"{job_id}.json"


def _save(root, job):
    path = _state_path(root, job.id)
    P._atomic_write(path, json.dumps(job.public(), indent=2))


def _update(root, job, **values):
    with _lock:
        for key, value in values.items():
            setattr(job, key, value)
        _save(root, job)


def get(job_id):
    with _lock:
        job = _jobs.get(job_id)
        return copy.copy(job) if job else None


def cancel(job_id):
    with _lock:
        job = _jobs.get(job_id)
        if job and job.status in ("queued", "running"):
            job._cancel.set()
            job.message = "Cancelling after the current step…"
            return True
    return False


def recover(root):
    """Return saved jobs; abandoned running jobs are labeled interrupted."""
    folder = Path(root) / P.EXPORTS_DIR / "jobs"
    result = []
    for path in sorted(folder.glob("*.json"), key=lambda p: p.stat().st_mtime_ns, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("status") in ("queued", "running") and data.get("id") not in _jobs:
                data.update(status="interrupted", message="The app closed before this export finished.")
            result.append(data)
        except (OSError, ValueError):
            continue
    return result


def _trim_snapshot(project, start_ms, end_ms):
    """Create a clip-relative project while retaining stable source IDs."""
    result = copy.deepcopy(project)
    keep_lines, keep_words = [], set()
    for line in result.lines:
        words = []
        for word in line.words:
            timing = result.effective_timing(word.id)
            if word.non_sung or not timing or not timing.resolved:
                continue
            if timing.end_ms > start_ms and timing.start_ms < end_ms:
                words.append(word); keep_words.add(word.id)
        if words:
            line.words = words
            line.display_start_ms = max(0, (line.display_start_ms if line.display_start_ms is not None else start_ms) - start_ms)
            line.display_end_ms = min(end_ms, line.display_end_ms if line.display_end_ms is not None else end_ms) - start_ms
            keep_lines.append(line)
    if not keep_lines:
        raise P.ProjectError("The selected passage contains no timed lyrics.")
    result.lines = keep_lines
    keep_line_ids = {line.id for line in keep_lines}
    result.sections = [section for section in result.sections if set(section.line_ids) & keep_line_ids]
    for section in result.sections:
        section.line_ids = [line_id for line_id in section.line_ids if line_id in keep_line_ids]
    for mapping in (result.original_alignment, result.alignment_proposals, result.timing_edits):
        for word_id in list(mapping):
            if word_id not in keep_words:
                mapping.pop(word_id)
                continue
            timing = mapping[word_id]
            if timing.resolved:
                timing.start_ms = max(0, timing.start_ms - start_ms)
                timing.end_ms = min(end_ms - start_ms, timing.end_ms - start_ms)
    result.presentation.line_overrides = {k: v for k, v in result.presentation.line_overrides.items() if k in keep_line_ids}
    return result


def _clip_audio(source, destination, start_ms, end_ms):
    import soundfile as sf
    info = sf.info(str(source))
    start = round(start_ms * info.samplerate / 1000)
    count = round((end_ms - start_ms) * info.samplerate / 1000)
    data, rate = sf.read(str(source), start=start, frames=count, dtype="float32", always_2d=True)
    if not len(data):
        raise P.ProjectError("The selected passage is outside the song audio.")
    sf.write(str(destination), data, rate, subtype="FLOAT")


def preflight(project, root, karaoke, selection_ms=None):
    """Fail before launching a costly job and return compiler warnings."""
    from .render import _audio_duration, _ffmpeg_path
    _ffmpeg_path()
    root, audio = Path(root), Path(karaoke)
    if project.vocal_mix.references:
        paths, basis = V.checked_references(project, root)
        duration_ms = P.seconds_to_ms(basis[2] / basis[0])
    elif project.vocal_mix.regions or project.vocal_mix.default_value:
        raise P.ProjectError("Restore calibrated audio references before exporting the vocal mix.")
    elif not audio.is_file():
        raise P.ProjectError("The karaoke audio is missing. Relink it before export.")
    else:
        duration_ms = P.seconds_to_ms(_audio_duration(audio))
    candidate = project
    compile_duration = duration_ms
    if selection_ms:
        start, end = selection_ms
        if not 0 <= start < end <= duration_ms or end - start > 60000:
            raise P.ProjectError("Choose a passage within the song, up to 60 seconds long.")
        candidate = _trim_snapshot(project, start, end)
        compile_duration = end - start
    compiled = S.compile_project(candidate, compile_duration, root)
    return duration_ms, compiled["warnings"]


def start(project, root, karaoke, selection_ms=None):
    snapshot, root = copy.deepcopy(project), Path(root).resolve()
    _, warnings = preflight(snapshot, root, karaoke, selection_ms)
    kind = "selection" if selection_ms else "full"
    with _lock:
        for old in _jobs.values():
            if old.project_id == snapshot.id and old.status in ("queued", "running"):
                raise P.ProjectError("An export for this project is already running.")
        job = ExportJob(P.new_id("export"), snapshot.id, snapshot.revision, kind,
                        selection_ms=selection_ms, warnings=warnings)
        _jobs[job.id] = job
        _save(root, job)
    thread = threading.Thread(target=_run, args=(job, snapshot, root, Path(karaoke)), daemon=True,
                              name=f"heartbeam-export-{job.id}")
    thread.start()
    return copy.copy(job)


def _run(job, snapshot, root, karaoke):
    exports = root / P.EXPORTS_DIR
    final = exports / f"rev-{snapshot.revision}-{job.kind}-{job.id}"
    temporary = exports / f".job-{job.id}.tmp"
    try:
        _update(root, job, status="running", progress=.02, message="Preparing the frozen audio mix…")
        audio = V.render_mix(snapshot, root) if snapshot.vocal_mix.references else karaoke
        if job._cancel.is_set():
            raise RuntimeError("Video export cancelled.")
        render_snapshot = snapshot
        temporary.mkdir(parents=True, exist_ok=False)
        if job.selection_ms:
            start_ms, end_ms = job.selection_ms
            clipped = temporary / "selection-audio.wav"
            _clip_audio(audio, clipped, start_ms, end_ms)
            audio = clipped
            render_snapshot = _trim_snapshot(snapshot, start_ms, end_ms)
        from .project_preview import current_timings
        from .render import _audio_duration
        from .timings import to_json
        duration = P.seconds_to_ms(_audio_duration(Path(audio)))
        timings = current_timings(render_snapshot, duration)
        _update(root, job, progress=.08, message="Encoding video from the frozen snapshot…")
        path = S.render_project(render_snapshot, root, audio, temporary,
            progress=lambda fraction: _update(root, job, progress=.08 + .9 * fraction,
                                               message=f"Encoding video… {round(fraction * 100)}%"),
            cancel=job._cancel)
        to_json(timings, temporary / "timings.json")
        manifest = {"format": "heartbeam-export", "version": 1, "job_id": job.id,
                    "kind": job.kind, "source_revision": snapshot.revision,
                    "selection_ms": job.selection_ms, "audio_sha256": P.file_sha256(audio),
                    "asset_ids": [{"id": a.id, "sha256": a.sha256, "role": a.role} for a in snapshot.assets],
                    "warnings": job.warnings}
        (temporary / "export-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if job._cancel.is_set():
            raise RuntimeError("Video export cancelled.")
        os.replace(temporary, final)
        path = final / path.name
        _update(root, job, status="complete", progress=1.0, message="Video ready.",
                output_path=str(path), finished_at=time.time())
    except Exception as exc:
        status = "cancelled" if job._cancel.is_set() else "failed"
        _update(root, job, status=status, message="Export cancelled." if status == "cancelled" else "Export failed.",
                error=str(exc), finished_at=time.time())
    finally:
        # This exact hidden directory belongs only to this job. Completed
        # exports and every previous good output are outside it.
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)
