# Dependency baseline

`windows-py312.txt` constrains the Windows x64 / Python 3.12 setup. It records the working environment's package versions, with PyArrow added to satisfy Streamlit and explicit build tools. CUDA/CPU wheel variants are selected by `scripts/install.ps1`.

Constraints do not install every listed package: Editor mode installs only the core and GUI dependency graph. They also are not a hash-locked wheel archive. New transitive dependencies, build isolation and model downloads still require validation. No Linux/macOS lock or full offline installer is claimed.

## ONNX Runtime packaging workaround

The pinned faster-whisper requires `onnxruntime` by distribution name, while audio-separator's GPU extra requires `onnxruntime-gpu`. Both distributions write the same Python module. A clean install exposed the CPU payload winning, despite `pip check` passing. Upstream [recommends one runtime package per environment](https://onnxruntime.ai/docs/get-started/with-python.html); the current dependency metadata prevents satisfying both packages that way without patching or splitting them.

For this baseline, the GPU installer restores the pinned GPU wheel **after** dependency resolution using `--force-reinstall --no-deps`. Both distribution records remain to satisfy their dependents, and doctor requires a real ONNX CUDA calculation with CPU fallback disabled. This is a tested compatibility workaround, not an upstream-supported dual-runtime configuration. Do not uninstall or independently upgrade either runtime: their files overlap. Rerun the complete installer after dependency changes. A future dependency refresh should remove this workaround when upstream metadata allows one runtime.

To maintain this baseline: create an isolated environment, resolve the intended change, run `pip check`, the regression suite and an appropriate real-model/browser smoke test, then review and commit the constraints with the verification evidence. Never replace the file with a blind freeze containing an editable local path, credentials or unrelated packages.
