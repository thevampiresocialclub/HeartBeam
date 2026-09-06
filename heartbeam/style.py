"""
Style configuration for the karaoke video.

Loaded from a TOML file; fields map 1:1 to ASS [V4+ Styles] entries.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # type: ignore


@dataclass
class FontCfg:
    family: str = "Arial"
    size_px: int = 72
    bold: bool = True
    italic: bool = False


@dataclass
class ColourCfg:
    primary: str = "#FFFFFF"     # text not yet sung
    highlight: str = "#FFD700"   # word currently being sung (\k karaoke fill)
    outline: str = "#000000"
    shadow: str = "#000000"


@dataclass
class BoxCfg:
    position: str = "bottom"     # top | center | bottom
    alignment: str = "center"    # left | center | right
    margin_v_px: int = 80
    margin_h_px: int = 60
    outline_px: int = 3
    shadow_px: int = 2


@dataclass
class BackgroundCfg:
    kind: str = "solid"          # solid | image | video
    value: str = "#101820"       # hex if solid, path if image/video


@dataclass
class VideoCfg:
    resolution: str = "1920x1080"
    fps: int = 30
    codec: str = "libx264"
    crf: int = 20
    audio_bitrate: str = "192k"


@dataclass
class Style:
    font: FontCfg = field(default_factory=FontCfg)
    colour: ColourCfg = field(default_factory=ColourCfg)
    box: BoxCfg = field(default_factory=BoxCfg)
    background: BackgroundCfg = field(default_factory=BackgroundCfg)
    video: VideoCfg = field(default_factory=VideoCfg)

    @classmethod
    def from_toml(cls, path: str | Path) -> "Style":
        data: dict[str, Any] = tomllib.loads(Path(path).read_text(encoding="utf-8"))
        return cls(
            font=FontCfg(**data.get("font", {})),
            colour=ColourCfg(**data.get("colour", {})),
            box=BoxCfg(**data.get("box", {})),
            background=BackgroundCfg(**data.get("background", {})),
            video=VideoCfg(**data.get("video", {})),
        )

    @classmethod
    def default(cls) -> "Style":
        """Load the packaged default preset."""
        default_path = Path(__file__).parent / "styles" / "default.toml"
        if default_path.exists():
            return cls.from_toml(default_path)
        return cls()


def hex_to_ass_colour(hex_str: str) -> str:
    """
    ASS uses &HAABBGGRR& byte order with optional alpha. We assume opaque (AA=00).
    Input: '#RRGGBB' or 'RRGGBB' or '#AARRGGBB'.
    """
    s = hex_str.lstrip("#")
    if len(s) == 6:
        r, g, b = s[0:2], s[2:4], s[4:6]
        aa = "00"
    elif len(s) == 8:
        aa, r, g, b = s[0:2], s[2:4], s[4:6], s[6:8]
    else:
        raise ValueError(f"invalid hex colour: {hex_str}")
    return f"&H{aa}{b}{g}{r}&".upper()


def ass_alignment(position: str, horizontal: str) -> int:
    """
    ASS \\an alignment numpad: 1-3 bottom, 4-6 middle, 7-9 top; 1/4/7 left, 2/5/8 centre, 3/6/9 right.
    """
    rows = {"bottom": 0, "center": 3, "top": 6}
    cols = {"left": 1, "center": 2, "right": 3}
    return rows.get(position, 0) + cols.get(horizontal, 2)
