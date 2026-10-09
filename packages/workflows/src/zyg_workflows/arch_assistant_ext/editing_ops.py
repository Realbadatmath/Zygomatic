# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""editing_ops — the assistant's editing tools (no new kinds).

Everything here EDITS records that already exist in the drawing: it moves,
turns, flips, repeats, rescales, renames, regroups, hides and re-kinds them.
No geometry is added to the tab or to Blender, so this family has no .js and
no arch_blender_ext module; `arch_ext/editing_ops.json` is present but empty
so the file set stays complete.

Conventions (arch_ext/README.md): x/z are metres, one grid cell is
`cell_size()` metres — a per-DRAWING setting (1, 2, 5 or 10; `arch_assistant`
installs it for the length of a tool call), so every cell-to-metre conversion
here calls cell_size() at USE time and never caches the module default. There
are five such conversions: move and array multiply their *_cells steps by
cell_size(); move_to, copy_to and the `about` cell of rotate/mirror go through
parse_cell + cell_centre, which read the same live value. y is
the storey base (storey k -> k * d.storey_h), `ry` is the rotation about the
vertical axis in radians, and a point at plan angle theta sits at
(r*cos(theta), -r*sin(theta)) — so rotating a position by theta is

    x' = px + dx*cos(theta) + dz*sin(theta)
    z' = pz - dx*sin(theta) + dz*cos(theta)

and `ry` gains theta, which keeps every wall on its own line. Mirroring in x
negates the x component of that direction (ry -> pi - ry); mirroring in z
negates the z component (ry -> -ry).

`which` is resolved by Drawing.select: 'new' | 'all' | a kind | a group name |
a list of ids | one id.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as _A
from zyg_workflows.arch_assistant import (
    MAX_OBJECTS,
    Drawing,
    cell_centre,
    cell_name,
    cell_of,
    cell_size,
    parse_cell,
    storey_of,
    _num,
)

# This family adds NO kinds. `KINDS` must stay empty here: load_extensions()
# reads it off the module, so importing arch_assistant.KINDS under that name
# would re-register every base kind as an extension kind. The live catalogue
# is read through _A.KINDS instead, which also sees the families loaded after
# this one.
KINDS: dict = {}
OPENINGS: list = []

PROMPT = (
    'Editing what is ALREADY drawn (every tool takes which = "new", "all", a kind, a group name or ids): '
    'move(dx_cells,dz_cells,dy_storeys) and move_to(cell,storey) shift it; rotate(degrees,about) and mirror(axis,about) '
    'turn or flip it about the selection centre or a cell; array(count,step_x_cells,step_z_cells,step_storeys) repeats '
    'it in a row, stack(count) adds copies one storey apart, copy_to(cell) drops one copy, duplicate_storey(group,'
    'storey,to_storeys) copies a whole floor. scale(factor), set_param(key,value), set_height(storeys|metres), '
    'set_thickness(t) and replace_kind(kind) change numbers and kinds (wall->partition). rename, group, hide, show and '
    'select_objects tidy the outliner and the viewport. Openings moved with their wall are re-hosted on injection.'
)

# parameters that are LENGTHS and therefore scale; counts (seg, sides, steps,
# bays, posts, rungs) and angles (a0, a1, sweep) must not.
SCALE_KEYS = (
    'w',
    'd',
    'h',
    't',
    'len',
    'r',
    'rt',
    'r_in',
    'r_out',
    'r_can',
    'r_trunk',
    'span',
    'sill',
    'over',
    'rise',
    'run',
)


# ── helpers ─────────────────────────────────────────────────────────────────
def _pick(d: Drawing, which):
    """Selection, or [] — every tool refuses on an empty one with the same words."""
    return d.select(which if which is not None else 'new')


def _none(which):
    return f'refused: nothing matches {which!r} — pass "new", "all", a kind, a group name or a list of ids'


def _centroid(recs) -> tuple:
    n = float(len(recs))
    return sum(o['x'] for o in recs) / n, sum(o['z'] for o in recs) / n


def _is_self(about) -> bool:
    return str(about if about is not None else 'centre').strip().lower() in ('', 'centre', 'center', 'middle', 'self')


def _pivot(recs, about) -> tuple:
    """'centre' (the selection's own centroid) or a cell label."""
    if _is_self(about):
        return _centroid(recs)
    return cell_centre(*parse_cell(about))


def _room(d: Drawing, n: int) -> str:
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} more objects and the drawing may hold {MAX_OBJECTS} in total'
    return ''


def _span(recs) -> str:
    ids = [o['id'] for o in recs]
    return f'{len(ids)} object(s) {ids[0]}..{ids[-1]}' if len(ids) > 1 else f'1 object {ids[0]}'


def _where(recs, d: Drawing) -> str:
    cx, cz = _centroid(recs)
    ys = [o['y'] for o in recs]
    return f'{cell_of(cx, cz)} storeys {storey_of(min(ys), d.storey_h)}..{storey_of(max(ys), d.storey_h)}'


def _copy(d: Drawing, o: dict, dx=0.0, dy=0.0, dz=0.0, name=None) -> dict:
    c = d.new(
        o['kind'],
        dict(o['p']),
        o['x'] + dx,
        o['z'] + dz,
        o['y'] + dy,
        o['ry'],
        o['mat'],
        name=name or o['name'],
        grp=o['grp'],
    )
    c['rx'], c['rz'], c['s'], c['hidden'] = o['rx'], o['rz'], o['s'], o['hidden']
    return c


# ── move ────────────────────────────────────────────────────────────────────
def t_move(d: Drawing, a, which='new', dx_cells=0, dz_cells=0, dy_storeys=0):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    m = cell_size()
    dx, dz = _num(dx_cells, 0) * m, _num(dz_cells, 0) * m
    dy = _num(dy_storeys, 0) * d.storey_h
    if not (dx or dz or dy):
        return 'refused: dx_cells, dz_cells and dy_storeys are all zero — nothing would move'
    for o in recs:
        o['x'] = round(o['x'] + dx, 4)
        o['z'] = round(o['z'] + dz, 4)
        o['y'] = round(o['y'] + dy, 4)
    return f'moved {_span(recs)} by {dx:g} m east, {dz:g} m south, {dy:g} m up — now around {_where(recs, d)}'


def t_move_to(d: Drawing, a, which='new', cell='A1', storey=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    tx, tz = cell_centre(*parse_cell(cell))
    ox, oz = _centroid(recs)
    dx, dz = tx - ox, tz - oz
    dy = 0.0
    if storey is not None:
        dy = int(_num(storey, 0)) * d.storey_h - min(o['y'] for o in recs)
    for o in recs:
        o['x'] = round(o['x'] + dx, 4)
        o['z'] = round(o['z'] + dz, 4)
        o['y'] = round(o['y'] + dy, 4)
    return (
        f'moved {_span(recs)} so its centre sits on {cell_name(*parse_cell(cell))}'
        + (f', lowest storey {int(_num(storey, 0))}' if storey is not None else '')
        + f' ({dx:+.2f} m x, {dz:+.2f} m z, {dy:+.2f} m y)'
    )


# ── turn and flip ───────────────────────────────────────────────────────────
def t_rotate(d: Drawing, a, which='new', degrees=90, about='centre'):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    deg = _num(degrees, 90)
    if deg % 360 == 0:
        return 'refused: that is a whole number of full turns — give an angle like 90, -45 or 180'
    th = math.radians(deg)
    px, pz = _pivot(recs, about)
    ca, sa = math.cos(th), math.sin(th)
    for o in recs:
        dx, dz = o['x'] - px, o['z'] - pz
        o['x'] = round(px + dx * ca + dz * sa, 4)
        o['z'] = round(pz - dx * sa + dz * ca, 4)
        o['ry'] = round(o['ry'] + th, 6)
    return (
        f'rotated {_span(recs)} by {deg:g}° about '
        + ('its own centre' if _is_self(about) else cell_name(*parse_cell(about)))
        + f' — now around {_where(recs, d)}'
    )


def t_mirror(d: Drawing, a, which='new', axis='x', about=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    ax = str(axis or 'x').strip().lower()
    if ax not in ('x', 'z'):
        return 'refused: axis must be "x" (flip east-west) or "z" (flip north-south)'
    px, pz = _pivot(recs, about)
    for o in recs:
        if ax == 'x':
            o['x'] = round(2 * px - o['x'], 4)
            o['ry'] = round(math.pi - o['ry'], 6)
        else:
            o['z'] = round(2 * pz - o['z'], 4)
            o['ry'] = round(-o['ry'], 6)
    return (
        f'mirrored {_span(recs)} in {ax} about '
        + ('its own centre' if _is_self(about) else cell_name(*parse_cell(about)))
        + f' — now around {_where(recs, d)}'
    )


# ── repeat ──────────────────────────────────────────────────────────────────
def t_array(d: Drawing, a, which='new', count=3, step_x_cells=0, step_z_cells=0, step_storeys=0):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    n = int(_num(count, 3))
    if n < 2 or n > 200:
        return 'refused: count must be between 2 and 200 (it is the TOTAL number of copies, the original included)'
    m = cell_size()
    dx, dz = _num(step_x_cells, 0) * m, _num(step_z_cells, 0) * m
    dy = _num(step_storeys, 0) * d.storey_h
    if not (dx or dz or dy):
        return 'refused: every copy would land on the original — give step_x_cells, step_z_cells or step_storeys'
    full = _room(d, len(recs) * (n - 1))
    if full:
        return full
    made = []
    for k in range(1, n):
        for o in recs:
            made.append(_copy(d, o, dx * k, dy * k, dz * k))
    return (
        f'arrayed {_span(recs)} into {n} copies ({len(made)} new objects {made[0]["id"]}..{made[-1]["id"]}), '
        f'step {dx:g} m x / {dz:g} m z / {dy:g} m y'
    )


def t_stack(d: Drawing, a, which='new', count=1):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    n = int(_num(count, 1))
    if n < 1 or n > 200:
        return 'refused: count must be between 1 and 200 (it is how many EXTRA storeys are added above)'
    full = _room(d, len(recs) * n)
    if full:
        return full
    made = []
    for k in range(1, n + 1):
        for o in recs:
            st = storey_of(o['y'], d.storey_h) + k
            nm = o['name'].replace(f'st{storey_of(o["y"], d.storey_h)}', f'st{st}') if 'st' in o['name'] else o['name']
            made.append(_copy(d, o, 0.0, k * d.storey_h, 0.0, name=nm))
    return (
        f'stacked {_span(recs)} {n} storey(s) up: {len(made)} new objects '
        f'{made[0]["id"]}..{made[-1]["id"]}, top at {max(o["y"] for o in made):g} m'
    )


def t_copy_to(d: Drawing, a, which='new', cell='A1', storey=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    tx, tz = cell_centre(*parse_cell(cell))
    ox, oz = _centroid(recs)
    dy = 0.0
    if storey is not None:
        dy = int(_num(storey, 0)) * d.storey_h - min(o['y'] for o in recs)
    full = _room(d, len(recs))
    if full:
        return full
    made = [_copy(d, o, tx - ox, dy, tz - oz) for o in recs]
    return (
        f'copied {_span(recs)} to {cell_name(*parse_cell(cell))}'
        + (f' storey {int(_num(storey, 0))}' if storey is not None else '')
        + f': {len(made)} new objects {made[0]["id"]}..{made[-1]["id"]}'
    )


def t_duplicate_storey(d: Drawing, a, group='all', storey=0, to_storeys=None):
    recs = _pick(d, group)
    if not recs:
        return _none(group)
    st = int(_num(storey, 0))
    src = [o for o in recs if storey_of(o['y'], d.storey_h) == st]
    if not src:
        return f'refused: nothing in {group!r} sits on storey {st}'
    tos = [
        int(_num(t, 0))
        for t in (to_storeys if isinstance(to_storeys, (list, tuple)) else [to_storeys])
        if t is not None
    ]
    tos = [t for t in tos if t != st]
    if not tos:
        return 'refused: to_storeys must be a list of storey numbers other than the source storey'
    full = _room(d, len(src) * len(tos))
    if full:
        return full
    made = []
    for t in tos:
        for o in src:
            nm = o['name'].replace(f'st{st}', f'st{t}') if f'st{st}' in o['name'] else o['name']
            made.append(_copy(d, o, 0.0, (t - st) * d.storey_h, 0.0, name=nm))
    return (
        f'duplicated storey {st} of {group!r} ({len(src)} objects) onto storeys '
        + ', '.join(str(t) for t in tos)
        + f': {len(made)} new objects {made[0]["id"]}..{made[-1]["id"]}'
    )


# ── numbers ─────────────────────────────────────────────────────────────────
def t_scale(d: Drawing, a, which='new', factor=1.0):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    f = _num(factor, 1.0)
    if f <= 0.01 or f > 100 or abs(f - 1.0) < 1e-9:
        return 'refused: factor must be between 0.01 and 100 and not 1'
    px, pz = _centroid(recs)
    y0 = min(o['y'] for o in recs)
    hit = 0
    for o in recs:
        o['x'] = round(px + (o['x'] - px) * f, 4)
        o['z'] = round(pz + (o['z'] - pz) * f, 4)
        o['y'] = round(y0 + (o['y'] - y0) * f, 4)
        for k in SCALE_KEYS:
            if k in o['p'] and isinstance(o['p'][k], (int, float)):
                o['p'][k] = round(_num(o['p'][k], 0) * f, 4)
                hit += 1
    return f'scaled {_span(recs)} by {f:g} about its centre ({hit} parameters resized, base kept at {y0:g} m)'


def t_set_param(d: Drawing, a, which='new', key='', value=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    k = str(key or '').strip()
    if not k:
        return 'refused: key must be a parameter name such as len, w, d, h, t, r or sill'
    hit = [o for o in recs if k in o['p']]
    if not hit:
        have = sorted({p for o in recs for p in o['p']})
        return f'refused: none of those {len(recs)} objects has a parameter "{k}" — they have ' + (
            ', '.join(have) or 'none'
        )
    v = value if isinstance(value, (str, bool, list, dict)) else _num(value, None)
    if v is None:
        return f'refused: value for "{k}" must be a number or a string'
    for o in hit:
        o['p'][k] = v
    return f'set {k}={v} on {_span(hit)}' + (
        f' ({len(recs) - len(hit)} without that parameter left alone)' if len(hit) < len(recs) else ''
    )


def t_set_height(d: Drawing, a, which='new', storeys=None, metres=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    if storeys is None and metres is None:
        return 'refused: give storeys or metres'
    h = _num(metres, None) if metres is not None else _num(storeys, 1) * d.storey_h
    if h is None or h <= 0 or h > 300:
        return 'refused: the height must be between 0 and 300 m'
    hit = [o for o in recs if 'h' in o['p']]
    if not hit:
        return (
            f'refused: none of those {len(recs)} objects has a height parameter h '
            f'({", ".join(sorted({o["kind"] for o in recs}))}) — a slab or a flat roof has a thickness t, '
            f'use set_thickness or set_param instead'
        )
    for o in hit:
        o['p']['h'] = round(h, 4)
    return f'set h={h:g} m on {_span(hit)}' + (
        f' ({len(recs) - len(hit)} objects without a height left alone)' if len(hit) < len(recs) else ''
    )


def t_set_thickness(d: Drawing, a, which='new', t=0.24):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    tv = _num(t, None)
    if tv is None or tv <= 0 or tv > 5:
        return 'refused: the thickness must be between 0 and 5 m'
    hit = [o for o in recs if 't' in o['p']]
    if not hit:
        return (
            f'refused: none of those {len(recs)} objects has a thickness parameter t '
            f'({", ".join(sorted({o["kind"] for o in recs}))})'
        )
    for o in hit:
        o['p']['t'] = round(tv, 4)
    return f'set t={tv:g} m on {_span(hit)}' + (
        f' ({len(recs) - len(hit)} objects without a thickness left alone)' if len(hit) < len(recs) else ''
    )


def t_replace_kind(d: Drawing, a, which='new', kind='', params=None):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    k = str(kind or '').strip()
    if k not in _A.KINDS:
        return 'refused: unknown kind ' + repr(k) + ' — add_object lists the kinds this drawing knows'
    was: dict = {}
    for o in recs:
        was[o['kind']] = was.get(o['kind'], 0) + 1
        p = dict(_A.KINDS[k])
        for pk, pv in o['p'].items():  # carry the numbers the new kind also uses
            if pk in p:
                p[pk] = pv
        for pk, pv in (params or {}).items():
            p[pk] = _num(pv, p.get(pk, 0)) if not isinstance(pv, (list, dict, str)) else pv
        o['kind'] = k
        o['p'] = p
    return (
        f'replaced {", ".join(f"{v} {kk}" for kk, v in sorted(was.items()))} with {k}: {_span(recs)} '
        f'(position, rotation and material kept)'
    )


# ── outliner and viewport ───────────────────────────────────────────────────
def t_rename(d: Drawing, a, which='new', name=''):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    nm = str(name or '').strip()
    if not nm:
        return 'refused: name must not be empty'
    for i, o in enumerate(recs):
        o['name'] = nm if len(recs) == 1 else f'{nm} {i + 1}'
    return f'renamed {_span(recs)} to "{nm}"' + ('' if len(recs) == 1 else f' 1..{len(recs)}')


def t_group(d: Drawing, a, which='new', name=''):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    nm = str(name or '').strip()
    if not nm:
        return 'refused: name must not be empty — a group name is what the outliner shows'
    for o in recs:
        o['grp'] = nm
    return f'grouped {_span(recs)} as "{nm}"'


def t_hide(d: Drawing, a, which='new'):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    for o in recs:
        o['hidden'] = True
    d.ui.append({'cmd': 'hide', 'args': {'ids': [o['id'] for o in recs], 'hidden': True}})
    return f'hid {_span(recs)}'


def t_show(d: Drawing, a, which='all'):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    for o in recs:
        o['hidden'] = False
    d.ui.append({'cmd': 'hide', 'args': {'ids': [o['id'] for o in recs], 'hidden': False}})
    return f'showed {_span(recs)}'


def t_select_objects(d: Drawing, a, which='new'):
    recs = _pick(d, which)
    if not recs:
        return _none(which)
    ids = [o['id'] for o in recs]
    d.selected = ids
    d.ui.append({'cmd': 'focus', 'args': {'ids': ids}})
    return f'selected and focused {_span(recs)} around {_where(recs, d)}'


# ── registration ────────────────────────────────────────────────────────────
_WHICH = {
    'type': ['string', 'array'],
    'items': {'type': 'string'},
    'description': '"new", "all", a kind, a group name, or a list of ids',
}

TOOLS = [
    (
        {
            'name': 'move',
            'description': 'Shift objects that are already drawn by a number of grid cells east (dx_cells), south (dz_cells) and storeys up (dy_storeys). Negative numbers go west, north and down.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'dx_cells': {'type': 'number'},
                    'dz_cells': {'type': 'number'},
                    'dy_storeys': {'type': 'number'},
                },
                'required': ['which'],
            },
        },
        t_move,
    ),
    (
        {
            'name': 'move_to',
            'description': 'Move objects so that their centre lands on the centre of a cell, optionally putting their lowest storey on `storey`. Use when the user names the place rather than the offset.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'cell': {'type': 'string'}, 'storey': {'type': 'integer'}},
                'required': ['which', 'cell'],
            },
        },
        t_move_to,
    ),
    (
        {
            'name': 'rotate',
            'description': 'Turn objects by an angle in degrees about their own centre ("centre") or about a cell. Positions turn AND each wall turns on its own line. 0 degrees = east, 90 = north.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'degrees': {'type': 'number'},
                    'about': {'type': 'string', 'description': '"centre" or a cell like C4'},
                },
                'required': ['which', 'degrees'],
            },
        },
        t_rotate,
    ),
    (
        {
            'name': 'mirror',
            'description': 'Flip objects across a line through their centre or through a cell: axis "x" flips east-west, axis "z" flips north-south. Rotations are fixed so walls keep their line.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'axis': {'type': 'string', 'enum': ['x', 'z']},
                    'about': {'type': 'string'},
                },
                'required': ['which'],
            },
        },
        t_mirror,
    ),
    (
        {
            'name': 'array',
            'description': 'Repeat objects in a row: count is the TOTAL including the original, step_x_cells / step_z_cells / step_storeys is the gap between copies. Use for a terrace of houses, a run of columns, a row of trees.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': _WHICH,
                    'count': {'type': 'integer', 'minimum': 2, 'maximum': 200},
                    'step_x_cells': {'type': 'number'},
                    'step_z_cells': {'type': 'number'},
                    'step_storeys': {'type': 'number'},
                },
                'required': ['which', 'count'],
            },
        },
        t_array,
    ),
    (
        {
            'name': 'stack',
            'description': 'Copy objects upward, one storey per copy: count is how many EXTRA storeys are added above what is selected. Use to turn a finished ground floor into a block of flats.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'count': {'type': 'integer', 'minimum': 1, 'maximum': 200}},
                'required': ['which', 'count'],
            },
        },
        t_stack,
    ),
    (
        {
            'name': 'copy_to',
            'description': 'One copy of the selection, moved so its centre sits on a cell (and optionally its lowest storey on `storey`). The copy keeps the group and the materials.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'cell': {'type': 'string'}, 'storey': {'type': 'integer'}},
                'required': ['which', 'cell'],
            },
        },
        t_copy_to,
    ),
    (
        {
            'name': 'duplicate_storey',
            'description': 'Copy one whole storey of a group onto other storeys, names renumbered. Use for "make it five floors like the first one".',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'to_storeys': {'type': 'array', 'items': {'type': 'integer'}},
                },
                'required': ['group', 'storey', 'to_storeys'],
            },
        },
        t_duplicate_storey,
    ),
    (
        {
            'name': 'scale',
            'description': 'Resize objects about their centre: every length parameter (w, d, h, t, len, r, span, sill...) is multiplied by factor and the positions spread from the centre; the base stays on its storey. Counts and angles are untouched.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'factor': {'type': 'number'}},
                'required': ['which', 'factor'],
            },
        },
        t_scale,
    ),
    (
        {
            'name': 'set_param',
            'description': 'Set one parameter on objects that have it (len, w, d, h, t, r, sill, over, steps...). Objects without that parameter are left alone; if none has it the call is refused.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'key': {'type': 'string'}, 'value': {'type': ['number', 'string']}},
                'required': ['which', 'key', 'value'],
            },
        },
        t_set_param,
    ),
    (
        {
            'name': 'set_height',
            'description': 'Set the height of walls, columns, roofs and other objects with an h parameter, in storeys or in metres. Slabs and flat roofs have a thickness, not a height — use set_thickness for those.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'storeys': {'type': 'number'}, 'metres': {'type': 'number'}},
                'required': ['which'],
            },
        },
        t_set_height,
    ),
    (
        {
            'name': 'set_thickness',
            'description': 'Set the thickness t in metres of walls, partitions, slabs and roofs (0.24 is a Dutch cavity wall, 0.10 a partition, 0.22 a floor slab).',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 't': {'type': 'number'}},
                'required': ['which', 't'],
            },
        },
        t_set_thickness,
    ),
    (
        {
            'name': 'replace_kind',
            'description': 'Swap objects for another kind in place — wall to partition, window to window_arch, tree to tree_conifer. Position, rotation, material and any shared numbers are kept; params overrides the rest.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'kind': {'type': 'string'}, 'params': {'type': 'object'}},
                'required': ['which', 'kind'],
            },
        },
        t_replace_kind,
    ),
    (
        {
            'name': 'rename',
            'description': 'Rename objects for the outliner. One object gets the name, several get "name 1", "name 2"...',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'name': {'type': 'string'}},
                'required': ['which', 'name'],
            },
        },
        t_rename,
    ),
    (
        {
            'name': 'group',
            'description': 'Put objects in a named group so the outliner reads well and later tools can address them by that name.',
            'input_schema': {
                'type': 'object',
                'properties': {'which': _WHICH, 'name': {'type': 'string'}},
                'required': ['which', 'name'],
            },
        },
        t_group,
    ),
    (
        {
            'name': 'hide',
            'description': 'Hide objects in the viewport without deleting them (a roof hiding the plan, the site around a study).',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': ['which']},
        },
        t_hide,
    ),
    (
        {
            'name': 'show',
            'description': 'Show objects again; which defaults to "all", which unhides everything.',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': []},
        },
        t_show,
    ),
    (
        {
            'name': 'select_objects',
            'description': 'Select objects in the studio and move the camera to them, so the user sees exactly what was meant. Use it at the end when the user asked "where is..." or "show me...".',
            'input_schema': {'type': 'object', 'properties': {'which': _WHICH}, 'required': ['which']},
        },
        t_select_objects,
    ),
]

EXAMPLES = [
    {
        'ask': 'move the house two cells north and one east',
        'calls': [{'tool': 'move', 'args': {'which': 'new', 'dx_cells': 1, 'dz_cells': -2}}],
    },
    {
        'ask': 'turn that shed a quarter turn and put it on H12',
        'calls': [
            {'tool': 'rotate', 'args': {'which': 'shed', 'degrees': 90, 'about': 'centre'}},
            {'tool': 'move_to', 'args': {'which': 'shed', 'cell': 'H12'}},
        ],
    },
    {
        'ask': 'make it a terrace of five houses, 6 metres apart',
        'calls': [{'tool': 'array', 'args': {'which': 'new', 'count': 5, 'step_x_cells': 6}}],
    },
    {
        'ask': 'the ground floor is right — give it three more floors like it',
        'calls': [{'tool': 'stack', 'args': {'which': 'new', 'count': 3}}],
    },
    {
        'ask': 'the mirror image of that wing on the other side of C10',
        'calls': [{'tool': 'mirror', 'args': {'which': 'west wing', 'axis': 'x', 'about': 'C10'}}],
    },
    {
        'ask': 'those inner walls should be partitions, 10 cm thick, and 2.4 m high',
        'calls': [
            {'tool': 'replace_kind', 'args': {'which': 'inner walls', 'kind': 'partition'}},
            {'tool': 'set_thickness', 'args': {'which': 'inner walls', 't': 0.1}},
            {'tool': 'set_height', 'args': {'which': 'inner walls', 'metres': 2.4}},
        ],
    },
]

if len(PROMPT) > 900:
    raise RuntimeError(f'PROMPT is {len(PROMPT)} chars (max 900)')
_BASE = (
    'help',
    'get_state',
    'draw_box',
    'draw_wall',
    'add_slab',
    'add_roof',
    'add_windows',
    'add_opening',
    'add_object',
    'delete',
    'set_material',
    'look',
    'ask_user',
    'done',
)
if [t for t, _ in TOOLS if t['name'] in _BASE]:
    raise RuntimeError('a tool name collides with a base tool')
