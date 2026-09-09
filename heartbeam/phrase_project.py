"""Explicit saved-audio alignment and identity-checked, undoable proposals."""
from __future__ import annotations
import copy
import hashlib
from dataclasses import asdict
from pathlib import Path
import soundfile as sf
from . import project as P


def vocal_audio(project, root):
    def read(asset):
        path = asset.resolve(root)
        if asset.sha256 and P.file_sha256(path) != asset.sha256:
            raise P.ProjectError('A saved vocal track or original recording has changed. Relink the correct audio before matching.')
        return sf.read(str(path), dtype='float32', always_2d=True)
    complete = project.asset_by_role('vocals_stem')
    if complete and complete.resolve(root).is_file():
        samples, sr = read(complete)
        return samples, sr, 'complete vocals'
    parts, basis = [], None
    for role in ('lead_stem', 'backing_stem'):
        asset = project.asset_by_role(role)
        if asset is None or not asset.resolve(root).is_file():
            parts = []
            break
        samples, sr = read(asset)
        current = (sr, samples.shape)
        if basis is not None and current != basis:
            raise P.ProjectError('Saved vocal tracks have different lengths or sample rates. Relink matching tracks.')
        basis = current
        parts.append(samples)
    if parts:
        return parts[0] + parts[1], basis[0], 'combined saved lead and backing'
    original = project.asset_by_role('original_audio')
    if original and original.resolve(root).is_file():
        samples, sr = read(original)
        return samples, sr, 'original recording (full vocals unavailable)'
    raise P.ProjectError('Link the original recording or both saved vocal tracks before matching timing.')


def align_saved(project, root, *, line_ids=None, bounds=None, device='cpu'):
    from . import align, timings as T
    root = Path(root)
    samples, sr, source = vocal_audio(project, root)
    prepared_asset = None
    if source == 'combined saved lead and backing':
        digest = hashlib.sha256(samples.tobytes()).hexdigest()[:16]
        path = root / P.AUDIO_DIR / f'vocals-{digest}.wav'
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            temporary = path.with_suffix('.tmp.wav')
            sf.write(str(temporary), samples, sr, subtype='FLOAT')
            temporary.replace(path)
        prepared_asset = P.Asset(P.new_id('asset'), 'vocals_stem', str(path.relative_to(root)),
            sha256=P.file_sha256(path), sample_rate=sr, channels=samples.shape[1],
            sample_count=len(samples), duration_ms=P.seconds_to_ms(len(samples)/sr))
    selected = set(line_ids) if line_ids is not None else {ln.id for ln in project.lines}
    indexed = {i: ln for i,ln in enumerate(project.lines) if ln.id in selected}
    # Keep the whole lyric sequence as context, so a selected chorus is matched
    # to its own occurrence. Only the selected lines are refined and applied.
    text = '\n'.join(' '.join(w.text for w in ln.words if not w.non_sung)
                     for ln in project.lines)
    manual = {i: bounds[ln.id] for i,ln in indexed.items() if bounds and ln.id in bounds}
    result = align.align(samples, sr, text,
        whisper_model=project.provenance.whisper_model or 'medium', device=device,
        cache_dir=root / P.CACHE_DIR / 'alignment', online=project.alignment.get('online_candidate'),
        manual_anchors=manual, target_indices=list(indexed),
        language=project.alignment.get('last_run', {}).get('language'))
    result.diagnostics['source'] = source
    if prepared_asset:
        result.diagnostics['prepared_vocals'] = asdict(prepared_asset)
    result.diagnostics['input_words'] = {str(i): [[w.id,w.text] for w in ln.words if not w.non_sung]
                                          for i,ln in indexed.items()}
    result.diagnostics['input_lines'] = {str(i): ln.id for i,ln in indexed.items()}
    artifact = T.Timings(T.Source(source, 'project lyrics', sr, len(samples)/sr),
                         T.Models(project.provenance.separator_preset or 'saved', 'phrase-whisperx'),
                         result.lines, alignment=result.diagnostics)
    dest = root / P.ASSETS_DIR / f"alignment-{P.new_id('run')}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    T.to_json(artifact, dest)
    result.diagnostics['artifact'] = str(dest.relative_to(root))
    return result


def apply_result(project, result, *, only_unresolved=False):
    diagnostics = result.diagnostics
    for index, expected in diagnostics['input_words'].items():
        line = project.find_line(diagnostics['input_lines'][index])
        actual = [[w.id,w.text] for w in line.words if not w.non_sung] if line else None
        if actual != expected:
            raise P.ProjectError('Lyrics changed while matching timing. Run matching again for the changed section.')
    filled = skipped = 0
    if diagnostics.get('prepared_vocals') and project.asset_by_role('vocals_stem') is None:
        project.assets.append(P.Asset(**diagnostics['prepared_vocals']))
    for phrase in diagnostics['phrases']:
        key = str(phrase['index'])
        line = project.find_line(diagnostics['input_lines'][key])
        targets = diagnostics['input_words'][key]
        if [t[1] for t in targets] != [w['text'] for w in phrase['words']]:
            raise P.ProjectError('Alignment words no longer match this lyric line.')
        old_times = [project.effective_timing(w.id) for w in line.words]
        old_times = [t for t in old_times if t and t.resolved]
        automatic_window = not old_times or (line.display_start_ms == min(t.start_ms for t in old_times)
                            and line.display_end_ms == max(t.end_ms for t in old_times))
        for (wid, _), source in zip(targets, phrase['words']):
            current, manual = project.raw_timing(wid), project.timing_edits.get(wid)
            if (manual and manual.resolved and not manual.estimated) or (only_unresolved and current and current.resolved and not current.estimated):
                skipped += 1
                continue
            project.alignment_proposals[wid] = P.WordTiming(
                P.seconds_to_ms(source['start_s']) if source['start_s'] is not None else None,
                P.seconds_to_ms(source['end_s']) if source['end_s'] is not None else None,
                source['score'], source['reason'])
            if manual and (not manual.resolved or manual.estimated):
                project.timing_edits.pop(wid)
            project.reviewed.pop(wid, None)
            filled += source['start_s'] is not None
        entry = copy.deepcopy(phrase)
        entry['word_ids'] = [t[0] for t in targets]
        project.alignment.setdefault('phrases', {})[line.id] = entry
        new_times = [project.effective_timing(w.id) for w in line.words]
        new_times = [t for t in new_times if t and t.resolved]
        if automatic_window and new_times:
            line.display_start_ms = min(t.start_ms for t in new_times)
            line.display_end_ms = max(t.end_ms for t in new_times)
    project.alignment['last_run'] = {k:v for k,v in diagnostics.items() if k not in ('phrases','input_words','input_lines')}
    project.alignment.pop('failure', None)
    return True, f'{filled} word timings applied; {skipped} existing corrections kept. Save to keep this work.'


def review_lines(project):
    from .alignment_match import word_review
    result = []
    for number, line in enumerate(project.lines, 1):
        words = []
        for word in line.words:
            if word.non_sung:
                continue
            t = project.effective_timing(word.id)
            words.append(dict(start_s=t.start_ms/1000 if t and t.resolved else None,
                              end_s=t.end_ms/1000 if t and t.resolved else None,
                              score=1. if project.reviewed.get(word.id) or (word.id in project.timing_edits and t and t.resolved and not t.estimated) else
                              t.score if t and t.score is not None else 0.))
        issues = word_review(words)
        phrase = project.alignment.get('phrases', {}).get(line.id, {})
        if phrase.get('anchor') and phrase['anchor'].get('source') != 'manual':
            if not all(project.reviewed.get(w.id) or (w.id in project.timing_edits and project.timing_edits[w.id].resolved) for w in line.words):
                issues += [issue for issue in phrase.get('issues', []) if issue.startswith(('Repeated phrase','Recovered between'))]
        if phrase and phrase.get('word_ids') != [w.id for w in line.words if not w.non_sung]:
            issues.append('Lyrics changed since phrase matching')
        if issues:
            result.append((line, number, issues))
    return result


def phrase_window(project, line, duration_ms):
    """A current phrase anchor supports draft display and labelled estimates."""
    entry = project.alignment.get('phrases', {}).get(line.id, {})
    if entry.get('word_ids') != [w.id for w in line.words if not w.non_sung]:
        return None
    anchor = entry.get('anchor') or {}
    try:
        start, end = P.seconds_to_ms(anchor['start_s']), P.seconds_to_ms(anchor['end_s'])
        if 0 <= start < end <= duration_ms:
            return start, end
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return None
