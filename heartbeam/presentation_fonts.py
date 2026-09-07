"""Concrete font files shared by browser libass and native libass.

Font lookup is explicit: installed faces are copied on request, never silently
selected by the native machine's font provider. Missing faces use bundled Noto
Sans in both renderers and produce a visible warning.
"""
from __future__ import annotations
from functools import lru_cache
import os
from pathlib import Path
import shutil

from . import project as P

VENDOR = Path(__file__).parent / "editor_assets" / "vendor"


@lru_cache(maxsize=1024)
def _font_info(path, size, mtime):
    from fontTools.ttLib import TTFont
    with TTFont(path, lazy=True) as font:
        if "fvar" in font:
            raise P.ProjectError("Use a static TTF or OTF font face; variable font instances are not supported yet.")
        family = font["name"].getDebugName(1)
        if not family or any(c in family for c in ",{}\\\n\r"):
            raise P.ProjectError("This font has an unsupported family name.")
        bits = font["head"].macStyle
        cmap = font.getBestCmap() or {}
        metrics = font["hmtx"].metrics
        units = font["head"].unitsPerEm
        return {"family": family, "bold": bool(bits & 1), "italic": bool(bits & 2),
                "advances": {c: metrics[g][0] / units for c, g in cmap.items()},
                "line_height": (font["hhea"].ascent - font["hhea"].descent) / units}


def font_info(path):
    path = Path(path)
    try:
        stat = path.stat()
        return _font_info(str(path.resolve()), stat.st_size, stat.st_mtime_ns)
    except P.ProjectError:
        raise
    except Exception as exc:
        raise P.ProjectError(f"Could not read font {path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def installed_fonts():
    """A cached catalog. Merely browsing the list does not alter the project."""
    directories = [Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts",
                   Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Microsoft/Windows/Fonts",
                   Path.home() / ".fonts", Path("/usr/share/fonts/truetype"),
                   Path("/Library/Fonts")]
    families = {}
    for directory in directories:
        if not directory.is_dir():
            continue
        for path in sorted(directory.rglob("*")):
            if path.suffix.lower() not in (".ttf", ".otf"):
                continue
            try:
                info = font_info(path)
            except P.ProjectError:
                continue
            families.setdefault(info["family"], []).append(path)
    return dict(sorted(families.items(), key=lambda pair: pair[0].casefold()))


def copy_asset(project, root, source, role):
    """Content-addressed assets never overwrite files still referenced by undo."""
    root, source = Path(root), Path(source)
    digest = P.file_sha256(source)
    existing = next((a for a in project.assets if a.sha256 == digest and a.role == role), None)
    if existing and existing.resolve(root).is_file():
        return existing
    destination = root / P.ASSETS_DIR / role / f"{digest}{source.suffix.lower()}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    if existing:
        existing.path = destination.relative_to(root).as_posix()
        existing.external = False
        return existing
    asset = P.Asset(P.new_id("asset"), role, destination.relative_to(root).as_posix(), sha256=digest)
    project.assets.append(asset)
    return asset


def import_fonts(project, root, paths):
    faces = [(Path(path), font_info(path)) for path in paths]
    if not faces:
        raise P.ProjectError("Choose at least one font file.")
    for path, info in faces:
        asset = copy_asset(project, root, path, "font")
        slot = {key: info[key] for key in ("family", "bold", "italic")}
        project.presentation.fonts = [face for face in project.presentation.fonts
                if any(face.get(key) != value for key, value in slot.items())]
        project.presentation.fonts.append({**slot, "asset_id": asset.id})
    return True, f"Added {len(faces)} font face(s) to this project."


def resolve_face(project, root, spec):
    """Return path, actual family and warnings; never silently substitute."""
    family, bold, italic = spec["family"], spec["bold"], spec["italic"]
    warnings = []
    face = next((f for f in project.presentation.fonts if
            (f["family"], f["bold"], f["italic"]) == (family, bold, italic)), None)
    asset = next((a for a in project.assets if face and a.id == face["asset_id"]), None)
    if asset and root is not None:
        path = asset.resolve(Path(root))
        if path.is_file() and P.file_sha256(path) == asset.sha256:
            info = font_info(path)
            if (info["family"], info["bold"], info["italic"]) == (family, bold, italic):
                return path, family, warnings
    if face or family != "Noto Sans":
        weight = ("bold " if bold else "") + ("italic" if italic else "regular")
        warnings.append(f"Missing or changed font: {family} {weight}. Preview and export use Noto Sans. Add or relink that face to restore it.")
    name = "BoldItalic" if bold and italic else "Bold" if bold else "Italic" if italic else "Regular"
    return VENDOR / f"NotoSans-{name}.ttf", "Noto Sans", warnings
