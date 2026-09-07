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


def _timing_controls(project, duration):
    h = history(project)
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
            st.caption("Imported timings were preserved. Correct overlapping or reversed words before export.")
            for (a, b), amount in list(conflicts.items())[:30]:
                st.write(f"{project.find_word(a).text} → {project.find_word(b).text}: {amount} ms overlap")
    if not word:
        st.caption("Select a lyric word to set its timing, shift its line, or mark it reviewed.")
        return
    timing = project.effective_timing(word.id)
    st.markdown(f"Selected word: **{word.text}**")
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


def _audio_tools(project, root):
    with st.expander("Audio references and final mix"):
        st.caption("Link the cache from this song's generation run. The clean and original references must share the same pre-mastering sample basis.")
        with st.form(f"audio_cache_{project.id}"):
            folder = st.text_input("Audio cache folder")
            if st.form_submit_button("Link cached tracks"):
                change(project, lambda p: media.attach_cached_audio(p, root, Path(folder)), save_root=root)
        refs = project.vocal_mix.references
        if refs:
            changed = refs.get("timing_hash") != V.timing_hash(project)
            st.caption("Clean audio was built from earlier timing. Rebuild only when you want the removal mask to follow your corrections." if changed else "Clean audio matches the recorded timing basis.")
            if st.button("Rebuild clean audio from corrected timing"):
                with st.spinner("Rebuilding from saved stems…"):
                    change(project, lambda p: V.rebuild_clean(p, root))
            if st.button("Prepare final mix for audition and download"):
                try:
                    with st.spinner("Rendering and mastering the current vocal mix…"):
                        path = V.render_mix(copy.deepcopy(project), root)
                    st.session_state[f"final_mix_{project.id}"] = (V.mix_key(project), str(path))
                except (P.ProjectError, OSError, ValueError) as exc:
                    st.error(str(exc))
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


def _alignment_tools(project, root):
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
                change(project, lambda p: lyrics.apply_alignment(p, incoming.lines, only_unresolved=only_missing))
        lead = project.asset_by_role("lead_stem")
        st.caption("Run alignment again only when needed. This loads the speech model; it does not run vocal separation.")
        if st.button("Run alignment on saved lead vocal", disabled=lead is None or not lead.resolve(root).is_file()):
            from .project_align import align_saved
            base_revision = project.revision
            try:
                with st.spinner("Aligning the saved lead vocal…"):
                    result = align_saved(copy.deepcopy(project), root)
                command = {"id": P.new_id("cmd"), "base_revision": base_revision}
                change(project, lambda p: lyrics.apply_alignment(p, result.lines, only_unresolved=only_missing), command=command)
            except (RuntimeError, OSError, ValueError) as exc:
                st.error(f"Alignment could not finish: {exc}")


def render(project, root, karaoke_path):
    st.divider()
    st.subheader("Lyric and vocal editor")
    h = history(project)
    _audio_tools(project, root)
    sources = media.build_sources(project, root, karaoke_path)
    available = [s for s in sources if s["available"]]
    if not available:
        st.error("Relink the missing audio in the project sidebar before editing timing.")
        return
    duration = available[0]["duration_ms"]
    from . import presentation_ui, presentation
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
                    can_undo=h.can_undo, can_redo=h.can_redo,
                    command_ack=st.session_state.get(f"command_ack_{project.id}"))
    try:
        payload["mix"] = V.preview_payload(project, root, media.register_media, selection)
        sources.append({**available[0], "id": "mix", "label": "Vocal mix (draft)",
                         "key": "vocal-mix", "src": "heartbeam:mix", "available": False,
                         "reason": "Preparing calibrated references…"})
    except (P.ProjectError, OSError, ValueError):
        payload["mix"] = None
    final = st.session_state.get(f"final_mix_{project.id}")
    if final and final[0] == V.mix_key(project) and Path(final[1]).is_file():
        path = Path(final[1])
        sources.append({**available[0], "id": "final", "label": "Final mix (mastered)",
                         "key": str(path), "src": media.register_media(path, f"final/{project.id}")})
        st.download_button("Download final vocal mix.wav", path.read_bytes(), "vocal-mix.wav", mime="audio/wav")
    result = E.timeline_component()(data=payload, key=f"hb_timeline_{project.id}")
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
        elif kind == "placement":
            change(project, lambda p: presentation.placement_command(p, data), command=command)
    message = st.session_state.pop("timing_message", None)
    message_slot = st.empty()
    if message:
        (message_slot.success if message[0] == "ok" else message_slot.error)(message[1])
    if preview and preview["warnings"]:
        for warning in preview["warnings"][:8]:
            st.warning(warning)
        if len(preview["warnings"]) > 8:
            with st.expander("All presentation warnings"):
                for warning in preview["warnings"]:
                    st.write(warning)
    appearance_tab, timing_tab, vocals_tab = st.tabs(["Appearance", "Timing", "Vocals"])
    with timing_tab:
        _timing_controls(project, duration)
        _alignment_tools(project, root)
    with vocals_tab:
        selection = _vocal_controls(project, root, duration)
    template_changed = selection != st.session_state.get(f"vocal_template_{project.id}")
    st.session_state[f"vocal_template_{project.id}"] = selection
    if selection_changed or template_changed:
        st.rerun()
    with appearance_tab:
        presentation_ui.controls(project, root, appearance_selection)
