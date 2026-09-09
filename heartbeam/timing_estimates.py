"""Deterministic, labelled word estimates; never overwrite acoustic/manual data."""
from functools import lru_cache
from . import project as P


def enabled(project):
    return project.alignment.get('estimate_missing_words', True) is True


def estimate(project, word_id):
    if not enabled(project):
        return None
    line = next((line for line, word in project.iter_words() if word.id == word_id), None)
    if line is None:
        return None
    words = [w for w in line.words if not w.non_sung]
    from .phrase_project import phrase_window
    audio = project.asset_by_role('original_audio') or project.asset_by_role('instrumental_stem')
    duration = audio.duration_ms if audio and audio.duration_ms else float('inf')
    phrase = phrase_window(project, line, duration)
    inputs = tuple((w.id, max(1, sum(c.isalnum() for c in w.text)),
                    t.start_ms if t and t.resolved else None,
                    t.end_ms if t and t.resolved else None)
                   for w in words for t in [project.raw_timing(w.id)])
    bounds = _line_estimates(inputs, phrase).get(word_id)
    if bounds and bounds[1] <= duration:
        return P.WordTiming(*bounds, score=0., reason='Estimated from surrounding words or phrase timing', estimated=True)
    return None


@lru_cache(maxsize=2048)
def _line_estimates(words, phrase):
    estimates, index = {}, 0
    valid = lambda w: w[2] is not None and w[3] is not None and 0 <= w[2] < w[3]
    while index < len(words):
        if valid(words[index]):
            index += 1
            continue
        first = index
        while index < len(words) and not valid(words[index]):
            index += 1
        left = words[first - 1] if first else None
        right = words[index] if index < len(words) else None
        start = left[3] if left else phrase[0] if phrase else None
        end = right[2] if right else phrase[1] if phrase else None
        if start is None or end is None:
            continue  # Do not spread unanchored verses through instrumental gaps.
        gap = words[first:index]
        weights = sum(w[1] for w in gap)
        if end - start < len(gap) * 10 and left and right and left[2] < right[2]:
            # A dropped word can be absorbed into its predecessor's duration.
            # Borrow the tail of the onset interval without changing that known
            # word. This estimated overlap is intentional, not a timing conflict.
            available = right[2] - left[2]
            start = left[2] + round(available * left[1] / (left[1] + weights))
        if phrase:
            start, end = max(start, phrase[0]), min(end, phrase[1])
        if end - start < len(gap) * 10:
            continue
        remaining = end - start - len(gap) * 10
        cursor, cumulative = start, 0
        for offset, word in enumerate(gap):
            cumulative += word[1]
            finish = start + (offset + 1) * 10 + round(remaining * cumulative / weights)
            estimates[word[0]] = (cursor, finish)
            cursor = finish
    return estimates
