# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The STYLE layer of kids_music_theory: the 11 children's styles.

A style is a set of DEFAULTS, not a lock — which is the whole thing worth
testing. Two properties matter more than any individual value:

  * a brief WITHOUT a style must come out of _normalise_brief exactly as it did
    before the layer existed (test_no_style_brief_is_unchanged holds the literal
    pre-change JSON, captured from the module before it was edited);
  * an explicit operator value must still win over the style, exactly as an
    explicit mood already wins over an age band.

The voice vocabulary is hard-coded here on purpose. It is the contract between
this table and the sampler that resolves those keys against the instrument
library; a typo in a voice key would otherwise only surface as silence at
render time.
"""

import json

import pytest

from zyg_workflows import kids_music_theory as T


# The fixed voice vocabulary. Written out rather than derived from STYLES —
# a test that reads its expectation out of the thing under test proves nothing.
# 'kalimba' and 'glockenspiel' were in this list until 2026-09-06: both are still
# real sampler voices, but as LEADS they lost the mix gate (a struck note that
# stops while the bass holds), so no children's style names them any more. Re-add
# the name here if a style takes one back, and re-run
# tools/measure_style_margins.py before believing it ships.
LEAD_VOICES = {
    'xylophone',
    'recorder',
    'recorder_alto',
    'hand_chimes',
    'ukulele',
    'marimba',
    'harmonica',
    'clarinet',
    'flute',
    'vibraphone',
}
PAD_VOICES = {'guitar_nylon', 'harp', 'piano', 'strings_sus', 'guitar_steel'}
# 'cello' survives as a bass only where the lead out-sustains it (seasons' flute).
BASS_VOICES = {'double_bass_pizz', 'cello_pizz', 'cello', 'bass_electric', 'tuba'}

STYLE_KEYS = [
    'playtime',
    'sleeptime',
    'storytime',
    'learning',
    'lullaby',
    'nursery',
    'counting',
    'singalong',
    'animals',
    'seasons',
    'bedtime',
]

# Captured from the module BEFORE the style layer was added:
#   ../.venv/bin/python -c "import kids_music_theory as T, json; \
#       print(json.dumps(T._normalise_brief({'theme':'x'}), sort_keys=True))"
# singer: adult_male since 2026-09-10, when DEFAULT_SINGER moved to the
# operator's 'Warm Control' voice. Nothing else in this dict moved.
BASELINE_NO_STYLE = {
    'age_band': 'preschool',
    'bpm': 117,
    'form': 'AABA',
    'lyrics_lines': [],
    'lyrics_mode': 'theme',
    'lyrics_truncated': 0,
    'meter': '4/4',
    # seconds: 150.0 since 2026-10-02 — the operator moved every children's song
    # into kids_music_theory.SONG_SECONDS (130-210 s), and 150 is the middle of
    # the part of it that MEASURES clean (see song_seconds): a brief with no style
    # and no length of its own gets that. Nothing else in this dict moved.
    'mode': 'major',
    'mood': 'happy',
    'seconds': 150.0,
    'singer': 'adult_male',
    'subject': '',
    'sung': True,
    'theme': 'x',
    'title': '',
    'tonic': 'D',
    'tonic_pc': 2,
}


# ── (a) the table itself ─────────────────────────────────────────────────────


def test_eleven_styles_and_dance_is_excluded():
    assert list(T.STYLES) == STYLE_KEYS
    assert len(T.STYLES) == 11
    assert 'dance' not in T.STYLES
    # Named, so the panel can say why it is absent instead of looking broken.
    assert 'dance' in T.EXCLUDED_STYLES
    assert T.STYLE_FAMILY == 'children'


@pytest.mark.parametrize('key', STYLE_KEYS)
def test_style_voices_are_in_the_fixed_vocabulary(key):
    v = T.STYLES[key]['voices']
    assert set(v) == {'lead', 'pad', 'bass'}
    assert v['lead'] in LEAD_VOICES
    assert v['pad'] in PAD_VOICES
    assert v['bass'] in BASS_VOICES


@pytest.mark.parametrize('key', STYLE_KEYS)
def test_style_fields_are_coherent(key):
    s = T.STYLES[key]
    assert s['family'] == T.STYLE_FAMILY
    assert s['shelf'] == key
    assert s['mood'] in T.MOODS
    assert s['mood'] in s['moods']
    assert all(m in T.MOODS for m in s['moods'])
    assert s['age_band'] in T.AGE_BANDS
    assert s['form'] in T.FORMS
    assert s['meter'] is None or s['meter'] in T.METERS
    # Every children's FORMAT lives in the band (2026-10-02): a format's seconds
    # is its place in it, not a free number.
    assert T.SONG_SECONDS[0] <= s['seconds'] <= T.SONG_SECONDS[1]
    assert s['lyrics_mode'] in T.LYRICS_MODES
    assert s['ace_tags'] and s['look'] and s['clap_pos']
    # 'dance' is excluded, so no style may reach for it as a motif either.
    assert 'dance' not in s['burst_motifs'] + s['fill_motifs']


# ── (b) a style supplies its defaults ────────────────────────────────────────


def test_lullaby_style_supplies_its_defaults():
    b = T._normalise_brief({'theme': 'x', 'style': 'lullaby'})
    assert b['style'] == 'lullaby'
    assert b['mood'] == 'lullaby'
    assert b['age_band'] == 'toddler'
    assert b['meter'] == '6/8'
    assert b['form'] == 'AABA'
    assert b['seconds'] == 200.0  # the band's top end: a lullaby is long by nature
    assert b['shelf'] == 'lullaby'
    assert b['family'] == 'children'
    assert b['voices'] == {'lead': 'hand_chimes', 'pad': 'strings_sus', 'bass': 'cello_pizz'}
    assert b['style_perc'] is False


# ── (c) explicit values still win; the style only fills the gaps ─────────────


def test_mood_outside_the_style_is_replaced_and_inside_is_kept():
    # 'marching' is not a Sleeptime mood — the style wins, or "Sleeptime" would
    # be a label on a brass band.
    b = T._normalise_brief({'theme': 'x', 'style': 'sleeptime', 'mood': 'marching'})
    assert b['mood'] == 'lullaby'
    # 'gentle' IS a Sleeptime mood — the operator's choice is honoured.
    b = T._normalise_brief({'theme': 'x', 'style': 'sleeptime', 'mood': 'gentle'})
    assert b['mood'] == 'gentle'


def test_explicit_values_beat_the_style():
    b = T._normalise_brief(
        {
            'theme': 'x',
            'style': 'lullaby',
            'age_band': 'early',
            'meter': '3/4',
            'form': 'ABAB',
            'seconds': 40,
        }
    )
    assert b['age_band'] == 'early'
    assert b['meter'] == '3/4'
    assert b['form'] == 'ABAB'
    assert b['seconds'] == 40.0
    # …but the style is still recorded, and still supplies what was not given.
    assert b['style'] == 'lullaby'
    assert b['voices']['lead'] == 'hand_chimes'


def test_unknown_style_is_dropped_not_raised():
    b = T._normalise_brief({'theme': 'x', 'style': 'no-such-style'})
    assert b['style'] is None
    # …and nothing else moved: it is the plain default brief plus that one key.
    assert {k: v for k, v in b.items() if k != 'style'} == BASELINE_NO_STYLE


# ── (d) a brief without a style is untouched ─────────────────────────────────


def test_no_style_brief_is_unchanged():
    b = T._normalise_brief({'theme': 'x'})
    assert b == BASELINE_NO_STYLE
    # No style key at all — not `'style': None`. Every downstream reader that
    # predates this layer must see the dict it has always seen.
    for k in ('style', 'family', 'shelf', 'voices', 'style_perc'):
        assert k not in b, f'{k} leaked into a brief that named no style'


def test_no_style_plan_keeps_the_mood_instrumentation():
    p = T.compose({'theme': 'x'}, seed=0)
    assert p['style'] is None
    assert p['voices'] is None
    assert p['percussion'] == T.MOODS['happy']['perc']
    assert p['instruments'] == {k: T.MOODS['happy'][k] for k in ('lead', 'pad', 'bass')}


# ── (e) every style composes a plan that passes its gate ─────────────────────


@pytest.mark.parametrize('key', STYLE_KEYS)
def test_every_style_composes_a_passing_plan(key):
    s = T.STYLES[key]
    p = T.compose_best({'theme': 'self test', 'style': key}, candidates=8)
    sc = p['score']
    assert sc['ok'], f'{key}: {"; ".join(sc.get("fails") or [])}'
    assert p['style'] == key
    assert p['brief']['age_band'] == s['age_band']
    # The sampled voices ride the plan; the GM programs stay for the SoundFont.
    assert p['voices'] == s['voices']
    assert p['percussion'] is s['perc']


def test_counting_style_is_a_single_tiled_phrase():
    b = T._normalise_brief({'theme': 'counting to five', 'style': 'counting'})
    assert b['lyrics_mode'] == 'counting'
    assert b['form'] == 'AAAA'
    p = T.compose_best({'theme': 'counting to five', 'style': 'counting'}, candidates=8)
    assert p['form'] == 'AAAA'
    assert set(p['order']) == {'A'}


def test_counting_is_a_valid_lyrics_mode_without_a_style():
    b = T._normalise_brief({'theme': 'x', 'lyrics_mode': 'counting'})
    assert b['lyrics_mode'] == 'counting'
    # Same reason 'facts' does it: one phrase, every line.
    assert b['form'] == 'AAAA'


# ── (f) the UI vocabulary ────────────────────────────────────────────────────


def test_ui_spec_carries_the_styles():
    spec = T.ui_spec()
    assert len(spec['styles']) == 11
    assert [s['key'] for s in spec['styles']] == STYLE_KEYS
    assert 'dance' in spec['styles_excluded']
    assert 'counting' in [m['key'] for m in spec['lyrics_modes']]
    for s in spec['styles']:
        assert set(s) == {
            'key',
            'label',
            'shelf',
            'mood',
            'moods',
            'age_band',
            'form',
            'meter',
            'seconds',
            'lyrics_mode',
            'voices',
        }
    # It is handed to a browser, so it has to survive JSON.
    json.dumps(spec)


# ── helpers ──────────────────────────────────────────────────────────────────


def test_style_for_plan_and_clap_captions():
    p = T.compose({'theme': 'x', 'style': 'bedtime'}, seed=0)
    assert T.style_for_plan(p)['label'] == 'Bath & Bedtime Routine'
    assert T.style_for_plan(T.compose({'theme': 'x'}, seed=0)) is None

    # A lullaby measured against "a cheerful children's song" is being graded on
    # the wrong question — that is what these captions exist to prevent.
    assert T.clap_captions('lullaby') == [
        'a gentle lullaby for children',
        'soft calm music for a sleeping child',
        'slow soothing nursery melody',
    ]
    assert T.clap_captions(None) == T.DEFAULT_CLAP_POS
    assert T.clap_captions('no-such-style') == T.DEFAULT_CLAP_POS
    # A caller must not be able to mutate the table through the return value.
    T.clap_captions('lullaby').append('junk')
    assert len(T.STYLES['lullaby']['clap_pos']) == 3
