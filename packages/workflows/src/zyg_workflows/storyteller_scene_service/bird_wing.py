# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.bird_wing — the spline helpers and the bird wing-shape tables of the video-helpers section (lines 1569-1817).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    math,
)
from zyg_workflows.storyteller_scene_service.frame import (
    _smoothstep,
)


def _lerp_table(tab, x: float) -> float:
    """Piecewise-linear lookup over [(x, y), ...]."""
    ts = sorted(((float(a), float(b)) for a, b in tab), key=lambda p: p[0])
    if x <= ts[0][0]:
        return ts[0][1]
    for a, b in zip(ts, ts[1:]):
        if x <= b[0]:
            f = 0.0 if b[0] <= a[0] else (x - a[0]) / (b[0] - a[0])
            return a[1] + (b[1] - a[1]) * f
    return ts[-1][1]


def _bez(p, n: int):
    """Quadratic Bezier through three control points, as n points."""
    out = []
    for k in range(n):
        t = k / (n - 1.0)
        w0, w1, w2 = (1 - t) ** 2, 2 * (1 - t) * t, t * t
        out.append((p[0][0] * w0 + p[1][0] * w1 + p[2][0] * w2, p[0][1] * w0 + p[1][1] * w1 + p[2][1] * w2))
    return out


def _catmull(pts, u: float):
    """Position and unit tangent at u ∈ [0,1] along a Catmull-Rom spline.

    The waypoints are the flight path; the spline is what turns them into a
    curve a bird could fly. A polyline cannot be used here — its tangent jumps
    at every waypoint, and the bird's heading is read off that tangent, so the
    bird would snap round on the spot each time it passed one.
    """
    n = len(pts)
    if n < 2:
        return tuple(pts[0]), (1.0, 0.0)
    u = max(0.0, min(1.0, float(u))) * (n - 1)
    i = min(int(u), n - 2)
    f = u - i
    p0, p1, p2, p3 = (pts[max(0, i - 1)], pts[i], pts[i + 1], pts[min(n - 1, i + 2)])
    f2, f3 = f * f, f * f * f

    def comp(a, b, c, dd):
        return 0.5 * ((2 * b) + (-a + c) * f + (2 * a - 5 * b + 4 * c - dd) * f2 + (-a + 3 * b - 3 * c + dd) * f3)

    def dcomp(a, b, c, dd):
        return 0.5 * ((-a + c) + 2 * (2 * a - 5 * b + 4 * c - dd) * f + 3 * (-a + 3 * b - 3 * c + dd) * f2)

    x = comp(p0[0], p1[0], p2[0], p3[0])
    y = comp(p0[1], p1[1], p2[1], p3[1])
    tx = dcomp(p0[0], p1[0], p2[0], p3[0])
    ty = dcomp(p0[1], p1[1], p2[1], p3[1])
    m = math.hypot(tx, ty) or 1.0
    return (x, y), (tx / m, ty / m)


_BIRD_TABLES: dict = {}


def _bird_tables(cfg: dict) -> tuple:
    """(arc-length table, speed table) for a path, built once and cached.

    ARC LENGTH, because waypoints are never evenly spaced: advancing the spline
    parameter at a constant rate flies the bird fast through the widely-spaced
    stretches and slow through the tight ones, and the swoop — which is exactly
    where the waypoints bunch — came out as a crawl. Re-parameterising makes the
    authored path a SHAPE and leaves speed to the second table.

    SPEED, because a bird trades height for speed. `dive_gain` adds speed where
    the path descends and takes it back where it climbs, so the swoop
    accelerates into the harbour and eases out of it. A constant-rate traverse
    reads as a decal being slid across the picture.
    """
    key = (
        tuple(tuple(p) for p in cfg['path']),
        int(cfg.get('arc_n', 192)),
        float(cfg.get('dive_gain', 0.45)),
        bool(cfg.get('speed_from_scale')),
        tuple(tuple(p) for p in (cfg.get('scale') or ())),
    )
    tab = _BIRD_TABLES.get(key)
    if tab is not None:
        return tab
    n = int(cfg.get('arc_n', 192))
    us = [k / (n - 1.0) for k in range(n)]
    ps = [_catmull(cfg['path'], u)[0] for u in us]
    cum = [0.0]
    for a, b in zip(ps, ps[1:]):
        cum.append(cum[-1] + math.hypot(b[0] - a[0], b[1] - a[1]))
    arc = [c / (cum[-1] or 1.0) for c in cum]
    # time cost of each arc step, at that step's speed
    gain = float(cfg.get('dive_gain', 0.45))
    # RECESSION. A bird leaving the camera covers less of the PICTURE per
    # second the further off it gets — image speed falls with distance, and
    # scale is 1/distance — so a flight authored to recede and then run at a
    # constant image speed says the opposite of what the path says, and the
    # picture wins: it reads as a decal sliding across the frame at one size.
    # `speed_from_scale` ties the traverse to the scale table, which is the
    # cheapest honest approximation of it.
    sc_tab = cfg.get('scale') or [(0.0, 1.0), (1.0, 1.0)]
    recede = bool(cfg.get('speed_from_scale'))
    tcum = [0.0]
    for k in range(1, n):
        _, tg = _catmull(cfg['path'], us[k])
        v = max(0.35, 1.0 + gain * tg[1])  # +y is DOWN the frame
        if recede:
            v *= max(0.12, _lerp_table(sc_tab, arc[k]))
        tcum.append(tcum[-1] + (arc[k] - arc[k - 1]) / v)
    tt = [c / (tcum[-1] or 1.0) for c in tcum]
    tab = (us, arc, tt)
    _BIRD_TABLES[key] = tab
    return tab


def _table_lookup(xs, ys, x: float) -> float:
    """y at x by binary search over a monotone table."""
    x = max(0.0, min(1.0, float(x)))
    lo, hi = 0, len(xs) - 1
    while lo < hi - 1:
        mid = (lo + hi) // 2
        if xs[mid] <= x:
            lo = mid
        else:
            hi = mid
    span = xs[hi] - xs[lo]
    f = 0.0 if span <= 0 else (x - xs[lo]) / span
    return ys[lo] + (ys[hi] - ys[lo]) * f


def _bird_wing(cfg: dict, t_rel: float) -> tuple:
    """(elev, tuck, climb) — the wing state alone, so it can be sampled at
    sub-frame times for motion blur without recomputing the whole flight.

    elev is WING ELEVATION, +1 at the top of the upstroke and -1 at the bottom
    of the downstroke, and it is continuous — the sprite ladder is indexed off
    it. The old model returned a symmetric sinusoid; two things measured off a
    real bird say that is wrong:

    * THE STROKE IS ASYMMETRIC. The downstroke is the power stroke and it is
      fast; the recovery is slower. `down_frac` is the share of one beat spent
      going down (0.5 restores the old symmetry). Measured on the reference
      clip the down half is roughly a third of the beat.
    * THE BEAT IS SLOWER THAN IT LOOKS IT SHOULD BE. The reference beats at
      3.1 Hz — nearly eight frames per cycle at 24 — where our first cut ran
      4.8 Hz, 5 frames per cycle, and the delivered file spent 31 of its 65
      wing-phase runs on a SINGLE frame. A beat the frame rate cannot resolve
      does not read as fast, it reads as a glitch.

    Kept behind `wing_model: 'stroke'` so the polygon bird v19 shipped with is
    bit-identical on the old path.

    `flap_events_s` (new, optional, default unset): a list of
    `{'t0': seconds[, 'beats': n]}` bursts authored at specific instants,
    instead of the `bound_period_s` cycle above repeating for the whole
    flight. Every cfg before this one leaves it unset and renders bit-
    identical — this is an alternate MODE, not a retune of the existing
    knobs, for a flight that should read as mostly a glide with a handful of
    deliberate wingbeats (gain a heading, hold the wings through a turn and
    let bank alone carry it, beat again to resume) rather than continuous
    bounding flight.
    """
    events = cfg.get('flap_events_s')
    if events:
        return _bird_wing_scripted(cfg, t_rel, events)
    per = max(0.25, float(cfg.get('bound_period_s', 0.82)))
    ff = min(0.92, max(0.20, float(cfg.get('flap_frac', 0.62))))
    beats = float(cfg.get('beats', 5.0))
    p = (t_rel / per) % 1.0
    if p >= ff:
        q = (p - ff) / (1.0 - ff)
        return 0.0, _smoothstep(min(1.0, q * 2.4)), 1.0 - _smoothstep(q)
    q = p / ff
    env = math.sin(math.pi * q) ** 0.35  # the burst eases in and out
    if cfg.get('wing_model') != 'stroke':
        return (math.sin(2.0 * math.pi * beats * q) * env, 0.0, _smoothstep(q))
    df = min(0.85, max(0.15, float(cfg.get('down_frac', 0.38))))
    bq = (q * beats) % 1.0  # position within ONE beat
    if bq < df:
        elev = math.cos(math.pi * (bq / df))  # +1 -> -1, fast
    else:
        elev = -math.cos(math.pi * ((bq - df) / (1.0 - df)))  # -1 -> +1, slow
    return elev * env, 0.0, _smoothstep(q)


def _bird_wing_scripted(cfg: dict, t_rel: float, events: list) -> tuple:
    """Same stroke shape as `_bird_wing`'s default cycle — asymmetric,
    eased-in/out — but timed to a short authored list of bursts instead of
    repeating for the whole flight.

    `bound_period_s`/`flap_frac`/`beats` still set the shape of a single
    beat and how long a burst of `beats` takes; `down_frac` still sets the
    stroke asymmetry. Only WHEN a burst happens stops being
    `t_rel mod bound_period_s` and becomes each event's own `t0` (and its
    own `beats`, if given — defaults to `cfg['beats']`). Outside every
    event the bird is gliding: wings ramp closed over the same
    `per * (1 - flap_frac)` settle window the default cycle's glide phase
    uses, then hold tucked until the next event starts (or forever, past
    the last one) — before the FIRST event it is simply already gliding,
    since a flight built from a handful of deliberate beats is not assumed
    to open with one.

    Wings ramp OPEN at a burst's onset over that same settle-window
    timescale, rather than snapping from tucked to spread in one frame the
    way `_bird_wing`'s own cycle does at every repeat. That snap is invisible
    there — it recurs every `bound_period_s` (~every half-second), so a
    motion-blur check sampled over any few-second window always catches
    several of them and the softened ones dominate the "worst jump" stat.
    Scripted down to two isolated bursts, the check sampled the ONE onset in
    its window and measured blur doing nothing to it (42% hard, 42%
    blurred) — motion blur only smooths WITHIN a frame's exposure, not
    across the frame boundary a truly instant snap lands on. Symmetric with
    the existing release ramp, not a new mechanism.
    """
    per = max(0.25, float(cfg.get('bound_period_s', 0.82)))
    ff = min(0.92, max(0.20, float(cfg.get('flap_frac', 0.62))))
    df = min(0.85, max(0.15, float(cfg.get('down_frac', 0.38))))
    default_beats = float(cfg.get('beats', 2.0))
    beat_dur = max(1e-6, per * ff / max(1e-6, default_beats))
    settle_dur = max(1e-6, per * (1.0 - ff))

    def _dur(ev):
        return max(1e-6, beat_dur * float(ev.get('beats', default_beats)))

    for ev in events:
        t0 = float(ev['t0'])
        dur = _dur(ev)
        if t0 <= t_rel < t0 + dur:
            beats = float(ev.get('beats', default_beats))
            q = (t_rel - t0) / dur
            env = math.sin(math.pi * q) ** 0.35
            bq = (q * beats) % 1.0
            if bq < df:
                elev = math.cos(math.pi * (bq / df))
            else:
                elev = -math.cos(math.pi * ((bq - df) / (1.0 - df)))
            q_open = min(1.0, (t_rel - t0) / settle_dur)
            tuck_in = 1.0 - _smoothstep(min(1.0, q_open * 2.4))
            return elev * env, tuck_in, _smoothstep(q)

    since_end = None
    for ev in events:
        t_end = float(ev['t0']) + _dur(ev)
        if t_end <= t_rel:
            gap = t_rel - t_end
            if since_end is None or gap < since_end:
                since_end = gap
    if since_end is None:
        return 0.0, 1.0, 0.0  # before the first burst: already gliding
    q = min(1.0, since_end / settle_dur)
    return 0.0, _smoothstep(min(1.0, q * 2.4)), 1.0 - _smoothstep(q)
