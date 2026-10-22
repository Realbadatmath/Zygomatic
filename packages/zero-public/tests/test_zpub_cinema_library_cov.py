# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_zero.zpub_cinema.library: thumbnails, the JSON index, the scan job.

Everything here is offline: ffmpeg/ffprobe are reached only through the module's
own ``_run`` seam, every path the module derives is redirected into tmp_path, and
the scan job runs synchronously through a fake ``threading.Thread``.
"""

import json
import os
import types

import pytest

from zyg_zero.zpub_cinema import library, prefs


_MB = 1024 * 1024


def _mkfile(path: str, size: int = 0, text: str = '') -> str:
    """Create ``path`` (sparse when ``size`` is large) and return it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        if text:
            f.write(text.encode('utf-8'))
        if size:
            f.truncate(size)
    return path


def _video(root: str, *parts: str, size: int = 25 * _MB) -> str:
    return _mkfile(os.path.join(root, *parts), size=size)


class _SyncThread:
    """``threading.Thread`` stand-in that runs the target on ``start()``."""

    made: list['_SyncThread'] = []

    def __init__(self, target=None, daemon=None, name=None):
        self.target, self.daemon, self.name = target, daemon, name
        _SyncThread.made.append(self)

    def start(self):
        self.target()


@pytest.fixture(autouse=True)
def cine(tmp_path, monkeypatch):
    """Redirect every derived path into tmp_path and reset module state."""
    thumbs = tmp_path / 'thumbs'
    media = tmp_path / 'media'
    thumbs.mkdir()
    media.mkdir()
    monkeypatch.setattr(library, 'LIBRARY_PATH', str(tmp_path / 'cinema_library.json'))
    monkeypatch.setattr(library, 'THUMB_DIR', str(thumbs))
    # prefs_for() reads the prefs file; point it at an absent path so the
    # module defaults are used and nothing under the repo is touched.
    monkeypatch.setattr(prefs, 'PREFS_PATH', str(tmp_path / 'cinema_prefs.json'))
    monkeypatch.setitem(prefs._prefs_cache, 'mtime', -2.0)
    monkeypatch.setitem(prefs._prefs_cache, 'data', None)
    _SyncThread.made.clear()
    with library._scan_lock:
        library._scans.clear()
    yield types.SimpleNamespace(root=str(tmp_path), thumbs=str(thumbs), media=str(media))
    with library._scan_lock:
        library._scans.clear()


def _probe_info(duration=3600.0, vcodec='h264', acodec='aac', chapters=()):
    return {
        'duration': duration,
        'video': {'index': 0, 'codec': vcodec, 'profile': 'main', 'width': 1920, 'height': 1080, 'pix_fmt': 'yuv420p'},
        'audio': [{'index': 1, 'order': 0, 'codec': acodec, 'channels': 6, 'lang': 'en', 'title': '', 'default': True}],
        'subs': [{'index': 2, 'order': 0, 'codec': 'subrip', 'lang': 'en', 'title': '', 'default': True}],
        'chapters': list(chapters),
        'bitrate': 8_000_000,
    }


# ── Thumbnail helpers ─────────────────────────────────────────────────────────
def test_thumb_path_lands_in_the_patched_thumb_dir(cine):
    assert library.thumb_path('deadbeef') == os.path.join(cine.thumbs, 'deadbeef.jpg')


@pytest.mark.parametrize(
    ('raw', 'want'),
    [
        ('/plain/movie.mkv', '/plain/movie.mkv'),
        ('/a:b/movie.mkv', '/a\\:b/movie.mkv'),
        ("/it's/movie.mkv", "/it\\'s/movie.mkv"),
        ('C\\x\\movie.mkv', 'C\\\\x\\\\movie.mkv'),
    ],
)
def test_lavfi_escape_quotes_the_filtergraph_specials(raw, want):
    assert library._lavfi_escape(raw) == want


def test_folder_artwork_is_none_when_the_folder_cannot_be_listed(cine):
    assert library._folder_artwork(os.path.join(cine.media, 'gone', 'movie.mkv')) is None


def test_folder_artwork_skips_text_dirs_adverts_and_unknown_names(cine):
    folder = os.path.join(cine.media, 'Some Movie 2019')
    _mkfile(os.path.join(folder, 'notes.txt'), text='hi')
    os.makedirs(os.path.join(folder, 'cover.jpg'))  # a DIRECTORY named like artwork
    _mkfile(os.path.join(folder, 'random.png'), text='x')
    _mkfile(os.path.join(folder, 'yts.jpg'), text='x')
    assert library._folder_artwork(os.path.join(folder, 'movie.mkv')) is None


def test_folder_artwork_returns_the_plex_poster(cine):
    folder = os.path.join(cine.media, 'Named 2019')
    art = _mkfile(os.path.join(folder, 'poster.jpg'), text='jpeg')
    assert library._folder_artwork(os.path.join(folder, 'movie.mkv')) == art


def test_frame_score_is_minus_one_for_an_unreadable_file(cine):
    assert library._frame_score(os.path.join(cine.root, 'nope.jpg')) == (-1.0, 0)


@pytest.mark.parametrize(
    ('rc', 'out', 'want'),
    [
        (1, '', (-1.0, 10)),
        (0, '42.5\n', (42.5, 10)),
        (0, '', (0.0, 10)),
        (0, 'oops\n', (-1.0, 10)),
    ],
)
def test_frame_score_reads_the_signalstats_yavg(cine, monkeypatch, rc, out, want):
    cand = _mkfile(os.path.join(cine.root, 'cand.jpg'), text='0123456789')
    seen = []

    def fake_run(cmd, timeout=120):
        seen.append((cmd, timeout))
        return rc, out, ''

    monkeypatch.setattr(library, '_run', fake_run)
    assert library._frame_score(cand) == want
    cmd, timeout = seen[0]
    assert cmd[0] == library.FFPROBE and timeout == 30
    assert f'movie={cand},signalstats' in cmd
    assert 'frame_tags=lavfi.signalstats.YAVG' in cmd


# ── build_thumb ───────────────────────────────────────────────────────────────
def test_build_thumb_returns_the_cached_jpg_without_running_ffmpeg(cine, monkeypatch):
    dest = _mkfile(library.thumb_path('abc'), size=4096)

    def boom(cmd, timeout=120):  # pragma: no cover - must not be reached
        raise AssertionError('ffmpeg must not run for a cached thumb')

    monkeypatch.setattr(library, '_run', boom)
    assert library.build_thumb({'id': 'abc'}) == dest


@pytest.mark.parametrize('item', [{'id': 'x'}, {'id': 'x', 'path': '/nonexistent/movie.mkv'}])
def test_build_thumb_is_none_without_a_readable_source(cine, item):
    assert library.build_thumb(item) is None


def test_build_thumb_prefers_folder_artwork(cine, monkeypatch):
    folder = os.path.join(cine.media, 'Art 2019')
    art = _mkfile(os.path.join(folder, 'folder.jpg'), text='jpeg')
    src = _video(folder, 'Art.2019.1080p.mkv')
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append(cmd)
        _mkfile(cmd[-1], size=2048)
        return 0, '', ''

    monkeypatch.setattr(library, '_run', fake_run)
    dest = library.build_thumb({'id': 'art', 'path': src})
    assert dest == library.thumb_path('art')
    assert len(calls) == 1
    assert calls[0][0] == library.FFMPEG
    assert art in calls[0] and 'scale=480:-2' in calls[0] and dest in calls[0]


def test_build_thumb_falls_back_to_frames_and_keeps_the_best(cine, monkeypatch):
    folder = os.path.join(cine.media, 'Frames 2019')
    _mkfile(os.path.join(folder, 'poster.jpg'), text='jpeg')
    src = _video(folder, 'Frames.2019.1080p.mkv')
    grabs = []

    def fake_run(cmd, timeout=120):
        if '-ss' not in cmd:
            return 1, '', 'artwork scale failed'  # folder artwork path gives up
        grabs.append(cmd)
        if len(grabs) == 1:
            return 1, '', 'grab failed'  # the `continue` branch
        _mkfile(cmd[-1], size=2048)
        return 0, '', ''

    scores = iter([(10.0, 1000), (60.0, 20000)])
    monkeypatch.setattr(library, '_run', fake_run)
    monkeypatch.setattr(library, '_frame_score', lambda p: next(scores))
    dest = library.build_thumb({'id': 'fr', 'path': src, 'duration': 3600})
    assert dest == library.thumb_path('fr')
    assert os.path.isfile(dest)
    assert not os.path.exists(dest + '.cand.jpg')
    # 7 fractions are available; a clearly good frame stops the search at 3.
    assert len(grabs) == 3
    offsets = [cmd[cmd.index('-ss') + 1] for cmd in grabs]
    assert offsets == [f'{3600 * f:.2f}' for f in library._THUMB_FRACTIONS[:3]]


def test_build_thumb_on_a_short_clip_samples_two_offsets(cine, monkeypatch):
    src = _video(cine.media, 'short.mp4')
    grabs = []

    def fake_run(cmd, timeout=120):
        grabs.append(cmd)
        _mkfile(cmd[-1], size=2048)
        return 0, '', ''

    scores = iter([(100.0, 1000), (50.0, 500)])
    monkeypatch.setattr(library, '_run', fake_run)
    monkeypatch.setattr(library, '_frame_score', lambda p: next(scores))
    assert library.build_thumb({'id': 'sh', 'path': src, 'duration': 30}) == library.thumb_path('sh')
    assert [cmd[cmd.index('-ss') + 1] for cmd in grabs] == ['15.00', '2.00']


def test_build_thumb_gives_up_when_the_candidate_cannot_be_promoted(cine, monkeypatch):
    src = _video(cine.media, 'replace.mp4')

    def fake_run(cmd, timeout=120):
        _mkfile(cmd[-1], size=2048)
        return 0, '', ''

    def no_replace(a, b):
        raise OSError('read-only cache')

    monkeypatch.setattr(library, '_run', fake_run)
    monkeypatch.setattr(library, '_frame_score', lambda p: (80.0, 15000))
    monkeypatch.setattr(library.os, 'replace', no_replace)
    assert library.build_thumb({'id': 'rp', 'path': src, 'duration': 3600}) is None


def test_build_thumb_survives_an_undeletable_candidate(cine, monkeypatch, caplog):
    import logging

    src = _video(cine.media, 'dirty.mp4')

    def fake_run(cmd, timeout=120):
        _mkfile(cmd[-1], size=2048)
        return 1, '', 'every grab failed'

    def no_remove(path):
        raise OSError('busy')

    monkeypatch.setattr(library, '_run', fake_run)
    monkeypatch.setattr(library.os, 'remove', no_remove)
    with caplog.at_level(logging.DEBUG, logger='zyg_zero.zpub_cinema'):
        assert library.build_thumb({'id': 'dt', 'path': src, 'duration': 3600}) is None
    assert 'suppressed OSError' in caplog.text


# ── The JSON index ────────────────────────────────────────────────────────────
def test_load_library_is_blank_when_the_file_is_missing(cine):
    assert library.load_library() == {
        'version': 1,
        'updated_at': None,
        'roots': [],
        'items': {},
        'series_names': {},
    }


@pytest.mark.parametrize('payload', ['{not json', '[]', '{"version": 1}'])
def test_load_library_is_blank_for_unusable_content(cine, payload):
    _mkfile(library.LIBRARY_PATH, text=payload)
    assert library.load_library() == library._blank_library()


def test_load_library_backfills_the_optional_keys(cine):
    _mkfile(library.LIBRARY_PATH, text=json.dumps({'items': {'a': {'id': 'a'}}}))
    lib = library.load_library()
    assert lib['items'] == {'a': {'id': 'a'}}
    assert lib['roots'] == [] and lib['series_names'] == {} and lib['version'] == 1


def test_save_library_round_trips_and_stamps_updated_at(cine):
    lib = library._blank_library()
    lib['items'] = {'a': {'id': 'a', 'title': 'A'}}
    library.save_library(lib)
    assert not os.path.exists(library.LIBRARY_PATH + '.tmp')
    back = library.load_library()
    assert back['items'] == lib['items']
    assert isinstance(back['updated_at'], str) and back['updated_at']


def test_save_library_reports_an_unwritable_path(cine, monkeypatch, caplog):
    import logging

    monkeypatch.setattr(library, 'LIBRARY_PATH', os.path.join(cine.root, 'no', 'such', 'dir', 'lib.json'))
    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        library.save_library(library._blank_library())
    assert '[Cinema] library save failed' in caplog.text


def test_item_id_for_is_a_stable_short_sha1(cine):
    a = os.path.join(cine.media, 'a.mkv')
    assert library.item_id_for(a) == library.item_id_for(a)
    assert len(library.item_id_for(a)) == 16
    assert all(c in '0123456789abcdef' for c in library.item_id_for(a))
    assert library.item_id_for(a) != library.item_id_for(os.path.join(cine.media, 'b.mkv'))


# ── _walk_videos ──────────────────────────────────────────────────────────────
def test_walk_videos_skips_junk_dirs_small_files_and_samples(cine):
    keep = _video(cine.media, 'Good 2019', 'Good.2019.1080p.mkv')
    _video(cine.media, 'samples', 'inside-a-skip-dir.mkv')
    _video(cine.media, '.hidden', 'hidden.mkv')
    _mkfile(os.path.join(cine.media, 'notes.txt'), text='x')
    _video(cine.media, 'tiny.mkv', size=1024)
    _video(cine.media, 'Some-sample.mkv', size=30 * _MB)
    os.symlink(os.path.join(cine.media, 'absent.mkv'), os.path.join(cine.media, 'dangling.mkv'))
    assert list(library._walk_videos(cine.media)) == [(keep, 25 * _MB)]


def test_walk_videos_stops_at_max_files(cine):
    for i in range(3):
        _video(cine.media, f'm{i}.mkv')
    assert len(list(library._walk_videos(cine.media, max_files=1))) == 1


# ── build_item ────────────────────────────────────────────────────────────────
def test_build_item_is_none_for_a_missing_file(cine):
    assert library.build_item(os.path.join(cine.media, 'gone.mkv'), 1) is None


def test_build_item_is_none_when_the_probe_finds_no_video(cine, monkeypatch):
    src = _video(cine.media, 'audio-only.mkv')
    monkeypatch.setattr(library, 'probe', lambda p: {})
    assert library.build_item(src, 25 * _MB) is None
    monkeypatch.setattr(library, 'probe', lambda p: {'duration': 1.0, 'video': None})
    assert library.build_item(src, 25 * _MB) is None


def test_build_item_describes_a_movie_with_its_sidecar_subs(cine, monkeypatch):
    folder = os.path.join(cine.media, 'Gods of Egypt 2016 1080p BluRay x264')
    src = _video(folder, 'Gods.of.Egypt.2016.1080p.BluRay.x264.mkv')
    _mkfile(os.path.join(folder, 'Gods.of.Egypt.2016.1080p.BluRay.x264.srt'), text='1\n')
    monkeypatch.setattr(library, 'probe', lambda p: _probe_info())
    item = library.build_item(src, 25 * _MB)
    assert item['id'] == library.item_id_for(src)
    assert item['kind'] == 'movie'
    assert (item['title'], item['year']) == ('Gods of Egypt', 2016)
    assert (item['width'], item['height'], item['vcodec'], item['acodec']) == (1920, 1080, 'h264', 'aac')
    assert item['size'] == 25 * _MB and item['duration'] == 3600.0
    assert item['folder'] == folder and item['filename'] == os.path.basename(src)
    assert item['direct'] is False and item['transcode_reason'] == 'container'
    assert {s['kind'] for s in item['subs']} == {'external', 'embedded'}
    assert item['default_sub'] and item['default_audio'] == 0
    assert isinstance(item['added_at'], str)


def test_build_item_titles_a_short_stem_from_its_folder(cine, monkeypatch):
    src = _video(cine.media, 'The Big Film 2011 1080p', 'ab.mkv')
    monkeypatch.setattr(library, 'probe', lambda p: _probe_info())
    item = library.build_item(src, 25 * _MB)
    assert (item['title'], item['year']) == ('The Big Film', 2011)


def test_build_item_marks_an_episode_and_keeps_added_at(cine, monkeypatch):
    src = _video(cine.media, 'Some Show', 'Season 2', 'Some.Show.S02E05.The.Title.1080p.mkv')
    monkeypatch.setattr(library, 'probe', lambda p: _probe_info(vcodec='hevc', acodec='dts'))
    item = library.build_item(src, 25 * _MB, {'added_at': 'earlier'})
    assert item['kind'] == 'episode'
    assert (item['series'], item['season'], item['episode']) == ('Some Show', 2, 5)
    assert item['title'] == 'Some Show' and item['episode_title'] == 'The Title'
    assert item['added_at'] == 'earlier'
    assert item['transcode_reason'] == 'video+audio'


def test_build_item_reuses_an_unchanged_entry_and_backfills_chapters(cine, monkeypatch):
    folder = os.path.join(cine.media, 'Reuse 2019')
    src = _video(folder, 'Reuse.2019.1080p.mkv')
    _mkfile(os.path.join(folder, 'Subs', 'English.eng.srt'), text='1\n')
    mtime = int(os.stat(src).st_mtime)
    existing = {
        'id': library.item_id_for(src),
        'path': src,
        'size': 25 * _MB,
        'mtime': mtime,
        'duration': 3600.0,
        'audio': [{'order': 0, 'codec': 'aac', 'lang': 'en', 'channels': 2}],
        'subs': [{'id': 'e0', 'kind': 'embedded', 'label': 'English', 'lang': 'en', 'text': True}],
    }

    def boom(path):  # pragma: no cover - an unchanged file must not be re-probed
        raise AssertionError('probe must not run for an unchanged file')

    monkeypatch.setattr(library, 'probe', boom)
    monkeypatch.setattr(library, 'chapters_of', lambda p: [{'start': 0.0, 'end': 90.0, 'title': 'OP'}])
    item = library.build_item(src, 25 * _MB, existing)
    assert item['chapters'] == [{'start': 0.0, 'end': 90.0, 'title': 'OP'}]
    kinds = sorted(s['kind'] for s in item['subs'])
    assert kinds == ['embedded', 'external']
    assert item['default_sub'] and item['default_audio'] == 0
    # A changed size re-probes instead of reusing.
    monkeypatch.setattr(library, 'probe', lambda p: _probe_info())
    assert library.build_item(src, 24 * _MB, existing)['size'] == 24 * _MB


# ── The scan job ──────────────────────────────────────────────────────────────
def test_scan_status_is_none_for_an_unknown_id(cine):
    assert library.scan_status('nope') is None


def test_start_scan_refuses_a_path_that_is_not_a_folder(cine):
    missing = os.path.join(cine.root, 'not-there')
    assert library.start_scan(missing) == {'error': f'Not a folder: {missing}'}


def test_start_scan_refuses_a_second_concurrent_scan(cine):
    with library._scan_lock:
        library._scans['running1'] = {'scan_id': 'running1', 'state': 'running'}
    assert library.start_scan(cine.media) == {'error': 'A scan is already running', 'scan_id': 'running1'}


def test_start_scan_indexes_the_tree_and_builds_thumbnails(cine, monkeypatch):
    kept = [_video(cine.media, f'Film {i} 2019 1080p', f'Film.{i}.2019.1080p.mkv') for i in range(5)]
    dup = _video(cine.media, 'Copy', 'Film.0.2019.1080p.mkv')  # same basename+size → duplicate
    broken = _video(cine.media, 'Broken', 'Broken.2019.1080p.mkv')
    gone = os.path.join(cine.media, 'vanished.mkv')
    seed = library._blank_library()
    seed['items'] = {library.item_id_for(gone): {'id': library.item_id_for(gone), 'path': gone, 'filename': 'v.mkv'}}
    library.save_library(seed)

    def fake_probe(path):
        return {} if path == broken else _probe_info()

    thumbed = []

    def fake_thumb(item, force=False):
        thumbed.append(item['id'])
        if len(thumbed) == 1:
            raise RuntimeError('ffmpeg exploded')
        return library.thumb_path(item['id'])

    monkeypatch.setattr(library, 'probe', fake_probe)
    monkeypatch.setattr(library, 'build_thumb', fake_thumb)
    monkeypatch.setattr(library, 'threading', types.SimpleNamespace(Thread=_SyncThread))

    out = library.start_scan(cine.media)
    sid = out['scan_id']
    assert len(sid) == 12
    thread = _SyncThread.made[-1]
    assert thread.daemon is True and thread.name == f'cinema-scan-{sid}'

    st = library.scan_status(sid)
    assert st['state'] == 'done'
    assert st['root'] == cine.media
    assert st['total'] == 7 and st['found'] == 7
    # The duplicate copy and the unprobeable file are both skipped.
    assert st['added'] == 5 and st['updated'] == 0 and st['skipped'] == 2
    assert st['removed'] == 1 and st['current'] == '' and st['thumbs_done'] is True
    assert st['error'] is None and st['finished_at']

    lib = library.load_library()
    assert lib['roots'] == [cine.media]
    assert sorted(it['path'] for it in lib['items'].values()) == sorted(kept)
    assert library.item_id_for(dup) not in lib['items']
    assert library.item_id_for(broken) not in lib['items']
    assert len(thumbed) == 5

    # A second scan over the same tree updates instead of adding.
    again = library.start_scan(cine.media)
    st2 = library.scan_status(again['scan_id'])
    assert (st2['added'], st2['updated'], st2['state']) == (0, 5, 'done')
    assert library.load_library()['roots'] == [cine.media]


def test_start_scan_records_a_failure_instead_of_crashing(cine, monkeypatch):
    def boom(root, max_files=20000):
        raise RuntimeError('walk exploded')

    monkeypatch.setattr(library, '_walk_videos', boom)
    monkeypatch.setattr(library, 'threading', types.SimpleNamespace(Thread=_SyncThread))
    sid = library.start_scan(cine.media)['scan_id']
    st = library.scan_status(sid)
    assert st['state'] == 'failed' and st['error'] == 'walk exploded'
    assert st['finished_at'] and st['thumbs_done'] is True


def test_start_scan_expands_a_relative_user_path(cine, monkeypatch):
    monkeypatch.setenv('HOME', cine.media)
    monkeypatch.setattr(library, 'threading', types.SimpleNamespace(Thread=_SyncThread))
    sid = library.start_scan('~')['scan_id']
    assert library.scan_status(sid)['root'] == os.path.abspath(cine.media)


# ── set_series_name ───────────────────────────────────────────────────────────
def _seed_two_folder_series(cine):
    lib = library._blank_library()
    lib['items'] = {
        'a': {'id': 'a', 'kind': 'episode', 'series': 'Some Show', 'folder': '/m/s1', 'path': '/m/s1/a.mkv'},
        'b': {'id': 'b', 'kind': 'episode', 'series': 'Some Show', 'folder': '/m/s2', 'path': '/m/s2/b.mkv'},
        'c': {'id': 'c', 'kind': 'movie', 'title': 'Some Show', 'folder': '/m/film', 'path': '/m/film/c.mkv'},
    }
    library.save_library(lib)


def test_set_series_name_rejects_an_unknown_series(cine):
    _seed_two_folder_series(cine)
    assert library.set_series_name('No Such Show', 'Nice') == {'error': "No series matching 'No Such Show'"}


def test_set_series_name_covers_every_folder_of_the_group(cine):
    _seed_two_folder_series(cine)
    out = library.set_series_name('some show', 'Nice   Name')
    assert out == {'name': 'Nice Name', 'folders': ['/m/s1', '/m/s2']}
    assert library.load_library()['series_names'] == {'/m/s1': 'Nice Name', '/m/s2': 'Nice Name'}
    # The stored name is what the group is now found by, and '' un-names it.
    assert library.set_series_name('Nice Name', '')['name'] == ''
    assert library.load_library()['series_names'] == {}


def test_set_series_name_truncates_to_120_characters(cine):
    _seed_two_folder_series(cine)
    assert library.set_series_name('Some Show', 'x' * 130)['name'] == 'x' * 120
