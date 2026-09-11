"""A deterministic rolling lyric scene shared by browser libass and export.

Each ASS segment uses absolute word offsets. Splitting a moving line into
events never restarts its karaoke timing, including a sweep already underway.
"""
from . import presentation as S, presentation_fonts as F, project as P, ass_writer as A


def layout(spec, line, breaks, face):
    box, font = spec['box'], spec['font']
    info = F.font_info(face)
    def measure(words):
        text = ' '.join(S.display_text(w) for w in words)
        return (sum(info['advances'].get(ord(c), .6) * font['size_px'] for c in text)
                + max(0, len(text) - 1) * font['letter_spacing_px'])
    rows, row = [], []
    for word in line.words:
        if row and (word.id in breaks or (box['wrap'] == 'auto' and measure(row + [word]) > box['width_px'])):
            rows.append(row); row = []
        row.append(word)
    if row:
        rows.append(row)
    pitch = font['size_px'] * font['line_height']
    glyph_height = font['size_px']  # ASS font size is the rendered line height.
    height = glyph_height + max(0, len(rows) - 1) * pitch
    vertical, horizontal = box['anchor'].split()
    left = box['x'] - {'left': 0, 'center': .5, 'right': 1}[horizontal] * box['width_px']
    top = box['y'] - {'top': 0, 'center': .5, 'bottom': 1}[vertical] * height
    return dict(x=box['x'], y=box['y'], left=left, top=top, width=box['width_px'],
                height=height, text_width=max(map(measure, rows), default=0), rows=rows, pitch=pitch)


def karaoke(words, timings, spec, start_ms):
    """Untimed text stays unsung; every timed word has its own absolute onset."""
    plain = A.hex_to_ass_colour(spec['colour']['primary'])
    sung = A.hex_to_ass_colour(spec['colour']['highlight'])
    tag = 'kf' if spec['highlight']['mode'] == 'sweep' else 'k'
    parts = []
    for word in words:
        timing = timings.get(word.id)
        if timing:
            onset = round(timing.start_ms / 10) - round(start_ms / 10)
            duration = max(1, round(timing.end_ms / 10) - round(timing.start_ms / 10))
            tags = f'{{\\1c{sung}\\2c{plain}\\kt{onset}\\{tag}{duration}}}'
        else:
            tags = f'{{\\1c{plain}\\2c{plain}\\kt0\\k0}}'
        parts.append(tags + A.escape_text(S.display_text(word)))
    return ' '.join(parts)


def compile_scene(project, duration_ms, root=None, *, draft=False, allow_timing_issues=False):
    from .project_preview import current_timings, timing_warnings, line_window
    current_timings(project, duration_ms, draft=draft, allow_timing_issues=allow_timing_issues)
    lenient_timing = draft or allow_timing_issues
    width, height = project.presentation.design_width, project.presentation.design_height
    base = S.resolved_style(project)
    script_style = S.as_legacy_style(base); script_style.video.resolution = f'{width}x{height}'
    header = A._build_script_info(script_style)
    schedule = S.display_settings(project)
    styles, warnings, fonts, entries, events = [], [], set(), [], []
    if allow_timing_issues:
        warnings.extend(timing_warnings(project, duration_ms))
    for index, line in enumerate(project.lines):
        spec = S.resolved_style(project, line.id)
        face, family, messages = F.resolve_face(project, root, spec['font'])
        warnings.extend(messages); fonts.add(face); spec['font']['family'] = family
        breaks = project.presentation.line_overrides.get(line.id, {}).get('break_before', [])
        geometry = layout(spec, line, breaks, face)
        if geometry['text_width'] > geometry['width'] + 1:
            warnings.append(f'Line {index + 1} may overflow its text box. Reduce the font size or add a line break.')
        glyphs = F.font_info(face)['advances']
        missing = sorted({c for w in line.words for c in S.display_text(w) if not c.isspace() and ord(c) not in glyphs})
        if missing:
            message = f"Line {index + 1}: {family} lacks characters {''.join(missing[:12])!r}. Choose a font containing these characters."
            if not draft:
                raise P.ProjectError(message)
            warnings.append(message)
        timings = {w.id: project.effective_timing(w.id) for w in line.words if not w.non_sung}
        timings = {wid: t for wid, t in timings.items() if t and t.resolved and 0 <= t.start_ms < t.end_ms <= duration_ms}
        if any(t.estimated for t in timings.values()):
            warnings.append(f'Line {index + 1}: some word highlights use estimated timing. Original and manual timings are preserved.')
        partial = len(timings) < sum(not w.non_sung for w in line.words)
        window = line_window(project, line, duration_ms) if lenient_timing and partial else None
        if not timings and not window:
            if partial:
                warnings.append(f'Line {index + 1} has no usable timing window and will not appear in the video.')
            continue
        starts = [t.start_ms for t in timings.values()] + ([window[0]] if window else [])
        ends = [t.end_ms for t in timings.values()] + ([window[1]] if window else [])
        first, last = min(starts), max(ends)
        start = max(0, first - schedule['advance_ms']) if schedule['automatic'] else line.display_start_ms
        end = min(duration_ms, last + schedule['hold_ms']) if schedule['automatic'] else line.display_end_ms
        start = first if start is None else start; end = last if end is None else end
        if not 0 <= start <= first < last <= end <= duration_ms:
            if not lenient_timing:
                raise P.ProjectError(f'Line {index + 1} has an invalid display window.')
            warnings.append(f'Line {index + 1}: invalid display window; using available lyric timing.')
            start, end = first, last
        if partial:
            warnings.append(f'Line {index + 1}: untimed words remain plain; words with timing still highlight.')
        name = f'Line{index}'
        style = S.as_legacy_style(spec); style.box.position = 'top'
        block = A._build_styles_block(style).replace('Style: Default,', f'Style: {name},')
        styles.append(block if not styles else block.splitlines()[-1] + '\n')
        entries.append(dict(line=line, name=name, spec=spec, geometry=geometry, timings=timings,
                            start=start, end=end, first=first, last=last, segments=[]))

    # A fixed-height viewport keeps the main position stable from first to last
    # phrase. It accommodates explicit/automatic wraps and per-line font sizes.
    visible = min(schedule['visible_lines'], len(entries))
    slot = max((max(e['geometry']['height'], len(e['geometry']['rows']) * e['geometry']['pitch']) for e in entries), default=0)
    stack_height = slot * visible
    for entry in entries:
        box = entry['spec']['box']; geometry = entry['geometry']
        top = box['y'] - {'top': 0, 'center': .5, 'bottom': 1}[box['anchor'].split()[0]] * stack_height
        entry['top'] = top
        if top < 0 or top + stack_height > height + 1 or geometry['left'] < 0 or geometry['left'] + geometry['width'] > width + 1:
            warnings.append('The lyric stack may overflow the canvas. Reduce font size, line height or visible lines, or adjust its placement.')
    # Finish the top phrase before promoting the next. Overlapping next words
    # can already highlight below it; their absolute timing is never serialized.
    boundaries = [round(entries[0]['start'] / 10) * 10] if entries else []
    for entry in entries[:-1]:
        boundaries.append(max(boundaries[-1], round(entry['last'] / 10) * 10))
    if entries:
        boundaries.append(max(boundaries[-1], round(entries[-1]['end'] / 10) * 10))
    if any(a['last'] > b['first'] for a, b in zip(entries, entries[1:])):
        warnings.append('Sung phrases overlap. Both rows keep their own word highlighting while the earlier phrase is on top.')

    def emit(entry, begin, end, from_top, to_top, moving_ms, outgoing=False):
        if end <= begin:
            return
        box, geometry = entry['spec']['box'], entry['geometry']
        text_x = geometry['left'] + {'left': 0, 'center': .5, 'right': 1}[box['alignment']] * box['width_px']
        clip_top = max(0, round(entry['top'])); clip_bottom = min(height, round(entry['top'] + stack_height))
        for row_index, words in enumerate(geometry['rows']):
            offset = row_index * geometry['pitch']
            position = (f'\\move({text_x:g},{from_top + offset:g},{text_x:g},{to_top + offset:g},0,{moving_ms})'
                        if moving_ms and from_top != to_top else f'\\pos({text_x:g},{to_top + offset:g})')
            tags = f'{{{position}\\q2\\clip(0,{clip_top},{width},{clip_bottom})' + (f'\\fad(0,{end - begin})' if outgoing else '') + '}'
            text = karaoke(words, entry['timings'], entry['spec'], begin)
            events.append(f"Dialogue: 0,{A._fmt_ass_time(begin / 1000)},{A._fmt_ass_time(end / 1000)},{entry['name']},,0,0,0,,{tags}{text}")
        if not outgoing:
            entry['segments'].append(dict(start_ms=begin, end_ms=end, from_top=from_top, to_top=to_top, move_ms=moving_ms))

    for current_index, current in enumerate(entries):
        begin, end = boundaries[current_index:current_index + 2]
        move = min(schedule['transition_ms'], end - begin) if current_index else 0
        for distance, entry in enumerate(entries[current_index:current_index + visible]):
            target = entry['top'] + distance * slot
            emit(entry, begin, end, target + (slot if move else 0), target, move)
        if move:
            previous = entries[current_index - 1]
            emit(previous, begin, begin + move, previous['top'], previous['top'] - slot, move, outgoing=True)

    layouts = []
    for index, entry in enumerate(entries):
        line, geometry = entry['line'], entry['geometry']
        overrides = project.presentation.line_overrides.get(line.id, {})
        layouts.append({k: v for k, v in geometry.items() if k not in ('rows', 'pitch')})
        layouts[-1].update(line_id=line.id, ass_name=entry['name'], word_id=next((w.id for w in line.words if not w.non_sung), line.words[0].id),
                          start_ms=boundaries[index], end_ms=boundaries[index + 1], seek_ms=entry['first'], label=line.text,
                          top=entry['top'], style=entry['spec'], exception=bool(overrides), segments=entry['segments'],
                          placement_exception=bool({'x', 'y'} & set(overrides.get('box', {}))))
    fallback, _, messages = F.resolve_face(project, root, {'family': 'Noto Sans', 'bold': False, 'italic': False})
    fonts.add(fallback); warnings.extend(messages)
    ass = header + '\n' + (''.join(styles) or A._build_styles_block(script_style)) + '\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n' + '\n'.join(events) + '\n'
    bg, messages = S.background(project, root, strict=not draft); warnings.extend(messages)
    return dict(ass=ass, fonts=sorted(fonts), fallback_font=fallback, lines=layouts, warnings=list(dict.fromkeys(warnings)),
                background=bg, width=width, height=height)
