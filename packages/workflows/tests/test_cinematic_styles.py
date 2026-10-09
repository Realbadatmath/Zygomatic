# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The cinematic family: thirteen INSTRUMENTAL cues on their own band.

What these tests are actually defending, in order of how expensive the mistake
would be to find later:

  1. The children's family did not move. The cinematic band composes EIGHT-bar
     sections instead of four, which is a change inside compose()'s hot loop —
     the one place where a family flag read one line too early would silently
     rewrite every nursery rhyme in the catalogue. `test_children_plan_is_byte_
     identical` pins a sha256 measured on the module BEFORE this layer existed.
  2. Every instrument named in the table exists in the sampler. A style is a
     commission; a voice key that melody_sampler cannot resolve is a commission
     nobody can play, and it would not surface until render time.
  3. 'storytime' means two different things. It is the one key in both families,
     so the family must decide which one a brief gets — and the default must
     stay 'children', because every caller that predates this layer omits it.
  4. All thirteen pass the musical gate at THEIR OWN defaults. Not at some
     tuned-until-green tempo: at the tempo and metre the operator will pick.
"""

import hashlib
import json

import pytest

from zyg_workflows import kids_music_theory as T


# ── The table ────────────────────────────────────────────────────────────────

EXPECTED = {
    'cheerful': ('major', '4/4', (112, 132), 'ABAB', 60),
    'sad': ('natural_minor', '4/4', (58, 72), 'AABA', 75),
    'heroic': ('major', '4/4', (96, 116), 'AABA', 70),
    'tavern': ('mixolydian', '6/8', (108, 132), 'AABA', 60),
    'storytime': ('major', '3/4', (80, 96), 'ABAC', 70),
    'sonata': ('major', '4/4', (88, 108), 'AABA', 80),
    'suspense': ('natural_minor', '4/4', (66, 84), 'ABAB', 70),
    'romance': ('major', '3/4', (72, 88), 'AABA', 75),
    'wonder': ('major', '4/4', (84, 100), 'ABAC', 75),
    'mystery': ('minor_pentatonic', '4/4', (70, 86), 'ABAB', 70),
    'chase': ('natural_minor', '4/4', (140, 168), 'ABAB', 60),
    'melancholy': ('natural_minor', '3/4', (60, 76), 'AABA', 75),
    'triumph': ('major', '4/4', (100, 120), 'AAB', 60),
}


def test_thirteen_styles_with_the_agreed_musical_defaults():
    assert len(T.CINEMATIC_STYLES) == 13
    assert set(T.CINEMATIC_STYLES) == set(EXPECTED)
    for key, (mode, meter, bpm, form, secs) in EXPECTED.items():
        S = T.CINEMATIC_STYLES[key]
        assert (S['mode'], S['meter'], tuple(S['bpm']), S['form'], S['seconds']) == (mode, meter, bpm, form, secs), key
        assert S['mode'] in T.MODES and S['meter'] in T.METERS and S['form'] in T.FORMS
        assert S['bpm'][0] < S['bpm'][1]


def test_every_entry_is_instrumental_and_belongs_to_the_cinematic_family():
    for key, S in T.CINEMATIC_STYLES.items():
        assert S['family'] == T.CINEMATIC_FAMILY == 'cinematic', key
        assert S['shelf'] == key, key
        # The two flags that make this family what it is: nobody sings, and
        # nothing keeps time with a drum kit.
        assert S['sung'] is False, key
        assert S['perc'] is False, key
        assert S['mood'] == 'cinematic', key
        assert S['label'] and S['ace_tags'] and len(S['clap_pos']) == 3, key
        # NO PICTURE LEG. A `look` or a motif pool here would advertise a video
        # path this family does not have.
        assert not {'look', 'burst_motifs', 'fill_motifs'} & set(S), key


def test_the_cinematic_mood_exists_and_is_wide_enough_for_all_thirteen():
    mo = T.MOODS['cinematic']
    assert mo['label'] == 'Cinematic'
    assert mo['perc'] is False
    # GM string ensemble over contrabass: the SoundFont fallback, not the real
    # instrumentation (that is each style's `voices`).
    assert (mo['lead'], mo['pad'], mo['bass']) == (48, 48, 43)
    for key, S in T.CINEMATIC_STYLES.items():
        assert S['mode'] in mo['modes'], key
        assert S['meter'] in mo['meters'], key
        assert mo['bpm'][0] <= S['bpm'][0] and S['bpm'][1] <= mo['bpm'][1], key


# ── The instruments have to exist ────────────────────────────────────────────


def test_every_voice_resolves_in_the_sampler():
    """lead/pad/bass AND the extra part, checked against the live vocabulary.

    Hard-coding the list here would only assert that this file agrees with
    itself; melody_sampler.VOICES is what actually has to hold the name.
    """
    MS = pytest.importorskip('melody_sampler')
    for key, S in T.CINEMATIC_STYLES.items():
        for role in ('lead', 'pad', 'bass'):
            assert S['voices'][role] in MS.VOICES, f'{key}.{role}={S["voices"][role]}'
        assert S['extra']['voice'] in MS.VOICES, f'{key}.extra'


def test_every_extra_names_one_of_the_four_arranger_roles():
    assert T.EXTRA_ROLES == ('double', 'counter', 'ostinato', 'arpeggio')
    for key, S in T.CINEMATIC_STYLES.items():
        assert set(S['extra']) == {'voice', 'role'}, key
        assert S['extra']['role'] in T.EXTRA_ROLES, key


# ── The band ─────────────────────────────────────────────────────────────────


def test_the_cinematic_band_is_an_instrument_range_not_an_age():
    band = T.AGE_BANDS['cinematic']
    assert band['instrumental'] is True
    assert band['long_phrases'] is True
    assert (band['lo'], band['hi']) == (55, 84)  # G3-C6
    assert band['max_leap'] == 12 and band['max_span'] == 19
    assert band['bpm'] == (50, 176)
    # Wide enough for every style's window, or the tempo would be clamped twice.
    for key, S in T.CINEMATIC_STYLES.items():
        assert band['bpm'][0] <= S['bpm'][0] and S['bpm'][1] <= band['bpm'][1], key


# ── style_lookup and the 'storytime' collision ───────────────────────────────


def test_storytime_defaults_to_children_and_needs_a_family_to_be_cinematic():
    assert 'storytime' in T.STYLES and 'storytime' in T.CINEMATIC_STYLES
    fam, entry = T.style_lookup('storytime')
    assert fam == 'children' and entry is T.STYLES['storytime']
    fam, entry = T.style_lookup('storytime', 'cinematic')
    assert fam == 'cinematic' and entry is T.CINEMATIC_STYLES['storytime']
    fam, entry = T.style_lookup('storytime', 'children')
    assert fam == 'children' and entry is T.STYLES['storytime']


def test_storytime_is_the_only_key_shared_by_the_two_families():
    assert set(T.STYLES) & set(T.CINEMATIC_STYLES) == {'storytime'}


def test_style_lookup_refuses_the_wrong_family_and_unknown_keys():
    assert T.style_lookup('chase', 'children') == (None, None)
    assert T.style_lookup('lullaby', 'cinematic') == (None, None)
    assert T.style_lookup('no-such-style') == (None, None)
    assert T.style_lookup(None) == (None, None)
    assert T.style_lookup('') == (None, None)
    # Every other cinematic key is reachable without naming the family.
    for key in T.CINEMATIC_STYLES:
        if key != 'storytime':
            assert T.style_lookup(key)[0] == 'cinematic', key


def test_the_two_families_are_separate_dicts_not_a_namespaced_merge():
    assert set(T.STYLE_FAMILIES) == {'children', 'cinematic'}
    assert T.STYLE_FAMILIES['children']['styles'] is T.STYLES
    assert T.STYLE_FAMILIES['cinematic']['styles'] is T.CINEMATIC_STYLES
    # Keys stay bare — everything downstream reads brief['style'] as one.
    assert not any('/' in k for k in T.CINEMATIC_STYLES)


# ── _normalise_brief ─────────────────────────────────────────────────────────


def test_normalise_brief_chase():
    b = T._normalise_brief({'theme': 'x', 'style': 'chase', 'family': 'cinematic'})
    assert b['age_band'] == 'cinematic'
    assert b['mood'] == 'cinematic'
    assert b['sung'] is False
    assert b['mode'] == 'natural_minor'
    assert b['meter'] == '4/4'
    assert b['form'] == 'ABAB'
    assert 140 <= b['bpm'] <= 168
    assert b['family'] == 'cinematic'
    assert b['shelf'] == 'chase'
    assert b['style_perc'] is False
    assert b['voices'] == {'lead': 'trumpet', 'pad': 'strings_spic', 'bass': 'contrabass_pizz'}
    assert b['extra'] == {'voice': 'marimba', 'role': 'ostinato'}


def test_normalise_brief_resolves_storytime_by_family():
    child = T._normalise_brief({'theme': 'x', 'style': 'storytime'})
    assert child['family'] == 'children'
    assert child['age_band'] == 'preschool' and child['sung'] is True
    cine = T._normalise_brief({'theme': 'x', 'style': 'storytime', 'family': 'cinematic'})
    assert cine['family'] == 'cinematic'
    assert cine['age_band'] == 'cinematic' and cine['sung'] is False
    assert cine['meter'] == '3/4' and cine['voices']['lead'] == 'oboe'


def test_a_cinematic_brief_can_never_be_sung_and_says_so():
    b = T._normalise_brief({'theme': 'x', 'style': 'sad', 'family': 'cinematic', 'sung': True})
    assert b['sung'] is False
    assert b['sung_forced_off'] is True
    # Not asked for, not reported — the flag means "we overrode you".
    assert 'sung_forced_off' not in T._normalise_brief({'theme': 'x', 'style': 'sad', 'family': 'cinematic'})


def test_the_band_and_mood_are_not_negotiable_for_a_cinematic_style():
    b = T._normalise_brief(
        {'theme': 'x', 'style': 'chase', 'family': 'cinematic', 'age_band': 'toddler', 'mood': 'lullaby'}
    )
    assert b['age_band'] == 'cinematic' and b['mood'] == 'cinematic'


def test_an_explicit_mode_meter_and_form_still_win():
    b = T._normalise_brief(
        {'theme': 'x', 'style': 'chase', 'family': 'cinematic', 'mode': 'major', 'meter': '3/4', 'form': 'AABA'}
    )
    assert (b['mode'], b['meter'], b['form']) == ('major', '3/4', 'AABA')


def test_tempo_inside_the_style_window_wins_and_outside_it_is_clamped():
    lo, hi = T.CINEMATIC_STYLES['chase']['bpm']
    mk = lambda bpm: T._normalise_brief({'theme': 'x', 'style': 'chase', 'family': 'cinematic', 'bpm': bpm})['bpm']
    assert mk(150) == 150
    assert mk(60) == lo  # a 60 bpm chase is a different cue
    assert mk(190) == hi
    assert lo <= mk(None) <= hi


def test_seconds_default_from_the_style_and_an_explicit_value_wins():
    b = T._normalise_brief({'theme': 'x', 'style': 'sonata', 'family': 'cinematic'})
    assert b['seconds'] == 80
    b = T._normalise_brief({'theme': 'x', 'style': 'sonata', 'family': 'cinematic', 'seconds': 45})
    assert b['seconds'] == 45


# ── compose: the eight-bar phrase, and the children's family untouched ───────


def test_cinematic_sections_are_eight_bars_and_children_stay_four():
    p = T.compose({'theme': 'x', 'style': 'chase', 'family': 'cinematic'}, seed=1)
    assert all(s['bar_end'] - s['bar_start'] + 1 == 8 for s in p['sections'])
    assert p['melody'][-1]['line'] == 4 * len(p['sections']) - 1
    q = T.compose({'theme': 'x', 'style': 'lullaby'}, seed=1)
    assert all(s['bar_end'] - s['bar_start'] + 1 == 4 for s in q['sections'])
    assert q['melody'][-1]['line'] == 2 * len(q['sections']) - 1


def test_lines_per_section_is_the_only_switch():
    assert T._lines_per_section(T.AGE_BANDS['cinematic']) == 4
    for band in ('toddler', 'preschool', 'early'):
        assert T._lines_per_section(T.AGE_BANDS[band]) == 2


def test_a_composed_cue_carries_family_voices_and_the_extra_part():
    p = T.compose({'theme': 'x', 'style': 'romance', 'family': 'cinematic'}, seed=3)
    assert p['family'] == 'cinematic'
    assert p['style'] == 'romance'
    assert p['voices'] == T.CINEMATIC_STYLES['romance']['voices']
    assert p['extra'] == {'voice': 'piano', 'role': 'arpeggio'}
    assert p['percussion'] is False
    # The GM trio behind it is the cinematic mood's, for the SoundFont path.
    assert p['instruments'] == {'lead': 48, 'pad': 48, 'bass': 43}


def test_a_childrens_plan_has_no_extra_part():
    p = T.compose({'theme': 'x', 'style': 'lullaby'}, seed=1)
    assert p['family'] == 'children'
    assert p['extra'] is None


# The sha256 of the MUSIC of a children's plan: every note, duration, chord,
# section boundary, form, key, tempo and score. What it deliberately does NOT
# cover is the orchestration — which is why these keys are stripped first:
#
#   family, extra          added by the cinematic layer; a whole-plan hash could
#                          only ever have recorded that the addition happened.
#   voices, instruments,   the voice table (STYLES[...]['voices']) and the GM
#   brief.voices           programme numbers derived from it. Which instrument
#                          plays a note is a mixing decision that is re-measured
#                          whenever the sampler is re-balanced; it must be free
#                          to move without breaking this pin. (It did move, on
#                          2026-09-06: learning, sleeptime, lullaby and nursery
#                          were all revoiced.)
#
# So the invariant this pins is exactly "the MUSIC did not move by one tick",
# independent of who plays it. Stripping those keys is verified to make the
# hash stable across a voice-table change.
CHILDREN_PLAN_MUSIC_SHA256 = 'f6ed30d5ee3ee1d97fce7d78888ed0c91307d7f0f4997fe00c4ae22ae398add1'  # re-pinned 2026-10-02: every children's song moved into SONG_SECONDS (130-210 s), so the lullaby this pins is 200 s and not 80 — more bars is more music, by instruction

# Keys that carry orchestration, not music.
_VOICING_KEYS = ('family', 'extra', 'voices', 'instruments')


def test_children_plan_music_is_byte_identical_to_before_the_cinematic_layer():
    # The singer is named, not defaulted: DEFAULT_SINGER went adult_male on
    # 2026-09-10 and the male entry has no sung_window, so a defaulted brief
    # would move this pin for a reason that is not the composer's.
    p = T.compose({'theme': 'x', 'style': 'lullaby', 'singer': 'adult_female'}, seed=1)
    assert set(p) >= {'family', 'extra', 'voices', 'instruments'}
    core = {k: v for k, v in p.items() if k not in _VOICING_KEYS}
    core['brief'] = {k: v for k, v in p['brief'].items() if k != 'voices'}
    got = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    assert got == CHILDREN_PLAN_MUSIC_SHA256, (
        "the music of a children's plan moved — long_phrases must be read "
        'from the band, never applied unconditionally. (Revoicing a style '
        'cannot reach this hash; if only the instruments changed, something '
        'else is stripping the wrong key.)'
    )


def test_the_children_plan_pin_does_not_depend_on_the_voice_table():
    """Revoicing a style must not be able to break the pin above."""
    style = T.STYLES['lullaby']
    kept = style['voices']
    style['voices'] = {'lead': 'ocarina', 'pad': 'organ_full', 'bass': 'double_bass_pizz'}
    try:
        p = T.compose({'theme': 'x', 'style': 'lullaby', 'singer': 'adult_female'}, seed=1)
        assert p['voices']['bass'] == 'double_bass_pizz'
        core = {k: v for k, v in p.items() if k not in _VOICING_KEYS}
        core['brief'] = {k: v for k, v in p['brief'].items() if k != 'voices'}
        got = hashlib.sha256(json.dumps(core, sort_keys=True).encode()).hexdigest()
    finally:
        style['voices'] = kept
    assert got == CHILDREN_PLAN_MUSIC_SHA256


# ── the gate ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize('style', sorted(EXPECTED))
def test_every_cue_passes_the_gate_at_its_own_defaults(style):
    p = T.compose_best({'theme': 'self test', 'style': style, 'family': 'cinematic'}, candidates=8)
    sc = p['score']
    assert sc['ok'], f'{style}: ' + '; '.join(sc['fails'])
    assert sc['invariants_ok'], f'{style}: {sc["invariants"]}'
    band = T.AGE_BANDS['cinematic']
    m = sc['metrics']
    assert band['lo'] <= min(n['p'] for n in p['melody'])
    assert max(n['p'] for n in p['melody']) <= band['hi']
    assert m['notes_per_second'] <= band['max_density']
    lo, hi = T.CINEMATIC_STYLES[style]['bpm']
    assert lo <= p['bpm'] <= hi


# ── ui_spec ──────────────────────────────────────────────────────────────────


def test_ui_spec_carries_both_families_and_the_thirteen_cues():
    spec = T.ui_spec()
    assert spec['families'] == [
        {'key': 'children', 'label': "Children's Music"},
        {'key': 'cinematic', 'label': 'Cinematic'},
    ]
    cine = spec['cinematic_styles']
    assert len(cine) == 13
    assert [c['key'] for c in cine] == list(T.CINEMATIC_STYLES)
    for c in cine:
        S = T.CINEMATIC_STYLES[c['key']]
        assert c['label'] == S['label'] and c['shelf'] == S['shelf']
        assert c['mode'] == S['mode'] and c['meter'] == S['meter']
        assert c['bpm'] == list(S['bpm']) and c['form'] == S['form']
        assert c['seconds'] == S['seconds']
        assert c['voices'] == S['voices'] and c['extra'] == S['extra']
    # The children's list did not grow the cinematic cues.
    assert len(spec['styles']) == len(T.STYLES) == 11
    assert 'chase' not in [s['key'] for s in spec['styles']]


def test_ui_spec_marks_the_cinematic_band_as_instrumental():
    bands = {b['key']: b for b in T.ui_spec()['age_bands']}
    assert bands['cinematic']['instrumental'] is True
    assert bands['cinematic']['label'] == 'Instrumental (cinematic)'
    for k in ('toddler', 'preschool', 'early'):
        assert bands[k]['instrumental'] is False


def test_ui_spec_is_json_serialisable():
    json.dumps(T.ui_spec())


# ── clap captions ────────────────────────────────────────────────────────────


# The literal captions are NOT pinned here: they are a measured artefact and
# get rewritten whenever a cue is re-scored against CLAP (mystery and suspense
# were, on 2026-09-06). What must hold is the shape and the family routing.
def test_clap_captions_are_family_aware():
    children_captions = set(T.DEFAULT_CLAP_POS)
    for s in T.STYLES.values():
        children_captions |= set(s['clap_pos'])

    for key in T.CINEMATIC_STYLES:
        caps = T.clap_captions(key, 'cinematic')
        assert caps == T.CINEMATIC_STYLES[key]['clap_pos'], key
        assert len(caps) == 3, key
        assert all(isinstance(c, str) and c.strip() for c in caps), key
        assert len(set(caps)) == 3, key
        # A cinematic cue never asks CLAP for a nursery rhyme.
        assert not (set(caps) & children_captions), key

    # A cinematic-only key is NOT reachable without its family: the default is
    # 'children', so an unfamilied caller gets the children's default list.
    assert 'chase' not in T.STYLES
    assert T.clap_captions('chase') == T.DEFAULT_CLAP_POS
    # storytime without a family is still the children's song it always was.
    assert T.clap_captions('storytime') == T.STYLES['storytime']['clap_pos']
    assert T.clap_captions('storytime', 'cinematic') == T.CINEMATIC_STYLES['storytime']['clap_pos']
    assert T.clap_captions('storytime') != T.clap_captions('storytime', 'cinematic')
    assert T.clap_captions('no-such-style') == T.DEFAULT_CLAP_POS
    assert T.clap_captions('no-such-style', 'cinematic') == T.DEFAULT_CLAP_POS
    # A caller may not mutate the table through the returned list.
    T.clap_captions('sad', 'cinematic').append('junk')
    assert len(T.CINEMATIC_STYLES['sad']['clap_pos']) == 3


def test_style_for_plan_resolves_the_cinematic_family():
    p = T.compose({'theme': 'x', 'style': 'storytime', 'family': 'cinematic'}, seed=0)
    assert T.style_for_plan(p) is T.CINEMATIC_STYLES['storytime']
    q = T.compose({'theme': 'x', 'style': 'storytime'}, seed=0)
    assert T.style_for_plan(q) is T.STYLES['storytime']
    assert T.style_for_plan(T.compose({'theme': 'x'}, seed=0)) is None
