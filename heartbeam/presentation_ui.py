"""Placement/styling inspector. Shared History owns all durable changes."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import streamlit as st

from . import presentation as S, presentation_fonts as F, project as P


def _colour(label, value):
    """Streamlit's swatch lacks keyboard access; always offer a labelled input."""
    picked = st.color_picker(label, value)
    code = st.text_input(f"{label} code", value, max_chars=7,
                         help="Optional #RRGGBB value. A changed code takes priority over the swatch.")
    return code.strip() if code.strip().upper() != value.upper() else picked


def scope_controls(project):
    cols = st.columns([2, 1])
    scope = cols[0].selectbox("Style scope", ["Whole song", "Selected lyric line", "Lyric lines"],
                            key=f"style_scope_{project.id}")
    guides = cols[1].checkbox("Show safe area and handles", value=True, key=f"style_guides_{project.id}")
    selected = st.session_state.get("selected_word_id")
    line = next((line for line, word in project.iter_words() if word.id == selected), None)
    if scope == "Lyric lines":
        choices = {ln.id: f"{i + 1}. {ln.text}" for i, ln in enumerate(project.lines)}
        key = f"style_lines_{project.id}"
        if key in st.session_state:
            st.session_state[key] = [i for i in st.session_state[key] if i in choices]
        ids = st.multiselect("Lines to style", list(choices), format_func=choices.get, key=key)
    else:
        ids = [line.id] if line else []
    st.caption("Song defaults apply wherever a line has no exception." if scope == "Whole song" else
               "Changes apply only to the selected line(s). Reset returns them to the song style.")
    return {"scope": "song" if scope == "Whole song" else "lines", "line_ids": ids,
            "guides": guides, "label": scope}


def controls(project, root, selection):
    from .editor_ui import change
    ids = None if selection["scope"] == "song" else selection["line_ids"]
    if ids == []:
        st.info("Select a lyric word or choose lines to edit their appearance.")
        return
    line_id = ids[0] if ids else None
    spec = S.resolved_style(project, line_id)
    identity = f"{project.id}_{project.revision}_{line_id or 'song'}"
    with st.expander("Lyric appearance and placement", expanded=True):
        st.caption(f"Editing: {selection['label']}. Coordinates and sizes use the {project.presentation.design_width} × {project.presentation.design_height} design canvas.")
        if ids and len(ids) > 1:
            st.caption("Values show the first selected line. Applying changes sets the changed fields on all selected lines.")
        families = sorted({"Noto Sans", spec["font"]["family"]} | {f["family"] for f in project.presentation.fonts})
        with st.form(f"presentation_{identity}"):
            c = st.columns(2)
            family = c[0].selectbox("Lyric font", families, index=families.index(spec["font"]["family"]))
            size = c[1].number_input("Lyric font size", 8., 400., float(spec["font"]["size_px"]), step=1.)
            c = st.columns(2)
            bold = c[0].checkbox("Bold lyrics", spec["font"]["bold"])
            italic = c[1].checkbox("Italic lyrics", spec["font"]["italic"])
            c = st.columns(2)
            x = c[0].number_input("Lyric X", 0., float(project.presentation.design_width), float(spec["box"]["x"]), step=1.)
            y = c[1].number_input("Lyric Y", 0., float(project.presentation.design_height), float(spec["box"]["y"]), step=1.)
            c = st.columns(2)
            anchor = c[0].selectbox("Text box anchor", S.ANCHORS, index=S.ANCHORS.index(spec["box"]["anchor"]))
            alignment = c[1].selectbox("Text alignment", S.ALIGNMENTS, index=S.ALIGNMENTS.index(spec["box"]["alignment"]))
            c = st.columns(2)
            width = c[0].number_input("Text box width", 1., float(project.presentation.design_width), float(spec["box"]["width_px"]), step=10.)
            wrap = c[1].selectbox("Wrapping", ["Explicit line breaks", "Wrap to box width"], index=0 if spec["box"]["wrap"] == "explicit" else 1)
            c = st.columns(2)
            with c[0]:
                primary = _colour("Unsung colour", spec["colour"]["primary"])
            with c[1]:
                highlight = _colour("Sung colour", spec["colour"]["highlight"])
            c = st.columns(2)
            with c[0]:
                outline = _colour("Outline colour", spec["colour"]["outline"])
            outline_px = c[1].number_input("Outline thickness", 0., 40., float(spec["box"]["outline_px"]), step=.5)
            c = st.columns(2)
            with c[0]:
                shadow = _colour("Shadow colour", spec["colour"]["shadow"])
            shadow_px = c[1].number_input("Shadow distance", 0., 40., float(spec["box"]["shadow_px"]), step=.5)
            mode = st.selectbox("Highlighting", ["Whole word at onset", "Sweep during word"], index=0 if spec["highlight"]["mode"] == "word" else 1)
            st.caption("Sung words keep the sung colour. Zero thickness removes the outline or shadow.")
            if st.form_submit_button("Apply lyric appearance", type="primary"):
                entered = {"font": {"family": family, "size_px": size, "bold": bold, "italic": italic},
                    "box": {"x": x, "y": y, "anchor": anchor, "alignment": alignment, "width_px": width,
                            "wrap": "explicit" if wrap == "Explicit line breaks" else "auto", "outline_px": outline_px, "shadow_px": shadow_px},
                    "colour": {"primary": primary, "highlight": highlight, "outline": outline, "shadow": shadow},
                    "highlight": {"mode": "word" if mode == "Whole word at onset" else "sweep"}}
                # Store only edited fields. A colour exception must not freeze
                # its inherited font/position when song defaults change later.
                patch = {g: {k: v for k, v in values.items() if v != spec[g].get(k)} for g, values in entered.items()}
                patch = {g: values for g, values in patch.items() if values}
                change(project, lambda p: S.apply_style(p, patch, ids))
        if ids and st.button("Reset selected lines to song style"):
            change(project, lambda p: S.reset_lines(p, ids))
        if project.presentation.line_overrides and st.button("Reset all line exceptions"):
            change(project, lambda p: p.presentation.line_overrides.clear())
        with st.expander("Place using margins"):
            with st.form(f"margins_{identity}"):
                anchor = st.selectbox("Margin anchor", S.ANCHORS, index=S.ANCHORS.index(spec["box"]["anchor"]))
                c = st.columns(2)
                mh = c[0].number_input("Horizontal margin", 0., project.presentation.design_width / 2 - 1, float(spec["box"]["margin_h_px"]))
                mv = c[1].number_input("Vertical margin", 0., project.presentation.design_height / 2, float(spec["box"]["margin_v_px"]))
                if st.form_submit_button("Place inside margins"):
                    change(project, lambda p: S.apply_style(p, S.inside_margins(p.presentation.design_width, p.presentation.design_height, anchor, mh, mv), ids))
        selected = st.session_state.get("selected_word_id")
        line = next((line for line, word in project.iter_words() if word.id == selected), None)
        if line:
            with st.form(f"wrap_{identity}_{line.id}"):
                wrapped = st.text_area("Line breaks for the selected lyric", S.wrapped_text(project, line),
                        help="Insert Enter between existing words. This changes display wrapping without changing lyric timing or vocal regions.")
                if st.form_submit_button("Apply line breaks"):
                    change(project, lambda p: S.set_line_breaks(p, line.id, wrapped))
            word = project.find_word(selected)
            with st.form(f"display_word_{identity}_{word.id}"):
                spelling = st.text_input("Selected word on screen", S.display_text(word),
                                        help="Changes only the displayed spelling. The sung text and timing stay the same.")
                if st.form_submit_button("Apply display spelling"):
                    change(project, lambda p: setattr(p.find_word(word.id), "display_text", None if spelling == word.text else spelling))
    font_controls(project, root, identity)
    background_controls(project, root, identity)
    preset_controls(project, root, identity)


def display_controls(project):
    """Song-wide reading lead/hold; musical word timing remains untouched."""
    from .editor_ui import change
    value = S.display_settings(project)
    with st.expander("Lyric reading timing"):
        st.caption("Show a phrase early enough to read it. These controls change only when lines are visible; word highlighting and vocal levels keep their original timing.")
        with st.form(f"display_schedule_{project.id}_{project.revision}"):
            automatic = st.checkbox("Automatically schedule lyric lines", value["automatic"])
            c = st.columns(2)
            advance = c[0].number_input("Show before singing (ms)", 0, 10000, value["advance_ms"], step=100)
            hold = c[1].number_input("Keep after singing (ms)", 0, 10000, value["hold_ms"], step=100)
            upcoming = st.checkbox("Show the next lyric in a second slot", value["show_upcoming"])
            offset = st.number_input("Next-line vertical offset", -1080, 1080, value["upcoming_offset_y"], step=10,
                                     help="Negative places the upcoming line above its normal position; positive places it below.")
            if st.form_submit_button("Apply lyric reading timing"):
                change(project, lambda p: S.set_display_settings(p, {"automatic": automatic,
                    "advance_ms": advance, "hold_ms": hold, "show_upcoming": upcoming,
                    "upcoming_offset_y": offset}))


def _uploaded_files(uploads, action):
    """Use temporary input copies; committed assets receive safe hashed names."""
    with tempfile.TemporaryDirectory(prefix="heartbeam-style-") as folder:
        paths = []
        for i, upload in enumerate(uploads):
            path = Path(folder) / f"upload-{i}{Path(upload.name).suffix.lower()}"
            path.write_bytes(upload.getvalue()); paths.append(path)
        return action(paths)


def font_controls(project, root, identity):
    from .editor_ui import change
    with st.expander("Fonts in this project"):
        st.caption("Noto Sans includes regular, bold and italic faces. Added fonts are copied into the project and used by both preview and export.")
        uploads = st.file_uploader("Add font files", type=["ttf", "otf"], accept_multiple_files=True, key=f"font_upload_{project.id}")
        if st.button("Add uploaded fonts", disabled=not uploads):
            change(project, lambda p: _uploaded_files(uploads, lambda paths: F.import_fonts(p, root, paths)))
        if st.checkbox("Browse installed fonts", key=f"font_browse_{project.id}"):
            with st.spinner("Reading installed font families…"):
                catalog = F.installed_fonts()
            family = st.selectbox("Installed font family", list(catalog), index=None)
            if st.button("Copy this font family into project", disabled=family is None):
                change(project, lambda p: F.import_fonts(p, root, catalog[family]))
        for family in sorted({f["family"] for f in project.presentation.fonts}):
            faces = [f for f in project.presentation.fonts if f["family"] == family]
            st.caption(f"{family}: {len(faces)} saved face(s)")
        st.caption("To restore a missing or changed face, add the same font again or use Relink in the project sidebar. Unsupported variable fonts and font collections need a static TTF/OTF face.")


def background_controls(project, root, identity):
    from .editor_ui import change
    spec = S.resolved_style(project)
    with st.expander("Background and output size"):
        with st.form(f"background_{identity}"):
            colour = _colour("Canvas colour", spec["background"]["value"] if spec["background"]["kind"] == "solid" else "#101820")
            resolution = st.selectbox("Export resolution", ["1280x720", "1920x1080", "3840x2160"],
                 index=["1280x720", "1920x1080", "3840x2160"].index(spec["video"]["resolution"]) if spec["video"]["resolution"] in ["1280x720", "1920x1080", "3840x2160"] else 1)
            c = st.columns(2)
            colour_button = c[0].form_submit_button("Use solid background")
            size_button = c[1].form_submit_button("Set export resolution")
            if colour_button:
                change(project, lambda p: S.apply_style(p, {"background": {"kind": "solid", "value": colour, "asset_id": None}, "video": {"resolution": resolution}}))
            if size_button:
                change(project, lambda p: S.apply_style(p, {"video": {"resolution": resolution}}))
        upload = st.file_uploader("Background image or video", type=["png", "jpg", "jpeg", "webp", "mp4", "webm", "mov"], key=f"background_upload_{project.id}")
        if st.button("Use uploaded background", disabled=upload is None):
            def apply(p):
                asset = _uploaded_files([upload], lambda paths: F.copy_asset(p, root, paths[0], "background"))
                kind = "video" if Path(upload.name).suffix.lower() in (".mp4", ".webm", ".mov") else "image"
                S.apply_style(p, {"background": {"kind": kind, "asset_id": asset.id, "value": "#101820"}})
            change(project, apply)
        st.caption("Images and videos fill the canvas with a centered crop. Background videos loop silently using the song position; their audio is excluded from export.")


def preset_controls(project, root, identity):
    from .editor_ui import change
    with st.expander("Style presets and legacy import"):
        with st.form(f"save_style_{identity}"):
            name = st.text_input("Preset name", max_chars=80)
            if st.form_submit_button("Save named style preset"):
                def save(p):
                    data = S.preset_document(name, S.resolved_style(p))
                    p.presentation.presets[data["name"]] = data
                change(project, save)
        presets = project.presentation.presets
        if presets:
            chosen = st.selectbox("Saved style preset", list(presets), key=f"preset_{project.id}")
            if st.button("Apply saved style preset"):
                change(project, lambda p: S.apply_preset(p, presets[chosen]))
            st.download_button("Download style preset", json.dumps(presets[chosen], indent=2),
                               "heartbeam-style.json", mime="application/json")
        uploaded = st.file_uploader("Load a style preset", type=["json"], key=f"preset_upload_{project.id}")
        if st.button("Apply uploaded style preset", disabled=uploaded is None):
            change(project, lambda p: S.apply_preset(p, json.loads(uploaded.getvalue())))
        st.caption("Presets contain song appearance defaults only. Line exceptions stay in place; use Reset to remove them. Download a preset to reuse it in another song.")
        legacy = st.file_uploader("Import legacy style.toml", type=["toml"], key=f"style_toml_{project.id}")
        if st.button("Import TOML as song defaults", disabled=legacy is None):
            from .style import Style
            change(project, lambda p: _uploaded_files([legacy], lambda paths: S.import_legacy_style(p, root, Style.from_toml(paths[0]))))
