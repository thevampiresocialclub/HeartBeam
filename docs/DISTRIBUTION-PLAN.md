# GitHub distribution and maintenance

Decision: maintain HeartBeam on GitHub and let friends use a local coding agent to install the checked-out revision. A standalone installer, remote ML bridge and cloud website are parked ideas, not shipped features.

## Current deliverables

- `INSTALL-WITH-AN-AGENT.md`: installation, hardware choices, models, diagnostics, smoke tests, updates and troubleshooting.
- `scripts/install.ps1`: Windows x64 / Python 3.12 setup, known dependency constraints, explicit CUDA wheels, consistent install locations and required failure checks.
- `heartbeam.doctor`: dependency/import/asset/FFmpeg checks and GPU diagnostics.
- `scripts/start.ps1` and shortcuts: launch the installed environment with its saved FFmpeg location.
- `scripts/fetch_models.py`: default Pop downloads and a nonzero result if required downloads fail.
- `requirements/windows-py312.txt`: known package versions. Constraints are not a fully hashed offline dependency lock.

## Release evidence

See BUILD-STATUS.md for the concrete checks completed for a given commit. A clean Editor installation does not certify a clean GPU installation. Imports and registered ONNX providers do not replace a real-model smoke test. No new standalone installer or two-PC bridge has been built.

## Maintenance sequence

1. Keep a recommended, identified revision available for friends. Keep code separate from personal projects, models and diagnostic reports.
2. Run the installation checks and regressions before changing dependencies. Update the agent instructions whenever supported setup behavior changes.
3. Test preparation and export on real hardware before claiming support. Record cold/warm model behavior and any unresolved failures.
4. Push reviewed source changes to the intended GitHub repository. Keep sample media appropriate for redistribution; never publish secrets or model caches.
5. Friends update their clean checkout, rerun constrained setup, then diagnostics. Preserve user files and pause active jobs before updating.

Friends without a compatible NVIDIA GPU can use Editor mode with an already-prepared project. The agent subscription itself does not provide HeartBeam's GPU processing.
