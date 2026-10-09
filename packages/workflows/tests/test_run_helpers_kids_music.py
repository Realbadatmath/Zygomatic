# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers `kids_music_service.run.run()` was split into.

Each test pins one decision the 404-line `run()` used to make inline, so the
split cannot quietly change it: which leg ships, when the score render is
allowed to ship at all, where the title comes from when nothing supplies one,
which temporary files a run deletes, and that a shelf record is written once.
No GPU, no network, no service.

Named `..._kids_music` because `tests/test_run_helpers.py` is the same brief's
name for a different `run.py` (the Movement Studio anatomy proof) and that file
is already in modcheck's brand band.
"""

from __future__ import annotations

import json
import os
from importlib import import_module

import pytest

# `from zyg_workflows.kids_music_service import run` would hand back the
# re-exported run() FUNCTION, not the module the helpers live in.
R = import_module('zyg_workflows.kids_music_service.run')


class _Log:
    """A log_fn that keeps its lines, so a test can assert on them."""

    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        self.lines.append(str(msg))


def test_pick_leg_prefers_the_ace_take_when_it_passed_its_gates():
    log = _Log()
    pick, why, leg = R._pick_leg('ace.mp3', 'melody.mp3', {'produced': {'ok': True}}, True, log)
    assert (pick, leg) == ('ace.mp3', 'produced')
    assert why == 'ACE-Step variation passed its gates'
    # The happy path says nothing: only the no-leg branch logs.
    assert log.lines == []


def test_pick_leg_falls_back_to_the_score_render_when_it_is_safe():
    log = _Log()
    pick, why, leg = R._pick_leg('ace.mp3', 'melody.mp3', {'produced': {'ok': False}}, True, log)
    assert (pick, leg) == ('melody.mp3', 'render')
    assert why == 'ACE-Step variation failed its gates — shipping the score render'
    assert log.lines == []

    # Same fallback, but there never was an ACE take: a different sentence.
    _, why_no_ace, leg_no_ace = R._pick_leg(None, 'melody.mp3', {}, True, log)
    assert why_no_ace == 'no ACE-Step variation — shipping the score render'
    assert leg_no_ace == 'render'


def test_pick_leg_ships_nothing_and_says_why_when_neither_leg_is_safe():
    log = _Log()
    pick, why, leg = R._pick_leg('ace.mp3', 'melody.mp3', {'produced': {'ok': False}}, False, log)
    assert pick is None
    assert leg == ''
    assert why == (
        'no shippable leg: the ACE-Step variation failed its gates and the score render did not clear its content gate'
    )
    assert log.lines == [f'deliver: {why}']

    log2 = _Log()
    _, why_bare, _ = R._pick_leg(None, None, {}, False, log2)
    assert why_bare == 'no shippable leg: no ACE-Step variation and no score render'
    assert log2.lines == [f'deliver: {why_bare}']


def _measure(monkeypatch, *, gate_ok, clap, mix_ok, render_mp3='melody.mp3'):
    """Run `_stage_measure_render` with a stubbed `gate_audio`; out: its result."""
    monkeypatch.setattr(
        R,
        'gate_audio',
        lambda *a, **k: {'ok': gate_ok, 'checks': {'clap': clap}, 'warnings': [], 'fails': []},
    )
    sr = R._ScoreRender(midi='melody.mid', render_mp3=render_mp3, mix={'ok': mix_ok})
    return R._stage_measure_render({'seconds': 30.0}, sr, _Log(), lambda _n: None)


@pytest.mark.parametrize(
    ('gate_ok', 'clap', 'mix_ok', 'expected'),
    [
        (True, {'ok': True}, True, True),
        (True, {'ok': None}, True, False),  # CLAP did not run — not shippable
        (True, {}, True, False),  # no CLAP verdict at all
        (False, {'ok': True}, True, False),
        (True, {'ok': True}, False, False),  # the tune is buried
    ],
)
def test_stage_measure_render_only_calls_the_render_shippable_on_a_full_pass(
    monkeypatch, gate_ok, clap, mix_ok, expected
):
    gates, fallback_safe = _measure(monkeypatch, gate_ok=gate_ok, clap=clap, mix_ok=mix_ok)
    assert fallback_safe is expected
    assert gates['render']['mix'] == {'ok': mix_ok}


def test_stage_measure_render_without_a_render_gates_nothing(monkeypatch):
    called = []
    monkeypatch.setattr(R, 'gate_audio', lambda *a, **k: called.append(1))
    sr = R._ScoreRender(midi='melody.mid', render_mp3=None)
    gates, fallback_safe = R._stage_measure_render({}, sr, _Log(), lambda _n: None)
    assert (gates, fallback_safe, called) == ({}, False, [])


def test_stage_lyrics_keeps_operator_lines_and_asks_for_none():
    asked = []
    brief = {'theme': 'the deep sea', 'sung': True, 'lyrics_lines': ['one', 'two']}
    lyric_src, lyric_info = R._stage_lyrics(brief, False, _Log(), asked.append)
    assert lyric_src == 'operator'
    assert lyric_info == {}
    assert asked == []  # no 'Lyrics' section banner — nothing was written
    assert brief['lyrics_lines'] == ['one', 'two']


def test_stage_lyrics_titles_an_untitled_brief_from_its_theme():
    brief = {'theme': 'the deep sea', 'sung': False}
    R._stage_lyrics(brief, False, _Log(), lambda _n: None)
    assert brief['title'] == 'The deep sea'

    # A title the caller supplied is never overwritten.
    titled = {'theme': 'the deep sea', 'sung': False, 'title': 'Down Below'}
    R._stage_lyrics(titled, False, _Log(), lambda _n: None)
    assert titled['title'] == 'Down Below'


def test_stage_lyrics_skips_the_lyric_leg_for_a_cinematic_brief():
    asked = []
    brief = {'theme': 'a chase', 'sung': True}
    lyric_src, _ = R._stage_lyrics(brief, True, _Log(), asked.append)
    assert lyric_src == 'none'
    assert asked == []
    assert 'lyrics_lines' not in brief


def test_sweep_temps_removes_the_working_files_and_keeps_the_deliverables(tmp_path):
    for name in ('_render.wav', '_render_lvl.wav', '_remix.wav', 'master.mp3', 'melody.mp3'):
        (tmp_path / name).write_bytes(b'x')
    (tmp_path / '_vc').mkdir()
    (tmp_path / '_vc' / 'probe.wav').write_bytes(b'x')

    R._sweep_temps(str(tmp_path), None, None)

    assert sorted(p.name for p in tmp_path.iterdir()) == ['master.mp3', 'melody.mp3']


def test_sweep_temps_is_silent_when_a_temp_was_never_written(tmp_path):
    # Every removal is best effort: an empty directory must not raise.
    R._sweep_temps(str(tmp_path), None, None)
    assert list(tmp_path.iterdir()) == []


def _manifest():
    """The three manifest fields `_stage_file_it` reads."""
    return {'family': 'children', 'elapsed_s': 12.0, 'delivery': {'picked': 'master.mp3'}}


def test_stage_file_it_writes_the_shelf_record_once(monkeypatch, tmp_path):
    monkeypatch.setattr(R, '_write_state', lambda *a, **k: None)
    log = _Log()
    brief = {'family': 'children', 'shelf': 'bedtime'}

    R._stage_file_it(brief, str(tmp_path), _manifest(), True, {}, False, 'because', log, 'job1')
    record = json.loads((tmp_path / 'shelf.json').read_text())
    assert (record['family'], record['shelf'], record['by']) == ('children', 'bedtime', 'style')
    assert 'filed: children/bedtime' in log.lines

    # A shelf record the operator already placed is never overwritten.
    (tmp_path / 'shelf.json').write_text('{"shelf": "operator"}')
    R._stage_file_it(brief, str(tmp_path), _manifest(), True, {}, False, 'because', log, 'job1')
    assert json.loads((tmp_path / 'shelf.json').read_text()) == {'shelf': 'operator'}


def test_stage_file_it_files_nothing_when_the_run_did_not_succeed(monkeypatch, tmp_path):
    states = []
    monkeypatch.setattr(R, '_write_state', lambda *a, **k: states.append(a))
    R._stage_file_it(
        {'shelf': 'bedtime'}, str(tmp_path), _manifest(), False, {}, False, 'nothing shipped', _Log(), 'job1'
    )
    assert not os.path.exists(tmp_path / 'shelf.json')
    assert len(states) == 1  # the run state is written either way


def test_stage_file_it_closing_line_names_the_video_or_says_why_there_is_none(monkeypatch, tmp_path):
    monkeypatch.setattr(R, '_write_state', lambda *a, **k: None)

    log = _Log()
    video = {'ok': True, 'file': 'song.mp4', 'pacing': {'pictures': 9, 'per_5s_mean': 1.5}}
    R._stage_file_it({}, str(tmp_path), _manifest(), True, video, True, 'picked', log, '')
    assert log.lines[-1] == 'done in 12s → master.mp3 (picked) · video song.mp4 — 9 pictures, 1.5 per 5s'

    log = _Log()
    R._stage_file_it({}, str(tmp_path), _manifest(), True, {'ok': False, 'reason': 'no frames'}, True, 'p', log, '')
    assert log.lines[-1] == 'done in 12s → master.mp3 (p) · no video (no frames)'

    # A run that never asked for a video says nothing about one.
    log = _Log()
    R._stage_file_it({}, str(tmp_path), _manifest(), True, {'ok': False, 'reason': 'x'}, False, 'p', log, '')
    assert log.lines[-1] == 'done in 12s → master.mp3 (p)'


def test_remix_for_level_masters_the_take_unbalanced_when_the_remix_fails(monkeypatch, tmp_path):
    def _boom(*_a, **_k):
        raise RuntimeError('ffmpeg said no')

    monkeypatch.setattr(R, 'remix_stems', _boom)
    voice = {'_stems': {'vocals': 'v.wav', 'rest': 'r.wav'}, 'mix': {'vocal_db': -9.0}}
    log = _Log()

    feed = R._remix_for_level(voice, str(tmp_path), 'pick.mp3', log)

    assert feed == 'pick.mp3'  # the unbalanced take, not a remix
    assert voice['mix'] == {'vocal_db': 0.0, 'backing_db': 0.0, 'by': 'none', 'error': 'RuntimeError'}
    assert log.lines == ['voice: level fix failed (RuntimeError: ffmpeg said no) — mastering the take']


def test_remix_for_level_feeds_the_remix_when_it_worked(monkeypatch, tmp_path):
    seen = {}

    def _remix(vocals, rest, dst, *, vocal_db):
        seen.update(vocals=vocals, rest=rest, dst=dst, vocal_db=vocal_db)
        return {'path': dst}

    monkeypatch.setattr(R, 'remix_stems', _remix)
    voice = {'_stems': {'vocals': 'v.wav', 'rest': 'r.wav'}, 'mix': {'vocal_db': 2.5}}
    log = _Log()

    feed = R._remix_for_level(voice, str(tmp_path), 'pick.mp3', log)

    assert feed == os.path.join(str(tmp_path), '_remix.wav')
    assert seen == {'vocals': 'v.wav', 'rest': 'r.wav', 'dst': feed, 'vocal_db': 2.5}
    assert voice['mix'] == {'vocal_db': 2.5}  # untouched on the happy path
    assert log.lines == ['voice: level fix — vocal +2.5 dB from the stems before mastering']
