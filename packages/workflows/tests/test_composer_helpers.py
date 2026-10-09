# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers ``kids_music_theory.compose`` was split into.

``voice_chord``, ``line_rhythm``, ``emit_bars`` and ``assemble_plan`` were all
inline in the 306-line ``compose``, so none of them could be called with a
hand-made input before. ``voice_chord`` in particular is the voice-leading
search, and this is the first test that pins its "move least" promise.
"""

from __future__ import annotations

import pytest

from zyg_workflows.kids_music_theory.composer import compose
from zyg_workflows.kids_music_theory.composer_build import (
    ComposeState,
    assemble_plan,
    emit_bars,
    line_rhythm,
    prepare_compose,
    voice_chord,
)


def _brief():
    """The smallest brief ``prepare_compose`` accepts, as a fresh dict."""
    return {'title': 'Helper Test', 'age_band': '3-5'}


def _cached(cells, indices, fit_err=0):
    """A one-line motif cache entry, the shape ``compose`` stores."""
    return {'lines': [{'cells': cells, 'indices': indices, 'fit_err': fit_err}]}


# ---------------------------------------------------------------- voice_chord


def test_voice_chord_stacks_upwards_from_above_b2():
    """The first chord has no predecessor, so it is placed near E3."""
    voicing = voice_chord([0, 4, 7], None)
    assert voicing == sorted(voicing), 'the tones stack upwards'
    assert all(48 <= m <= 71 for m in voicing), voicing


def test_voice_chord_stays_under_the_melody_b4():
    """A voicing that would reach B4 is dropped an octave, whole."""
    for pcs in ([0, 4, 7], [2, 5, 9], [11, 2, 6], [7, 11, 2]):
        assert max(voice_chord(pcs, None)) <= 71, pcs


def test_voice_chord_picks_the_inversion_that_moves_least():
    """Given a previous voicing, the cheapest rotation wins."""
    prev = voice_chord([0, 4, 7], None)
    chosen = voice_chord([7, 11, 2], prev)
    cost = sum(abs(a - b) for a, b in zip(chosen, prev))
    # Every rotation is legal; none may beat the one that was returned.
    for inv in range(3):
        rot = [7, 11, 2][inv:] + [7, 11, 2][:inv]
        alt = voice_chord(rot, None)
        if len(alt) == len(prev):
            assert cost <= sum(abs(a - b) for a, b in zip(alt, prev)), (chosen, alt)


def test_voice_chord_is_a_rotation_of_the_pitch_classes():
    """Whatever inversion wins, the chord's pitch classes are unchanged."""
    voicing = voice_chord([0, 3, 7], voice_chord([0, 4, 7], None))
    assert sorted(m % 12 for m in voicing) == [0, 3, 7]


# ---------------------------------------------------------------- line_rhythm


def test_line_rhythm_takes_a_cached_motif_whose_note_count_fits():
    """Reuse is a copy: the cells and a COPY of the indices come straight back."""
    setup = prepare_compose(_brief(), seed=3)
    cached = _cached([[1.0, 1.0], [2.0]], [4, 5, 6], fit_err=1)
    cells, idx, fit_err, reused, rejected = line_rhythm(
        setup, cached=cached, reuse=True, line_i=0, target=3, is_final=False, is_last_line=False
    )
    assert (cells, idx, fit_err, reused, rejected) == ([[1.0, 1.0], [2.0]], [4, 5, 6], 1, True, False)
    assert idx is not cached['lines'][0]['indices'], 'the caller may transpose its copy'


def test_line_rhythm_refuses_a_motif_that_cannot_carry_the_syllables():
    """Three onsets cannot hold five syllables: rejected, and composed fresh."""
    setup = prepare_compose(_brief(), seed=3)
    cached = _cached([[1.0, 1.0], [2.0]], [4, 5, 6])
    cells, idx, _fit_err, reused, rejected = line_rhythm(
        setup, cached=cached, reuse=True, line_i=0, target=5, is_final=False, is_last_line=False
    )
    assert (idx, reused, rejected) == (None, False, True)
    assert cells, 'a fresh rhythm was picked instead'


def test_line_rhythm_never_reuses_on_the_final_line():
    """The last line of the song is always composed, so the ending is one."""
    setup = prepare_compose(_brief(), seed=3)
    cached = _cached([[1.0, 1.0], [2.0]], [4, 5, 6])
    _cells, idx, _fit_err, reused, rejected = line_rhythm(
        setup, cached=cached, reuse=True, line_i=0, target=3, is_final=True, is_last_line=True
    )
    assert (idx, reused, rejected) == (None, False, False), 'not a rejection — a cadence'


@pytest.mark.parametrize('target', [0, 4])
def test_line_rhythm_with_no_cache_composes_fresh(target):
    """No cache at all is the ordinary first pass through a section."""
    setup = prepare_compose(_brief(), seed=7)
    cells, idx, fit_err, reused, rejected = line_rhythm(
        setup, cached=None, reuse=False, line_i=0, target=target, is_final=False, is_last_line=True
    )
    assert idx is None and reused is False and rejected is False
    assert sum(len(c) for c in cells) > 0
    assert int(fit_err or 0) >= 0


# ---------------------------------------------------------------- emit_bars


def test_emit_bars_advances_the_write_head_by_whole_bars():
    """`count` accompaniment bars on one chord, and nothing else touched."""
    setup = prepare_compose(_brief(), seed=1)
    st = ComposeState()
    emit_bars(setup, st, root_deg=0, section=-1, count=3)
    assert len(st.chords) == 3
    assert st.bar == 3
    assert st.t == pytest.approx(3 * setup.bar_beats)
    assert [c['bar'] for c in st.chords] == [0, 1, 2]
    assert {c['section'] for c in st.chords} == {-1}
    assert st.melody == [], 'intro and outro bars carry no melody'


def test_emit_bars_zero_count_is_a_no_op():
    """A brief with no intro must not move the write head."""
    setup = prepare_compose(_brief(), seed=1)
    st = ComposeState()
    emit_bars(setup, st, root_deg=4, section=-2, count=0)
    assert (st.chords, st.bar, st.t) == ([], 0, 0.0)


# ---------------------------------------------------------------- assemble_plan


def test_assemble_plan_reports_the_lyric_fit_telemetry():
    """The fitter's per-line errors are summarised, not discarded."""
    setup = prepare_compose(_brief(), seed=5)
    st = ComposeState()
    st.fit_errors = [0, 2, 1]
    st.motif_reuses, st.motif_rejects = 4, 1
    st.bar, st.t = 8, 32.0
    plan = assemble_plan(setup, st)
    assert plan['lyric_fit'] == {
        'line_errors': [0, 2, 1],
        'total_error': 3,
        'worst_line_error': 2,
        'lines': 3,
        'motif_reuses': 4,
        'motif_rejected_wrong_length': 1,
    }


def test_assemble_plan_has_no_score_and_an_empty_range_is_zero():
    """``score`` is the caller's to add; an empty melody has a 0..0 range."""
    setup = prepare_compose(_brief(), seed=5)
    plan = assemble_plan(setup, ComposeState())
    assert 'score' not in plan
    assert plan['range'] == {'lo': 0, 'hi': 0}
    assert plan['seconds'] == 0.0


def test_assemble_plan_seconds_follow_the_beats_and_the_bpm():
    """total_beats * 60 / bpm, rounded to 2dp — the duration every caller reads."""
    setup = prepare_compose(_brief(), seed=5)
    st = ComposeState()
    st.t = 24.0
    plan = assemble_plan(setup, st)
    assert plan['total_beats'] == 24.0
    assert plan['seconds'] == pytest.approx(round(24.0 * 60.0 / setup.brief['bpm'], 2))


# ---------------------------------------------------------------- the whole chain


def test_compose_is_still_deterministic_for_a_seed():
    """The orchestrator's contract: same (brief, seed) → the same plan."""
    a = compose(_brief(), seed=11)
    b = compose(_brief(), seed=11)
    assert a == b
    assert a['seed'] == 11
    assert a['melody'] and a['chords'] and a['sections']
    assert a['bars'] == len(a['chords'])
