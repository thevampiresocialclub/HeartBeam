"""
Phase 2 CLI: heartbeam-video karaoke.mp3 timings.json -o karaoke.mp4

Consumes the timings.json + audio produced by `heartbeam` and renders a karaoke
video. Re-running with a different --style produces a new video without re-running
the slow ML pipeline.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="heartbeam-video",
        description="Render a karaoke MP4 from a karaoke.mp3 + timings.json (produced by `heartbeam`).",
    )
    p.add_argument("audio", type=Path, help="karaoke.mp3 (or any audio)")
    p.add_argument("timings", type=Path, help="timings.json")
    p.add_argument("-o", "--out", type=Path, default=Path("karaoke.mp4"), help="output MP4 path")
    p.add_argument("--style", type=Path, default=None, help="path to style.toml (uses packaged default if omitted)")
    p.add_argument("--background", default=None,
                   help="override [background] in style.toml: a hex colour like '#101820', or a path to an image/video")
    p.add_argument("--resolution", default=None, help="override style.video.resolution, e.g. '1280x720'")
    p.add_argument("--ass-out", type=Path, default=None,
                   help="also write the generated .ass file to this path (for debugging)")
    p.add_argument("-v", "--verbose", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    log = logging.getLogger("heartbeam-video")

    if not args.audio.exists():
        log.error("audio not found: %s", args.audio)
        return 2
    if not args.timings.exists():
        log.error("timings not found: %s", args.timings)
        return 2

    from . import ass_writer
    from . import render as render_mod
    from . import style as style_mod
    from . import timings as timings_mod

    style = style_mod.Style.from_toml(args.style) if args.style else style_mod.Style.default()
    if args.resolution:
        style.video.resolution = args.resolution

    timings = timings_mod.from_json(args.timings)
    log.info("loaded timings: %d lines, %d words",
             len(timings.lines), sum(len(ln.words) for ln in timings.lines))

    # Decide where to write the intermediate .ass file.
    if args.ass_out:
        ass_path = args.ass_out
        ass_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        ass_path = args.out.with_suffix(".ass")

    ass_writer.write_ass(timings, style, ass_path)
    log.info("wrote ASS subtitle: %s", ass_path)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    log.info("rendering MP4 with ffmpeg + libass (res=%s fps=%d codec=%s crf=%d)…",
             style.video.resolution, style.video.fps, style.video.codec, style.video.crf)
    render_mod.render(
        audio_path=args.audio,
        ass_path=ass_path,
        out_path=args.out,
        style=style,
        background_override=args.background,
    )
    log.info("wrote %s", args.out)
    print(f"\nDone: {args.out.resolve()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
