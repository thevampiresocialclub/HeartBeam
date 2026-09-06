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


def toml_escape(value: str) -> str:
    """Escape a Python string into a TOML basic string BODY (no surrounding quotes).

    Windows paths are the reason this exists. Interpolating one straight into a
    double-quoted TOML string makes the parser read its backslashes as escape
    sequences: "C:\\Users\\..." fails outright, because \\U starts a
    unicode escape and "Users" is not valid hex. Worse are the ones that parse:
    "C:\\temp" silently becomes "C:<TAB>emp" via \\t.

    Handles the TOML 1.0 basic-string escapes plus \\uXXXX for other control
    characters. Anything not requiring an escape passes through unchanged.
    """
    out = []
    for ch in value:
        if ch == chr(92):
            out.append(chr(92) * 2)
        elif ch == '"':
            out.append(chr(92) + '"')
        elif ch == chr(8):
            out.append(chr(92) + "b")
        elif ch == chr(9):
            out.append(chr(92) + "t")
        elif ch == chr(10):
            out.append(chr(92) + "n")
        elif ch == chr(12):
            out.append(chr(92) + "f")
        elif ch == chr(13):
            out.append(chr(92) + "r")
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(chr(92) + "u%04X" % ord(ch))
        else:
            out.append(ch)
    return "".join(out)


def toml_string(value: str) -> str:
    """Quote and escape a value as a complete TOML basic string."""
    return '"' + toml_escape(value) + '"'


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
