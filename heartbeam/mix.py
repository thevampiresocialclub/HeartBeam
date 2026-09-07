"""
Lyrics-aware mix: subtract the isolated lead-vocal stem from the original mix,
but only inside the time-domain mask (which marks word intervals).

Backing vocals live in a separate stem and are never touched. Instrumental
sections (mask == 0) pass through bit-identical to the input.
"""
from __future__ import annotations

import numpy as np


def mix(
    original: np.ndarray,
    lead_stem: np.ndarray,
    mask: np.ndarray,
    vocal_gain: float = 1.0,
    backing_stem: np.ndarray | None = None,
    backing_boost: float = 0.0,
    clip: bool = True,
) -> np.ndarray:
    """Subtract strategy: out = original - vocal_gain·mask·lead + backing_boost·mask·backing.

    original:      shape (N,) mono or (N, C) float32, range ~[-1, 1]
    lead_stem:     same shape — separator's isolated lead
    mask:          shape (N,) float32 in [0, 1]
    vocal_gain:    overshoot factor on the lead subtraction. 1.0 = mathematically
                   exact removal of whatever's in lead_stem. >1.0 trades subtraction
                   completeness for phase artifacts; 1.2-1.5 is typical for rock.
    backing_stem:  optional — when paired with backing_boost, adds separator-isolated
                   backing back in during masked intervals to compensate for harmony
                   energy that overshoot can eat into. Helps preserve gang vocals.
    backing_boost: 0.0 = off (default), 1.0 = full backing doubled. Typical 0.3-0.5.

    Only as clean as the separator. Anything in `original` that wasn't extracted
    into lead_stem stays as residue — overshoot (vocal_gain > 1) cancels more of
    that residue at the cost of phase artifacts.
    """
    if original.shape != lead_stem.shape:
        raise ValueError(
            f"shape mismatch: original {original.shape} vs lead_stem {lead_stem.shape}"
        )
    if mask.ndim != 1 or mask.shape[0] != original.shape[0]:
        raise ValueError(
            f"mask must be shape ({original.shape[0]},), got {mask.shape}"
        )

    m = mask[:, None] if original.ndim == 2 else mask
    out = original - vocal_gain * m * lead_stem
    if backing_stem is not None and backing_boost != 0.0:
        if backing_stem.shape != original.shape:
            raise ValueError(
                f"backing_stem shape {backing_stem.shape} doesn't match original {original.shape}"
            )
        out = out + backing_boost * m * backing_stem
    # clip=False is for the cached clean reference: the section mixer later
    # blends clean -> original, and clipping here would bake in distortion that
    # no downstream gain change can undo.
    if clip:
        out = np.clip(out, -1.0, 1.0)
    return out.astype(np.float32, copy=False)


def mix_replace(
    original: np.ndarray,
    instrumental: np.ndarray,
    backing: np.ndarray,
    mask: np.ndarray,
    clip: bool = True,
) -> np.ndarray:
    """Replace strategy: crossfade between original and (instrumental + backing).

    out = (1 - mask) * original + mask * (instrumental + backing)

    Fully eliminates the lead vocal during sung intervals because we don't rely on
    subtraction accuracy — we substitute the separated non-lead stems directly.
    Trade-off: any non-lead texture in `original` that the separator failed to
    capture into instrumental/backing is also lost during sung intervals.

    Peaks in `instrumental + backing` can exceed ±1.0 (the separators normalise
    each stem independently, so their literal sum is roughly `original − lead`
    which often peaks higher than `original`). Hard-clipping that with np.clip
    creates audible distortion that *sounds like* residual vocal because of how
    ears perceive clipping harmonics in the vocal frequency band. We therefore
    pre-scale the karaoke part so its peak matches the original's peak — uniform
    attenuation preserves relative levels and only kicks in when needed.
    """
    if not (original.shape == instrumental.shape == backing.shape):
        raise ValueError(
            f"shape mismatch: original {original.shape}, instrumental "
            f"{instrumental.shape}, backing {backing.shape}"
        )
    if mask.ndim != 1 or mask.shape[0] != original.shape[0]:
        raise ValueError(
            f"mask must be shape ({original.shape[0]},), got {mask.shape}"
        )

    karaoke = instrumental + backing
    peak_kar = float(np.max(np.abs(karaoke))) if karaoke.size else 0.0
    peak_orig = float(np.max(np.abs(original))) if original.size else 0.0
    if peak_kar > peak_orig and peak_kar > 0.0:
        karaoke = karaoke * (peak_orig / peak_kar)

    m = mask[:, None] if original.ndim == 2 else mask
    out = (1.0 - m) * original + m * karaoke
    if clip:
        out = np.clip(out, -1.0, 1.0)
    return out.astype(np.float32, copy=False)
