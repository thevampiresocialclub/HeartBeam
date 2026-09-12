"""Local MP3 comparisons with explicit gain policy and decode verification."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pyloudnorm as pyln
from scipy.signal import resample_poly

from . import io, project as P


def loudness(samples, sr):
    if len(samples) < round(.4 * sr):
        raise ValueError('Listening comparisons need at least 0.4 seconds of audio.')
    value = float(pyln.Meter(sr).integrated_loudness(samples))
    return value if np.isfinite(value) else None


def peak(samples):
    return float(np.max(np.abs(resample_poly(samples, 4, 1, axis=0))))


def prepare_group(conditions, sr, *, match_loudness=False, target_lufs=-16., peak_db=-2.):
    """One common gain, or individual loudness matching + common peak protection.

    No per-condition limiter is used: dynamics and the relative local lift remain
    inspectable. The returned gain is the TOTAL applied gain for each condition.
    """
    if not conditions:
        raise ValueError('At least one listening condition is required.')
    arrays = {name: np.asarray(value, dtype='float32') for name, value in conditions.items()}
    shape = next(iter(arrays.values())).shape
    if len(shape) not in (1, 2) or any(a.shape != shape or not np.isfinite(a).all() for a in arrays.values()):
        raise ValueError('Listening conditions must share a finite sample basis.')
    levels = {name: loudness(value, sr) for name, value in arrays.items()}
    baseline_level = next(iter(levels.values()))
    gains = {name: (10**((target_lufs - (level if match_loudness else baseline_level))/20)
                    if (level if match_loudness else baseline_level) is not None else 1.)
             for name, level in levels.items()}
    # Keep normalization bounded for near-silent conditions; silence is never
    # promoted into a loudness-matched condition or misreported as equivalent.
    gains = {name: min(gain, 10**(36/20)) for name, gain in gains.items()}
    maximum = max(peak(arrays[name]) * gain for name, gain in gains.items())
    protection = min(1., 10**(peak_db/20)/maximum) if maximum else 1.
    gains = {name: gain * protection for name, gain in gains.items()}
    return {name: (arrays[name]*gains[name]).astype('float32') for name in arrays}, {
        'policy': 'matched loudness, common peak protection' if match_loudness else 'one common gain',
        'source_lufs': levels, 'gains': gains, 'peak_protection_gain': protection,
        'target_lufs_before_peak_protection': target_lufs, 'peak_ceiling_dbfs': peak_db,
    }


def _encode(path, value, sr):
    path.parent.mkdir(parents=True, exist_ok=True)
    io.write_mp3(path, value, sr, bitrate='320k')
    decoded, _ = io.load_audio(path, sr=sr, mono=value.ndim == 1)
    if abs(len(decoded)-len(value)) > round(sr*.04) or not np.isfinite(decoded).all():
        raise RuntimeError(f'MP3 failed duration/sample validation: {path.name}')
    decoded_peak = peak(decoded)
    if decoded_peak >= 1:
        raise RuntimeError(f'MP3 clipping check failed: {path.name}')
    return {'sha256': P.file_sha256(path), 'samples': len(decoded),
            'sample_rate': sr, 'duration_s': len(decoded)/sr,
            'decoded_lufs': loudness(decoded, sr),
            'decoded_true_peak_dbfs': 20*np.log10(max(decoded_peak, 1e-15))}


def write_comparisons(output, conditions, sr, *, original=None, donors=None,
                      guide_vocal=None, details=None):
    """Create common-gain, matched-level and clearly labeled diagnostic MP3s."""
    output = Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty listening-pack folder to preserve previous comparisons.')
    output.mkdir(parents=True, exist_ok=True)
    expected = next(iter(conditions.values())).shape
    for name in conditions:
        if not name or Path(name).name != name or any(c in name for c in '<>:"/\\|?*'):
            raise ValueError('Comparison names must be plain filenames.')
    # Identical short edge fades suppress clip-boundary clicks for all versions.
    edge = np.ones(expected[0], dtype='float32'); width = min(round(sr*.02), len(edge)//2)
    if width:
        ramp=np.linspace(0, 1, width, dtype='float32'); edge[:width]=ramp;edge[-width:]=ramp[::-1]
    if len(expected)==2: edge=edge[:,None]
    arrays={name: np.asarray(a,dtype='float32')*edge for name,a in conditions.items()}
    report={'format':'heartbeam-mp3-comparisons','version':1,'details':details or {},'groups':{},'files':{}}
    for folder, matched in [('01-consistent-gain',False),('02-matched-loudness',True)]:
        encoded, policy = prepare_group(arrays,sr,match_loudness=matched)
        report['groups'][folder]=policy
        for name,value in encoded.items():
            relative=f'{folder}/{name}.mp3'
            report['files'][relative]=_encode(output/relative,value,sr)
        if matched:
            measured=[report['files'][f'{folder}/{name}.mp3']['decoded_lufs'] for name in encoded]
            finite=[x for x in measured if x is not None]
            report['groups'][folder]['decoded_loudness_spread_lu']=max(finite)-min(finite) if finite else None
    if original is not None:
        group,policy=prepare_group({'original-song':original*edge},sr)
        report['groups']['original-context']=policy
        report['files']['00-original-song.mp3']=_encode(output/'00-original-song.mp3',group['original-song'],sr)
    for name,value in (donors or {}).items():
        if value.shape != expected:
            raise ValueError('Donor audio must share the listening sample basis.')
        group,policy=prepare_group({name:value*edge},sr,target_lufs=-22.)
        relative=f'03-diagnostics/BOOSTED-{name}.mp3'
        report['files'][relative]=_encode(output/relative,group[name],sr)
        report['groups'][relative]=policy
    if guide_vocal is not None:
        base=next(iter(arrays.values()))
        guides={'reference-no-guide':base}
        guides.update({f'reference-{percent:02d}-percent-lead':base+guide_vocal*edge*(percent/100) for percent in (1,3,5)})
        group,policy=prepare_group(guides,sr)
        report['groups']['vocal-controls']=policy
        for name,value in group.items():
            relative=f'03-diagnostics/{name}.mp3'
            report['files'][relative]=_encode(output/relative,value,sr)
    (output/'mp3-manifest.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
    return report
