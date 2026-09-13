"""Failure reporting must prevent a broken install being labelled ready."""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from heartbeam import doctor


@pytest.mark.skipif(shutil.which("powershell") is None, reason="Windows launcher test")
@pytest.mark.parametrize("receipt", [None, {"schema_version": 1, "variant": "Editor", "ready": False}])
def test_launcher_refuses_missing_or_interrupted_install(tmp_path, receipt):
    if receipt is not None:
        (tmp_path / "heartbeam-install.json").write_text(json.dumps(receipt))
    script = Path(__file__).parents[1] / "scripts" / "start.ps1"
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-InstallDir", str(tmp_path)], capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert "install.ps1" in result.stderr


def _mock_editor(monkeypatch):
    monkeypatch.setattr(doctor.sys, "version_info", (3, 12, 10))
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: SimpleNamespace())
    monkeypatch.setattr(doctor.metadata, "version", lambda name: "1.57.0")
    monkeypatch.setattr(doctor.shutil, "which", lambda name: name)

    def run(args, timeout=60):
        if "-filters" in args:
            return " ... ass V->V subtitles "
        if "-encoders" in args:
            return "libx264 libmp3lame aac"
        return "OK"
    monkeypatch.setattr(doctor, "_run", run)


def test_editor_check_does_not_require_ml(monkeypatch):
    _mock_editor(monkeypatch)
    names = []
    monkeypatch.setattr(doctor.importlib, "import_module", lambda name: names.append(name))
    assert doctor.diagnose("Editor")["ok"]
    assert not any(name.startswith(("torch", "whisper", "audio_separator")) for name in names)


def test_missing_ffmpeg_is_a_failure(monkeypatch):
    _mock_editor(monkeypatch)
    monkeypatch.setattr(doctor.shutil, "which", lambda name: None)
    report = doctor.diagnose("Editor")
    assert not report["ok"]
    assert not next(c for c in report["checks"] if c["name"] == "FFmpeg and codecs")["ok"]


def test_missing_pyarrow_is_a_failure_but_other_checks_continue(monkeypatch):
    _mock_editor(monkeypatch)

    def imports(name):
        if name == "pyarrow":
            raise ModuleNotFoundError("pyarrow")
    monkeypatch.setattr(doctor.importlib, "import_module", imports)
    report = doctor.diagnose("Editor")
    assert not report["ok"]
    assert any("pyarrow" in item["detail"] for item in report["checks"] if not item["ok"])
    assert report["checks"][-1]["ok"]


def test_dependency_conflict_sets_failure_exit_and_saves_report(monkeypatch, tmp_path):
    _mock_editor(monkeypatch)
    original = doctor._run

    def run(args, timeout=60):
        if args[-2:] == ["pip", "check"]:
            raise RuntimeError("dependency conflict")
        return original(args, timeout)
    monkeypatch.setattr(doctor, "_run", run)
    destination = tmp_path / "report.json"
    assert doctor.main(["--variant", "Editor", "--json", str(destination)]) == 1
    assert '"ok": false' in destination.read_text()


def test_failed_model_download_returns_nonzero_after_attempting_other_steps(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location("fetch_models", Path(__file__).parents[1] / "scripts" / "fetch_models.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    calls = []

    def separator(names):
        calls.append("separator")
        raise RuntimeError("download interrupted")
    monkeypatch.setattr(module, "fetch_separator_models", separator)
    monkeypatch.setattr(module, "fetch_whisper", lambda name: calls.append("whisper"))
    monkeypatch.setattr(module, "fetch_aligner", lambda name: calls.append("aligner"))
    monkeypatch.setattr(module.paths, "apply_env", lambda: None)
    monkeypatch.setattr(module.sys, "argv", ["fetch_models.py"])
    assert module.main() == 1
    assert calls == ["separator", "whisper", "aligner"]
    assert "=== Done ===" not in capsys.readouterr().out
