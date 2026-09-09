"""Independent instrumental, lead and backing tracks on one sample basis."""
import numpy as np
from . import project as P

MODE = 'separated_stems'
ROLES = ('instrumental_stem', 'lead_stem', 'backing_stem')


def checked(project, root):
    from .vocal_mix import _file_info
    paths, basis = {}, None
    for role in ROLES:
        asset = project.asset_by_role(role)
        if not asset or not asset.resolve(root).is_file():
            raise P.ProjectError(f'Separate track controls need the saved {role.replace("_", " ")}. Link or relink the matching audio tracks.')
        path = asset.resolve(root); stat = path.stat()
        sr, channels, count, digest, fmt = _file_info(str(path), stat.st_size, stat.st_mtime_ns)
        if not asset.sha256 or asset.sha256 != digest or fmt not in ('WAV', 'WAVEX', 'FLAC'):
            raise P.ProjectError('A separated track changed or is not lossless. Relink the matching saved track.')
        if count <= 0 or (basis and basis != (sr, channels, count)):
            raise P.ProjectError('Separated tracks must have the same sample rate, channels and length.')
        basis = (sr, channels, count); paths[role] = path
    return paths, basis


def enable(project, root, *, backing=None):
    from .vocal_mix import level
    checked(project, root)
    project.vocal_mix.restoration_mode = MODE
    if backing is not None:
        project.vocal_mix.backing_value = level(backing)
    return True, 'Separate lead and backing controls are ready. Save to keep this mix.'


def mix_arrays(instrumental, lead, backing, mix, sr):
    from .vocal_mix import compile_envelope, envelope_array, level
    if instrumental.shape != lead.shape or lead.shape != backing.shape or instrumental.ndim not in (1, 2) or not instrumental.size:
        raise P.ProjectError('Separated tracks must share a non-empty sample basis.')
    if any(not np.isfinite(a).all() for a in (instrumental, lead, backing)):
        raise P.ProjectError('A separated track contains non-finite samples.')
    envelope = envelope_array(compile_envelope(mix, sr, len(lead)), len(lead))
    if lead.ndim == 2:
        envelope = envelope[:, None]
    return (instrumental.astype(np.float64) + lead * envelope + backing * level(mix.backing_value)).astype(np.float32)
