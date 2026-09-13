"""Small, explicit bridges from the local web UI to the desktop shell."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


class DesktopError(RuntimeError):
    pass


def _open_command(path: Path) -> list[str]:
    if os.name == "nt":
        return ["explorer.exe", str(path)]
    if sys.platform == "darwin":
        return ["open", str(path)]
    return ["xdg-open", str(path)]


def _reveal_command(path: Path) -> list[str]:
    if os.name == "nt":
        return ["explorer.exe", "/select,", str(path)]
    if sys.platform == "darwin":
        return ["open", "-R", str(path)]
    return ["xdg-open", str(path.parent)]


def _launch(command: list[str]) -> None:
    try:
        subprocess.Popen(command, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise DesktopError(f"Windows could not open that location: {exc}") from exc


def open_folder(path: str | Path) -> Path:
    folder = Path(path).expanduser().resolve()
    if not folder.is_dir():
        raise DesktopError(f"Folder not found: {folder}")
    _launch(_open_command(folder))
    return folder


def reveal_file(path: str | Path) -> Path:
    file = Path(path).expanduser().resolve()
    if not file.is_file():
        raise DesktopError(f"File not found: {file}")
    _launch(_reveal_command(file))
    return file


_PICK_PROJECT = r'''import sys
import tkinter as tk
from tkinter import filedialog
root = tk.Tk()
root.withdraw()
root.attributes("-topmost", True)
chosen = filedialog.askopenfilename(
    title="Open HeartBeam project",
    initialdir=sys.argv[1],
    filetypes=(("HeartBeam project", "project.json"), ("JSON files", "*.json")),
)
root.destroy()
if chosen:
    print(chosen)
'''


def choose_project_file(initial_dir: str | Path) -> Path | None:
    """Open the native picker in a separate process; return only on a click."""
    initial = Path(initial_dir).expanduser().resolve()
    try:
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-c", _PICK_PROJECT, str(initial)],
            stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
            timeout=300, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DesktopError(f"The project picker could not open: {exc}") from exc
    if result.returncode:
        detail = result.stderr.strip() or "the desktop picker is unavailable"
        raise DesktopError(f"The project picker could not open: {detail}")
    raw = result.stdout.strip()
    if not raw:
        return None
    path = Path(raw).resolve()
    if path.name.casefold() != "project.json" or not path.is_file():
        raise DesktopError("Choose a HeartBeam project.json file.")
    return path
