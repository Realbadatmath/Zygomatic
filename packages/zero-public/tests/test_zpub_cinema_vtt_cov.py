# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_zero.zpub_cinema.vtt — pure text in, exact text out."""

import os

import pytest

from zyg_zero.zpub_cinema import vtt as V


# ── _read_text ────────────────────────────────────────────────────────────────
def test_read_text_missing_file_is_empty_never_raises(tmp_path):
    assert V._read_text(str(tmp_path / 'nope.srt')) == ''


def test_read_text_strips_the_utf8_bom(tmp_path):
    p = tmp_path / 'bom.srt'
    p.write_bytes(b'\xef\xbb\xbfHello')
    assert V._read_text(str(p)) == 'Hello'


def test_read_text_falls_back_to_cp1252_for_legacy_bytes(tmp_path):
    p = tmp_path / 'legacy.srt'
    p.write_bytes(b'caf\xe9 \x93quoted\x94')
    assert V._read_text(str(p)) == 'café \u201cquoted\u201d'


# ── srt_to_vtt ────────────────────────────────────────────────────────────────
def test_srt_to_vtt_converts_crlf_index_coords_and_ass_overrides():
    srt = (
        '1\r\n'
        '00:00:01,000 --> 00:00:02,500 X1:10 Y1:20\r\n'
        '{\\an8}Hello <i>there</i>\r\n'
        '\r\n'
        '2\r\n'
        '0:0:3,5 --> 0:0:4,50\r\n'
        'Second\r\n'
    )
    assert V.srt_to_vtt(srt) == (
        'WEBVTT\n\n00:00:01.000 --> 00:00:02.500\nHello <i>there</i>\n\n00:00:03.500 --> 00:00:04.500\nSecond\n'
    )


def test_srt_to_vtt_keeps_a_two_line_cue_without_an_index():
    srt = '00:01:02,003 --> 00:01:04,000\nfirst line\nsecond line\n'
    assert V.srt_to_vtt(srt) == ('WEBVTT\n\n00:01:02.003 --> 00:01:04.000\nfirst line\nsecond line\n')


def test_srt_to_vtt_old_mac_cr_only_newlines():
    assert V.srt_to_vtt('1\r00:00:00,500 --> 00:00:01,500\rMac\r') == ('WEBVTT\n\n00:00:00.500 --> 00:00:01.500\nMac\n')


@pytest.mark.parametrize(
    'srt',
    [
        pytest.param('', id='empty'),
        pytest.param('\n\n   \n\n', id='blank-blocks-only'),
        pytest.param('just a caption line\n\nand another', id='no-arrow'),
        pytest.param('7\n', id='lonely-index'),
        pytest.param('00:00:01,000 --> 00:00:02,000 --> 00:00:03,000\ntext', id='two-arrows'),
    ],
)
def test_srt_to_vtt_skips_everything_that_is_not_a_cue(srt):
    assert V.srt_to_vtt(srt) == 'WEBVTT\n'


# ── timestamps ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    ('stamp', 'secs'),
    [
        ('01:02:03.500', 3723.5),
        ('00:00:00.000', 0.0),
        ('02:03.500', 123.5),
        ('bad', 0.0),
        ('a:b:c', 0.0),
        ('x:y', 0.0),
    ],
)
def test_vtt_seconds_parses_or_returns_zero(stamp, secs):
    assert V._vtt_seconds(stamp) == secs


@pytest.mark.parametrize(
    ('sec', 'stamp'),
    [
        (0.0, '00:00:00.000'),
        (-5.0, '00:00:00.000'),
        (3723.456, '01:02:03.456'),
        (59.9999, '00:00:60.000'),
    ],
)
def test_vtt_stamp_formats_and_clamps_at_zero(sec, stamp):
    assert V._vtt_stamp(sec) == stamp


# ── shift_vtt ─────────────────────────────────────────────────────────────────
_SHIFT_SRC = (
    'WEBVTT\n'
    '\n'
    'cue1\n'
    '00:00:01.000 --> 00:00:02.000\n'
    'Gone\n'
    '\n'
    '00:00:10.000 --> 00:00:12.000 line:90%\n'
    'Kept\n'
    '\n'
    '00:00:04.000 --> 00:00:06.000\n'
    'Partly\n'
)


def test_shift_vtt_without_an_offset_is_the_identity():
    assert V.shift_vtt(_SHIFT_SRC, 0) is _SHIFT_SRC
    assert V.shift_vtt(_SHIFT_SRC, 0.0) is _SHIFT_SRC


def test_shift_vtt_drops_past_cues_with_their_identifier_and_body():
    assert V.shift_vtt(_SHIFT_SRC, 5.0) == (
        'WEBVTT\n\n00:00:05.000 --> 00:00:07.000 line:90%\nKept\n\n00:00:00.000 --> 00:00:01.000\nPartly\n'
    )


def test_shift_vtt_drops_a_leading_cue_that_has_no_identifier():
    src = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nGone\n\n00:00:09.000 --> 00:00:11.000\nKept\n'
    assert V.shift_vtt(src, 8.0) == 'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nKept\n'


def test_shift_vtt_accepts_a_negative_offset_as_a_delay():
    assert V.shift_vtt(_SHIFT_SRC, -2.0) == (
        'WEBVTT\n'
        '\n'
        'cue1\n'
        '00:00:03.000 --> 00:00:04.000\n'
        'Gone\n'
        '\n'
        '00:00:12.000 --> 00:00:14.000 line:90%\n'
        'Kept\n'
        '\n'
        '00:00:06.000 --> 00:00:08.000\n'
        'Partly\n'
    )


def test_shift_vtt_handles_mm_ss_stamps_and_a_cue_ending_exactly_at_zero():
    src = 'WEBVTT\n\n00:03.000 --> 00:05.000\nDrop\n\n00:06.000 --> 00:08.000\nShift\n'
    assert V.shift_vtt(src, 5.0) == 'WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nShift\n'


# ── _vtt_blocks ───────────────────────────────────────────────────────────────
def test_vtt_blocks_keeps_the_header_and_drops_notes_ids_and_junk():
    src = (
        'WEBVTT - the film\n'
        '\n'
        'NOTE a comment block\n'
        '\n'
        'an-id\n'
        '00:00:01.000 --> 00:00:02.000 align:start\n'
        'Body\n'
        'more\n'
        '\n'
        '\n'
        'badtime --> nonsense\n'
    )
    header, cues = V._vtt_blocks(src)
    assert header == 'WEBVTT - the film'
    assert cues == [[1.0, 2.0, ' align:start', 'Body\nmore']]


def test_vtt_blocks_defaults_the_header_when_the_file_has_none():
    header, cues = V._vtt_blocks('00:00:01.000 --> 00:00:02.000\nHi\n')
    assert (header, cues) == ('WEBVTT', [[1.0, 2.0, '', 'Hi']])


# ── tidy_vtt ──────────────────────────────────────────────────────────────────
def test_tidy_vtt_returns_the_input_untouched_when_there_are_no_cues():
    assert V.tidy_vtt('no cues at all\n') == 'no cues at all\n'


def test_tidy_vtt_merges_duplicates_drops_debris_and_caps_simultaneous_cues():
    src = (
        'WEBVTT\n'
        '\n'
        '00:00:01.000 --> 00:00:03.000\n'
        '{=112}Hello there\n'
        '\n'
        '00:00:03.100 --> 00:00:05.000\n'
        'Hello there\n'
        '\n'
        '00:00:06.000 --> 00:00:07.000\n'
        'A\n'
        '\n'
        '00:00:08.000 --> 00:00:08.000\n'
        'Zero length\n'
        '\n'
        '00:00:09.000 --> 00:00:10.000\n'
        'm 0 0 l 100 0 100 100 0 100\n'
        '\n'
        '00:00:09.000 --> 00:00:10.000\n'
        '200,000?\n'
        '\n'
        '00:00:20.000 --> 00:00:30.000\n'
        'The full sentence of dialogue\n'
        '\n'
        '00:00:21.000 --> 00:00:22.000 align:start\n'
        'Sign one\n'
        '\n'
        '00:00:21.000 --> 00:00:22.500\n'
        'Sign two\n'
        '\n'
        '00:00:21.000 --> 00:00:23.000\n'
        'Sign three\n'
    )
    assert V.tidy_vtt(src) == (
        'WEBVTT\n'
        '\n'
        '00:00:01.000 --> 00:00:05.000\n'
        'Hello there\n'
        '\n'
        '00:00:09.000 --> 00:00:10.000\n'
        '200,000?\n'
        '\n'
        '00:00:20.000 --> 00:00:30.000\n'
        'The full sentence of dialogue\n'
        '\n'
        '00:00:21.000 --> 00:00:22.000 align:start\n'
        'Sign one\n'
        '\n'
        '00:00:21.000 --> 00:00:23.000\n'
        'Sign three\n'
    )


def test_tidy_vtt_counts_visible_text_not_markup_and_keeps_tags():
    src = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<i>o</i>\n\n00:00:03.000 --> 00:00:04.000\n<b>kept line</b>\n'
    assert V.tidy_vtt(src) == 'WEBVTT\n\n00:00:03.000 --> 00:00:04.000\n<b>kept line</b>\n'


def test_tidy_vtt_drops_every_cue_and_still_emits_a_header():
    src = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n.\n'
    assert V.tidy_vtt(src) == 'WEBVTT\n'


# ── _ffmpeg_to_vtt ────────────────────────────────────────────────────────────
def _fake_run(dest: str, payload: bytes | None, rc: int = 0, err: str = ''):
    """A _run stand-in that writes ``payload`` to ``dest`` and returns ``rc``."""

    def _run(cmd, timeout=120):
        if payload is not None:
            with open(dest, 'wb') as f:
                f.write(payload)
        return rc, '', err

    return _run


def test_ffmpeg_to_vtt_is_true_when_a_real_file_is_produced(tmp_path, monkeypatch):
    dest = str(tmp_path / 'out.vtt')
    monkeypatch.setattr(V, '_run', _fake_run(dest, b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nHi\n'))
    assert V._ffmpeg_to_vtt(['-i', 'movie.mkv'], dest) is True


@pytest.mark.parametrize(
    ('payload', 'rc'),
    [
        pytest.param(None, 0, id='no-file'),
        pytest.param(b'tiny', 0, id='too-small'),
        pytest.param(b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n', 1, id='nonzero-exit'),
    ],
)
def test_ffmpeg_to_vtt_is_false_and_logs_on_failure(tmp_path, monkeypatch, caplog, payload, rc):
    import logging

    dest = str(tmp_path / 'out.vtt')
    monkeypatch.setattr(V, '_run', _fake_run(dest, payload, rc=rc, err='stream not found'))
    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        assert V._ffmpeg_to_vtt(['-i', 'movie.mkv'], dest) is False
    assert 'subtitle extract failed' in caplog.text


# ── subtitle_vtt ──────────────────────────────────────────────────────────────
@pytest.fixture
def subs_dir(tmp_path, monkeypatch):
    """Point the module's cache directory at tmp_path."""
    d = tmp_path / 'subs'
    d.mkdir()
    monkeypatch.setattr(V, 'SUB_DIR', str(d))
    return d


def _item(tmp_path, **sub) -> dict:
    sub.setdefault('id', 's0')
    sub.setdefault('text', True)
    return {'id': 'film1', 'path': str(tmp_path / 'film.mkv'), 'subs': [sub]}


def _cached(subs_dir, item_id='film1', sub_id='s0') -> str:
    return str(subs_dir / f'{item_id}_{sub_id}.v{V.SUB_CACHE_VER}.vtt')


@pytest.mark.parametrize(
    'item',
    [
        pytest.param({'id': 'x', 'subs': None}, id='subs-none'),
        pytest.param({'id': 'x'}, id='subs-missing'),
        pytest.param({'id': 'x', 'subs': [{'id': 'other', 'text': True}]}, id='other-id'),
        pytest.param({'id': 'x', 'subs': [{'id': 's0', 'text': False}]}, id='not-text'),
    ],
)
def test_subtitle_vtt_returns_none_without_a_usable_text_track(subs_dir, item):
    assert V.subtitle_vtt(item, 's0') is None


def test_subtitle_vtt_reuses_a_big_enough_cached_file(subs_dir, tmp_path):
    dest = _cached(subs_dir)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nCached\n')
    assert V.subtitle_vtt(_item(tmp_path, kind='embedded'), 's0') == dest


def test_subtitle_vtt_ignores_a_truncated_cache_and_rebuilds(subs_dir, tmp_path, monkeypatch):
    dest = _cached(subs_dir)
    with open(dest, 'w', encoding='utf-8') as f:
        f.write('WEBVTT\n')
    monkeypatch.setattr(V, '_run', _fake_run(dest, b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFresh line\n'))
    assert V.subtitle_vtt(_item(tmp_path, kind='embedded', stream=2), 's0') == dest
    assert 'Fresh line' in open(dest, encoding='utf-8').read()


def test_subtitle_vtt_copies_an_external_vtt_and_tidies_it(subs_dir, tmp_path):
    src = tmp_path / 'ext.vtt'
    src.write_text(
        'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n{=9}Real dialogue\n\n00:00:03.000 --> 00:00:04.000\nx\n',
        encoding='utf-8',
    )
    dest = V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0')
    assert dest == _cached(subs_dir)
    assert open(dest, encoding='utf-8').read() == ('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nReal dialogue\n')


def test_subtitle_vtt_leaves_an_already_tidy_copy_byte_for_byte(subs_dir, tmp_path):
    body = 'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nTidy already\n'
    src = tmp_path / 'ext.vtt'
    src.write_text(body, encoding='utf-8')
    assert V.tidy_vtt(body) == body  # so _finish must not rewrite the copy
    dest = V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0')
    assert open(dest, encoding='utf-8').read() == body


def test_subtitle_vtt_converts_an_external_srt(subs_dir, tmp_path):
    src = tmp_path / 'ext.srt'
    src.write_bytes(b'1\n00:00:01,000 --> 00:00:02,000\nFrom SubRip\n')
    dest = V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0')
    assert dest == _cached(subs_dir)
    assert open(dest, encoding='utf-8').read() == ('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nFrom SubRip\n')


def test_subtitle_vtt_returns_none_when_an_srt_holds_no_cues(subs_dir, tmp_path):
    src = tmp_path / 'empty.srt'
    src.write_text('not a subtitle at all\n', encoding='utf-8')
    assert V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0') is None


def test_subtitle_vtt_returns_none_when_the_external_file_is_gone(subs_dir, tmp_path):
    item = _item(tmp_path, kind='external', path=str(tmp_path / 'absent.srt'))
    assert V.subtitle_vtt(item, 's0') is None
    assert V.subtitle_vtt(_item(tmp_path, kind='external'), 's0') is None


@pytest.mark.parametrize('ext', ['.vtt', '.srt'])
def test_subtitle_vtt_returns_none_when_the_cache_dir_is_unwritable(tmp_path, monkeypatch, ext):
    monkeypatch.setattr(V, 'SUB_DIR', str(tmp_path / 'no-such-dir'))
    src = tmp_path / f'ext{ext}'
    src.write_text('WEBVTT\n\n00:00:01,000 --> 00:00:02,000\nSome dialogue\n', encoding='utf-8')
    assert V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0') is None


def test_subtitle_vtt_hands_an_ass_track_to_ffmpeg(subs_dir, tmp_path, monkeypatch):
    src = tmp_path / 'ext.ass'
    src.write_text('[Script Info]\n', encoding='utf-8')
    dest = _cached(subs_dir)
    monkeypatch.setattr(V, '_run', _fake_run(dest, b'WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nStyled line\n'))
    assert V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0') == dest


def test_subtitle_vtt_returns_none_when_ffmpeg_fails(subs_dir, tmp_path, monkeypatch):
    src = tmp_path / 'ext.ssa'
    src.write_text('[Script Info]\n', encoding='utf-8')
    monkeypatch.setattr(V, '_run', _fake_run(str(subs_dir / 'unused'), None, rc=1, err='boom'))
    assert V.subtitle_vtt(_item(tmp_path, kind='external', path=str(src)), 's0') is None
    assert V.subtitle_vtt(_item(tmp_path, kind='embedded'), 's0') is None


def test_subtitle_vtt_survives_a_read_only_cache_file(subs_dir, tmp_path, monkeypatch, caplog):
    import logging

    dest = _cached(subs_dir)

    def _run(cmd, timeout=120):
        with open(dest, 'w', encoding='utf-8') as f:
            f.write('WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n{=1}Needs tidying\n')
        os.chmod(dest, 0o444)
        return 0, '', ''

    monkeypatch.setattr(V, '_run', _run)
    with caplog.at_level(logging.INFO, logger='zyg_zero.zpub_cinema'):
        assert V.subtitle_vtt(_item(tmp_path, kind='embedded'), 's0') == dest
    assert 'vtt tidy failed' in caplog.text
    os.chmod(dest, 0o644)
