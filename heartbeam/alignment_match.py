"""Phrase anchors from textual evidence. No ML, network, or project mutations."""
from __future__ import annotations

from array import array
from difflib import SequenceMatcher
from functools import lru_cache
import math
import re
from statistics import median
import unicodedata


def normalize(text):
    text = unicodedata.normalize('NFKC', text).replace('\u2019', "'").casefold()
    return re.sub(r"[^\w]", '', text)


def token_pairs(expected, observed):
    """Global monotone fuzzy edit alignment. Omissions do not shift later words.

    Returned pairs require an actual token match, never a positional allocation.
    Repeated choruses share one sequence so each occurrence is consumed once.
    """
    a, b = [normalize(x) for x in expected], [normalize(x) for x in observed]
    m, n = len(a), len(b)
    if m * n > 6_000_000:
        raise ValueError('Too many words for one alignment. Select a shorter section.')

    @lru_cache(maxsize=32768)
    def similarity(x, y):
        if not x or not y:
            return 0.
        if x == y:
            return 1.
        if min(len(x), len(y)) < 3:
            return 0.
        return SequenceMatcher(None, x, y).ratio()

    trace = [bytearray(n + 1) for _ in range(m + 1)]
    previous = array('f', [-.8 * j for j in range(n + 1)])
    for i in range(1, m + 1):
        row = array('f', [-.8 * i] + [0.] * n)
        for j in range(1, n + 1):
            sim = similarity(a[i-1], b[j-1])
            diagonal = previous[j-1] + (3 * sim if sim >= .72 else -2.)
            up, left = previous[j] - .8, row[j-1] - .8
            if diagonal >= max(up, left):
                row[j], trace[i][j] = diagonal, 1
            elif up >= left:
                row[j], trace[i][j] = up, 2
            else:
                row[j], trace[i][j] = left, 3
        previous = row
    pairs = []
    i, j = m, n
    while i and j:
        direction = trace[i][j]
        if direction == 1:
            if similarity(a[i-1], b[j-1]) >= .72:
                pairs.append((i-1, j-1))
            i -= 1; j -= 1
        elif direction == 2:
            i -= 1
        else:
            j -= 1
    return pairs[::-1]


def phrase_anchors(lines, observed, duration):
    """Find source phrases in acoustically timed ASR words."""
    observed = [w for w in observed if w.get('start') is not None and w.get('end') is not None
                and math.isfinite(w['start']) and math.isfinite(w['end'])
                and 0 <= w['start'] < w['end'] <= duration + .05]
    expected = [t for _, text in lines for t in text.split()]
    pairs = dict(token_pairs(expected, [w['word'] for w in observed]))
    anchors, cursor = {}, 0
    for index, text in lines:
        tokens = text.split()
        hits = [(k, observed[pairs[cursor+k]]) for k in range(len(tokens)) if cursor+k in pairs]
        cursor += len(tokens)
        coverage = len(hits) / max(1, len(tokens))
        if coverage < .6 or len(hits) < min(2, len(tokens)):
            continue
        start, end = hits[0][1]['start'], hits[-1][1]['end']
        gaps = [b[1]['start'] - a[1]['end'] for a, b in zip(hits, hits[1:])]
        if max(gaps, default=0) > 3.0 or end-start > max(12, len(tokens)*1.5):
            continue
        anchors[index] = dict(index=index, text=text, start_s=max(0, start-.35-hits[0][0]*.3),
            end_s=min(duration, end+.45+(len(tokens)-1-hits[-1][0])*.3),
            onset_s=start, source='audio', coverage=coverage)
    return anchors


def online_anchors(lines, synced_lines, audio_anchors, duration):
    """Accept database timing only with distributed acoustic corroboration.

    LRC line boundaries are search hints. They are not exact word boundaries.
    Different wrapping is reconciled through the complete token sequence.
    """
    cues = [line for line in synced_lines if line.get('text', '').strip()]
    if any(not isinstance(line.get('start_s'), (int, float)) or
           not math.isfinite(line['start_s']) or line['start_s'] < 0 for line in synced_lines):
        return {}, 'Online timing contains invalid timestamps; using audio matching.'
    if any(line['start_s'] > duration + 2 for line in cues):
        last = max(line['start_s'] for line in cues)
        return {}, (f'Online lyrics continue to {last:.1f}s, but this recording is {duration:.1f}s. '
                    'The timing sheet does not fit this recording; using audio matching.')
    if any(a['start_s'] > b['start_s'] for a,b in zip(synced_lines,synced_lines[1:])):
        return {}, 'Online timestamps are out of order; using audio matching.'
    flat, times = [], []
    for pos, line in enumerate(synced_lines):
        end = synced_lines[pos+1]['start_s'] if pos+1 < len(synced_lines) else duration
        for token in line['text'].split():
            flat.append(token); times.append((line['start_s'], end))
    pairs = dict(token_pairs([t for _, text in lines for t in text.split()], flat))
    candidates, cursor = {}, 0
    for index, text in lines:
        tokens = text.split()
        hits = [times[pairs[cursor+k]] for k in range(len(tokens)) if cursor+k in pairs]
        cursor += len(tokens)
        if len(hits) >= max(1, math.ceil(.8*len(tokens))):
            candidates[index] = (min(t[0] for t in hits), max(t[1] for t in hits))
    checks = [(index, audio_anchors[index]['onset_s']-bounds[0]) for index,bounds in candidates.items()
              if index in audio_anchors and audio_anchors[index]['coverage'] >= .75]
    reason = 'Online timing could not be verified against enough of this recording; using audio matching.'
    if len(checks) < 3:
        return {}, reason
    offset = median(delta for _,delta in checks)
    inliers = [(i,d) for i,d in checks if abs(d-offset) <= 1.5]
    spread = [audio_anchors[i]['onset_s'] for i,_ in inliers]
    if len(inliers) < 3 or len(inliers) < .8*len(checks) or max(spread)-min(spread) < duration*.45:
        return {}, reason
    anchors = {}
    for index, (start,end) in candidates.items():
        local = audio_anchors.get(index)
        if local and abs(local['onset_s']-(start+offset)) > 2.:
            continue
        # A long instrumental gap before the next LRC cue is not sung duration.
        end = min(end, local['end_s']-offset if local else start+max(8,len(dict(lines)[index].split())*1.2))
        if end <= start or start+offset >= duration or end+offset <= 0:
            continue
        anchors[index] = dict(index=index, text=dict(lines)[index], start_s=max(0,start+offset-.5),
            end_s=min(duration,end+offset+.5), onset_s=max(0,start+offset),
            source='online', coverage=1., offset_s=offset)
    return anchors, f'Online timing checked against {len(inliers)} phrases; offset {offset:+.2f} seconds.'


def word_review(words):
    issues = []
    timed = [w for w in words if w.get('start_s') is not None]
    if len(timed) != len(words):
        issues.append('Some words need timing')
    if any(w.get('score', 0) < .3 for w in timed):
        issues.append('Low-confidence words')
    if any(w['end_s']-w['start_s'] < .04 for w in timed):
        issues.append('Very short word timing')
    if any(b['start_s']-a['end_s'] > 3 for a,b in zip(timed,timed[1:])):
        issues.append('Long gap inside the phrase')
    if any(a['end_s'] > b['start_s']+.001 for a,b in zip(timed,timed[1:])):
        issues.append('Overlapping words')
    return issues
