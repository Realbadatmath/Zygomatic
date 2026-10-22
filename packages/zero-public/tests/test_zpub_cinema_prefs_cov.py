# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_zero.zpub_cinema.prefs: prefs round-trip, naming keys,
default track picking and intro/outro mark detection — all offline."""

import json
import logging
import os

import pytest

from zyg_zero.zpub_cinema import prefs as MOD


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    """Every test reads and writes its own prefs JSON, never the repo's."""
    path = tmp_path / 'cinema_prefs.json'
    monkeypatch.setattr(MOD, 'PREFS_PATH', str(path))
    monkeypatch.setitem(MOD._prefs_cache, 'mtime', -1.0)
    monkeypatch.setitem(MOD._prefs_cache, 'data', None)
    return path


# ── load_prefs / save_prefs ───────────────────────────────────────────────────
def test_load_without_a_file_is_the_blank_shape_and_is_cached():
    first = MOD.load_prefs()
    assert first == {'version': 1, 'defaults': dict(MOD.DEFAULT_PREFS), 'shows': {}}
    # Second call takes the "missing file, already blank" branch and hands back
    # the very same object.
    assert MOD.load_prefs() is first


def test_save_then_load_round_trips_and_a_repeat_load_hits_the_cache(prefs_file):
    MOD.save_prefs({'version': 1, 'defaults': {'sub_langs': ['nl']}, 'shows': {'slime': {'intro_end': 7.0}}})
    assert json.loads(prefs_file.read_text(encoding='utf-8'))['shows'] == {'slime': {'intro_end': 7.0}}
    data = MOD.load_prefs()
    assert data['shows'] == {'slime': {'intro_end': 7.0}}
    assert MOD.load_prefs() is data


def test_a_file_written_behind_our_back_is_merged_over_the_defaults(prefs_file):
    prefs_file.write_text(
        json.dumps({'defaults': {'sub_langs': ['nl'], 'bogus': 1}, 'shows': 'not-a-dict'}),
        encoding='utf-8',
    )
    data = MOD.load_prefs()
    assert data['defaults']['sub_langs'] == ['nl']
    assert 'bogus' not in data['defaults']
    assert data['defaults']['audio_langs'] == MOD.DEFAULT_PREFS['audio_langs']
    assert data['shows'] == {}
    assert data['version'] == 1


@pytest.mark.parametrize('body', ['{not json', '[]'])
def test_unreadable_prefs_fall_back_to_defaults_with_a_log_line(prefs_file, body, caplog):
    prefs_file.write_text(body, encoding='utf-8')
    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        data = MOD.load_prefs()
    assert data['defaults'] == dict(MOD.DEFAULT_PREFS)
    assert data['shows'] == {}
    assert 'prefs unreadable' in caplog.text


def test_a_save_that_cannot_be_written_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(MOD, 'PREFS_PATH', str(tmp_path / 'no-such-dir' / 'prefs.json'))
    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        MOD.save_prefs({'version': 1})
    assert 'prefs save failed' in caplog.text


# ── keys and names ────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('name', 'expected'),
    [
        ('That Time I Got Reincarnated as a Slime S01', 'that time i got reincarnated as a slime s01'),
        ('  Dune:  Part Two (2024) ', 'dune part two 2024'),
        ('', ''),
        (None, ''),
    ],
)
def test_show_key_collapses_a_title(name, expected):
    assert MOD.show_key(name) == expected


@pytest.mark.parametrize(
    ('item', 'names', 'expected'),
    [
        ({'series': 'Slime', 'title': 'E01'}, None, 'slime'),
        ({'title': 'Dune'}, None, 'dune'),
        ({'filename': 'S01E14-Title.mkv'}, None, 's01e14 title mkv'),
        ({}, None, ''),
        ({'folder': '/m/01. Season 1', 'series': 'Season 1'}, {'/m/01. Season 1': 'Slime'}, 'slime'),
        ({'folder': '/m/other', 'series': 'Season 1'}, {'/m/01': 'Slime'}, 'season 1'),
        ({'series': 'Season 1'}, {}, 'season 1'),
    ],
)
def test_item_show_key_follows_the_displayed_name(item, names, expected):
    assert MOD.item_show_key(item, names) == expected


@pytest.mark.parametrize(
    ('item', 'names', 'expected'),
    [
        ({'folder': '/m/f', 'series': 'Season 1'}, {'/m/f': 'Slime'}, 'Slime'),
        ({'folder': '/m/f', 'series': 'Season 1'}, {'/m/g': 'Slime'}, 'Season 1'),
        ({'title': 'Dune'}, None, 'Dune'),
        ({}, {'/m/f': 'Slime'}, ''),
    ],
)
def test_display_series_prefers_the_stored_folder_name(item, names, expected):
    assert MOD.display_series(item, names) == expected


# ── _coerce_pref / update_prefs ───────────────────────────────────────────────
@pytest.mark.parametrize(
    ('key', 'value', 'expected'),
    [
        ('auto_skip_outro', 0, False),
        ('auto_skip_outro', 'yes', True),
        ('intro_seconds', '45', 45.0),
        ('intro_seconds', -5, 0.0),
        ('intro_seconds', 'nope', None),
        ('intro_seconds', None, None),
        ('sub_langs', ('EN', ' nl ', ''), ['en', 'nl']),
        ('sub_langs', 'en', None),
        ('nope', 1, None),
    ],
)
def test_coerce_pref_keeps_the_default_shape(key, value, expected):
    assert MOD._coerce_pref(key, value) == expected


def test_coerce_pref_caps_a_list_at_24_entries():
    assert len(MOD._coerce_pref('sub_langs', [f'l{i}' for i in range(40)])) == 24


def test_update_prefs_writes_the_global_defaults(prefs_file):
    out = MOD.update_prefs({'sub_langs': ['NL', 'en'], 'intro_seconds': 42, 'junk': 1})
    assert out['defaults']['sub_langs'] == ['nl', 'en']
    assert out['defaults']['intro_seconds'] == 42.0
    assert 'junk' not in out['defaults']
    assert json.loads(prefs_file.read_text(encoding='utf-8'))['defaults']['intro_seconds'] == 42.0
    assert MOD.load_prefs()['defaults']['sub_langs'] == ['nl', 'en']


def test_update_prefs_per_show_then_clears_the_override():
    out = MOD.update_prefs({'intro_end': 91.5, 'bad_float': 1}, show='Slime S01')
    assert out['shows']['slime s01'] == {'intro_end': 91.5}
    # A value that cannot be coerced is dropped, leaving the override untouched.
    out = MOD.update_prefs({'intro_end': 'later'}, show='Slime S01')
    assert out['shows']['slime s01'] == {'intro_end': 91.5}
    # None means "stop overriding", and an emptied show drops out entirely.
    out = MOD.update_prefs({'intro_end': None}, show='slime  s01')
    assert 'slime s01' not in out['shows']


def test_update_prefs_with_an_empty_patch_keeps_the_file_loadable():
    MOD.update_prefs({})
    assert MOD.update_prefs(None)['defaults'] == dict(MOD.DEFAULT_PREFS)


def test_prefs_for_layers_a_shows_overrides_over_the_defaults():
    MOD.update_prefs({'sub_langs': ['nl']})
    MOD.update_prefs({'intro_end': 90.0, 'auto_skip_outro': False}, show='Slime')
    eff = MOD.prefs_for({'series': 'Slime'})
    assert eff['sub_langs'] == ['nl']
    assert eff['intro_end'] == 90.0
    assert eff['auto_skip_outro'] is False
    assert eff['_show'] == 'slime'
    assert eff['_overrides'] == ['auto_skip_outro', 'intro_end']
    bare = MOD.prefs_for({'series': 'Dune'})
    assert bare['_overrides'] == []
    assert bare['_show'] == 'dune'


# ── scoring helpers ───────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('text', 'keywords', 'expected'),
    [
        ('Dialogue [Asakura]', ['asakura', 'dialogue'], 0),
        ('Dialogue', ['asakura', 'dialogue'], 1),
        ('Signs & Songs', ['asakura', 'dialogue'], 2),
        (None, ['x'], 1),
        ('anything', [], 0),
        ('anything', None, 0),
        ('anything', ['', 'any'], 1),
    ],
)
def test_kw_score_is_the_index_of_the_first_hit(text, keywords, expected):
    assert MOD._kw_score(text, keywords) == expected


@pytest.mark.parametrize(
    ('lang', 'order', 'expected'),
    [
        ('ja', ['ja', 'en'], 0),
        ('en', ['ja', 'en'], 1),
        ('', ['ja', 'en'], 2),
        ('de', ['ja', 'en'], 3),
        ('de', [], 1),
        ('', None, 0),
    ],
)
def test_lang_score_orders_listed_then_untagged_then_the_rest(lang, order, expected):
    assert MOD._lang_score(lang, order) == expected


# ── subtitle discovery ────────────────────────────────────────────────────────
def _video_tree(tmp_path):
    root = tmp_path / 'Thunderbolts (2025)'
    root.mkdir()
    video = root / 'Thunderbolts.2025.1080p.WEB-DL.mkv'
    video.write_bytes(b'\0' * 16)
    (root / 'Thunderbolts.2025.1080p.WEB-DL.srt').write_text('forced-up-top' * 10, encoding='utf-8')
    (root / 'Thunderbolts.forced.nl.srt').write_text('x', encoding='utf-8')
    (root / 'notes.txt').write_text('ignored', encoding='utf-8')
    subs = root / 'Subs'
    subs.mkdir()
    (subs / 'English (SDH).eng.srt').write_text('y' * 4096, encoding='utf-8')
    (subs / 'cover.jpg').write_bytes(b'\0')
    (root / 'Extras').mkdir()
    return str(video)


def test_external_subs_finds_sidecars_and_a_subs_folder(tmp_path):
    found = MOD._external_subs(_video_tree(tmp_path))
    by_label = {s['label']: s for s in found}
    assert set(by_label) == {'English', 'Dutch (Forced)', 'English (SDH)'}
    assert all(s['kind'] == 'external' and s['text'] and s['id'].startswith('x') for s in found)
    # The sidecar matching the video stem carries no language of its own.
    assert by_label['English']['lang'] == 'en'
    assert by_label['Dutch (Forced)']['forced'] is True
    assert by_label['English (SDH)']['sdh'] is True
    assert by_label['English (SDH)']['size'] == 4096


def test_external_subs_of_a_missing_directory_is_empty(tmp_path):
    assert MOD._external_subs(str(tmp_path / 'gone' / 'film.mkv')) == []


def test_external_subs_survives_an_unreadable_subs_folder_and_a_lost_size(tmp_path, monkeypatch):
    video = _video_tree(tmp_path)
    real_listdir, real_getsize = os.listdir, os.path.getsize

    def listdir(path, *a, **kw):
        if str(path).endswith('Subs'):
            raise PermissionError('nope')
        return real_listdir(path, *a, **kw)

    def getsize(path, *a, **kw):
        if str(path).endswith('.srt'):
            raise OSError('vanished')
        return real_getsize(path, *a, **kw)

    monkeypatch.setattr(os, 'listdir', listdir)
    monkeypatch.setattr(os.path, 'getsize', getsize)
    found = MOD._external_subs(video)
    assert {s['label'] for s in found} == {'English', 'Dutch (Forced)'}
    assert all(s['size'] == 0 for s in found)


def test_external_subs_of_a_nameless_video_keeps_the_sidecar_stem(tmp_path):
    root = tmp_path / 'loose'
    root.mkdir()
    (root / 'odd.srt').write_text('odd', encoding='utf-8')
    found = MOD._external_subs(str(root / '.mkv'))
    assert [s['label'] for s in found] == ['odd']
    assert found[0]['lang'] == ''


def test_embedded_subs_labels_every_track_shape():
    info = {
        'subs': [
            {'order': 0, 'index': 2, 'codec': 'subrip', 'lang': 'en', 'title': 'Dialogue'},
            {'order': 1, 'index': 3, 'codec': 'ass', 'lang': 'en', 'title': 'SDH', 'hearing_impaired': 1},
            {'order': 2, 'index': 4, 'codec': 'hdmv_pgs_subtitle', 'lang': 'nl', 'forced': True},
            {'order': 3, 'index': 5, 'codec': 'weird_codec', 'lang': '', 'title': ''},
            {'order': 4, 'index': 6, 'codec': 'subrip', 'lang': 'en', 'title': 'Show.S01E01.1080p.WEB-DL.x264'},
            {'order': 5, 'index': 7, 'codec': 'subrip', 'lang': 'fr', 'title': 'q' * 41},
        ]
    }
    out = MOD._embedded_subs(info)
    assert [s['label'] for s in out] == [
        'English — Dialogue',
        'English — SDH',
        'Dutch (Forced) [burn-in]',
        'Track 4',
        'English',
        'French',
    ]
    assert [s['id'] for s in out] == ['e0', 'e1', 'e2', 'e3', 'e4', 'e5']
    assert [s['text'] for s in out] == [True, True, False, True, True, True]
    assert out[1]['sdh'] is True
    assert out[2]['forced'] is True and out[2]['abs_index'] == 4
    assert all(s['kind'] == 'embedded' for s in out)


def test_embedded_subs_of_nothing_is_empty():
    assert MOD._embedded_subs({}) == []
    assert MOD._embedded_subs({'subs': None}) == []


# ── pick_default_sub ──────────────────────────────────────────────────────────
def test_pick_default_sub_prefers_the_full_dialogue_track_over_signs():
    subs = [
        {'id': 'e0', 'kind': 'embedded', 'lang': 'en', 'label': 'English — Signs & Songs', 'text': True},
        {'id': 'e1', 'kind': 'embedded', 'lang': 'en', 'label': 'English — Dialogue', 'text': True},
        {'id': 'e2', 'kind': 'embedded', 'lang': 'nl', 'label': 'Dutch', 'text': True},
    ]
    assert MOD.pick_default_sub(subs) == 'e1'


def test_pick_default_sub_uses_the_shows_language_and_keyword_order():
    subs = [
        {'id': 'e0', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True},
        {'id': 'e1', 'kind': 'embedded', 'lang': 'nl', 'label': 'Dutch', 'text': True},
    ]
    assert MOD.pick_default_sub(subs, {'sub_langs': ['nl'], 'sub_prefer': [], 'sub_avoid': []}) == 'e1'


def test_pick_default_sub_lets_a_wanted_keyword_cancel_the_avoid_list():
    subs = [
        {'id': 'e0', 'kind': 'embedded', 'lang': 'en', 'label': 'English — Signs', 'text': True},
        {'id': 'e1', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True},
    ]
    pref = {'sub_langs': ['en'], 'sub_prefer': ['signs'], 'sub_avoid': ['signs']}
    assert MOD.pick_default_sub(subs, pref) == 'e0'


def test_pick_default_sub_breaks_a_tie_on_external_then_size():
    subs = [
        {'id': 'e9', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True},
        {'id': 'x1', 'kind': 'external', 'lang': 'en', 'label': 'Sub', 'size': 2048, 'text': True},
        {'id': 'x2', 'kind': 'external', 'lang': 'en', 'label': 'Sub', 'size': 40960, 'text': True},
    ]
    assert MOD.pick_default_sub(subs) == 'x2'


def test_pick_default_sub_pushes_forced_and_sdh_behind_a_plain_track():
    subs = [
        {'id': 'e0', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True, 'forced': True},
        {'id': 'e1', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True, 'sdh': True},
        {'id': 'e2', 'kind': 'embedded', 'lang': 'en', 'label': 'English', 'text': True},
    ]
    assert MOD.pick_default_sub(subs) == 'e2'


def test_pick_default_sub_falls_back_to_an_image_track_and_handles_nothing():
    assert MOD.pick_default_sub([]) == ''
    burned = [{'id': 'e0', 'kind': 'embedded', 'lang': 'en', 'label': 'English [burn-in]', 'text': False}]
    assert MOD.pick_default_sub(burned) == 'e0'


# ── pick_default_audio ────────────────────────────────────────────────────────
def test_pick_default_audio_is_japanese_first_on_a_dual_audio_release():
    tracks = [
        {'lang': 'en', 'title': 'English', 'channels': 6, 'default': True},
        {'lang': 'ja', 'title': 'Japanese', 'channels': 2},
    ]
    assert MOD.pick_default_audio(tracks) == 1


def test_pick_default_audio_pushes_commentary_to_the_back():
    tracks = [
        {'lang': 'en', 'title': 'Director Commentary', 'channels': 6},
        {'lang': 'en', 'title': 'Feature', 'channels': 2},
    ]
    assert MOD.pick_default_audio(tracks, {'audio_langs': ['en'], 'audio_avoid': ['commentary']}) == 1


def test_pick_default_audio_uses_default_flag_then_channels_then_order():
    tracks = [
        {'lang': 'en', 'label': '', 'channels': 2},
        {'lang': 'en', 'label': '', 'channels': 8},
        {'lang': 'en', 'label': '', 'channels': 2, 'default': True},
    ]
    assert MOD.pick_default_audio(tracks) == 2
    assert MOD.pick_default_audio(tracks[:2]) == 1
    assert MOD.pick_default_audio([{'lang': 'en'}, {'lang': 'en'}]) == 0


def test_pick_default_audio_of_nothing_is_zero():
    assert MOD.pick_default_audio([]) == 0


# ── detect_marks ──────────────────────────────────────────────────────────────
def _chapters(*triples):
    return [{'title': t, 'start': s, 'end': e} for t, s, e in triples]


def test_detect_marks_reads_the_chapter_list_of_a_real_episode():
    item = {
        'kind': 'episode',
        'series': 'Slime',
        'duration': 1440.0,
        'chapters': _chapters(
            ('Intro', 0, 31),
            ('OP', 31, 121),
            ('', 121, 122),
            ('Part A', 122, 700),
            ('Part B', 700, 1326),
            ('ED', 1326, 1416),
            ('PV', 1416, 1422),
        ),
    }
    marks = MOD.detect_marks(item)
    assert marks['intro'] == {'start': 31.0, 'end': 121.0, 'source': 'chapter', 'label': 'OP'}
    assert marks['outro'] == {'start': 1326.0, 'source': 'chapter', 'label': 'ED'}
    assert marks['auto_skip_outro'] is True
    assert marks['button_seconds'] == 10.0
    assert marks['show'] == 'slime'
    assert marks['overrides'] == []


def test_detect_marks_refuses_a_six_minute_intro_and_a_closing_opening():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': _chapters(
            ('Intro', 0, 360),
            ('Part A', 360, 700),
            ('Part B', 700, 1326),
            ('OP', 1326, 1416),
            ('PV', 1416, 1422),
        ),
    }
    marks = MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS))
    assert marks['intro'] is None
    assert marks['outro'] == {'start': 1326.0, 'source': 'chapter', 'label': 'OP'}


def test_detect_marks_ignores_a_chapter_with_an_unparsable_time():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': [
            {'title': 'OP', 'start': 'early', 'end': 'late'},
            {'title': 'Part A', 'start': 121, 'end': 1300},
            {'title': 'ED', 'start': 'bad', 'end': 'bad'},
        ],
    }
    marks = MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS))
    assert marks['intro'] is None and marks['outro'] is None


def test_detect_marks_stops_at_the_story_that_follows_an_ending():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': _chapters(('ED', 100, 190), ('Extra', 190, 1430)),
    }
    assert MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS))['outro'] is None


def test_detect_marks_drops_a_tail_that_starts_too_early():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': _chapters(('Part A', 0, 100), ('Credits', 100, 1440)),
    }
    assert MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS))['outro'] is None


def test_detect_marks_lets_a_typed_setting_beat_the_chapters():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': _chapters(('OP', 31, 121), ('Part A', 121, 1440)),
    }
    pref = dict(MOD.DEFAULT_PREFS, intro_start=5.0, intro_end=95.0)
    assert MOD.detect_marks(item, pref)['intro'] == {
        'start': 5.0,
        'end': 95.0,
        'source': 'setting',
        'label': '',
    }
    show = dict(pref, _overrides=['intro_end'], _show='slime')
    marks = MOD.detect_marks(item, show)
    assert marks['intro']['source'] == 'show'
    assert marks['show'] == 'slime' and marks['overrides'] == ['intro_end']


def test_detect_marks_ignores_an_out_of_range_typed_setting():
    item = {
        'kind': 'episode',
        'duration': 1440.0,
        'chapters': _chapters(('OP', 31, 121), ('Part A', 121, 1440)),
    }
    pref = dict(MOD.DEFAULT_PREFS, intro_start=5.0, intro_end=1200.0)
    assert MOD.detect_marks(item, pref)['intro']['source'] == 'chapter'


def test_detect_marks_applies_a_per_show_outro_lead():
    item = {'kind': 'episode', 'duration': 1000.0, 'chapters': _chapters(('Part A', 0, 1000))}
    pref = dict(MOD.DEFAULT_PREFS, outro_lead=120.0, _overrides=['outro_lead'])
    assert MOD.detect_marks(item, pref)['outro'] == {'start': 880.0, 'source': 'show', 'label': ''}


def test_detect_marks_guesses_both_ends_of_a_chapterless_episode():
    item = {'kind': 'episode', 'duration': 1200.0, 'chapters': []}
    marks = MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS))
    assert marks['intro'] == {'start': 0.0, 'end': 90.0, 'source': 'default', 'label': ''}
    assert marks['outro'] == {'start': 1110.0, 'source': 'default', 'label': ''}
    assert marks['auto_skip_outro'] is True


def test_detect_marks_caps_the_guess_at_half_the_runtime():
    item = {'kind': 'episode', 'duration': 320.0, 'chapters': []}
    assert MOD.detect_marks(item, dict(MOD.DEFAULT_PREFS, intro_seconds=600.0))['intro']['end'] == 160.0


def test_detect_marks_guesses_nothing_for_a_movie_or_a_zero_length_intro():
    movie = {'kind': 'movie', 'duration': 7200.0, 'chapters': []}
    marks = MOD.detect_marks(movie, dict(MOD.DEFAULT_PREFS))
    assert marks == {
        'intro': None,
        'outro': None,
        'auto_skip_outro': False,
        'button_seconds': 10.0,
        'show': '',
        'overrides': [],
    }
    short = {'kind': 'episode', 'duration': 400.0, 'chapters': []}
    quiet = MOD.detect_marks(short, dict(MOD.DEFAULT_PREFS, intro_seconds=0.0, outro_lead=0.0))
    assert quiet['intro'] is None and quiet['outro'] is None


def test_detect_marks_without_a_pref_reads_the_stored_show_overrides():
    MOD.update_prefs({'auto_skip_outro': False, 'intro_button_seconds': 4.0}, show='Slime')
    item = {'kind': 'episode', 'series': 'Slime', 'duration': 1200.0, 'chapters': []}
    marks = MOD.detect_marks(item)
    assert marks['auto_skip_outro'] is False
    assert marks['button_seconds'] == 4.0
    assert marks['overrides'] == ['auto_skip_outro', 'intro_button_seconds']


# ── chapters_of ───────────────────────────────────────────────────────────────
def test_chapters_of_parses_an_ffprobe_payload(monkeypatch):
    payload = json.dumps(
        {
            'chapters': [
                {'start_time': '31.0', 'end_time': '121.0', 'tags': {'title': 'OP'}},
                {'start_time': '0.0', 'end_time': '31.0', 'tags': {}},
            ]
        }
    )
    seen = {}

    def fake_run(cmd, timeout=120):
        seen['cmd'] = cmd
        seen['timeout'] = timeout
        return 0, payload, ''

    monkeypatch.setattr(MOD, '_run', fake_run)
    assert MOD.chapters_of('/m/e01.mkv') == [
        {'start': 0.0, 'end': 31.0, 'title': ''},
        {'start': 31.0, 'end': 121.0, 'title': 'OP'},
    ]
    assert seen['cmd'][0] == MOD.FFPROBE
    assert seen['cmd'][-1] == '/m/e01.mkv'
    assert seen['timeout'] == 60


@pytest.mark.parametrize(('rc', 'out'), [(1, '{}'), (0, '  '), (0, '{not json')])
def test_chapters_of_a_failed_or_unparsable_probe_is_empty(monkeypatch, rc, out):
    monkeypatch.setattr(MOD, '_run', lambda cmd, timeout=120: (rc, out, 'err'))
    assert MOD.chapters_of('/m/e01.mkv') == []
