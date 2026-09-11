"""P06 export job contracts: frozen revisions, clips, cancellation and recovery."""
import json
from pathlib import Path
import time

import pytest

from heartbeam import export_jobs as J, project as P, presentation as S
from tests.test_presentation import song


def _audio(path, seconds=8):
    import numpy as np
    import soundfile as sf
    rate = 8000
    sf.write(path, (np.sin(np.arange(rate * seconds) * .17) * .1).astype("float32"), rate)
    return path


def _wait(job_id, timeout=20):
    until = time.time() + timeout
    while time.time() < until:
        job = J.get(job_id)
        if job.status not in ("queued", "running"):
            return job
        time.sleep(.02)
    raise AssertionError("export job did not finish")


def test_preflight_blocks_missing_audio_and_bad_passage(tmp_path):
    p = song()
    with pytest.raises(P.ProjectError, match="karaoke audio"):
        J.preflight(p, tmp_path, tmp_path / "missing.wav")
    audio = _audio(tmp_path / "audio.wav")
    with pytest.raises(P.ProjectError, match="within the song"):
        J.preflight(p, tmp_path, audio, (7000, 9000))


def test_trimmed_snapshot_keeps_source_ids_and_shifts_only_clip_timing():
    p = song(); before = p.to_dict()
    clip = J._trim_snapshot(p, 4000, 8000)
    assert [line.id for line in clip.lines] == ["line1"]
    assert clip.word_ids() == [word.id for word in p.lines[1].words]
    assert clip.effective_timing(clip.word_ids()[0]).start_ms == 500
    assert p.to_dict() == before


@pytest.mark.media
def test_background_job_freezes_revision_and_promotes_complete_output(tmp_path):
    audio = _audio(tmp_path / "audio.wav")
    p = song(); S.apply_style(p, {"video": {"resolution": "320x180"}})
    job = J.start(p, tmp_path, audio, (4000, 7000))
    p.revision += 20
    S.apply_style(p, {"colour": {"highlight": "#123456"}})
    done = _wait(job.id)
    assert done.status == "complete" and done.progress == 1
    output = Path(done.output_path)
    assert output.is_file() and not list((tmp_path / P.EXPORTS_DIR).glob(".job-*.tmp"))
    manifest = json.loads((output.parent / "export-manifest.json").read_text(encoding="utf-8"))
    snapshot = json.loads((output.parent / "project-snapshot.json").read_text(encoding="utf-8"))
    assert manifest["source_revision"] == job.revision
    assert manifest["selection_ms"] == [4000, 7000]
    assert snapshot["revision"] == job.revision
    assert "123456" not in (output.parent / "lyrics.ass").read_text(encoding="utf-8")


def test_cancelled_or_failed_job_never_removes_previous_video(tmp_path, monkeypatch):
    audio = _audio(tmp_path / "audio.wav")
    previous = tmp_path / P.EXPORTS_DIR / "rev-1-full-old" / "karaoke.mp4"
    previous.parent.mkdir(parents=True); previous.write_bytes(b"old-good-video")
    p = song()
    def fail(*args, **kwargs):
        raise RuntimeError("fixture encoder failure")
    monkeypatch.setattr(S, "render_project", fail)
    done = _wait(J.start(p, tmp_path, audio).id)
    assert done.status == "failed" and "fixture encoder failure" in done.error
    assert previous.read_bytes() == b"old-good-video"
    assert not list((tmp_path / P.EXPORTS_DIR).glob(".job-*.tmp"))


def test_cancel_running_job_keeps_previous_video(tmp_path, monkeypatch):
    import threading
    audio = _audio(tmp_path / "audio.wav")
    previous = tmp_path / P.EXPORTS_DIR / "rev-1-full-old" / "karaoke.mp4"
    previous.parent.mkdir(parents=True); previous.write_bytes(b"old-good-video")
    entered = threading.Event()
    def wait_for_cancel(project, root, audio, destination, *, progress, cancel, allow_timing_issues):
        Path(destination).mkdir(parents=True, exist_ok=True)
        entered.set()
        assert cancel.wait(5)
        raise RuntimeError("Video export cancelled.")
    monkeypatch.setattr(S, "render_project", wait_for_cancel)
    job = J.start(song(), tmp_path, audio)
    assert entered.wait(5) and J.cancel(job.id)
    done = _wait(job.id)
    assert done.status == "cancelled"
    assert previous.read_bytes() == b"old-good-video"
    assert not list((tmp_path / P.EXPORTS_DIR).glob(".job-*.tmp"))


def test_status_save_retries_a_windows_file_lock(tmp_path, monkeypatch):
    atomic_write = P._atomic_write
    attempts = []
    def briefly_locked(path, content):
        attempts.append(path)
        if len(attempts) < 3:
            raise PermissionError("[WinError 5] Access is denied")
        atomic_write(path, content)
    monkeypatch.setattr(P, "_atomic_write", briefly_locked)
    job = J.ExportJob("retry", "song", 1, "full")
    J._save(tmp_path, job)
    record = J.recover(tmp_path)[0]
    assert len(attempts) == 3
    assert record["id"] == job.id
    assert "_last_saved_at" not in record


@pytest.mark.media
def test_progress_storage_failure_keeps_rendering_and_preserves_completed_video(tmp_path, monkeypatch):
    audio = _audio(tmp_path / "audio.wav")
    p = song(); S.apply_style(p, {"video": {"resolution": "320x180"}})
    save = J._save
    def unavailable_after_start(root, job):
        if job.status != "queued":
            raise PermissionError("[WinError 5] Access is denied")
        save(root, job)
    monkeypatch.setattr(J, "_save", unavailable_after_start)
    done = _wait(J.start(p, tmp_path, audio).id)
    assert done.status == "complete", done.error
    assert done.progress == 1 and done.status_warning
    output = Path(done.output_path)
    assert output.is_file() and output.stat().st_size > 1000
    assert (output.parent / "export-manifest.json").is_file()
    assert not list((tmp_path / P.EXPORTS_DIR).glob(".job-*.tmp"))


def test_failed_initial_job_save_does_not_leave_a_phantom_running_export(tmp_path, monkeypatch):
    audio = _audio(tmp_path / "audio.wav")
    p = song(); p.id = P.new_id("project")
    save = J._save
    def denied(*args):
        raise PermissionError("Cannot create job record")
    monkeypatch.setattr(J, "_save", denied)
    with pytest.raises(PermissionError):
        J.start(p, tmp_path, audio)
    assert not any(job.project_id == p.id for job in J._jobs.values())
    monkeypatch.setattr(J, "_save", save)
    done = _wait(J.start(p, tmp_path, audio).id)
    assert done.status == "complete", done.error
