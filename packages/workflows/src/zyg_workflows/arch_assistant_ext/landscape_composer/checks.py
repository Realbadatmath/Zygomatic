# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landscape_composer/checks.py — block arithmetic and the ground checks describe_landscape shares with the test.

Moved verbatim out of landscape_composer.py (lines 244-713).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.landscape_composer.constants import (
    BODY_REACHES,
    DRAPE_MAX_M,
    FLOW_WATER,
    GROUND_KIND,
    GROUND_TOL,
    HEAD_FRAC,
    HEAD_REACHES,
    LANDSCAPE_KINDS,
    LEVEL_WATER,
    MAX_BOULDER_M,
    MAX_TREE_OF_PEAK,
    MAX_WINDMILL_M,
    MIN_REACH_M,
    OLD_SOLID_GROUND,
    PEAK_KINDS,
    PEAK_MIN_M,
    POOL_TOL,
    RIM_TOL,
    SCULPT_KINDS,
    TREE_KINDS,
    V3_FLOW_WATER,
    V3_WATER,
    WATER_TOL,
    _A,
    block_bounds,
    cell_name,
    math,
    parse_cell,
)


# ── block arithmetic ──────────────────────────────────────────────────────────
def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _f(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def _block_cells(cell_from, cell_to):
    """Inclusive block -> (col_a, row_a, col_b, row_b), 0-based, sorted."""
    c0, r0 = parse_cell(cell_from)
    c1, r1 = parse_cell(cell_to)
    ca, cb = sorted((c0, c1))
    ra, rb = sorted((r0, r1))
    return ca, ra, cb, rb


def _span(a, b, f0, f1):
    """The fractional sub-range [f0, f1) of the inclusive index range a..b."""
    n = b - a + 1
    i = int(_clamp(a + int(round(n * f0)), a, b))
    j = int(_clamp(a + int(round(n * f1)) - 1, i, b))
    return i, j


def _at(a, b, f):
    """The single index at fraction f of the inclusive range a..b."""
    return int(_clamp(a + int(round((b - a) * f)), a, b))


def _mid(a, b):
    return (a + b) // 2


def _cells_m(i, j):
    """How many metres an inclusive index band i..j covers on the live grid.
    Cells are square, so this reads rows as happily as columns."""
    x0, _z0, x1, _z1 = block_bounds(cell_name(i, 0), cell_name(j, 0))
    return x1 - x0


def _cell_m():
    """One cell, in metres, on the drawing the tool is running against."""
    return _cells_m(0, 0)


def _bands(a, b, max_m=DRAPE_MAX_M):
    """Split the inclusive index range a..b into as few bands as will each stay
    under max_m metres. The drape tools refuse past 600 m a side, and a single
    record over half a kilometre of ground would be seated on one plane fit."""
    total = _cells_m(a, b)
    n = max(1, int(math.ceil(total / float(max_m) - 1e-9)))
    cnt = b - a + 1
    out = []
    for k in range(n):
        i = a + (cnt * k) // n
        j = a + (cnt * (k + 1)) // n - 1
        if j >= i:
            out.append((i, j))
    return out


def _walk(a, b, max_m=DRAPE_MAX_M):
    """The cell indices a chain tool (add_scree, plant_tree_line, carve_river)
    should be handed so no single record spans more than max_m."""
    return [a] + [j for _i, j in _bands(a, b, max_m)]


def _river_nodes(a, b):
    """The cell indices a carved river should be handed, between index a and b:
    close together over its HEAD, far apart down the rest of its run.

    A v3 river is a chain of STRAIGHT falls (water_v3 gave rivers a profile on
    2026-09-07: each reach is a bed SET to the line between two node levels,
    and the water slopes on it). A reach can only follow ground that is
    straight under it, and the head of a cut valley is the one place it is not:
    lower_ground feathers a trough's ENDS over 0.10 of its length, so a 25 m
    canyon drops its full depth over a 30 m smoothstep. The chord of a reach
    laid across that ramp stands above the true ground by about kL^2/8, and
    freeboard only buys back 0.2 of the river's depth — a 15 m reach on a 300 m
    block leaves its water nearly two metres over the floor beside it, which is
    the raised blue ribbon the eye rejects.

    The cure has to be uneven, because carve_river draws at most 40 reaches in
    one go and an even chain short enough for the ramp needs sixty-five. So the
    first HEAD_FRAC of the run — the ramp, plus margin — takes HEAD_REACHES of
    them and the flat floor takes BODY_REACHES. That holds head reaches to
    0.009 of the run (2.7 m on a 300 m block, 9 m on a kilometre), comfortably
    inside the ~0.0155 the sagitta allows, and both counts scale with the block
    because the feather does. The far end needs no such care: the bed chain
    never rises, so where the ground ramps back up the river simply digs in.
    Nodes closer than MIN_REACH_M are dropped — the tool refuses a reach under
    a metre."""
    cm = _cell_m()
    span = b - a
    ts = [HEAD_FRAC * k / float(HEAD_REACHES) for k in range(HEAD_REACHES)]
    ts += [HEAD_FRAC + (1.0 - HEAD_FRAC) * k / float(BODY_REACHES) for k in range(1, BODY_REACHES + 1)]
    out = []
    for t in ts:
        i = a + int(round(span * t))
        if out and abs(i - out[-1]) * cm < MIN_REACH_M:
            continue
        out.append(i)
    if out[-1] != b:
        out.append(b)
    if len(out) > 2 and abs(out[-1] - out[-2]) * cm < MIN_REACH_M:
        out.pop(-2)
    return out


def _meander_m(run, width, want):
    """How far a carved river `width` m wide may wander off its centre line,
    over a run of `run` m, given the composer would like `want` m of it.

    carve_river takes ONE meander for the whole chain and every reach seeds its
    own wander, so a junction can jog sideways by the whole meander. Two things
    bound it. Against the RUN: the chain's shortest link is a head reach, 0.009
    of it, and asking for more swing than half a reach turns a canyon river
    into a saw blade. Against the WIDTH: a jog of more than about a third of
    the ribbon pulls consecutive reaches clear of each other, and a 2 m alpine
    stream comes out as a dotted line down its own valley. Both were rendered
    and looked at; the smaller of the two bounds is the one to obey."""
    return round(min(float(want), 0.5 * HEAD_FRAC / HEAD_REACHES * float(run), 0.35 * float(width)), 2)


def _sq(cc, rc, half_m, ca, ra, cb, rb):
    """A square block of about 2 x half_m metres centred on (cc, rc), clipped to
    the block. Returns (cell_from, cell_to, r) where r is the radius the callee
    will actually compute from it."""
    cm = _cell_m()
    hc = max(1, int(round(half_m / cm)))
    c0, c1 = int(_clamp(cc - hc, ca, cb)), int(_clamp(cc + hc, ca, cb))
    r0, r1 = int(_clamp(rc - hc, ra, rb)), int(_clamp(rc + hc, ra, rb))
    r = 0.5 * min(_cells_m(c0, c1), _cells_m(r0, r1))
    return cell_name(c0, r0), cell_name(c1, r1), r


# ── the ground checks, shared by describe_landscape and the test ──────────────
def ground_under(d, rec):
    """The ground at a record's centre with THAT RECORD temporarily hidden.

    A mountain reports its own summit under itself, so the only honest way to
    ask 'what is this thing standing on?' is to take it out of the drawing for
    the length of one sample. `hidden` is exactly the flag the seam already
    skips, so nothing else has to know."""
    had = 'hidden' in rec
    was = rec.get('hidden')
    rec['hidden'] = True
    try:
        return _A.ground_height(d, _f(rec.get('x')), _f(rec.get('z')))
    finally:
        if had:
            rec['hidden'] = was
        else:
            rec.pop('hidden', None)


def _hh(o):
    return _f((o.get('p') or {}).get('h'), 0.0)


def boulder_across(o):
    return 2.0 * _f((o.get('p') or {}).get('r'), 0.0)


def windmill_top(o):
    p = o.get('p') or {}
    return _f(p.get('h')) + _f(p.get('cap')) + _f(p.get('sail_len'))


def _label(o):
    return '%s %s' % (o.get('kind'), o.get('id') or '?')


def is_ground_kind(kind):
    """True for a kind that IS ground — one the seam reads a height off."""
    return _A.EXT_HEIGHTS.get(kind) is not None


def water_extent(o):
    """(half_x, half_z) of a v3 water surface in its OWN frame, in metres."""
    k, p = o.get('kind'), (o.get('p') or {})
    if k == 'water_body':
        return _f(p.get('rx')), _f(p.get('rz'))
    if k == 'water_path':
        return 0.5 * _f(p.get('len')), 0.5 * _f(p.get('w'))
    return 0.5 * _f(p.get('w')), 0.5 * _f(p.get('d'))


def surface_y(o, t=0.5):
    """The water surface height at station t along a record (0 at its start,
    1 at its end), in world metres.

    A LAKE and the sea are one datum — the record's y, whatever t. A REACH
    FALLS. Since water_v3 gave rivers a profile (2026-09-07) every water_path
    carries a (level0, level1) pair in its own frame and the record's y is the
    level at its START, so a reach that drops into a canyon reports y = the rim
    level and stands metres over its own banks everywhere downstream of its
    first node. Asking such a reach 'are your banks above y?' answers a
    question nobody asked. Records without the pair are flat, as before."""
    if o.get('kind') not in V3_FLOW_WATER:
        return _f(o.get('y'))
    p = o.get('p') or {}
    a, b = p.get('level0'), p.get('level1')
    if a is None or b is None:
        return _f(o.get('y'))
    return _f(o.get('y')) + _f(a) + (_f(b) - _f(a)) * _clamp(t, 0.0, 1.0)


def flow_band(o):
    """Half the width of the ground a carved reach OWNS, in metres.

    A water_path is drawn as a straight record but it does not run straight:
    carve_river hands the bed and the ribbon the same `meander`, and the
    channel wanders that far either side of the centre line before its banks
    are shouldered out on top. So the low, wet line of a 12 m river with a
    9.6 m meander can be twenty metres off the record's own x — which is why
    both questions below have to be asked of a BAND and not of a point."""
    _hx, hz = water_extent(o)
    p = o.get('p') or {}
    return _f(p.get('meander')) + hz + max(0.5, 0.5 * hz)


def _rim_offsets(o, out, n):
    """Where to stand to ask 'is the land here as high as the water?', in the
    water record's own frame — each with the station t of the water beside it.

    A LAKE or a sea is asked all round, on a ring just outside its footprint.
    A REACH is asked only sideways — on its two BANKS, spread along its length,
    and OUTSIDE its meander band: stand any closer and the answer is the
    reach's own bed, which is of course below its own water. Walking out past
    the END of a river and finding lower ground is not a fault either, it is
    the river's own valley continuing downhill, so the ends are never asked."""
    hx, hz = water_extent(o)
    if o.get('kind') in V3_FLOW_WATER:
        m = max(2, n // 2)
        off = flow_band(o) + max(2.0, hz)
        return [
            (hx * (-0.8 + 1.6 * i / (m - 1.0)), s * off, 0.1 + 0.8 * i / (m - 1.0))
            for s in (-1.0, 1.0)
            for i in range(m)
        ]
    return [
        (out * hx * math.cos(2.0 * math.pi * i / n), out * hz * math.sin(2.0 * math.pi * i / n), 0.5) for i in range(n)
    ]


def reach_bed(d, o, n=9):
    """The bed a carved reach actually lies on: the LOWEST ground across its
    meander band, at its middle, with the reach itself hidden. Sampling the
    centre point alone finds the untouched valley floor whenever the meander
    has swung the channel aside, and then a perfectly good river reads as a
    river buried metres under its own bed."""
    ry = _f(o.get('ry'))
    ca, sa = math.cos(ry), math.sin(ry)
    x, z = _f(o.get('x')), _f(o.get('z'))
    band = flow_band(o)
    had, was = 'hidden' in o, o.get('hidden')
    o['hidden'] = True
    try:
        return min(
            _A.ground_height(d, x + lz * sa, z + lz * ca)
            for lz in (band * (-1.0 + 2.0 * i / (n - 1.0)) for i in range(n))
        )
    finally:
        if had:
            o['hidden'] = was
        else:
            o.pop('hidden', None)


def water_rim(d, o, out=1.35, n=8):
    """(ground, water) at each point _rim_offsets picks, with the water record
    itself hidden. This is the whole 'is it a puddle on a plinth or is it lying
    in a hollow?' question asked in numbers — and asked against the surface AT
    THAT POINT, so a falling reach is judged against the height its water
    really has beside that bank."""
    ry = _f(o.get('ry'))
    ca, sa = math.cos(ry), math.sin(ry)
    x, z = _f(o.get('x')), _f(o.get('z'))
    had, was = 'hidden' in o, o.get('hidden')
    o['hidden'] = True
    try:
        return [
            (_A.ground_height(d, x + lx * ca + lz * sa, z - lx * sa + lz * ca), surface_y(o, t))
            for lx, lz, t in _rim_offsets(o, out, n)
        ]
    finally:
        if had:
            o['hidden'] = was
        else:
            o.pop('hidden', None)


def v3_water_fault(d, o):
    """'' if a v3 water surface lies in its own hollow, else why not.

    v3 water does NOT sit at the ground height: it sits at bed + 0.8 * depth,
    which is metres above the bed it was fitted to. So the two honest questions
    are (a) is the surface above its own bed, and (b) is the land AROUND it at
    least as high as the water — because water standing higher than its banks
    is the plinth the whole rebuild was for."""
    mid = surface_y(o, 0.5)
    # a reach's bed is SET to the straight fall between its two nodes, so bed
    # and surface are asked at the same station — but across the meander band,
    # not at the centre point (see reach_bed). Level water has no meander and
    # no excuse, so it is asked where it stands.
    flow = o.get('kind') in V3_FLOW_WATER
    bed = reach_bed(d, o) if flow else ground_under(d, o)
    sink = POOL_TOL if flow else 1e-3
    if mid < bed - sink:
        return 'water: %s lies %.2f m UNDER its own bed at %.2f m' % (_label(o), bed - mid, bed)
    rim = water_rim(d, o)
    below = [g for g, wy in rim if g < wy - RIM_TOL]
    if len(below) > len(rim) // 2:
        return (
            'water: %s stands at %.2f m with %d of %d rim samples below it (lowest %.2f m) — '
            'that is a puddle on a plinth, not water in a hollow'
            % (_label(o), mid, len(below), len(rim), min(g for g, _ in rim))
        )
    return ''


def drape_band(d, o):
    """(lowest, highest) ground a TILED drape covers, with the drape hidden.

    scatter_rocks (and its neighbours) seat a tile on a PLANE least-squares
    fitted to the ground under it and hand the record the gradient, so the tile
    really does follow the land. Over ground that BENDS, the plane's value at
    the centre is not the ground's, by exactly the curvature — a residual, not
    a fault. So the fair question for a tile is not 'is your centre off?' but
    'do you lie between the lowest and the highest ground you cover?'."""
    p = o.get('p') or {}
    hx, hz = 0.5 * _f(p.get('w')), 0.5 * _f(p.get('d'))
    x, z = _f(o.get('x')), _f(o.get('z'))
    had, was = 'hidden' in o, o.get('hidden')
    o['hidden'] = True
    try:
        hs = [_A.ground_height(d, x + sx * hx, z + sz * hz) for sx in (-1.0, 0.0, 1.0) for sz in (-1.0, 0.0, 1.0)]
    finally:
        if had:
            o['hidden'] = was
        else:
            o.pop('hidden', None)
    return min(hs), max(hs)


def is_tiled_drape(o):
    """True for a record seated on a fitted plane rather than at a point."""
    p = o.get('p') or {}
    return ('gx' in p or 'gz' in p) and _f(p.get('w')) > 0.0 and _f(p.get('d')) > 0.0


def ground_fault(d, o, tol=GROUND_TOL):
    """'' if the record sits on its ground, else the sentence that says why.

    A SCULPT is exempt: it is not a thing standing on the ground, it is a
    PARAMETER of the ground, and ground_v3 requires every one of them to be at
    y = 0 (a sculpt placed at the height there would lift the land before
    cutting into it). A GROUND SURFACE can only be at fault for FLOATING: a
    mountain standing on the base leaves the base 'under' a summit, and that is
    stacking, not burial. Everything that STANDS on the ground is judged both
    ways."""
    k = o.get('kind')
    if k in SCULPT_KINDS:
        return ''
    if k in V3_WATER:
        return v3_water_fault(d, o)
    y = _f(o.get('y'))
    if is_tiled_drape(o):
        lo, hi = drape_band(d, o)
        if y > hi + tol or y < lo - tol:
            return '%s: %s sits at %.2f m over ground running %.2f to %.2f m across its own tile' % (
                'floating' if y > hi else 'buried',
                _label(o),
                y,
                lo,
                hi,
            )
        return ''
    g = ground_under(d, o)
    dy = _f(o.get('y')) - g
    if k in LEVEL_WATER:
        if abs(dy) > WATER_TOL:
            return 'water: %s lies %.2f m %s the ground at %.2f m — level water sits ON the ground' % (
                _label(o),
                abs(dy),
                'above' if dy > 0 else 'below',
                g,
            )
    elif k in FLOW_WATER:
        if dy > WATER_TOL:
            return 'water: %s runs %.2f m above the ground at %.2f m' % (_label(o), dy, g)
        if dy < -POOL_TOL:
            return 'water: %s is %.2f m under the ground at %.2f m' % (_label(o), -dy, g)
    elif is_ground_kind(k):
        if dy > tol:
            return 'floating: %s sits at %.2f m over ground of %.2f m (%.2f m out)' % (_label(o), _f(o.get('y')), g, dy)
    elif abs(dy) > tol:
        return '%s: %s sits at %.2f m on ground of %.2f m (%.2f m out)' % (
            'floating' if dy > 0 else 'buried',
            _label(o),
            _f(o.get('y')),
            g,
            abs(dy),
        )
    return ''


def solid_ground_kinds(d):
    """Every OLD_SOLID_GROUND record in a drawing that also has a v3 ground.

    On a v3 drawing this list must be empty: mountains, rivers_lakes,
    coast_dunes and terrain all branch to a sculpt when a ground is there, so a
    solid appearing means a recipe reached past the branch."""
    if not any(o.get('kind') == GROUND_KIND for o in d.objs):
        return []
    return [(o.get('kind'), o.get('id')) for o in d.objs if o.get('kind') in OLD_SOLID_GROUND]


def landscape_warnings(d, tol=GROUND_TOL):
    """Every proportion (R8) and burial breach in the drawing, as sentences.

    The model calls describe_landscape after drawing freehand and reads this
    back: it is the same arithmetic the composer's own test runs."""
    out = []
    objs = [o for o in d.objs if o.get('kind') in LANDSCAPE_KINDS and not o.get('hidden')]
    trees = [o for o in objs if o.get('kind') in TREE_KINDS]
    peaks = [o for o in objs if o.get('kind') in PEAK_KINDS]
    if trees and peaks:
        th, ph = max(_hh(o) for o in trees), max(_hh(o) for o in peaks)
        if ph >= PEAK_MIN_M and th > MAX_TREE_OF_PEAK * ph + 1e-6:
            out.append(
                'proportion: the tallest tree is %.1f m against a %.1f m summit — beside mountains a '
                'tree may reach %.1f m (%g of the peak), or the wood reads as a second range'
                % (th, ph, MAX_TREE_OF_PEAK * ph, MAX_TREE_OF_PEAK)
            )
    for k, oid in solid_ground_kinds(d):
        out.append(
            'solid: %s %s is a v1 ground record on a v3 sculpted ground — a landform has to be a '
            'sculpt of the one ground, not a box parked on it' % (k, oid)
        )
    for o in objs:
        k = o.get('kind')
        if k == 'boulder' and boulder_across(o) > MAX_BOULDER_M + 1e-6:
            out.append(
                'size: %s is %.1f m across — a boulder is at most %g m, bigger is an outcrop'
                % (_label(o), boulder_across(o), MAX_BOULDER_M)
            )
        elif k == 'rock_field' and _f((o.get('p') or {}).get('size')) > MAX_BOULDER_M + 1e-6:
            out.append(
                'size: %s strews %.1f m boulders — %g m is the largest real boulder'
                % (_label(o), _f((o.get('p') or {}).get('size')), MAX_BOULDER_M)
            )
        elif k == 'windmill' and windmill_top(o) > MAX_WINDMILL_M + 1e-6:
            out.append(
                'size: %s stands %.1f m to the sail tip — a windmill is at most %g m'
                % (_label(o), windmill_top(o), MAX_WINDMILL_M)
            )
    for o in objs:
        why = ground_fault(d, o, tol)
        if why:
            out.append(why)
    return out
