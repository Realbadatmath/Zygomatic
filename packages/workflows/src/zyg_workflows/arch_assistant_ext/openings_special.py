# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""openings_special — the openings the built-in window/door pair cannot say,
plus curtain walling.

Tools: add_special_openings (arched, round, bay, strip windows and garage,
sliding and french doors, placed on walls exactly the way add_windows places
plain windows), add_curtain_wall (REPLACES whole wall faces with a glazed
mullion/transom grid), add_garage (one garage door in one named wall).

The studio's hole model is rectangular: whatever the frame looks like, the
opening cut into its host wall is p.w x p.h at p.sill. That is why
window_round carries w = h = 2r next to r.
"""

from __future__ import annotations

from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    _wall_world,
    cell_of,
    is_opening,
    openings_in_wall,
    storey_of,
    world_to_local,
)

KINDS = {
    'window_arch': {'w': 1.2, 'h': 1.4, 'sill': 0.9, 'arch': 0.6},
    'window_round': {'r': 0.6, 'sill': 1.2, 'w': 1.2, 'h': 1.2},
    'window_bay': {'w': 2.4, 'h': 1.4, 'sill': 0.9, 'depth': 0.8},
    'window_strip': {'w': 8, 'h': 1.0, 'sill': 1.1},
    'door_garage': {'w': 2.5, 'h': 2.2, 'panels': 4},
    'door_sliding': {'w': 2.4, 'h': 2.1},
    'door_french': {'w': 1.6, 'h': 2.1},
    'curtain_wall': {'len': 6, 'h': 2.7, 'mullion': 1.5, 'transom': 1.2, 't': 0.15},
}
OPENINGS = ['window_arch', 'window_round', 'window_bay', 'window_strip', 'door_garage', 'door_sliding', 'door_french']

MARGIN = 0.6  # the same end margin add_windows keeps

PROMPT = (
    'Special openings and glazed facades: add_special_openings(walls, kind, per_wall, every_n_storeys, '
    'width, height, sill) places window_arch (round-topped, height is to the springing), window_round '
    '(a bullseye; width is its diameter), window_bay (a three-sided box projecting out of the wall), '
    'window_strip (a long ribbon light), door_garage, door_sliding or door_french on the matching walls, '
    'spread evenly with a 0.6 m end margin like add_windows, skipping walls too short. The hole '
    'cut in the wall is always the plain RECTANGLE width x height at the sill — the arch and the circle '
    'are frame drawn in front of it. add_curtain_wall(walls, mullion, transom, storeys) REPLACES whole '
    'walls with a glazed curtain wall and deletes the openings that were in them, so use it for '
    'shopfronts and office facades, not for one window. add_garage(wall_id, at, width) puts a single '
    'garage door in one named wall.'
)


def _mat(m, default='mat_plaster'):
    return m if m in MATERIALS else default


def _shown(which) -> str:
    return (
        ('[' + ', '.join(str(w) for w in list(which)[:6]) + ']')
        if isinstance(which, (list, tuple, set))
        else f'"{which}"'
    )


def _by_id(d: Drawing, which) -> bool:
    """True when `which` names records ONE BY ONE — then the caller picked those
    walls and the storey rule must not filter them again (2026-09-10)."""
    if isinstance(which, (list, tuple, set)):
        return True
    w = str(which or '').strip()
    return bool(w) and w not in ('new', 'all', 'walls') and d.find(w) is not None


def _hosts(d: Drawing, which):
    """(walls, why): the wall/partition records `which` names — the only kinds
    the studio can cut a hole in — and, when there are none, what was there
    instead. A curtain_wall is NOT a host: it is glazing, it has no hole model;
    that is why add_curtain_wall keeps a wall that holds a door."""
    sel = [o for o in d.select(which) if o is not None]
    recs = [o for o in sel if o['kind'] in ('wall', 'partition')]
    if recs:
        return recs, ''
    if not sel:
        return [], f'nothing in the drawing matches {_shown(which)}'
    kinds = ', '.join(sorted({o['kind'] for o in sel})[:6])
    glazed = sum(1 for o in sel if o['kind'] == 'curtain_wall')
    return [], (
        f'{_shown(which)} matches {len(sel)} record(s) but none is a wall — they are {kinds}'
        + (
            f'; a curtain wall is glazing and cannot hold an opening — the glazing grid IS the '
            f'window, or delete those {glazed} curtain walls and draw walls there'
            if glazed
            else ''
        )
    )


def _params(kind, ww, hh, ss):
    """The record's p for one opening, sized so the wall hole matches the frame."""
    if kind == 'window_round':
        r = round(max(0.1, ww / 2), 3)
        return {'r': r, 'sill': round(ss, 3), 'w': round(2 * r, 3), 'h': round(2 * r, 3)}
    p = dict(KINDS[kind])
    p['w'] = round(ww, 3)
    p['h'] = round(hh, 3)
    if 'sill' in p:
        p['sill'] = round(ss, 3)
    if kind == 'window_arch':
        p['arch'] = round(ww / 2, 3)
    return p


def t_add_special_openings(
    d: Drawing,
    a,
    walls='new',
    kind='window_arch',
    every_n_storeys=1,
    storey_offset=0,
    per_wall=1,
    width=None,
    height=None,
    sill=None,
    material='mat_plaster',
):
    if kind not in OPENINGS:
        return 'refused: kind must be one of ' + ', '.join(OPENINGS)
    recs, why = _hosts(d, walls)
    if not recs:
        return f'refused: no walls to cut a {kind} into — {why} — pass "all", a group name, or wall ids'
    n = max(1, int(_num(every_n_storeys, 1)))
    off = int(_num(storey_offset, 0))
    base = KINDS[kind]
    ww = _num(width, base['w'])
    hh = _num(height, base['h'])
    ss = _num(sill, base.get('sill', 0.0))
    if ww < 0.2 or hh < 0.2:
        return 'refused: width and height must be at least 0.2 m'
    rise = ww / 2 if kind == 'window_arch' else 0.0
    mat = _mat(material)
    by_id = _by_id(d, walls)
    made, skipped_storey, skipped_fit = 0, 0, 0
    storeys_seen, longest, heights = set(), 0.0, set()
    for w in recs:
        st = storey_of(w['y'], d.storey_h)
        storeys_seen.add(st)
        longest = max(longest, _num(w['p'].get('len'), 4))
        if not by_id and (st < off or (st - off) % n):
            skipped_storey += 1
            continue
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        usable = L - 2 * MARGIN
        cnt = max(1, int(_num(per_wall, 1)))
        while cnt > 0 and cnt * (ww + 0.14) > usable:
            cnt -= 1
        if cnt <= 0:
            skipped_fit += 1
            continue
        if len(d.objs) + cnt > MAX_OBJECTS:
            return f'stopped at {made} {kind}s: the drawing hit its {MAX_OBJECTS}-object ceiling'
        h_here = min(hh, max(0.3, H - ss - rise - 0.15))
        heights.add(round(h_here, 3))
        for i in range(cnt):
            u = MARGIN + usable * (i + 0.5) / cnt
            x, z = _wall_world(w, u)
            d.new(kind, _params(kind, ww, h_here, ss), x, z, w['y'], w['ry'], mat, name=f'{kind} st{st}', grp=w['grp'])
            made += 1
    if not made:
        # 2026-09-10: nothing made = a refusal with the counts and the call that
        # works, never 'added 0 … (skipped 11 walls)' — a model reads that as done.
        bits, fix = [], ''
        if skipped_storey:
            bits.append(
                f'{skipped_storey} of {len(recs)} walls are on storeys {sorted(storeys_seen)[:12]}, '
                f'which storey_offset={off} + every_n_storeys={n} skips'
            )
            fix = (
                f'call add_special_openings(walls={_shown(walls)}, kind="{kind}", '
                f'storey_offset={min(storeys_seen)}, every_n_storeys=1) or pass the walls by id '
                f'(that ignores the storey rule)'
            )
        if skipped_fit:
            fits = max(0.2, longest - 2 * MARGIN - 0.14)
            bits.append(
                f'{skipped_fit} of {len(recs)} walls are too short for {int(_num(per_wall, 1))} x '
                f'{ww:g} m plus the {MARGIN} m end margins (the longest is {longest:g} m)'
            )
            fix = fix or (
                f'call add_special_openings(walls={_shown(walls)}, kind="{kind}", width={fits:.2f}, per_wall=1)'
            )
        return f'refused: added 0 {kind}(s) — ' + '; '.join(bits) + ' — ' + fix
    tall = f'{min(heights):g}' if len(heights) == 1 else f'{min(heights):g}-{max(heights):g}'
    return (
        f'added {made} {kind}(s) ({ww:g} x {tall} m at sill {ss:g} m) on '
        f'{len(recs) - skipped_storey - skipped_fit} walls'
        + (f' (skipped {skipped_storey} walls on other storeys)' if skipped_storey else '')
        + (f' (skipped {skipped_fit} walls too short)' if skipped_fit else '')
    )


def _holds_door(d: Drawing, w: dict) -> bool:
    return any(
        str(o.get('kind') or '').startswith('door') or o.get('kind') == 'double_door' for o in openings_in_wall(d, w)
    )


def _covers(w: dict, x: float, z: float, tol: float = 0.6) -> bool:
    """Does wall-like record w's PLAN SEGMENT pass within `tol` of (x, z)? Two
    records that answer yes for each other's centre stand in the same face."""
    lx, lz = world_to_local(w, x, z)
    return abs(lz) <= tol and abs(lx) <= _num(w['p'].get('len'), 4) / 2 + 0.05


# The tab draws mullions and transoms for the kind `curtain_wall` only
# (arch_ext/openings_special.js AR_EXT.geom.curtain_wall); its `wall` builder
# (inspection.html case 'wall') reads len, h, t and p.holes and nothing else. So
# a door wall kept as glass carries NO grid, and the reply has to say so rather
# than record p.mullion/p.transom the viewer would silently drop.
_NO_GRID = (
    'plain glass wall(s) without a mullion grid — the studio draws mullions on curtain_wall '
    'records only, and glazing cannot hold a door'
)


def t_add_curtain_wall(d: Drawing, a, walls='new', mullion=1.5, transom=1.2, storeys=None, name='', keep_doors=True):
    recs, why = _hosts(d, walls)
    if storeys is not None and recs:
        want = {int(_num(s, -999)) for s in (storeys if isinstance(storeys, list) else [storeys])}
        have = sorted({storey_of(o['y'], d.storey_h) for o in recs})
        kept = [o for o in recs if storey_of(o['y'], d.storey_h) in want]
        if not kept:
            return (
                f'refused: none of the {len(recs)} walls in {_shown(walls)} is on a storey in '
                f'{sorted(want)} — they are on storeys {have[:16]} — call add_curtain_wall'
                f'(walls={_shown(walls)}, storeys={have[:8]})'
            )
        recs = kept
    if not recs:
        return f'refused: nothing to glaze — {why} — pass "all", a group name, or wall ids'
    # 2026-09-10: the studio cuts holes in WALLS only, so glazing the entrance
    # wall deleted the door and the model then spent three calls finding a new
    # host. A wall that holds a door is kept as a wall and turned glass instead.
    kept = []
    if keep_doors not in (False, 'false', 0):
        kept = [o for o in recs if _holds_door(d, o)]
        if kept:
            for o in kept:
                o['mat'] = 'mat_glass'
            # 2026-09-10 (job 71ac02b0's entrance read as a tan panel BEHIND the
            # glass): the door wall is kept AND nothing may be glazed over it.
            # Anything left in recs standing in the same face at the same storey
            # would put a second pane in front of the door, so it goes too.
            covered = [
                o
                for o in recs
                if o not in kept
                and any(
                    storey_of(o['y'], d.storey_h) == storey_of(k['y'], d.storey_h) and _covers(o, k['x'], k['z'])
                    for k in kept
                )
            ]
            recs = [o for o in recs if o not in kept and o not in covered]
        if not recs:
            return (
                f'kept {len(kept)} wall(s) that hold a door as '
                + _NO_GRID
                + f' ({", ".join(o["id"] for o in kept)}); nothing else matched'
            )
    mu, tr = _num(mullion, 1.5), _num(transom, 1.2)
    if mu < 0.3 or tr < 0.3:
        return 'refused: mullion and transom spacing must be at least 0.3 m'
    wall_ids = {w['id'] for w in recs}
    doomed = [o for o in d.objs if is_opening(o['kind']) and str(o['p'].get('host') or '') in wall_ids]
    ids = []
    for w in recs:
        L = _num(w['p'].get('len'), 4)
        H = _num(w['p'].get('h'), d.storey_h)
        st = storey_of(w['y'], d.storey_h)
        cp = {'len': round(L, 4), 'h': round(H, 4), 'mullion': round(mu, 3), 'transom': round(tr, 3), 't': 0.15}
        if w['p'].get('base') is not None:  # a head house on a deck keeps its base level (2026-09-16)
            cp['base'] = w['p']['base']
        o = d.new(
            'curtain_wall',
            cp,
            w['x'],
            w['z'],
            w['y'],
            w['ry'],
            'mat_glass',
            name=name or f'curtain wall st{st}',
            grp=w['grp'] or name,
        )
        ids.append(o['id'])
    d.remove(recs + doomed)
    d.selected = list(ids)
    return (
        f'replaced {len(recs)} wall(s) with curtain walls {ids[0]}..{ids[-1]} '
        f'(mullions every {mu:g} m, transoms every {tr:g} m)'
        + (f'; deleted {len(doomed)} opening(s) that were in them' if doomed else '')
        + (
            f'; kept {len(kept)} wall(s) that hold a door as '
            + _NO_GRID
            + f', now mat_glass: {", ".join(o["id"] for o in kept)}'
            if kept
            else ''
        )
    )


def t_add_garage(d: Drawing, a, wall_id, at='middle', width=2.5, height=2.2, panels=4, material='mat_steel'):
    w = d.find(str(wall_id))
    if not w:
        return f'refused: there is no object {wall_id} — get a wall id from draw_box or list_storeys'
    if w['kind'] not in ('wall', 'partition'):
        return (
            f'refused: {wall_id} is a {w["kind"]}, not a wall — a garage door is a hole, and the studio '
            'cuts holes in walls only'
        )
    L = _num(w['p'].get('len'), 4)
    ww = _num(width, 2.5)
    if ww < 1.5 or ww > 8:
        return 'refused: a garage door is between 1.5 and 8 m wide'
    if ww + 0.3 > L:
        return f'refused: wall {wall_id} is only {L:.2f} m long — a {ww:g} m garage door does not fit'
    lo, hi = ww / 2 + 0.15, L - ww / 2 - 0.15
    u = L / 2 if str(at) == 'middle' else max(lo, min(hi, _num(at, L / 2)))
    hh = min(_num(height, 2.2), max(0.5, _num(w['p'].get('h'), d.storey_h) - 0.15))
    p = {'w': round(ww, 3), 'h': round(hh, 3), 'panels': max(1, min(12, int(_num(panels, 4))))}
    x, z = _wall_world(w, u)
    o = d.new('door_garage', p, x, z, w['y'], w['ry'], _mat(material, 'mat_steel'), name='garage door', grp=w['grp'])
    return (
        f'garage door {o["id"]} ({p["w"]:g} x {p["h"]:g} m, {p["panels"]} panels) in wall {wall_id} '
        f'at {u:.2f} m along it, cell {cell_of(x, z)}'
    )


TOOLS = [
    (
        {
            'name': 'add_special_openings',
            'description': (
                'Place arched, round, bay or strip windows, or garage, sliding or french doors, on the '
                'matching walls — spread evenly with a 0.6 m end margin, one per wall by default, walls '
                'that are too short are skipped. width is the diameter for window_round. The hole cut in '
                'the wall is always the plain rectangle width x height at the sill.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': {'description': '"new", "all", a group name, or a list of wall ids'},
                    'kind': {'type': 'string', 'enum': OPENINGS},
                    'every_n_storeys': {'type': 'integer'},
                    'storey_offset': {'type': 'integer'},
                    'per_wall': {'type': 'integer'},
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'sill': {'type': 'number'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['kind'],
            },
        },
        t_add_special_openings,
    ),
    (
        {
            'name': 'add_curtain_wall',
            'description': (
                'Replace whole wall faces with a glazed curtain wall: the wall is deleted and one curtain_wall of '
                'the same length, height, position and rotation takes its place. THE tool for a glass storey or '
                'an alternating facade: draw the box in the solid material, then add_curtain_wall(walls=<group>, '
                'storeys=[0, 2, 4, …]) — one call for all the glass storeys. A wall that holds a door is KEPT (as a '
                'mat_glass wall) so the entrance survives; put the entrance in first. Also shopfronts, office '
                'facades and glazed atria.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'walls': {'description': '"new", "all", a group name, or a list of wall ids'},
                    'mullion': {'type': 'number', 'description': 'vertical spacing in metres, default 1.5'},
                    'transom': {'type': 'number', 'description': 'horizontal spacing in metres, default 1.2'},
                    'storeys': {
                        'type': 'array',
                        'items': {'type': 'integer'},
                        'description': 'the storeys to glaze, e.g. [0, 2, 4, 6] for every other storey from the ground up; leave out for all',
                    },
                    'keep_doors': {
                        'type': 'boolean',
                        'description': 'default true: a wall holding a door stays a (glass) wall',
                    },
                    'name': {'type': 'string'},
                },
                'required': [],
            },
        },
        t_add_curtain_wall,
    ),
    (
        {
            'name': 'add_garage',
            'description': 'One up-and-over garage door in one named wall, at "middle" or a distance in metres along it.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'wall_id': {'type': 'string'},
                    'at': {'description': '"middle" or metres from the wall\'s -X end'},
                    'width': {'type': 'number'},
                    'height': {'type': 'number'},
                    'panels': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['wall_id'],
            },
        },
        t_add_garage,
    ),
]

EXAMPLES = [
    {
        'ask': 'a 20 x 20 m tower centred on FH100, 20 storeys, ground floor glass, next floor rough concrete, '
        'alternating all the way up, an entrance with a porte-cochere on the south, an infinity pool on the roof',
        'core': True,
        'calls': [
            {
                'tool': 'plan_building',
                'args': {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20},
            },
            {'tool': 'search_materials', 'args': {'query': 'rough board-formed concrete', 'limit': 3}},
            {
                'tool': 'draw_box',
                'args': {
                    'centre': 'FH100',
                    'width': 20,
                    'depth': 20,
                    'storeys': 20,
                    'roof': 'flat',
                    'material': 'pht_rough_concrete',
                    'name': 'tower',
                },
            },
            {
                'tool': 'add_opening',
                'args': {
                    'group': 'tower',
                    'side': 'south',
                    'storey': 0,
                    'kind': 'double_door',
                    'width': 2.4,
                    'height': 3,
                },
            },
            {
                'tool': 'add_canopy',
                'args': {
                    'group': 'tower',
                    'side': 'south',
                    'storey': 0,
                    'width': 12,
                    'depth': 5,
                    'height': 4.2,
                    'columns': 4,
                },
            },
            {
                'tool': 'add_curtain_wall',
                'args': {
                    'walls': 'tower',
                    'storeys': [0, 2, 4, 6, 8, 10, 12, 14, 16, 18],
                    'mullion': 1.5,
                    'transom': 1.35,
                },
            },
            {
                'tool': 'add_facade_bands',
                'args': {'group': 'tower', 'kind': 'string_course', 'every_n_storeys': 1, 'depth': 0.15},
            },
            {'tool': 'add_elevator', 'args': {'cell': 'FH100', 'from_storey': 0, 'to_storey': 20}},
            {'tool': 'add_stair', 'args': {'cell': 'FJ100', 'from_storey': 0, 'to_storey': 20, 'kind': 'u'}},
            {'tool': 'add_parapet', 'args': {'group': 'tower', 'height': 1.1, 'cap': True}},
            {
                'tool': 'add_pool',
                'args': {'cell_from': 'FC104', 'cell_to': 'FL109', 'storey': 20, 'depth': 1.5, 'infinity': 'south'},
            },
            {'tool': 'add_road', 'args': {'cells': ['FH135', 'FH112'], 'width': 8}},
            {
                'tool': 'plant_tree_line',
                'args': {'cells': ['FA135', 'FA113'], 'kind': 'deciduous', 'height': 10, 'spacing': 7},
            },
            {
                'tool': 'plant_tree_line',
                'args': {'cells': ['FO135', 'FO113'], 'kind': 'deciduous', 'height': 10, 'spacing': 7},
            },
            {
                'tool': 'add_street_furniture',
                'args': {'cells': ['FC112', 'FC122', 'FC132', 'FM112', 'FM122', 'FM132'], 'kind': 'lamp_post'},
            },
            {'tool': 'design_check', 'args': {}},
            {
                'tool': 'blender_render',
                'args': {'from_cell': 'FH135', 'to_cell': 'FH109', 'eye_height': 1.7, 'focal_mm': 28, 'look_height': 4},
            },
            {
                'tool': 'done',
                'args': {
                    'summary': '20-storey tower 20 x 20 m at EX90..FQ109, glass and concrete storeys alternating, south entrance with a 4-column canopy, infinity pool on the roof facing south, drive with trees and lamps.'
                },
            },
        ],
    },
    {
        'ask': 'arched windows on the front of the house, one per wall, on the ground floor only',
        'calls': [
            {
                'tool': 'add_special_openings',
                'args': {
                    'walls': 'new',
                    'kind': 'window_arch',
                    'width': 1.2,
                    'height': 1.4,
                    'sill': 0.9,
                    'every_n_storeys': 100,
                },
            }
        ],
    },
    {
        'ask': 'a round window 60 cm across high up in every gable wall',
        'calls': [
            {
                'tool': 'add_special_openings',
                'args': {'walls': 'all', 'kind': 'window_round', 'width': 0.6, 'sill': 2.0},
            }
        ],
    },
    {
        'ask': 'a bay window on the ground floor and french doors at the back',
        'calls': [
            {
                'tool': 'add_special_openings',
                'args': {'walls': 'new', 'kind': 'window_bay', 'width': 2.4, 'height': 1.4, 'sill': 0.9},
            },
            {
                'tool': 'add_special_openings',
                'args': {'walls': ['o3'], 'kind': 'door_french', 'width': 1.6, 'height': 2.1},
            },
        ],
    },
    {
        'ask': 'glaze the whole shopfront on the ground floor',
        'calls': [{'tool': 'add_curtain_wall', 'args': {'walls': 'new', 'storeys': 0, 'mullion': 1.5, 'transom': 1.2}}],
    },
    {
        'ask': 'ribbon windows along the office facade, 8 m long, sill 1.1',
        'calls': [
            {
                'tool': 'add_special_openings',
                'args': {'walls': 'new', 'kind': 'window_strip', 'width': 8, 'height': 1.0, 'sill': 1.1},
            }
        ],
    },
    {
        'ask': 'put a 2.5 m garage door in wall o7',
        'calls': [{'tool': 'add_garage', 'args': {'wall_id': 'o7', 'width': 2.5}}],
    },
]
