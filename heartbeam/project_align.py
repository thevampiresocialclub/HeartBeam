"""Explicit alignment action; never imported by playback or timing gestures."""
import json
import soundfile as sf
from . import project as P


def align_saved(project, root):
    from . import align
    from . import timings as T
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError("Saved-track alignment needs the supported CUDA environment.")
    asset = project.asset_by_role("lead_stem")
    if asset is None or not asset.resolve(root).is_file():
        raise RuntimeError("Relink the saved lead vocal first.")
    samples, sr = sf.read(str(asset.resolve(root)), dtype="float32", always_2d=True)
    text = "\n".join(" ".join(w.text for w in line.words if not w.non_sung) for line in project.lines)
    result = align.align(samples, sr, text,
                         whisper_model=project.provenance.whisper_model or "medium", device="cuda")
    artifact = T.Timings(T.Source(asset.path, "project lyrics", sr, len(samples) / sr),
                         T.Models(project.provenance.separator_preset or "saved", "whisperx"), result.lines)
    dest = root / P.ASSETS_DIR / f"alignment-{P.new_id('run')}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    T.to_json(artifact, dest)
    return result
