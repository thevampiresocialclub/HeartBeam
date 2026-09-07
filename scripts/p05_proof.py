"""Create a short original-lyrics fixture and reproducible P05 media proof.

Run with the repository Python environment and an empty output folder. No ML,
downloads or copyrighted sample audio are used. Existing projects are refused.
"""
import argparse
import copy
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import soundfile as sf
from heartbeam import project as P, presentation as S, lyrics, timings as T
from heartbeam import audio_cache as AC, editor_media as EM


def build(root):
    project_root = root / "project"
    if (project_root / P.MANIFEST_NAME).exists():
        raise P.ProjectError("A proof project already exists here; choose a new output folder.")
    root.mkdir(parents=True, exist_ok=True)
    sr, duration = 16000, 8
    time = np.arange(sr * duration) / sr
    original = (.09 * np.sin(2 * np.pi * 330 * time) + .03 * np.sin(2 * np.pi * 550 * time)).astype(np.float32)
    original = np.column_stack([original, original])
    clean = original * .4
    audio = root / "karaoke.wav"; sf.write(audio, clean, sr, subtype="FLOAT")
    p = P.create_project(project_root, name="P05 original lyric proof")
    lyrics.apply_lyrics_edit(p, "# Verse\nBright {stars} guide us\n# Chorus\nCafé Ω Привет \\N")
    for index, line in enumerate(p.lines):
        line.display_start_ms, line.display_end_ms = index * 4000, (index + 1) * 4000
        for j, word in enumerate(line.words):
            p.original_alignment[word.id] = P.WordTiming(index * 4000 + 500 + j * 700, index * 4000 + 1100 + j * 700, .99)
            p.timing_edits.pop(word.id, None)
    P.add_asset(p, project_root, audio, "karaoke_audio")
    from heartbeam.project_preview import current_timings
    imported = project_root / P.ASSETS_DIR / "imported_timings.json"
    T.to_json(current_timings(p, duration * 1000), imported)
    p.imported_timings_path = imported.relative_to(project_root).as_posix()
    AC.write_cache(root / "cache", {role: original.copy() if role != "clean" else clean.copy() for role in AC.ROLES},
                   sample_rate=sr, source_sha256="p05-original-synthetic", settings={"mix_strategy": "subtract"})
    EM.attach_cached_audio(p, project_root, root / "cache")
    S.apply_style(p, {"font": {"size_px": 110}, "box": {"x": 960, "y": 850, "width_px": 1600, "outline_px": 4}})
    S.set_line_breaks(p, p.lines[0].id, "Bright {stars}\nguide us")
    S.apply_style(p, {"font": {"italic": True}, "highlight": {"mode": "sweep"}, "colour": {"highlight": "#55E6C1"}}, [p.lines[1].id])
    p.presentation.presets["Original proof"] = S.preset_document("Original proof", S.resolved_style(p))
    P.save_project(p, project_root)
    return p, project_root, audio


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("output", type=Path)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--background", action="store_true", help="Add a moving test-pattern background for clock/crop verification")
    args = parser.parse_args(); p, root, audio = build(args.output)
    if args.background:
        from heartbeam.presentation_fonts import copy_asset
        video = args.output / "background.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x480:rate=30:duration=2",
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-y", str(video)], capture_output=True, check=True)
        image = args.output / "background.png"
        subprocess.run(["ffmpeg", "-v", "error", "-ss", "0.5", "-i", str(video), "-frames:v", "1", "-y", str(image)], capture_output=True, check=True)
        copy_asset(p, root, image, "background")
        asset = copy_asset(p, root, video, "background")
        S.apply_style(p, {"background": {"kind": "video", "asset_id": asset.id, "value": "#101820"}})
        P.save_project(p, root)
    if args.render:
        for resolution in ("1280x720", "1920x1080", "3840x2160"):
            snapshot = copy.deepcopy(p); S.apply_style(snapshot, {"video": {"resolution": resolution}})
            output = S.render_project(snapshot, root, audio, args.output / resolution)
            for label, seconds in (("lead-in", .25), ("word", 1.5), ("sweep", 5.5)):
                subprocess.run(["ffmpeg", "-v", "error", "-ss", str(seconds), "-i", str(output), "-frames:v", "1", "-y",
                                str(output.parent / f"{label}.png")], capture_output=True, check=True)
    print(json.dumps({"project": str(root.resolve()), "revision": p.revision, "words": len(p.word_ids()), "duration_ms": 8000}))


if __name__ == "__main__":
    main()
