# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""balconies_facade — the assistant's facade-mounted elements.

Tools: add_balconies, add_parapet, add_canopy, add_louvres, add_facade_bands,
add_pilasters.

THE OUTWARD RULE (the one thing this family is about). Every kind here is
drawn in its own local frame projecting toward LOCAL -Z, whose world direction
is (-sin ry, -cos ry). A wall record does not know which of its two faces is
the outside, so this module decides it: it takes the centroid of the wall's
GROUP (all records sharing its `grp`; the selection itself when the wall has
none) and, if local -Z points back toward that centroid, adds PI to ry. For a
draw_box the centroid is the box centre, so the north wall (ry 0, smallest z)
keeps ry 0 and its balconies project toward -z, while the south wall (ry 0,
largest z) is flipped to ry PI and projects toward +z. The record is then
pushed out of the wall by half its thickness so it hangs off the OUTER face —
which is why a north-wall balcony's z is SMALLER than its wall's z.
"""

from __future__ import annotations

import math

import re

from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    _wall_world,
    storey_of,
    deck_top,
    host_wall,
)

KINDS = {
    'balcony': {'w': 2.4, 'd': 1.2, 't': 0.18, 'rail_h': 1.0, 'post': 0.04},
    'canopy': {'w': 3, 'd': 1.5, 't': 0.12, 'h_drop': 0},
    'awning': {'w': 3, 'd': 1.2, 'angle': 20},
    'cornice': {'len': 4, 'h': 0.3, 'd': 0.25},
    'pilaster': {'h': 2.7, 'w': 0.4, 'd': 0.12},
    'louvre_fins': {'w': 3, 'h': 2.7, 'fin': 0.3, 'spacing': 0.4, 't': 0.03},
    'sunshade': {'w': 3, 'd': 0.8, 't': 0.05, 'slats': 8},
    'string_course': {'len': 4, 'h': 0.12, 'd': 0.08},
    'parapet_cap': {'len': 4, 'w': 0.3, 't': 0.06},
}
OPENINGS: list = []

PROMPT = (
    'Facade elements — all of these clip onto straight walls and project outward, away from the '
    'building centre (the tool works the outward side out for you): add_balconies(walls, '
    'every_n_storeys, storey_offset, per_wall, width, depth, sides) hangs balconies with railings, '
    'spread like windows, skipping the ground storey by default; add_parapet(group, height, '
    'thickness) runs a low wall round the top storey of a group — use it before a flat roof; '
    'add_canopy(wall_id, at, width, depth, kind) puts one canopy (flat plate) or awning (sloped) '
    'over an entrance or a shopfront; add_louvres(walls, spacing, depth) covers whole walls in '
    'vertical sun fins; add_facade_bands(group, every_n_storeys, kind, depth) runs a cornice or a '
    'thin string_course round every wall at a storey top; add_pilasters(walls, spacing) sets '
    'shallow piers along a wall every few metres. walls/group take "new", a group name or wall ids — a '
    'CURTAIN WALL is a host too, so a glazed storey can carry balconies; naming walls by id also '
    'switches the storey rule off, because then you picked the storeys yourself.'
)


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


def _wall_like(o: dict) -> bool:
    """Is this record a facade host? A wall or a partition, and — since
    2026-09-10 — anything wall-shaped that stands in the facade: a record whose
    kind says wall and which carries a wall's own geometry (p.len, p.h, p.t), so
    _wall_world/_face read it exactly as they read the wall it replaced. This is
    what add_curtain_wall leaves behind: glazing a storey used to make it
    invisible to every tool in this file (job 71ac02b0 hung 0 balconies on a
    20-storey tower whose south face was curtain_wall)."""
    if o['kind'] in ('wall', 'partition'):
        return True
    p = o.get('p') or {}
    return 'wall' in o['kind'] and 'len' in p and 'h' in p and 't' in p


def _words(s: str) -> set:
    return {w for w in re.split(r'[^a-z0-9]+', str(s).lower()) if w}


def _by_id(d: Drawing, which) -> bool:
    """True when `which` names records ONE BY ONE. Then the caller asked for
    THESE hosts and a storey rule must not quietly drop them (job 71ac02b0:
    nine curtain walls passed by id, every one skipped 'on other storeys')."""
    if isinstance(which, (list, tuple, set)):
        return True
    w = str(which or '').strip()
    return bool(w) and w not in ('new', 'all', 'walls') and d.find(w) is not None


def _shown(which) -> str:
    return (
        ('[' + ', '.join(str(w) for w in list(which)[:6]) + ']')
        if isinstance(which, (list, tuple, set))
        else f'"{which}"'
    )


def _pick(d: Drawing, which, sides=None):
    """(hosts, why): the wall-like records `which` names, and — when that list is
    empty — a sentence saying what WAS there and why none of it qualified. Never
    return an empty list with an empty reason: the caller has to be able to
    refuse with a cause."""
    sel = [o for o in d.select(which) if o is not None]
    if not sel and isinstance(which, str) and which.strip():
        # 2026-09-10: add_curtain_wall(name="tower_glazing") NAMES the records but
        # leaves them in the wall's own group, so "tower_glazing" is neither an id
        # nor a group and d.select finds nothing. Match the name the caller gave.
        want_name = which.strip().lower()
        sel = [o for o in d.objs if o['name'].lower() == want_name]
    hosts = [o for o in sel if _wall_like(o)]
    named = hosts
    want: set = set()
    if sides:
        want = {str(s).lower() for s in (sides if isinstance(sides, (list, tuple, set)) else [sides])}
        named = [o for o in hosts if want & _words(o['name'])]
    if named:
        return named, ''
    if not sel:
        return [], f'nothing in the drawing matches {_shown(which)}'
    if not hosts:
        kinds = ', '.join(sorted({o['kind'] for o in sel})[:6])
        return [], (f'{_shown(which)} matches {len(sel)} record(s) but none is a wall — they are {kinds}')
    names = ', '.join(sorted({o['name'] for o in hosts})[:4])
    kinds = '/'.join(sorted({o['kind'] for o in hosts})[:4])
    sts = sorted({storey_of(o['y'], d.storey_h) for o in hosts})
    return [], (
        f'{_shown(which)} matches {len(hosts)} {kinds} record(s) on storeys {sts[:16]}, none of them '
        f'named for {"/".join(sorted(want))} — their names are {names}, so `sides` cannot tell them '
        f'apart; pass the ids of the ones you mean instead'
    )


def _centres(d: Drawing, recs: list):
    """grp -> plan centre, frozen BEFORE anything is added (else the elements we
    hang on the first wall would drag the centroid the next wall is judged
    against). Returns a lookup fn; a wall with no group falls back to the centre
    of the selection itself."""
    fam: dict = {}
    for o in d.objs:
        fam.setdefault(o.get('grp') or '', []).append(o)
    sel = [o for o in recs if o is not None] or list(d.objs)
    sx = sum(o['x'] for o in sel) / len(sel), sum(o['z'] for o in sel) / len(sel)
    cache = {
        g: (sum(o['x'] for o in v) / len(v), sum(o['z'] for o in v) / len(v))
        for g, v in fam.items()
        if g and len(v) > 1
    }

    def centre(w):
        return cache.get(w.get('grp') or '', sx)

    return centre


def _outward(w: dict, cx: float, cz: float) -> tuple:
    """(ry, nx, nz): ry whose local -Z points AWAY from (cx, cz), and that unit
    vector in world x/z. Local -Z in world is (-sin ry, -cos ry)."""
    ry = _num(w.get('ry'), 0.0)
    nx, nz = -math.sin(ry), -math.cos(ry)
    if (w['x'] - cx) * nx + (w['z'] - cz) * nz < 0:
        ry += math.pi
        nx, nz = -nx, -nz
    return ry, nx, nz


def _face(w: dict, u: float, nx: float, nz: float) -> tuple:
    """A point u along the wall, pushed onto its OUTER face."""
    x, z = _wall_world(w, u)
    off = _num(w['p'].get('t'), 0.24) / 2
    return x + nx * off, z + nz * off


def _room(d: Drawing, need: int) -> str:
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} more objects and the drawing may hold {MAX_OBJECTS} in total'
    return ''


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_balconies(
    d: Drawing,
    a,
    walls='new',
    every_n_storeys=1,
    storey_offset=1,
    per_wall=1,
    width=2.4,
    depth=1.2,
    sides=None,
    rail_h=1.0,
    material='',
    name='',
):
    recs, why = _pick(d, walls, sides)
    if not recs:
        return (
            f'refused: no walls to hang balconies on — {why} — call get_state(detail="objects") for the '
            'ids of the walls (or curtain walls) you mean and pass them as walls=["o12", "o17", …], or '
            'walls="all" with sides=["south"]'
        )
    ww, dd = _num(width, 2.4), _num(depth, 1.2)
    if ww < 0.6 or ww > 20 or dd < 0.3 or dd > 6:
        return 'refused: a balcony is 0.6-20 m wide and 0.3-6 m deep'
    n = max(1, int(_num(every_n_storeys, 1)))
    off = int(_num(storey_offset, 1))
    cnt0 = max(1, int(_num(per_wall, 1)))
    mg = 0.4
    mat = _mat(material, 'mat_concrete')
    err = _room(d, len(recs) * cnt0)
    if err:
        return err
    centre = _centres(d, recs)
    # 2026-09-10: walls named ONE BY ONE are the caller's own list — the storey
    # rule is how you pick storeys out of a GROUP, not a filter to re-apply to a
    # hand-picked selection.
    by_id = _by_id(d, walls)
    made, skip_storey, skip_fit, on = 0, 0, 0, 0
    storeys_seen, longest = set(), 0.0
    for w in recs:
        st = storey_of(w['y'], d.storey_h)
        storeys_seen.add(st)
        longest = max(longest, _num(w['p'].get('len'), 4))
        if not by_id and (st < off or (st - off) % n):
            skip_storey += 1
            continue
        L = _num(w['p'].get('len'), 4)
        usable = L - 2 * mg
        cnt = cnt0
        while cnt > 0 and cnt * (ww + 0.2) > usable:
            cnt -= 1
        if cnt <= 0:
            skip_fit += 1
            continue
        ry, nx, nz = _outward(w, *centre(w))
        for i in range(cnt):
            u = mg + usable * (i + 0.5) / cnt
            x, z = _face(w, u, nx, nz)
            d.new(
                'balcony',
                {'w': round(ww, 3), 'd': round(dd, 3), 't': 0.18, 'rail_h': _num(rail_h, 1.0), 'post': 0.04},
                x,
                z,
                w['y'],
                ry,
                mat,
                name=name or f'balcony on {w["name"]}',
                grp=w['grp'] or name,
            )
            made += 1
        on += 1
    if not made:
        # THE RULE (2026-09-10): a tool that made nothing REFUSES, with the count
        # behind every skip and the call that works. 'added 0 balconies … skipped
        # 11 walls' reads as done and the model moved on (job 71ac02b0).
        bits, fix = [], ''
        if skip_storey:
            bits.append(
                f'{skip_storey} of {len(recs)} walls are on storeys '
                f'{sorted(storeys_seen)[:12]}, which storey_offset={off} + every_n_storeys={n} skips'
            )
            fix = (
                f'pass those walls by id (walls=["o12", …] ignores the storey rule) or call '
                f'add_balconies(walls={_shown(walls)}, storey_offset={min(storeys_seen)}, every_n_storeys=1'
                + (f', sides={list(sides)}' if sides else '')
                + ')'
            )
        if skip_fit:
            bits.append(
                f'{skip_fit} of {len(recs)} walls are too short for {cnt0} x {ww:g} m '
                f'(the longest is {longest:g} m, so width must be at most '
                f'{max(0.6, (longest - 2 * mg) / cnt0 - 0.2):.2f} m)'
            )
            fix = fix or (
                f'call add_balconies(walls={_shown(walls)}, '
                f'width={max(0.6, (longest - 2 * mg) / cnt0 - 0.2):.2f}, depth={dd:g})'
            )
        return 'refused: added 0 balconies — ' + '; '.join(bits) + ' — ' + fix
    return (
        f'added {made} balconies ({ww:g} x {dd:g} m, rail {_num(rail_h, 1.0):g} m) on {on} walls'
        + (f', skipped {skip_storey} walls on other storeys' if skip_storey else '')
        + (f', skipped {skip_fit} walls too short' if skip_fit else '')
    )


def t_add_parapet(d: Drawing, a, group='new', height=1.0, thickness=0.2, material='', cap=False):
    recs, why = _pick(d, group)
    if not recs:
        return f'refused: no walls to stand a parapet on — {why} — pass the building group name or wall ids'
    h = _num(height, 1.0)
    t = _num(thickness, 0.2)
    if h < 0.2 or h > 3:
        return 'refused: a parapet is 0.2-3 m high'
    top = max(storey_of(w['y'], d.storey_h) for w in recs)
    tops = [w for w in recs if storey_of(w['y'], d.storey_h) == top]
    err = _room(d, len(tops) * (2 if cap else 1))
    if err:
        return err
    mat = _mat(material, 'mat_brick')
    ids = []
    for w in tops:
        L = _num(w['p'].get('len'), 4)
        y = w['y'] + _num(w['p'].get('h'), d.storey_h)
        # 2026-09-08: the top of the wall is the roof record's BASE, and a flat
        # roof is a solid — its walkable deck is base + thickness. A parapet
        # left at the wall top therefore stood 0.3 m INSIDE the roof it guards
        # (design_check reported all four of them as buried on every building).
        y = deck_top(d, w['x'], w['z'], y)[0]
        o = d.new('wall', {'len': L, 'h': h, 't': t}, w['x'], w['z'], y, w['ry'], mat, name='parapet', grp=w['grp'])
        ids.append(o['id'])
        if cap:
            d.new(
                'parapet_cap',
                {'len': L, 'w': round(t + 0.1, 3), 't': 0.06},
                w['x'],
                w['z'],
                y + h,
                w['ry'],
                'mat_stone',
                name='parapet cap',
                grp=w['grp'],
            )
    y0 = d.find(ids[0])['y']
    return (
        f'parapet {ids[0]}..{ids[-1]}: {len(tops)} walls {h:g} m high, {t:g} m thick, on top of '
        f'storey {top} at y {y0:g} m' + (f', with {len(tops)} coping stones' if cap else '')
    )


def t_add_canopy(
    d: Drawing,
    a,
    wall_id=None,
    at='middle',
    width=3.0,
    depth=1.5,
    kind='canopy',
    angle=20,
    material='',
    height=None,
    columns=0,
    column_material='',
    group='',
    side='',
    storey=0,
):
    # 2026-09-10: by id, or by group + side + storey; a curtain wall is a fine host
    # for a canopy (same length, position and rotation as the wall it replaced)
    w, err, how = host_wall(d, wall_id, group, side, storey, ('wall', 'partition', 'curtain_wall'))
    if err:
        return err
    wall_id = w['id']
    if kind not in ('canopy', 'awning'):
        return 'refused: kind must be canopy (a flat plate) or awning (a sloped one)'
    ww, dd = _num(width, 3.0), _num(depth, 1.5)
    if ww < 0.5 or ww > 30 or dd < 0.3 or dd > 8:
        return 'refused: a canopy is 0.5-30 m wide and 0.3-8 m deep'
    ncol = max(0, min(12, int(_num(columns, 0))))
    err = _room(d, (2 if kind == 'canopy' else 1) + ncol)
    if err:
        return err
    L = _num(w['p'].get('len'), 4)
    H = _num(w['p'].get('h'), d.storey_h)
    u = L / 2 if str(at) == 'middle' else max(0.3, min(L - 0.3, _num(at, L / 2)))
    ry, nx, nz = _outward(w, *_centres(d, [w])(w))
    x, z = _face(w, u, nx, nz)
    # soffit height: 2.4 m is a shop awning; a porte-cochere wants 3.5-4.5 m
    # (the 'height' argument, metres above the wall's base, at most the wall top)
    soffit = _num(height, 0.0) if height is not None else (H - 0.3 if kind == 'awning' else 2.4)
    if soffit < 2.1 or soffit > 12:
        return 'refused: a canopy soffit is 2.1-12 m above the floor'
    y = w['y'] + soffit
    p = (
        {'w': round(ww, 3), 'd': round(dd, 3), 'angle': _num(angle, 20)}
        if kind == 'awning'
        else {'w': round(ww, 3), 'd': round(dd, 3), 't': 0.12, 'h_drop': 0}
    )
    o = d.new(
        kind,
        p,
        x,
        z,
        y,
        ry,
        _mat(material, 'mat_paint_dark' if kind == 'awning' else 'mat_concrete'),
        name=kind,
        grp=w['grp'],
    )
    from zyg_workflows.arch_assistant import place_height

    cols = []
    if ncol and kind == 'canopy':
        # columns carry the plate: under its OUTER edge (0.35 m in), evenly along
        # the width, each exactly as tall as the soffit so nothing pierces it
        along = (math.cos(ry), -math.sin(ry))  # unit vector along the wall in plan (x, z)
        out = (nx, nz)
        r = 0.18 if soffit < 5 else 0.25
        for i in range(ncol):
            f = (i + 0.5) / ncol - 0.5 if ncol > 1 else 0.0
            cx = x + along[0] * f * (ww - 0.7) + out[0] * (dd - 0.35)
            cz = z + along[1] * f * (ww - 0.7) + out[1] * (dd - 0.35)
            gy = place_height(d, cx, cz, None)
            c = d.new(
                'column_round',
                {'r': r, 'h': round(y - gy, 3)},
                cx,
                cz,
                gy,
                0.0,
                _mat(column_material, _mat(material, 'mat_concrete')),
                name=f'canopy column {i + 1}',
                grp=w['grp'],
            )
            cols.append(c['id'])
    col_h = y - place_height(d, x, z, None) if cols else 0.0
    # 2026-09-10 (job 71ac02b0): the plate's inner edge ran straight into the
    # facade with no joint. A flat canopy is carried at the wall by an EDGE BEAM
    # spanning its width, sitting on the wall's outer face at soffit level, so
    # the junction reads as a junction. 'beam' is a kind the tab (inspection.html
    # case 'beam') and the Blender builder both draw: p = len x w (plan) x h,
    # length along local X, drawn UP from the record's y.
    beam = None
    if kind == 'canopy':
        bd, bh = 0.4, 0.35
        beam = d.new(
            'beam',
            {'len': round(ww, 3), 'w': bd, 'h': bh},
            x + nx * bd / 2,
            z + nz * bd / 2,
            y,
            ry,
            _mat(material, 'mat_concrete'),
            name='canopy beam',
            grp=w['grp'],
        )
    return (
        f'{kind} {o["id"]} on wall {wall_id}{how} at {u:.2f} m along it, {ww:g} x {dd:g} m, soffit at y {y:g} m'
        + (
            f', carried by {ncol} round columns {cols[0]}..{cols[-1]} under its outer edge, each {col_h:.2f} m tall'
            if cols
            else ''
        )
        + (f', joined to wall {wall_id} with a {bh:g} m edge beam {beam["id"]} along the facade' if beam else '')
    )


def t_add_louvres(d: Drawing, a, walls='new', spacing=0.4, depth=0.3, thickness=0.03, material='', sides=None):
    recs, why = _pick(d, walls, sides)
    if not recs:
        return f'refused: no walls to cover in louvres — {why} — pass "all", a group name or wall ids'
    sp = _num(spacing, 0.4)
    dp = _num(depth, 0.3)
    if sp < 0.05 or sp > 5:
        return 'refused: fin spacing must be between 0.05 and 5 m'
    err = _room(d, len(recs))
    if err:
        return err
    centre = _centres(d, recs)
    mat = _mat(material, 'mat_timber')
    ids = []
    for w in recs:
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        ry, nx, nz = _outward(w, *centre(w))
        x, z = _face(w, L / 2, nx, nz)
        o = d.new(
            'louvre_fins',
            {'w': round(L, 3), 'h': round(H, 3), 'fin': dp, 'spacing': sp, 't': _num(thickness, 0.03)},
            x,
            z,
            w['y'],
            ry,
            mat,
            name=f'louvres on {w["name"]}',
            grp=w['grp'],
        )
        ids.append(o['id'])
    if not ids:
        return (
            f'refused: added 0 louvre panels — none of the {len(recs)} matching walls could take one '
            f'— pass the wall ids you mean'
        )
    return f'added {len(ids)} louvre panels {ids[0]}..{ids[-1]}, fins every {sp:g} m, {dp:g} m deep'


def t_add_facade_bands(
    d: Drawing, a, group='new', every_n_storeys=1, kind='cornice', depth=0.25, material='', sides=None
):
    if kind not in ('cornice', 'string_course'):
        return 'refused: kind must be cornice (a deep band) or string_course (a thin one)'
    recs, why = _pick(d, group, sides)
    if not recs:
        return f'refused: no walls to run a band along — {why} — pass a group name, "all", or wall ids'
    n = max(1, int(_num(every_n_storeys, 1)))
    dp = _num(depth, 0.25 if kind == 'cornice' else 0.08)
    if dp < 0.02 or dp > 2:
        return 'refused: a band projects between 0.02 and 2 m'
    err = _room(d, len(recs))
    if err:
        return err
    mat = _mat(material, 'mat_stone')
    h = 0.3 if kind == 'cornice' else 0.12
    centre = _centres(d, recs)
    by_id = _by_id(d, group)
    made, skipped = 0, 0
    storeys_seen = set()
    for w in recs:
        st = storey_of(w['y'], d.storey_h)
        storeys_seen.add(st)
        if not by_id and st % n:
            skipped += 1
            continue
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        ry, nx, nz = _outward(w, *centre(w))
        x, z = _face(w, L / 2, nx, nz)
        d.new(
            kind, {'len': round(L, 3), 'h': h, 'd': dp}, x, z, w['y'] + H, ry, mat, name=f'{kind} st{st}', grp=w['grp']
        )
        made += 1
    if not made:
        return (
            f'refused: added 0 {kind} bands — all {skipped} matching walls are on storeys '
            f'{sorted(storeys_seen)[:12]}, and every_n_storeys={n} only bands storeys divisible by {n} '
            f'— call add_facade_bands(group={_shown(group)}, kind="{kind}", every_n_storeys=1, '
            f'depth={dp:g}) or pass the walls by id'
        )
    return f'added {made} {kind} bands, {dp:g} m deep, at the top of every {n} storey(s)' + (
        f' (skipped {skipped} walls on other storeys)' if skipped else ''
    )


def t_add_pilasters(d: Drawing, a, walls='new', spacing=3.0, width=0.4, depth=0.12, material='', sides=None):
    recs, why = _pick(d, walls, sides)
    if not recs:
        return f'refused: no walls to set pilasters on — {why} — pass "all", a group name or wall ids'
    sp = _num(spacing, 3.0)
    if sp < 0.5 or sp > 30:
        return 'refused: pilaster spacing must be between 0.5 and 30 m'
    ww, dp = _num(width, 0.4), _num(depth, 0.12)
    mat = _mat(material, 'mat_plaster')
    plan = []
    for w in recs:
        L = _num(w['p'].get('len'), 4)
        plan.append((w, max(2, int(L // sp) + 1)))
    err = _room(d, sum(c for _, c in plan))
    if err:
        return err
    centre = _centres(d, recs)
    made = 0
    for w, cnt in plan:
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        ry, nx, nz = _outward(w, *centre(w))
        mg = ww / 2 + 0.05
        for i in range(cnt):
            u = mg + (L - 2 * mg) * i / (cnt - 1)
            x, z = _face(w, u, nx, nz)
            d.new(
                'pilaster',
                {'h': round(H, 3), 'w': ww, 'd': dp},
                x,
                z,
                w['y'],
                ry,
                mat,
                name=f'pilaster on {w["name"]}',
                grp=w['grp'],
            )
            made += 1
    if not made:
        return (
            f'refused: added 0 pilasters — none of the {len(recs)} matching walls is long enough for a '
            f'{ww:g} m pier every {sp:g} m — try a smaller spacing or width'
        )
    return f'added {made} pilasters on {len(recs)} walls, one every {sp:g} m, {ww:g} m wide'


_WALLS_ARG = {
    'oneOf': [{'type': 'string'}, {'type': 'array', 'items': {'type': 'string'}}],
    'description': '"new", "all", a group name, or a list of wall ids',
}

TOOLS = [
    (
        {
            'name': 'add_balconies',
            'description': 'Hang balconies (a projecting slab with a railing on three sides) on walls, spread along each wall the way windows are. storey_offset 1 skips the ground floor; every_n_storeys 2 puts them on every second floor — but a LIST OF IDS turns that rule off, because then you chose the storeys yourself. A curtain_wall counts as a wall, so a glazed storey can carry balconies. They always project away from the building.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': _WALLS_ARG,
                    'every_n_storeys': {'type': 'integer'},
                    'storey_offset': {'type': 'integer'},
                    'per_wall': {'type': 'integer'},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'sides': {'type': 'array', 'items': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']}},
                    'rail_h': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_add_balconies,
    ),
    (
        {
            'name': 'add_parapet',
            'description': 'A low wall round the top storey of a group, sitting on top of its walls — what a flat roof needs before it reads as a building. cap=true adds a coping stone on top.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': _WALLS_ARG,
                    'height': {'type': 'number'},
                    'thickness': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'cap': {'type': 'boolean'},
                },
                'required': ['group'],
            },
        },
        t_add_parapet,
    ),
    (
        {
            'name': 'add_canopy',
            'description': 'One canopy (a flat plate) or awning (a sloped one) on a wall — by wall_id, or by group + side + storey (add_canopy(group="tower", side="south", storey=0, columns=4, height=4) is a porte-cochere on the entrance; a curtain wall is a fine host) — over an entrance or a shopfront. at is "middle" or metres along the wall from its -X end. height = the soffit above the floor (default 2.4 for a shopfront; a porte-cochere on a tower wants 3.5-4.5). columns=N puts N round columns under the plate\'s outer edge, exactly as tall as the soffit — use this for a porte-cochere instead of a separate add_colonnade, which pierces the plate.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'wall_id': {'type': 'string'},
                    'group': {
                        'type': 'string',
                        'description': 'the building group — with side + storey instead of wall_id',
                    },
                    'side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'storey': {'type': 'integer', 'description': 'with group + side; default 0'},
                    'at': {'type': 'string'},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'kind': {'type': 'string', 'enum': ['canopy', 'awning']},
                    'angle': {'type': 'number'},
                    'height': {'type': 'number'},
                    'columns': {'type': 'integer'},
                    'column_material': {'type': 'string'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': [],
            },
        },
        t_add_canopy,
    ),
    (
        {
            'name': 'add_louvres',
            'description': 'Cover whole walls in vertical sun fins — one louvre panel per wall, the full length and height of it, a fin every `spacing` metres.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': _WALLS_ARG,
                    'spacing': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'thickness': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'sides': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': [],
            },
        },
        t_add_louvres,
    ),
    (
        {
            'name': 'add_facade_bands',
            'description': 'Run a horizontal band round every wall of a group at the top of each matching storey: kind "cornice" for a deep eaves-like band, "string_course" for a thin floor line.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': _WALLS_ARG,
                    'every_n_storeys': {'type': 'integer'},
                    'kind': {'type': 'string', 'enum': ['cornice', 'string_course']},
                    'depth': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'sides': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': ['group'],
            },
        },
        t_add_facade_bands,
    ),
    (
        {
            'name': 'add_pilasters',
            'description': 'Shallow piers standing proud of a wall, one every `spacing` metres along it, full storey height. Use for a classical or a warehouse rhythm.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': _WALLS_ARG,
                    'spacing': {'type': 'number'},
                    'width': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'sides': {'type': 'array', 'items': {'type': 'string'}},
                },
                'required': [],
            },
        },
        t_add_pilasters,
    ),
]

EXAMPLES = [
    {
        'ask': 'a four-storey block on C4 to H12 with balconies on the south side from the first floor up',
        'calls': [
            {'tool': 'draw_box', 'args': {'cell_from': 'C4', 'cell_to': 'H12', 'storeys': 4, 'name': 'block'}},
            {
                'tool': 'add_balconies',
                'args': {'walls': 'block', 'sides': ['south'], 'storey_offset': 1, 'width': 2.4, 'depth': 1.4},
            },
        ],
    },
    {
        'ask': 'put a parapet with a stone coping on the block and a cornice at every floor',
        'calls': [
            {'tool': 'add_parapet', 'args': {'group': 'block', 'height': 1.0, 'thickness': 0.2, 'cap': True}},
            {'tool': 'add_facade_bands', 'args': {'group': 'block', 'kind': 'cornice', 'depth': 0.25}},
        ],
    },
    {
        'ask': 'a 4 m glass canopy over the entrance in wall o3',
        'calls': [
            {
                'tool': 'add_canopy',
                'args': {'wall_id': 'o3', 'width': 4, 'depth': 1.8, 'kind': 'canopy', 'material': 'mat_glass'},
            }
        ],
    },
    {
        'ask': 'a shop awning over o7, 3 m wide, sloping 25 degrees',
        'calls': [
            {'tool': 'add_canopy', 'args': {'wall_id': 'o7', 'kind': 'awning', 'width': 3, 'depth': 1.2, 'angle': 25}}
        ],
    },
    {
        'ask': 'timber sun louvres on the west wall of the office, fins every 30 cm',
        'calls': [
            {
                'tool': 'add_louvres',
                'args': {'walls': 'office', 'sides': ['west'], 'spacing': 0.3, 'depth': 0.35, 'material': 'mat_timber'},
            }
        ],
    },
    {
        'ask': 'pilasters every 3 m on the warehouse walls',
        'calls': [{'tool': 'add_pilasters', 'args': {'walls': 'warehouse', 'spacing': 3, 'width': 0.5}}],
    },
]
