"""Timing and vocal editor controls; all durable edits use History.execute."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import streamlit as st

from . import editor as E, editor_media as media, project as P, lyrics, vocal_mix as V
from .commands import History, CommandError
from .project_preview import preview_payload


def history(project):
    if st.session_state.get("history_project") != project.id:
        st.session_state.history_project = project.id
        st.session_state.undo_stack = History()
        st.session_state.selected_word_id = None
    return st.session_state.undo_stack


def change(project, action, *, command=None, save_root=None):
    h = history(project)
    try:
        result = h.execute(project, action,
                           command_id=command.get("id") if command else None,
                           base_revision=command.get("base_revision") if command else None)
        st.session_state.timing_message = ("ok", result[1] if isinstance(result, tuple) else "Changes applied. Save to keep them.")
        if save_root:
            P.save_project(project, save_root, bump=False)
            saved = project.to_dict()
            saved.pop("modified_at", None); saved.pop("revision", None)
            saved.pop("command_ids", None)
            st.session_state.project_saved_snapshot = json.dumps(saved, sort_keys=True)
    except (P.ProjectError, ValueError, OSError, TypeError) as exc:
        st.session_state.timing_message = ("err", str(exc))
    if command:
        st.session_state[f"command_ack_{project.id}"] = command["id"]
    st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1
    st.rerun()


def vocal_action(project, selection, duration):
    if selection.get("song"):
        project.vocal_mix.default_value = V.level(selection["value"])
        project.vocal_mix.transition_ms = V._ms(selection.get("transition_ms", 40), "Transition")
    else:
        region = P.VocalRegion(selection.get("region_id") or P.new_id("vr"),
                selection["start_ms"], selection["end_ms"], V.level(selection["value"]),
                selection.get("transition_ms", 40), selection.get("source_line_ids", []),
                selection.get("source_word_ids", []), selection.get("source_section_id"))
        V.insert_region(project.vocal_mix, region, duration)


def track_action(project, data):
    if project.vocal_mix.restoration_mode != 'separated_stems':
        raise P.ProjectError('Enable separate track controls first.')
    value = V.level(data['value'])
    if data.get('track') == 'lead':
        project.vocal_mix.default_value = value
    elif data.get('track') == 'backing':
        project.vocal_mix.backing_value = value
    else:
        raise P.ProjectError('Choose lead or backing vocals.')
    return True, 'Track volume updated. Save to keep this mix.'


def _timing_controls(project, duration):
    h = history(project)
    from .timing_estimates import enabled
    automatic = st.checkbox('Estimate missing word timing', enabled(project),
        key=f'estimate_timing_{project.id}_{project.revision}',
        help='Fill gaps using surrounding words or phrase boundaries. Estimates stay labelled and update when nearby timing changes.')
    if automatic != enabled(project):
        change(project, lambda p: p.alignment.__setitem__('estimate_missing_words', automatic))
    estimates = project.estimated_word_ids()
    if estimates:
        st.caption(f'{len(estimates)} words use estimated timing and can highlight. You can edit them like any other word.')
    selected = st.session_state.get("selected_word_id")
    word = project.find_word(selected)
    nav = st.columns(3)
    if nav[0].button("Next untimed word", key="next_untimed"):
        st.session_state.selected_word_id = E.next_unresolved(project, selected)
        st.rerun()
    if nav[1].button("Next uncertain word", key="next_uncertain"):
        st.session_state.selected_word_id = E.next_low_confidence(project, selected)
        st.rerun()
    nav[2].caption(f"{len(project.unresolved_words())} untimed · {sum(project.reviewed.values())} reviewed")
    conflicts = E.timing_conflicts(project)
    if conflicts:
        with st.expander(f"Timing conflicts ({len(conflicts)})"):
            st.caption("Imported timings were preserved. Timing problems show warnings and do not block video rendering.")
            for (a, b), amount in list(conflicts.items())[:30]:
                st.write(f"{project.find_word(a).text} → {project.find_word(b).text}: {amount} ms overlap")
    if not word:
        st.caption("Select a lyric word to set its timing, shift its line, or mark it reviewed.")
        return
    timing = project.effective_timing(word.id)
    st.markdown(f"Selected word: **{word.text}**")
    if timing and timing.estimated:
        st.info('Estimated from nearby words or phrase timing. Set a manual timing to override it.')
    identity = f"{project.id}_{word.id}_{project.revision}"
    with st.form(f"timing_numbers_{identity}"):
        cols = st.columns(2)
        start = cols[0].number_input("Start (ms)", min_value=0, max_value=duration,
                  value=min(duration, max(0, timing.start_ms or 0)) if timing else 0, step=1)
        end = cols[1].number_input("End (ms)", min_value=0, max_value=duration,
                  value=min(duration, max(0, timing.end_ms or 500)) if timing else min(duration, 500), step=1)
        if st.form_submit_button("Set word timing"):
            change(project, lambda p: E.set_manual_timing(p, word.id, start, end, duration))
    cols = st.columns([2, 1, 1, 1])
    scope_label = cols[0].selectbox("Shift scope", ["Word", "Lyric line", "Whole song"], key="timing_scope")
    amount = cols[1].number_input("Nudge (ms)", 1, 10000, 10, key="nudge_ms")
    scope = {"Word": "word", "Lyric line": "line", "Whole song": "song"}[scope_label]
    if cols[2].button("← Earlier", key="nudge_back"):
        change(project, lambda p: E.shift_timing(p, word.id, -amount, scope, duration))
    if cols[3].button("Later →", key="nudge_fwd"):
        change(project, lambda p: E.shift_timing(p, word.id, amount, scope, duration))
    cols = st.columns(3)
    reviewed = project.reviewed.get(word.id, False)
    if cols[0].button("Mark unreviewed" if reviewed else "Mark reviewed", key="review_word"):
        change(project, lambda p: p.reviewed.__setitem__(word.id, not reviewed))
    if cols[1].button("Undo", key="undo_timing", disabled=not h.can_undo):
        h.undo(project); st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1; st.rerun()
    if cols[2].button("Redo", key="redo_timing", disabled=not h.can_redo):
        h.redo(project); st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1; st.rerun()


def _vocal_controls(project, root, duration):
    st.subheader("Section vocals")
    from . import stem_mix
    if project.vocal_mix.restoration_mode != stem_mix.MODE:
        st.caption('Separate lead and backing tracks give independent volume controls. Existing mixes keep their original blend until you switch.')
        try:
            stem_mix.checked(project, root)
            if st.button('Use separate lead and backing tracks', key=f'enable_tracks_{project.id}'):
                change(project, lambda p: stem_mix.enable(p, root))
        except P.ProjectError as exc:
            st.caption(str(exc))
    else:
        st.caption('Lead and backing song sliders are above the preview. These section controls change only lead vocals.')
    try:
        V.checked_references(project, root)
    except P.ProjectError as exc:
        st.info(str(exc))
        return None
    revision = f"{project.id}_{project.revision}"
    scopes = ["Selected lyric line", "Lyric lines", "Lyric section", "Time range", "Existing vocal region", "Whole song"]
    if st.session_state.get("pending_region"):
        st.session_state[f"vocal_scope_{project.id}"] = "Existing vocal region"
        st.session_state[f"vocal_region_{project.id}"] = st.session_state.pop("pending_region")
    scope = st.selectbox("Vocal selection", scopes, key=f"vocal_scope_{project.id}")
    selected = st.session_state.get("selected_word_id")
    selected_line = next((ln for ln, w in project.iter_words() if w.id == selected), None)
    region = None
    selection = {"value": project.vocal_mix.default_value, "transition_ms": project.vocal_mix.transition_ms}
    try:
        if scope == "Whole song":
            selection.update(song=True, label="Song default (outside regions)")
        elif scope == "Existing vocal region":
            regions = {r.id: r for r in project.vocal_mix.regions}
            if not regions:
                st.caption("Create a region from lyrics or a time range first.")
                return None
            key = f"vocal_region_{project.id}"
            if st.session_state.get(key) not in regions:
                st.session_state.pop(key, None)
            rid = st.selectbox("Vocal region", list(regions), key=key,
                    format_func=lambda i: f"{regions[i].start_ms / 1000:.2f}–{regions[i].end_ms / 1000:.2f}s · {regions[i].value:.0%}")
            region = regions[rid]
            from dataclasses import asdict
            selection.update(asdict(region), region_id=region.id, label="Selected vocal region")
        elif scope == "Time range":
            cols = st.columns(2)
            start = cols[0].number_input("Region start (ms)", 0, duration, 0, step=10)
            end = cols[1].number_input("Region end (ms)", 0, duration, min(duration, 1000), step=10)
            if end <= start:
                raise P.ProjectError("Region end must be after its start.")
            selection.update(start_ms=start, end_ms=end, label=f"Time range {start / 1000:.2f}–{end / 1000:.2f}s")
        else:
            line_ids, section_id = [], None
            if scope == "Selected lyric line":
                if selected_line is None:
                    st.caption("Select a word in the lyrics below to target its line.")
                    return None
                line_ids = [selected_line.id]
            elif scope == "Lyric lines":
                choices = {ln.id: f"{i + 1}. {ln.text}" for i, ln in enumerate(project.lines)}
                line_ids = st.multiselect("Lines to target", list(choices), format_func=choices.get,
                                          key=f"vocal_lines_{project.id}")
            else:
                sections = {s.id: f"{i + 1}. {s.name}" for i, s in enumerate(project.sections)}
                if not sections:
                    st.caption("Add headings such as # Verse or # Chorus in the lyrics box to create sections.")
                    return None
                section_id = st.selectbox("Lyric section", list(sections), format_func=sections.get)
            start, end, words = V.lyric_range(project, line_ids=line_ids, section_id=section_id)
            selection.update(start_ms=start, end_ms=end, source_line_ids=line_ids,
                              source_word_ids=words, source_section_id=section_id,
                              label=f"{scope}: {start / 1000:.2f}–{end / 1000:.2f}s")
        if not selection.get("song") and not region:
            exact = next((r for r in project.vocal_mix.regions if r.start_ms == selection["start_ms"] and r.end_ms == selection["end_ms"]), None)
            if exact:
                selection.update(region_id=exact.id, value=exact.value, transition_ms=exact.transition_ms)
            elif any(r.start_ms < selection["end_ms"] and r.end_ms > selection["start_ms"] for r in project.vocal_mix.regions):
                selection["label"] += " · mixed levels; the slider sets a new level"
                st.caption("This selection contains existing levels. Moving the slider or applying a value replaces them within the selected range.")
        transition = st.number_input("Vocal transition (ms)", 0, 5000, selection["transition_ms"],
                                      key=f"transition_{revision}_{scope}_{selection.get('region_id', '')}")
        selection["transition_ms"] = transition
        with st.form(f"vocal_number_{revision}_{scope}_{selection.get('region_id', '')}"):
            value = st.number_input("Vocal level (%)", 0, 100, round(selection["value"] * 100))
            if st.form_submit_button("Apply vocal level"):
                change(project, lambda p: vocal_action(p, {**selection, "value": value / 100}, duration))
        if region:
            cols = st.columns(2)
            if cols[0].button("Reset region to song default"):
                change(project, lambda p: setattr(p.vocal_mix, "regions", [r for r in p.vocal_mix.regions if r.id != region.id]))
            if cols[1].button("Refit to source lyrics", disabled=not (region.source_word_ids or region.source_line_ids or region.source_section_id)):
                change(project, lambda p: V.refit(p, region.id, duration))
        st.caption("Regions keep their times when lyrics move. Refit a region explicitly to follow corrected lyrics.")
        return selection
    except P.ProjectError as exc:
        st.info(str(exc))
        return None


def prepare_final_mix(project, root):
    try:
        with st.spinner("Preparing audio with the current lead and backing levels…"):
            snapshot = copy.deepcopy(project)
            path = V.render_mix(snapshot, root)
            V.render_mix_mp3(snapshot, root)
        st.session_state[f"final_mix_{project.id}"] = (V.mix_key(project), str(path))
        st.rerun()
    except (P.ProjectError, OSError, ValueError, RuntimeError) as exc:
        st.error(str(exc))


def _audio_tools(project, root):
    with st.expander("Audio references and final mix"):
        st.caption("Link the cache from this song's generation run. The clean and original references must share the same pre-mastering sample basis.")
        with st.form(f"audio_cache_{project.id}"):
            folder = st.text_input("Audio cache folder")
            if st.form_submit_button("Link cached tracks"):
                change(project, lambda p: media.attach_cached_audio(p, root, Path(folder)), save_root=root)
        refs = project.vocal_mix.references
        if V.configured(project):
            if project.vocal_mix.restoration_mode == 'separated_stems':
                st.caption("The mix uses the saved instrumental, lead and backing tracks. Timing edits change the lyric highlights; they do not require rebuilding audio.")
            else:
                changed = refs.get("timing_hash") != V.timing_hash(project)
                st.caption("Clean audio was built from earlier timing. Rebuild only when you want the removal mask to follow your corrections." if changed else "Clean audio matches the recorded timing basis.")
                if st.button("Rebuild clean audio from corrected timing"):
                    with st.spinner("Rebuilding from saved stems…"):
                        change(project, lambda p: V.rebuild_clean(p, root))
            if st.button("Prepare final mix for audition and download"):
                prepare_final_mix(project, root)
        else:
            st.caption("For an older project, prepare new calibrated references from its original audio and saved stems. This uses the chosen recipe and current timing; it does not run separation.")
            with st.form(f"prepare_legacy_{project.id}"):
                original = st.text_input("Original audio file")
                stem_dir = st.text_input("Saved stems folder", help="Contains lead.wav, backing.wav and instrumental.wav.")
                strategy = st.selectbox("Clean audio recipe", ["subtract", "replace"])
                gain = st.number_input("Removal gain", .0, 3., 1., step=.05)
                if st.form_submit_button("Prepare calibrated references"):
                    from .reference_prepare import prepare_legacy
                    with st.spinner("Preparing calibrated references from the saved audio…"):
                        change(project, lambda p: prepare_legacy(p, root, Path(original), Path(stem_dir),
                            {"mix_strategy": strategy, "vocal_gain": gain, "backing_boost": 0,
                             "pad_ms": 120, "crossfade_ms": 60, "merge_gap_ms": 500, "energy_threshold": 0}))


def _select_review_line(project, line, duration):
    from .phrase_project import phrase_window
    words = [w for w in line.words if not w.non_sung]
    if not words:
        return
    spans = [project.effective_timing(w.id) for w in words]
    spans = [t for t in spans if t and t.resolved and 0 <= t.start_ms < t.end_ms <= duration]
    phrase = phrase_window(project, line, duration)
    start = phrase[0] if phrase else min((t.start_ms for t in spans), default=None)
    st.session_state.selected_word_id = words[0].id
    st.session_state[f'lyric_navigation_{project.id}'] = dict(id=P.new_id('nav'), word_id=words[0].id, start_ms=start)
    if start is None:
        st.session_state.timing_message = ('ok', 'Line selected. No phrase or word timing is available to seek to yet.')


def _alignment_tools(project, root, audio_duration_ms):
    from .phrase_project import align_saved, apply_result, review_lines
    needs_review = review_lines(project)
    last_run = project.alignment.get('last_run', {})
    if last_run.get('online'):
        st.caption(last_run['online'])
    if project.alignment.get('failure'):
        st.warning('Separation is saved. Automatic timing could not finish; match timing here when the model is available.')
    if needs_review:
        st.warning(f'Check timing in {len(needs_review)} lyric lines.')
        with st.expander('Lines to review', key=f'review_lines_{project.id}', on_change='rerun'):
            for line, number, issues in needs_review:
                st.caption(f'{number}. {line.text}: {", ".join(issues)}')
                if st.button('Select this line', key=f'review_line_{line.id}'):
                    _select_review_line(project, line, audio_duration_ms)
                    st.rerun()
    else:
        st.caption('No unresolved timing checks. Listen through before export.')
    with st.expander('Match lyric timing', expanded=True):
        st.caption('Match phrases first, then words. Uses saved complete vocals and checks any online timing hints. Manual word corrections are kept.')
        scope = st.selectbox('Timing scope', ['Whole song', 'Selected lines', 'Lines needing review'], key='alignment_scope')
        choices = {ln.id: f'{i+1}. {ln.text}' for i,ln in enumerate(project.lines)}
        selected = next((ln.id for ln,w in project.iter_words() if w.id == st.session_state.get('selected_word_id')), None)
        line_ids = None
        if scope == 'Selected lines':
            line_ids = st.multiselect('Phrases to match', list(choices), default=[selected] if selected else [],
                                     format_func=choices.get, key=f'align_lines_{project.id}')
        elif scope == 'Lines needing review':
            line_ids = [line.id for line,_,_ in needs_review]
        bounds = None
        if line_ids and len(line_ids) == 1:
            line = project.find_line(line_ids[0])
            if st.checkbox('Set approximate phrase boundaries', key=f'anchor_{line.id}'):
                times = [project.effective_timing(w.id) for w in line.words]
                times = [t for t in times if t and t.resolved]
                duration = audio_duration_ms / 1000
                cols = st.columns(2)
                start = cols[0].number_input('Phrase start (seconds)', 0., duration,
                    min(duration, min((t.start_ms for t in times), default=0)/1000), step=.1, key=f'phrase_start_{line.id}')
                end = cols[1].number_input('Phrase end (seconds)', 0., duration,
                    min(duration, max((t.end_ms for t in times), default=5000)/1000), step=.1, key=f'phrase_end_{line.id}')
                bounds = {line.id:(start,end)}
                if st.button('Loop this phrase', key='audition_phrase', disabled=end <= start):
                    st.session_state[f'phrase_audition_{project.id}'] = dict(id=P.new_id('listen'), start_ms=round(start*1000), end_ms=round(end*1000))
                    st.rerun()
        only_missing = st.checkbox('Fill only untimed words', value=False, key='phrase_only_missing')
        if st.button('Match phrases and words', key='run_phrase_alignment', disabled=line_ids == []):
            revision = project.revision
            try:
                with st.spinner('Matching lyric timing against the saved vocals…'):
                    result = align_saved(copy.deepcopy(project), root, line_ids=line_ids, bounds=bounds)
                change(project, lambda p: apply_result(p, result, only_unresolved=only_missing),
                       command={'id':P.new_id('cmd'), 'base_revision':revision})
            except (RuntimeError, OSError, ValueError, P.ProjectError) as exc:
                st.error(f'Timing could not finish: {exc}')
    with st.expander("Apply alignment results"):
        st.caption("Apply a saved timing result to matching words. Manual corrections remain intact; original proposals remain available for comparison.")
        uploaded = st.file_uploader("Alignment timings.json", type=["json"], key="alignment_upload")
        only_missing = st.checkbox("Fill only untimed words", value=True)
        if st.button("Apply alignment", disabled=uploaded is None):
            from .timings import Timings
            try:
                incoming = Timings.from_dict(json.loads(uploaded.getvalue()))
            except (ValueError, KeyError, TypeError) as exc:
                st.error(f"Could not read alignment: {exc}")
            else:
                if incoming.alignment:
                    from .timings import AlignmentResult
                    if not incoming.alignment.get('input_words'):
                        st.error('Open this timing file as a project, or match against this project’s saved audio. It has no lyric IDs for safe application here.')
                    else:
                        result = AlignmentResult(incoming.lines, '', 0, 0, incoming.alignment)
                        change(project, lambda p: apply_result(p, result, only_unresolved=only_missing))
                else:
                    change(project, lambda p: lyrics.apply_alignment(p, incoming.lines, only_unresolved=only_missing))


def render(project, root, karaoke_path, *, lyrics_editor=None, export_controls=None,
           timing_review=False):
    h = history(project)
    sources = media.build_sources(project, root, karaoke_path)
    if timing_review:
        sources = [s for s in sources if s['id'] != 'karaoke']
    available = [s for s in sources if s["available"]]
    if not available:
        st.error("Relink the missing audio in the project sidebar before editing timing.")
        return
    duration = available[0]["duration_ms"]
    from . import presentation_ui, presentation
    left, right = st.columns([1.55, 1], gap="large")
    monitor = left.container(key="hb_monitor")
    inspector = right.container(key="hb_inspector")
    with inspector:
        st.subheader("Lyric controls")
        E.inspector_component()(data={"project_id": project.id}, key=f"hb_inspector_{project.id}")
        appearance_tab = lyrics_tab = timing_tab = vocals_tab = export_tab = None
        if timing_review:
            timing_tab, lyrics_tab, appearance_tab, export_tab = st.tabs(
                ["Timing", "Lyrics", "Appearance", "Build karaoke"],
                default="Timing", key=f"editor_tabs_{project.id}_review")
        else:
            appearance_tab, lyrics_tab, timing_tab, vocals_tab = st.tabs(
                ["Appearance", "Lyrics", "Timing", "Vocals"],
                key=f"editor_tabs_{project.id}_video")
        appearance_selection = None
        if appearance_tab:
            with appearance_tab:
                appearance_selection = presentation_ui.scope_controls(project)
                presentation_ui.display_controls(project)
    selection = st.session_state.get(f"vocal_template_{project.id}")
    payload = E.build_payload(project, sources, duration, st.session_state.get("selected_word_id"))
    try:
        preview = preview_payload(project, duration, media.register_media, root)
    except (P.ProjectError, ValueError, OSError) as exc:
        preview = None
        st.error(f"Lyric preview could not load: {exc}")
    payload.update(preview=preview, presentation_selection=appearance_selection,
                    lyric_navigation=st.session_state.get(f'lyric_navigation_{project.id}'),
                    phrase_audition=st.session_state.get(f'phrase_audition_{project.id}'),
                    can_undo=h.can_undo, can_redo=h.can_redo,
                    command_ack=st.session_state.get(f"command_ack_{project.id}"))
    payload["mix"] = None
    if not timing_review:
        try:
            payload["mix"] = V.preview_payload(project, root, media.register_media, selection)
            sources.append({**available[0], "id": "mix", "label": "Vocal mix (draft)",
                             "key": "vocal-mix", "src": "heartbeam:mix", "available": False,
                             "reason": "Preparing calibrated references…"})
        except (P.ProjectError, OSError, ValueError):
            pass
    final = st.session_state.get(f"final_mix_{project.id}")
    if not timing_review and final and final[0] == V.mix_key(project) and Path(final[1]).is_file():
        path = Path(final[1])
        sources.append({**available[0], "id": "final", "label": "Final mix (mastered)",
                         "key": str(path), "src": media.register_media(path, f"final/{project.id}")})
        if export_tab:
            with export_tab:
                st.download_button("Download final vocal mix.wav", path.read_bytes(), "vocal-mix.wav", mime="audio/wav")
                if path.with_suffix('.mp3').is_file():
                    st.download_button("Download current karaoke.mp3", path.with_suffix('.mp3').read_bytes(), "karaoke.mp3", mime="audio/mpeg")
    with monitor:
        st.subheader("Lyric timing preview" if timing_review else "Video preview")
        if timing_review:
            st.caption("Play the original and check the coloured word highlights against the singing. Select a word or line to adjust it, then open Build karaoke.")
        result = E.timeline_component()(data=payload, key=f"hb_timeline_{project.id}_{'review' if timing_review else 'video'}")
    selection_event = result.get("selection") if result else None
    if selection_event and selection_event.get("nonce") != st.session_state.get(f"selection_nonce_{project.id}"):
        st.session_state[f"selection_nonce_{project.id}"] = selection_event["nonce"]
        st.session_state.selected_word_id = selection_event.get("word_id")
        selection_changed = True
    else:
        selection_changed = False
    region_event = result.get("region_selection") if result else None
    if region_event and region_event.get("nonce") != st.session_state.get("region_nonce"):
        st.session_state.region_nonce = region_event["nonce"]
        st.session_state.pending_region = region_event["id"]
        st.rerun()
    command = result.get("command") if result else None
    if command and command.get("id") != st.session_state.get(f"command_ack_{project.id}"):
        kind, data = command.get("kind"), command.get("payload", {})
        if kind in ("undo", "redo"):
            try:
                h.travel_command(project, kind, command["id"], command.get("base_revision"))
            except CommandError as exc:
                st.session_state.timing_message = ("err", str(exc))
            st.session_state[f"command_ack_{project.id}"] = command["id"]
            st.session_state.lyrics_editor_version = st.session_state.get("lyrics_editor_version", 0) + 1
            st.rerun()
        elif kind == "timing":
            st.session_state.selected_word_id = data.get("word_id")
            change(project, lambda p: E.apply_timing_edit(p, data, duration), command=command)
        elif kind == "vocal":
            change(project, lambda p: vocal_action(p, data, duration), command=command)
        elif kind == 'track_level':
            change(project, lambda p: track_action(p, data), command=command)
        elif kind == "placement":
            change(project, lambda p: presentation.placement_command(p, data), command=command)
    message = st.session_state.pop("timing_message", None)
    message_slot = inspector.empty()
    if message:
        (message_slot.success if message[0] == "ok" else message_slot.error)(message[1])
    if preview and preview["warnings"]:
        with inspector.expander(f"Preview notes ({len(preview['warnings'])})"):
            for warning in preview["warnings"]:
                st.write(warning)
    if lyrics_tab:
        with lyrics_tab:
            if lyrics_editor:
                lyrics_editor(project, root)
    if timing_tab:
        with timing_tab:
            _timing_controls(project, duration)
            _alignment_tools(project, root, duration)
    if not timing_review:
        with vocals_tab:
            selection = _vocal_controls(project, root, duration)
            _audio_tools(project, root)
            with st.expander("Instrumental volume"):
                from .repair_ui import controls as level_controls
                level_controls(project, root, karaoke_path)
    template_changed = selection != st.session_state.get(f"vocal_template_{project.id}")
    st.session_state[f"vocal_template_{project.id}"] = selection
    if selection_changed or template_changed:
        st.rerun()
    if appearance_tab:
        with appearance_tab:
            presentation_ui.controls(project, root, appearance_selection)
    if export_tab:
        with export_tab:
            if export_controls:
                export_controls(project, root, karaoke_path)
