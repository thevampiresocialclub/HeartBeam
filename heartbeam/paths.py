"""Portable cache locations for model weights.

Three separate libraries download multi-GB checkpoints, each with its own cache
root and its own environment variable. This module pins all three to one place
so a cache can be pre-seeded on a fast machine and copied to a slow one.

Why this exists: audio-separator's default `model_file_dir` is the hardcoded
POSIX string ``/tmp/audio-separator-models/``. On Windows that is *drive*-
relative, not %TEMP% — it resolves to ``C:\\tmp\\...`` when the working
directory is on C:, but ``D:\\tmp\\...`` from a D: drive. A pre-seeded cache
silently misses and re-downloads ~2 GB the first time you run from elsewhere.

Layout under the root (see scripts/fetch_models.py, which populates it):

    <root>/separator/   UVR checkpoints  (AUDIO_SEPARATOR_MODEL_DIR)
    <root>/hf/          faster-whisper   (HF_HOME)
    <root>/torch/       wav2vec2 aligner (TORCH_HOME)
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

#: Set this to relocate every cache at once — the one knob users need.
ROOT_ENV = "HEARTBEAM_MODEL_ROOT"


def data_root() -> Path:
    """User work lives outside the installation and OS temporary directory."""
    configured = os.environ.get("HEARTBEAM_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    documents = Path.home() / "Documents"
    if os.name == "nt":
        # Honour redirected Documents folders (including OneDrive).
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as key:
                documents = Path(os.path.expandvars(winreg.QueryValueEx(key, "Personal")[0]))
        except OSError:
            pass
    return documents / "HeartBeam"


def projects_dir() -> Path:
    return data_root() / "Projects"


def safe_file_stem(value: str, fallback="Untitled song") -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip(' .')[:120].rstrip(' .')
    if not stem:
        stem = fallback
    if stem.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
            *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        stem = '_' + stem
    return stem


def new_session(song_name: str) -> Path:
    """Keep resumable preparation output until the user deliberately removes it."""
    folder = data_root() / "Sessions"
    folder.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=safe_file_stem(song_name) + '-', dir=folder))


def model_root() -> Path:
    """Base directory holding every downloaded model.

    Honours $HEARTBEAM_MODEL_ROOT, else ~/.heartbeam/models on every platform.

    Deliberately NOT %LOCALAPPDATA% on Windows. Python installed from the
    Microsoft Store runs under MSIX filesystem virtualization, which silently
    redirects writes to %LOCALAPPDATA% into

        %LOCALAPPDATA%\\Packages\\PythonSoftwareFoundation.Python.3.12_<hash>\\LocalCache\\Local\\

    The interpreter still *reports* the nominal path, so a multi-GB cache lands
    somewhere Explorer, PowerShell, and any non-Store Python cannot see — which
    would quietly break "copy this folder to the other machine". The user
    profile root is outside the redirection scope, so it behaves identically for
    Store, python.org, and winget installs.
    """
    env = os.environ.get(ROOT_ENV)
    if env:
        return Path(env).expanduser()
    return Path.home() / ".heartbeam" / "models"


def separator_dir() -> Path:
    """Where audio-separator keeps UVR checkpoints."""
    return model_root() / "separator"


def hf_home() -> Path:
    """HF_HOME — faster-whisper's CTranslate2 models live under here in hub/."""
    return model_root() / "hf"


def torch_home() -> Path:
    """TORCH_HOME — torchaudio's wav2vec2 aligner lands in hub/checkpoints/."""
    return model_root() / "torch"


def apply_env(create: bool = True) -> dict[str, str]:
    """Point every model-downloading library at our cache root.

    Call once, early, before any ML import — these libraries read their cache
    environment variables at import time. Pre-existing values are respected so
    a user who has already curated $HF_HOME keeps it.

    Returns the variables this call actually set (for logging).
    """
    wanted = {
        "AUDIO_SEPARATOR_MODEL_DIR": separator_dir(),
        "HF_HOME": hf_home(),
        "TORCH_HOME": torch_home(),
    }
    applied: dict[str, str] = {}
    for key, path in wanted.items():
        if os.environ.get(key):
            continue  # user knows better
        if create:
            # audio-separator raises FileNotFoundError if its dir is missing.
            path.mkdir(parents=True, exist_ok=True)
        os.environ[key] = str(path)
        applied[key] = str(path)
    return applied
