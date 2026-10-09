#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Voice conversion wired into the kids-music run (2026-09-15).

    ../.venv/bin/python -m pytest tests/test_voice_conversion_wiring.py

No GPU, no Applio, no Whisper: the conversion, the pitch tracks and the review
are stubbed. The conversion quality itself was benched in tools/vc_bench.py;
these pin the ship decision, what is kept for A/B, and the remix reset.
"""

import json
import os
import sys

import pytest

from tests import _tree

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

np = pytest.importorskip('numpy')
sf = pytest.importorskip('soundfile')

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import vocal_analysis as VA  # noqa: E402
from zyg_workflows import voice_conversion as VC  # noqa: E402

MALE = T.SINGERS['adult_male']
SR = 44100


def _wav(path, freq=220.0, secs=2.0, amp=0.2):
    t = np.arange(int(SR * secs)) / SR
    y = (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)
    sf.write(path, np.stack([y, y], 1), SR, subtype='PCM_16')
    return path


# ── ship_check: the bench's per-song criteria ───────────────────────────────


def _rev(sung, lines=12, clear=None):
    """A review report. `clear` defaults to `sung`: every line that was sung
    could also be made out, which is the case the limits are written against."""
    return {
        'lyrics': {'measured': True, 'sung': sung, 'lines': lines},
        'lyrics_bare': {'measured': True, 'clear': sung if clear is None else clear, 'lines': lines},
    }


GOOD = {'measured': True, 'median_abs_cents': 5.4, 'octave_error_share': 0.0005}


def test_a_conversion_inside_every_limit_ships():
    assert VC.ship_check(_rev(10), _rev(10), GOOD) == (True, [])


def test_losing_one_line_is_allowed_and_two_is_not():
    assert VC.ship_check(_rev(10), _rev(9), GOOD)[0]
    ok, why = VC.ship_check(_rev(10), _rev(8), GOOD)
    assert not ok and 'lyric lines sung 10 -> 8' in why[0]


def test_melody_drift_and_octave_errors_each_refuse():
    assert not VC.ship_check(_rev(10), _rev(10), dict(GOOD, median_abs_cents=26.0))[0]
    assert not VC.ship_check(_rev(10), _rev(10), dict(GOOD, octave_error_share=0.03))[0]


def test_an_unmeasured_check_refuses_rather_than_passes():
    assert not VC.ship_check(_rev(10), _rev(10), {'measured': False})[0]
    ok, why = VC.ship_check(_rev(10), {'lyrics': {'measured': False}}, GOOD)
    assert not ok and 'unmeasured after' in why[0]


# ── intelligibility: RVC must not cost the song its words ──────────────────


def test_a_conversion_that_keeps_every_line_audible_ships():
    assert VC.ship_check(_rev(12, clear=12), _rev(12, clear=12), GOOD) == (True, [])


def test_losing_one_audible_line_is_allowed_and_two_is_not():
    """Measured: RVC cost 8.6 points of coverage over 16 songs and was worse on
    13 of them. 0184f07516ab lost 26 points — that conversion must not ship."""
    assert VC.ship_check(_rev(12, clear=12), _rev(12, clear=11), GOOD)[0]
    ok, why = VC.ship_check(_rev(12, clear=12), _rev(12, clear=10), GOOD)
    assert not ok and 'lines you can make out 12 -> 10' in why[0]


def test_the_prompted_count_alone_cannot_pass_a_conversion_that_destroyed_clarity():
    """The exact hole being closed: every line still 'sung' by the prompted
    decode, while the words became unrecoverable."""
    ok, why = VC.ship_check(_rev(12, clear=12), _rev(12, clear=3), GOOD)
    assert not ok and any('make out' in r for r in why)


def test_unmeasured_intelligibility_refuses_rather_than_passes():
    before = _rev(12, clear=12)
    after = {'lyrics': {'measured': True, 'sung': 12, 'lines': 12}, 'lyrics_bare': {'measured': False}}
    ok, why = VC.ship_check(before, after, GOOD)
    assert not ok and 'intelligibility unmeasured after' in why[0]
    ok, why = VC.ship_check(
        {'lyrics': {'measured': True, 'sung': 12, 'lines': 12}, 'lyrics_bare': {'measured': False}}, _rev(12), GOOD
    )
    assert not ok and 'intelligibility unmeasured before' in why[0]


def test_a_conversion_that_improves_clarity_ships():
    assert VC.ship_check(_rev(12, clear=8), _rev(12, clear=11), GOOD) == (True, [])


def test_the_male_singer_pins_the_benched_weights():
    assert MALE['vc_model'] == 'warm_control_v2'
    assert MALE['vc_weights'] == 'warm_control_v2_300e_9900s.pth'
    assert not T.SINGERS['adult_female'].get('vc_model')


def test_the_worker_honours_a_pinned_weights_file():
    src = open(_tree.pkg('tools', 'vc_applio_worker.py')).read()
    assert "os.environ.get('VC_PTH'" in src


# ── convert_voice: what run() gets back and what is kept ────────────────────


def _voice(tmp_path):
    take_dir = tmp_path / '_takes' / 'take1' / 'stems'
    take_dir.mkdir(parents=True)
    voc = _wav(str(take_dir / 'vocals.wav'), 220.0)
    rest = _wav(str(take_dir / 'no_vocals.wav'), 110.0)
    return {
        'reviewed': True,
        'lyrics': {'measured': True, 'sung': 10, 'lines': 12},
        'lyrics_bare': {'measured': True, 'clear': 10, 'lines': 12},
        'mix': {'vocal_db': 2.0, 'backing_db': 0.0},
        'stems': {},
        '_stems': {'vocals': voc, 'rest': rest},
    }


def _stub(monkeypatch, tmp_path, *, sung_after=10, cents=5.0, convert_ok=True, clear_after=None):
    def fake_convert(vocals_wav, work_dir, **kw):
        os.makedirs(work_dir, exist_ok=True)
        if not convert_ok:
            return {'ok': False, 'error': 'boom'}
        return {
            'ok': True,
            'path': _wav(os.path.join(work_dir, 'vocals_converted.wav'), 221.0),
            'engine': VC.ENGINE,
            'weights': kw.get('weights'),
            'lag_samples': 0,
            'envelope_corr': 0.9,
            'gain_db': 0.5,
            'convert_s': 1.0,
        }

    monkeypatch.setattr(VC, 'convert_stem', fake_convert)
    monkeypatch.setattr(VC, 'melody_drift', lambda a, b: dict(GOOD, median_abs_cents=cents))
    # The bare decode has to be handed the CONVERTED mix, never the take: record
    # what convert_voice passed so a test can assert it.
    seen = {}

    def fake_review(take, plan, singer, work_dir, **k):
        seen['bare_take'] = k.get('bare_take')
        seen['take'] = take
        return {
            'ok': True,
            'lyrics': {'measured': True, 'sung': sung_after, 'lines': 12},
            'lyrics_bare': {'measured': True, 'lines': 12, 'clear': sung_after if clear_after is None else clear_after},
            'register': {},
            'key': {},
            'severity': 1,
            'problems': [],
        }

    monkeypatch.setattr(VA, 'review', fake_review)
    return seen


def test_a_passing_conversion_returns_a_mix_and_keeps_both_vocals(tmp_path, monkeypatch):
    _stub(monkeypatch, tmp_path)
    voice = _voice(tmp_path)
    feed = K.convert_voice(voice, {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path))
    assert feed and os.path.isfile(feed)
    c = voice['conversion']
    assert c['shipped'] and c['reasons'] == [] and c['weights'] == MALE['vc_weights']
    assert os.path.isfile(tmp_path / 'stems' / 'vocals.flac')
    assert os.path.isfile(tmp_path / 'stems' / 'vocals_unconverted.flac')
    assert voice['stems']['vocals_unconverted'] == 'stems/vocals_unconverted.flac'
    assert c['unconverted']['master'] == 'master_unconverted.mp3'
    # The converted stem really is the converted one, the kept one the original.
    yc, _ = sf.read(tmp_path / 'stems' / 'vocals.flac')
    yo, _ = sf.read(tmp_path / 'stems' / 'vocals_unconverted.flac')
    assert not np.allclose(yc, yo)


def test_a_failing_check_ships_the_take_unconverted(tmp_path, monkeypatch):
    _stub(monkeypatch, tmp_path, sung_after=7)
    voice = _voice(tmp_path)
    assert K.convert_voice(voice, {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path)) is None
    assert voice['conversion']['shipped'] is False
    assert 'lyric lines sung 10 -> 7' in voice['conversion']['reasons'][0]
    assert not os.path.exists(tmp_path / 'stems' / 'vocals_unconverted.flac')


def test_a_failed_conversion_ships_unconverted_and_says_why(tmp_path, monkeypatch):
    _stub(monkeypatch, tmp_path, convert_ok=False)
    voice = _voice(tmp_path)
    assert K.convert_voice(voice, {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path)) is None
    assert voice['conversion']['reasons'] == ['boom']


def test_the_switch_turns_it_off(tmp_path, monkeypatch):
    _stub(monkeypatch, tmp_path)
    monkeypatch.setenv('ZYG_KIDSMUSIC_VC', '0')
    voice = _voice(tmp_path)
    assert K.convert_voice(voice, {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path)) is None
    assert 'turned off' in voice['conversion']['reasons'][0]


# ── remix reset on a converted song ─────────────────────────────────────────


def _song(tmp_path, converted):
    (tmp_path / 'stems').mkdir()
    _wav(str(tmp_path / 'stems' / 'vocals.flac'.replace('.flac', '.wav')), 221.0)
    for name, _f in (('vocals', 221.0), ('backing', 110.0), ('vocals_unconverted', 220.0)):
        y = np.zeros(SR, np.float32) + (0.1 if name != 'backing' else 0.05)
        sf.write(tmp_path / 'stems' / f'{name}.flac', np.stack([y, y], 1), SR, format='FLAC')
    (tmp_path / 'song.mp3').write_bytes(b'take')
    (tmp_path / 'song.json').write_text('{}')
    man = {
        'delivery': {'picked_leg': 'produced'},
        'voice': {'take_file': 'song.mp3', 'conversion': {'shipped': converted}},
    }
    (tmp_path / 'manifest.json').write_text(json.dumps(man))


def test_reset_on_a_converted_song_re_sums_the_converted_stems_not_the_take(tmp_path, monkeypatch):
    _song(tmp_path, converted=True)
    fed = []

    def fake_master(src, out_dir, plan, log_fn=None, dst_name='master.mp3'):
        fed.append(os.path.basename(src))
        p = os.path.join(out_dir, dst_name)
        open(p, 'wb').write(b'm')
        return p, {'checks': {'lufs': -14.0}}, 0.0

    monkeypatch.setattr(K, 'master_audio', fake_master)
    monkeypatch.setattr(K, 'remux_video', lambda *a, **k: False)
    r = K.remix_job(str(tmp_path), vocal_db=0.0, backing_db=0.0)
    assert r['ok']
    # 1st: the converted stems at 0 dB; 2nd: the A/B master from the take.
    assert fed == ['_remix.wav', 'song.mp3']
    assert os.path.isfile(tmp_path / 'master_unconverted.mp3')


def test_reset_on_an_unconverted_song_is_unchanged(tmp_path, monkeypatch):
    _song(tmp_path, converted=False)
    os.remove(tmp_path / 'stems' / 'vocals_unconverted.flac')
    fed = []

    def fake_master(src, out_dir, plan, log_fn=None, dst_name='master.mp3'):
        fed.append(os.path.basename(src))
        p = os.path.join(out_dir, dst_name)
        open(p, 'wb').write(b'm')
        return p, {'checks': {}}, 0.0

    monkeypatch.setattr(K, 'master_audio', fake_master)
    monkeypatch.setattr(K, 'remux_video', lambda *a, **k: False)
    assert K.remix_job(str(tmp_path), vocal_db=0.0, backing_db=0.0)['ok']
    assert fed == ['song.mp3']
    # ...and a gain move still works without an unconverted stem on disk.
    fed.clear()
    assert K.remix_job(str(tmp_path), vocal_db=3.0, backing_db=0.0)['ok']
    assert fed == ['_remix.wav']


def test_a_conversion_that_destroys_clarity_ships_unconverted(tmp_path, monkeypatch):
    """Every line still 'sung', but only 3 of 12 can be made out. This is the
    13-of-16 case from the measurement; it used to ship."""
    _stub(monkeypatch, tmp_path, sung_after=10, clear_after=3)
    voice = _voice(tmp_path)
    feed = K.convert_voice(voice, {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path))
    assert feed is None
    c = voice['conversion']
    assert not c['shipped'] and any('make out' in r for r in c['reasons'])
    # the unconverted stems must NOT have been swapped in
    assert not os.path.isfile(tmp_path / 'stems' / 'vocals.flac')


def test_the_bare_decode_is_handed_the_converted_mix_not_the_take(tmp_path, monkeypatch):
    """A bare decode of `take` would grade the UNCONVERTED audio and miss the
    damage entirely — the whole point of the check."""
    seen = _stub(monkeypatch, tmp_path)
    K.convert_voice(_voice(tmp_path), {}, MALE, str(tmp_path / 'song.mp3'), str(tmp_path))
    assert seen['bare_take'] and seen['bare_take'] != seen['take']
    assert os.path.isfile(seen['bare_take'])
