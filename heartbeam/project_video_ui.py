"""P06 export controls backed by immutable background jobs."""
from pathlib import Path
import streamlit as st

from . import desktop, export_jobs as J, project as P
from .export_names import default_video_filename, video_filename


@st.fragment(run_every=1.0)
def _running_status(job_id):
    """Poll only the status panel, preserving the editor and its audio clock."""
    job = J.get(job_id)
    if job is None or job.status not in ("queued", "running"):
        # The full page consumes completion once, restores download controls,
        # and removes this fragment so its timer stops.
        st.rerun()
    st.progress(job.progress, text=f"{job.message} Source revision {job.revision}.")
    st.caption("Progress updates automatically. You can keep editing while this renders.")
    if job.status_warning:
        st.warning(job.status_warning)
    if st.button("Cancel export", key=f"cancel_{job.id}"):
        J.cancel(job.id)
        st.rerun(scope="fragment")


def _show_video(record, project, *, selection=False):
    if not record:
        return
    revision, raw = record
    path = Path(raw)
    if not path.is_file():
        return
    if revision != project.revision:
        st.caption(f"This video is from revision {revision}. Render again to include newer edits.")
    st.video(str(path))
    name = path.name
    st.caption(f"Saved: {name}")
    actions = st.columns(2)
    actions[0].download_button(f"Download {name}", lambda p=path: p.read_bytes(), name,
        mime="video/mp4", key=f"dl_{'selection' if selection else 'video'}_{path.parent.name}",
        on_click="ignore")
    if actions[1].button("Show video in folder",
            key=f"reveal_{'selection' if selection else 'video'}_{path.parent.name}"):
        try:
            desktop.reveal_file(path)
        except desktop.DesktopError as exc:
            st.error(str(exc))
    with st.expander("File details"):
        st.caption(str(path))


def _active_status(project, root):
    key = f"export_job_{project.id}"
    job_id = st.session_state.get(key)
    if not job_id:
        return False
    job = J.get(job_id)
    if job is None:
        st.warning("This export belonged to an earlier app session. Its last saved status is available below.")
        st.session_state.pop(key, None)
        return False
    running = job.status in ("queued", "running")
    if running:
        _running_status(job.id)
    else:
        st.progress(job.progress, text=f"{job.message} Source revision {job.revision}.")
        if job.status_warning:
            st.warning(job.status_warning)
    if job.warnings:
        with st.expander(f'Export warnings ({len(job.warnings)})', expanded=True):
            for warning in job.warnings:
                st.warning(warning)
    if running:
        return True
    st.session_state.pop(key, None)
    if job.status == "complete":
        record = (job.revision, job.output_path)
        if job.kind == "full":
            st.session_state[f"last_video_{project.id}"] = record
        else:
            st.session_state[f"last_selection_video_{project.id}"] = record
        st.success(f"{'Passage' if job.kind == 'selection' else 'Full video'} rendered from revision {job.revision}.")
    elif job.status == "cancelled":
        st.info("Export cancelled. Your previous completed video was kept.")
    else:
        st.error(f"Video could not finish: {job.error or job.message}")
    return False


def render_controls(project, root, karaoke):
    st.divider()
    st.subheader("Karaoke video")
    st.caption("Exports freeze the current revision, lyric appearance, timing, fonts, background and vocal levels. Editing can continue while the video renders.")
    st.caption('Estimated highlights, untimed words and timing overlaps will show warnings and allow rendering. The video uses the timing available in the preview.')
    busy = _active_status(project, root)
    readonly = st.session_state.get("project_readonly", False)
    if not busy:
        name_key = f"chosen_export_name_{project.id}"
        filename = st.text_input("Video filename", value=st.session_state.get(name_key, default_video_filename(project, root)),
                                 key=f"export_filename_{project.id}",
                                 help="Saved inside this project's exports folder. The .mp4 extension is added if needed.")
        st.session_state[name_key] = filename
        st.caption("Saved in this project's Exports folder. Each render is kept.")
        with st.expander("Export folder details"):
            st.caption(str(Path(root) / P.EXPORTS_DIR))
        try:
            if st.button("Render video", type="primary", disabled=readonly):
                job = J.start(project, root, karaoke, output_name=filename)
                st.session_state[f"export_job_{project.id}"] = job.id
                st.rerun()
        except (P.ProjectError, OSError, ValueError, RuntimeError) as exc:
            st.error(f"Video could not start: {exc}")
        with st.expander("Render a short passage first"):
            st.caption("Use the final font, background, vocal mix and encoder on a difficult passage before committing to the full song. Passage renders are limited to 60 seconds.")
            with st.form(f"selection_export_{project.id}_{project.revision}"):
                c = st.columns(2)
                start_s = c[0].number_input("Passage start (seconds)", min_value=0.0, value=0.0, step=.5)
                end_s = c[1].number_input("Passage end (seconds)", min_value=.1, value=15.0, step=.5)
                submitted = st.form_submit_button("Render passage", disabled=readonly)
                if submitted:
                    try:
                        selection = (P.seconds_to_ms(start_s), P.seconds_to_ms(end_s))
                        passage_name = video_filename(filename)[:-4] + '_passage.mp4'
                        job = J.start(project, root, karaoke, selection, output_name=passage_name)
                        st.session_state[f"export_job_{project.id}"] = job.id
                        st.rerun()
                    except (P.ProjectError, OSError, ValueError, RuntimeError) as exc:
                        st.error(f"Passage could not start: {exc}")
    recovered = J.recover(root)
    interrupted = next((item for item in recovered if item["project_id"] == project.id and item["status"] == "interrupted"), None)
    if interrupted:
        st.caption("An earlier export was interrupted when the app closed. Completed videos were unaffected; start it again when ready.")
    _show_video(st.session_state.get(f"last_selection_video_{project.id}"), project, selection=True)
    _show_video(st.session_state.get(f"last_video_{project.id}"), project)
