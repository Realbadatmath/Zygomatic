# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Beat grid, energy and the slot walk that lays the pictures on the song.

Moved verbatim out of the old single-file kids_video_service.py (lines 709-1290).
"""

from __future__ import annotations

import math
import subprocess
from zyg_workflows.bin import exe

from zyg_workflows.kids_video_service.constants import (
    ABSORB_MAX_S,
    CLIP_S,
    MAX_SLOT_S,
    MIN_SLOT_S,
    WINDOW_S,
    _RATE_NOTES,
    _log_noop,
)
from zyg_workflows.kids_video_service.transitions import (
    _xfade_graph,
    transitions_for,
)


# ── Beat grid ────────────────────────────────────────────────────────────────


def beat_grid(audio_path, plan, log_fn=None):
    """The beat times of the DELIVERED audio, with the composed plan as prior.

    Returns ``{'beats', 'bpm', 'source', 'duration_s', 'agree_pct'}``.

    The plan's bpm is ground truth for what was ASKED; the audio is the thing the
    pictures actually have to land on, and on the ACE-Step leg those differ (123
    detected against 121 asked, measured on this workflow's first songs).  So the
    measurement wins — but only when it agrees with the plan closely enough to be
    the same song: a detector that has locked onto half or double tempo would
    otherwise silently halve or double the whole video's cutting rate.  Outside
    ±12 % the symbolic grid is used and the disagreement is reported.
    """
    log_fn = log_fn or _log_noop
    bpm_plan = float(plan.get('bpm') or 100.0)
    beat_s = 60.0 / max(1.0, bpm_plan)
    dur = _duration(audio_path)
    out = {
        'beats': [],
        'bpm': bpm_plan,
        'source': 'symbolic',
        'duration_s': dur,
        'agree_pct': None,
        'measured_bpm': None,
    }
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units='time', trim=False, start_bpm=bpm_plan, tightness=160)
        m_bpm = float(np.atleast_1d(tempo)[0])
        out['measured_bpm'] = round(m_bpm, 2)
        agree = abs(m_bpm - bpm_plan) / max(1.0, bpm_plan)
        out['agree_pct'] = round(100.0 * agree, 1)
        if len(beats) >= 8 and agree <= 0.12:
            out['beats'] = [float(b) for b in beats]
            out['bpm'] = m_bpm
            out['source'] = 'measured'
            log_fn(
                f'beats: measured {m_bpm:.1f} bpm vs {bpm_plan:.0f} asked '
                f'({100 * agree:.1f}% apart) — {len(beats)} beats'
            )
        else:
            log_fn(
                f'beats: measurement not trusted ({m_bpm:.1f} bpm vs '
                f'{bpm_plan:.0f} asked, {len(beats)} beats) — using the '
                f'composed grid'
            )
    except Exception as e:  # noqa: BLE001 — librosa is optional
        log_fn(f'beats: tracker unavailable ({type(e).__name__}) — using the composed grid')
    if not out['beats']:
        n = int(max(0.0, dur) / beat_s) + 2
        out['beats'] = [round(i * beat_s, 4) for i in range(n)]
    return out


def _duration(path):
    try:
        r = subprocess.run(
            [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', path],
            capture_output=True,
            timeout=30,
        )
        return float((r.stdout or b'').decode().strip() or 0.0)
    except Exception:  # noqa: BLE001
        return 0.0


def _snap(t, beats, tol):
    """Nearest beat within ``tol``, else ``t`` unchanged."""
    if not beats:
        return t, False
    lo, hi = 0, len(beats) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if beats[mid] < t:
            lo = mid + 1
        else:
            hi = mid
    best, bd = t, tol + 1.0
    for j in (lo - 1, lo, lo + 1):
        if 0 <= j < len(beats):
            d = abs(beats[j] - t)
            if d < bd:
                best, bd = float(beats[j]), d
    return (best, True) if bd <= tol else (t, False)


# ── Energy ───────────────────────────────────────────────────────────────────


def rms_envelope(audio_path, log_fn=None):
    """(times, rms) for the delivered audio, or (None, None).

    Pace is driven by what the music actually DOES, not only by what the form
    says it should do: a chorus that was rendered quietly should not be cut like
    a loud one.
    """
    try:
        import librosa
        import numpy as np

        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        hop = 512
        r = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop)[0]
        t = librosa.frames_to_time(np.arange(len(r)), sr=sr, hop_length=hop)
        return [float(x) for x in t], [float(x) for x in r]
    except Exception as e:  # noqa: BLE001
        (log_fn or _log_noop)(f'energy: RMS unavailable ({type(e).__name__}) — pace from the form only')
        return None, None


def _energy_between(times, rms, a, b):
    if not times or not rms:
        return None
    vals = [rms[i] for i, t in enumerate(times) if a <= t < b]
    if not vals:
        return None
    return sum(vals) / len(vals)


# ── Storyboard ───────────────────────────────────────────────────────────────


def _segments(plan, media_s):
    """The song's structure in DELIVERED-audio seconds.

    The composed plan is in symbolic seconds and the delivered audio is whatever
    length it ended up (ACE-Step renders to a requested duration, and the master
    is tail-trimmed).  A single linear time-warp maps one onto the other; the
    scale factor is reported so a large stretch is visible rather than implied.
    """
    bar_beats = float(plan.get('bar_beats') or 4.0)
    beat_s = 60.0 / max(1.0, float(plan.get('bpm') or 100.0))
    sec_per_bar = bar_beats * beat_s
    plan_s = float(plan.get('seconds') or 0.0) or media_s
    k = (media_s / plan_s) if plan_s > 0 else 1.0

    segs = []
    intro = int(plan.get('intro_bars') or 0)
    if intro > 0:
        segs.append({'role': 'intro', 'name': 'intro', 'start': 0.0, 'end': intro * sec_per_bar * k})
    for s in plan.get('sections') or []:
        segs.append(
            {
                'role': str(s.get('role') or 'verse'),
                'name': str(s.get('name') or 'A'),
                'start': float(s['bar_start']) * sec_per_bar * k,
                'end': float(s['bar_end'] + 1) * sec_per_bar * k,
            }
        )
    if segs:
        segs[-1]['end'] = max(segs[-1]['end'], min(media_s, segs[-1]['end']))
    tail = segs[-1]['end'] if segs else 0.0
    if media_s - tail > 0.4:
        segs.append({'role': 'outro', 'name': 'outro', 'start': tail, 'end': media_s})
    # Clamp into the real timeline and drop anything the warp pushed past the end.
    out = []
    for s in segs:
        s['start'] = max(0.0, min(media_s, s['start']))
        s['end'] = max(0.0, min(media_s, s['end']))
        if s['end'] - s['start'] > 0.2:
            out.append(s)
    if not out:
        out = [{'role': 'verse', 'name': 'A', 'start': 0.0, 'end': media_s}]
    out[0]['start'] = 0.0
    out[-1]['end'] = media_s
    return out, round(k, 4)


# The lengths a slot is allowed to be, as multiples of a BAR.  Pictures change on
# a musically meaningful boundary rather than on a stopwatch tick, which is what
# makes a cut look intended; the clip length decides which of these rungs fit.
_UNIT_BARS = (8.0, 6.0, 4.0, 3.0, 2.0, 1.5, 1.0, 0.5, 0.25)


def _unit_ladder(plan, beat_s):
    """Every musical unit a clip can cover, longest first, in BEATS: the rungs
    inside [MIN_SLOT_S, ABSORB_MAX_S].

    One ladder, two jobs, so they cannot drift apart: rung 0 is the base slot and
    rung 1 is what a double-rate section steps to when it steps at all
    (_double_unit).  At 117 bpm in 4/4 a bar is 2.05 s, so a 5 s clip admits 2
    bars, 1.5 bars and 1 bar, and the base is 4.10 s; the old 2.45 s ceiling with
    the allowance off admits 1 bar, a half and a quarter, which is the
    one-picture-a-bar layout this module shipped before the clips existed.

    THE BOUND IS WHAT A CLIP CAN COVER, NOT THE TARGET, and the difference is six
    pictures.  Measured on job 998d6075706f (Green Frog Hop Song): librosa read
    that song at 112.35 bpm where the plan said 117, which makes a bar 2.136 s and
    two bars 4.272 s — over the 4.25 s TARGET by 22 ms.  Bounding the ladder by the
    target rejected that rung outright, dropped the walk to 1.5 bars (3.20 s) and
    laid out 20 pictures of 3.1 s where 14 of 4.27 s cover the song.  Song
    0184f07516ab has byte-identical section geometry, measured 117.45 bpm, and got
    its 14.  A tempo read 4 % slow must not cost 43 % more renders.

    Bounding by ABSORB_MAX_S instead puts that rung back: a 4.27 s picture needs a
    6 s clip rather than a 5 s one, which is precisely the bargain ABSORB_S already
    makes everywhere else — one extra clip-second, never an extra picture.  With
    ABSORB_S=0 the two bounds collapse and this reads exactly as it did before.

    Never empty: a song whose bar does not fit the window at all (a very slow tune
    against a short clip) falls back to the bound itself, so the walk always has a
    step.
    """
    bar = float(plan.get('bar_beats') or 4.0)
    out = [bar * m for m in _UNIT_BARS if MIN_SLOT_S - 1e-9 <= bar * m * beat_s <= ABSORB_MAX_S + 1e-9]
    if not out:
        out = [max(MIN_SLOT_S, min(ABSORB_MAX_S, bar * beat_s)) / beat_s]
    return out


def _double_unit(ladder, unit):
    """What a double-rate section steps to: the NEXT rung down the ladder, and only
    when that rung actually HALVES the base.  Otherwise the base itself — a loud
    section then reads through its faster transitions and its motion instead of
    through its cut rate.

    The rungs are bar multiples, so the only ratios on offer next door are a half
    (2 bars -> 1, 4 -> 2, 8 -> 4) and three quarters (2 -> 1.5, 4 -> 3, 8 -> 6),
    and 0.6 separates them cleanly.  Which one is next door depends on the clip
    length, and that is the whole point: at the old 2.45 s ceiling the base is one
    bar and the next rung is a half bar, so a chorus genuinely runs at double rate
    exactly as it always did; at a 5 s clip the base is two bars and the next rung
    is one and a half, which shortens a picture by a quarter and buys a THIRD more
    renders — 18.8 pictures a minute against 14.6, measured on the test song.  A
    pace change that small is not a pace change, it is a bill.

    Skipping a rung to find a halving is not the answer either: two rungs down is
    a flurry, which is what _burst_unit is for.
    """
    if len(ladder) < 2:
        return unit
    return ladder[1] if ladder[1] <= 0.6 * unit + 1e-9 else unit


def _burst_unit(beat_s):
    """The burst step in beats, or None when a burst does not fit at all.

    A burst is ONE PICTURE PER BEAT — that is the device, not a tunable: it is the
    flurry the counting motifs land on, one block, two blocks, three blocks.  One
    per two beats is the only concession, for a song whose beat is shorter than a
    picture may be.  Neither fitting means this cadence has no burst in it, which
    is the case for every clip length past about 2 s: at a 5 s clip the floor is
    1.27 s and a beat at 117 bpm is 0.51 s, so a one-per-beat run would be five
    pictures sharing one clip's worth of screen time.

    Asking instead for "the shortest slot length that fits" was tried and is
    wrong: it made bursts appear at a 7 s clip (three 2 s pictures with 3 s clips
    inside a run of 7 s ones) and vanish at 5 s, which is not a device an operator
    can predict.
    """
    if beat_s >= MIN_SLOT_S:
        return 1.0
    if 2.0 * beat_s >= MIN_SLOT_S:
        return 2.0
    return None


def plan_slots(plan, grid, media_s, *, energy=(None, None), log_fn=None):
    """Lay the picture slots on the beat grid.

    Returns (slots, info).  Each slot: ``{'i','start','end','dur','beats','pace',
    'section','role','burst'}``.  Pace is one of ``steady`` (one picture per base
    unit), ``double`` (two) or ``burst`` (one per beat).
    """
    log_fn = log_fn or _log_noop
    beats = grid['beats']
    beat_s = 60.0 / max(1.0, float(grid.get('bpm') or 100.0))
    ladder = _unit_ladder(plan, beat_s)
    unit = ladder[0]
    # A double-rate section steps DOWN THE LADDER rather than halving the unit:
    # half of a three-bar slot is a bar and a half, which is not where the grid
    # has a bar line. It steps only when the step is a real halving (_double_unit).
    unit_double = _double_unit(ladder, unit)
    bar_beats = float(plan.get('bar_beats') or 4.0)
    # A burst is one picture per beat, one bar long — when the clip length leaves
    # room for one at all (see _burst_unit; at a 5 s clip it does not).
    burst_step = _burst_unit(beat_s)
    burst_len = max(2, int(round(bar_beats / burst_step))) if burst_step else 0

    segs, warp = _segments(plan, media_s)
    # SNAP THE SECTION BOUNDARIES FIRST.  A section edge is a hard boundary for
    # the walk — the last slot of a section is stretched to reach it — so an
    # edge sitting between two beats drags that slot off the grid however well
    # the slots inside the section were snapped.  Measured: snapping the edges
    # first took cuts within 60 ms of a beat from 84 % to well over 90 %.
    for k in range(1, len(segs)):
        b, ok = _snap(segs[k]['start'], beats, 0.5 * unit * beat_s)
        if ok and 0.0 < b < media_s:
            segs[k - 1]['end'] = segs[k]['start'] = b
    times, rms = energy
    for s in segs:
        s['energy'] = _energy_between(times, rms, s['start'], s['end'])
    seen = [s['energy'] for s in segs if s['energy'] is not None]
    hi = sorted(seen)[int(0.66 * (len(seen) - 1))] if seen else None

    # Pace per segment. The form proposes and the measured energy disposes: a
    # chorus is fast because it is a chorus, and any section is fast if it is
    # actually loud.
    for s in segs:
        role = s['role']
        loud = hi is not None and s['energy'] is not None and s['energy'] >= hi
        if role in ('intro', 'outro'):
            s['pace'] = 'steady'
        elif role in ('bridge', 'chorus') or loud:
            s['pace'] = 'double'
        else:
            s['pace'] = 'steady'
        s['loud'] = bool(loud)

    # One burst per ~20 s of song, placed at the start of the loudest eligible
    # segments — never in the intro or outro, and never twice in a row.
    n_burst = max(1, int(media_s // 18.0)) if burst_step else 0
    cand = (
        []
        if not burst_step
        else [
            i
            for i, s in enumerate(segs)
            if s['role'] not in ('intro', 'outro') and (s['end'] - s['start']) >= burst_len * burst_step * beat_s * 1.6
        ]
    )
    cand.sort(key=lambda i: -(segs[i]['energy'] or 0.0))
    picked = []
    for i in cand:
        if len(picked) >= n_burst:
            break
        # Distance from EVERY burst already placed, not just the last one. The
        # first version compared against `last` only, and `i - last <= 1` is true
        # for any i BELOW last — so a song whose loudest section came late
        # silently got one burst instead of two.
        if any(abs(i - j) < 2 for j in picked):
            continue
        picked.append(i)
    for i in picked:
        segs[i]['burst_at_start'] = True

    slots, t = [], 0.0
    # Snapping is a CORRECTION for grid jitter, not a layout decision: the walk
    # steps whole beats from a boundary that is already on a beat, so the landing
    # point is a few ms from a measured beat unless the measurement wandered. One
    # beat is the most that can be absorbed — half the slot, which is what this
    # was when a slot was one bar long, would let a four-bar picture start a bar
    # late and still be called "on the beat".
    tol = min(0.5 * unit * beat_s, beat_s)
    for si, s in enumerate(segs):
        end = s['end']
        step = unit if s['pace'] == 'steady' else unit_double
        burst_left = burst_len if s.get('burst_at_start') else 0
        while t < end - 1e-6:
            # The step this slot would take is decided BEFORE the tail is measured,
            # because the tail is measured AGAINST it. A burst's step is not the
            # section's, and a threshold left over from the burst is how a 2 s
            # picture survived beside a 6 s one at a 7 s clip.
            if burst_left > 0:
                this, pace = burst_step, 'burst'
            else:
                this, pace = step, s['pace']
            # A TAIL SHORTER THAN SIX TENTHS OF THE STEP IS NOT A PICTURE, it is a
            # stub. The absolute floor below was written when a slot was one bar —
            # about a second — and it does not travel: at a 7 s clip the step is
            # three bars and a seven-bar section leaves one bar over, which clears
            # a 1.9 s floor easily and ships as a 2 s picture with a 3 s clip in
            # the middle of 7 s ones. Measured: a third of that song's pictures.
            stub_s = max(MIN_SLOT_S, 0.6 * this * beat_s)
            # A SECTION TAIL SHORTER THAN A SLOT IS NOT A SLOT.  The previous
            # section's last boundary can land a few tens of milliseconds before
            # this one starts (beat snapping moves it), and walking on from there
            # produced a 43 ms "picture" that nobody could see and a 0.1 s
            # transition either side of it.  The leftover is given to the picture
            # before it — or, when that would push it past the ceiling, split
            # evenly between the two so neither breaks the rate contract.
            if end - t < stub_s:
                if slots:
                    prev = slots[-1]
                    if end - prev['start'] <= ABSORB_MAX_S:
                        prev['end'] = round(end, 4)
                        prev['dur'] = round(end - prev['start'], 4)
                    else:
                        half = (end - prev['start']) / 2.0
                        mid = prev['start'] + half
                        prev['end'], prev['dur'] = round(mid, 4), round(half, 4)
                        slots.append(
                            {
                                'start': round(mid, 4),
                                'end': round(end, 4),
                                'dur': round(half, 4),
                                'pace': s['pace'],
                                'section': si,
                                'role': s['role'],
                                'name': s['name'],
                                'burst': False,
                                'on_beat': False,
                            }
                        )
                t = end
                break
            if pace == 'burst':
                burst_left -= 1
            nxt = min(end, t + this * beat_s)
            if end - nxt < MIN_SLOT_S:  # no runt at a section boundary
                nxt = end
            snapped, did = _snap(nxt, beats, tol)
            if MIN_SLOT_S <= (snapped - t) <= MAX_SLOT_S and abs(snapped - end) > 1e-9:
                nxt = snapped
            else:
                did = False
            nxt = min(nxt, media_s)
            dur = nxt - t
            if dur <= 1e-6:
                break
            # THE HARD LIMIT IS ENFORCED HERE, not hoped for: a slot longer than
            # a clip can cover is split, whatever the beat grid suggested. The
            # target ceiling is what the split aims at, so a slot that has to be
            # cut in two lands on two pictures of the target length, not on two
            # halves of whatever the grid produced.
            if dur > ABSORB_MAX_S:
                parts = int(math.ceil(dur / MAX_SLOT_S))
                sub = dur / parts
                for p in range(parts):
                    a = t + p * sub
                    slots.append(
                        {
                            'start': round(a, 4),
                            'end': round(a + sub, 4),
                            'dur': round(sub, 4),
                            'pace': pace,
                            'section': si,
                            'role': s['role'],
                            'name': s['name'],
                            'burst': pace == 'burst',
                            'on_beat': False,
                        }
                    )
            else:
                slots.append(
                    {
                        'start': round(t, 4),
                        'end': round(nxt, 4),
                        'dur': round(dur, 4),
                        'pace': pace,
                        'section': si,
                        'role': s['role'],
                        'name': s['name'],
                        'burst': pace == 'burst',
                        'on_beat': bool(did),
                    }
                )
            t = nxt
    if slots:
        slots[-1]['end'] = round(media_s, 4)
        slots[-1]['dur'] = round(max(MIN_SLOT_S, media_s - slots[-1]['start']), 4)

    # Belt and braces on both ends of the contract, whatever the walk produced:
    # nothing under the floor (invisible, and it wrecks its own transitions) and
    # nothing over the ceiling (that IS the two-per-five-seconds guarantee).
    merged = []
    for s in slots:
        if merged and s['dur'] < MIN_SLOT_S and (s['end'] - merged[-1]['start']) <= ABSORB_MAX_S:
            merged[-1]['end'] = s['end']
            merged[-1]['dur'] = round(s['end'] - merged[-1]['start'], 4)
            continue
        merged.append(s)
    slots = merged
    for i, s in enumerate(slots):
        s['i'] = i
        s['beats'] = round(s['dur'] / beat_s, 3)
    over = [s['i'] for s in slots if s['dur'] > ABSORB_MAX_S + 1e-6]
    if over:  # cannot happen by construction; if
        log_fn(
            f'storyboard: {len(over)} slot(s) are longer than the '  # it ever does
            f'{ABSORB_MAX_S:.2f}s a clip can cover — the contract is broken'
        )

    info = {
        'unit_beats': round(unit, 3),
        'unit_s': round(unit * beat_s, 3),
        'unit_double_beats': round(unit_double, 3),
        'unit_double_s': round(unit_double * beat_s, 3),
        'ladder_s': [round(u * beat_s, 3) for u in ladder],
        # The clip every picture is about to become, and the ceiling derived
        # from it. A manifest that records the cadence but not the number it
        # came from cannot be read back later.
        'clip_s': CLIP_S,
        'slot_ceiling_s': round(MAX_SLOT_S, 3),
        'slot_floor_s': round(MIN_SLOT_S, 3),
        'slot_absorb_max_s': round(ABSORB_MAX_S, 3),
        'stretched': [s['i'] for s in slots if s['dur'] > MAX_SLOT_S + 1e-6],
        'burst_step_beats': burst_step,
        'burst_len': burst_len,
        'bursts': len(picked),
        'time_warp': warp,
        'segments': [
            {
                'name': s['name'],
                'role': s['role'],
                'start': round(s['start'], 2),
                'end': round(s['end'], 2),
                'pace': s['pace'],
                'loud': s['loud'],
                'burst': bool(s.get('burst_at_start')),
            }
            for s in segs
        ],
    }
    for _n in _RATE_NOTES:
        log_fn(f'storyboard: {_n}')
    log_fn(
        f'storyboard: {len(slots)} pictures for {media_s:.1f}s — one per '
        f'{CLIP_S:g}s clip, base unit {unit:.2f} beats ({unit * beat_s:.2f}s), '
        f'double {unit_double * beat_s:.2f}s, ceiling {MAX_SLOT_S:.2f}s · '
        + (f'{len(picked)} beat burst(s) · ' if burst_step else 'no bursts at this clip length · ')
        + f'{sum(1 for s in slots if s["on_beat"])} cuts snapped to a measured beat'
    )
    return slots, info


def clip_plan(slots, *, seed=0):
    """The clip every slot is about to ask LTX for, from the plan alone.

    The same two calls the animate leg makes — ``transitions_for`` then
    ``_xfade_graph`` — because a clip has to cover its slot PLUS the overlap it
    gives away, and then whole seconds on top of that.  Pure arithmetic, so the
    GPU bill can be printed before any of it is spent rather than inferred from
    the log afterwards.  Returns (seconds per slot, total seconds).
    """
    try:
        from zyg_workflows.ltx_hidream_service import clip_seconds as _cs
    except Exception:  # noqa: BLE001 — the formula, not the import

        def _cs(slot_s, transition_s=0.3, minimum=2):
            return max(minimum, int(math.ceil(float(slot_s) + float(transition_s))))

    if not slots:
        return [], 0
    trans = transitions_for(slots, seed=seed)
    _graph, lens = _xfade_graph(slots, trans, len(slots))
    each = [_cs(ln) for ln in lens]
    return each, sum(each)


def min_per_window(starts, total_s, win=WINDOW_S, step=0.25):
    """The WORST rolling ``win``-second window, in picture starts.

    An average cannot see a ten-second still; this can.  Returns (worst, at_time)
    or (None, None) when the video is shorter than one window.
    """
    if total_s < win or not starts:
        return None, None
    worst, at = 10**9, 0.0
    t = 0.0
    while t <= total_s - win + 1e-9:
        n = sum(1 for s in starts if t <= s < t + win)
        if n < worst:
            worst, at = n, t
        t += step
    return worst, round(at, 2)


def beat_alignment(slots, beats):
    """How far each cut lands from the nearest measured beat, in milliseconds."""
    if not beats or len(slots) < 2:
        return {}
    errs = []
    for s in slots[1:]:
        b, _ = _snap(s['start'], beats, 10.0)
        errs.append(abs(b - s['start']) * 1000.0)
    errs.sort()
    n = len(errs)
    return {
        'cuts': n,
        'median_ms': round(errs[n // 2], 1),
        'p90_ms': round(errs[min(n - 1, int(0.9 * n))], 1),
        'within_60ms_pct': round(100.0 * sum(1 for e in errs if e <= 60.0) / n, 1),
    }
