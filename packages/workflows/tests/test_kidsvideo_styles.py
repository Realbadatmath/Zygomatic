# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The picture leg is style-aware — and still only ever draws flat 2D cartoons.

Three claims, none of which needs a GPU or a model:

  * the look clause follows the STYLE when a song has one and the MOOD when it
    does not, and BASE_STYLE — the flat-2D contract — leads either way;
  * the motif pools are the style's own lists, and 'dance' (the one excluded
    children's style) is in no styled pool;
  * the storyboard actually honours those pools: an 'animals' song bursts on
    animals, not on a counting run it never asked for.

``llm_ideas`` is monkeypatched out, so nothing here talks to ollama.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from zyg_workflows import kids_music_theory as T  # noqa: E402
from zyg_workflows import kids_video_service as V  # noqa: E402


# The literal output of style_for({'mood': 'happy'}) captured from the file
# BEFORE styles were wired in. An unstyled song must render exactly as it did.
HAPPY_BEFORE = (
    'flat 2D cartoon illustration for young children, children picture-book art, '
    'bold clean dark outlines, simple rounded shapes, large friendly forms, '
    'flat colour fills, minimal detail, plain uncluttered background, '
    'cheerful joyful and wholesome, sweet and gentle, safe for toddlers, '
    'bright sunny primary colours, clear blue sky, warm daylight'
)


@pytest.fixture
def no_llm(monkeypatch):
    """No model in this test run: the motif deck fills every slot."""
    monkeypatch.setattr(V, 'llm_ideas', lambda *a, **k: ([], {'hero': 'a duck'}))


# ── (a) the look clause ──────────────────────────────────────────────────────


def test_styled_song_takes_the_style_look_on_top_of_base_style():
    s = V.style_for({'style': 'lullaby'})
    assert s.startswith(V.BASE_STYLE), 'the flat-2D contract must lead the prompt'
    assert 'midnight blue' in s, 'the lullaby colour clause is missing'


def test_unstyled_song_is_byte_identical_to_the_pre_change_output():
    assert V.style_for({'mood': 'happy'}) == HAPPY_BEFORE


def test_unknown_style_falls_back_to_the_mood_palette():
    assert V.style_for({'style': 'no_such_style', 'mood': 'happy'}) == HAPPY_BEFORE


def test_nothing_here_reaches_for_a_photo_or_a_3d_render():
    for key in list(T.STYLES) + [None]:
        s = V.style_for({'style': key} if key else {'mood': 'gentle'})
        low = s.lower()
        for banned in ('photo', '3d', 'render', 'cinematic', 'live action'):
            assert banned not in low, f'{key}: {banned!r} leaked into the style'


# ── (b) the motif pools ──────────────────────────────────────────────────────


def test_counting_draws_its_own_two_lists():
    assert V.motif_pools({'style': 'counting'}) == (['count_up', 'count_down'], ['shapes', 'colours', 'toys'])


def test_no_styled_pool_contains_dance():
    for key in T.STYLES:
        burst, fill = V.motif_pools({'style': key})
        assert 'dance' not in burst and 'dance' not in fill, key
        assert burst and fill, f'{key} was left with an empty pool'
        for m in burst + fill:
            assert m in V.MOTIFS, f'{key} names a motif this file cannot draw: {m}'


def test_unstyled_song_still_gets_the_whole_deck():
    assert V.motif_pools({'mood': 'happy'}) == (V.BURST_MOTIFS, V.FILL_MOTIFS)


def test_a_style_whose_lists_are_all_unknown_falls_back_without_dance(monkeypatch):
    faked = dict(T.STYLES['animals'], burst_motifs=['not_a_motif'], fill_motifs=['dance'])
    monkeypatch.setitem(V.T.STYLES, 'animals', faked)
    burst, fill = V.motif_pools({'style': 'animals'})
    assert burst == [m for m in V.BURST_MOTIFS if m != 'dance']
    assert 'dance' not in fill and fill


# ── (c) the storyboard honours the pools ─────────────────────────────────────


def _fake_slots(n=40, burst_from=10, burst_to=18):
    """The keys plan_slots emits, with one contiguous burst run."""
    out = []
    for i in range(n):
        burst = burst_from <= i < burst_to
        out.append(
            {
                'i': i,
                'start': round(i * 1.0, 3),
                'dur': 1.0,
                'burst': burst,
                'pace': 'burst' if burst else 'normal',
                'name': 'A',
                'role': 'verse',
            }
        )
    return out


def test_an_animals_song_bursts_on_animals_and_never_dances(no_llm):
    brief = {'theme': 'x', 'style': 'animals', 'seconds': 40}
    plan = T.compose_best(brief, candidates=4)
    slots = _fake_slots()
    V.assign_ideas(slots, brief, plan, seed=1)

    burst_motifs = {s['motif'] for s in slots if s['burst']}
    assert burst_motifs == {'animals'}, burst_motifs
    assert all(s['motif'] != 'dance' for s in slots)
    assert all(s['idea'] for s in slots), 'every slot must get a picture'


def test_an_unstyled_song_may_still_use_the_whole_deck(no_llm):
    brief = {'theme': 'x', 'seconds': 40}
    plan = T.compose_best(dict(brief), candidates=4)
    slots = _fake_slots()
    V.assign_ideas(slots, brief, plan, seed=1)
    assert {s['motif'] for s in slots if s['burst']} <= set(V.BURST_MOTIFS)
    assert all(s['idea'] for s in slots)


def test_no_motif_repeats_back_to_back_within_a_style(no_llm):
    brief = {'theme': 'x', 'style': 'playtime', 'seconds': 40}
    plan = T.compose_best(brief, candidates=4)
    slots = _fake_slots()
    V.assign_ideas(slots, brief, plan, seed=1)
    # Runs, in order — the rule is about consecutive RUNS, not slots.
    runs = []
    for s in slots:
        if not runs or runs[-1] != s['motif']:
            runs.append(s['motif'])
    assert all(a != b for a, b in zip(runs, runs[1:])), runs
    assert all(s['idea'] != slots[i]['idea'] for i, s in enumerate(slots[1:])), 'consecutive duplicate idea'
