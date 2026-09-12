"""Portable filenames, independent of each immutable export folder."""
import json
import re
from pathlib import Path, PureWindowsPath

from .paths import safe_file_stem


def video_filename(value: str) -> str:
    name = value.strip()
    if not name or re.search(r'[<>:"/\\|?*\x00-\x1f]', name) or name.endswith('.'):
        raise ValueError('Enter a video filename without folders or special characters.')
    if not name.lower().endswith('.mp4'):
        name += '.mp4'
    stem = name[:-4]
    if not stem or stem != safe_file_stem(stem) or len(name) > 180:
        raise ValueError('Choose a shorter, valid video filename (for example My song_karaoke.mp4).')
    return name


def default_video_filename(project, root) -> str:
    source = project.provenance.settings.get('input_filename')
    if not source and project.imported_timings_path:
        try:
            legacy = json.loads((Path(root) / project.imported_timings_path).read_text(encoding='utf-8'))
            source = legacy.get('source', {}).get('audio_path')
        except (OSError, ValueError, TypeError):
            pass
    # PureWindowsPath also understands forward slashes on other hosts.
    stem = PureWindowsPath(source).stem if source else project.name
    return safe_file_stem(stem) + '_karaoke.mp4'
