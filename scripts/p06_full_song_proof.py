"""Build and export a full saved project from existing audio/timings artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import time

from heartbeam import export_jobs as J, presentation as S, project as P


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir", type=Path)
    parser.add_argument("timings", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("--resolution", default="960x540")
    args = parser.parse_args()
    if args.project_dir.exists():
        raise SystemExit("Choose a new project folder; this proof never overwrites one.")
    project = P.import_legacy_timings(args.project_dir, args.timings, args.audio,
                                      name="P06 full-song proof")
    S.set_display_settings(project, {"automatic": True, "advance_ms": 1500,
                                     "hold_ms": 500, "show_upcoming": True,
                                     "upcoming_offset_y": -180})
    S.apply_style(project, {"video": {"resolution": args.resolution}})
    P.save_project(project, args.project_dir)
    audio = project.asset_by_role("karaoke_audio").resolve(args.project_dir)
    job = J.start(project, args.project_dir, audio)
    until = time.time() + 180
    while time.time() < until:
        state = J.get(job.id)
        if state.status not in ("queued", "running"):
            break
        time.sleep(.1)
    else:
        J.cancel(job.id)
        raise SystemExit("Export timed out.")
    if state.status != "complete":
        raise SystemExit(state.error or state.message)
    output = Path(state.output_path)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,sample_rate,channels",
        "-of", "json", str(output)], capture_output=True, text=True, check=True)
    media = json.loads(probe.stdout)
    result = {"job_id": job.id, "source_revision": job.revision,
              "word_count": len(project.word_ids()), "output": str(output),
              "bytes": output.stat().st_size, "media": media,
              "manifest": json.loads((output.parent / "export-manifest.json").read_text(encoding="utf-8"))}
    (args.project_dir / "p06-evidence.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
