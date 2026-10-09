# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""envelope_rules — where a thing is ALLOWED to stand (2026-09-10).

Why this family exists: on 2026-09-10 the assistant built a 20-storey tower
whose `add_stair(FH96, 0 -> 19, u)` became ONE stair_u record of 285 steps —
a 39.8 m flight that ran out through the east wall and stood in mid air — and
whose `add_fire_escape(cell='FH91')` planted the external escape stair in the
MIDDLE of the plan, while its own checklist said "opposite end of the plan".
Neither tool could see it: each reply named only the record it had just made.
Both are the same relation — a record and the BUILDING ENVELOPE it is meant to
be inside of, or outside of and touching.

This module is the geometry of that relation and nothing else. It owns no
kinds and no tools; it exports the envelope functions the drawing tools of
other families call before they draw (so the wrong thing cannot be produced),
plus one DESIGN_CHECK that names every record already standing in the wrong
place.

Plan axes, as everywhere in the studio: column letters run along +X, rows run
along +Z, so NORTH is -Z (the small rows, `zmin`) and SOUTH is +Z (`zmax`);
WEST is -X (`xmin`), EAST is +X (`xmax`). That is the same naming
arch_assistant.wall_on_side (L709-736) sorts by: its 'north' key is
`o['z'] - cz` ascending, i.e. the wall with the SMALLEST z.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
    _wall_world,
    cell_of,
    EXT_MODULES,
    storey_index,
    storey_of,
    wall_on_side,
)

KINDS: dict = {}
OPENINGS: list = []

DECK_KINDS = ('slab', 'roof_flat')  # what makes a group a building
DECK_T = {'slab': 0.22, 'roof_flat': 0.3}
ENV_WALL_KINDS = ('wall', 'curtain_wall')

# Things that belong INSIDE a building envelope. The furniture families are
# resolved lazily (interior_kinds()): extensions load alphabetically, so
# furniture_* is not imported yet when this module is, and a drawing may run
# with those families absent altogether.
INTERIOR_KINDS = frozenset(
    {
        'partition',
        'stair_straight',
        'stair_u',
        'stair_l',
        'stair_winder',
        'stair_spiral',
        'stair_landing',
        'elevator_shaft',
        'elevator_car',
        'escalator',
    }
)
FURNITURE_FAMILIES = ('furniture_living', 'furniture_kitchen_bath')

# Things that belong OUTSIDE the envelope, hung on a facade.
EXTERIOR_KINDS = frozenset({'fire_stair_exterior', 'canopy', 'balcony', 'awning', 'porch'})

POKE_TOL = 0.3  # metres a record may overhang its own envelope
FACADE_TOL = 0.6  # metres between an exterior record and the wall it hangs on
MAX_FINDINGS = 8

# A partition whose centre line sits this close to a facade line IS the facade:
# the outer wall is already there, so the partition only doubles it (and carries a
# second door beside the real entrance). 0.3 m clears a 0.15 m partition drawn
# flush against a 0.2 m wall; a partition a metre in is a real room wall.
FACADE_LINE_TOL = 0.3
# A partition sits exactly ON the envelope boundary, so the containment test needs
# an outward margin bigger than group_at's 0.05.
FACADE_IN_MARGIN = 0.35
MAX_FACADE_FINDINGS = 12


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


def interior_kinds() -> frozenset:
    """INTERIOR_KINDS plus every furniture kind the loaded families declare."""
    out = set(INTERIOR_KINDS)
    for fam in FURNITURE_FAMILIES:
        mod = EXT_MODULES.get(fam)
        if mod is not None:
            out.update((getattr(mod, 'KINDS', None) or {}).keys())
    return frozenset(out)


def _rot_bbox(x, z, w, dd, ry) -> tuple:
    """Axis-aligned plan bounds of a w (local X) x dd (local Z) rectangle centred
    on (x, z) and turned by `ry`. world_to_local maps local +X to
    (cos ry, -sin ry), so local (lx, lz) -> world (x + lx c + lz s, z - lx s + lz c)."""
    c, s = math.cos(ry or 0.0), math.sin(ry or 0.0)
    xs, zs = [], []
    for lx in (-w / 2.0, w / 2.0):
        for lz in (-dd / 2.0, dd / 2.0):
            xs.append(x + lx * c + lz * s)
            zs.append(z - lx * s + lz * c)
    return min(xs), min(zs), max(xs), max(zs)


# ── the envelope ─────────────────────────────────────────────────────────────
def group_envelope(d: Drawing, group: str):
    """The plan envelope of one group, or None when the group is not a building.

    {'xmin','zmin','xmax','zmax','y0','y1','top_deck','storeys'}: slabs and flat
    roofs contribute x +- p.w/2 by z +- p.d/2 and y .. y + p.t; walls and curtain
    walls contribute both ends (_wall_world(w, 0) and _wall_world(w, p.len)) and
    y .. y + p.h. `top_deck` is the highest slab/roof top (None when the group
    has no deck at all), `storeys` is (y1 - y0) / d.storey_h rounded.

    None when the group has neither a deck nor at least three walls — three
    walls is the least that can enclose anything, and it keeps a lone partition
    or a pair of garden walls from claiming to be a building.
    """
    g = str(group or '')
    if not g:
        return None
    xs, zs, ys = [], [], []
    decks, n_wall, n_deck = [], 0, 0
    for o in d.objs:
        if o.get('grp') != g or o.get('hidden'):
            continue
        k = o.get('kind')
        if k in DECK_KINDS:
            n_deck += 1
            t = _p(o, 't', DECK_T.get(k, 0.22))
            bx = _rot_bbox(o['x'], o['z'], _p(o, 'w', 0.0), _p(o, 'd', 0.0), o.get('ry') or 0.0)
            xs += [bx[0], bx[2]]
            zs += [bx[1], bx[3]]
            ys += [o['y'], o['y'] + t]
            decks.append(o['y'] + t)
        elif k in ENV_WALL_KINDS:
            n_wall += 1
            L = _p(o, 'len', 4.0)
            for u in (0.0, L):
                wx, wz = _wall_world(o, u)
                xs.append(wx)
                zs.append(wz)
            ys += [o['y'], o['y'] + _p(o, 'h', d.storey_h or 2.7)]
    if not xs or (n_deck == 0 and n_wall < 3):
        return None
    H = d.storey_h or 2.7
    y0, y1 = min(ys), max(ys)
    # 2026-09-11: storeys come from the SLABS (one per storey; void pieces share a
    # storey), not from the wall tops — a 1.1 m parapet on a 20-storey tower made
    # it "21 storeys" and the deck moved above the stair that had just reached it.
    slab_st = (
        {
            int(round((o['y'] - y0) / H))
            for o in d.objs
            if o.get('grp') == g and not o.get('hidden') and o.get('kind') == 'slab'
        }
        if H
        else set()
    )
    storeys = (max(slab_st) + 1) if slab_st else (int(round((y1 - y0) / H)) if H else 0)
    return {
        'group': g,
        'xmin': round(min(xs), 4),
        'zmin': round(min(zs), 4),
        'xmax': round(max(xs), 4),
        'zmax': round(max(zs), 4),
        'y0': round(y0, 4),
        'y1': round(y1, 4),
        'top_deck': round(max(decks), 4) if decks else None,
        'storeys': storeys,
    }


def envelopes(d: Drawing) -> dict:
    """{group: envelope} for every group that qualifies, in drawing order."""
    out = {}
    for o in d.objs:
        g = o.get('grp') or ''
        if not g or g in out:
            continue
        env = group_envelope(d, g)
        if env is not None:
            out[g] = env
    return out


def inside(env: dict, x: float, z: float, margin: float = 0.05) -> bool:
    """Is the plan point inside the envelope? `margin` is an OUTWARD tolerance:
    a wall centre sits exactly on the boundary line, so a hair outside counts."""
    m = _num(margin, 0.0)
    return (env['xmin'] - m <= x <= env['xmax'] + m) and (env['zmin'] - m <= z <= env['zmax'] + m)


def group_at(d: Drawing, x: float, z: float, envs: dict | None = None):
    """The name of the first building envelope containing (x, z), else None.
    Pass `envs` (= envelopes(d)) when calling this in a loop: rebuilding every
    envelope per record made check_envelope take 143 s on a 2,568-object tower
    (2026-09-11) — records x groups x objects."""
    for g, env in (envs if envs is not None else envelopes(d)).items():
        if inside(env, x, z):
            return g
    return None


def touches_facade(env: dict, x: float, z: float, tol: float = 0.6):
    """'north' | 'south' | 'east' | 'west' | None — the facade the plan point is
    within `tol` of. north = the zmin edge (-Z, the small rows), south = zmax,
    west = xmin, east = xmax: the same naming arch_assistant.wall_on_side uses,
    whose 'north' sort key is `o['z'] - cz` ascending. The nearest facade wins."""
    t = _num(tol, 0.6)
    cands = []
    if env['xmin'] - t <= x <= env['xmax'] + t:
        cands += [(abs(z - env['zmin']), 'north'), (abs(z - env['zmax']), 'south')]
    if env['zmin'] - t <= z <= env['zmax'] + t:
        cands += [(abs(x - env['xmin']), 'west'), (abs(x - env['xmax']), 'east')]
    cands = [c for c in cands if c[0] <= t]
    return min(cands)[1] if cands else None


# ── the plan footprint of one record ─────────────────────────────────────────
def _plan_size(o: dict) -> tuple:
    """(along local X, across local Z) of a record, in metres."""
    k = str(o.get('kind') or '')
    p = o.get('p') or {}
    if k == 'stair_u':
        # stairs_vertical.js L22-33: x0 = -(na*run + w)/2, the landing caps the
        # flight, so the run is na*run + w across 2w + gap.
        na = max(1, int(max(2, round(_p(o, 'steps', 16))) // 2))
        return na * _p(o, 'run', 0.28) + _p(o, 'w', 1.0), 2 * _p(o, 'w', 1.0) + _p(o, 'gap', 0.2)
    if k == 'stair_straight':
        return max(1.0, _p(o, 'steps', 16)) * _p(o, 'run', 0.28), _p(o, 'w', 1.0)
    if k == 'stair_l':
        w = _p(o, 'w', 1.0)
        return _p(o, 'steps_a', 8) * _p(o, 'run', 0.28) + w, _p(o, 'steps_b', 8) * _p(o, 'run', 0.28) + w
    if k == 'stair_winder':
        # a flight, a fan and a second flight: at worst it reaches the whole run
        L = max(3.0, _p(o, 'steps', 16)) * _p(o, 'run', 0.28)
        return L, max(L * 0.5, _p(o, 'w', 1.0))
    if k == 'stair_spiral':
        r = _p(o, 'r_out', 1.1)
        return 2 * r, 2 * r
    if k == 'elevator_shaft':
        return _p(o, 'w', 1.8), _p(o, 'd', 2.0)
    if k == 'escalator':
        a = max(5.0, min(60.0, _p(o, 'angle', 30.0)))
        return _p(o, 'rise', 2.7) / math.tan(math.radians(a)), _p(o, 'w', 1.0)
    if k == 'fire_stair_exterior':
        # stairs_vertical.js L114-130: nst = round(h / rise) steps of `run`,
        # plus one w x w landing beyond the top of the flight.
        w = _p(o, 'w', 1.2)
        nst = max(2, int(round(_p(o, 'h', 2.7) / max(0.05, _p(o, 'rise', 0.18)))))
        return nst * _p(o, 'run', 0.28) + w, w
    if 'len' in p:  # wall-like: length along local X, t across
        return _p(o, 'len', 4.0), max(_p(o, 't', 0.1), _p(o, 'd', 0.0), 0.05)
    if 'w' in p and ('d' in p or 'l' in p):
        return _p(o, 'w', 1.0), _p(o, 'd', 0.0) or _p(o, 'l', 1.0)
    if 'r_out' in p:
        return 2 * _p(o, 'r_out', 1.0), 2 * _p(o, 'r_out', 1.0)
    if 'r' in p:
        return 2 * _p(o, 'r', 0.5), 2 * _p(o, 'r', 0.5)
    if 'w' in p:
        return _p(o, 'w', 1.0), _p(o, 'w', 1.0)
    return 0.5, 0.5


def bbox_of(o: dict) -> tuple:
    """(xmin, zmin, xmax, zmax): the record's plan footprint, turned by its own
    `ry` and returned axis-aligned. Scale `s` multiplies it."""
    w, dd = _plan_size(o)
    sc = _num(o.get('s'), 1.0) or 1.0
    return _rot_bbox(_num(o.get('x'), 0.0), _num(o.get('z'), 0.0), abs(w) * sc, abs(dd) * sc, _num(o.get('ry'), 0.0))


def _near_point(env: dict, bb: tuple, o: dict) -> tuple:
    """The point of the record's footprint closest to the envelope rectangle."""

    def axis(lo, hi, blo, bhi, c):
        if bhi < lo:
            return bhi
        if blo > hi:
            return blo
        return min(max(c, max(lo, blo)), min(hi, bhi))

    return (
        axis(env['xmin'], env['xmax'], bb[0], bb[2], _num(o.get('x'), 0.0)),
        axis(env['zmin'], env['zmax'], bb[1], bb[3], _num(o.get('z'), 0.0)),
    )


def _facade_of(d: Drawing, o: dict, envs: dict, tol: float = FACADE_TOL) -> tuple:
    """(group, side) of the facade this record hangs on, else (nearest group, None)."""
    bb = bbox_of(o)
    best = (None, None, 1e18)
    for g, env in envs.items():
        px, pz = _near_point(env, bb, o)
        side = touches_facade(env, px, pz, tol)
        gap = math.hypot(max(env['xmin'] - px, 0.0, px - env['xmax']), max(env['zmin'] - pz, 0.0, pz - env['zmax']))
        if side:
            return g, side
        if gap < best[2]:
            best = (g, None, gap)
    return best[0], best[1]


def _cells(x0, z0, x1, z1) -> str:
    return f'{cell_of(x0, z0)}..{cell_of(x1 - 1e-6, z1 - 1e-6)}'


def _plural(n, word):
    return f'{n} {word}' if n == 1 else f'{n} {word}s'


def _category(kind: str) -> str:
    if kind == 'partition':
        return 'partition'
    if kind.startswith('stair_') or kind.startswith('elevator') or kind == 'escalator':
        return 'stair'
    return 'fixture'


# ── the check ────────────────────────────────────────────────────────────────
def check_envelope(d: Drawing) -> list:
    """Interior things inside their building, exterior things on its facade."""
    envs = envelopes(d)
    if not envs:
        return []
    interior = interior_kinds()
    ux0 = min(e['xmin'] for e in envs.values())
    uz0 = min(e['zmin'] for e in envs.values())
    ux1 = max(e['xmax'] for e in envs.values())
    uz1 = max(e['zmax'] for e in envs.values())
    plan_cells = _cells(ux0, uz0, ux1, uz1)

    out, orphans = [], {}
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden') or (k not in interior and k not in EXTERIOR_KINDS):
            continue
        if k in interior:
            g = group_at(d, o['x'], o['z'], envs)
            if g is None:
                orphans.setdefault(o.get('grp') or '', []).append(o)
                continue
            env = envs[g]
            bb = bbox_of(o)
            over = max(
                (env['xmin'] - bb[0], 'west'),
                (bb[2] - env['xmax'], 'east'),
                (env['zmin'] - bb[1], 'north'),
                (bb[3] - env['zmax'], 'south'),
            )
            if over[0] > POKE_TOL:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'envelope_poke',
                        'text': f'{_lbl(o)} leaves group "{g}" by {over[0]:.1f} m to the {over[1]} — '
                        f'draw it inside the plan (direction_deg) or shorten it',
                    }
                )
        elif k == 'fire_stair_exterior':
            g = group_at(d, o['x'], o['z'], envs)
            if g is not None:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'envelope_exterior',
                        'text': f'fire escape {o["id"]} stands INSIDE "{g}" — add_fire_escape(group="{g}", '
                        f'side="north") hangs it outside the facade',
                    }
                )
                continue
            host, side = _facade_of(d, o, envs)
            if side is None:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'envelope_exterior',
                        'text': f'fire escape {o["id"]} touches no facade — add_fire_escape(group='
                        f'"{host}", side="north") hangs it outside the facade',
                    }
                )
        elif k == 'canopy':
            host, side = _facade_of(d, o, envs)
            if side is None:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'envelope_exterior',
                        'text': f'canopy {o["id"]} touches no facade — a canopy is carried by a wall: '
                        f'add_canopy(group="{host}", side="south") hangs it on one',
                    }
                )

    for grp, recs in orphans.items():
        counts: dict = {}
        for o in recs:
            c = _category(o['kind'])
            counts[c] = counts.get(c, 0) + 1
        what = ' + '.join(_plural(n, c) for c, n in sorted(counts.items(), key=lambda kv: -kv[1]))
        who = f'room "{grp}" ({what})' if grp else f'{what} with no group'
        out.append(
            {
                'sev': 'error',
                'code': 'envelope_outside',
                'text': f'{who} stands outside every building — move it inside the plan ({plan_cells})',
            }
        )

    if len(out) > MAX_FINDINGS:
        rest = len(out) - MAX_FINDINGS
        out = out[:MAX_FINDINGS] + [
            {
                'sev': 'info',
                'code': 'envelope_more',
                'text': f'... and {rest} more envelope finding{"s" if rest > 1 else ""}',
            }
        ]
    return out


def facade_side_of(env: dict, x: float, z: float, ry) -> str | None:
    """'north' | 'south' | 'east' | 'west' | None — the facade LINE a partition
    centred on (x, z) and turned by `ry` lies on. A partition running along +X
    (|cos ry| > 0.7) can only double the north (zmin) or south (zmax) face; one
    running along Z can only double the west (xmin) or east (xmax) face. Unlike
    touches_facade this is not a proximity test on a point: the orientation has to
    agree, or a partition ENDING at the wall would read as doubling it."""
    along_x = abs(math.cos(_num(ry, 0.0))) > 0.7
    if along_x:
        if abs(z - env['zmin']) <= FACADE_LINE_TOL:
            return 'north'
        if abs(z - env['zmax']) <= FACADE_LINE_TOL:
            return 'south'
    else:
        if abs(x - env['xmin']) <= FACADE_LINE_TOL:
            return 'west'
        if abs(x - env['xmax']) <= FACADE_LINE_TOL:
            return 'east'
    return None


def check_facade_partitions(d: Drawing) -> list:
    """A partition drawn ON a facade line — the outer wall is already the room's.

    2026-09-12: on the live 20-storey tower add_room drew the lobby's south
    partition on the facade line with its own 2.8 m door a metre beside the
    facade's glass double door. design_check then blamed the partition, the model
    deleted it, and the door was left standing in mid air. On a GLAZED storey (the
    curtain_wall records replace the wall there) it is worse than a doubling: the
    partition walls the room off from the view it was glazed for — so that case is
    an error, an opaque storey only a warning.
    """
    envs = envelopes(d)
    if not envs:
        return []
    out, glazed_at = [], {}
    for o in d.objs:
        if o.get('hidden') or o.get('kind') != 'partition':
            continue
        x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
        group = next((g for g, e in envs.items() if inside(e, x, z, FACADE_IN_MARGIN)), None)
        if group is None:
            continue
        side = facade_side_of(envs[group], x, z, o.get('ry'))
        if side is None:
            continue
        try:
            st = storey_index(d, o)
        except Exception:
            st = storey_of(_num(o.get('y'), 0.0), d.storey_h or 2.7)
        key = (group, side, st)
        if key not in glazed_at:
            glazed_at[key] = wall_on_side(d, group, side, st, kinds=('curtain_wall',))[0] is not None
        glazed = glazed_at[key]
        why = (
            (" — a glass curtain wall: the partition blocks the view; delete it, the facade is the room's wall")
            if glazed
            else (" — delete it, the facade is the room's wall (a door here is a second entrance)")
        )
        out.append(
            {
                'sev': 'error' if glazed else 'warn',
                'code': 'env_facade_partition',
                'text': f'{_lbl(o)} doubles the {side} facade of "{group}" on storey {st}' + why,
            }
        )

    if len(out) > MAX_FACADE_FINDINGS:
        rest = len(out) - MAX_FACADE_FINDINGS
        out = out[:MAX_FACADE_FINDINGS] + [
            {
                'sev': 'info',
                'code': 'env_facade_partition',
                'text': f'... and {rest} more partition{"s" if rest > 1 else ""} on a facade line',
            }
        ]
    return out


DESIGN_CHECKS = [check_envelope, check_facade_partitions]

PROMPT = (
    'ENVELOPE: every building group has a plan envelope — the rectangle its slabs and walls occupy. '
    'Interior things (partitions, stairs, lifts, furniture) belong INSIDE it: a stair drawn outside the '
    'plan, or one whose flight runs out through a facade, is refused and reported by design_check. '
    'Exterior things (fire escapes, canopies, balconies) belong OUTSIDE it and TOUCHING a facade within '
    '0.6 m — a fire escape in the middle of the plan, or a canopy floating 5 m off the wall, is the same '
    'error. north is -Z (small rows), south +Z, west -X, east +X.'
)

EXAMPLES = [
    {
        'ask': 'put the stair and lift core in the tower, then check it',
        'calls': [
            {'tool': 'add_stair', 'args': {'cell': 'FH96', 'from_storey': 0, 'to_storey': 1, 'kind': 'u'}},
            {'tool': 'add_elevator', 'args': {'cell': 'FJ96', 'from_storey': 0, 'to_storey': 3}},
            {'tool': 'design_check', 'args': {}},
        ],
    },
    {
        'ask': 'the WC I drew does not seem to be in the building — check the drawing',
        'calls': [{'tool': 'design_check', 'args': {}}],
    },
]

TOOLS: list = []
