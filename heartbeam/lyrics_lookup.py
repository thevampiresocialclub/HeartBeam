"""Read-only LRCLIB lookup. Cached metadata/lyrics; never uploads song audio."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .alignment_match import normalize


def parse_lrc(text):
    offset = re.search(r'\[offset:([+-]?\d+)\]', text or '', re.I)
    offset = int(offset[1])/1000 if offset else 0
    result = []
    pattern = r'\[(\d+):(\d{1,2}(?:\.\d+)?)\]'
    for raw in (text or '').splitlines():
        stamps = re.findall(pattern, raw)
        lyric = re.sub(pattern, '', raw).strip()
        for minutes, seconds in stamps:
            start = int(minutes)*60 + float(seconds) + offset
            if 0 <= float(seconds) < 60 and start >= 0:
                result.append({'start_s': start, 'text': lyric})
    return sorted(result, key=lambda ln: ln['start_s'])


def _request(route, params):
    url = 'https://lrclib.net/api/' + route + '?' + urlencode(params)
    request = Request(url, headers={'User-Agent': 'HeartBeam/0.1 (local karaoke editor)',
                                   'Accept': 'application/json'})
    with urlopen(request, timeout=12) as response:
        body = response.read(4_000_001)
        if len(body) > 4_000_000:
            raise ValueError('Lyrics response was too large.')
        return json.loads(body)


def _candidate(item, metadata):
    if not isinstance(item, dict) or item.get('instrumental'):
        return None
    plain, synced = item.get('plainLyrics') or '', item.get('syncedLyrics') or ''
    if not isinstance(plain, str) or not isinstance(synced, str):
        return None
    lines = parse_lrc(synced)
    if not plain:
        plain = '\n'.join(line['text'] for line in lines if line['text'])
    if not plain.strip():
        return None
    duration = float(item.get('duration') or 0)
    if not math.isfinite(duration) or duration < 0:
        return None
    title, artist = str(item.get('trackName', '')), str(item.get('artistName', ''))
    requested = float(metadata.get('duration') or 0)
    rank = (normalize(title) != normalize(metadata['title']),
            normalize(artist) != normalize(metadata['artist']),
            abs(duration-requested) if requested else 0, not bool(lines))
    return dict(id=item.get('id'), title=title, artist=artist, album=str(item.get('albumName') or ''),
                duration=duration, lyrics=plain, synced_lines=lines, provider='lrclib', rank=list(rank))


def lookup(metadata, cache_dir, *, request=_request):
    """Return candidates plus a visible status. Network errors have an offline path."""
    metadata = {key: metadata.get(key, '') for key in ('title','artist','album','duration')}
    if not str(metadata['title']).strip() or not str(metadata['artist']).strip():
        return {'candidates': [], 'status': 'Enter a song title and artist to find lyrics.'}
    cache_dir = Path(cache_dir)
    key = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    path = cache_dir / f'lrclib-{key}.json'
    cached = None
    try:
        cached = json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(cached.get('candidates'), list) or any(
            not isinstance(c, dict) or not all(k in c for k in ('id','title','artist','album','duration','lyrics','synced_lines'))
            for c in cached['candidates']):
            raise ValueError('Invalid saved lyrics result')
        if time.time()-cached['retrieved_at'] < 86400:
            return {**cached, 'status': 'Using saved lyrics results.'}
    except (OSError, ValueError, KeyError, TypeError):
        cached = None
    params = {'track_name': metadata['title'], 'artist_name': metadata['artist']}
    if metadata['album']:
        params['album_name'] = metadata['album']
    if metadata['duration']:
        params['duration'] = metadata['duration']
    try:
        try:
            exact = request('get', params)
            raw = [exact] if isinstance(exact, dict) else []
        except HTTPError as exc:
            if exc.code != 404:
                raise
            raw = []
        if not raw or not raw[0].get('syncedLyrics'):
            found = request('search', {k:v for k,v in params.items() if k != 'duration'})
            if isinstance(found, list):
                raw += found
        candidates, seen = [], set()
        for item in raw:
            candidate = _candidate(item, metadata)
            if candidate and candidate['id'] not in seen:
                candidates.append(candidate); seen.add(candidate['id'])
        candidates.sort(key=lambda c: c['rank'])
        result = dict(candidates=candidates[:8], retrieved_at=time.time(), metadata=metadata,
                      status='Choose the recording that matches your song.' if candidates else
                      'No lyrics found. Paste lyrics and use local timing.')
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.tmp')
            temporary.write_text(json.dumps(result), encoding='utf-8')
            temporary.replace(path)
        except OSError:
            pass  # Cache failure must not discard a successful lookup.
        return result
    except (OSError, URLError, ValueError, TypeError, KeyError) as exc:
        if cached:
            return {**cached, 'status': 'Online lookup unavailable; using saved results.'}
        return dict(candidates=[], status='Online lookup unavailable. Paste lyrics and use local timing.',
                    detail=str(exc))


def audio_metadata(source):
    """Read tags/duration from a path or seekable upload without saving it."""
    try:
        # Existing installations may not have picked up this new dependency.
        # Metadata prefilling is optional; uploading and editing must still work.
        from mutagen import File
        audio = File(source, easy=True)
        if audio is None:
            return {}
        tags = audio.tags or {}
        return dict(title=(tags.get('title') or [''])[0], artist=(tags.get('artist') or [''])[0],
                    album=(tags.get('album') or [''])[0], duration=float(audio.info.length))
    except Exception:
        return {}
    finally:
        if hasattr(source, 'seek'):
            source.seek(0)
