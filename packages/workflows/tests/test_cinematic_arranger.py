#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler.arrange_cinematic — the four-layer orchestral arrangement.

    ../.venv/bin/python -m pytest tests/test_cinematic_arranger.py

The children's renderer plays a plan literally: tune, chord on every downbeat,
bass on every strong beat, bar 1 to the end at one dynamic. That is correct for
a nursery rhyme and wrong for a film cue, so the cinematic family goes through
a second event builder. What is asserted here is the difference:

* four layers come back, and the fourth one is not empty — a `double`,
  `counter`, `ostinato` or `arpeggio` line is the whole point of the arranger;
* the pad MERGES bars that share a chord instead of restriking them, which is
  what makes strings swell rather than pulse;
* the bass follows the cue: one root a bar normally, driving eighths for a
  chase;
* the dynamic ARC really rises — the last section is louder than the first;
* intro bars carry pad and bass only, the outro carries the pad alone;
* every note the arranger invents is inside the chosen voice's recorded range,
  so nothing gets octave-folded on the way to the wav (`out_of_range_notes`);
* the render is still deterministic to the bit and still passes the licence
  fence, because a stored plan has to reproduce the cue that shipped.

The plans are built by hand from `compose_best` — family, extra layer and
voices set on the returned dict — so this file does not depend on the thirteen
cinematic STYLES having landed in kids_music_theory yet.
"""

import os

import pytest

from tests import _tree
from zyg_workflows import kids_music_theory as T
from zyg_workflows import melody_sampler as MS

np = pytest.importorskip('numpy')
pytest.importorskip('soundfile')


SECONDS = 40

# (brief, extra layer, voices) for two of the thirteen cues, chosen because
# they exercise opposite ends of the arranger: a fast 4/4 minor chase with a
# repeating ostinato and a driving eighth-note bass, and a slow 3/4 major
# waltz with a broken-chord piano.
CUES = {
    'chase': (
        {
            'theme': 'a chase across the rooftops',
            'age_band': 'cinematic',
            'mood': 'cinematic',
            'mode': 'natural_minor',
            'meter': '4/4',
            'bpm': 150,
            'form': 'ABAB',
            'seconds': SECONDS,
        },
        {'voice': 'marimba', 'role': 'ostinato'},
        {'lead': 'trumpet', 'pad': 'strings_spic', 'bass': 'contrabass_pizz', 'extra': 'marimba'},
    ),
    'romance': (
        {
            'theme': 'two people on a bridge',
            'age_band': 'cinematic',
            'mood': 'cinematic',
            'mode': 'major',
            'meter': '3/4',
            'bpm': 80,
            'form': 'AABA',
            'seconds': SECONDS,
        },
        {'voice': 'piano', 'role': 'arpeggio'},
        {'lead': 'violin', 'pad': 'strings_sus', 'bass': 'cello', 'extra': 'piano'},
    ),
}


@pytest.fixture(scope='module')
def idx():
    if not os.path.isfile(MS.SIDECAR):
        pytest.skip('instruments sidecar not present on this machine')
    _tree.instrument_samples()
    return MS.index()


@pytest.fixture(scope='module')
def plans(idx):
    out = {}
    for name, (brief, extra, voices) in CUES.items():
        plan = T.compose_best(dict(brief), candidates=4)
        plan['family'] = 'cinematic'
        plan['extra'] = dict(extra)
        plan['voices'] = dict(voices)
        out[name] = plan
    return out


@pytest.fixture(scope='module')
def arranged(plans):
    return {name: MS.arrange_cinematic(p) for name, p in plans.items()}


@pytest.fixture(scope='module')
def rendered(plans, tmp_path_factory):
    pytest.importorskip('mido', reason='the cue writes a MIDI stem with mido')
    d = tmp_path_factory.mktemp('cin')
    out = {}
    for name, plan in plans.items():
        wav = str(d / f'{name}.wav')
        out[name] = (wav, MS.render_plan(plan, wav, voices=plan['voices']))
    return out


# ── (a) four layers, and the fourth is real ──────────────────────────────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_arrangement_has_four_non_empty_layers(arranged, name):
    ev = arranged[name]
    assert set(ev) == {'lead', 'pad', 'bass', 'extra'}
    for role in ('lead', 'pad', 'bass', 'extra'):
        assert ev[role], f'{name}: {role} layer is empty'
        for e in ev[role]:
            assert len(e) == 4
            start_s, dur_s, midi, vel = e
            assert start_s >= 0.0 and dur_s > 0.0
            assert 0 < int(midi) < 128 and 1 <= int(vel) <= 127


def test_a_plan_without_an_extra_spec_is_an_ordinary_trio(plans):
    plan = dict(plans['romance'])
    plan.pop('extra', None)
    ev = MS.arrange_cinematic(plan)
    assert ev['extra'] == []
    assert ev['lead'] and ev['pad'] and ev['bass']


# ── (b) the pad swells: consecutive equal chords are merged ──────────────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_pad_merges_repeated_chords_instead_of_restriking(plans, arranged, name):
    """The progressions all repeat a chord, so merging must be visible."""
    plan, ev = plans[name], arranged[name]
    bar_beats = float(plan['bar_beats'])
    spb = 60.0 / float(plan['bpm'])
    ids = [MS._cin_chord_id(c) for c in plan['chords']]
    assert any(a == b for a, b in zip(ids, ids[1:])), (
        'fixture plan never repeats a chord — the merge cannot be observed'
    )

    starts = sorted({e[0] for e in ev['pad']})
    assert len(starts) < plan['bars'], f'{name}: {len(starts)} pad entries for {plan["bars"]} bars — no merge'
    held = max(e[1] for e in ev['pad'])
    assert held > bar_beats * spb + 0.3, f'{name}: longest pad note {held:.2f}s never spans two bars'
    # every entry is a full triad, voiced wide (root, fifth, third+12)
    assert len(ev['pad']) == 3 * len(starts)
    first = sorted(e[2] for e in ev['pad'] if e[0] == starts[0])
    assert first[2] - first[0] > 12, f'{name}: pad voicing {first} is not spread'


# ── (c) the bass follows the cue ─────────────────────────────────────────────


def test_chase_bass_drives_in_eighths(plans, arranged):
    plan, ev = plans['chase'], arranged['chase']
    assert plan['bpm'] >= MS.CIN_CHASE_BPM
    assert len(ev['bass']) > plan['bars'] * 2, f'{len(ev["bass"])} bass notes over {plan["bars"]} bars is not eighths'


def test_slow_cue_puts_one_root_on_each_downbeat(plans, arranged):
    plan, ev = plans['romance'], arranged['romance']
    assert plan['bpm'] < MS.CIN_CHASE_BPM
    playing = [c for c in plan['chords'] if c.get('section') != -2]
    assert len(ev['bass']) == len(playing)
    spb = 60.0 / float(plan['bpm'])
    downbeats = {round(float(c['t']) * spb, 6) for c in playing}
    assert {round(e[0], 6) for e in ev['bass']} == downbeats


# ── (d) intro and outro ──────────────────────────────────────────────────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_intro_is_pad_and_bass_and_the_outro_is_pad_alone(plans, arranged, name):
    plan, ev = plans[name], arranged[name]
    spb = 60.0 / float(plan['bpm'])
    intro = [c for c in plan['chords'] if c.get('section') == -1]
    outro = [c for c in plan['chords'] if c.get('section') == -2]
    if not (intro and outro):
        pytest.skip(f'{name}: plan has no intro/outro bars')

    def window(chords):
        lo = min(float(c['t']) for c in chords) * spb
        hi = (max(float(c['t']) + float(c['beats']) for c in chords)) * spb
        return lo, hi

    i_lo, i_hi = window(intro)
    assert not [e for e in ev['lead'] if i_lo <= e[0] < i_hi], 'lead in the intro'
    assert not [e for e in ev['extra'] if i_lo <= e[0] < i_hi], 'extra in the intro'
    assert [e for e in ev['pad'] if e[0] < i_hi], 'no pad in the intro'
    assert [e for e in ev['bass'] if i_lo <= e[0] < i_hi], 'no bass in the intro'

    o_lo, o_hi = window(outro)
    assert not [e for e in ev['bass'] if e[0] >= o_lo], 'bass plays over the outro'
    assert not [e for e in ev['extra'] if e[0] >= o_lo], 'extra plays over the outro'
    last_pad_end = max(e[0] + e[1] for e in ev['pad'])
    assert last_pad_end >= o_hi - 0.5, 'the final chord is not held to the end'


# ── (e) the dynamic arc ──────────────────────────────────────────────────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_the_last_section_is_louder_than_the_first(plans, arranged, name):
    plan, ev = plans[name], arranged[name]
    n_sec = len(plan['sections'])
    if n_sec < 2:
        pytest.skip(f'{name}: single-section plan has no arc to measure')
    by_sec = {}
    for n, e in zip(sorted(plan['melody'], key=lambda x: (x['t'], x['p'])), ev['lead']):
        by_sec.setdefault(n['section'], []).append(e[3])
    first = max(by_sec[min(by_sec)])
    last = max(by_sec[max(by_sec)])
    assert last > first, f'{name}: arc is flat ({first} -> {last})'
    assert MS._cin_arc(0, n_sec) == pytest.approx(0.78)
    assert MS._cin_arc(n_sec - 1, n_sec) == pytest.approx(1.0)


def test_lead_is_legato_never_overlapping_more_than_its_tail(plans, arranged):
    for name in CUES:
        _plan, ev = plans[name], arranged[name]
        lead = ev['lead']
        for (s0, d0, _m, _v), (s1, _d1, _m1, _v1) in zip(lead, lead[1:]):
            assert s0 + d0 <= s1 + MS.CIN_LEGATO_TAIL_S + 1e-6, name


# ── (f) everything the arranger invents is inside the voice's range ──────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_every_event_sits_inside_its_voice_range(plans, arranged, name):
    plan, ev = plans[name], arranged[name]
    for role, key in plan['voices'].items():
        info = MS.voice_info(key)
        tr = info['transpose']
        for start_s, _d, midi, _v in ev[role]:
            sounding = int(midi) + tr
            assert info['midi_lo'] - 7 <= sounding <= info['midi_hi'] + 7, (
                f'{name}/{role} ({key} {info["midi_lo"]}-{info["midi_hi"]}): '
                f'{sounding} at {start_s:.2f}s would be octave-folded'
            )


# ── (g) the render ───────────────────────────────────────────────────────────


@pytest.mark.parametrize('name', sorted(CUES))
def test_render_plan_writes_a_four_layer_cue(plans, rendered, name):
    import soundfile as sf

    plan = plans[name]
    wav, res = rendered[name]
    assert res['ok'] is True, res
    assert res['out_of_range_notes'] == 0
    assert res['layers'] == plan['voices']
    assert set(res['files']) == {'lead', 'pad', 'bass', 'extra'}
    assert all(res['files'][r] for r in res['files'])

    info = sf.info(wav)
    assert info.samplerate == MS.SR and info.channels == 2
    assert info.subtype == 'PCM_16'
    # render_events always leaves a 2.5 s tail for the last note's decay, so the
    # wav is the plan plus that tail and never shorter than the plan.
    assert plan['seconds'] - 0.5 <= info.duration <= plan['seconds'] + 3.0, (
        f'{name}: {info.duration:.1f}s for a {plan["seconds"]:.1f}s plan'
    )
    assert 0.2 < res['peak'] <= 0.98, res['peak']


@pytest.mark.parametrize('name', sorted(CUES))
def test_a_second_render_of_the_same_plan_is_bit_identical(plans, rendered, name, tmp_path):
    import soundfile as sf

    plan = plans[name]
    wav, _res = rendered[name]
    again = str(tmp_path / f'{name}-again.wav')
    res2 = MS.render_plan(plan, again, voices=plan['voices'])
    assert res2['ok'] is True
    a, _sr = sf.read(wav, dtype='float32', always_2d=True)
    b, _sr2 = sf.read(again, dtype='float32', always_2d=True)
    assert np.array_equal(a, b), 'a re-render of a stored plan drifted'


def test_render_role_renders_the_extra_layer(plans, arranged):
    plan = plans['chase']
    audio, stats = MS.render_role(plan, 'extra', plan['voices']['extra'])
    assert stats['notes'] == len(arranged['chase']['extra'])
    assert float(np.abs(audio).max()) > 0.001, 'the extra layer is silent'
    assert MS._role_db(plan, 'extra') == -10.0, 'an ostinato mixes at -10 dB'
    assert MS._role_db(plans['romance'], 'extra') == -7.0


def test_a_children_plan_still_has_no_extra_role():
    plan = T.compose_best(
        {'theme': 'a plain song', 'age_band': 'preschool', 'mood': 'happy', 'seconds': 20}, candidates=2
    )
    assert MS._is_cinematic(plan) is False
    with pytest.raises(KeyError):
        MS.render_role(plan, 'extra', 'marimba')


@pytest.mark.parametrize('name', sorted(CUES))
def test_credits_pass_for_a_rendered_cue(rendered, name):
    _wav, res = rendered[name]
    gate = MS.credits(res['files'])
    assert gate['ok'] is True, gate['violations']
    assert gate['violations'] == []


# ── (h) the CLI's extra-layer spec ───────────────────────────────────────────


def test_parse_extra_reads_the_style_tables_voice_role_string():
    assert MS.parse_extra('marimba:ostinato') == {'voice': 'marimba', 'role': 'ostinato'}
    assert MS.parse_extra(' piano : Arpeggio ') == {'voice': 'piano', 'role': 'arpeggio'}
    assert MS.parse_extra('') is None
    with pytest.raises(ValueError):
        MS.parse_extra('kazoo:double')
    with pytest.raises(ValueError):
        MS.parse_extra('piano:noodling')
