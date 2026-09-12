"""Online discovery beside the editable lyrics, without replacing text on search."""
from pathlib import Path
import streamlit as st
from .lyrics_lookup import lookup


def _adopt(key, candidate):
    st.session_state[f'lookup_adopt_{key}'] = candidate


@st.dialog('Find lyrics online', width='large')
def _results(key):
    if st.session_state.get(f'lookup_adopt_{key}'):
        st.rerun()
    request = st.session_state.pop(f'lookup_request_{key}', None)
    if request:
        with st.spinner('Looking for lyrics…'):
            st.session_state[f'lookup_result_{key}'] = lookup(request['metadata'], request['cache_dir'])
    result = st.session_state[f'lookup_result_{key}']
    st.write(result['status'])
    candidates = result['candidates']
    if not candidates:
        st.caption('Try another title or artist, or paste your lyrics into the text box.')
        return
    selected = st.selectbox('Matching recording', range(len(candidates)),
        format_func=lambda i: f"{candidates[i]['artist']} · {candidates[i]['title']} · {candidates[i]['album']} · {candidates[i]['duration']:.1f}s",
        key=f'lookup_choice_{key}')
    candidate = candidates[selected]
    st.caption('Line timings available' if candidate['synced_lines'] else 'Lyrics available; timing will be matched locally')
    duration = st.session_state.get(f'lookup_searched_duration_{key}', 0)
    if duration and any(line['text'].strip() and line['start_s'] > duration + 2 for line in candidate['synced_lines']):
        st.warning('These lyric times extend beyond this recording. You can use the text; timing will need local matching.')
    st.text_area('Found lyrics', value=candidate['lyrics'], disabled=True, height=260,
                 key=f"lookup_preview_{key}_{candidate['id']}")
    st.button('Use this result', key=f'lookup_use_{key}', type='primary',
              on_click=_adopt, args=(key, candidate))


def controls(key, defaults=None, cache_dir=None, *, inline=False):
    defaults = defaults or {}
    adopted = st.session_state.pop(f'lookup_adopt_{key}', None)
    with st.container() if inline else st.expander('Find lyrics online'):
        title_col, artist_col = st.columns(2)
        title = title_col.text_input('Song title', value=defaults.get('title') or '', key=f'lookup_title_{key}')
        artist = artist_col.text_input('Artist', value=defaults.get('artist') or '', key=f'lookup_artist_{key}')
        with st.container(horizontal=True):
            clicked = st.button('Find lyrics online', key=f'lookup_search_{key}')
            with st.popover('Options'):
                album = st.text_input('Album (optional)', value=defaults.get('album') or '', key=f'lookup_album_{key}')
                duration = st.number_input('Recording length (seconds)', min_value=0.,
                    value=float(defaults.get('duration') or 0), key=f'lookup_duration_{key}')
                st.caption('Choose the same recording or release. Timing is checked locally during preparation.')
            reopen = st.button('View results', key=f'lookup_reopen_{key}') if st.session_state.get(f'lookup_result_{key}') else False
        if clicked:
            st.session_state[f'lookup_request_{key}'] = {
                'metadata': dict(title=title, artist=artist, album=album, duration=duration),
                'cache_dir': cache_dir or Path.home()/'.heartbeam'/'lyrics-cache'}
            st.session_state[f'lookup_searched_duration_{key}'] = duration
            st.session_state.pop(f'lookup_choice_{key}', None)
        if clicked or reopen:
            _results(key)
    return adopted
