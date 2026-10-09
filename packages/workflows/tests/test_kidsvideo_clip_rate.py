# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The picture rate IS the clip length (2026-10-02).

Every picture becomes one LTX-2.5 clip, so a 60 s song needs 60/CLIP_S pictures —
twelve at a 5 s clip, not the fifty the old 2.45 s slot ceiling asked for.  What
is checked here:

  * the ceiling, floor and rate target are all DERIVED from CLIP_S, and CLIP_S is
    clamped to the range LTX can actually render without drifting;
  * the walk gives one picture per clip over a real song plan, every slot fits
    under the clip that has to cover it, and no clip exceeds CLIP_S whole seconds;
  * a longer clip buys proportionally fewer pictures;
  * bursts — one picture per beat — exist only at a clip length short enough for a
    flurry to read as one;
  * the pre-2026-10-02 cadence is still reachable by naming both bounds, and the
    pacing gate holds a COUNT of window starts to an integer floor rather than to
    the fractional mean.

CPU-only: no ComfyUI, no ollama, no GPU.
"""

import importlib
import json
import math
import os
import random
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
if CREWS not in sys.path:
    sys.path.insert(0, CREWS)

from zyg_workflows import kids_video_service as KV  # noqa: E402
from zyg_workflows import ltx_hidream_service as LH  # noqa: E402

BPM = 117.0
BEAT_S = 60.0 / BPM
MEDIA_S = 57.44  # the delivered length of job 81fb01e85934


def _reload(monkeypatch, **env):
    """kids_video_service with a fresh rate block. The constants are read at
    import, which is exactly what a run does, so the env has to be set first."""
    for k in (
        'ZYG_KIDSVIDEO_CLIP_S',
        'ZYG_KIDSVIDEO_MAX_SLOT_S',
        'ZYG_KIDSVIDEO_MIN_SLOT_S',
        'ZYG_KIDSVIDEO_PER_5S',
        'ZYG_KIDSVIDEO_ABSORB_S',
    ):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return importlib.reload(KV)


@pytest.fixture(autouse=True)
def _restore():
    """Leave the module as the rest of the suite found it."""
    yield
    importlib.reload(KV)


def _plan():
    return {
        'bar_beats': 4.0,
        'bpm': BPM,
        'seconds': MEDIA_S,
        'intro_bars': 2,
        'sections': [
            {'role': 'verse', 'name': 'A', 'bar_start': 2, 'bar_end': 8},
            {'role': 'chorus', 'name': 'B', 'bar_start': 9, 'bar_end': 15},
            {'role': 'verse', 'name': 'A', 'bar_start': 16, 'bar_end': 22},
        ],
        'lyrics': [f'line {i}' for i in range(12)],
    }


def _grid(jitter=0.0, seed=7):
    """A MEASURED grid is never a perfect metronome, so the default here is not
    one either: the snap tolerance has to absorb jitter without moving a cut."""
    rng = random.Random(seed)
    beats, t = [], 0.0
    while t < MEDIA_S + 2 * BEAT_S:
        beats.append(round(t, 4))
        t += BEAT_S * (1.0 + rng.uniform(-jitter, jitter))
    return {'beats': beats, 'bpm': BPM, 'bar_beats': 4.0, 'duration_s': MEDIA_S}


def _energy(seed=7):
    rng = random.Random(seed)
    times = [i * 0.1 for i in range(int(MEDIA_S / 0.1))]
    rms = [0.2 + (0.5 if 12 < x < 24 else 0.0) + 0.05 * rng.random() for x in times]
    return times, rms


def _clips(mod, slots):
    """The clip length the animate leg will ask LTX for, per slot."""
    trans = mod.transitions_for(slots, seed=0)
    _graph, lens = mod._xfade_graph(slots, trans, len(slots))
    return [LH.clip_seconds(ln) for ln in lens]


# ── the rate block is derived, not hand-set ──────────────────────────────────


def test_ceiling_floor_and_target_all_come_from_the_clip_length(monkeypatch):
    m = _reload(monkeypatch)
    assert m.CLIP_S == 5.0, 'a 5 s clip is the shipped default'
    # headroom = one full transition (0.45) + clip_seconds' own 0.3 margin
    assert m.MAX_SLOT_S == pytest.approx(4.25), 'the target a slot aims at'
    assert m.ABSORB_MAX_S == pytest.approx(5.25), 'one extra clip-second past it'
    assert m.MIN_SLOT_S == pytest.approx(1.275)
    # The rate follows the HARD limit, not the target: a picture really may run
    # 5.25 s, so a 5 s window really may hold no start at all and the floor is 0.
    assert m.TARGET_PER_5S == pytest.approx(5.0 / 5.25, abs=1e-3)
    assert m.MIN_STARTS_PER_5S == 0


def test_a_ten_second_clip_moves_every_derived_bound(monkeypatch):
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S='10')
    assert m.MAX_SLOT_S == pytest.approx(9.25)
    # a single 10 s picture can fill a 5 s window on its own, and the gate says so
    assert m.MIN_STARTS_PER_5S == 0


@pytest.mark.parametrize('asked,got', [('30', 10.0), ('1', 2.0), ('0.5', 2.0)])
def test_clip_length_is_clamped_to_what_ltx_renders_without_drifting(monkeypatch, asked, got):
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S=asked)
    assert m.CLIP_S == got
    assert m._RATE_NOTES, 'a clamped clip length must say so in the run log'


def test_a_bad_env_pair_cannot_deadlock_the_walk(monkeypatch):
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_MAX_SLOT_S='2.0', ZYG_KIDSVIDEO_MIN_SLOT_S='9.0')
    assert m.MIN_SLOT_S < m.MAX_SLOT_S
    slots, _info = m.plan_slots(_plan(), _grid(), MEDIA_S, energy=_energy())
    assert slots


# ── the ladder ───────────────────────────────────────────────────────────────


def test_every_rung_is_a_bar_multiple_inside_the_window(monkeypatch):
    m = _reload(monkeypatch)
    ladder = m._unit_ladder(_plan(), BEAT_S)
    assert ladder == sorted(ladder, reverse=True), 'longest rung first'
    for u in ladder:
        # the bound is what a clip can COVER, not the target it aims at
        assert m.MIN_SLOT_S - 1e-9 <= u * BEAT_S <= m.ABSORB_MAX_S + 1e-9
        assert (u / 4.0) in m._UNIT_BARS, f'{u} beats is not a bar multiple'


def test_a_song_whose_bar_does_not_fit_still_gets_a_step(monkeypatch):
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S='2', ZYG_KIDSVIDEO_MIN_SLOT_S='1.2')
    ladder = m._unit_ladder({'bar_beats': 4.0}, 4.0)  # a 16 s bar
    assert len(ladder) == 1 and ladder[0] * 4.0 <= m.ABSORB_MAX_S + 1e-9


# ── what the walk actually produces ──────────────────────────────────────────


def test_one_picture_per_clip_over_a_real_song(monkeypatch):
    m = _reload(monkeypatch)
    slots, info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    per_min = 60.0 * len(slots) / MEDIA_S
    # 12 a minute is the arithmetic ideal (60 / 5) and this song cannot reach it:
    # its sections are 14.36 s, so each one needs ceil(14.36 / 4.25) = 4 pictures
    # and 16 is the FEWEST the ceiling allows. The real song (job 81fb01e85934,
    # even sections) lays out at 14. Both are a long way from the 54 it shipped.
    assert 11 <= per_min <= 17.5, f'{len(slots)} pictures = {per_min:.1f} a minute'
    # The floor is arithmetic: a section cannot hold fewer pictures than its own
    # length divided by the ceiling, and the walk must not need more than one over.
    need = sum(
        max(1, math.ceil((sg['end'] - sg['start']) / m.MAX_SLOT_S - 1e-9)) for sg in m._segments(_plan(), MEDIA_S)[0]
    )
    assert len(slots) <= need + 1, f'{len(slots)} pictures against a floor of {need}'
    assert info['clip_s'] == 5.0
    assert all(s['dur'] <= m.MAX_SLOT_S + 1e-6 for s in slots)
    assert all(s['dur'] >= 0.35 for s in slots)
    assert sum(s['dur'] for s in slots) == pytest.approx(MEDIA_S, abs=0.05), 'the slots must still tile the whole song'


def test_no_clip_is_longer_than_the_clip_length_asked_for(monkeypatch):
    m = _reload(monkeypatch)
    slots, _info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    clips = _clips(m, slots)
    assert max(clips) <= m.CLIP_S, clips
    # and the point of the whole change: the motion rendered is not far above the
    # song it has to cover. 54 two-second clips for 57 s of song was 1.8x.
    assert sum(clips) / MEDIA_S < 1.35, f'{sum(clips)} s of clip for {MEDIA_S} s'


def test_a_longer_clip_buys_fewer_pictures(monkeypatch):
    counts = {}
    for c in ('5', '7', '10'):
        m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S=c)
        slots, _i = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
        counts[c] = len(slots)
        assert max(_clips(m, slots)) <= float(c)
    assert counts['10'] < counts['5'], counts
    assert counts['10'] <= 10, counts


def test_cuts_still_land_on_the_measured_beat(monkeypatch):
    m = _reload(monkeypatch)
    grid = _grid(0.04)
    slots, _info = m.plan_slots(_plan(), grid, MEDIA_S, energy=_energy())
    b = m.beat_alignment(slots, grid['beats'])
    assert b['median_ms'] <= 60.0, b
    assert b['within_60ms_pct'] >= 80.0, b


# ── bursts, and when there cannot be one ─────────────────────────────────────


def test_a_five_second_clip_has_no_burst_because_a_flurry_cannot_read(monkeypatch):
    m = _reload(monkeypatch)
    assert BEAT_S < m.MIN_SLOT_S, 'a one-beat picture would be under the floor'
    assert m._burst_unit(BEAT_S) is None
    slots, info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    assert info['bursts'] == 0 and info['burst_step_beats'] is None
    assert not any(s['burst'] for s in slots)


def test_the_old_cadence_is_still_reachable_and_still_bursts(monkeypatch):
    m = _reload(
        monkeypatch, ZYG_KIDSVIDEO_MAX_SLOT_S='2.45', ZYG_KIDSVIDEO_MIN_SLOT_S='0.35', ZYG_KIDSVIDEO_ABSORB_S='0'
    )
    assert m.ABSORB_MAX_S == m.MAX_SLOT_S, 'the old ceiling is a hard one'
    assert m._burst_unit(BEAT_S) == 1.0, 'one picture a beat, as it always was'
    assert m._burst_unit(0.3) == 2.0, 'a beat under the floor takes two'
    assert m._burst_unit(0.1) is None
    slots, info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    assert info['unit_beats'] == 4.0, 'one picture a bar'
    assert info['burst_step_beats'] == 1.0, 'one picture a beat'
    assert info['bursts'] >= 1 and any(s['burst'] for s in slots)
    assert 40 <= len(slots) <= 60, len(slots)


# ── the gate reads its own numbers ───────────────────────────────────────────


def test_a_count_of_window_starts_is_held_to_an_integer_floor(monkeypatch):
    """The bug this guards: a COUNT of window starts compared against a fractional
    mean failed a layout that was exactly right. A 4 s clip is where it bites — the
    hard limit is 4.25 s, so the mean target is 1.18 while the integer floor is 1,
    and a window genuinely holding one start has to pass."""
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S='4')
    assert m.MIN_STARTS_PER_5S == 1 and m.TARGET_PER_5S > 1.0, (
        'if this ever stops being true the regression it guards is gone'
    )
    slots, _info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    worst, _at = m.min_per_window([s['start'] for s in slots], MEDIA_S)
    per5 = m.WINDOW_S * len(slots) / MEDIA_S
    assert worst == 1 and float(worst) < m.TARGET_PER_5S, (worst, m.TARGET_PER_5S)
    assert worst >= m.MIN_STARTS_PER_5S, 'the count must clear the integer floor'
    assert per5 >= m.TARGET_PER_5S - 1e-3


def test_the_storyboard_records_the_number_the_cadence_came_from(monkeypatch):
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S='7')
    _slots, info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    for k in ('clip_s', 'slot_ceiling_s', 'slot_floor_s', 'ladder_s', 'unit_double_s', 'burst_step_beats'):
        assert k in info, k
    assert info['clip_s'] == 7.0
    assert json.dumps(info), 'the manifest has to serialise'


# ── the pace rung, the stubs, and the bill ───────────────────────────────────


def test_a_quarter_off_a_picture_is_not_a_pace_change(monkeypatch):
    """At a 5 s clip the next rung down is 3/4 of the base, which buys a third
    more renders for a cadence shift nobody sees — so the rate stays flat and the
    loud section reads through its transitions instead."""
    m = _reload(monkeypatch)
    ladder = m._unit_ladder(_plan(), BEAT_S)
    assert ladder[1] == pytest.approx(0.75 * ladder[0])
    assert m._double_unit(ladder, ladder[0]) == ladder[0], 'should not step'
    slots, info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    assert info['unit_double_beats'] == info['unit_beats']
    # One cadence for the whole song: a chorus picture is the same length as a
    # verse picture. The spread that is left is section arithmetic — a section
    # that is not a whole number of slots long splits its tail evenly — and it
    # never drops a picture below six tenths of the longest.
    durs = sorted({round(s['dur'], 1) for s in slots})
    assert min(durs) >= 0.6 * max(durs), durs
    by_pace = {}
    for s in slots:
        by_pace.setdefault(s['pace'], []).append(round(s['dur'], 1))
    assert max(max(v) for v in by_pace.values()) == pytest.approx(min(max(v) for v in by_pace.values())), by_pace
    # the chorus is still visibly a chorus — its joins are the faster ones
    assert any(s['pace'] == 'double' for s in slots), 'energy still labels sections'
    trans = m.transitions_for(slots, seed=0)
    assert len({t['duration'] for t in trans}) > 1, 'all joins the same length'


def test_the_old_ceiling_still_halves_in_a_loud_section(monkeypatch):
    m = _reload(
        monkeypatch, ZYG_KIDSVIDEO_MAX_SLOT_S='2.45', ZYG_KIDSVIDEO_MIN_SLOT_S='0.35', ZYG_KIDSVIDEO_ABSORB_S='0'
    )
    ladder = m._unit_ladder(_plan(), BEAT_S)
    assert m._double_unit(ladder, ladder[0]) == pytest.approx(0.5 * ladder[0])


def test_a_section_tail_is_measured_against_this_sections_step(monkeypatch):
    """A seven-bar section against a three-bar step leaves one bar over. That bar
    clears the absolute floor easily, so the old rule shipped it as a 2 s picture
    with a 3 s clip between 7 s ones."""
    m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S='7')
    slots, _info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    shortest, longest = min(s['dur'] for s in slots), max(s['dur'] for s in slots)
    assert shortest >= 0.6 * longest, f'{shortest:.2f}s stub beside a {longest:.2f}s picture'
    assert min(_clips(m, slots)) >= 4, _clips(m, slots)


def test_the_bill_is_readable_off_the_plan(monkeypatch):
    m = _reload(monkeypatch)
    slots, _info = m.plan_slots(_plan(), _grid(0.04), MEDIA_S, energy=_energy())
    each, total = m.clip_plan(slots, seed=0)
    assert len(each) == len(slots)
    assert total == sum(each) and total > 0
    assert each == _clips(m, slots), 'the helper must agree with the animate leg'
    # what the rewrite is for: the old cadence rendered 1.8x the motion the song
    # could use and 80 images for a 57 s song; this is the same song.
    assert total / MEDIA_S < 1.3
    assert len(slots) * m.CANDIDATES <= 32


def test_clip_plan_survives_without_the_ltx_module(monkeypatch):
    """The arithmetic is the contract, not the import: a box with no LTX service
    still has to be able to print the bill."""
    m = _reload(monkeypatch)
    slots, _info = m.plan_slots(_plan(), _grid(), MEDIA_S, energy=_energy())
    want, _t = m.clip_plan(slots, seed=0)
    real = sys.modules.pop('zyg_workflows.ltx_hidream_service', None)
    monkeypatch.setitem(sys.modules, 'zyg_workflows.ltx_hidream_service', None)
    try:
        got, _t2 = m.clip_plan(slots, seed=0)
    finally:
        if real is not None:
            sys.modules['zyg_workflows.ltx_hidream_service'] = real
    assert got == want


# ── the absorb allowance, on the song shape that exposed it ──────────────────


def _plan_209():
    """Job 7d67da47b424 reproduced: six four-bar sections, which the time-warp
    (plan 57.46 s against 59.87 s delivered) stretches to 8.55 s — 2.09 base units
    at a 5 s clip, leaving 0.37 s over. That leftover is what used to cost a whole
    extra picture per section."""
    return {
        'bar_beats': 4.0,
        'bpm': 117.0,
        'seconds': 57.46,
        'intro_bars': 2,
        'sections': [
            {'role': r, 'name': n, 'bar_start': 2 + 4 * k, 'bar_end': 5 + 4 * k}
            for k, (r, n) in enumerate(
                [
                    ('verse', 'call'),
                    ('verse', 'answer'),
                    ('bridge', 'bridge'),
                    ('verse', 'answer'),
                    ('verse', 'call'),
                    ('verse', 'answer'),
                ]
            )
        ],
        'lyrics': [f'line {i}' for i in range(12)],
    }


def test_a_leftover_stretches_the_picture_instead_of_splitting_it(monkeypatch):
    m = _reload(monkeypatch)
    plan, media = _plan_209(), 59.87
    segs, _warp = m._segments(plan, media)
    assert round(segs[1]['end'] - segs[1]['start'], 2) == 8.55, 'the shape under test'
    slots, info = m.plan_slots(plan, _grid(0.03), media, energy=_energy())
    # 14 covers this song; splitting every 0.37 s tail in half produced 19-20 and
    # put a 2.24 s picture beside a 4.10 s one in every section.
    assert len(slots) <= 15, f'{len(slots)} pictures for {media}s'
    assert min(s['dur'] for s in slots) >= 0.8 * m.MAX_SLOT_S, sorted(round(s['dur'], 2) for s in slots)
    assert info['stretched'], 'this song shape must use the allowance'
    assert all(s['dur'] <= m.ABSORB_MAX_S + 1e-6 for s in slots)
    # the stretch costs ONE clip-second each, never a picture
    each, _total = m.clip_plan(slots, seed=0)
    assert set(each) <= {int(m.CLIP_S), int(m.CLIP_S) + 1}, sorted(set(each))


def test_turning_the_allowance_off_brings_the_splits_back(monkeypatch):
    """The allowance is the thing doing the work, not a coincidence of this plan."""
    off = _reload(monkeypatch, ZYG_KIDSVIDEO_ABSORB_S='0')
    a, _i = off.plan_slots(_plan_209(), _grid(0.03), 59.87, energy=_energy())
    on = _reload(monkeypatch)
    b, _j = on.plan_slots(_plan_209(), _grid(0.03), 59.87, energy=_energy())
    assert len(a) >= len(b) + 4, (len(a), len(b))
    assert min(s['dur'] for s in a) < 0.6 * max(s['dur'] for s in a), 'stubs are back'


def test_nothing_may_be_longer_than_the_clip_that_covers_it(monkeypatch):
    """The one hard contract left: over the target costs a clip-second, over what a
    clip can cover is a broken video."""
    for c in ('2', '4', '5', '7', '10'):
        m = _reload(monkeypatch, ZYG_KIDSVIDEO_CLIP_S=c)
        for plan in (_plan(), _plan_209()):
            slots, _i = m.plan_slots(plan, _grid(0.04), MEDIA_S, energy=_energy())
            assert not [s for s in slots if s['dur'] > m.ABSORB_MAX_S + 1e-6], c
            each, _t = m.clip_plan(slots, seed=0)
            assert all(cl >= s['dur'] for cl, s in zip(each, slots)), c


# ── the tempo cliff ──────────────────────────────────────────────────────────


def _grid_at(bpm, media=59.87, jitter=0.0, seed=11):
    """A measured grid at a given tempo. librosa reads the DELIVERED audio, so it
    disagrees with the composed plan — that disagreement is the whole test."""
    rng = random.Random(seed)
    bs = 60.0 / bpm
    beats, t = [], 0.0
    while t < media + 2 * bs:
        beats.append(round(t, 4))
        t += bs * (1.0 + rng.uniform(-jitter, jitter))
    return {'beats': beats, 'bpm': bpm, 'bar_beats': 4.0, 'duration_s': media}


def test_a_tempo_read_four_percent_slow_does_not_cost_a_rung(monkeypatch):
    """Job 998d6075706f: plan 117 bpm, librosa measured 112.35, which makes two
    bars 4.272 s — over the 4.25 s TARGET by 22 ms. Bounding the ladder by the
    target dropped it to 1.5 bars and laid out 20 pictures where 14 cover the
    song; job 0184f07516ab has the same sections, measured 117.45, and got 14."""
    m = _reload(monkeypatch)
    slow = m._unit_ladder({'bar_beats': 4.0}, 60.0 / 112.35)
    assert slow[0] == 8.0, 'two bars must survive a 4 % slow read'
    assert slow[0] * 60.0 / 112.35 > m.MAX_SLOT_S, 'the rung really is over the target'
    assert slow[0] * 60.0 / 112.35 <= m.ABSORB_MAX_S, 'and really is coverable'

    plan, media = _plan_209(), 59.87
    a, _i = m.plan_slots(plan, _grid_at(112.35, media), media, energy=(None, None))
    b, _j = m.plan_slots(plan, _grid_at(117.45, media), media, energy=(None, None))
    assert len(a) == len(b), (len(a), len(b))  # tempo does not change the count
    assert len(a) <= 15, f'{len(a)} pictures at 112.35 bpm'


def test_the_rung_costs_one_clip_second_and_never_a_picture(monkeypatch):
    m = _reload(monkeypatch)
    media = 59.87
    slots, _i = m.plan_slots(_plan_209(), _grid_at(112.35, media), media, energy=(None, None))
    each, total = m.clip_plan(slots, seed=0)
    assert set(each) <= {int(m.CLIP_S), int(m.CLIP_S) + 1}, sorted(set(each))
    assert all(s['dur'] <= m.ABSORB_MAX_S + 1e-6 for s in slots)
    # A longer rung means FEWER, longer clips, so the motion bill does not grow.
    # The hard bound is one clip per picture at CLIP_S+1 over a base unit of
    # 4.272 s = 1.40x; measured 1.25-1.34x here against the 1.78x this song's
    # pipeline spent before the cadence changed (job f28b3396cfdb, 119 clip-
    # seconds for 60 s), and 14 pictures at every tempo instead of 20-22.
    assert total / media <= (m.CLIP_S + 1) / min(s['dur'] for s in slots) + 1e-6
    assert total / media < 1.4, total


def test_the_allowance_off_restores_the_cliff(monkeypatch):
    """ABSORB_S=0 collapses the two bounds, which is what the pre-2026-10-02
    cadence needs — and is also what the cliff looked like."""
    off = _reload(monkeypatch, ZYG_KIDSVIDEO_ABSORB_S='0')
    assert off.ABSORB_MAX_S == off.MAX_SLOT_S
    assert off._unit_ladder({'bar_beats': 4.0}, 60.0 / 112.35)[0] == 6.0, '1.5 bars'
    on = _reload(monkeypatch)
    assert on._unit_ladder({'bar_beats': 4.0}, 60.0 / 112.35)[0] == 8.0, '2 bars'


def test_a_fast_song_gains_a_whole_bar(monkeypatch):
    """140 bpm: three bars is 5.14 s, which a 6 s clip covers. The target bound
    took two bars (3.43 s) and 18 pictures where 12 cover the song."""
    m = _reload(monkeypatch)
    assert m._unit_ladder({'bar_beats': 4.0}, 60.0 / 140.0)[0] == 12.0, 'three bars'
