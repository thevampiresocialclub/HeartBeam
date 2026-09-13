"""Read-only installation diagnostics; never downloads models or edits projects."""
from __future__ import annotations

import argparse
import importlib
import importlib.metadata as metadata
import json
import platform
import shutil
import struct
import subprocess
import sys
from pathlib import Path


def _run(args: list[str], timeout: int = 60) -> str:
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                            encoding="utf-8", errors="replace")
    output = (result.stdout + result.stderr).strip()
    if result.returncode:
        raise RuntimeError(output[-4000:] or f"Process exited with {result.returncode}")
    return output


def diagnose(variant: str = "GPU") -> dict:
    checks = []

    def check(name, operation):
        try:
            detail = operation()
            checks.append(dict(name=name, ok=True, detail=str(detail)))
        except Exception as exc:
            checks.append(dict(name=name, ok=False, detail=f"{type(exc).__name__}: {exc}"))

    def python_version():
        if sys.version_info[:2] != (3, 12) or struct.calcsize("P") != 8:
            raise RuntimeError("The Windows setup baseline requires 64-bit Python 3.12.")
        return f"Python {platform.python_version()} ({sys.executable})"

    check("Python", python_version)
    check("Dependency consistency", lambda: _run([sys.executable, "-m", "pip", "check"]))

    def imports():
        for name in ("numpy", "scipy", "soundfile", "mutagen", "pyarrow", "streamlit", "heartbeam.gui"):
            importlib.import_module(name)
        if metadata.version("streamlit") != "1.57.0":
            raise RuntimeError("The editor's tested Streamlit version is 1.57.0.")
        return "Editor, audio libraries and PyArrow import successfully."

    check("Application imports", imports)

    def assets():
        root = Path(__file__).parent
        required = [root / "editor_assets" / name for name in
                    ("timeline.js", "timeline.css", "workstation.js", "workstation.css",
                     "presentation.js", "audio_transport.js")]
        # Renderer filenames may change; require its shipped WASM and fonts.
        if not list((root / "editor_assets" / "vendor").glob("*.wasm")):
            raise RuntimeError("Bundled subtitle renderer WASM is missing.")
        if not list((root / "editor_assets" / "vendor").glob("*.ttf")):
            raise RuntimeError("Bundled preview font is missing.")
        missing = [str(path.name) for path in required if not path.is_file()]
        if missing:
            raise RuntimeError(f"Missing editor assets: {', '.join(missing)}")
        return "Editor scripts, styles, renderer and fonts are present."

    check("Packaged assets", assets)

    def ffmpeg():
        executable = shutil.which("ffmpeg")
        probe = shutil.which("ffprobe")
        if not executable or not probe:
            raise RuntimeError("Both ffmpeg and ffprobe must be on this process's PATH.")
        version = _run([executable, "-version"]).splitlines()[0]
        _run([probe, "-version"])
        filters = _run([executable, "-hide_banner", "-filters"])
        encoders = _run([executable, "-hide_banner", "-encoders"])
        if " ass " not in filters and " subtitles " not in filters:
            raise RuntimeError("FFmpeg lacks libass subtitle rendering.")
        for encoder in ("libx264", "libmp3lame", "aac"):
            if encoder not in encoders:
                raise RuntimeError(f"FFmpeg lacks required encoder {encoder}.")
        return version

    check("FFmpeg and codecs", ffmpeg)

    if variant != "Editor":
        def ml_imports():
            for name in ("audio_separator.separator", "whisperx", "ctranslate2", "onnxruntime"):
                importlib.import_module(name)
            return "Separation and alignment libraries import successfully."
        check("ML imports", ml_imports)

    if variant == "GPU":
        def cuda():
            import torch
            if not torch.cuda.is_available():
                raise RuntimeError("CUDA is unavailable. Check the NVIDIA driver and cu128 Torch build.")
            values = torch.arange(16, device="cuda", dtype=torch.float32)
            total = (values * values).sum().item()
            torch.cuda.synchronize()
            if total != 1240:
                raise RuntimeError("CUDA calculation returned an unexpected result.")
            device = torch.cuda.get_device_properties(0)
            return f"{device.name}; {device.total_memory / 1024**3:.1f} GiB; torch {torch.__version__}; CUDA calculation passed."
        check("CUDA execution", cuda)

        def onnx_cuda():
            import numpy as np
            import onnx
            import onnxruntime as ort
            import torch  # Preload the matching CUDA/cuDNN DLLs on Windows.
            providers = ort.get_available_providers()
            if "CUDAExecutionProvider" not in providers:
                raise RuntimeError(f"ONNX CUDA provider missing: {providers}")
            graph = onnx.helper.make_graph(
                [onnx.helper.make_node("Add", ["a", "b"], ["sum"])], "cuda-check",
                [onnx.helper.make_tensor_value_info(name, onnx.TensorProto.FLOAT, [4])
                 for name in ("a", "b")],
                [onnx.helper.make_tensor_value_info("sum", onnx.TensorProto.FLOAT, [4])])
            model = onnx.helper.make_model(graph, opset_imports=[onnx.helper.make_opsetid("", 17)])
            model.ir_version = 10
            options = ort.SessionOptions()
            options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
            session = ort.InferenceSession(model.SerializeToString(), sess_options=options,
                                           providers=["CUDAExecutionProvider"])
            if "CUDAExecutionProvider" not in session.get_providers():
                raise RuntimeError("ONNX session fell back from CUDA.")
            values = np.arange(4, dtype=np.float32)
            output = session.run(None, {"a": values, "b": values})[0]
            if not np.array_equal(output, values * 2):
                raise RuntimeError("ONNX CUDA calculation returned an unexpected result.")
            return "ONNX CUDA calculation passed with CPU fallback disabled."
        check("ONNX CUDA execution", onnx_cuda)

    ok = all(item["ok"] for item in checks)
    return dict(schema_version=1, variant=variant, ok=ok, checks=checks,
                limitations=["Does not download or run model weights; complete a short-song smoke test before sharing."] +
                (["Editor mode cannot prepare audio or automatically rematch lyrics."] if variant == "Editor" else []) +
                (["CPU ML is experimental and requires --allow-cpu in the processing CLI."] if variant == "CPU" else []))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--variant", choices=("GPU", "CPU", "Editor"), default="GPU")
    parser.add_argument("--json", type=Path, help="Also save the diagnostic report to this file.")
    args = parser.parse_args(argv)
    report = diagnose(args.variant)
    for item in report["checks"]:
        print(f"[{'OK' if item['ok'] else 'FAIL'}] {item['name']}: {item['detail']}")
    for limitation in report["limitations"]:
        print(f"[NOTE] {limitation}")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
