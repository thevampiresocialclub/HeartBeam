"""Online discovery beside the editable lyrics, without replacing text on search."""
from pathlib import Path
import streamlit as st
from .lyrics_lookup import lookup


def controls(key, defaults=None, cache_dir=None):
    defaults = defaults or {}
    with st.expander('Find lyrics online'):
        st.caption('Find the matching recording. Online times are checked against the vocals when you run timing.')
        with st.form(f'lookup_{key}'):
            title = st.text_input('Song title', value=defaults.get('title', ''), key=f'lookup_title_{key}')
            artist = st.text_input('Artist', value=defaults.get('artist', ''), key=f'lookup_artist_{key}')
            album = st.text_input('Album (optional)', value=defaults.get('album', ''), key=f'lookup_album_{key}')
            duration = st.number_input('Recording length (seconds)', min_value=0.,
                         value=float(defaults.get('duration') or 0), key=f'lookup_duration_{key}')
            clicked = st.form_submit_button('Find lyrics')
        if clicked:
            with st.spinner('Looking for lyrics…'):
                st.session_state[f'lookup_result_{key}'] = lookup(
                    dict(title=title, artist=artist, album=album, duration=duration),
                    cache_dir or Path.home()/'.heartbeam'/'lyrics-cache')
        result = st.session_state.get(f'lookup_result_{key}')
        if not result:
            return None
        st.caption(result['status'])
        candidates = result['candidates']
        if not candidates:
            return None
        selected = st.selectbox('Matching recording', range(len(candidates)),
            format_func=lambda i: f"{candidates[i]['artist']} — {candidates[i]['title']} · {candidates[i]['album']} · {candidates[i]['duration']:.1f}s",
            key=f'lookup_choice_{key}')
        candidate = candidates[selected]
        st.caption('Line timings available' if candidate['synced_lines'] else 'Lyrics available; timing will be matched locally')
        if duration and any(line['text'].strip() and line['start_s'] > duration + 2 for line in candidate['synced_lines']):
            st.warning('These lyric times extend beyond this recording. You can use the text; timing will need local matching.')
        st.text_area('Found lyrics', value=candidate['lyrics'], disabled=True, height=140,
                     key=f"lookup_preview_{key}_{candidate['id']}")
        if st.button('Use this result', key=f'lookup_use_{key}'):
            return candidate
    return None
