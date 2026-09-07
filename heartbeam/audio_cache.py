"""Lossless audio cache: the reusable foundation under the later editors.

Implements P01.3 and sections 6 and 8 of `08-SHARED-CONTRACT.md`.

The point is that adjusting a vocal level, a font or a word's timing must never
rerun separation. That is only possible if the expensive intermediate audio
survives the run, on a common sample basis, with enough provenance to know when
it has gone stale.

Five roles are cached:

    original       the decoded source, before any processing
    lead           isolated lead vocal stem
    backing        isolated backing vocal stem
    instrumental   instrumental stem
    clean          the processed karaoke mix BEFORE loudness normalisation
                   and before clipping

`clean` is the one that matters most and the one the old pipeline threw away.
P04's section mixer blends `clean + restore * (original - clean)`, which only
reaches the original at restore=1 if `clean` is captured at the same gain
reference as `original` -- i.e. before mastering. Reconstructing it from the
normalised MP3 would make the scale inconsistent and add encoding loss.

**Validity.** A manifest records the source audio hash and a fingerprint of the
processing settings. `is_valid()` compares both; a mismatch means the cache
describes different work and must not be reused. The manifest is written last,
so an interrupted run leaves no manifest and the cache simply reads as absent
rather than as valid-but-wrong.

**Format.** WAV float32 by default: bit-exact, no quantisation question to argue
about later. Stereo 44.1 kHz float32 costs about 21 MB per minute per role, so a
full five-role set for a 3.5-minute song is roughly 345 MB (measured: 344 MB for
the 3:27 test fixture). `flac` (24-bit) is available for about 40% of that, at
the cost of no longer being bit-exact against the float pipeline.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf

CACHE_SCHEMA_VERSION = 1
MANIFEST_NAME = "audio_cache.json"

#: Roles cached by a full pipeline run.
ROLES = ("original", "lead", "backing", "instrumental", "clean")

FORMATS = {
    "wav": {"suffix": ".wav", "format": "WAV", "subtype": "FLOAT"},
    "flac": {"suffix": ".flac", "format": "FLAC", "subtype": "PCM_24"},
}


class CacheError(Exception):
    pass


@dataclass
class CachedAudio:
    role: str
    path: str                 # relative to the cache directory
    sample_rate: int
    channels: int
    sample_count: int
    sha256: str


@dataclass
class CacheManifest:
    schema_version: int = CACHE_SCHEMA_VERSION
    source_sha256: str = ""
    settings_fingerprint: str = ""
    sample_rate: int = 0
    audio_format: str = "wav"
    entries: dict[str, CachedAudio] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "settings_fingerprint": self.settings_fingerprint,
            "sample_rate": self.sample_rate,
            "audio_format": self.audio_format,
            "entries": {k: asdict(v) for k, v in self.entries.items()},
            "provenance": self.provenance,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CacheManifest":
        sv = int(d.get("schema_version", -1))
        if sv != CACHE_SCHEMA_VERSION:
            raise CacheError(
                f"unsupported audio cache schema_version {sv} "
                f"(this build reads {CACHE_SCHEMA_VERSION})"
            )
        return cls(
            schema_version=sv,
            source_sha256=d.get("source_sha256", ""),
            settings_fingerprint=d.get("settings_fingerprint", ""),
            sample_rate=int(d.get("sample_rate", 0)),
            audio_format=d.get("audio_format", "wav"),
            entries={k: CachedAudio(**v) for k, v in d.get("entries", {}).items()},
            provenance=d.get("provenance", {}),
        )


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def settings_fingerprint(settings: dict[str, Any]) -> str:
    """Stable hash of the settings that determine the cached audio.

    Only include things that change the audio. Style, placement and export
    settings must NOT be here, or restyling would invalidate the stems and
    trigger a needless re-separation.
    """
    canonical = json.dumps(settings, sort_keys=True, separators=(",", ":"),
                           default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _array_sha256(a: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(a, dtype=np.float32).tobytes()).hexdigest()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".json")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_cache(cache_dir: str | Path, arrays: dict[str, np.ndarray], *,
                sample_rate: int, source_sha256: str,
                settings: dict[str, Any],
                provenance: dict[str, Any] | None = None,
                audio_format: str = "wav") -> CacheManifest:
    """Write the cached audio, then the manifest last.

    Writing the manifest last is the whole interruption story: a run killed
    halfway leaves audio files with no manifest, and `load_cache` reports the
    cache as absent rather than trusting a partial set.
    """
    if audio_format not in FORMATS:
        raise CacheError(f"unknown audio format {audio_format!r}; "
                         f"expected one of {sorted(FORMATS)}")
    spec = FORMATS[audio_format]
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)

    # A stale manifest must not survive a rewrite that fails partway.
    manifest_path = root / MANIFEST_NAME
    manifest_path.unlink(missing_ok=True)

    entries: dict[str, CachedAudio] = {}
    for role, array in arrays.items():
        a = np.ascontiguousarray(array, dtype=np.float32)
        name = f"{role}{spec['suffix']}"
        target = root / name
        sf.write(str(target), a, sample_rate,
                 format=spec["format"], subtype=spec["subtype"])
        entries[role] = CachedAudio(
            role=role,
            path=name,
            sample_rate=sample_rate,
            channels=1 if a.ndim == 1 else int(a.shape[1]),
            sample_count=int(a.shape[0]),
            sha256=_array_sha256(a),
        )

    manifest = CacheManifest(
        source_sha256=source_sha256,
        settings_fingerprint=settings_fingerprint(settings),
        sample_rate=sample_rate,
        audio_format=audio_format,
        entries=entries,
        provenance=provenance or {},
    )
    _atomic_write_text(manifest_path,
                       json.dumps(manifest.to_dict(), indent=2, ensure_ascii=False))
    return manifest


def load_cache(cache_dir: str | Path) -> CacheManifest | None:
    """Return the manifest, or None when there is no usable cache."""
    path = Path(cache_dir) / MANIFEST_NAME
    if not path.exists():
        return None
    try:
        return CacheManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, CacheError, KeyError, TypeError):
        return None


def is_valid(manifest: CacheManifest | None, *, source_sha256: str,
             settings: dict[str, Any], required_roles: tuple[str, ...] = ROLES,
             cache_dir: str | Path | None = None) -> tuple[bool, str]:
    """Decide whether cached audio may be reused. Returns (ok, reason).

    The reason is returned rather than logged so callers can surface exactly why
    a cache was rejected -- "the source file changed" and "you changed the
    separator preset" call for very different responses from the user.
    """
    if manifest is None:
        return False, "no cache manifest"
    if manifest.source_sha256 != source_sha256:
        return False, "source audio changed since the cache was written"
    if manifest.settings_fingerprint != settings_fingerprint(settings):
        return False, "processing settings changed since the cache was written"
    missing = [r for r in required_roles if r not in manifest.entries]
    if missing:
        return False, f"cache is missing roles: {', '.join(missing)}"
    if cache_dir is not None:
        root = Path(cache_dir)
        absent = [r for r in required_roles if not (root / manifest.entries[r].path).exists()]
        if absent:
            return False, f"cached files missing on disk: {', '.join(absent)}"
    return True, "valid"


def read_role(cache_dir: str | Path, manifest: CacheManifest, role: str) -> tuple[np.ndarray, int]:
    """Read one cached stem back as float32.

    Reads with soundfile directly rather than shelling out to ffmpeg, so preview
    and remix paths do not depend on an external binary.
    """
    if role not in manifest.entries:
        raise CacheError(f"role {role!r} is not in this cache")
    entry = manifest.entries[role]
    path = Path(cache_dir) / entry.path
    if not path.exists():
        raise CacheError(f"cached file missing: {path}")
    data, sr = sf.read(str(path), dtype="float32", always_2d=False)
    return data, int(sr)


def cache_size_bytes(cache_dir: str | Path, manifest: CacheManifest) -> int:
    root = Path(cache_dir)
    total = 0
    for entry in manifest.entries.values():
        p = root / entry.path
        if p.exists():
            total += p.stat().st_size
    return total
