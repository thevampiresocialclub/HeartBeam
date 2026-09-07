"""P03.2 audition assets and small, served editor payloads.

Streamlit's existing /media endpoint supports byte ranges. Keep this private
API behind one adapter, register on EVERY script run (session references are
cleared between runs), and never send audio in component JSON. Streamlit still
holds registered media in RAM; this removes base64/websocket duplication, not
the server's media-memory cost.
"""
from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Callable

from . import project as P
from . import waveform as wf

SOURCE_ROLES = (("karaoke", "Karaoke", "karaoke_audio"),
                ("original", "Original", "original_audio"),
                ("lead", "Lead vocal", "lead_stem"))


def attach_cached_audio(project: P.Project, project_dir: Path,
                        cache_dir: Path) -> int:
    """Explicitly copy a verified common-basis cache into durable project assets.

    Used when adopting a fresh pipeline run, or through the user's Link cached
    tracks action. Never invoked merely by selecting or playing a word.
    """
    import soundfile as sf
    from . import audio_cache as ac

    manifest = ac.load_cache(cache_dir)
    if manifest is None:
        raise P.ProjectError("No usable audio_cache.json in that folder.")
    mappings = {"original": "original_audio", "lead": "lead_stem",
                "backing": "backing_stem", "instrumental": "instrumental_stem",
                "clean": "clean_audio"}
    checked = []
    basis = None
    for role, asset_role in mappings.items():
        entry = manifest.entries.get(role)
        if entry is None:
            continue
        path = (cache_dir / entry.path).resolve()
        if not path.is_relative_to(cache_dir.resolve()) or not path.is_file():
            raise P.ProjectError(f"Cached {role} is missing or outside its cache folder.")
        info = sf.info(str(path))
        actual = (info.samplerate, info.channels, info.frames)
        expected = (entry.sample_rate, entry.channels, entry.sample_count)
        if actual != expected or (basis is not None and actual != basis):
            raise P.ProjectError(f"Cached {role} does not share the declared audio basis.")
        basis = actual
        checked.append((path, asset_role, entry))
    if not checked:
        raise P.ProjectError("The cache contains no audition tracks.")
    # Duration catches obvious mismatches; it cannot establish song identity.
    # Legacy projects have no source hash, so the user explicitly chooses the
    # matching run. Retain that provenance for subsequent consumers.
    karaoke = project.asset_by_role("karaoke_audio")
    if karaoke and karaoke.resolve(project_dir).is_file():
        info = sf.info(str(karaoke.resolve(project_dir)))
        if abs(info.duration - basis[2] / basis[0]) > 0.030:
            raise P.ProjectError("Cached tracks and karaoke differ in duration by more than 30 ms.")
    destinations = set()
    for path, role, entry in checked:
        existing = project.asset_by_role(role)
        if existing is not None:
            raise P.ProjectError(f"Project already has {role}; relink it instead of duplicating it.")
        destination = (project_dir / P.AUDIO_DIR / path.name).resolve()
        if destination in destinations or (destination.exists() and destination != path):
            raise P.ProjectError(f"Audio filename {path.name} is already in this project; nothing was overwritten.")
        destinations.add(destination)
    for path, role, entry in checked:
        asset = P.add_asset(project, project_dir, path, role, copy_into_project=True)
        asset.sample_rate = entry.sample_rate
        asset.channels = entry.channels
        asset.sample_count = entry.sample_count
        asset.duration_ms = P.seconds_to_ms(entry.sample_count / entry.sample_rate)
    project.provenance.settings["audition_cache_source_sha256"] = manifest.source_sha256
    if project.asset_by_role("original_audio") and project.asset_by_role("clean_audio"):
        from .vocal_mix import bind_references
        bind_references(project, source_sha256=manifest.source_sha256, recipe=manifest.settings)
    return len(checked)


def source_files(project: P.Project, project_dir: Path,
                 karaoke_path: Path) -> list[dict]:
    """Resolve explicit assets; missing choices remain visible with a reason."""
    result = []
    for source_id, label, role in SOURCE_ROLES:
        asset = project.asset_by_role(role)
        path = (asset.resolve(project_dir) if asset else
                karaoke_path if source_id == "karaoke" else None)
        available = path is not None and path.is_file()
        result.append({"id": source_id, "label": label, "path": path,
                       "available": available,
                       "reason": "" if available else (
                           "File is missing; relink it in the project sidebar." if asset else
                           "No saved track; link the audio cache from a generation run.")})
    return result


def prepare_waveforms(path: Path, cache_dir: Path, *,
                      levels: tuple[int, ...] = wf.PEAK_LEVELS) -> dict:
    """Decode once on cache misses, then serve requested resolutions as JSON.

    Size + nanosecond mtime invalidate on ordinary file replacement. A fresh
    cache import/relink also changes the saved asset hash. These are audition
    caches, not the engine's stronger source/model provenance validation.
    """
    import soundfile as sf
    info = sf.info(str(path))
    stat = path.stat()
    key = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    samples = None

    def provider():
        nonlocal samples
        if samples is None:
            samples, _ = sf.read(str(path), dtype="float32", always_2d=False)
        return samples

    peaks = []
    for buckets in levels:
        value = wf.load_or_compute(cache_dir, key, provider, info.samplerate, buckets)
        peaks.append({"buckets": value.buckets,
                      "path": cache_dir / wf._cache_name(key, buckets)})
    return {"key": key, "duration_ms": P.seconds_to_ms(info.duration),
            "levels": peaks}


def register_media(path: Path, coordinates: str) -> str:
    """Version-tested adapter to Streamlit's own same-origin range endpoint."""
    from streamlit import runtime
    if not runtime.exists():
        # AppTest has no HTTP server. Its media URLs are intentionally inert;
        # unit/media tests exercise registration with a real/fake manager.
        return "/media/unavailable-in-apptest"
    mime = {".json": "application/json", ".js": "application/javascript", ".wasm": "application/wasm", ".ttf": "font/ttf"}.get(path.suffix) or (
        mimetypes.guess_type(path.name)[0] or "audio/wav")
    return runtime.get_instance().media_file_mgr.add(str(path), mime, coordinates)


def build_sources(project: P.Project, project_dir: Path, karaoke_path: Path,
                  *, prepare: Callable = prepare_waveforms,
                  register: Callable = register_media) -> list[dict]:
    """URLs and metadata only; no audio or high-resolution peak arrays inline."""
    sources = source_files(project, project_dir, karaoke_path)
    result = []
    duration = None
    for source in sources:
        item = {k: v for k, v in source.items() if k != "path"}
        if source["available"]:
            try:
                path = source["path"]
                wave = prepare(path, project_dir / P.CACHE_DIR / "waveforms")
                if duration is None:
                    duration = wave["duration_ms"]
                if abs(wave["duration_ms"] - duration) > 30:
                    raise ValueError("Track duration differs from karaoke by more than 30 ms.")
                coord = f"heartbeam/{project.id}/{source['id']}"
                item.update(key=wave["key"], src=register(path, coord),
                            duration_ms=wave["duration_ms"],
                            levels=[{"buckets": level["buckets"],
                                     "src": register(level["path"], f"{coord}/peaks/{level['buckets']}")}
                                    for level in wave["levels"]])
            except (OSError, ValueError, RuntimeError) as exc:
                item.update(available=False, reason=str(exc))
        result.append(item)
    return result
