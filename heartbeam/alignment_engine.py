"""Two timing sources, one phrase-first alignment pipeline.

Expensive recognition is cached by audio/model identity. Per-line proposals retain
all source tokens, including words the aligner could not place.
"""
from __future__ import annotations

import gc
import hashlib
import json
import logging
from pathlib import Path

import numpy as np

from . import alignment_match as matching
from .timings import AlignmentResult, Line, Word

log = logging.getLogger(__name__)


def unresolved_result(lyrics_text, reason, *, language='en', online=None):
    """Keep every lyric when models are unavailable after separation finishes."""
    from .align import _split_lyrics
    phrases, lines = [], []
    for index, text in _split_lyrics(lyrics_text):
        if text.startswith('#'):
            continue
        words = [dict(text=t, start_s=None, end_s=None, score=None, reason=reason) for t in text.split()]
        phrases.append(dict(index=index, text=text, anchor=None, words=words,
                            issues=['Some words need timing'], state='match_needed'))
        lines.append(Line(index, text, 0, 0, []))
    return AlignmentResult(lines, language or 'en', 0, 0,
        dict(version=1, phrases=phrases, failure=reason, online_candidate=online))


def align(samples, sr, lyrics_text, whisper_model='medium', device='cpu', language=None,
          *, cache_dir=None, online=None, manual_anchors=None, target_indices=None):
    from .paths import apply_env
    apply_env()
    import whisperx
    from .align import _resample_to_16k_mono, _split_lyrics

    lines = [(i,t) for i,t in _split_lyrics(lyrics_text) if not t.startswith('#')]
    if not lines:
        raise ValueError('Add lyrics before matching timing.')
    targets = set(target_indices) if target_indices is not None else {i for i,_ in lines}
    audio = _resample_to_16k_mono(samples, sr)
    duration = len(audio)/16000
    fingerprint = hashlib.sha256(audio.tobytes()).hexdigest()
    key = hashlib.sha256(f'phrase-v1:{fingerprint}:{whisper_model}:{device}:{language}'.encode()).hexdigest()
    cached = Path(cache_dir)/f'recognition-{key}.json' if cache_dir else None
    analysis = None
    if cached and cached.is_file():
        try:
            analysis = json.loads(cached.read_text(encoding='utf-8'))
            if not isinstance(analysis, dict) or analysis.get('audio_sha256') != fingerprint or \
                    analysis.get('version') != 1 or not isinstance(analysis.get('words'), list) or \
                    not isinstance(analysis.get('language'), str) or \
                    any(not isinstance(w, dict) or not isinstance(w.get('word'), str) for w in analysis.get('words', [])):
                analysis = None
        except (OSError, ValueError):
            pass
    if manual_anchors and targets and all(i in manual_anchors for i in targets):
        analysis = dict(language=language or 'en', words=[], segments=[])
    if analysis is None:
        log.info('Finding sung phrases in the complete vocals…')
        asr = whisperx.load_model(whisper_model, device, compute_type='float16' if device == 'cuda' else 'int8')
        result = asr.transcribe(audio, batch_size=8, language=language)
        lang = result.get('language', language or 'en')
        del asr
        gc.collect()
    else:
        log.info('Using saved vocal recognition…')
        lang = analysis['language']
    model, metadata = whisperx.load_align_model(language_code=lang, device=device)
    if analysis is None:
        recognized = whisperx.align(result['segments'], model, metadata, audio, device,
                                    return_char_alignments=False) if result['segments'] else {}
        analysis = dict(language=lang, segments=result['segments'], words=recognized.get('word_segments', []),
                        audio_sha256=fingerprint, model=whisper_model, version=1)
        if cached:
            cached.parent.mkdir(parents=True, exist_ok=True)
            temporary = cached.with_suffix('.tmp')
            temporary.write_text(json.dumps(analysis), encoding='utf-8')
            temporary.replace(cached)
    anchors = matching.phrase_anchors(lines, analysis['words'], duration)
    online_note = 'Local audio matching'
    if online and online.get('synced_lines'):
        imported, online_note = matching.online_anchors(lines, online['synced_lines'], anchors, duration)
        # Strong local evidence refines the broad LRC window; online fills holes.
        anchors = {**imported, **anchors}
        log.info(online_note)
    for index, bounds in (manual_anchors or {}).items():
        index = int(index)
        start, end = bounds
        if not (0 <= start < end <= duration):
            raise ValueError('Phrase boundaries must be inside the song, with end after start.')
        if index not in dict(lines):
            raise ValueError('The selected lyric line changed. Select it again.')
        anchors[index] = dict(index=index, text=dict(lines)[index], start_s=start, end_s=end,
                              onset_s=start, source='manual', coverage=1.)

    # Recover a single missed phrase between strong anchors with an acoustic
    # search over that bounded gap. Never spread multiple phrases by word count.
    for position, (index, text) in enumerate(lines):
        if index in anchors:
            continue
        previous = anchors.get(lines[position-1][0]) if position else None
        following = anchors.get(lines[position+1][0]) if position+1 < len(lines) else None
        if previous and following and previous['source'] != 'gap' and following['source'] != 'gap':
            start, end = previous['end_s'], following['start_s']
            if .4 < end-start < 18:
                anchors[index] = dict(index=index, text=text, start_s=start, end_s=end,
                                      onset_s=start, source='gap', coverage=0.)

    log.info('Matching words inside %d of %d lyric phrases…', len(anchors), len(lines))
    output, phrases = [], []
    for index, text in lines:
        if index not in targets:
            continue
        anchor = anchors.get(index)
        tokens = text.split()
        words = [dict(text=t, start_s=None, end_s=None, score=None, reason='Phrase needs matching') for t in tokens]
        def refine(window):
            proposal = [dict(text=t, start_s=None, end_s=None, score=None, reason='Word needs timing') for t in tokens]
            try:
                aligned = whisperx.align([dict(text=text, start=window['start_s'], end=window['end_s'])],
                             model, metadata, audio, device, return_char_alignments=False)
            except (RuntimeError, ValueError, IndexError) as exc:
                log.warning('Could not refine phrase %d: %s', index + 1, exc)
                aligned = {}
            got = aligned.get('word_segments', [])
            for target, source in matching.token_pairs(tokens, [w.get('word', '') for w in got]):
                word = got[source]
                start, end, score = word.get('start'), word.get('end'), word.get('score', 0.)
                if all(isinstance(v, (int, float)) for v in (start,end,score)) and np.isfinite([start,end,score]).all() \
                        and window['start_s']-.05 <= start < end <= window['end_s']+.05 and score >= .1:
                    proposal[target] = dict(text=tokens[target], start_s=start, end_s=end,
                                         score=score, reason=None)
                else:
                    proposal[target]['reason'] = 'Word could not be placed reliably in this phrase'
            return proposal
        disagreement = False
        if anchor:
            words = refine(anchor)
            if matching.refinement_conflicts(words, anchor):
                retry = matching.compact_anchor(anchor, len(tokens))
                if retry:
                    log.info('Retrying phrase %d inside its supported words', index + 1)
                    anchor, words = retry, refine(retry)
                if matching.refinement_conflicts(words, anchor):
                    disagreement = True
                    words = [dict(text=t,start_s=None,end_s=None,score=None,
                                  reason='Word refinement disagrees with acoustic phrase evidence') for t in tokens]
        issues = matching.word_review(words)
        if disagreement:
            issues.append('Word timing disagrees with the recognized phrase; set approximate boundaries')
        if anchor and anchor['source'] == 'gap':
            issues.append('Recovered between phrases; check this line')
        state = 'match_needed' if not anchor else 'check' if issues else 'ready'
        phrases.append(dict(index=index, text=text, anchor=anchor, words=words, issues=issues, state=state))
        resolved = [Word(w['text'], w['start_s'], w['end_s'], w['score']) for w in words if w['start_s'] is not None]
        output.append(Line(index, text, min((w.start_s for w in resolved), default=anchor['start_s'] if anchor else 0),
                           max((w.end_s for w in resolved), default=anchor['end_s'] if anchor else 0), resolved))
    for phrase in phrases:
        siblings = [i for i,text in lines if matching.normalize(text) == matching.normalize(phrase['text'])]
        if len(siblings) > 1 and any(i not in anchors for i in siblings) and phrase['anchor']:
            phrase['issues'].append('Repeated phrase has unmatched occurrences; check the repetition')
            phrase['state'] = 'check'
    diagnostics = dict(version=1, phrases=phrases, audio_sha256=fingerprint, model=whisper_model,
                       language=lang, online=online_note,
                       online_candidate=online,
                       recognition_cache=str(cached) if cached else None,
                       input_lyrics_sha256=hashlib.sha256(lyrics_text.encode()).hexdigest())
    return AlignmentResult(output, lang, sum(w.score < .3 for ln in output for w in ln.words),
                           sum(len(ln.words) for ln in output), diagnostics)
