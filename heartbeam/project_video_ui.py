"""Synchronous project export, using P05's compiler. P06 owns job management."""
import copy
from pathlib import Path
import streamlit as st
from . import project as P, presentation as S, vocal_mix as V


def render_controls(project, root, karaoke):
    st.divider()
    st.subheader("Karaoke video")
    st.caption("Uses the saved project appearance, current lyric timing and vocal levels. Update the lyric preview controls above to change the video.")
    previous = st.session_state.get(f"last_video_{project.id}")
    path = Path(previous[1]) if previous else None
    if st.button("Render video", type="primary", disabled=st.session_state.get("project_readonly", False)):
        snapshot = copy.deepcopy(project)
        destination = Path(root) / P.EXPORTS_DIR / f"rev-{snapshot.revision}-{P.new_id('video')}"
        try:
            with st.spinner("Rendering the current project…"):
                audio = karaoke
                if snapshot.vocal_mix.references:
                    audio = V.render_mix(snapshot, root)
                elif snapshot.vocal_mix.regions or snapshot.vocal_mix.default_value:
                    raise P.ProjectError("Restore calibrated audio references before exporting the vocal mix.")
                # Keep a timing artifact alongside the exact ASS, presentation,
                # font files and frozen manifest for a reviewable export.
                from .project_preview import current_timings
                from .render import _audio_duration
                from .timings import to_json
                compiled = current_timings(snapshot, P.seconds_to_ms(_audio_duration(Path(audio))))
                path = S.render_project(snapshot, root, audio, destination)
                to_json(compiled, destination / "timings.json")
            st.session_state[f"last_video_{project.id}"] = (snapshot.revision, str(path))
            previous = (snapshot.revision, str(path))
            st.success("Video rendered from the current project.")
        except (P.ProjectError, OSError, ValueError, RuntimeError) as exc:
            st.error(f"Video could not finish: {exc}")
    if path and path.is_file():
        if previous[0] != project.revision:
            st.caption(f"This video is from revision {previous[0]}. Render again to include newer edits.")
        st.video(str(path))
        st.download_button("Download karaoke.mp4", path.read_bytes(), "karaoke.mp4", mime="video/mp4", key="dl_video")
