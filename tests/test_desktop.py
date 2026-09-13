from pathlib import Path
from types import SimpleNamespace

import pytest

from heartbeam import desktop


def test_windows_folder_and_file_actions_use_exact_nonshell_arguments(tmp_path, monkeypatch):
    folder = tmp_path / "folder with spaces"
    folder.mkdir()
    file = folder / "Café video.mp4"
    file.write_bytes(b"video")
    calls = []
    monkeypatch.setattr(desktop.os, "name", "nt")
    monkeypatch.setattr(desktop.subprocess, "Popen",
                        lambda command, **kwargs: calls.append((command, kwargs)))

    desktop.open_folder(folder)
    desktop.reveal_file(file)

    assert calls[0][0] == ["explorer.exe", str(folder.resolve())]
    assert calls[1][0] == ["explorer.exe", "/select,", str(file.resolve())]
    assert all("shell" not in kwargs for _, kwargs in calls)


def test_missing_or_unlaunchable_desktop_targets_report_clearly(tmp_path, monkeypatch):
    with pytest.raises(desktop.DesktopError, match="Folder not found"):
        desktop.open_folder(tmp_path / "missing")
    folder = tmp_path / "exists"
    folder.mkdir()
    monkeypatch.setattr(desktop.subprocess, "Popen",
                        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("blocked")))
    with pytest.raises(desktop.DesktopError, match="blocked"):
        desktop.open_folder(folder)


def test_project_picker_uses_utf8_and_accepts_only_project_manifest(tmp_path, monkeypatch):
    project = tmp_path / "Café" / "project.json"
    project.parent.mkdir()
    project.write_text("{}")
    captured = {}

    def run(command, **kwargs):
        captured.update(command=command, kwargs=kwargs)
        return SimpleNamespace(returncode=0, stdout=str(project) + "\n", stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    assert desktop.choose_project_file(tmp_path) == project.resolve()
    assert captured["command"][1:3] == ["-X", "utf8"]
    assert captured["kwargs"]["encoding"] == "utf-8"
    assert "shell" not in captured["kwargs"]

    wrong = tmp_path / "other.json"
    wrong.write_text("{}")
    monkeypatch.setattr(desktop.subprocess, "run", lambda *a, **k:
                        SimpleNamespace(returncode=0, stdout=str(wrong), stderr=""))
    with pytest.raises(desktop.DesktopError, match="project.json"):
        desktop.choose_project_file(tmp_path)
