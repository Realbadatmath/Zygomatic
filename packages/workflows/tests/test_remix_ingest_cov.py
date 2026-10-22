# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for :mod:`zyg_workflows.remix_ingest`: every state file is redirected
into ``tmp_path`` and the RSS fetch, the Data API call, ``yt_dlp`` and every subprocess are
monkeypatched, so nothing here touches the network, the GPU or a tracked data file."""

from __future__ import annotations

import contextlib
import gzip
import json
import os
import subprocess
import sys
import types
from datetime import timedelta

import pytest

from zyg_workflows import remix_ingest as mod

UC = 'UC' + 'a' * 22
C_OK, C_HOT, C_OFF = UC, 'UC' + 'b' * 22, 'UC' + 'c' * 22


@pytest.fixture
def rt(tmp_path, monkeypatch):
    """Point every path the module derives at a private runtime root."""
    root = tmp_path / 'runtime'
    root.mkdir()
    monkeypatch.setattr(mod, '_RUNTIME', str(root))
    for state in 'CHANNELS WATERMARKS STATS LIBRARY SETTINGS BROLL_CACHE'.split():
        attr = f'_{state}_PATH'
        monkeypatch.setattr(mod, attr, str(root / os.path.basename(getattr(mod, attr))))
    monkeypatch.setattr(mod, '_COOKIE_PATHS', [str(root / 'youtube_cookies.txt')])
    return root


def _ago(hours=0, days=0):
    return mod._iso(mod._now_utc() - timedelta(hours=hours, days=days))


def _write(path, data):
    path.write_text(json.dumps(data), encoding='utf-8')


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _media(path, size=200 * 1024):
    path.write_bytes(b'\0' * size)
    return str(path)


def _fake_yt_dlp(monkeypatch, *, info=None, boom=None, on_download=None):
    """Install a fake ``yt_dlp`` module; the returned dict records what it saw."""
    seen: dict = {'opts': None, 'url': None, 'downloaded': None}

    def extract_info(url, download=False):
        seen['url'] = url
        if boom:
            raise RuntimeError(boom)
        return dict(info or {})

    def download(urls):
        seen['downloaded'] = list(urls)
        if boom:
            raise RuntimeError(boom)
        if on_download:
            on_download()

    def _ydl(opts):
        seen['opts'] = opts
        return contextlib.nullcontext(types.SimpleNamespace(extract_info=extract_info, download=download))

    fake = types.ModuleType('yt_dlp')
    fake.YoutubeDL = _ydl
    monkeypatch.setitem(sys.modules, 'yt_dlp', fake)
    return seen


def _subprocess_stub(monkeypatch, *, returncode=0, stdout='', stderr='', boom=None, on_run=None):
    """Replace ``subprocess.run`` and return the list of argv lists it was handed."""
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        if boom:
            raise boom
        if on_run:
            on_run()
        return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)

    monkeypatch.setattr(subprocess, 'run', fake_run)
    return calls


def test_load_and_save_round_trip_and_swallow_every_failure(tmp_path):
    missing = str(tmp_path / 'nope.json')
    assert mod._load(missing, {'a': 1}) == {'a': 1}
    assert mod._load(missing, list) == []
    (tmp_path / 'broken.json').write_text('{not json', encoding='utf-8')
    assert mod._load(str(tmp_path / 'broken.json'), []) == []

    mod._save(str(tmp_path / 'deep' / 'state.json'), {'k': [1, 2]})
    assert _read(tmp_path / 'deep' / 'state.json') == {'k': [1, 2]}
    assert not (tmp_path / 'deep' / 'state.json.tmp').exists()
    (tmp_path / 'blocker').write_text('x', encoding='utf-8')
    mod._save(str(tmp_path / 'blocker' / 'sub' / 'x.json'), {})  # makedirs → OSError
    mod._save(str(tmp_path / 'bad.json'), {'o': object()})  # json.dump → TypeError
    assert not (tmp_path / 'bad.json').exists()


def test_iso_round_trips_and_parse_iso_takes_every_shape():
    now = mod._now_utc()
    assert mod._parse_iso(mod._iso(now)).replace(microsecond=0) == now.replace(microsecond=0)
    for raw in ('2026-01-02T03:04:05Z', '2026-01-02T03:04:05+00:00', '2026-01-02T03:04:05.123456+0000', mod._iso()):
        assert mod._parse_iso(raw) is not None
    for raw in ('', None, 'nonsense', 1234):
        assert mod._parse_iso(raw) is None
    raws = ('PT1H2M3S', 'PT45S', 'PT10M', '', 'garbage', None)
    assert [mod._parse_iso_duration(r) for r in raws] == [3723, 45, 600, None, None, None]


def test_youtube_api_key_prefers_the_env_then_the_credentials_file(rt, monkeypatch):
    monkeypatch.setenv('YOUTUBE_API_KEY', 'from-env')
    assert mod.youtube_api_key() == 'from-env'
    monkeypatch.delenv('YOUTUBE_API_KEY')
    assert mod.youtube_api_key() == ''
    _write(rt / 'clipfarm_credentials.json', {'YOUTUBE_API_KEY': 'from-file'})
    assert mod.youtube_api_key() == 'from-file'


def test_settings_merges_defaults_and_update_filters_unknown_keys(rt):
    assert mod.settings() == mod.DEFAULT_SETTINGS
    out = mod.update_settings({'auto_mode': True, 'bogus': 'ignored'})
    assert out['auto_mode'] is True
    assert 'bogus' not in out
    assert out['poll_sec'] == mod.DEFAULT_SETTINGS['poll_sec']
    assert _read(rt / 'remix_settings.json') == {'auto_mode': True}
    assert mod.update_settings(None)['auto_mode'] is True


def test_resolve_channel_builds_the_videos_url_and_reports_every_error(rt, monkeypatch):
    monkeypatch.setattr(mod, 'rss_poll', lambda cid, timeout=15: [])
    videos = 'https://www.youtube.com/@Someone/videos'
    for raw, expect_url in (
        ('@Someone', videos),
        ('Some One', 'https://www.youtube.com/@SomeOne/videos'),
        ('https://www.youtube.com/@Someone', videos),
        (videos, videos),
    ):
        seen = _fake_yt_dlp(monkeypatch, info={'channel_id': UC, 'channel': 'Some One'})
        assert mod.resolve_channel(raw) == {'channel_id': UC, 'name': 'Some One'}
        assert seen['url'] == expect_url
        assert seen['opts']['extract_flat'] is True

    assert mod.resolve_channel('   ') == {'error': 'empty input'}
    _fake_yt_dlp(monkeypatch, info={'uploader_id': 'not-a-uc', 'title': 'T'})
    assert 'could not resolve' in mod.resolve_channel('@x')['error']
    _fake_yt_dlp(monkeypatch, boom='403')
    assert mod.resolve_channel('@x')['error'] == 'resolve failed: 403'
    monkeypatch.setattr(mod, 'rss_poll', lambda cid, timeout=15: None)
    assert mod.resolve_channel(UC)['error'] == f'feed for {UC} did not answer'


def test_channel_registry_add_toggle_remove(rt, monkeypatch):
    monkeypatch.setattr(mod, 'rss_poll', lambda cid, timeout=15: [])
    assert mod.channels() == []

    rec = mod.add_channel(UC, clipping_permission=False, notes='hi')
    assert (rec['channel_id'], rec['clipping_permission'], rec['notes']) == (UC, False, 'hi')
    assert [c['channel_id'] for c in mod.channels()] == [UC]
    assert mod.add_channel(UC)['error'] == 'channel already registered'
    assert mod.add_channel('')['error'] == 'empty input'

    assert mod.toggle_channel(UC, 'clipping_permission')['clipping_permission'] is True
    assert mod.toggle_channel(UC)['enabled'] is False
    assert mod.toggle_channel(UC, 'nope') == {'error': 'bad field'}
    assert mod.toggle_channel(C_HOT) == {'error': 'not found'}
    assert mod.remove_channel(UC) is True
    assert mod.remove_channel(UC) is False


FEED = (
    '<feed xmlns="http://www.w3.org/2005/Atom" xmlns:yt="http://www.youtube.com/xml/schemas/2015">'
    '<entry><yt:videoId>aaaaaaaaaaa</yt:videoId><title> One </title>'
    '<published>2026-01-01T00:00:00+00:00</published></entry>'
    '<entry><link rel="alternate" href="https://www.youtube.com/watch?v=bbbbbbbbbbb"/>'
    '<title>Two</title></entry>'
    '<entry><title>no id at all</title></entry>'
    '</feed>'
)


def _urlopen_stub(monkeypatch, bodies):
    """Serve `bodies` (bytes, or an Exception to raise) in order; record the urls asked for."""
    calls: list[str] = []
    queue = list(bodies)

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        assert req.get_header('User-agent') == mod._UA
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        gz = req.get_header('Accept-encoding') == 'gzip'
        body = gzip.compress(item) if gz else item
        headers = {'Content-Encoding': 'gzip'} if gz else {}
        return contextlib.nullcontext(types.SimpleNamespace(read=lambda: body, headers=headers))

    monkeypatch.setattr(mod.urllib.request, 'urlopen', fake_urlopen)
    return calls


def test_rss_poll_parses_cache_busts_falls_back_and_gives_up(monkeypatch):
    calls = _urlopen_stub(monkeypatch, [FEED.encode('utf-8')])
    entries = mod.rss_poll(UC)
    # the third entry carries no id at all and is dropped
    assert [(e['video_id'], e['title'], e['published']) for e in entries] == [
        ('aaaaaaaaaaa', 'One', '2026-01-01T00:00:00+00:00'),
        ('bbbbbbbbbbb', 'Two', ''),  # id recovered from the <link href>
    ]
    assert entries[0]['link'] == 'https://www.youtube.com/watch?v=aaaaaaaaaaa'
    assert len(calls) == 1
    assert f'playlist_id=UULF{UC[2:]}' in calls[0]
    assert '&cb=' in calls[0]

    calls = _urlopen_stub(monkeypatch, [OSError('boom'), b'<feed></feed>'])
    assert mod.rss_poll(UC) == []
    assert len(calls) == 2
    assert f'channel_id={UC}' in calls[1]

    calls = _urlopen_stub(monkeypatch, [b'not xml at all'])
    assert mod.rss_poll('plain-id') is None
    assert len(calls) == 1  # non-UC ids skip the UULF feed


def test_note_seen_returns_first_seen_entries_seeds_stats_and_clears_errors(rt):
    assert mod.note_poll_error(UC) == 1
    assert mod.note_poll_error(UC) == 2

    entries = [{'video_id': f'v{i}', 'title': f'T{i}', 'published': f'p{i}'} for i in (1, 2)]
    assert {e['video_id'] for e in mod.note_seen(UC, entries)} == {'v1', 'v2'}
    seeded = _read(rt / 'remix_stats.json')['v1']
    assert seeded['channel_id'] == UC
    assert (seeded['snapshots'], seeded['duration'], seeded['live']) == ([], None, None)

    assert mod.note_seen(UC, entries) == []
    assert mod.note_seen(UC, None) == []
    assert sorted(mod.watermarks()[UC]['seen']) == ['v1', 'v2']
    assert mod.watermarks()[UC]['consecutive_errors'] == 0


def test_refresh_stats_snapshots_the_due_videos_and_prunes_the_old_ones(rt, monkeypatch):
    monkeypatch.setenv('YOUTUBE_API_KEY', 'k')
    _write(
        rt / 'remix_stats.json',
        {
            'young': {'first_seen': _ago(hours=1), 'snapshots': []},  # <48 h → every 3 h
            'mid': {'first_seen': _ago(hours=100), 'snapshots': [[_ago(hours=20), 10]]},  # 2-10 d → 12 h
            'settled': {'first_seen': _ago(hours=300), 'snapshots': [[_ago(hours=1), 5]]},  # 10-30 d → 24 h
            'ancient': {'first_seen': _ago(days=40), 'snapshots': []},  # past the window
        },
    )
    asked: list[str] = []
    items = [
        {
            'id': 'young',
            'statistics': {'viewCount': '1234'},
            'contentDetails': {'duration': 'PT2M30S'},
            'liveStreamingDetails': {'actualStartTime': 'x'},  # started, never ended → live
        },
        {'id': 'mid', 'statistics': {}, 'contentDetails': {}},
        {'id': 'unknown-id', 'statistics': {'viewCount': '9'}},  # not tracked → ignored
    ]
    monkeypatch.setattr(mod.http_json, 'request_json', lambda url, **k: (asked.append(url), {'items': items})[1])

    assert mod.refresh_stats() == {'snapshotted': 2, 'due': 2}
    assert 'youtube/v3/videos?' in asked[0]
    assert 'part=statistics' in asked[0]

    stats = _read(rt / 'remix_stats.json')
    assert stats['young']['snapshots'][-1][1] == 1234
    assert stats['young']['duration'] == 150
    assert stats['young']['live'] is True
    assert stats['mid']['snapshots'][-1][1] == 0
    assert 'duration' not in stats['mid']  # an empty contentDetails leaves the record alone
    assert 'live' not in stats['mid']
    assert 'ancient' not in stats  # pruned past the 30-day window
    assert 'settled' in stats  # not due, kept untouched


def test_refresh_stats_needs_a_key_bounds_the_batch_and_survives_an_outage(rt, monkeypatch):
    monkeypatch.delenv('YOUTUBE_API_KEY', raising=False)
    assert mod.refresh_stats() == {'error': 'no YOUTUBE_API_KEY', 'snapshotted': 0}

    monkeypatch.setenv('YOUTUBE_API_KEY', 'k')
    _write(rt / 'remix_stats.json', {f'v{i}': {'first_seen': _ago(hours=1), 'snapshots': []} for i in range(4)})
    monkeypatch.setattr(mod.http_json, 'request_json', lambda *a, **k: {'items': []})
    assert mod.refresh_stats(max_videos=1) == {'snapshotted': 0, 'due': 1}

    def boom(*_a, **_k):
        raise OSError('api down')

    monkeypatch.setattr(mod.http_json, 'request_json', boom)
    assert mod.refresh_stats() == {'snapshotted': 0, 'due': 4}

    # and the per-video snapshot list stays bounded at 40 entries
    _write(rt / 'remix_stats.json', {'v': {'first_seen': _ago(hours=1), 'snapshots': [[_ago(hours=50), 1]] * 45}})
    monkeypatch.setattr(
        mod.http_json, 'request_json', lambda *a, **k: {'items': [{'id': 'v', 'statistics': {'viewCount': '7'}}]}
    )
    mod.refresh_stats()
    snaps = _read(rt / 'remix_stats.json')['v']['snapshots']
    assert len(snaps) == 40
    assert snaps[-1][1] == 7


def test_views_10d_is_lifetime_for_young_videos_and_a_delta_for_old_ones():
    now = mod._now_utc()
    assert mod._views_10d({'snapshots': []}, now) is None
    assert mod._views_10d({'published': _ago(days=2), 'snapshots': [[_ago(hours=1), 900]]}, now) == 900
    # first_seen stands in for a missing published date
    assert mod._views_10d({'first_seen': _ago(days=1), 'snapshots': [[_ago(hours=1), 5]]}, now) == 5

    def old(snaps):
        return mod._views_10d({'published': _ago(days=40), 'snapshots': snaps}, now)

    assert old([[_ago(days=15), 1000], [_ago(hours=1), 4000]]) == 3000
    assert old([[_ago(days=3), 100], [_ago(hours=1), 180]]) == 80  # nothing reaches past the window
    assert old([[_ago(days=15), 500], [_ago(hours=1), 100]]) == 0  # a purge clamps, never goes negative


def _stat(cid, *, fs=50, dur=600, views=None, **extra):
    rec = {'channel_id': cid, 'first_seen': _ago(hours=fs), 'published': _ago(hours=fs), 'duration': dur}
    rec['snapshots'] = [] if views is None else [[_ago(hours=1), views]]
    rec.update(extra)
    return rec


def _seed_ranking(rt):
    _write(
        rt / 'remix_channels.json',
        [
            {'channel_id': C_OK, 'name': 'Okay', 'enabled': True, 'clipping_permission': True},
            {'channel_id': C_HOT, 'enabled': True, 'clipping_permission': True},
            {'channel_id': C_OFF, 'enabled': False, 'clipping_permission': True},
        ],
    )
    _write(rt / 'remix_library.json', {'clips': [{'source_video_id': 'remixed'}]})
    _write(
        rt / 'remix_stats.json',
        {
            'brandnew': _stat(C_OK, fs=2, views=1000, title='Brand new'),
            'tiny': _stat(C_OK, views=100),  # under the 500-view floor
            'hot': _stat(C_HOT, dur=1200, views=60000, title='Hot one'),
            'median_a': _stat(C_HOT, views=600),  # sets the channel median, scores below min_score
            'remixed': _stat(C_HOT, views=600),  # already in the clip library
            'nosnaps': _stat(C_HOT),  # no snapshot → no velocity
            'live': _stat(C_HOT, fs=2, live=True),
            'ashort': _stat(C_HOT, fs=2, dur=60),
            'marathon': _stat(C_HOT, fs=2, dur=5 * 3600),
            'disabled': _stat(C_OFF, fs=2),
        },
    )


def test_ranked_candidates_puts_fresh_first_then_the_proven_outliers(rt):
    assert mod.ranked_candidates() == []  # an empty runtime ranks nothing
    _seed_ranking(rt)
    out = mod.ranked_candidates()
    assert [c['video_id'] for c in out] == ['brandnew', 'hot']

    fresh, hot = out
    assert (fresh['reason'], fresh['score'], fresh['views_10d']) == ('fresh', None, 1000)
    assert fresh['channel'] == 'Okay'
    assert fresh['url'] == 'https://www.youtube.com/watch?v=brandnew'
    assert hot['reason'] == 'proven'
    assert hot['channel'] == C_HOT  # no name recorded → the id stands in
    assert hot['outlier'] > 1.0
    assert hot['score'] >= mod.DEFAULT_SETTINGS['min_score']
    assert hot['duration'] == 1200

    assert len(mod.ranked_candidates(limit=1)) == 1
    mod.update_settings({'min_score': 10_000})
    assert [c['video_id'] for c in mod.ranked_candidates()] == ['brandnew']


def test_fetch_video_intel_flattens_the_payload_defaults_and_never_raises(monkeypatch):
    seen = _fake_yt_dlp(
        monkeypatch,
        info={
            'title': 'T',
            'duration': 1200,
            'heatmap': [{'start_time': 0, 'end_time': 12, 'value': 0.5}],
            'chapters': [{'title': 'intro'}],
            'comments': [{'text': 'nice', 'like_count': '4'}, {}],
            'live_status': 'not_live',
        },
    )
    out = mod.fetch_video_intel('vid123', max_comments=5)
    assert (out['title'], out['duration'], out['live_status']) == ('T', 1200, 'not_live')
    assert out['comments'] == [{'text': 'nice', 'likes': 4}, {'text': '', 'likes': 0}]
    assert out['heatmap'][0]['value'] == 0.5
    assert out['chapters'] == [{'title': 'intro'}]
    assert seen['url'] == 'https://www.youtube.com/watch?v=vid123'
    assert seen['opts']['extractor_args']['youtube']['max_comments'][0] == '5'

    seen = _fake_yt_dlp(monkeypatch, info={})
    assert mod.fetch_video_intel('vid123', want_comments=False) == dict.fromkeys(
        ('duration', 'heatmap', 'chapters', 'live_status')
    ) | {'title': 'vid123', 'channel': '', 'channel_id': '', 'comments': []}
    assert seen['opts']['getcomments'] is False

    _fake_yt_dlp(monkeypatch, boom='no such video')
    assert mod.fetch_video_intel('vid123') == {'error': 'no such video'}


def test_detrend_heatmap_normalises_away_the_retention_decay():
    det = mod.detrend_heatmap([10.0] * 10 + [30.0] + [10.0] * 10, w=3)
    assert (min(det), max(det)) == (pytest.approx(0.0), pytest.approx(1.0))
    assert det.index(max(det)) == 10
    assert len(det) == 21
    # a flat curve has no peak to find, and must not divide by zero
    assert mod.detrend_heatmap([5.0] * 6) == [0.0] * 6


def test_comment_timestamps_extracts_in_bounds_mentions_only():
    comments = [
        {'text': 'the bit at 0:45 is gold', 'likes': 12},
        {'text': 'also 1:02:03 and 2:00:00', 'likes': '3'},
        {'text': 'no timestamp here, 1234 views'},
        {},
    ]
    assert mod.comment_timestamps(comments, 4000) == [(45, 12), (3723, 3)]
    assert mod.comment_timestamps(comments, 100) == [(45, 12)]
    assert mod.comment_timestamps(None, 100) == []


def test_find_media_and_the_cookie_and_node_ladders(rt, tmp_path, monkeypatch):
    assert mod._find_media(str(tmp_path), 'v') is None
    (tmp_path / 'v.mp4').write_bytes(b'tiny')  # under the 100 KB floor
    assert mod._find_media(str(tmp_path), 'v') is None
    want = _media(tmp_path / 'v.mkv')
    assert mod._find_media(str(tmp_path), 'v') == want

    assert mod._cookie_file() is None
    (rt / 'youtube_cookies.txt').write_text('# netscape', encoding='utf-8')
    assert mod._cookie_file() == str(rt / 'youtube_cookies.txt')

    monkeypatch.setattr('shutil.which', lambda name: want)
    assert mod._node_bin() == want
    monkeypatch.setattr('shutil.which', lambda name: None)
    assert mod._node_bin() is None


def test_download_video_walks_the_format_cookie_and_node_ladders(tmp_path, monkeypatch, rt):
    out_dir = tmp_path / 'media'
    (rt / 'youtube_cookies.txt').write_text('# netscape', encoding='utf-8')
    monkeypatch.setattr(mod, '_node_bin', lambda: '/usr/bin/node')
    monkeypatch.setattr('shutil.which', lambda name: '/usr/bin/ffmpeg')
    seen = _fake_yt_dlp(monkeypatch, on_download=lambda: _media(out_dir / 'vid123.mp4'))

    assert mod.download_video('vid123', str(out_dir)) == str(out_dir / 'vid123.mp4')
    assert seen['downloaded'] == ['https://www.youtube.com/watch?v=vid123']
    assert seen['opts']['format'].startswith('bestvideo[height<=1080]+bestaudio/')
    assert seen['opts']['cookiefile'] == str(rt / 'youtube_cookies.txt')
    assert seen['opts']['js_runtimes'] == {'node': {'path': '/usr/bin/node'}}
    assert seen['opts']['outtmpl'] == str(out_dir / 'vid123.%(ext)s')

    # a second call finds the file already there and never reaches yt-dlp
    _fake_yt_dlp(monkeypatch, boom='must not be called')
    assert mod.download_video('vid123', str(out_dir)) == str(out_dir / 'vid123.mp4')

    # without ffmpeg, cookies or node the ladder falls back to a single muxed format
    bare = str(tmp_path / 'bare')
    monkeypatch.setattr(mod, '_node_bin', lambda: None)
    monkeypatch.setattr(mod, '_COOKIE_PATHS', [])
    monkeypatch.setattr('shutil.which', lambda name: None)
    seen = _fake_yt_dlp(monkeypatch)
    assert mod.download_video('vid123', bare) == ''  # yt-dlp wrote nothing
    assert seen['opts']['format'] == 'best[ext=mp4]/best'
    assert 'cookiefile' not in seen['opts']
    assert 'js_runtimes' not in seen['opts']

    _fake_yt_dlp(monkeypatch, boom='429 rate limited')
    said: list[str] = []
    assert mod.download_video('vid123', bare, log=said.append) == ''
    assert said == ['download failed for vid123: 429 rate limited']


def test_download_section_passes_the_padded_range_and_reports_failures(tmp_path, monkeypatch):
    out_dir = tmp_path / 'sections'
    monkeypatch.setattr(mod, '_cookie_file', lambda: '/tmp/ck.txt')
    calls = _subprocess_stub(monkeypatch, on_run=lambda: _media(out_dir / 'vid123_30_40.mp4'))

    got = mod.download_section('vid123', 30.0, 40.0, str(out_dir))
    assert got == str(out_dir / 'vid123_30_40.mp4')
    cmd = calls[0]
    assert (cmd[0], cmd[1]) == (sys.executable, '-m')
    assert cmd[2:4] == ['--cookies', '/tmp/ck.txt']  # spliced in between `-m` and `yt_dlp`
    assert 'yt_dlp' in cmd
    assert '*27.0-43.0' in cmd
    assert '--force-keyframes-at-cuts' in cmd
    assert cmd[-1] == 'https://www.youtube.com/watch?v=vid123'
    assert mod.download_section('vid123', 30.0, 40.0, str(out_dir)) == got  # already on disk
    assert len(calls) == 1

    monkeypatch.setattr(mod, '_cookie_file', lambda: None)
    calls = _subprocess_stub(monkeypatch, returncode=1, stderr='E' * 300)
    said: list[str] = []
    assert mod.download_section('v', 2.0, 9.0, str(out_dir), log=said.append) == ''
    assert '*0.0-12.0' in calls[0]  # the start is clamped at zero
    assert '--cookies' not in calls[0]
    assert len(said[0]) == len('section download failed: ') + 200

    _subprocess_stub(monkeypatch, boom=OSError('no python'))
    said.clear()
    assert mod.download_section('v', 2.0, 9.0, str(out_dir), log=said.append) == ''
    assert said == ['section download error: no python']


def test_broll_catalog_probes_once_then_reads_the_cache(rt, tmp_path, monkeypatch):
    assert mod.broll_dir() == mod.paths.ZYG_REMIX_BROLL_DIR
    monkeypatch.setattr(mod, 'broll_dir', lambda: str(tmp_path / 'nope'))
    assert mod.broll_catalog() == []  # an unreadable directory yields nothing

    root = tmp_path / 'broll'
    root.mkdir()
    for name in ('a_minecraft.mp4', 'broken_minecraft.mp4', 'short_minecraft.mp4', 'other.mp4', 'notes.txt'):
        (root / name).write_bytes(b'\0')
    monkeypatch.setattr(mod, 'broll_dir', lambda: str(root))
    monkeypatch.setattr(mod, 'exe', lambda name: f'/usr/bin/{name}')
    probed: list[str] = []

    def fake_run(cmd, **kwargs):
        probed.append(os.path.basename(cmd[-1]))
        if 'broken' in cmd[-1]:
            raise OSError('ffprobe exploded')
        return subprocess.CompletedProcess(cmd, 0, '10.0\n' if 'short' in cmd[-1] else '300.5\n', '')

    monkeypatch.setattr(subprocess, 'run', fake_run)

    assert mod.broll_catalog() == [{'path': str(root / 'a_minecraft.mp4'), 'duration': 300.5}]
    assert sorted(probed) == ['a_minecraft.mp4', 'broken_minecraft.mp4', 'short_minecraft.mp4']
    assert _read(rt / 'remix_broll_cache.json') == {
        'a_minecraft.mp4': 300.5,
        'broken_minecraft.mp4': 0.0,
        'short_minecraft.mp4': 10.0,
    }

    probed.clear()
    assert mod.broll_catalog(min_duration=5.0) == [
        {'path': str(root / 'a_minecraft.mp4'), 'duration': 300.5},
        {'path': str(root / 'short_minecraft.mp4'), 'duration': 10.0},
    ]
    assert probed == []  # the cache answered


def test_pick_broll_window_avoids_the_windows_already_used(monkeypatch):
    monkeypatch.setattr(mod.random, 'shuffle', lambda seq: None)
    monkeypatch.setattr(mod.random, 'uniform', lambda a, b: 100.0)
    monkeypatch.setattr(mod, 'broll_catalog', lambda min_duration=120.0: [])
    assert mod.pick_broll_window(60.0) == {}

    cands = [{'path': '/b/one.mp4', 'duration': 400.0}]
    monkeypatch.setattr(mod, 'broll_catalog', lambda min_duration=120.0: list(cands))
    assert mod.pick_broll_window(60.0) == {'path': '/b/one.mp4', 'offset': 100.0}

    # every draw clashes with the avoid list → the fallback window is handed back anyway
    avoid = [{'path': '/b/one.mp4', 'offset': 100.0}]
    assert mod.pick_broll_window(60.0, avoid=avoid) == {'path': '/b/one.mp4', 'offset': 100.0}

    cands.append({'path': '/b/two.mp4', 'duration': 400.0})  # a file with no clash is preferred
    assert mod.pick_broll_window(60.0, avoid=avoid) == {'path': '/b/two.mp4', 'offset': 100.0}


def test_library_register_update_and_mark_deleted(rt):
    assert mod.library() == {'clips': []}
    mod.library_register({'clip_id': 'c1', 'job_id': 'j1', 'source_video_id': 'v1'})
    mod.library_register({'clip_id': 'c2', 'job_id': 'j1'})
    mod.library_register({'clip_id': 'c3', 'job_id': 'j2'})
    assert [c['clip_id'] for c in mod.library()['clips']] == ['c1', 'c2', 'c3']

    assert mod.library_update(['c1', 'c3', 'missing'], {'phash': 'ab'}) == 2
    assert mod.library_update([], {'phash': 'zz'}) == 0
    clips = {c['clip_id']: c for c in mod.library()['clips']}
    assert clips['c1']['phash'] == 'ab'
    assert 'phash' not in clips['c2']

    assert mod.library_mark_deleted_for_job('j1') == 2
    assert mod.library_mark_deleted_for_job('j1') == 0  # idempotent
    assert mod.library_mark_deleted_for_job('nope') == 0
    clips = {c['clip_id']: c for c in mod.library()['clips']}
    assert (clips['c1']['deleted'], clips['c2']['deleted']) == (True, True)
    assert 'deleted' not in clips['c3']
