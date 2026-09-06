"""A/B several HeartBeam configurations on one song, for picking by ear.

Each config is a full Phase 1 run, so this is minutes per config -- but it is
the only honest way to compare, since separation quality is the thing under
test and it cannot be cached between processes.

    python scripts/sweep.py song.mp3 lyrics.txt -o sweep_out/

Writes sweep_out/<config>.mp3 for each config plus a summary table of mask
coverage, so you can pair what you hear with why.

Reading the results:
  lyric%    how much of the song WhisperX aligned to your lyrics
  energy%   how much the lead stem's own energy flagged as vocal
  combined% the union -- what actually got subtracted
A low lyric% with a high combined% means the energy mask is carrying the run;
that is the safety net working, but it also means alignment is weak.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

# (label, extra CLI args). Kept flat and explicit so it is obvious what differs.
CONFIGS: list[tuple[str, list[str]]] = [
    # What the GUI gives you today.
    ("00_pop_current_default",
     ["--separator", "pop", "--whisper-model", "medium"]),
    # Pass-2 karaoke-model bake-off, alignment held constant at large-v3.
    ("01_rock_aufr33",
     ["--separator", "rock", "--whisper-model", "large-v3"]),
    ("02_rock_becruily",
     ["--separator", "rock-becruily", "--whisper-model", "large-v3"]),
    ("03_rock_gabox2",
     ["--separator", "rock-gabox2", "--whisper-model", "large-v3"]),
    # Same models as 01, but targeting the two failure modes directly.
    ("04_rock_widemask",
     ["--separator", "rock", "--whisper-model", "large-v3",
      "--pad-ms", "250", "--merge-gap-ms", "600", "--energy-threshold", "0.02"]),
    ("05_rock_overshoot",
     ["--separator", "rock", "--whisper-model", "large-v3",
      "--vocal-gain", "1.7", "--backing-boost", "0.3"]),
]

_COVERAGE = re.compile(
    r"mask coverage: lyric=([\d.]+)% energy=([\d.]+)% combined=([\d.]+)%")
_ALIGN = re.compile(r"alignment: (\d+) words across (\d+) lines \((\d+) low-confidence")


def run_one(exe: str, song: Path, lyrics: Path, out_root: Path,
            label: str, extra: list[str]) -> dict:
    run_dir = out_root / label
    run_dir.mkdir(parents=True, exist_ok=True)
    cmd = [exe, str(song), str(lyrics), "-o", str(run_dir), "-v"] + extra
    print(f"\n=== {label} ===\n    {' '.join(extra)}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          text=True, encoding="utf-8", errors="replace")
    elapsed = time.time() - t0
    (run_dir / "run.log").write_text(proc.stdout or "", encoding="utf-8")

    row = {"label": label, "rc": proc.returncode, "secs": elapsed,
           "lyric": None, "energy": None, "combined": None,
           "words": None, "lowconf": None}
    for line in (proc.stdout or "").splitlines():
        m = _COVERAGE.search(line)
        if m:
            row["lyric"], row["energy"], row["combined"] = (float(g) for g in m.groups())
        m = _ALIGN.search(line)
        if m:
            row["words"], _, row["lowconf"] = (int(g) for g in m.groups())

    if proc.returncode == 0:
        src = run_dir / "karaoke.mp3"
        if src.exists():
            dest = out_root / f"{label}.mp3"
            dest.write_bytes(src.read_bytes())
            print(f"    -> {dest.name}  ({elapsed:.0f}s)", flush=True)
    else:
        print(f"    FAILED rc={proc.returncode} -- see {run_dir/'run.log'}", flush=True)
    return row


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song", type=Path)
    ap.add_argument("lyrics", type=Path)
    ap.add_argument("-o", "--out", type=Path, default=Path("sweep_out"))
    ap.add_argument("--only", nargs="*", default=None,
                    help="run only configs whose label contains one of these strings")
    args = ap.parse_args()

    for f in (args.song, args.lyrics):
        if not f.exists():
            print(f"not found: {f}", file=sys.stderr)
            return 2

    import shutil
    exe = shutil.which("heartbeam") or str(Path(sys.executable).with_name("heartbeam.exe"))
    args.out.mkdir(parents=True, exist_ok=True)

    configs = CONFIGS
    if args.only:
        configs = [c for c in CONFIGS if any(o in c[0] for o in args.only)]

    rows = [run_one(exe, args.song, args.lyrics, args.out, label, extra)
            for label, extra in configs]

    print("\n" + "=" * 78)
    print(f"{'config':<26}{'time':>7}{'lyric%':>9}{'energy%':>9}{'comb%':>8}{'lowconf':>9}")
    print("-" * 78)
    for r in rows:
        if r["rc"] != 0:
            print(f"{r['label']:<26}{'FAILED':>7}")
            continue
        print(f"{r['label']:<26}{r['secs']:>6.0f}s"
              f"{r['lyric'] or 0:>9.1f}{r['energy'] or 0:>9.1f}"
              f"{r['combined'] or 0:>8.1f}{r['lowconf'] if r['lowconf'] is not None else 0:>9}")
    print("=" * 78)
    print()
    print(f"Listen to the .mp3 files in {args.out} and pick the one that sounds best.")
    print("Coverage numbers explain WHY, they do not rank quality -- your ears do.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
