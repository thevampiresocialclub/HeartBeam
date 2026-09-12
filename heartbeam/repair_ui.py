"""Optional manual instrumental level controls; automatic repair is archived."""
from __future__ import annotations

import streamlit as st

from . import instrument_repair as R, project as P


def _add_repair(project, root, start_ms, end_ms, gain_db, fade_ms):
    if project.vocal_mix.restoration_mode != "separated_stems":
        raise P.ProjectError("Enable separate lead and backing tracks in Vocal mix before applying an instrumental repair.")
    item = R.create_level_repair(project, root, start_ms, end_ms,
                                 gain_db=gain_db, fade_ms=fade_ms)
    project.music_repair.repairs.append(item)
    return True, "Local level repair applied. Playback and export now use it."


def _disable(project, repair_id):
    item = next((value for value in project.music_repair.repairs if value.id == repair_id), None)
    if not item:
        raise P.ProjectError("That repair is no longer available.")
    item.status = "disabled"
    return True, "Repair disabled; the saved instrumental is unchanged."


def _audition(project, start_ms, end_ms):
    st.session_state[f"phrase_audition_{project.id}"] = {
        "id": P.new_id("listen"), "start_ms": start_ms, "end_ms": end_ms,
    }


def _remember_draft(draft_key, field, widget_key):
    # Ordinary widget keys are cleared when an earlier command reruns before
    # this part of the page mounts. A separate draft survives that cleanup.
    st.session_state[draft_key][field] = st.session_state[widget_key]


def controls(project, root, _karaoke):
    from . import editor_ui as UI
    instrumental = project.asset_by_role("instrumental_stem")
    if not instrumental or not instrumental.resolve(root).is_file():
        st.caption("A saved instrumental track is needed for local volume adjustments.")
        return
    st.caption("Lift a passage you choose. This changes the volume of existing music; it cannot restore a missing instrument.")
    chosen = (0, 1000, None)
    separate_tracks = project.vocal_mix.restoration_mode == "separated_stems"
    if not separate_tracks:
        st.info("To apply an instrumental repair, enable separate lead and backing tracks in Vocal mix. Existing adjustments can still be disabled below.")
    # A Streamlit form batches its inputs until submission, so any playback or
    # editor rerun discards the unfinished draft. Keep draft controls in session
    # state immediately; only Apply writes a repair to the project.
    seed = f"{project.id}_{chosen[0]}_{chosen[1]}_{chosen[2]}"
    draft_key = f"repair_draft_{seed}"
    draft = st.session_state.setdefault(draft_key, {
        "start": int(chosen[0]), "end": int(chosen[1]), "lift": 2.0, "fade": 120})
    def remember(field):
        return dict(key=f"repair_{field}_{seed}", on_change=_remember_draft,
                    args=(draft_key, field, f"repair_{field}_{seed}"))
    with st.container():
        st.markdown("**Apply a local level repair**")
        cols = st.columns(2)
        start_ms = cols[0].number_input("Start (ms)", min_value=0, value=draft["start"], step=50, **remember("start"))
        end_ms = cols[1].number_input("End (ms)", min_value=1, value=draft["end"], step=50, **remember("end"))
        cols = st.columns(2)
        gain_db = cols[0].slider("Lift (dB)", 0.0, 6.0, draft["lift"], .5, **remember("lift"))
        fade_ms = cols[1].number_input("Edge fade (ms)", 0, 1000, draft["fade"], 20, **remember("fade"))
        st.caption("Press Enter after typing a number to confirm it.")
        st.caption(f"Ready to apply: {start_ms / 1000:.2f}–{end_ms / 1000:.2f} sec · +{gain_db:g} dB · {fade_ms} ms fade")
        if st.button("Apply repair", key=f"apply_repair_{project.id}", disabled=not instrumental or not separate_tracks):
            UI.change(project, lambda p: _add_repair(
                p, root, int(start_ms), int(end_ms), float(gain_db), int(fade_ms)))

    if st.button("Play range", key=f"play_level_range_{project.id}"):
        _audition(project, int(start_ms), int(end_ms))
        st.rerun()

    applied = [item for item in project.music_repair.repairs if item.status == "applied"]
    if applied:
        st.markdown(f"**Applied repairs** · {len(applied)}")
        for item in applied:
            row = st.columns([2, 1])
            row[0].write(f"{item.start_ms / 1000:.2f}–{item.end_ms / 1000:.2f} sec · +{item.gain_db:g} dB")
            if row[1].button("Undo", key=f"disable_repair_{item.id}"):
                UI.change(project, lambda p, i=item.id: _disable(p, i))
