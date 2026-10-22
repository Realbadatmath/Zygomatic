# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Offline coverage for zyg_dashboard.kanban.music.

Every library root the module reads is redirected to tmp_path through the
module's own constants, and the two HTTP forwarders are exercised against a
monkeypatched ``urllib.request.urlopen`` — nothing here touches the network,
the GPU or the repository's tracked output trees.
"""

import io
import json
import os
import urllib.error
import urllib.request

import pytest

from zyg_dashboard.kanban import music as mod

SID = 'a1b2c3d4e5f6'
SID2 = 'cli_20260101'


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """(children, cinematic) library roots under tmp_path, plus a cold cache."""
    out = os.path.realpath(str(tmp_path))
    children = os.path.join(out, 'kidsmusic')
    cinematic = os.path.join(out, 'cinematic')
    os.makedirs(children)
    os.makedirs(cinematic)
    monkeypatch.setattr(mod, '_OUTPUT_ROOT', out)
    monkeypatch.setattr(mod, '_KM_ROOTS', {'children': children, 'cinematic': cinematic})
    monkeypatch.setattr(mod, '_KM_ROOT', children)
    monkeypatch.setattr(mod, '_KM_CACHE', {'ts': 0.0, 'data': None})
    return children, cinematic


def _song(root, sid, manifest=None, **extra):
    """A song folder with an optional manifest and extra text files."""
    d = os.path.join(root, sid)
    os.makedirs(d, exist_ok=True)
    if manifest is not None:
        _write(os.path.join(d, 'manifest.json'), json.dumps(manifest))
    for name, body in extra.items():
        _write(os.path.join(d, name.replace('__', '.')), body)
    return d


def _write(path, body):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(body)


# ── _km_dir / _km_root_of ────────────────────────────────────────────────────


@pytest.mark.parametrize('sid', ['', None, 'nope', '../etc', 'a1b2c3', 'A1B2C3D4E5F6'])
def test_km_dir_refuses_ids_outside_the_pattern(roots, sid):
    assert mod._km_dir(sid) is None


def test_km_dir_finds_a_song_in_either_root_and_misses_absent_ones(roots):
    children, cinematic = roots
    _song(children, SID)
    _song(cinematic, SID2)
    assert mod._km_dir(SID) == os.path.join(children, SID)
    assert mod._km_dir(SID2) == os.path.join(cinematic, SID2)
    assert mod._km_dir('ffffffffffff') is None


def test_km_root_of_names_the_family_root(roots):
    children, cinematic = roots
    assert mod._km_root_of(os.path.join(children, SID)) == 'children'
    assert mod._km_root_of(os.path.join(cinematic, SID)) == 'cinematic'
    assert mod._km_root_of('/somewhere/else/song') == ''


# ── _km_derive_shelf ─────────────────────────────────────────────────────────

DERIVE_CASES = [
    ('declared style wins', {'style': 'Lullaby'}, ('children', 'lullaby')),
    ('style under brief', {'brief': {'style': 'counting'}}, ('children', 'counting')),
    ('unknown family falls back to children', {'family': 'martian'}, ('children', 'playtime')),
    ('family from the brief', {'brief': {'family': 'Cinematic', 'mood': 'sad'}}, ('cinematic', 'sad')),
    ('sleepy mood', {'labels': {'mood': 'dreamy'}}, ('children', 'sleeptime')),
    ('slow bpm', {'music': {'bpm': 72}}, ('children', 'sleeptime')),
    ('bpm out of the sleepy band', {'music': {'bpm': 140}}, ('children', 'playtime')),
    ('unparsable bpm', {'music': {'bpm': 'fast'}}, ('children', 'playtime')),
    ('narrative theme', {'brief': {'theme': 'a dinosaur who lost his socks'}}, ('children', 'storytime')),
    ('activity theme', {'brief': {'theme': 'washing your hands'}}, ('children', 'playtime')),
    (
        'mood matched inside a cinematic shelf key',
        {'family': 'cinematic', 'labels': {'mood': 'very heroic'}},
        ('cinematic', 'heroic'),
    ),
    (
        'cinematic narrative theme with no mood',
        {'family': 'cinematic', 'brief': {'theme': 'the train that says toot'}},
        ('cinematic', 'storytime'),
    ),
    ('cinematic fallback', {'family': 'cinematic', 'labels': {'mood': 'beige'}}, ('cinematic', 'cheerful')),
    (
        'soundtracks fallback has no storytime shelf',
        {'family': 'soundtracks', 'brief': {'theme': 'a knight who rides'}},
        ('soundtracks', 'underscore'),
    ),
    (
        'soundtracks cue role from the mood',
        {'family': 'soundtracks', 'labels': {'mood': 'tension'}},
        ('soundtracks', 'tension'),
    ),
]


@pytest.mark.parametrize('label,manifest,expected', DERIVE_CASES, ids=[c[0] for c in DERIVE_CASES])
def test_km_derive_shelf(label, manifest, expected):
    assert mod._km_derive_shelf(manifest) == expected


def test_km_derive_shelf_survives_null_sections():
    assert mod._km_derive_shelf({'labels': None, 'brief': None, 'music': None}) == ('children', 'playtime')


def test_km_fallback_shelf_keys_exist_in_their_family():
    for fam, shelf in mod._KM_FALLBACK_SHELF.items():
        assert shelf in mod._KM_SHELF_OK[fam]
        assert mod._KM_FIRST_SHELF[fam] in mod._KM_SHELF_OK[fam]


# ── _km_shelf_of ─────────────────────────────────────────────────────────────


def test_km_shelf_of_prefers_the_written_record(roots):
    children, _ = roots
    d = _song(children, SID)
    _write(os.path.join(d, 'shelf.json'), json.dumps({'family': 'children', 'shelf': 'Nursery', 'filed': '2026-09-01'}))
    assert mod._km_shelf_of(d, {}) == {
        'family': 'children',
        'shelf': 'nursery',
        'source': 'filed',
        'filed': '2026-09-01',
    }


def test_km_shelf_of_ignores_a_record_naming_an_unknown_shelf(roots):
    children, _ = roots
    d = _song(children, SID)
    _write(os.path.join(d, 'shelf.json'), json.dumps({'family': 'children', 'shelf': 'disco'}))
    got = mod._km_shelf_of(d, {'style': 'animals'})
    assert got == {'family': 'children', 'shelf': 'animals', 'source': 'derived', 'filed': ''}


def test_km_shelf_of_derives_when_the_record_is_missing_or_broken(roots, caplog):
    children, _ = roots
    d = _song(children, SID)
    assert mod._km_shelf_of(d, {})['source'] == 'derived'
    _write(os.path.join(d, 'shelf.json'), 'not json at all')
    with caplog.at_level('WARNING'):
        assert mod._km_shelf_of(d, {})['source'] == 'derived'
    assert 'unreadable' in caplog.text


# ── _km_file_song ────────────────────────────────────────────────────────────


def test_km_file_song_writes_the_record_and_clears_the_cache(roots):
    children, _ = roots
    d = _song(children, SID)
    mod._KM_CACHE.update({'ts': 123.0, 'data': {'songs': []}})
    body, code = mod._km_file_song(SID, 'children', 'sleeptime')
    assert code == 200
    assert body['ok'] is True and body['id'] == SID and body['shelf'] == 'sleeptime'
    assert body['filed']
    with open(os.path.join(d, 'shelf.json'), encoding='utf-8') as fh:
        assert json.load(fh)['shelf'] == 'sleeptime'
    assert mod._KM_CACHE == {'ts': 0.0, 'data': None}
    assert not os.path.exists(os.path.join(d, 'shelf.json.part'))


def test_km_file_song_refuses_an_unknown_song(roots):
    assert mod._km_file_song('ffffffffffff', 'children', 'playtime') == ({'error': 'no such song'}, 404)


@pytest.mark.parametrize('family,shelf', [('martian', 'playtime'), ('children', 'disco')])
def test_km_file_song_refuses_an_unknown_shelf(roots, family, shelf):
    children, _ = roots
    _song(children, SID)
    body, code = mod._km_file_song(SID, family, shelf)
    assert code == 400
    assert body['error'] == f'unknown shelf {family}/{shelf}'


def test_km_file_song_reports_a_write_failure(roots, monkeypatch):
    children, _ = roots
    _song(children, SID)

    def _boom(*a, **k):
        raise OSError('disk full')

    monkeypatch.setattr('builtins.open', _boom)
    body, code = mod._km_file_song(SID, 'children', 'playtime')
    assert code == 500
    assert body['error'].startswith('could not write shelf.json:')


# ── _km_download_name ────────────────────────────────────────────────────────


def test_km_download_name_cleans_the_title_and_names_the_leg(roots):
    children, _ = roots
    d = _song(children, SID, manifest={'title': 'Ten "Little" Bees; drop\nit/'})
    # The quotes, the semicolon, the newline and the separator are all gone.
    assert mod._km_download_name(d, 'master.mp3') == 'Ten Little Bees dropit - master.mp3'
    assert mod._km_download_name(d, 'stems/vocals.flac') == 'Ten Little Bees dropit - voice track.flac'


def test_km_download_name_falls_back_to_the_folder_name(roots, caplog):
    children, _ = roots
    d = _song(children, SID)
    with caplog.at_level('DEBUG'):
        assert mod._km_download_name(d, 'frames/f12.png') == f'{SID} - f12.png'
    assert mod._km_download_name(d, 'odd_leg') == f'{SID} - odd_leg.bin'


def test_km_download_name_ignores_an_unusable_title(roots):
    children, _ = roots
    d = _song(children, SID, manifest={'title': '***'})
    assert mod._km_download_name(d, 'melody.mid') == f'{SID} - score.mid'


# ── _km_series ───────────────────────────────────────────────────────────────


def _episode(base, job, manifest, *, video=b'mp4', poster=b'jpg'):
    jd = os.path.join(base, job)
    os.makedirs(jd, exist_ok=True)
    if manifest is not None:
        _write(os.path.join(jd, 'manifest.json'), manifest)
    if video is not None:
        with open(os.path.join(jd, 'episode.mp4'), 'wb') as fh:
            fh.write(video)
    if poster is not None:
        with open(os.path.join(jd, 'poster.jpg'), 'wb') as fh:
            fh.write(poster)
    return jd


def test_km_series_returns_nothing_when_the_output_root_is_gone(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_OUTPUT_ROOT', str(tmp_path / 'absent'))
    assert mod._km_series() == []


def test_km_series_builds_one_card_per_delivered_episode(roots):
    out = mod._OUTPUT_ROOT
    base = os.path.join(out, 'kids_bug_band')
    _episode(base, 'job1', json.dumps({'title': 'Bug Band', 'episode': 3, 'duration_s': 140.4, 'ok': True}))
    _episode(base, 'test_2', json.dumps({'episode': 4, 'test_mode': True}), poster=None)
    _episode(base, '.hidden', json.dumps({'episode': 9}))
    _episode(base, 'medusa_job', json.dumps({'episode': 9}))
    _episode(base, 'noman', None)
    _write(os.path.join(base, 'loose.txt'), 'x')
    _episode(base, 'bad_manifest', '[1, 2, 3]')
    _episode(base, 'novideo', json.dumps({'episode': 5}), video=None)
    os.makedirs(os.path.join(out, 'kids_empty'))
    _write(os.path.join(out, 'kids_not_a_dir'), 'x')
    _write(os.path.join(out, 'unrelated'), 'x')

    series = mod._km_series()
    slugs = [s['slug'] for s in series]
    assert slugs == ['bug_band', 'empty']
    band = series[0]
    assert band['title'] == 'Bug Band'
    jobs = sorted(e['job'] for e in band['episodes'])
    assert jobs == ['bad_manifest', 'job1', 'noman', 'test_2']
    ep = next(e for e in band['episodes'] if e['job'] == 'job1')
    assert ep['label'] == 'Episode 3 · 140s'
    assert ep['url'] == '/inspect/media?path=out/kids_bug_band/job1/episode.mp4'
    assert ep['still'] == '/inspect/media?path=out/kids_bug_band/job1/poster.jpg'
    assert ep['thumb'] == '/inspect/thumb?path=out/kids_bug_band/job1/poster.jpg'
    assert ep['final'] is True and ep['test'] is False and ep['ok'] is True
    assert ep['group'] == 'Bug Band' and ep['size'] == 3
    unit = next(e for e in band['episodes'] if e['job'] == 'test_2')
    assert unit['label'] == 'Episode 4 · test unit'
    assert unit['test'] is True and unit['final'] is False
    assert unit['thumb'] == '/inspect/thumb?path=out/kids_bug_band/test_2/episode.mp4'
    assert unit['still'] == ''
    assert next(e for e in band['episodes'] if e['job'] == 'noman')['label'] == 'Episode ?'
    assert series[1] == {'slug': 'empty', 'title': 'Empty', 'episodes': []}


def test_km_series_skips_an_unlistable_series_folder(roots, monkeypatch, caplog):
    out = mod._OUTPUT_ROOT
    base = os.path.join(out, 'kids_locked')
    _episode(base, 'job1', json.dumps({'episode': 1}))
    real = os.listdir

    def _listdir(path):
        if str(path) == base:
            raise OSError('permission denied')
        return real(path)

    monkeypatch.setattr(mod.os, 'listdir', _listdir)
    with caplog.at_level('WARNING'):
        assert mod._km_series() == []
    assert 'not listable' in caplog.text


def test_km_series_skips_an_unstatable_episode(roots, monkeypatch, caplog):
    out = mod._OUTPUT_ROOT
    base = os.path.join(out, 'kids_ghost')
    _episode(base, 'job1', json.dumps({'episode': 1}))

    def _getmtime(path):
        raise OSError('vanished')

    monkeypatch.setattr(mod.os.path, 'getmtime', _getmtime)
    with caplog.at_level('DEBUG'):
        assert mod._km_series() == [{'slug': 'ghost', 'title': 'Ghost', 'episodes': []}]
    assert 'not statable' in caplog.text


# ── _api_kidsmusic ───────────────────────────────────────────────────────────


def test_api_kidsmusic_serves_the_cache_until_it_is_forced(roots, monkeypatch):
    mod._KM_CACHE.update({'ts': 1e12, 'data': {'songs': ['cached']}})
    monkeypatch.setattr(mod.time, 'time', lambda: 1e12)
    assert mod._api_kidsmusic()['songs'] == ['cached']
    forced = mod._api_kidsmusic(force=True)
    assert forced['songs'] == []
    assert forced['count'] == 0
    assert forced['root'] == 'kidsmusic'
    assert forced['roots'] == {'children': 'kidsmusic', 'cinematic': 'cinematic'}
    assert [f['key'] for f in forced['families']] == ['children', 'cinematic', 'soundtracks']
    assert forced['families'][0]['shelves'][0] == {'key': 'playtime', 'label': 'Playtime'}
    assert mod._KM_CACHE['data'] is forced


def test_api_kidsmusic_lists_a_full_song(roots):
    children, cinematic = roots
    manifest = {
        'title': 'Bubble March',
        'style': 'playtime',
        'family': 'children',
        'created': '2026-09-02',
        'elapsed_s': 12.5,
        'brief': {'theme': 'bubbles'},
        'labels': {'mood': 'happy'},
        'music': {'bpm': 120},
        'score': {'total': 8.1, 'ok': True, 'subscores': {'melody': 9}, 'seed': 7, 'candidates': 3},
        'gates': {'loudness': 'ok'},
        'delivery': {'to': 'ada@example.com'},
        'licence': {'kind': 'AGPL'},
        'lyrics_source': 'llm',
        'voice': {'ok': True},
        'video': {
            'ok': True,
            'file': 'video.mp4',
            'poster': 'poster.jpg',
            'ideas': {'llm': 'secret', 'kept': 'yes'},
            'elapsed_s': 3,
        },
    }
    d = _song(children, SID, manifest=manifest)
    _write(os.path.join(d, 'lyrics.txt'), 'la ' * 900)
    _write(os.path.join(d, 'master.mp3'), 'ID3')
    _write(os.path.join(d, 'stems/vocals.flac'), 'fLaC')
    _write(
        os.path.join(d, 'storyboard.json'),
        json.dumps({'slots': [{'i': i, 'start': i, 'name': f's{i}', 'source_render': 'r'} for i in range(401)]}),
    )
    # A second song, newer, with the thinnest possible manifest.
    d2 = _song(cinematic, SID2, manifest={})
    os.utime(os.path.join(d2, 'manifest.json'), (2e9, 2e9))

    data = mod._api_kidsmusic(force=True)
    assert data['count'] == 2
    first, second = data['songs']
    assert first['id'] == SID2 and first['root'] == 'cinematic' and first['title'] == SID2
    assert second['id'] == SID and second['root'] == 'children'
    assert second['shelf'] == {'family': 'children', 'shelf': 'playtime', 'source': 'derived', 'filed': ''}
    # Only whitelisted legs that exist on disk, each with its real size.
    assert sorted(second['files']) == [
        'lyrics.txt',
        'manifest.json',
        'master.mp3',
        'stems/vocals.flac',
        'storyboard.json',
    ]
    assert second['files']['master.mp3'] == 3
    assert second['files']['stems/vocals.flac'] == 4
    assert second['files']['lyrics.txt'] == 2700
    assert len(second['lyrics']) == 1200
    assert len(second['slots']) == 400
    assert second['slots'][0] == {
        'i': 0,
        'start': 0,
        'dur': None,
        'pace': None,
        'name': 's0',
        'role': None,
        'motif': None,
        'idea': None,
        'source': None,
        'render': 'r',
    }
    assert second['video']['ok'] is True and second['video']['ideas'] == {'kept': 'yes'}
    assert second['score']['total'] == 8.1 and second['score']['fails'] == []
    assert second['voice'] == {'ok': True}
    assert first['voice'] is None and first['slots'] == []


def test_api_kidsmusic_skips_unreadable_manifests_and_unsized_files(roots, monkeypatch, caplog):
    children, cinematic = roots
    _song(children, 'aaaaaaaaaaaa', manifest=None)
    _song(children, 'bbbbbbbbbbbb')
    _write(os.path.join(children, 'bbbbbbbbbbbb', 'manifest.json'), '{ broken')
    _write(os.path.join(children, 'not-an-id', 'manifest.json'), '{}')
    # A video song whose storyboard cannot be read: the slot list stays empty.
    d = _song(cinematic, 'cccccccccccc', manifest={'video': {'ok': True}})
    _write(os.path.join(d, 'master.mp3'), 'ID3')
    _write(os.path.join(d, 'storyboard.json'), 'not json')
    # Same id in both roots: one song, listed once, from the first root.
    _song(cinematic, SID, manifest={'title': 'cinematic copy'})
    _song(children, SID, manifest={'title': 'children copy'})

    def _getsize(path):
        raise OSError('gone')

    monkeypatch.setattr(mod.os.path, 'getsize', _getsize)
    with caplog.at_level('WARNING'):
        data = mod._api_kidsmusic(force=True)
    by_id = {s['id']: s for s in data['songs']}
    assert sorted(by_id) == ['a1b2c3d4e5f6', 'cccccccccccc']
    assert by_id[SID]['root'] == 'children' and by_id[SID]['title'] == 'children copy'
    assert by_id['cccccccccccc']['files'] == {'manifest.json': 0, 'master.mp3': 0, 'storyboard.json': 0}
    assert by_id['cccccccccccc']['slots'] == []
    assert 'missing from the list' in caplog.text


def test_api_kidsmusic_treats_an_absent_root_as_empty(roots, monkeypatch, tmp_path, caplog):
    monkeypatch.setattr(mod, '_KM_ROOTS', {'children': str(tmp_path / 'nowhere')})
    with caplog.at_level('DEBUG'):
        assert mod._api_kidsmusic(force=True)['songs'] == []
    assert 'treated as empty' in caplog.text


# ── _km_theory / _km_spec ────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _cold_theory_cache(monkeypatch):
    monkeypatch.setattr(mod, '_KM_SPEC_MOD', {'m': None, 'err': ''})


def test_km_theory_caches_the_imported_module(monkeypatch):
    # another test (or the app) may already have imported the composer: start from a fresh cache
    monkeypatch.setattr(mod, '_KM_SPEC_MOD', {'m': None, 'err': ''})
    import types

    import zyg_workflows

    fake = types.SimpleNamespace(ui_spec=lambda: {'styles': ['playtime']})
    monkeypatch.setitem(__import__('sys').modules, 'zyg_workflows.kids_music_theory', fake)
    # `from zyg_workflows import kids_music_theory` reads the PACKAGE attribute first when the real
    # module was imported earlier in the session, so the stand-in must sit there as well.
    monkeypatch.setattr(zyg_workflows, 'kids_music_theory', fake, raising=False)
    assert mod._km_theory() is fake
    assert mod._km_theory() is fake
    assert mod._km_spec() == {'styles': ['playtime']}


def test_km_theory_records_an_import_failure(monkeypatch, caplog):
    # another test (or the app) may already have imported the composer: start from a fresh cache
    monkeypatch.setattr(mod, '_KM_SPEC_MOD', {'m': None, 'err': ''})
    import zyg_workflows

    monkeypatch.setitem(__import__('sys').modules, 'zyg_workflows.kids_music_theory', None)
    monkeypatch.delattr(zyg_workflows, 'kids_music_theory', raising=False)
    with caplog.at_level('INFO'):
        assert mod._km_theory() is None
    assert mod._KM_SPEC_MOD['err'].startswith('ModuleNotFoundError')
    # The second call does not retry the import — the error is remembered.
    assert mod._km_theory() is None
    body = mod._km_spec()
    assert body['error'].startswith('composer unavailable: ModuleNotFoundError')


# ── the two forwarders ───────────────────────────────────────────────────────


class _Resp:
    def __init__(self, body):
        self._body = body

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _http_error(code, body):
    return urllib.error.HTTPError('http://x', code, 'boom', {}, io.BytesIO(body))


@pytest.fixture
def calls(monkeypatch):
    """Record every urlopen call and reply from a queue of outcomes."""
    seen = []

    def _factory(outcome):
        def _urlopen(req, timeout=None):
            seen.append(
                {
                    'url': req.full_url,
                    'method': req.get_method(),
                    'headers': dict(req.headers),
                    'data': req.data,
                    'timeout': timeout,
                }
            )
            if isinstance(outcome, Exception):
                raise outcome
            return _Resp(outcome)

        monkeypatch.setattr(urllib.request, 'urlopen', _urlopen)
        return seen

    return _factory


def test_km_forward_posts_json_and_decodes_the_reply(calls):
    seen = calls(b'{"ok": true}')
    assert mod._km_forward('/api/kidsmusic', {'style': 'playtime'}, method='POST', timeout=5) == ({'ok': True}, 200)
    assert seen[0]['url'] == f'{mod._MAIN_APP}/api/kidsmusic'
    assert seen[0]['method'] == 'POST'
    assert json.loads(seen[0]['data']) == {'style': 'playtime'}
    assert seen[0]['timeout'] == 5
    assert 'X-zero-public-token' not in seen[0]['headers']


def test_km_forward_sends_no_body_on_get(calls):
    seen = calls(b'')
    assert mod._km_forward('/api/kidsmusic') == ({}, 200)
    assert seen[0]['data'] is None and seen[0]['method'] == 'GET'


def test_km_forward_passes_an_http_error_body_through(calls):
    calls(_http_error(409, b'{"error": "busy"}'))
    assert mod._km_forward('/api/x') == ({'error': 'busy'}, 409)


def test_km_forward_summarises_an_unparsable_http_error(calls):
    calls(_http_error(500, b'<html>nope'))
    assert mod._km_forward('/api/x') == ({'error': 'pipeline API returned 500'}, 500)


def test_km_forward_reports_an_unreachable_api(calls):
    calls(urllib.error.URLError('connection refused'))
    body, code = mod._km_forward('/api/x')
    assert code == 502
    assert body['error'].startswith('pipeline API unreachable:')


def test_pe_forward_refuses_without_a_token(monkeypatch):
    monkeypatch.setattr(mod, '_internal_token', lambda: '')
    body, code = mod._pe_forward('/api/edit')
    assert code == 503
    assert 'ZERO_PUBLIC_TOKEN not set' in body['error']


def test_pe_forward_authenticates_the_hop(monkeypatch, calls):
    monkeypatch.setattr(mod, '_internal_token', lambda: 'sekrit')
    seen = calls(b'{"job": "1"}')
    assert mod._pe_forward('/api/edit', {'op': 'crop'}, method='POST') == ({'job': '1'}, 200)
    assert seen[0]['headers']['X-zero-public-token'] == 'sekrit'
    assert json.loads(seen[0]['data']) == {'op': 'crop'}
    assert seen[0]['timeout'] == 30


def test_pe_forward_passes_an_http_error_body_through(monkeypatch, calls):
    monkeypatch.setattr(mod, '_internal_token', lambda: 'sekrit')
    calls(_http_error(403, b'{"error": "denied"}'))
    assert mod._pe_forward('/api/edit') == ({'error': 'denied'}, 403)


def test_pe_forward_summarises_an_unparsable_http_error(monkeypatch, calls):
    monkeypatch.setattr(mod, '_internal_token', lambda: 'sekrit')
    calls(_http_error(502, b'not json'))
    assert mod._pe_forward('/api/edit') == ({'error': 'pipeline API returned 502'}, 502)


def test_pe_forward_reports_an_unreachable_api(monkeypatch, calls):
    monkeypatch.setattr(mod, '_internal_token', lambda: 'sekrit')
    calls(OSError('socket closed'))
    body, code = mod._pe_forward('/api/edit')
    assert code == 502
    assert body['error'].startswith('pipeline API unreachable:')
