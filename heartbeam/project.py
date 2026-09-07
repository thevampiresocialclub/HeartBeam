"""Saved-project store: the durable state behind the editor.

Implements section 1 of `08-SHARED-CONTRACT.md`. This module is deliberately
free of Streamlit and ML imports so the CLI, the GUI and the tests can all use
it, and so loading a project never costs a torch import.

Three ideas carry most of the design:

**Stable IDs.** Text, ordinal position and hashes of text are not identities:
repeated choruses and duplicated words are normal in lyrics. Every section, line
and word gets a generated ID that survives insertion, deletion and re-wrapping,
so alignment results and vocal regions can reference words rather than indices.

**One place resolves timing.** A word has an immutable `original` proposal from
the aligner and an optional `edit` from the user. `effective_timing()` is the
only function that decides which wins. Nothing else stores a third copy of
"current" timing that could drift.

**Integer milliseconds.** Editor timing is integer ms end-to-end. Legacy float
seconds are converted once, at the importer boundary, rounding to nearest with
ties away from zero. ASS export converts to centiseconds once, at the end.

Intervals are start-inclusive / end-exclusive.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

#: Editor project format. Independent of timings.SCHEMA_VERSION -- a legacy
#: timings.json is imported into a project, never read as one.
PROJECT_SCHEMA_VERSION = 1

MANIFEST_NAME = "project.json"
AUTOSAVE_DIR = "autosave"
ASSETS_DIR = "assets"
AUDIO_DIR = "audio"
CACHE_DIR = "cache"
EXPORTS_DIR = "exports"

#: Design canvas. Placement, font sizes and outline widths are expressed in
#: these units and scale uniformly to matching-aspect-ratio exports.
DEFAULT_DESIGN_WIDTH = 1920
DEFAULT_DESIGN_HEIGHT = 1080


class ProjectError(Exception):
    """Raised when a project cannot be loaded, saved or migrated."""


def new_id(prefix: str) -> str:
    """Short, collision-resistant, and readable in a diff."""
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def seconds_to_ms(value: float) -> int:
    """Convert legacy float seconds to integer milliseconds.

    Rounds to nearest, ties away from zero. Applied only at the importer
    boundary; the editor never round-trips through seconds afterwards.
    """
    if value is None:
        raise ValueError("cannot convert None to milliseconds")
    v = float(value)
    if v != v or v in (float("inf"), float("-inf")):
        raise ValueError(f"cannot convert non-finite seconds: {value!r}")
    return int(v * 1000 + (0.5 if v >= 0 else -0.5))


def ms_to_seconds(value: int) -> float:
    return value / 1000.0


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass
class Asset:
    """A file the project depends on.

    `path` is project-relative when the file lives inside the project folder,
    and absolute when it is an external reference the user asked us not to copy.
    External assets are the ones that go missing when a drive is unplugged, so
    they are what `missing_assets()` and `relink_asset()` exist for.
    """
    id: str
    role: str                      # original_audio | karaoke_audio | lead_stem | ...
    path: str
    external: bool = False
    sha256: str | None = None
    sample_rate: int | None = None
    channels: int | None = None
    sample_count: int | None = None
    duration_ms: int | None = None

    def resolve(self, project_dir: Path) -> Path:
        return Path(self.path) if self.external else (project_dir / self.path)


@dataclass
class Word:
    """One lyric token.

    `text` is what was sung; `display_text` overrides it on screen when they
    differ (punctuation, capitalisation). `non_sung` marks headings and section
    labels so they are never handed to the aligner.
    """
    id: str
    text: str
    display_text: str | None = None
    non_sung: bool = False


@dataclass
class Line:
    id: str
    words: list[Word] = field(default_factory=list)
    section_id: str | None = None
    #: Display window. May start before the first sung word and end after the
    #: last -- these are NOT audio-removal intervals.
    display_start_ms: int | None = None
    display_end_ms: int | None = None

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


@dataclass
class Section:
    id: str
    name: str
    line_ids: list[str] = field(default_factory=list)


@dataclass
class WordTiming:
    """Resolved or unresolved timing for one word.

    An unresolved word keeps `start_ms`/`end_ms` absent rather than inventing
    plausible values, and carries a reason so the editor can list it for review.
    """
    start_ms: int | None = None
    end_ms: int | None = None
    score: float | None = None
    reason: str | None = None

    @property
    def resolved(self) -> bool:
        return self.start_ms is not None and self.end_ms is not None


@dataclass
class VocalRegion:
    """A span with its own lead-vocal restoration level.

    `value` is 0..1, where 0 is the fully processed karaoke result and 1 the
    original pre-mastering reference. One non-overlapping lane; insertions split
    or replace intersecting portions.
    """
    id: str
    start_ms: int
    end_ms: int
    value: float
    transition_ms: int = 40
    source_line_ids: list[str] = field(default_factory=list)
    source_word_ids: list[str] = field(default_factory=list)
    source_section_id: str | None = None


@dataclass
class VocalMix:
    default_value: float = 0.0
    regions: list[VocalRegion] = field(default_factory=list)
    restoration_mode: str = "clean_to_original"
    transition_ms: int = 40
    references: dict[str, Any] = field(default_factory=dict)


@dataclass
class Presentation:
    design_width: int = DEFAULT_DESIGN_WIDTH
    design_height: int = DEFAULT_DESIGN_HEIGHT
    #: Song-wide style defaults; mirrors style.toml keys so the compiler can
    #: consume either. Per-line overrides are keyed by line ID.
    song_style: dict[str, Any] = field(default_factory=dict)
    line_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)


@dataclass
class Provenance:
    """What produced the cached artifacts. A mismatch invalidates them."""
    separator_preset: str | None = None
    separator_models: list[str] = field(default_factory=list)
    aligner: str | None = None
    whisper_model: str | None = None
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExportRecord:
    id: str
    revision: int
    output_path: str
    status: str = "pending"        # pending | complete | failed
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass
class Project:
    """The authoritative manifest."""
    id: str
    name: str
    schema_version: int = PROJECT_SCHEMA_VERSION
    revision: int = 0
    created_at: float = field(default_factory=time.time)
    modified_at: float = field(default_factory=time.time)

    assets: list[Asset] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    lines: list[Line] = field(default_factory=list)

    #: Immutable aligner output, keyed by word ID.
    original_alignment: dict[str, WordTiming] = field(default_factory=dict)
    #: User corrections, keyed by word ID. Overrides the original.
    timing_edits: dict[str, WordTiming] = field(default_factory=dict)
    alignment_proposals: dict[str, WordTiming] = field(default_factory=dict)
    reviewed: dict[str, bool] = field(default_factory=dict)
    command_ids: list[str] = field(default_factory=list)

    presentation: Presentation = field(default_factory=Presentation)
    vocal_mix: VocalMix = field(default_factory=VocalMix)
    provenance: Provenance = field(default_factory=Provenance)
    exports: list[ExportRecord] = field(default_factory=list)

    #: Path to the untouched imported timing artifact, kept for comparison.
    imported_timings_path: str | None = None

    # -- lookups ------------------------------------------------------------

    def word_ids(self) -> list[str]:
        return [w.id for ln in self.lines for w in ln.words]

    def iter_words(self) -> Iterable[tuple[Line, Word]]:
        for ln in self.lines:
            for w in ln.words:
                yield ln, w

    def find_word(self, word_id: str) -> Word | None:
        for _, w in self.iter_words():
            if w.id == word_id:
                return w
        return None

    def find_line(self, line_id: str) -> Line | None:
        return next((ln for ln in self.lines if ln.id == line_id), None)

    def asset_by_role(self, role: str) -> Asset | None:
        return next((a for a in self.assets if a.role == role), None)

    def effective_timing(self, word_id: str) -> WordTiming | None:
        """The single place that decides which timing wins.

        A user edit overrides the aligner's proposal. Returns None for a word
        that has neither -- a freshly inserted word, for instance.
        """
        edit = self.timing_edits.get(word_id)
        if edit is not None:
            return edit
        return self.alignment_proposals.get(word_id, self.original_alignment.get(word_id))

    def unresolved_words(self) -> list[tuple[Line, Word, str | None]]:
        """Words the editor should surface for review."""
        out = []
        for ln, w in self.iter_words():
            if w.non_sung:
                continue
            t = self.effective_timing(w.id)
            if t is None or not t.resolved:
                out.append((ln, w, t.reason if t else "no timing assigned"))
        return out

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_schema_version": self.schema_version,
            "id": self.id,
            "name": self.name,
            "revision": self.revision,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "assets": [asdict(a) for a in self.assets],
            "sections": [asdict(s) for s in self.sections],
            "lines": [asdict(ln) for ln in self.lines],
            "original_alignment": {k: asdict(v) for k, v in self.original_alignment.items()},
            "timing_edits": {k: asdict(v) for k, v in self.timing_edits.items()},
            "alignment_proposals": {k: asdict(v) for k, v in self.alignment_proposals.items()},
            "reviewed": self.reviewed.copy(),
            "command_ids": self.command_ids[:],
            "presentation": asdict(self.presentation),
            "vocal_mix": asdict(self.vocal_mix),
            "provenance": asdict(self.provenance),
            "exports": [asdict(e) for e in self.exports],
            "imported_timings_path": self.imported_timings_path,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        sv = int(d.get("project_schema_version", -1))
        if sv != PROJECT_SCHEMA_VERSION:
            raise ProjectError(
                f"unsupported project_schema_version {sv} "
                f"(this build reads {PROJECT_SCHEMA_VERSION})"
            )
        lines = [
            Line(
                id=ln["id"],
                words=[Word(**w) for w in ln.get("words", [])],
                section_id=ln.get("section_id"),
                display_start_ms=ln.get("display_start_ms"),
                display_end_ms=ln.get("display_end_ms"),
            )
            for ln in d.get("lines", [])
        ]
        vm = d.get("vocal_mix", {})
        return cls(
            id=d["id"],
            name=d["name"],
            schema_version=sv,
            revision=int(d.get("revision", 0)),
            created_at=float(d.get("created_at", time.time())),
            modified_at=float(d.get("modified_at", time.time())),
            assets=[Asset(**a) for a in d.get("assets", [])],
            sections=[Section(**s) for s in d.get("sections", [])],
            lines=lines,
            original_alignment={
                k: WordTiming(**v) for k, v in d.get("original_alignment", {}).items()
            },
            timing_edits={
                k: WordTiming(**v) for k, v in d.get("timing_edits", {}).items()
            },
            alignment_proposals={k: WordTiming(**v) for k, v in d.get("alignment_proposals", {}).items()},
            reviewed=dict(d.get("reviewed", {})),
            command_ids=list(d.get("command_ids", [])),
            presentation=Presentation(**d.get("presentation", {})),
            vocal_mix=VocalMix(
                default_value=vm.get("default_value", 0.0),
                regions=[VocalRegion(**r) for r in vm.get("regions", [])],
                restoration_mode=vm.get("restoration_mode", "clean_to_original"),
                transition_ms=vm.get("transition_ms", 40),
                references=vm.get("references", {}),
            ),
            provenance=Provenance(**d.get("provenance", {})),
            exports=[ExportRecord(**e) for e in d.get("exports", [])],
            imported_timings_path=d.get("imported_timings_path"),
        )


# ---------------------------------------------------------------------------
# Store: create, save, load
# ---------------------------------------------------------------------------


def create_project(project_dir: str | Path, name: str) -> Project:
    """Create the folder skeleton and an empty manifest (not yet saved)."""
    root = Path(project_dir)
    if (root / MANIFEST_NAME).exists():
        raise ProjectError("That folder already contains a project. Open it or choose a new folder.")
    for sub in (ASSETS_DIR, AUDIO_DIR, CACHE_DIR, AUTOSAVE_DIR, EXPORTS_DIR):
        (root / sub).mkdir(parents=True, exist_ok=True)
    return Project(id=new_id("proj"), name=name)


def _atomic_write(path: Path, text: str) -> None:
    """Replace `path` atomically.

    Writes a sibling temp file, flushes it to disk, then renames over the
    target. os.replace is atomic on Windows and POSIX, so an interrupted save
    leaves the previous manifest intact rather than a half-written one.
    """
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


def save_project(project: Project, project_dir: str | Path, *, bump: bool = True) -> Path:
    """Write the manifest atomically and take an autosave snapshot."""
    from .project_lock import WriterLease
    root = Path(project_dir)
    root.mkdir(parents=True, exist_ok=True)
    with WriterLease(root, ".save.lock"):
        return _save_locked(project, root, bump=bump)


def _save_locked(project, root, *, bump):
    manifest = root / MANIFEST_NAME
    disk_hash = file_sha256(manifest) if manifest.exists() else None
    if hasattr(project, "_disk_hash") and project._disk_hash != disk_hash:
        raise ProjectError("The saved project changed in another session. Save a copy or reopen it before saving.")
    if bump:
        project.revision += 1
        project.modified_at = time.time()
    text = json.dumps(project.to_dict(), indent=2, ensure_ascii=False)
    manifest = root / MANIFEST_NAME
    _atomic_write(manifest, text)
    project._disk_hash = file_sha256(manifest)

    autosave = root / AUTOSAVE_DIR
    autosave.mkdir(parents=True, exist_ok=True)
    _atomic_write(autosave / f"rev_{project.revision:06d}.json", text)
    _prune_autosaves(autosave)
    return manifest


def _prune_autosaves(autosave_dir: Path, keep: int = 20) -> None:
    snaps = sorted(autosave_dir.glob("rev_*.json"))
    for old in snaps[:-keep]:
        old.unlink(missing_ok=True)


def load_project(project_dir: str | Path) -> Project:
    root = Path(project_dir)
    manifest = root / MANIFEST_NAME
    if not manifest.exists():
        raise ProjectError(f"no {MANIFEST_NAME} in {root}")
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{manifest} is not valid JSON: {exc}") from exc
    project = Project.from_dict(data)
    project._disk_hash = file_sha256(manifest)
    return project


def save_project_as(project: Project, dest_dir: str | Path,
                    src_dir: str | Path | None = None) -> Project:
    """Copy the project to a new folder under a new identity.

    Returns the NEW project. The original is left untouched on disk and the copy
    gets a fresh ID, so later saves to either cannot be confused for each other.
    """
    dest = Path(dest_dir)
    if (dest / MANIFEST_NAME).exists():
        raise ProjectError("That folder already contains a project. Choose a new folder for the copy.")
    dest.mkdir(parents=True, exist_ok=True)
    if src_dir is not None:
        src = Path(src_dir)
        for sub in (ASSETS_DIR, AUDIO_DIR):
            s = src / sub
            if s.is_dir():
                shutil.copytree(s, dest / sub, dirs_exist_ok=True)
    for sub in (ASSETS_DIR, AUDIO_DIR, CACHE_DIR, AUTOSAVE_DIR, EXPORTS_DIR):
        (dest / sub).mkdir(parents=True, exist_ok=True)

    copy = Project.from_dict(json.loads(json.dumps(project.to_dict())))
    copy.id = new_id("proj")
    copy.revision = project.revision
    save_project(copy, dest)
    return copy


def recover_latest_autosave(project_dir: str | Path) -> Project | None:
    """Return the newest autosave that parses, or None.

    Walks backwards so a truncated newest snapshot falls through to the last
    complete one rather than failing the whole recovery.
    """
    autosave = Path(project_dir) / AUTOSAVE_DIR
    if not autosave.is_dir():
        return None
    for snap in sorted(autosave.glob("rev_*.json"), reverse=True):
        try:
            return Project.from_dict(json.loads(snap.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, ProjectError, KeyError):
            continue
    return None


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------


def add_asset(project: Project, project_dir: str | Path, source: str | Path,
              role: str, *, copy_into_project: bool = True) -> Asset:
    """Register a file with the project.

    Copying stores a project-relative path, which is what lets the folder be
    moved or renamed without breaking. Referencing externally keeps an absolute
    path and accepts that it can go missing.
    """
    root = Path(project_dir)
    src = Path(source)
    if not src.exists():
        raise ProjectError(f"asset not found: {src}")

    if copy_into_project:
        dest_dir = root / AUDIO_DIR
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / src.name
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        rel = dest.relative_to(root).as_posix()
        asset = Asset(id=new_id("asset"), role=role, path=rel, external=False,
                      sha256=file_sha256(dest))
    else:
        asset = Asset(id=new_id("asset"), role=role, path=str(src.resolve()),
                      external=True, sha256=file_sha256(src))

    project.assets = [a for a in project.assets if a.role != role]
    project.assets.append(asset)
    return asset


def missing_assets(project: Project, project_dir: str | Path) -> list[Asset]:
    root = Path(project_dir)
    return [a for a in project.assets if not a.resolve(root).exists()]


def relink_asset(project: Project, project_dir: str | Path, asset_id: str,
                 new_path: str | Path, *, copy_into_project: bool = False) -> Asset:
    """Point a missing asset at a new file, keeping its ID and role."""
    asset = next((a for a in project.assets if a.id == asset_id), None)
    if asset is None:
        raise ProjectError(f"no asset with id {asset_id}")
    src = Path(new_path)
    if not src.exists():
        raise ProjectError(f"replacement not found: {src}")

    root = Path(project_dir)
    if copy_into_project:
        dest = root / AUDIO_DIR / src.name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        asset.path = dest.relative_to(root).as_posix()
        asset.external = False
        asset.sha256 = file_sha256(dest)
    else:
        asset.path = str(src.resolve())
        asset.external = True
        asset.sha256 = file_sha256(src)
    return asset


# ---------------------------------------------------------------------------
# Lyrics
# ---------------------------------------------------------------------------


def set_lyrics_from_text(project: Project, text: str) -> None:
    """Replace the lyric document from plain text, one phrase per line.

    Fresh IDs throughout -- this is the "new project" path. P02 owns the harder
    job of editing lyrics while preserving IDs and timing.
    """
    lines: list[Line] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        lines.append(Line(
            id=new_id("line"),
            words=[Word(id=new_id("w"), text=tok) for tok in stripped.split()],
        ))
    project.lines = lines
    project.sections = []


# ---------------------------------------------------------------------------
# Legacy import
# ---------------------------------------------------------------------------


def import_legacy_timings(project_dir: str | Path, timings_path: str | Path,
                          audio_path: str | Path | None = None, *,
                          name: str | None = None,
                          audio_role: str = "karaoke_audio",
                          copy_audio: bool = True) -> Project:
    """Build a new project from a legacy timings.json plus optional audio.

    The originals are never modified. A verbatim copy of the timing file is kept
    under assets/ and recorded in `imported_timings_path`, so the aligner's
    proposal stays available for comparison after the user starts editing.
    """
    from . import timings as timings_mod  # local: keeps this module import-light

    root = Path(project_dir)
    tpath = Path(timings_path)
    if not tpath.exists():
        raise ProjectError(f"timings file not found: {tpath}")

    legacy = timings_mod.from_json(tpath)
    project = create_project(root, name or tpath.parent.name or "Imported project")

    for ln in legacy.lines:
        words = [Word(id=new_id("w"), text=w.text) for w in ln.words]
        line = Line(id=new_id("line"), words=words)
        if ln.words:
            line.display_start_ms = seconds_to_ms(ln.start_s)
            line.display_end_ms = seconds_to_ms(ln.end_s)
        project.lines.append(line)
        for src_word, new_word in zip(ln.words, words):
            project.original_alignment[new_word.id] = WordTiming(
                start_ms=seconds_to_ms(src_word.start_s),
                end_ms=seconds_to_ms(src_word.end_s),
                score=float(src_word.score),
            )

    project.provenance = Provenance(
        separator_preset=legacy.models.separator,
        aligner=legacy.models.aligner,
    )

    # Keep a verbatim copy; never touch the user's file.
    assets_dir = root / ASSETS_DIR
    assets_dir.mkdir(parents=True, exist_ok=True)
    kept = assets_dir / "imported_timings.json"
    shutil.copy2(tpath, kept)
    project.imported_timings_path = kept.relative_to(root).as_posix()

    if audio_path is not None:
        add_asset(project, root, audio_path, audio_role,
                  copy_into_project=copy_audio)

    save_project(project, root)
    return project
