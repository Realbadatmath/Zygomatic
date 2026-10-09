# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arch_reference_build.portfolio — THE PORTFOLIO (2026-09-23): forty-odd
pictures of a finished drawing, not ten (lines 1265-1704 of the original single
file, moved verbatim).
"""

import math

import mathutils

from .api import asset_objects
from .base import log
from .inspection import (
    CLEAR_M,
    EYE_M,
    FIG_H,
    HOLD_M,
    INSPECT_FOCAL,
    INSPECT_SENSOR,
    _body_bounds,
    _cam_ortho,
    _cam_persp,
    _cast,
    _clear_ahead,
    _cloud,
    _figure,
    _fit_bbox,
    _floors,
    _shoot_set,
    _sphere,
    cam_and,
)
from .scene import _make_cam, _ortho_span

# ── THE PORTFOLIO (2026-09-23) — forty-odd pictures, not ten ─────────────────
# The operator's rule, tightened the same day the ten-shot set was built: "i
# said 10 before but after every drawing, make sure ai assistant delivers
# portfolio folder with 40+ images from projects", and with it "make sure
# drawing curves and material quality is done perfectly".
#
# Ten pictures catch a deck floating over the sheer. They do not catch a door
# that was never cut, a cabin with no window, a hold with nothing in it, a
# chine that wanders half a metre between stations, or a surface left on
# Blender's default grey — those need a camera standing on EVERY deck, a cut at
# every station, a raking light down the side and a close lens on the joints.
# So the portfolio is generated from the asset rather than listed by hand:
# orbit, orthographic set, a cut per station, an interior per level, and the
# detail lenses. Every frame carries the measurement its camera made.
PORTFOLIO_N = 44  # the operator's floor is 40; the plan makes ~47
ORBIT_N = 12  # every 30 degrees around it
HIGH_N = 4  # ... and four from up high, off the quarters
STATIONS = (0.12, 0.28, 0.44, 0.60, 0.76, 0.90)  # where the body is cut across
DECK_LEVELS = 4  # how many levels get their own interior pair
MERGE_M = 1.2  # two 'levels' this close are one cambered deck
DETAIL_FOCAL = 50.0  # the close lens: a joint, a port, a rail
RAKE_FOCAL = 50.0  # the grazing shot down a flank — the FAIRNESS check
PORTRAIT_COS = 0.86  # an orbit shot this near end-on is a tall subject


def _cloud_extreme(pick, within=None):
    """One real vertex of the asset, chosen by a key — the bow point, the
    lowest point of the keel, the top of the mast. The bounding box corner is
    not on the object; a camera aimed at it aims past the subject."""
    pts = _cloud()
    if not pts:
        return None
    ok = [p for p in pts if (within is None or within(p))]
    return max(ok or pts, key=pick)


def _levels(lo, hi, cy=0.0, n=26):
    """Every level a person could stand on, clustered down the length:
    [(z, headroom, span_m)], highest first.

    Sampled, not assumed. A ship has a weather deck, a between-decks and a
    hold, and none of them is at a fraction of the bounding box — the box
    reaches up the topmast and out along the bowsprit."""
    L = max(0.5, hi[0] - lo[0])
    r = min(2.0, max(0.55, 0.06 * max(L, hi[1] - lo[1])))
    seen = {}
    for i in range(n):
        x = lo[0] + L * (i + 0.5) / float(n)
        for z, head in _floors(x, cy, hi[2] + 1.0, lo[2] - 1.0, head_m=HOLD_M, limit=8, r=r):
            e = seen.setdefault(int(round(z / 0.8)), {'zs': [], 'head': 0.0, 'xs': []})
            e['zs'].append(z)
            e['xs'].append(x)
            e['head'] = max(e['head'], head)
    out = []
    for e in seen.values():
        if len(e['xs']) < 2:  # one hit is a hatch cover, not a deck
            continue
        out.append(
            (
                round(sum(e['zs']) / len(e['zs']), 3),
                round(min(e['head'], 999.0), 2),
                round(max(e['xs']) - min(e['xs']), 2),
            )
        )
    out.sort(key=lambda t: -t[0])
    # A cambered deck answers at two heights half a metre apart and comes back
    # as two levels — which cost this ship two identical interior views out of
    # eight. Merge anything within MERGE_M, keeping the one that runs furthest
    # fore and aft, and throw away what is too short to be a deck at all: the
    # top of a capstan is a surface, not a level.
    merged = []
    for lv in out:
        if merged and abs(merged[-1][0] - lv[0]) < MERGE_M:
            if lv[2] > merged[-1][2]:
                merged[-1] = lv
            continue
        merged.append(lv)
    floor = max(2.0, 0.12 * L)
    kept = [lv for lv in merged if lv[2] >= floor]
    if len(kept) < len(merged):
        log(f'levels: {len(merged) - len(kept)} surface(s) under {floor:.1f} m long are not decks')
    return kept


def _inside_shot(z_level, back, lo, hi, cy=0.0, n=22):
    """One interior camera standing on the level nearest z_level, looking
    forward (or aft). Returns (cam, note, figures) like the inspection set's
    own interiors — same rules: the standpoint is chosen by what can be SEEN
    from it, and a 1.75 m figure stands down the view for scale."""
    L = max(0.5, hi[0] - lo[0])
    W = max(0.5, hi[1] - lo[1])
    cx = (lo[0] + hi[0]) / 2.0
    r = min(2.0, max(0.55, 0.06 * max(L, W)))
    tx = lo[0] if back else hi[0]
    best = None
    for i in range(n):
        x = lo[0] + L * (i + 0.5) / float(n)
        fl = [
            (z, h)
            for (z, h) in _floors(x, cy, z_level + 1.4, z_level - 1.4, head_m=1.0, r=r)
            if abs(z - z_level) <= 1.0
        ]
        if not fl:
            continue
        z0, head = fl[0]
        if (x - cx) * (-1.0 if back else 1.0) > 0.18 * L:
            continue  # stand BEHIND what you look at
        eye = z0 + (EYE_M if head > 900 else min(EYE_M, max(0.85, head - 0.25)))
        ca = _clear_ahead((x, cy, eye), (tx, cy, z0 + 0.6))
        if best is None or ca > best[0] + 0.05:
            best = (ca, x, z0, head, eye)
    if best is None:
        return None, f'no surface to stand on near {z_level:.2f} m', []
    ca, x0, z0, head, eye = best
    fd = min(max(ca * 0.55, 2.5), 0.30 * L)
    fx = x0 + (fd if tx > x0 else -fd)
    fy = cy + (1.25 if W > 4.0 else 0.0)
    fl = _floors(fx, fy, z0 + 2.2, z0 - 2.2, head_m=0.9, r=r)
    figs = _figure((fx, fy, fl[0][0] if fl else z0))
    note = (
        f'standing on the level at {z0:.2f} m, x {x0:.1f} m, eye {eye:.2f} m, '
        + ('open sky over it' if head > 900 else f'{head:.2f} m of headroom')
        + f', looking {"aft" if back else "forward"}, clear ahead {ca:.1f} m; '
        f'the red figure is {FIG_H:.2f} m tall, {fd:.1f} m away'
    )
    if ca < CLEAR_M:
        note += ' — the BEST standpoint on this level still looks straight into something'
    return cam_and((x0, cy, eye), (tx, cy, z0 + 0.60)), note, figs


def _portfolio_shots(width, height):
    """[(title, make_camera, (w, h))] — the whole plan, built from the asset."""
    sph = _sphere(asset_objects())
    if sph is None:
        return []
    lo, hi, ctr, rad = sph
    L, W, H = hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]
    cx, cy = ctr[0], ctr[1]
    body = _body_bounds() or (lo, hi)
    (bx0, by0, bz0), (bx1, by1, bz1) = body[0], body[1]
    bcx, bcz = (bx0 + bx1) / 2.0, (bz0 + bz1) / 2.0
    shots = []

    def _add(title, mk, portrait=False):
        w, h = int(width), int(height)
        fr = (max(320, int(round(h * 0.80))), h) if (portrait and w > h) else (w, h)
        shots.append((title, mk, fr))

    # 1 ── ALL ROUND IT: twelve standpoints on a ring, four more from up high.
    #      One quarter view flatters everything; twelve cannot all be lucky.
    for i in range(ORBIT_N):
        a = 2.0 * math.pi * i / ORBIT_N
        d = (math.cos(a), math.sin(a), 0.20)
        deg = int(round(math.degrees(a)))
        port = abs(math.cos(a)) > PORTRAIT_COS

        def mk(d=d, deg=deg, port=port):
            fw, fh = (max(320, int(round(height * 0.80))), height) if port and width > height else (width, height)
            n = mathutils.Vector(d).normalized()
            dd = _fit_bbox(lo, hi, ctr, n, INSPECT_FOCAL, fw, fh)
            cam = _cam_persp(ctr + n * dd, ctr, INSPECT_FOCAL, clip_start=max(0.05, dd * 0.002))
            return cam, (
                f'on the ring, {deg} degrees round from the bow, eye a fifth of the way up; '
                f'{INSPECT_FOCAL:.0f} mm, {dd:.0f} m out'
            )

        _add(f'orbit_{deg:03d}', mk, port)
    for i in range(HIGH_N):
        a = math.pi / 4.0 + math.pi / 2.0 * i
        d = (math.cos(a) * 0.55, math.sin(a) * 0.55, 0.95)
        deg = int(round(math.degrees(a)))

        def mk(d=d, deg=deg):
            n = mathutils.Vector(d).normalized()
            dd = _fit_bbox(lo, hi, ctr, n, INSPECT_FOCAL, width, height)
            cam = _cam_persp(ctr + n * dd, ctr, INSPECT_FOCAL, clip_start=max(0.05, dd * 0.002))
            return cam, f'from above, {deg} degrees round, 60 degrees up; {dd:.0f} m out'

        _add(f'high_{deg:03d}', mk)

    # 2 ── THE ORTHOGRAPHIC SET: what a draughtsman would issue. These are the
    #      views a curve is JUDGED in — a sheer that wanders reads as a wobble
    #      in the side elevation and as nothing at all in a perspective.
    for title, view in (
        ('ortho_side', 'side'),
        ('ortho_side_other', 'other_side'),
        ('ortho_bow', 'front'),
        ('ortho_stern', 'back'),
        ('ortho_plan', 'top'),
        ('ortho_underside', 'bottom'),
    ):

        def mk(view=view):
            cam = _make_cam(view, asset_objects())
            return cam, f'orthographic {view} — measure curves and spacing off this one, not off a perspective'

        _add(title, mk, portrait=view in ('front', 'back'))

    # 3 ── CUT IT OPEN: along the centreline, along a quarter line, and across
    #      the body at six stations. A hull with nothing inside it looks
    #      finished from every outside camera there is.
    # Every "centreline" below is the SUBJECT's, not the world's. A reference
    # asset is centred on the origin by the layout convention; a DRAWING sits
    # wherever it sits on the site grid, and a pavilion 40 m north of the
    # origin had its sections cut through empty air and no interior view at all
    # until this used cy.
    def mk_long():
        cam = _cam_ortho((bcx, cy, bcz), (0, 1, 0), _ortho_span(bx1 - bx0, bz1 - bz0, 1.10))
        return cam, 'CUT on the centreline, looking at the far half: every deck, beam and step where it really sits'

    _add('section_long', mk_long)

    def mk_long_q():
        yq = (by1 - by0) * 0.26
        cam = _cam_ortho((bcx, cy - yq, bcz), (0, 1, 0), _ortho_span(bx1 - bx0, bz1 - bz0, 1.10))
        return cam, (
            f'CUT along the quarter line, {yq:.2f} m off the centreline — the cabins and the side '
            'of the hold, which the centreline cut goes straight past'
        )

    _add('section_long_quarter', mk_long_q)
    for f in STATIONS:

        def mk(f=f):
            x = bx0 + (bx1 - bx0) * f
            cam = _cam_ortho((x, cy, bcz), (1, 0, 0), _ortho_span(by1 - by0, bz1 - bz0, 1.18))
            return cam, (
                f'CUT across at {f * 100:.0f} % of the body from aft (x {x:.2f} m), looking forward: '
                'the section here, the deck heights and the headroom between them'
            )

        _add(f'section_at_{int(f * 100):02d}', mk, portrait=True)

    # 4 ── DECK PLANS: a horizontal cut a hand's breadth over each level, so
    #      what stands ON that deck — and every door and hatch through it — is
    #      seen in plan. The near clip does the cutting.
    lv = _levels(lo, hi, cy)
    for n, (z, head, span) in enumerate(lv[:DECK_LEVELS]):

        def mk(z=z, head=head, span=span):
            cam = _cam_ortho((cx, cy, z + 1.55), (0, 0, -1), _ortho_span(L, W, 1.06))
            return cam, (
                f'PLAN CUT 1.55 m over the level at {z:.2f} m (it runs {span:.1f} m fore and aft, '
                + ('open to the sky' if head > 900 else f'{head:.2f} m of headroom')
                + '): everything standing on this deck, and every opening through it'
            )

        _add(f'deckplan_{n}_{z:.1f}m'.replace('.', 'p'), mk)

    # 5 ── FROM INSIDE, ON EVERY LEVEL: forward and aft. One interior view is a
    #      corridor; a pair per deck is the inside of the thing.
    for n, (z, _head, _span) in enumerate(lv[:DECK_LEVELS]):
        for back in (False, True):

            def mk(z=z, back=back):
                return _inside_shot(z, back, lo, hi, cy)

            _add(f'inside_{n}_{"aft" if back else "fwd"}', mk)

    # 6 ── THE CURVE CHECK: two grazing shots, one down the side at deck
    #      height, one along the bottom. A hull's fairness is invisible
    #      square-on and obvious along the surface — a flat spot between two
    #      stations shows as a kink in the highlight and nowhere else.
    def mk_rake():
        y = cy + (hi[1] - cy) * 0.92
        z = bz1 - (bz1 - bz0) * 0.22
        loc = (hi[0] - L * 0.04, y, z)
        cam = _cam_persp(
            loc, (lo[0] + L * 0.10, cy + (hi[1] - cy) * 0.30, z - (bz1 - bz0) * 0.10), RAKE_FOCAL, clip_start=0.05
        )
        return cam, (
            f'RAKING down the flank from the bow quarter at {z:.2f} m, {RAKE_FOCAL:.0f} mm: the '
            'highlight runs the length of the surface, so a flat spot, a kink or a station out of '
            'line shows as a break in it. Fairness is read here.'
        )

    _add('rake_side', mk_rake)

    def mk_rake_low():
        z = bz0 + (bz1 - bz0) * 0.10
        loc = (hi[0] - L * 0.02, cy + (hi[1] - cy) * 0.55, bz0 - max(1.0, H * 0.06))
        cam = _cam_persp(loc, (lo[0] + L * 0.15, cy, z), RAKE_FOCAL, clip_start=0.05)
        return cam, (
            'RAKING along the BOTTOM from forward and below: the run of the bilge and the garboard, '
            'where a loft goes unfair first'
        )

    _add('rake_bottom', mk_rake_low)

    # 7 ── THE CLOSE LENS: the joints and the fittings, where "finished" is
    #      decided — a door that is a painted rectangle, a port with no frame,
    #      a rail that stops short, a material still on Blender's grey.
    def _detail(title, target, ndir, field_m, why, port=False):
        # `field_m` is HOW WIDE A PIECE OF THE SHIP the frame holds — the first
        # portfolio aimed the close lens by distance and came back with four
        # frames of one plank and one of a bare pole against the sky. A close
        # view is defined by what it contains, not by how near it stands.
        def mk(target=target, ndir=ndir, field_m=field_m, why=why):
            t = mathutils.Vector(target)
            n = mathutils.Vector(ndir).normalized()
            dist = max(1.5, (float(field_m) / 2.0) / (INSPECT_SENSOR / 2.0 / DETAIL_FOCAL))
            loc = t + n * dist
            # AIM ON THE SURFACE, not at a point worked out in advance: the
            # intended target is a guess off the bounding body, and a close
            # lens aimed 2 m inboard of the planking photographs the sea behind
            # it. Cast at it and take what is actually hit.
            hit, hloc, _nr, _ob = _cast(tuple(loc), tuple(t - loc))
            # take the hit only when it is the SUBJECT and not something that
            # wandered in front of the lens: a shroud 2 m out would otherwise
            # become what the picture is of
            near = hit and (mathutils.Vector(hloc) - loc).length < 0.35 * dist
            aim = mathutils.Vector(hloc) if (hit and not near) else t
            cam = _cam_persp(loc, aim, DETAIL_FOCAL, clip_start=0.03)
            ca = (mathutils.Vector(aim) - loc).length
            return cam, (
                f'{why}; {DETAIL_FOCAL:.0f} mm at {dist:.0f} m, holding about {field_m:.0f} m of the '
                f'ship across the frame, on ({aim.x:.1f}, {aim.y:.1f}, {aim.z:.1f}) m, {ca:.1f} m out'
                + (
                    ''
                    if hit
                    else ' — NOTHING was hit along this line: the lens is aimed past the '
                    'asset, so what you see is whatever lies beyond it'
                )
                + (
                    f' — something stands only {(mathutils.Vector(hloc) - loc).length:.1f} m in front of the lens'
                    if near
                    else ''
                )
            )

        _add(title, mk, port)

    bow = _cloud_extreme(lambda p: p[0], within=lambda p: bz0 - 1.0 <= p[2] <= bz1 + 1.0)
    stern = _cloud_extreme(lambda p: -p[0], within=lambda p: bz0 - 1.0 <= p[2] <= bz1 + 1.0)
    topp = _cloud_extreme(lambda p: p[2])
    bowv = (bow.x, cy, bcz + (bz1 - bcz) * 0.5) if bow is not None else (bx1, cy, bcz)
    stv = (stern.x, cy, bcz + (bz1 - bcz) * 0.5) if stern is not None else (bx0, cy, bcz)
    _detail(
        'detail_bow',
        bowv,
        (0.55, 0.72, 0.22),
        max(8.0, 0.28 * L),
        'the BOW close to: the stem, the head, where the planking lands on it',
        True,
    )
    _detail(
        'detail_stern',
        stv,
        (-0.60, 0.68, 0.22),
        max(8.0, 0.30 * L),
        'the STERN close to: the transom, the rudder and its hangings, the windows in it',
        True,
    )
    _detail(
        'detail_midship_side',
        (bcx, by1, bz1 - (bz1 - bz0) * 0.25),
        (0.15, 0.95, 0.12),
        max(10.0, 0.34 * L),
        'the SIDE amidships close to: the ports, the sills, the rails and what carries them',
    )
    _detail(
        'detail_entry',
        (bcx + (bx1 - bcx) * 0.35, by1, bz1 - (bz1 - bz0) * 0.12),
        (0.25, 0.92, 0.18),
        max(7.0, 0.20 * L),
        'where a man COMES ABOARD: the entry, the steps up the side, the gangway opening',
    )
    _detail(
        'detail_stern_windows',
        (stv[0] + (bcx - stv[0]) * 0.10, cy + (by1 - cy) * 0.55, bz1 - (bz1 - bz0) * 0.10),
        (-0.45, 0.80, 0.25),
        max(8.0, 0.24 * L),
        'the quarter and the CABIN LIGHTS: windows, frames, galleries',
    )
    if topp is not None:
        _detail(
            'detail_top',
            (topp.x, cy, topp.z - H * 0.10),
            (0.35, 0.85, 0.05),
            max(8.0, 0.22 * H),
            'the HIGHEST work: tops, caps, trucks — where a spar is often left as a bare cylinder',
        )
    _detail(
        'detail_deck_fwd',
        (bcx + (bx1 - bcx) * 0.45, cy, bz1),
        (0.45, 0.35, 0.82),
        max(10.0, 0.34 * L),
        'the DECK forward, from over it: hatches, bitts, gratings, what is fastened down',
    )
    _detail(
        'detail_deck_aft',
        (stv[0] + (bcx - stv[0]) * 0.35, cy, bz1),
        (-0.45, 0.35, 0.82),
        max(10.0, 0.34 * L),
        'the DECK aft, from over it: the helm, the companion, the cabin doors',
    )
    return shots


def _trim(shots, want):
    """Cut a camera plan down to `want` frames without losing a FAMILY.

    The orbit ring thins first — twelve standpoints go to six and still go all
    the way round — then the high quarters, then the stations. The interiors
    and the detail lenses are never thinned: they are the ones that catch a
    missing door, and a portfolio without them is a set of postcards. `want`
    of 0 means the whole plan, which is what the operator's "40+" asks for."""
    if not want or want >= len(shots):
        return list(shots)
    keep = list(shots)
    for pref in ('orbit_', 'high_', 'section_at_', 'deckplan_'):
        if len(keep) <= want:
            break
        fam = [i for i, sh in enumerate(keep) if sh[0].startswith(pref)]
        n_rm = min(len(keep) - want, max(0, len(fam) - 2))
        if n_rm <= 0:
            continue
        n_keep = len(fam) - n_rm
        # keep n_keep of them, evenly spaced around the family, first one first
        survive = {fam[min(len(fam) - 1, int(round(k * len(fam) / float(n_keep))))] for k in range(n_keep)}
        keep = [sh for i, sh in enumerate(keep) if i not in set(fam) or i in survive]
    return keep


def _portfolio(base, width, height, engine, want=0):
    """THE PORTFOLIO: the whole plan, rendered. Returns [{path, title, note,
    portfolio}]."""
    shots = _portfolio_shots(width, height)
    if not shots:
        log('portfolio: nothing to photograph')
        return []
    shots = _trim(shots, want)
    log(
        f'portfolio: {len(shots)} pictures planned — '
        + ', '.join(t for t, _m, _f in shots[:8])
        + (' …' if len(shots) > 8 else '')
    )
    return _shoot_set(shots, base, 'shot', engine, 'portfolio', photo=True)
