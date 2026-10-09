#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Warm Control's re-seed loop — which takes run() renders, in which order.

    ../.venv/bin/python -m pytest tests/test_kidsmusic_male_retry.py

The adult_male singer carries `retry_lead_shift_st` (-12) and `singer_retries`
(6): take 1 is exactly Warm Control on the score render, take 2 the SAME seed
on the melody an octave down, then seed+1 both ways. The measurement behind
that order lives in kids_music_theory.SINGERS['adult_male'] and
tools/kidsmusic_male_octave_bench.py; this file pins the order itself, and that
a singer WITHOUT the key still walks seeds on one conditioning as before.

No GPU, no LLM, no ComfyUI: ace_render copies its conditioning to the take and
gate_singer_age answers from a script. Composition, the MIDI, the SoundFont
render and the lowered render are real.
"""

import os
import shutil
import sys

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)

from zyg_workflows import kids_music_service as K  # noqa: E402
from zyg_workflows import kids_music_theory as T  # noqa: E402

mido = pytest.importorskip('mido')
pytest.importorskip('numpy')
pytest.importorskip('soundfile')

_LYRICS = (['one two three', 'four five six', 'one two three', 'four five six'], 'T', 'fallback', {})


# ── the lowered render moves the tune and nothing else ───────────────────────


def _tiny_midi(path):
    mid = mido.MidiFile(type=1)
    for name, ch, note in (('Melody', 0, 62), ('Chords', 1, 50), ('Percussion', 9, 38)):
        tr = mido.MidiTrack()
        tr.append(mido.MetaMessage('track_name', name=name, time=0))
        tr.append(mido.Message('note_on', channel=ch, note=note, velocity=90, time=0))
        tr.append(mido.Message('note_off', channel=ch, note=note, velocity=0, time=480))
        mid.tracks.append(tr)
    mid.save(path)


def test_lowered_lead_moves_only_the_melody_track(tmp_path, monkeypatch):
    src = str(tmp_path / 'melody.mid')
    _tiny_midi(src)
    seen = {}

    def fake_render(midi_path, wav_path, **kw):
        for tr in mido.MidiFile(midi_path).tracks:
            name = next(m.name for m in tr if m.type == 'track_name')
            seen[name] = [m.note for m in tr if m.type == 'note_on']
        return wav_path

    monkeypatch.setattr(K, 'render_soundfont', fake_render)
    out = K.lowered_lead_wav(src, str(tmp_path / '_render_low.wav'), -12)
    assert out == str(tmp_path / '_render_low.wav')
    assert seen == {'Melody': [50], 'Chords': [50], 'Percussion': [38]}
    assert not os.path.exists(tmp_path / '_render_low.mid'), 'temp MIDI left behind'
    assert mido.MidiFile(src).tracks[0][1].note == 62, 'the source MIDI was edited'


def test_no_melody_track_means_no_lowered_render(tmp_path, monkeypatch):
    src = str(tmp_path / 'x.mid')
    mid = mido.MidiFile(type=1)
    tr = mido.MidiTrack()
    tr.append(mido.MetaMessage('track_name', name='Chords', time=0))
    mid.tracks.append(tr)
    mid.save(src)
    monkeypatch.setattr(K, 'render_soundfont', lambda *a, **kw: pytest.fail('rendered with nothing lowered'))
    assert K.lowered_lead_wav(src, str(tmp_path / 'low.wav'), -12) is None


# ── run(): the order of takes ────────────────────────────────────────────────


@pytest.fixture
def scripted_ace(monkeypatch):
    """ACE-Step and the singer gate, stubbed; returns the call log and a knob
    for how many takes fail before one passes."""
    from zyg_workflows import audio_qc

    for var in ('ZYG_KIDSMUSIC_SINGER_RETRIES', 'ZYG_KIDSMUSIC_TAKES', 'ZYG_KIDSMUSIC_ACE_MODE', 'ZYG_KIDSMUSIC_A2A'):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv('ZYG_KIDSMUSIC_SINGER_ENFORCE', '1')
    # The voice review would demucs + Whisper the stub takes; this file pins the
    # re-seed ORDER only. tests/test_voice_leg.py covers the review path.
    monkeypatch.setenv('ZYG_KIDSMUSIC_VOICE_REVIEW', '0')
    monkeypatch.setattr(K, 'write_lyrics', lambda *a, **kw: tuple(_LYRICS))
    monkeypatch.setattr(
        audio_qc,
        'qc_clap',
        lambda *a, **kw: {'ok': True, 'positive_prob': 0.9, 'effective_threshold': 0.5, 'scores': {}},
    )
    monkeypatch.setattr(K, 'ace_available', lambda: True)
    state = {'calls': [], 'fail_first': 99}

    def fake_ace(plan, out_path, *, seed=None, info=None, melody_wav=None, cover_wav=None, **kw):
        state['calls'].append(
            (seed, os.path.basename(melody_wav or ''), bool(melody_wav and os.path.isfile(melody_wav)))
        )
        shutil.copyfile(melody_wav, out_path)
        if info is not None:
            info.update({'ran': True, 'seed': seed, 'mode': 'a2a', 'melody_conditioned': True})
        return out_path

    def fake_gate(path, plan, **kw):
        n = len(state['calls'])
        ok = n > state['fail_first']
        f0 = 215.0 if ok else 372.0
        return {
            'gate': 'singer',
            'status': 'pass' if ok else 'fail',
            'ok': ok,
            'enforced': True,
            'checks': {'f0_median_hz': f0},
            'detail': f'{f0:.0f} Hz',
        }

    monkeypatch.setattr(K, 'ace_render', fake_ace)
    monkeypatch.setattr(K, 'gate_singer_age', fake_gate)
    return state


def _run(tmp_path, singer):
    out = str(tmp_path / singer)
    man = K.run(
        {'theme': 'counting ducks', 'seconds': 25, 'sung': True, 'want_video': False, 'singer': singer},
        out,
        candidates=6,
        want_ace=True,
    )
    return out, man


def test_warm_control_alternates_score_and_lowered_melody(tmp_path, scripted_ace):
    seed = T.SINGERS['adult_male']['ace_seed']
    scripted_ace['fail_first'] = 3  # takes 1-3 sing high, take 4 is male
    out, man = _run(tmp_path, 'adult_male')
    assert scripted_ace['calls'] == [
        (seed, '_render.wav', True),
        (seed, '_render_low.wav', True),
        (seed + 1, '_render.wav', True),
        (seed + 1, '_render_low.wav', True),
    ]
    prod = man['produced']
    assert [a['lead_shift_st'] for a in prod['attempts']] == [0, -12, 0, -12]
    assert prod['lead_shift_st'] == -12 and prod['seed'] == seed + 1
    assert man['gates']['singer']['ok'] is True
    assert not os.path.exists(os.path.join(out, '_render_low.wav'))


def test_warm_control_first_take_is_untouched_when_it_passes(tmp_path, scripted_ace):
    seed = T.SINGERS['adult_male']['ace_seed']
    scripted_ace['fail_first'] = 0
    _out, man = _run(tmp_path, 'adult_male')
    assert scripted_ace['calls'] == [(seed, '_render.wav', True)]
    assert man['produced']['lead_shift_st'] == 0


def test_warm_control_budget_is_six_takes(tmp_path, scripted_ace):
    seed = T.SINGERS['adult_male']['ace_seed']
    _out, man = _run(tmp_path, 'adult_male')  # every take fails
    assert [(s, w) for s, w, _ in scripted_ace['calls']] == [
        (seed, '_render.wav'),
        (seed, '_render_low.wav'),
        (seed + 1, '_render.wav'),
        (seed + 1, '_render_low.wav'),
        (seed + 2, '_render.wav'),
        (seed + 2, '_render_low.wav'),
    ]
    assert man['gates']['singer']['ok'] is False


def test_a_singer_without_the_key_walks_seeds_as_before(tmp_path, scripted_ace):
    assert not T.SINGERS['adult_female'].get('retry_lead_shift_st')
    seed = T.SINGERS['adult_female']['ace_seed']
    _out, man = _run(tmp_path, 'adult_female')  # every take fails
    assert [(s, w) for s, w, _ in scripted_ace['calls']] == [
        (seed, '_render.wav'),
        (seed + 1, '_render.wav'),
        (seed + 2, '_render.wav'),
    ]
    assert [a['lead_shift_st'] for a in man['produced']['attempts']] == [0, 0, 0]


def test_the_environment_still_sets_the_budget(tmp_path, scripted_ace, monkeypatch):
    monkeypatch.setenv('ZYG_KIDSMUSIC_SINGER_RETRIES', '2')
    seed = T.SINGERS['adult_male']['ace_seed']
    _run(tmp_path, 'adult_male')
    assert [(s, w) for s, w, _ in scripted_ace['calls']] == [(seed, '_render.wav'), (seed, '_render_low.wav')]
