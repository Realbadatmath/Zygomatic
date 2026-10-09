# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Walls by side, openings, objects, edits, get_state, help and the tool schemas.

Moved verbatim out of the old single-file arch_assistant.py (lines 1074-1708).
"""

from __future__ import annotations

import json
import math

from zyg_workflows.arch_assistant.config import (
    MATERIALS,
    OPENINGS,
)
from zyg_workflows.arch_assistant.tools import (
    t_add_roof,
    t_add_slab,
    t_add_windows,
    t_draw_box,
    t_draw_wall,
)

# ── walls by side (2026-09-10) ───────────────────────────────────────────────
# add_opening / add_canopy wanted a wall id. draw_box hands them out, but the
# moment add_curtain_wall glazed storey 0 the south wall's id was gone and the
# model spent three get_state calls, a 47 s thought and three "o2 is not a
# wall" refusals finding the new one. Now a wall is addressed by what the
# request says: group + side + storey.
SIDE_WORDS = {
    'north': 'north',
    'n': 'north',
    'back': 'north',
    'rear': 'north',
    'south': 'south',
    's': 'south',
    'front': 'south',
    'east': 'east',
    'e': 'east',
    'right': 'east',
    'west': 'west',
    'w': 'west',
    'left': 'west',
}


def openings_in_wall(d, w: dict) -> list:
    """The opening records that sit IN wall w — the tab's own arSyncHoles rule:
    on the wall line within t/2 + 0.45 m, inside its length, y within its height."""
    out = []
    L = _num(w['p'].get('len'), 4)
    t = _num(w['p'].get('t'), 0.24)
    H = _num(w['p'].get('h'), STOREY_M)
    for o in d.objs:
        if not is_opening(o.get('kind')) or o.get('hidden'):
            continue
        lx, lz = world_to_local(w, o['x'], o['z'])
        if abs(lz) > t / 2 + 0.45 or abs(lx) > L / 2 + 0.05:
            continue
        if o['y'] < w['y'] - 0.05 or o['y'] > w['y'] + H - 0.05:
            continue
        out.append(o)
    return out


def wall_on_side(d, group, side, storey=0, kinds=('wall', 'partition')) -> tuple:
    """(record, error): the wall of `group` on `side` at `storey`. By name first
    (draw_box names its walls "south wall st3"), else by geometry — the
    outermost wall on that side of the group's plan centre, running along it."""
    sd = SIDE_WORDS.get(str(side or '').strip().lower())
    if not sd:
        return None, 'refused: side must be north, south, east or west'
    st = int(_num(storey, 0))
    recs = [o for o in d.select(group) if o.get('kind') in kinds and not o.get('hidden')]
    if not recs:
        return None, f'refused: no wall in "{group}" — pass the group name draw_box returned, or a wall id'
    at = [o for o in recs if storey_index(d, o) == st]
    if not at:
        have = sorted({storey_index(d, o) for o in recs})
        return None, f'refused: "{group}" has no wall on storey {st} (it has storeys {have[0]}..{have[-1]})'
    named = [o for o in at if str(o.get('name') or '').lower().startswith(sd)]
    if named:
        return named[0], ''
    # the plan extent comes from EVERY wall-like record of the group, whatever its
    # kind: after add_curtain_wall the glazed storeys are curtain_wall records
    ext = [
        o for o in d.select(group) if o.get('kind') in ('wall', 'partition', 'curtain_wall') and not o.get('hidden')
    ] or recs
    cx = sum(o['x'] for o in ext) / len(ext)
    cz = sum(o['z'] for o in ext) / len(ext)

    def along_x(o):  # runs along +X: a north or south face
        return abs(math.cos(_num(o.get('ry'), 0.0))) > 0.7

    key = {
        'north': lambda o: (not along_x(o), o['z'] - cz),
        'south': lambda o: (not along_x(o), cz - o['z']),
        'west': lambda o: (along_x(o), o['x'] - cx),
        'east': lambda o: (along_x(o), cx - o['x']),
    }[sd]
    best = sorted(at, key=key)[0]
    # 2026-09-11: with ONE candidate left on the storey (the others turned curtain_wall)
    # the sort returned it whatever side it stood on — job 71ac02b0's replay hung a
    # "north" fire escape on the south face. The pick must lie on the requested side.
    xs, zs = [o['x'] for o in ext], [o['z'] for o in ext]
    on_side = {
        'north': along_x(best) and best['z'] <= min(zs) + 0.6,
        'south': along_x(best) and best['z'] >= max(zs) - 0.6,
        'west': (not along_x(best)) and best['x'] <= min(xs) + 0.6,
        'east': (not along_x(best)) and best['x'] >= max(xs) - 0.6,
    }[sd]
    if not on_side:
        there = sorted(
            {
                str(o.get('kind'))
                for o in d.select(group)
                if storey_index(d, o) == st
                and not o.get('hidden')
                and o.get('kind') in ('wall', 'partition', 'curtain_wall')
            }
        )
        return None, (
            f'refused: "{group}" has no {sd} wall of kind {"/".join(kinds)} on storey {st} '
            f'(that storey holds {", ".join(there) or "no wall"}) — a glazed storey is a curtain_wall: '
            f'pass its wall id, or a storey whose {sd} face is a wall'
        )
    return best, ''


def host_wall(d, wall_id, group, side, storey, kinds=('wall', 'partition')) -> tuple:
    """(record, error, how): the wall a facade tool works on — by id, or by
    group + side + storey when no id was given."""
    if wall_id in (None, ''):
        if not group or not side:
            return None, 'refused: pass wall_id, or group + side (+ storey)', ''
        w, err = wall_on_side(d, group, side, storey, kinds)
        return (
            w,
            err,
            f' ({SIDE_WORDS.get(str(side).strip().lower(), side)} side of "{group}", storey {int(_num(storey, 0))})',
        )
    w = d.find(str(wall_id))
    if not w or w['kind'] not in kinds:
        return None, f'refused: {wall_id} is not a wall — pass a wall id from draw_box, or group + side + storey', ''
    return w, '', ''


def t_add_opening(
    d: Drawing,
    a,
    wall_id=None,
    kind='door',
    at='middle',
    width=None,
    height=None,
    sill=None,
    material='',
    group='',
    side='',
    storey=0,
):
    w, err, how = host_wall(d, wall_id, group, side, storey, ('wall', 'partition', 'curtain_wall'))
    if err:
        return err
    if w['kind'] == 'curtain_wall':
        return (
            f'refused: {w["id"]} is a curtain wall — glazing cannot hold a door (the studio cuts holes in walls '
            'only). Put the entrance in BEFORE add_curtain_wall (it keeps a wall that holds a door and turns it '
            'glass), or call add_curtain_wall with storeys that skip this one'
        )
    wall_id = w['id']
    if not is_opening(kind):
        return 'refused: kind must be door, double_door, window, opening' + (
            ', ' + ', '.join(OPENINGS_EXT) if OPENINGS_EXT else ''
        )
    L = _num(w['p'].get('len'), 4)
    u = L / 2 if str(at) == 'middle' else max(0.3, min(L - 0.3, _num(at, L / 2)))
    p = dict(KINDS.get(kind) or {'w': 1.0, 'h': 2.1})
    if width is not None:
        p['w'] = _num(width, p.get('w', 1.0))
    if height is not None:
        p['h'] = _num(height, p['h'])
    if sill is not None and 'sill' in p:
        p['sill'] = _num(sill, p['sill'])
    # 2026-09-11: a 3.0 m double door asked for in a 2.7 m wall cut a hole taller than
    # the wall (t_add_windows already clamps; this path did not)
    wall_h = _num(w['p'].get('h'), STOREY_M)
    top = wall_h - (
        _num(p.get('sill'), 0.0) if 'sill' in p else 0.0
    )  # flush with the wall top is allowed (a shopfront strip)
    if _num(p.get('h'), 0.0) > top + 1e-6 and top > 0.3:
        p['h'] = round(top, 3)
        how += f' (height clamped to {p["h"]:g} m: the wall is {wall_h:g} m)'
    x, z = _wall_world(w, u)
    mat = material if material in MATERIALS else None
    # 2026-09-16: a door in a GLAZED ground floor is a GLASS door. add_curtain_wall
    # keeps the wall that holds a door and turns it mat_glass, so the host's own
    # material is the only signal the studio has — and the timber leaf this used to
    # default to is what made the live tower's entrance (o102, pht_oak_veneer_01 in
    # the glass wall o2) read as a brown panel stuck on a shopfront. Only when the
    # caller named nothing: an explicit material still wins.
    if (
        mat is None
        and (str(kind).startswith('door') or kind == 'double_door')
        and (w['kind'] == 'curtain_wall' or str(w.get('mat') or '') == 'mat_glass')
    ):
        mat = 'mat_glass'
    o = d.new(kind, _with_base(p, _num(w['p'].get('base'), 0.0)), x, z, w['y'], w['ry'], mat, grp=w['grp'])
    o['meta']['host'] = w['id']  # delete the wall, the opening goes with it
    return f'{kind} {o["id"]} in wall {wall_id}{how} at {u:.2f} m along it'


def _p_footprint(p: dict) -> tuple:
    """(w, d) of a kind's plan footprint from its own parameters."""
    if 'w' in p and 'd' in p:
        return abs(_num(p['w'], 0.0)), abs(_num(p['d'], 0.0))
    if 'rx' in p and 'rz' in p:  # an elliptical plan (stadium_ring, mass_ellipse)
        return 2 * abs(_num(p['rx'], 0.0)), 2 * abs(_num(p['rz'], 0.0))
    if 'len' in p:
        return abs(_num(p['len'], 0.0)), abs(_num(p.get('w'), _num(p.get('t'), 0.5)))
    if 'r' in p:
        return 2 * abs(_num(p['r'], 0.0)), 2 * abs(_num(p['r'], 0.0))
    if 'w' in p:
        return abs(_num(p['w'], 0.0)), abs(_num(p['w'], 0.0))
    return 0.0, 0.0


def t_add_object(
    d: Drawing, a, kind, cell, storey=0, params=None, rotation_deg=0, material='', name='', base_height=None
):
    if kind not in KINDS or is_opening(kind):
        return 'refused: unknown kind — the kinds are ' + ', '.join(k for k in KINDS if not is_opening(k))
    x, z = cell_centre(*parse_cell(cell))
    p = dict(KINDS[kind])
    for k, v in (params or {}).items():
        if k in p or k in ('seg', 'sides') or kind in EXT_KINDS:
            p[k] = _num(v, p.get(k, 0)) if not isinstance(v, (list, dict, str)) else v
    ry = math.radians(_num(rotation_deg, 0))
    # a GROUND kind (and a sculpt, which is the same heightfield's parameters) IS
    # the ground: it keeps the old base plane and never levels itself away. A
    # water surface takes the ground under it but never levels it either.
    # Everything else stands on the ground under its own footprint.
    if kind in EXT_HEIGHTS or is_sculpt(kind) or 'base' in KINDS[kind]:
        b0, note = (_num(base_height, 0.0) if base_height not in (None, '') else 0.0), ''
    else:
        fw, fd = _p_footprint(p)
        b0, note = footprint_base(d, x, z, fw, fd, ry, base_height, level=kind not in WATER_SURFACES)
        p = _with_base(p, b0)
    st = int(_num(storey, 0))
    y = b0 + st * d.storey_h
    if st > 0 and base_height in (None, ''):
        top, deck = deck_top(d, x, z, y)
        if deck is not None and top > y + 1e-6:
            note += f'storey {st} is the deck of {deck["id"]} at {top:g} m. '
            y = top
    o = d.new(kind, p, x, z, y, ry, material if material in MATERIALS else None, name=name or None, grp=name)
    return note + f'{kind} {o["id"]} at {cell} storey {st} with {json.dumps(p)}'


WALL_KINDS_DEL = ('wall', 'partition', 'curtain_wall')


def _on_segment(o: dict, w: dict) -> bool:
    """Does the opening `o` sit ON wall `w`'s line? Same y, on the line within
    0.2 m, inside its length. Used only for legacy records that carry no host."""
    if abs(_num(o.get('y'), 0.0) - _num(w.get('y'), 0.0)) >= 0.01:
        return False
    ry = _num(w.get('ry'), 0.0)
    ux, uz = math.cos(ry), -math.sin(ry)
    dx, dz = _num(o.get('x'), 0.0) - _num(w.get('x'), 0.0), _num(o.get('z'), 0.0) - _num(w.get('z'), 0.0)
    along = dx * ux + dz * uz
    perp = abs(dx * (-uz) + dz * ux)
    return perp <= 0.2 and abs(along) <= _num(w['p'].get('len'), 4.0) / 2 + 0.05


def t_delete(d: Drawing, a, which):
    recs = d.select(which)
    if not recs:
        return 'nothing matches'
    # a door or window is a hole IN a wall: deleting the wall must take it with
    # it. Openings drawn since 2026-09-12 name their wall in meta.host; older
    # ones are matched by geometry, and only when no surviving wall carries them
    # (a partition drawn on the facade line shares its line with the facade).
    gone = {r['id'] for r in recs}
    walls = [r for r in recs if r['kind'] in WALL_KINDS_DEL]
    extra = []
    if walls:
        survivors = [o for o in d.objs if o['kind'] in WALL_KINDS_DEL and o['id'] not in gone and not o.get('hidden')]
        for o in d.objs:
            if o['id'] in gone or not is_opening(o.get('kind')):
                continue
            host = (o.get('meta') or {}).get('host')
            if host:
                if host in gone:
                    extra.append(o)
                continue
            if any(_on_segment(o, w) for w in walls) and not any(_on_segment(o, s) for s in survivors):
                extra.append(o)
    d.remove(recs + extra)
    return f'deleted {len(recs)} objects' + (
        f' + {len(extra)} door(s)/window(s) that hung in the deleted walls ({", ".join(o["id"] for o in extra)})'
        if extra
        else ''
    )


def t_set_material(d: Drawing, a, which, material):
    if material not in MATERIALS:
        return 'refused: material must be one of ' + ', '.join(MATERIALS)
    recs = d.select(which)
    for o in recs:
        o['mat'] = material
    return f'set {material} on {len(recs)} objects'


def t_set_finish(d: Drawing, a, group, floor_material='', roof_material='', wall_material=''):
    """Repaint one group's three finishes: floors (slab), roof deck (roof_flat)
    and walls (wall / partition / the OPAQUE curtain_wall panels — glass stays
    glass). set_material paints everything one colour; this one keeps the three
    surfaces apart, which is the whole point of a finish."""
    want = {'floor': str(floor_material or ''), 'roof': str(roof_material or ''), 'wall': str(wall_material or '')}
    if not any(want.values()):
        return (
            'refused: name at least one of floor_material, roof_material, wall_material — '
            f'set_finish(group="{group}", floor_material="{FINISHES["luxury"]["floor"]}")'
        )
    for _k, m in want.items():
        if m and m not in MATERIALS:
            return (
                f'refused: "{m}" is not a material — search_materials(query="{m}") lists the ids, '
                f'or use a preset: ' + ', '.join(MATERIALS[:12])
            )
    recs = d.select(group)
    if not recs:
        return (
            f'refused: nothing is in group "{group}" — get_state(detail="objects") lists the groups, '
            f'then set_finish(group=<one of them>, floor_material="{FINISHES["luxury"]["floor"]}")'
        )
    done = {'floor': 0, 'roof': 0, 'wall': 0}
    for o in recs:
        k = o['kind']
        if k == 'slab':
            s = 'floor'
        elif k == 'roof_flat':
            s = 'roof'
        elif (k in ('wall', 'partition') or k == 'curtain_wall') and o.get('mat') != 'mat_glass':
            s = 'wall'  # a mat_glass wall (add_curtain_wall keeps the door wall as glass) stays glass
        else:
            continue
        if want[s]:
            o['mat'] = want[s]
            done[s] += 1
    if not sum(done.values()):
        return (
            f'refused: group "{group}" has no slab / roof_flat / wall record to paint '
            f'({len(recs)} objects, none of those kinds) — draw_box makes them'
        )
    return 'set on "%s": ' % group + ', '.join(
        f'{n} {s}{"s" if n != 1 else ""} {want[s]}' for s, n in done.items() if n
    )


def t_set_grid_scale(d: Drawing, a, metres_per_cell):
    """The cell size of THIS drawing — 1 m for a building, 5 or 10 m for a
    landscape. Only on an empty drawing: every record already placed was put at a
    cell centre computed at the old size, so changing it under them would move the
    grid out from under the drawing."""
    m = _num(metres_per_cell, 0)
    if m not in CELL_SIZES:
        return 'refused: the cell size must be 1, 2, 5 or 10 metres'
    if d.objs:
        return (
            f'refused: the drawing has {len(d.objs)} objects — the cell size is set before drawing; start a new drawing'
        )
    d.cell_m = float(m)
    _set_cell_m(d.cell_m)
    side = GRID_N * d.cell_m
    return f'cells are now {m:g} m: the field is {side:g} x {side:g} m, A1..{col_letters(GRID_N - 1)}{GRID_N}'


def t_get_state(d: Drawing, a, detail='summary', which='all'):
    if detail == 'objects':
        return d.summary() + '\n' + d.listing(which)
    return d.summary()


TOOL_DEFS = [
    {
        'name': 'get_state',
        'description': 'What is in the drawing now. detail=summary for counts and extents; detail=objects for a per-object listing (optionally filtered by "new", a kind, a group name or ids).',
        'input_schema': {
            'type': 'object',
            'properties': {'detail': {'type': 'string', 'enum': ['summary', 'objects']}, 'which': {'type': 'string'}},
            'required': [],
        },
    },
    {
        'name': 'set_grid_scale',
        'description': 'Set how many metres one grid cell is for THIS drawing: 1 (a building), 2, 5 or 10 (a landscape at real scale). The grid stays 300 x 300 cells A1..KN300, so 5 m cells make the field 1500 x 1500 m. Only on an EMPTY drawing, and before anything else; every size you give afterwards is still in metres.',
        'input_schema': {
            'type': 'object',
            'properties': {'metres_per_cell': {'type': 'number', 'enum': [1, 2, 5, 10]}},
            'required': ['metres_per_cell'],
        },
    },
    {
        'name': 'draw_box',
        'description': 'Draw a rectangular building: four walls per storey around the INCLUSIVE block of cells from cell_from to cell_to (e.g. C4 to L13 is a 10x10-cell footprint), stacked for `storeys` storeys starting at storey_from, with a floor slab per storey unless slabs=false, and an optional roof on top. This is the tool for "build N by M squares, K high". Takes centre + width + depth instead of the corners. Returns the group name, the wall ids per side and the roof deck height — plan the next calls from that reply.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cell_from': {'type': 'string'},
                'cell_to': {'type': 'string'},
                'centre': {
                    'type': 'string',
                    'description': 'the centre cell — with width + depth this replaces cell_from/cell_to ("20 x 20 centred on FH100" = centre FH100, width 20, depth 20)',
                },
                'width': {'type': 'integer', 'description': 'cells along X, with centre'},
                'depth': {'type': 'integer', 'description': 'cells along Z, with centre (default: width)'},
                'storeys': {'type': 'integer', 'minimum': 1, 'maximum': 400},
                'storey_from': {'type': 'integer'},
                'slabs': {'type': 'boolean'},
                'roof': {'type': 'string', 'enum': ['none', 'flat', 'gable', 'hip', 'shed']},
                'material': {'type': 'string', 'enum': MATERIALS, 'description': 'the WALL material'},
                'floor_material': {
                    'type': 'string',
                    'description': 'the material of every floor slab. Leave it out and the finish level decides (standard: mat_concrete; luxury: a library stone) — pass a search_materials id to overrule it.',
                },
                'roof_material': {
                    'type': 'string',
                    'description': 'the material of the flat roof deck. Leave it out and the finish level decides (standard: pht_bitumen; luxury: a timber deck).',
                },
                'wall_h': {'type': 'number'},
                'wall_t': {'type': 'number'},
                'base_height': {
                    'type': 'number',
                    'description': 'metres the base of storey 0 sits at. Leave it out and the tool uses the GROUND under the footprint, levelling it (a sculpt_flat + pad) when it is more than 0.3 m out of level.',
                },
                'name': {'type': 'string', 'description': 'group name for the outliner'},
            },
            'required': [],
        },
    },
    {
        'name': 'draw_wall',
        'description': 'One straight wall from the CENTRE of cell_from to the centre of cell_to, repeated per storey.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cell_from': {'type': 'string'},
                'cell_to': {'type': 'string'},
                'storeys': {'type': 'integer'},
                'storey_from': {'type': 'integer'},
                'material': {'type': 'string', 'enum': MATERIALS},
                'wall_h': {'type': 'number'},
                'wall_t': {'type': 'number'},
                'partition': {'type': 'boolean'},
                'base_height': {
                    'type': 'number',
                    'description': 'metres the base of storey 0 sits at. Leave it out and the tool uses the GROUND under the footprint, levelling it (a sculpt_flat + pad) when it is more than 0.3 m out of level.',
                },
                'name': {'type': 'string'},
            },
            'required': ['cell_from', 'cell_to'],
        },
    },
    {
        'name': 'add_slab',
        'description': 'A floor slab covering the inclusive block of cells at a storey.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cell_from': {'type': 'string'},
                'cell_to': {'type': 'string'},
                'storey': {'type': 'integer'},
                'thickness': {'type': 'number'},
                'material': {'type': 'string', 'enum': MATERIALS},
                'name': {'type': 'string'},
                'base_height': {
                    'type': 'number',
                    'description': 'metres the base of storey 0 sits at. Leave it out and the tool uses the GROUND under the footprint, levelling it (a sculpt_flat + pad) when it is more than 0.3 m out of level.',
                },
            },
            'required': ['cell_from', 'cell_to'],
        },
    },
    {
        'name': 'add_roof',
        'description': 'A roof over the inclusive block of cells, sitting at the given storey (the storey ABOVE the top walls: a 3-storey box gets its roof at storey 3).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'cell_from': {'type': 'string'},
                'cell_to': {'type': 'string'},
                'storey': {'type': 'integer'},
                'kind': {'type': 'string', 'enum': ['flat', 'gable', 'hip', 'shed', 'dome', 'vault']},
                'height': {'type': 'number'},
                'overhang': {'type': 'number'},
                'material': {'type': 'string', 'enum': MATERIALS},
                'base_height': {
                    'type': 'number',
                    'description': 'metres the base of storey 0 sits at. Leave it out and the tool uses the GROUND under the footprint, levelling it (a sculpt_flat + pad) when it is more than 0.3 m out of level.',
                },
            },
            'required': ['cell_from', 'cell_to', 'storey'],
        },
    },
    {
        'name': 'add_windows',
        'description': 'Put windows on walls. walls = "new" (walls drawn in this request), "all", a group name, or a list of wall ids. every_n_storeys=2 with storey_offset=0 means storeys 0,2,4,...; per_wall fixes the count per wall, otherwise one every `spacing` metres (default 3). Glass windows: material mat_glass.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'walls': {'type': ['string', 'array'], 'items': {'type': 'string'}},
                'every_n_storeys': {'type': 'integer', 'minimum': 1},
                'storey_offset': {'type': 'integer'},
                'per_wall': {'type': 'integer'},
                'spacing': {'type': 'number'},
                'width': {'type': 'number'},
                'height': {'type': 'number'},
                'sill': {'type': 'number'},
                'margin': {'type': 'number'},
                'material': {'type': 'string', 'enum': MATERIALS},
                'sides': {
                    'type': 'array',
                    'items': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'description': 'limit to these sides of a draw_box',
                },
            },
            'required': [],
        },
    },
    {
        'name': 'add_opening',
        'description': 'One door / double_door / window / opening in a wall, at "middle" or a distance in metres along it. Name the wall by id, OR by group + side + storey (add_opening(group="tower", side="south", storey=0, kind="double_door") is the entrance) — no need to look ids up. Put the entrance in BEFORE add_curtain_wall: glazing keeps a wall that holds a door.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'wall_id': {'type': 'string'},
                'group': {
                    'type': 'string',
                    'description': 'the building group (draw_box name) — with side + storey instead of wall_id',
                },
                'side': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                'storey': {'type': 'integer', 'description': 'with group + side; default 0'},
                'kind': {'type': 'string', 'enum': list(OPENINGS)},
                'at': {'type': ['string', 'number']},
                'width': {'type': 'number'},
                'height': {'type': 'number'},
                'sill': {'type': 'number'},
                'material': {'type': 'string', 'enum': MATERIALS},
            },
            'required': [],
        },
    },
    {
        'name': 'add_object',
        'description': "Place any other catalogue object at the centre of a cell: column_rect, column_round, beam, footing, truss, stair_straight, stair_l, stair_spiral, ramp, railing, ladder, roof_*, pad, road, path, tree, bollard, person, box, cylinder, sphere, cone, pyramid, torus, wedge, capsule, plane, disc. params override the kind's numbers (len/w/d/h/t/r...).",
        'input_schema': {
            'type': 'object',
            'properties': {
                'kind': {'type': 'string'},
                'cell': {'type': 'string'},
                'storey': {'type': 'integer'},
                'params': {'type': 'object'},
                'rotation_deg': {'type': 'number'},
                'material': {'type': 'string', 'enum': MATERIALS},
                'base_height': {
                    'type': 'number',
                    'description': 'metres the base of storey 0 sits at. Leave it out and the tool uses the GROUND under the footprint, levelling it (a sculpt_flat + pad) when it is more than 0.3 m out of level.',
                },
                'name': {'type': 'string'},
            },
            'required': ['kind', 'cell'],
        },
    },
    {
        'name': 'delete',
        'description': 'Remove objects: "new", "all", a kind, a group name, or a list of ids. Only when the user asked for it. Doors and windows hung in a deleted wall go with it.',
        'input_schema': {
            'type': 'object',
            'properties': {'which': {'type': ['string', 'array'], 'items': {'type': 'string'}}},
            'required': ['which'],
        },
    },
    {
        'name': 'set_material',
        'description': 'Change the material of objects ("new", "all", a kind, a group, or ids).',
        'input_schema': {
            'type': 'object',
            'properties': {
                'which': {'type': ['string', 'array'], 'items': {'type': 'string'}},
                'material': {'type': 'string', 'enum': MATERIALS},
            },
            'required': ['which', 'material'],
        },
    },
    {
        'name': 'set_finish',
        'description': "Repaint ONE group's three finishes separately: floor_material goes on the floor slabs, roof_material on the flat roof deck, wall_material on the walls and the opaque curtain-wall panels (glass stays glass). Use a search_materials id for anything a person sees on a luxury request — this is the tool that turns a grey massing model into a finished building without painting it all one colour.",
        'input_schema': {
            'type': 'object',
            'properties': {
                'group': {'type': 'string', 'description': 'the group name draw_box printed'},
                'floor_material': {'type': 'string'},
                'roof_material': {'type': 'string'},
                'wall_material': {'type': 'string'},
            },
            'required': ['group'],
        },
    },
    {
        'name': 'look',
        'description': 'Ask the studio for a fresh picture of the drawing AS IT WOULD BE with your changes so far: view top/iso/front/right, optionally one storey with cell labels on. Use it to check your work before done.',
        'input_schema': {
            'type': 'object',
            'properties': {
                'view': {'type': 'string', 'enum': ['top', 'iso', 'front', 'right']},
                'storey': {'type': 'integer'},
                'cells': {'type': 'boolean'},
            },
            'required': ['view'],
        },
    },
    {
        'name': 'ask_user',
        'description': 'Stop and ask the user ONE question when the request is ambiguous in a way that changes what gets built (e.g. "100 squares high": 100 storeys or 100 metres?). Nothing drawn so far is injected until the user answers, so ask before drawing.',
        'input_schema': {'type': 'object', 'properties': {'question': {'type': 'string'}}, 'required': ['question']},
    },
    {
        'name': 'done',
        'description': "Finish: hand the drawing to the studio with a one-or-two-sentence summary of what was built and where. Runs design_check first and REFUSES while it reports errors (floors missing, something buried in a deck, pool water below its deck, a column piercing a plate): fix them and call done again. There is no force flag (2026-09-11): after two refusals the gate hands the drawing over marked UNFINISHED with the open errors listed, so fix them. Call present() first, then portfolio(): done refuses until BOTH are of the CURRENT drawing — present() renders the five judged views with the design-check numbers, portfolio() writes the operator's ~50-picture hand-over folder (right round it, cuts at six stations, two from inside every level, raking shots for curve fairness, close lenses) with a surface audit of the materials and the shading beside it.",
        'input_schema': {'type': 'object', 'properties': {'summary': {'type': 'string'}}, 'required': ['summary']},
    },
]
TOOL_DEFS.append(
    {
        'name': 'help',
        'description': 'List what this assistant can do (every tool, one line), optionally filtered by a word.',
        'input_schema': {'type': 'object', 'properties': {'topic': {'type': 'string'}}, 'required': []},
    }
)
TOOL_FN = {
    'get_state': t_get_state,
    'set_grid_scale': t_set_grid_scale,
    'draw_box': t_draw_box,
    'draw_wall': t_draw_wall,
    'add_slab': t_add_slab,
    'add_roof': t_add_roof,
    'add_windows': t_add_windows,
    'add_opening': t_add_opening,
    'add_object': t_add_object,
    'delete': t_delete,
    'set_material': t_set_material,
    'set_finish': t_set_finish,
}


# Imported here, at the foot of the module, because these names are used only inside
# function bodies and their modules import this one back: by this line every name
# above is already bound, so the call-time cycle resolves either way round.
from zyg_workflows.arch_assistant.config import (  # noqa: E402
    CELL_SIZES,
    FINISHES,
    GRID_N,
    KINDS,
    STOREY_M,
    _num,
    _set_cell_m,
    cell_centre,
    col_letters,
    parse_cell,
)
from zyg_workflows.arch_assistant.drawing import Drawing  # noqa: E402
from zyg_workflows.arch_assistant.tools import _wall_world  # noqa: E402
from zyg_workflows.arch_assistant.ground import (  # noqa: E402
    EXT_HEIGHTS,
    EXT_KINDS,
    OPENINGS_EXT,
    WATER_SURFACES,
    _with_base,
    deck_top,
    footprint_base,
    is_opening,
    is_sculpt,
    storey_index,
    world_to_local,
)
