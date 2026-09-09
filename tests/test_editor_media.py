"""P03.2: cache adoption, served audio, and bounded waveform payloads.

Frontend playback must also be exercised in a real browser; these do not
substitute for that check (see BUILD-STATUS.md).
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile as sf

from heartbeam import audio_cache as AC, editor as ED, editor_media as EM
from heartbeam import lyrics as L, project as P, waveform as WF


def song(tmp_path, words=3):
    root = tmp_path / "project"
    project = P.create_project(root, "Audition")
    L.apply_lyrics_edit(project, " ".join(f"word{i}" for i in range(words)))
    audio = tmp_path / "karaoke.wav"
    sf.write(audio, np.zeros(8000, dtype=np.float32), 8000, subtype="FLOAT")
    P.add_asset(project, root, audio, "karaoke_audio")
    return project, root, audio


def cache(tmp_path, frames=8000):
    folder = tmp_path / "source_cache"
    arrays = {role: np.ones((frames, 2), dtype=np.float32) * i / 10
              for i, role in enumerate(AC.ROLES)}
    AC.write_cache(folder, arrays, sample_rate=8000, source_sha256="source-hash", settings={"profile": "rock"})
    return folder


def test_cache_adoption_persists_and_save_as_is_portable(tmp_path):
    project, root, audio = song(tmp_path)
    ids = project.word_ids()
    assert EM.attach_cached_audio(project, root, cache(tmp_path)) == 5
    P.save_project(project, root)
    reopened = P.load_project(root)
    assert reopened.word_ids() == ids
    assert reopened.provenance.settings["audition_cache_source_sha256"] == "source-hash"
    assert all(not a.external for a in reopened.assets)
    moved = tmp_path / "copy"
    copied = P.save_project_as(reopened, moved, root)
    assert copied.id != project.id
    assert all(a.resolve(moved).exists() for a in copied.assets)
    assert copied.asset_by_role("lead_stem").sample_count == 8000


def test_cache_adoption_rejects_wrong_duration_before_mutating(tmp_path):
    project, root, audio = song(tmp_path)
    before = project.to_dict()
    with pytest.raises(P.ProjectError, match="duration"):
        EM.attach_cached_audio(project, root, cache(tmp_path, frames=16000))
    assert project.to_dict() == before


def test_cache_adoption_rejects_broken_basis_before_mutating(tmp_path):
    project, root, audio = song(tmp_path)
    folder = cache(tmp_path)
    sf.write(folder / "lead.wav", np.zeros(500, dtype=np.float32), 8000)
    before = project.to_dict()
    with pytest.raises(P.ProjectError, match="basis"):
        EM.attach_cached_audio(project, root, folder)
    assert project.to_dict() == before


def test_cache_adoption_does_not_overwrite_existing_roles(tmp_path):
    project, root, audio = song(tmp_path)
    folder = cache(tmp_path)
    EM.attach_cached_audio(project, root, folder)
    before = project.to_dict()
    with pytest.raises(P.ProjectError, match="already has"):
        EM.attach_cached_audio(project, root, folder)
    assert project.to_dict() == before


def test_peaks_include_the_last_sample_at_high_zoom():
    samples = np.zeros(64003, dtype=np.float32)
    samples[-1] = -1
    peaks = WF.compute_peaks(samples, 8000, 64000)
    assert peaks.mins[-1] == -127
    assert peaks.duration_ms == round(64003 / 8000 * 1000)


def test_cache_adoption_refuses_filename_collision(tmp_path):
    project, root, audio = song(tmp_path)
    folder = cache(tmp_path)
    destination = root / P.AUDIO_DIR / "lead.wav"
    destination.write_bytes(b"preserve this existing file")
    before = project.to_dict()
    with pytest.raises(P.ProjectError, match="nothing was overwritten"):
        EM.attach_cached_audio(project, root, folder)
    assert destination.read_bytes() == b"preserve this existing file"
    assert project.to_dict() == before


def test_multi_resolution_cache_decodes_once_then_not_at_all(tmp_path, monkeypatch):
    project, root, audio = song(tmp_path)
    read = Mock(wraps=sf.read)
    monkeypatch.setattr(sf, "read", read)
    first = EM.prepare_waveforms(audio, root / "cache", levels=(100, 500, 2000))
    assert read.call_count == 1
    assert [item["buckets"] for item in first["levels"]] == [100, 500, 2000]
    assert EM.prepare_waveforms(audio, root / "cache", levels=(100, 500, 2000)) == first
    assert read.call_count == 1


def test_replacing_audio_invalidates_peak_urls(tmp_path):
    project, root, audio = song(tmp_path)
    before = EM.prepare_waveforms(audio, root / "cache", levels=(20,))
    previous = audio.stat().st_mtime_ns
    sf.write(audio, np.ones(8000, dtype=np.float32), 8000, subtype="FLOAT")
    os.utime(audio, ns=(previous + 1_000_000, previous + 1_000_000))
    after = EM.prepare_waveforms(audio, root / "cache", levels=(20,))
    assert before["key"] != after["key"]
    assert before["levels"][0]["path"] != after["levels"][0]["path"]
    assert json.loads(after["levels"][0]["path"].read_text())["maxs"] == [127] * 20


def test_missing_tracks_are_explicit_and_audition_does_not_edit_project(tmp_path):
    project, root, audio = song(tmp_path)
    before = project.to_dict()
    sources = EM.build_sources(project, root, audio, register=lambda path, coord: "/media/" + path.name)
    assert [s["available"] for s in sources] == [True, False, False, False, False, False]
    assert all(s["reason"] for s in sources[1:])
    assert all("path" not in s for s in sources)
    assert project.to_dict() == before


def test_incompatible_track_is_disabled(tmp_path):
    project, root, audio = song(tmp_path)
    longer = tmp_path / "original.wav"
    sf.write(longer, np.zeros(16000, dtype=np.float32), 8000)
    P.add_asset(project, root, longer, "original_audio")
    sources = EM.build_sources(project, root, audio, register=lambda path, coord: "/media/" + path.name)
    assert sources[0]["available"]
    assert not sources[1]["available"]
    assert "duration" in sources[1]["reason"]


def test_260_word_payload_contains_no_inline_audio_or_peaks(tmp_path):
    project, root, audio = song(tmp_path, words=260)
    EM.attach_cached_audio(project, root, cache(tmp_path))
    sources = EM.build_sources(project, root, audio, register=lambda path, coord: "/media/" + path.name)
    payload = ED.build_payload(project, sources, 1000)
    serialized = json.dumps(payload)
    assert len(payload["words"]) == 260
    assert len(serialized.encode()) < 100_000
    assert "base64" not in serialized and "audio_src" not in payload
    assert all("mins" not in source for source in sources)
    assert all(source["src"].startswith("/media/") for source in sources if source['available'])


def test_registration_and_streamlit_range_endpoint(tmp_path, monkeypatch):
    # Exercise the actual pinned Streamlit adapter AND route, including a rerun
    # where the framework clears session references before registering again.
    from streamlit import runtime
    from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
    from streamlit.runtime.media_file_manager import MediaFileManager
    from streamlit.web.server.starlette.starlette_routes import create_media_routes
    import asyncio
    from starlette.requests import Request

    project, root, audio = song(tmp_path)
    storage = MemoryMediaFileStorage("/media")
    manager = MediaFileManager(storage)
    monkeypatch.setattr(runtime, "exists", lambda: True)
    monkeypatch.setattr(runtime, "get_instance", lambda: SimpleNamespace(media_file_mgr=manager))
    url = EM.register_media(audio, "timeline/karaoke")
    manager.clear_session_refs()
    assert EM.register_media(audio, "timeline/karaoke") == url
    manager.remove_orphaned_files()
    endpoint = create_media_routes(storage, None)[0].endpoint

    def request(url, method="GET", headers=()):
        scope = {"type": "http", "method": method, "path": url,
                 "path_params": {"file_id": url.rsplit("/", 1)[-1]},
                 "headers": list(headers), "server": ("localhost", 8501)}
        return asyncio.run(endpoint(Request(scope)))

    response = request(url, headers=[(b"range", b"bytes=0-127")])
    assert response.status_code == 206
    assert response.body == audio.read_bytes()[:128]
    assert response.headers["content-range"] == f"bytes 0-127/{audio.stat().st_size}"
    assert response.headers["content-type"].startswith("audio/")
    assert request(url, method="HEAD").status_code == 200
    peaks_file = tmp_path / "peaks.json"
    peaks_file.write_text('{"mins":[0],"maxs":[1]}')
    peak_url = EM.register_media(peaks_file, "timeline/karaoke/peaks/1")
    response = request(peak_url)
    assert response.headers["content-type"].startswith("application/json")
    assert json.loads(response.body)["maxs"] == [1]
