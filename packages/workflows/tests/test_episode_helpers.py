# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from render_episode().

The panel flattening, the narration fan-out, the tempo pass and the sidecar
writer were all inline in the 314-line function — reachable only by rendering a
whole episode with ffmpeg and a TTS engine. Nothing here touches either.
"""

import logging
import os
import types

import pytest

from zyg_workflows.briefing_video import episode as EP


def _spec(**over):
    """A minimal render_episode spec; `over` replaces or adds keys."""
    spec = {
        'board_png': '/tmp/board.png',
        'outro_png': '/tmp/outro.png',
        'welcome_text': 'Welcome',
        'outro_text': 'Thanks for watching',
        'items': [
            {
                'chapter': 'First story',
                'panels': [
                    {'image': '/tmp/a.png', 'text': 'A', 'ken_burns': True},
                    {'image': '/tmp/b.png', 'text': 'B', 'min_seconds': 4},
                ],
            }
        ],
    }
    spec.update(over)
    return spec


# ── _emit ────────────────────────────────────────────────────────────────────


def test_emit_forwards_level_and_message_to_the_callers_sink():
    seen = []
    EP._emit(lambda level, msg: seen.append((level, msg)), 'INFO', 'hello')
    assert seen == [('INFO', 'hello')]


def test_emit_without_a_sink_logs_the_console_shape(caplog):
    with caplog.at_level(logging.INFO, logger=EP._zyg_log.name):
        EP._emit(None, 'WARNING', 'no audio')
    assert [r.getMessage() for r in caplog.records] == ['[BRIEF|WARNING] no audio']


# ── _build_panels ────────────────────────────────────────────────────────────


def test_panels_are_board_then_items_then_outro():
    panels = EP._build_panels(_spec(), '', '')
    assert [p['kind'] for p in panels] == ['board', 'item', 'item', 'outro']
    assert [p['image'] for p in panels] == ['/tmp/board.png', '/tmp/a.png', '/tmp/b.png', '/tmp/outro.png']


def test_only_the_first_panel_of_an_item_carries_its_chapter():
    panels = EP._build_panels(_spec(), '', '')
    assert panels[1]['chapter'] == 'First story'
    assert panels[2]['chapter'] is None


def test_panel_defaults_cover_an_item_without_text_or_timings():
    panels = EP._build_panels(_spec(items=[{'panels': [{'image': '/tmp/x.png'}]}]), '', '')
    item = panels[1]
    assert item['text'] == ''
    assert item['min_seconds'] == 0.0
    assert item['ken_burns'] is False


def test_without_an_intro_stinger_the_board_has_no_narration_lead_in():
    panels = EP._build_panels(_spec(), '', '')
    assert panels[0]['lead_in'] == 0.0
    assert panels[0]['min_seconds'] == 10.0


def test_an_existing_stinger_pair_sets_the_lead_in_and_the_longer_outro_hold(tmp_path):
    jin = tmp_path / 'in.wav'
    jin.write_bytes(b'x')
    jout = tmp_path / 'out.wav'
    jout.write_bytes(b'x')
    panels = EP._build_panels(_spec(), str(jin), str(jout))
    assert panels[0]['lead_in'] == 5.2
    assert panels[-1]['min_seconds'] == 14.0


def test_a_stinger_path_that_is_not_on_disk_keeps_the_12_second_outro_hold(tmp_path):
    panels = EP._build_panels(_spec(), str(tmp_path / 'absent.wav'), str(tmp_path / 'absent.wav'))
    assert panels[0]['lead_in'] == 0.0
    assert panels[-1]['min_seconds'] == 12.0


def test_the_welcome_and_outro_chapter_titles_are_overridable():
    panels = EP._build_panels(_spec(welcome_chapter='Hallo', outro_chapter='Bye'), '', '')
    assert panels[0]['chapter'] == 'Hallo'
    assert panels[-1]['chapter'] == 'Bye'


# ── _narrate_panels ──────────────────────────────────────────────────────────


def test_narration_takes_the_batch_result_and_only_speaks_what_it_missed(monkeypatch, tmp_path):
    panels = [{'text': 'one'}, {'text': 'two'}, {'text': '  '}]
    monkeypatch.setattr(EP, 'speak_batch', lambda items, wd, **kw: {0: '/tmp/batched.wav'})
    spoken = []

    def _speak(text, wav, **kw):
        spoken.append((text, wav))
        return True

    monkeypatch.setattr(EP, 'speak', _speak)
    n = EP._narrate_panels(panels, {}, str(tmp_path), '', None, lambda *a: None, lambda: None, None)
    assert n == 2
    assert panels[0]['wav'] == '/tmp/batched.wav'
    assert panels[1]['wav'] == os.path.join(str(tmp_path), 'seg_001.wav')
    assert panels[2]['wav'] == ''
    assert spoken == [('two', os.path.join(str(tmp_path), 'seg_001.wav'))]


def test_a_panel_the_engine_refused_holds_silently_with_a_warning(monkeypatch, tmp_path):
    panels = [{'text': 'one'}]
    monkeypatch.setattr(EP, 'speak_batch', lambda *a, **kw: {})
    monkeypatch.setattr(EP, 'speak', lambda *a, **kw: False)
    warned = []
    n = EP._narrate_panels(
        panels, {}, str(tmp_path), '', None, lambda lvl, msg: warned.append((lvl, msg)), lambda: None, None
    )
    assert n == 0
    assert panels[0]['wav'] == ''
    assert warned == [('WARNING', 'panel 0 produced no audio — it will hold silently')]


def test_narration_honours_the_stop_check(monkeypatch, tmp_path):
    monkeypatch.setattr(EP, 'speak_batch', lambda *a, **kw: {})

    def _stop():
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        EP._narrate_panels([{'text': 'x'}], {}, str(tmp_path), '', None, lambda *a: None, _stop, None)


# ── _apply_tempo ─────────────────────────────────────────────────────────────


def test_a_tempo_of_one_is_a_no_op(monkeypatch):
    monkeypatch.setenv('ZYG_BRIEF_TEMPO', '1.0')

    def _boom(*a, **kw):
        raise AssertionError('ffmpeg must not run')

    monkeypatch.setattr(EP, '_run', _boom)
    panels = [{'wav': '/tmp/a.wav'}]
    EP._apply_tempo(panels, lambda *a: None)
    assert panels[0]['wav'] == '/tmp/a.wav'


def test_an_unparseable_tempo_falls_back_to_the_default(monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_BRIEF_TEMPO', 'fast')
    calls = []

    def _run(cmd, timeout=None):
        calls.append(cmd)
        out = cmd[-1]
        with open(out, 'wb') as f:
            f.write(b'0' * 2000)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(EP, '_run', _run)
    wav = tmp_path / 'seg.wav'
    wav.write_bytes(b'0')
    panels = [{'wav': str(wav)}]
    lines = []
    EP._apply_tempo(panels, lambda lvl, msg: lines.append(msg))
    assert 'atempo=1.07' in calls[0]
    assert panels[0]['wav'] == str(wav).replace('.wav', '.tempo.wav')
    assert lines == ['narration pace: atempo 1.07 applied to 1 panel(s)']


def test_a_tempo_render_that_came_out_too_small_keeps_the_original_wav(monkeypatch, tmp_path):
    monkeypatch.setenv('ZYG_BRIEF_TEMPO', '1.2')
    monkeypatch.setattr(EP, '_run', lambda cmd, timeout=None: types.SimpleNamespace(returncode=0))
    wav = tmp_path / 'seg.wav'
    wav.write_bytes(b'0')
    panels = [{'wav': str(wav)}, {'wav': ''}]
    lines = []
    EP._apply_tempo(panels, lambda lvl, msg: lines.append(msg))
    assert panels[0]['wav'] == str(wav)
    assert lines == ['narration pace: atempo 1.2 applied to 0 panel(s)']


# ── _render_panels ───────────────────────────────────────────────────────────


def test_rendered_clips_carry_the_chapter_marks_at_their_running_offsets(monkeypatch, tmp_path):
    img = tmp_path / 'p.png'
    img.write_bytes(b'x')
    panels = [
        {'image': str(img), 'min_seconds': 0, 'ken_burns': False, 'chapter': 'One'},
        {'image': str(img), 'min_seconds': 0, 'ken_burns': False, 'chapter': None},
        {'image': str(img), 'min_seconds': 0, 'ken_burns': False, 'chapter': 'Two'},
    ]
    monkeypatch.setattr(EP, '_render_segment', lambda image, wav, clip, nv, **kw: (clip, 5.0))
    parts, marks, total = EP._render_panels(panels, str(tmp_path), False, lambda *a: None, lambda: None, None)
    assert len(parts) == 3
    assert marks == [{'at': 0.0, 'title': 'One'}, {'at': 10.0, 'title': 'Two'}]
    assert total == 15.0


def test_a_panel_without_an_image_on_disk_is_skipped_with_a_warning(monkeypatch, tmp_path):
    warned = []
    monkeypatch.setattr(EP, '_render_segment', lambda *a, **kw: (None, 0.0))
    parts, marks, total = EP._render_panels(
        [{'image': '', 'min_seconds': 0, 'ken_burns': False}],
        str(tmp_path),
        False,
        lambda lvl, msg: warned.append(msg),
        lambda: None,
        None,
    )
    assert (parts, marks, total) == ([], [], 0.0)
    assert warned == ['panel 0 has no image — skipped']


def test_a_panel_ffmpeg_refused_is_skipped_and_leaves_no_chapter(monkeypatch, tmp_path):
    img = tmp_path / 'p.png'
    img.write_bytes(b'x')
    warned = []
    monkeypatch.setattr(EP, '_render_segment', lambda *a, **kw: (None, 0.0))
    parts, marks, total = EP._render_panels(
        [{'image': str(img), 'min_seconds': 0, 'ken_burns': False, 'chapter': 'One'}],
        str(tmp_path),
        False,
        lambda lvl, msg: warned.append(msg),
        lambda: None,
        None,
    )
    assert (parts, marks, total) == ([], [], 0.0)
    assert warned == ['panel 0 failed to encode — skipped']


# ── _mix_stingers ────────────────────────────────────────────────────────────


def test_without_stingers_the_mastered_file_is_returned_untouched(monkeypatch):
    def _boom(*a, **kw):
        raise AssertionError('ffmpeg must not run')

    monkeypatch.setattr(EP, '_run', _boom)
    assert EP._mix_stingers('/tmp/m.mp4', [{}], 30.0, '/tmp', '', '', lambda *a: None) == '/tmp/m.mp4'


def test_a_failed_stinger_mix_delivers_the_mastered_file_with_a_warning(monkeypatch, tmp_path):
    jin = tmp_path / 'in.wav'
    jin.write_bytes(b'x')
    monkeypatch.setattr(EP, '_run', lambda cmd, timeout=None: types.SimpleNamespace(returncode=1))
    warned = []
    got = EP._mix_stingers(
        '/tmp/m.mp4', [{'wav': ''}], 30.0, str(tmp_path), str(jin), '', lambda lvl, msg: warned.append(msg)
    )
    assert got == '/tmp/m.mp4'
    assert warned == ['stinger mix failed — delivering without it']


def test_the_outro_stinger_is_anchored_so_its_five_second_tail_still_fits(monkeypatch, tmp_path):
    jout = tmp_path / 'out.wav'
    jout.write_bytes(b'x')
    cmds = []

    def _run(cmd, timeout=None):
        cmds.append(cmd)
        out = cmd[-1]
        with open(out, 'wb') as f:
            f.write(b'x')
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(EP, '_run', _run)
    monkeypatch.setattr(EP, '_dur', lambda p: 8.0)
    lines = []
    got = EP._mix_stingers(
        '/tmp/m.mp4',
        [{'wav': '/tmp/outro.wav'}],
        30.0,
        str(tmp_path),
        '',
        str(jout),
        lambda lvl, msg: lines.append(msg),
    )
    assert got == os.path.join(str(tmp_path), 'jingled.mp4')
    assert lines == ['intro/outro stingers mixed in']
    # 30 - 14 + 8 + 0.6 = 24.6 s, under the 30 - 5.2 ceiling
    assert 'adelay=24600|24600[j1]' in ';'.join(cmds[0])


# ── _qc_gate ─────────────────────────────────────────────────────────────────


def test_a_passing_gate_leaves_the_deliverable_where_it_is(monkeypatch, tmp_path):
    final = tmp_path / 'ep.mp4'
    final.write_bytes(b'x')
    monkeypatch.setattr(
        EP, 'qc', lambda *a, **kw: {'passed': True, 'checks': [{'name': 'duration', 'ok': True, 'detail': ''}]}
    )
    lines = []
    report, quarantined = EP._qc_gate(
        str(final), 30.0, [], [{'text': 'A'}], 1, 1, str(tmp_path), 'ep', lambda lvl, msg: lines.append((lvl, msg))
    )
    assert quarantined is None
    assert report['passed'] is True
    assert lines == [('INFO', 'QC PASS — duration')]
    assert final.is_file()


def test_a_failing_gate_quarantines_the_deliverable_and_logs_the_detail(monkeypatch, tmp_path):
    final = tmp_path / 'ep.mp4'
    final.write_bytes(b'x')
    monkeypatch.setattr(
        EP, 'qc', lambda *a, **kw: {'passed': False, 'checks': [{'name': 'audio', 'ok': False, 'detail': 'silent'}]}
    )
    lines = []
    _report, quarantined = EP._qc_gate(
        str(final), 30.0, [], [{'text': 'A'}], 1, 1, str(tmp_path), 'ep', lambda lvl, msg: lines.append((lvl, msg))
    )
    assert quarantined == os.path.join(str(tmp_path), 'ep.QUARANTINED.mp4')
    assert os.path.isfile(quarantined) and not final.is_file()
    assert lines == [('ERROR', 'QC FAIL — audio: silent')]


def test_the_gate_is_told_how_many_panels_were_planned_rendered_and_narrated(monkeypatch, tmp_path):
    final = tmp_path / 'ep.mp4'
    final.write_bytes(b'x')
    seen = {}

    def _qc(path, dur, chapters, production=None):
        seen.update(production)
        return {'passed': True, 'checks': []}

    monkeypatch.setattr(EP, 'qc', _qc)
    EP._qc_gate(
        str(final),
        30.0,
        [],
        [{'text': 'A'}, {'text': ' '}, {'text': 'B'}],
        2,
        2,
        str(tmp_path),
        'ep',
        lambda *a: None,
    )
    assert seen == {'planned': 3, 'rendered': 2, 'with_text': 2, 'narrated': 2}


# ── _write_sidecars ──────────────────────────────────────────────────────────


def test_the_description_carries_the_playbar_chapters(tmp_path):
    chapters = [{'at': 0.0, 'title': 'Welcome'}, {'at': 75.0, 'title': 'First story'}]
    desc, chap, script = EP._write_sidecars(str(tmp_path), 'ep', {'description_intro': 'Daily briefing.'}, chapters, [])
    assert desc == os.path.join(str(tmp_path), 'ep.description.txt')
    body = open(desc, encoding='utf-8').read()
    assert body.startswith('Daily briefing.\n\nCHAPTERS\n0:00 Welcome\n1:15 First story')
    assert open(chap, encoding='utf-8').read() == '0:00 Welcome\n1:15 First story\n'
    assert open(script, encoding='utf-8').read() == ''


def test_the_disclaimer_and_attribution_follow_the_chapters_in_that_order(tmp_path):
    spec = {
        'description_intro': 'Intro.',
        'disclaimer': 'Not advice.',
        'attribution_note': 'Images: us.',
    }
    desc, _chap, _script = EP._write_sidecars(str(tmp_path), 'ep', spec, [{'at': 0.0, 'title': 'W'}], [])
    lines = open(desc, encoding='utf-8').read().splitlines()
    assert lines[-3:] == ['Not advice.', '', 'Images: us.']


def test_the_script_file_holds_only_the_spoken_panels_under_their_chapter(tmp_path):
    panels = [
        {'kind': 'board', 'chapter': 'Welcome', 'text': 'Hello'},
        {'kind': 'item', 'chapter': None, 'text': '   '},
        {'kind': 'outro', 'chapter': None, 'text': 'Bye'},
    ]
    _desc, _chap, script = EP._write_sidecars(str(tmp_path), 'ep', {}, [], panels)
    assert open(script, encoding='utf-8').read() == '[Welcome]\nHello\n\n[outro]\nBye\n\n'
