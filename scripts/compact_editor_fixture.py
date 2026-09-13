"""Synthetic separated-track workstation for layout and interaction proof."""
from pathlib import Path
import sys

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from heartbeam import project as P, presentation as S, vocal_mix as V, stem_mix as M


def build(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    p = P.create_project(root, 'Workstation playback and separated vocals (long project title)')
    phrases = ['Follow the morning light', 'Sing with the stars tonight',
               'Keep every little word in time', 'Let the next line rise',
               'Hear the music carry on', 'Bring the melody back home']
    for i, phrase in enumerate(phrases):
        line = P.Line(f'line{i}', [P.Word(f'w{i}-{j}', text) for j, text in enumerate(phrase.split())],
                      display_start_ms=i * 4000, display_end_ms=(i + 1) * 4000)
        p.lines.append(line)
        for j, word in enumerate(line.words):
            p.original_alignment[word.id] = P.WordTiming(i * 4000 + 300 + j * 440, i * 4000 + 700 + j * 440, .99)
    sr = 8000
    t = np.arange(sr * 24) / sr
    def tone(frequency, gain):
        return np.repeat((gain * np.sin(2 * np.pi * frequency * t) * (.6 + .4 * np.sin(2 * np.pi * .4 * t)))[:, None], 2, axis=1).astype(np.float32)
    instrumental, lead, backing = tone(220, .2), tone(440, .15), tone(880, .07)
    for role, samples in [('original_audio', instrumental + lead + backing), ('clean_audio', instrumental),
                          ('karaoke_audio', instrumental + backing * .5), ('instrumental_stem', instrumental),
                          ('lead_stem', lead), ('backing_stem', backing)]:
        path = root / f'{role}.wav'
        sf.write(path, samples, sr, subtype='FLOAT')
        P.add_asset(p, root, path, role)
    V.bind_references(p, source_sha256=p.asset_by_role('original_audio').sha256,
                      recipe={'mix_strategy': 'replace', 'pad_ms': 0, 'crossfade_ms': 20, 'merge_gap_ms': 0})
    M.enable(p, root, backing=.5)
    p.vocal_mix.default_value = .03
    p.vocal_mix.regions = [P.VocalRegion('test-region', 8000, 12000, .4)]
    S.set_display_settings(p, {'automatic': True, 'visible_lines': 3})
    P.save_project(p, root, bump=False)
    print(root)


if __name__ == '__main__':
    build(sys.argv[1])
