"""Explicit user approval between preparation and the selective removal mix."""
import hashlib
import json
import os
import tempfile
from pathlib import Path

from . import project as P


def required(project):
    return project.alignment.get('review', {}).get('required', bool(project.alignment.get('phrases')))


def fingerprint(project):
    from .vocal_mix import timing_hash
    identity = dict(timing=timing_hash(project), lyrics=[
        (line.id, [(w.id,w.text,w.non_sung) for w in line.words]) for line in project.lines],
        audio=[(a.role,a.sha256,a.sample_count,a.sample_rate) for a in project.assets
               if a.role in ('original_audio','lead_stem','backing_stem','instrumental_stem','vocals_stem')])
    return hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()


def approved(project):
    return not required(project) or project.alignment.get('review', {}).get('approved_fingerprint') == fingerprint(project)


def require_approved(project):
    if not approved(project):
        raise P.ProjectError('Review and approve the current lyric timing before building karaoke audio or exporting video.')


def approve_and_build(project, root, *, keep_backing=True, allow_incomplete=False,
                      separate_tracks=False, backing_level=None):
    """Called only by the explicit approval action, inside the command history."""
    from . import vocal_mix as V, io as IO
    root = Path(root)
    project.alignment['review'] = dict(required=True, keep_backing=bool(keep_backing),
                                       allow_incomplete=bool(allow_incomplete))
    project.alignment['review']['approved_fingerprint'] = fingerprint(project)
    recipe = dict(project.vocal_mix.references.get('recipe') or {})
    if not recipe:
        raise P.ProjectError('Link the saved separation cache before building karaoke audio.')
    recipe.pop('pending_timing_review', None)
    recipe['keep_backing'] = bool(keep_backing)
    recipe['allow_incomplete_timing'] = bool(allow_incomplete)
    if not keep_backing:
        recipe['mix_strategy'] = 'replace'
    clean_path = V.rebuild_clean(project, root, recipe)
    if separate_tracks:
        from .stem_mix import enable
        enable(project, root, backing=backing_level if backing_level is not None else float(keep_backing))
    if project.vocal_mix.restoration_mode == 'separated_stems':
        clean_path = V.render_mix(project, root, mastered=False)
    import soundfile as sf
    samples,sr = sf.read(clean_path,dtype='float32',always_2d=True)
    mastered = V.master(samples,sr, target_lufs=recipe.get('target_lufs', -16.),
                        peak_db=recipe.get('peak_db', -1.))
    digest = hashlib.sha256(mastered.tobytes()).hexdigest()[:20]
    path = root/P.AUDIO_DIR/f'karaoke-approved-{digest}.mp3'
    if not path.exists():
        fd, temporary = tempfile.mkstemp(dir=path.parent, suffix='.mp3')
        os.close(fd)
        try:
            IO.write_mp3(Path(temporary),mastered,sr)
            os.replace(temporary,path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    project.assets = [a for a in project.assets if a.role != 'karaoke_audio']
    asset = P.add_asset(project,root,path,'karaoke_audio',copy_into_project=False)
    asset.path, asset.external = str(path.relative_to(root)), False
    return True, 'Karaoke audio built from the current word and phrase timing.'
