#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""melody_sampler — the sampled-instrument renderer for composed song plans.

    ../.venv/bin/python -m pytest tests/test_melody_sampler.py

What is asserted here is what would silently rot:

* every voice in the vocabulary still resolves against the 66k-file instruments
  library, with the pitch range it had when it was chosen — a re-ingest that
  renames a folder or drops a pack turns a voice into silence, and the only
  symptom downstream is a thin mix nobody can explain;
* a render is deterministic to the bit, because a re-render of a stored plan
  has to reproduce the episode that shipped;
* a plan renders to a wav of the right length and a sane level;
* the licence fence sees the samples that were actually played, and a
  CC-BY sample really does surface its credit line.
"""

import json
import os

import pytest

from tests import _tree
from zyg_workflows import kids_music_theory as T
from zyg_workflows import melody_sampler as MS

np = pytest.importorskip('numpy')
pytest.importorskip('soundfile')

# (midi_lo, midi_hi) measured over the library on 2026-09-06. The test allows
# +-2 semitones: a pack refresh may add or drop an extreme note, but a voice
# that has moved further than that is no longer the instrument it was picked
# to be.
#
# NOTE 'viola': the plan of record said 48-102. The library's viola arco-normal
# recordings actually stop at D7 = 98 (checked with and without the length
# filter), so 98 is what is asserted.
EXPECTED_RANGE = {
    'piano': (9, 96),
    'grand_piano': (22, 104),
    'guitar_nylon': (31, 84),
    'guitar_steel': (40, 84),
    'guitar_electric': (36, 85),
    'ukulele': (60, 84),
    'mandolin': (55, 93),
    'banjo': (48, 88),
    'harp': (28, 101),
    'folk_harp': (24, 80),
    'glockenspiel': (67, 96),
    'xylophone': (55, 96),
    'marimba': (29, 84),
    'vibraphone': (41, 76),
    'kalimba': (31, 85),
    'hand_chimes': (48, 84),
    'tubular_bells': (60, 82),
    'balafon': (49, 77),
    'steel_drum': (60, 83),
    'recorder': (60, 84),
    'recorder_alto': (53, 76),
    'ocarina': (66, 93),
    'flute': (60, 101),
    'clarinet': (50, 96),
    'oboe': (58, 94),
    'bassoon': (34, 79),
    'harmonica': (36, 84),
    'trumpet': (40, 88),
    'french_horn': (34, 77),
    'trombone': (40, 89),
    'tuba': (22, 65),
    'violin': (55, 103),
    'violin_pizz': (55, 93),
    'violin_trem': (55, 88),
    'viola': (48, 98),
    'cello': (36, 84),
    'cello_pizz': (24, 60),
    'double_bass': (24, 67),
    'double_bass_pizz': (28, 55),
    'strings_sus': (43, 74),
    'strings_sus_low': (24, 65),
    'strings_pizz': (43, 74),
    'strings_trem': (43, 74),
    'strings_spic': (43, 74),
    'contrabass_pizz': (16, 47),
    'harpsichord': (14, 72),
    'lute': (22, 76),
    'organ': (24, 84),
    'organ_full': (24, 76),
    'bass_electric': (24, 84),
}


@pytest.fixture(scope='module')
def idx():
    if not os.path.isfile(MS.SIDECAR):
        pytest.skip('instruments sidecar not present on this machine')
    _tree.instrument_samples()
    return MS.index()


# ── (a) the vocabulary resolves ──────────────────────────────────────────────


def test_every_voice_key_is_covered_by_the_expectation_table():
    """A new voice must arrive with its measured range, not untested."""
    playable = {k for k, sel in MS.VOICES.items() if sel is not None}
    assert playable == set(EXPECTED_RANGE)
    assert MS.VOICES['timpani'] is None, 'timpani is a deliberate tombstone'


@pytest.mark.parametrize('key', sorted(EXPECTED_RANGE))
def test_voice_resolves_with_the_expected_range(idx, key):
    info = MS.voice_info(key)
    assert info['count'] >= 6, f'{key}: only {info["count"]} pitched samples'
    lo, hi = EXPECTED_RANGE[key]
    assert abs(info['midi_lo'] - lo) <= 2, f'{key}: lo {info["midi_lo"]} != {lo}'
    assert abs(info['midi_hi'] - hi) <= 2, f'{key}: hi {info["midi_hi"]} != {hi}'
    assert info['packs'] and all(info['licences'].values())


def test_index_is_cached_against_the_sidecar_stamp(idx):
    """The 65 MB sidecar must not be re-parsed on every render."""
    assert os.path.isfile(MS.INDEX_CACHE)
    with open(MS.INDEX_CACHE, 'r', encoding='utf-8') as f:
        doc = json.load(f)
    assert doc['sidecar'] == MS._sidecar_stamp()
    assert set(doc['voices']) == set(EXPECTED_RANGE)


def test_pitch_is_read_from_meta_not_from_the_slugged_file_id():
    assert MS.pitch_to_midi('C4') == 60
    assert MS.pitch_to_midi('A#4') == 70
    assert MS.pitch_to_midi('Bb3') == 58
    assert MS.pitch_to_midi(None) is None
    assert MS.pitch_to_midi('kick') is None


# ── (b) render_events ────────────────────────────────────────────────────────


def test_render_events_is_audible_correctly_sized_and_deterministic(idx):
    events = [(i * 0.5, 0.5, 60 + 2 * i, 100) for i in range(4)]
    audio, stats = MS.render_events(events, 'ukulele')

    assert audio.dtype == np.float32 and audio.ndim == 2 and audio.shape[1] == 2
    assert abs(audio.shape[0] / MS.SR - (4 * 0.5 + 2.5)) < 0.1
    assert float(np.abs(audio).max()) > 0.01, 'render is silent'
    assert stats['notes'] == 4
    assert stats['shifted_octave'] == 0  # 60-66 is inside 60-84
    assert stats['max_shift_used'] <= 7
    assert stats['files'] and stats['files'] <= {r['file_id'] for r in idx['ukulele']}

    again, stats2 = MS.render_events(events, 'ukulele')
    assert np.array_equal(audio, again), 'the same call twice must be bit-identical'
    assert stats2['files'] == stats['files']


def test_notes_outside_the_recorded_range_are_octave_folded_and_counted(idx):
    """A C1 on a ukulele (60-84) is played an octave-folded C, not a rumble."""
    _audio, stats = MS.render_events([(0.0, 0.5, 24, 90)], 'ukulele')
    assert stats['shifted_octave'] == 1
    assert stats['max_shift_used'] <= 7


# ── (c) render_plan ──────────────────────────────────────────────────────────


@pytest.fixture(scope='module')
def rendered(idx, tmp_path_factory):
    plan = T.compose_best(
        {'theme': 'a sampled test song', 'age_band': 'preschool', 'mood': 'happy', 'seconds': 30}, candidates=6
    )
    out = str(tmp_path_factory.mktemp('ms') / 'song.wav')
    res = MS.render_plan(plan, out, voices={'lead': 'glockenspiel', 'pad': 'guitar_nylon', 'bass': 'double_bass_pizz'})
    return plan, res


def test_render_plan_writes_a_song_of_the_right_length_and_level(rendered):
    import soundfile as sf

    _plan, res = rendered
    assert res['ok'] is True
    assert os.path.isfile(res['path'])
    info = sf.info(res['path'])
    assert info.samplerate == MS.SR and info.channels == 2
    assert info.subtype == 'PCM_16'
    assert abs(info.duration - 30.0) <= 3.0, f'{info.duration:.1f}s'
    assert 0.2 < res['peak'] <= 0.98
    assert all(res['files'][role] for role in ('lead', 'pad', 'bass'))
    assert res['voices']['lead']['transpose'] == 12, 'glockenspiel plays +12'
    assert res['out_of_range_notes'] == 0


def test_render_plan_refuses_a_voice_with_no_samples(rendered, tmp_path):
    plan, _res = rendered
    out = str(tmp_path / 'nope.wav')
    res = MS.render_plan(plan, out, voices={'lead': 'timpani', 'pad': 'harp', 'bass': 'cello'})
    assert res['ok'] is False
    assert not os.path.exists(out), 'a failed render must not leave a wav behind'


# ── (d) licences ─────────────────────────────────────────────────────────────


def test_credits_pass_for_a_rendered_song(rendered):
    _plan, res = rendered
    refs = MS.licence_refs(res['files'])
    assert refs and all(cat == 'instruments' for cat, _ in refs)
    gate = MS.credits(res['files'])
    assert gate['ok'] is True, gate['violations']
    assert gate['violations'] == []


def test_a_cc_by_sample_surfaces_its_credit_line(idx):
    """CC-BY is commercial-ok *and* attribution-required: the line must appear."""
    fid = 'sfzi_salamandergrandpiano_a0v1.wav'
    assert os.path.isfile(os.path.join(MS.LIB_DIR, fid)), 'fixture file missing'
    gate = MS.credits([fid])
    assert gate['ok'] is True, gate['violations']
    assert gate['attributions'], 'a cc-by-3.0 sample produced no credit line'
    assert any('CC BY' in a for a in gate['attributions'])
