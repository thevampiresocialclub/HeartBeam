"""Music Repair stage: review hints and apply reversible local corrections."""
from __future__ import annotations

import soundfile as sf
import streamlit as st

from . import audio_analysis as A, instrument_repair as R, project as P


def _source(project):
    return project.asset_by_role("original_audio"), project.asset_by_role("instrumental_stem")


def _scan(project, root):
    original, instrumental = _source(project)
    if not original or not instrumental:
        raise P.ProjectError("Thin-spot scanning needs the saved original and instrumental tracks.")
    original_path, music_path = original.resolve(root), instrumental.resolve(root)
    if not original_path.is_file() or not music_path.is_file():
        raise P.ProjectError("Relink the original and instrumental tracks before scanning.")
    if P.file_sha256(original_path) != original.sha256 or P.file_sha256(music_path) != instrumental.sha256:
        raise P.ProjectError("An audio track changed. Relink it before scanning.")
    source, sr = sf.read(str(original_path), dtype="float32", always_2d=True)
    music, music_sr = sf.read(str(music_path), dtype="float32", always_2d=True)
    if sr != music_sr or source.shape != music.shape:
        raise P.ProjectError("The original and instrumental tracks must share one sample basis.")
    suggestions = A.find_thin_spots(source, music, sr)
    for item in suggestions:
        item.source_revision = project.revision
    return suggestions, instrumental


def _replace_scan(project, suggestions, instrumental):
    project.music_repair.analysis_version = A.ANALYSIS_VERSION
    project.music_repair.source_asset_id = instrumental.id
    project.music_repair.source_sha256 = instrumental.sha256
    project.music_repair.suggestions = suggestions
    return True, f"Found {len(suggestions)} passages to check. Nothing was changed automatically."


def _set_status(project, suggestion_id, status):
    item = next((value for value in project.music_repair.suggestions if value.id == suggestion_id), None)
    if not item:
        raise P.ProjectError("That suggestion is no longer available.")
    item.status = status
    return True, "Suggestion updated."


def _add_repair(project, root, start_ms, end_ms, gain_db, fade_ms, suggestion_id=None):
    item = R.create_level_repair(project, root, start_ms, end_ms,
                                 gain_db=gain_db, fade_ms=fade_ms)
    project.music_repair.repairs.append(item)
    if suggestion_id:
        _set_status(project, suggestion_id, "reviewed")
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


def controls(project, root, _karaoke):
    from . import editor_ui as UI
    st.subheader("Music repair")
    st.caption("Check the accompaniment after video editing. Suggestions are listening hints; no repair is applied until you choose it.")
    original, instrumental = _source(project)
    available = bool(original and instrumental and original.resolve(root).is_file()
                     and instrumental.resolve(root).is_file())
    if st.button("Find thin spots", type="primary", disabled=not available,
                 key=f"scan_music_{project.id}"):
        try:
            with st.spinner("Comparing the instrumental with the original recording…"):
                suggestions, source = _scan(project, root)
            UI.change(project, lambda p: _replace_scan(p, suggestions, source))
        except (P.ProjectError, OSError, ValueError) as exc:
            st.error(str(exc))
    if not available:
        st.warning("This project has no matching original and instrumental tracks to scan. You can skip this step and export.")
    st.caption("A level repair can lift music that survived quietly. It cannot recreate an instrument that is completely missing; recorded-component recovery is the next experiment in the roadmap.")

    suggestions = project.music_repair.suggestions
    scan_current = bool(instrumental and project.music_repair.source_asset_id == instrumental.id
                        and project.music_repair.source_sha256 == instrumental.sha256)
    if suggestions and not scan_current:
        st.warning("These suggestions belong to an older instrumental track. Scan again before using them.")
    if suggestions:
        unreviewed = sum(item.status == "unreviewed" for item in suggestions)
        st.markdown(f"**Suggested passages** · {unreviewed} left to check")
        for item in suggestions:
            with st.expander(f"{item.start_ms / 1000:.2f}–{item.end_ms / 1000:.2f} sec · {item.status}"):
                st.write(item.reason)
                st.caption(f"Instrumental dip: {item.metrics.get('instrumental_local_dip_db', 0):.1f} dB · original dip: {item.metrics.get('original_local_dip_db', 0):.1f} dB")
                row = st.columns(3)
                if row[0].button("Play range", key=f"play_hint_{item.id}"):
                    _audition(project, item.start_ms, item.end_ms); st.rerun()
                if row[1].button("Skip", key=f"skip_hint_{item.id}", disabled=item.status == "skipped"):
                    UI.change(project, lambda p, i=item.id: _set_status(p, i, "skipped"))
                if row[2].button("Use range", key=f"use_hint_{item.id}", disabled=not scan_current):
                    st.session_state[f"repair_range_{project.id}"] = (item.start_ms, item.end_ms, item.id)
                    st.rerun()
    else:
        st.info("Run the scan or enter a passage yourself. You can also continue without repairs.")

    chosen = st.session_state.get(f"repair_range_{project.id}", (0, 1000, None))
    with st.form(f"manual_repair_{project.id}_{project.revision}"):
        st.markdown("**Apply a local level repair**")
        cols = st.columns(2)
        start_ms = cols[0].number_input("Start (ms)", min_value=0, value=int(chosen[0]), step=50)
        end_ms = cols[1].number_input("End (ms)", min_value=1, value=int(chosen[1]), step=50)
        cols = st.columns(2)
        gain_db = cols[0].slider("Lift (dB)", 0.0, 6.0, 2.0, .5)
        fade_ms = cols[1].number_input("Edge fade (ms)", 0, 1000, 120, 20)
        if st.form_submit_button("Apply repair", disabled=not instrumental):
            UI.change(project, lambda p: _add_repair(
                p, root, int(start_ms), int(end_ms), float(gain_db), int(fade_ms), chosen[2]))

    applied = [item for item in project.music_repair.repairs if item.status == "applied"]
    if applied:
        st.markdown(f"**Applied repairs** · {len(applied)}")
        for item in applied:
            row = st.columns([2, 1])
            row[0].write(f"{item.start_ms / 1000:.2f}–{item.end_ms / 1000:.2f} sec · +{item.gain_db:g} dB")
            if row[1].button("Undo", key=f"disable_repair_{item.id}"):
                UI.change(project, lambda p, i=item.id: _disable(p, i))

    if any(item.status == "unreviewed" for item in suggestions):
        st.warning("Some suggestions are still unreviewed. You may continue; export will not apply them.")
    if st.button("Continue to export", key=f"repair_to_export_{project.id}", type="primary"):
        st.session_state.workflow_step = "export"
        st.rerun()
