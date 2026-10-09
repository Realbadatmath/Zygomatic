# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""organise_model — the assistant half of Organise ▸ components, storeys,
structural grid and rooms.

The six dock icons of arch_ext/organise_model.js (five tools and the
Room-labels switch, which is OFF by default) are declared pressable in
BUTTONS (the JS registrations all carry `assist: 1`, so both halves agree), and
each one has a server-side twin here for the work the model can do without a
canvas: make_component, place_component, add_storeys, draw_grid, add_zone. The
two pointer MODES (clicking a grid line's ends, clicking a room's corners) have
no twin beyond those tools — the model cannot click.

THE KINDS (parameters only, never geometry)
    component  {name, children:[{kind, p, x, y, z, rx, ry, rz, s, mat} …]}
    gridline   {len, label, axis}      a line on the plan: VOID, no solid
    zone       {pts:[[x, z] …], name, use, h}

DOCUMENT STATE lives in d.ext['organise_model'] = {'components': {name:
children}, 'storeys': [{'name', 'el', 'h'}]} — the same dict the tab keeps in
AR.doc.ext.organise_model, so a definition made in the browser is the one this
module edits and vice versa.

ONE HONEST DIFFERENCE. The tab computes a component's origin from the real
geometry (the selection's bounding box in x/z, its lowest point in y); this
module has no geometry, so make_component centres on the records' own x/z and
takes the lowest record y. For walls, slabs and columns — which are all centred
on their x/z — the two agree; for a kind whose mesh is not centred on its
record they differ by that offset, and the tool says so in its answer.

VOID_KINDS names `gridline` for the sweep in tests_arch_ext/test_all.py, which
keeps its own set and unions the modules' in.
"""

from __future__ import annotations

import copy
import math

from zyg_workflows.arch_assistant import Drawing, MATERIALS, MAX_OBJECTS, _num, cell_centre, cell_name, parse_cell

KINDS = {
    # a component with NO children has no body: add_object('component') would put
    # an invisible record in the drawing and Blender would build an empty mesh.
    # The default therefore carries one 1 m box — a kind every engine knows
    # (arch_blender_build.build_kind, this family's _child, and the tab's
    # arGeom case 'box') — which make_component and the browser then replace.
    'component': {
        'name': 'Component',
        'children': [
            {
                'kind': 'box',
                'p': {'w': 1.0, 'h': 1.0, 'd': 1.0},
                'x': 0.0,
                'y': 0.0,
                'z': 0.0,
                'ry': 0.0,
                's': 1,
                'mat': 'mat_concrete',
            }
        ],
    },
    'gridline': {'len': 30.0, 'label': 'A', 'axis': 'z'},
    'zone': {'pts': [[-2, -2], [2, -2], [2, 2], [-2, 2]], 'name': 'Room', 'use': 'living', 'h': 0.05},
}
OPENINGS: list = []
# a grid line is a line on the plan, not a solid — it is MEANT to have no mesh
VOID_KINDS = ['gridline']

BUTTONS = ['o_comp', 'o_browse', 'o_levels', 'o_gridlines', 'o_zones', 'o_zone_labels']

USES = [
    'living',
    'bedroom',
    'kitchen',
    'bathroom',
    'circulation',
    'office',
    'retail',
    'storage',
    'plant',
    'outdoor',
    'garden',
]

PROMPT = (
    'Organise the model: make_component(which, name) turns objects into ONE shared definition and '
    'place_component(name, cell, rotation_deg) drops instances that all rebuild together; '
    'add_storeys([{"name":"First","h":3.0}]) names the levels; draw_grid(letters, numbers, dx, dz, origin_cell) '
    'lays a structural grid columns snap to; add_zone(cells, name, use) outlines a room and labels its area. '
    'Icons o_comp, o_browse, o_levels, o_gridlines, o_zones; o_zone_labels is the switch that draws the room '
    'names over the plan (OFF by default — press_button("o_zone_labels", {"on": true}) when the person asks to '
    'see them). explain("organise model") has the detail.'
)


# ── state ───────────────────────────────────────────────────────────────────
def _ext(d: Drawing) -> dict:
    e = d.ext.get('organise_model')
    if not isinstance(e, dict):
        e = d.ext['organise_model'] = {}
    if not isinstance(e.get('components'), dict):
        e['components'] = {}
    if not isinstance(e.get('storeys'), list) or not e['storeys']:
        e['storeys'] = [{'name': 'Ground', 'el': 0.0, 'h': round(float(d.storey_h), 4)}]
    return e


def _children_of(o: dict) -> list:
    p = o.get('p') or {}
    return p['children'] if isinstance(p.get('children'), list) else []


def _instances(d: Drawing, name: str) -> list:
    return [o for o in d.objs if o['kind'] == 'component' and str((o.get('p') or {}).get('name') or '') == name]


def _shoelace(pts) -> float:
    s = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        s += a[0] * b[1] - b[0] * a[1]
    return abs(s) / 2.0


# ── components ──────────────────────────────────────────────────────────────
def t_make_component(d: Drawing, a, which='new', name=''):
    nm = str(name or '').strip()
    if not nm:
        return 'refused: a component needs a name'
    recs = d.select(which if which not in (None, '') else 'new')
    if not recs:
        return f'nothing matches "{which}" — pass "all", "new", a kind, a group name or ids'
    if len(recs) > 200:
        return f'refused: {len(recs)} objects is too many for one component — keep it under 200'
    xs = [o['x'] for o in recs]
    zs = [o['z'] for o in recs]
    cx = (min(xs) + max(xs)) / 2.0
    cz = (min(zs) + max(zs)) / 2.0
    gy = min(o['y'] for o in recs)
    kids = [
        {
            'kind': o['kind'],
            'p': copy.deepcopy(o.get('p') or {}),
            'x': round(o['x'] - cx, 4),
            'y': round(o['y'] - gy, 4),
            'z': round(o['z'] - cz, 4),
            'rx': o.get('rx', 0.0),
            'ry': o.get('ry', 0.0),
            'rz': o.get('rz', 0.0),
            's': o.get('s', 1) or 1,
            'mat': o.get('mat') or 'mat_concrete',
        }
        for o in recs
    ]
    grp = recs[0].get('grp') or ''
    e = _ext(d)
    e['components'][nm] = copy.deepcopy(kids)
    d.remove(recs)
    o = d.new(
        'component',
        {'name': nm, 'children': copy.deepcopy(kids)},
        cx,
        cz,
        gy,
        mat=recs[0].get('mat') or 'mat_concrete',
        name=nm,
        grp=grp,
    )
    d.selected = [o['id']]
    return (
        f'component "{nm}" = {o["id"]} at {cell_name(*_cell_of(cx, cz))} from {len(kids)} objects '
        f"(origin {cx:g}, {gy:g}, {cz:g} — the records' own centre, not their meshes'). "
        f'place_component("{nm}", cell) drops another instance.'
    )


def _cell_of(x, z):
    from zyg_workflows.arch_assistant import cell_of

    nm = cell_of(x, z)
    m = __import__('re').fullmatch(r'([A-Za-z]+)(\d+)', str(nm))
    if not m:
        return (0, 0)
    c = 0
    for ch in m.group(1).upper():
        c = c * 26 + (ord(ch) - 64)
    return (c - 1, int(m.group(2)) - 1)


def t_place_component(d: Drawing, a, name='', cell='A1', rotation_deg=0.0, storey=0):
    nm = str(name or '').strip()
    e = _ext(d)
    if nm not in e['components']:
        have = ', '.join(sorted(e['components'])) or 'none yet'
        return f'refused: no component called "{nm}" — the drawing has {have}'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    c, r = parse_cell(cell)
    x, z = cell_centre(c, r)
    st = int(_num(storey, 0))
    o = d.new(
        'component',
        {'name': nm, 'children': copy.deepcopy(e['components'][nm])},
        x,
        z,
        st * d.storey_h,
        math.radians(_num(rotation_deg, 0.0)),
        name=nm,
    )
    d.selected = [o['id']]
    n = len(_instances(d, nm))
    return (
        f'{o["id"]}: instance {n} of "{nm}" at {cell_name(c, r)} storey {st}, '
        f'turned {_num(rotation_deg, 0.0):g}deg ({len(e["components"][nm])} children)'
    )


# ── storeys ─────────────────────────────────────────────────────────────────
def t_add_storeys(d: Drawing, a, storeys=None):
    e = _ext(d)
    items = storeys if isinstance(storeys, list) else []
    if not items:
        return (
            'the drawing has '
            + ', '.join(
                f'{s["name"]} at {_num(s.get("el"), 0):g} m ({_num(s.get("h"), d.storey_h):g} m high)'
                for s in e['storeys']
            )
            + ' — pass storeys=[{"name":"First","h":3.0}] to add more'
        )
    added = []
    for it in items[:40]:
        if not isinstance(it, dict):
            continue
        nm = str(it.get('name') or f'Level {len(e["storeys"])}').strip()
        h = _num(it.get('h'), d.storey_h)
        if not 0.2 <= h <= 100:
            return f'refused: storey "{nm}" wants a height of {h:g} m — keep it between 0.2 and 100'
        if any(str(s.get('name')) == nm for s in e['storeys']):
            return f'refused: there is already a storey called "{nm}"'
        last = e['storeys'][-1]
        el = _num(it.get('el'), _num(last.get('el'), 0.0) + _num(last.get('h'), d.storey_h))
        e['storeys'].append({'name': nm, 'el': round(el, 4), 'h': round(h, 4)})
        added.append(f'{nm} at {el:g} m ({h:g} m)')
    e['storeys'].sort(key=lambda s: _num(s.get('el'), 0.0))
    if not added:
        return 'refused: storeys must be a list of {"name": ..., "h": ...} objects'
    return (
        'added '
        + '; '.join(added)
        + f'. The drawing now has {len(e["storeys"])} storeys: '
        + ', '.join(f'{s["name"]} {_num(s.get("el"), 0):g} m' for s in e['storeys'])
        + ". The dock's Level up/down arrows still step "
        + f'{d.storey_h:g} m — a storey of another height is reached from the storey sheet.'
    )


# ── the structural grid ─────────────────────────────────────────────────────
def _col_letters(c: int) -> str:
    s = ''
    while True:
        s = chr(65 + (c % 26)) + s
        c = c // 26 - 1
        if c < 0:
            return s


def _series(spec, dflt) -> list:
    s = str(dflt if spec in (None, '') else spec).strip()
    m = __import__('re').fullmatch(r'([A-Za-z]+|\d+)\s*-\s*([A-Za-z]+|\d+)', s)
    if m:
        a, b = m.group(1), m.group(2)
        if a.isdigit() and b.isdigit():
            return [str(i) for i in range(int(a), int(b) + 1)][:200]

        def idx(t):
            c = 0
            for ch in t.upper():
                c = c * 26 + (ord(ch) - 64)
            return c - 1

        return [_col_letters(c) for c in range(idx(a), idx(b) + 1)][:200]
    return [t for t in __import__('re').split(r'[,\s]+', s) if t][:200]


def t_draw_grid(d: Drawing, a, letters='A-F', numbers='1-8', dx=6.0, dz=6.0, origin_cell='A1', storey=0):
    ls, ns = _series(letters, 'A-F'), _series(numbers, '1-8')
    if not ls and not ns:
        return 'refused: a grid needs at least one line'
    ddx, ddz = _num(dx, 6.0), _num(dz, 6.0)
    if ddx <= 0.05 or ddz <= 0.05:
        return 'refused: grid spacing must be more than 0.05 m'
    if len(d.objs) + len(ls) + len(ns) > MAX_OBJECTS:
        return f'refused: that grid would pass the {MAX_OBJECTS}-object ceiling'
    c, r = parse_cell(origin_cell)
    x0, z0 = cell_centre(c, r)
    y = int(_num(storey, 0)) * d.storey_h
    span_x, span_z = (len(ls) - 1) * ddx, (len(ns) - 1) * ddz
    ids = []
    for i, lb in enumerate(ls):
        # a lettered line runs along +Z: ry = -pi/2 turns the record's local +X onto +Z
        o = d.new(
            'gridline',
            {'len': round(span_z + ddz, 4), 'label': str(lb), 'axis': 'z'},
            x0 + i * ddx,
            z0 + span_z / 2,
            y,
            -math.pi / 2,
            name=f'Grid {lb}',
            grp='grid',
        )
        ids.append(o['id'])
    for j, lb in enumerate(ns):
        o = d.new(
            'gridline',
            {'len': round(span_x + ddx, 4), 'label': str(lb), 'axis': 'x'},
            x0 + span_x / 2,
            z0 + j * ddz,
            y,
            0.0,
            name=f'Grid {lb}',
            grp='grid',
        )
        ids.append(o['id'])
    d.selected = ids
    return (
        f'{len(ids)} grid lines in group "grid": {len(ls)} lettered ({ls[0] if ls else "-"}..'
        f'{ls[-1] if ls else "-"}) at {ddx:g} m, {len(ns)} numbered ({ns[0] if ns else "-"}..'
        f'{ns[-1] if ns else "-"}) at {ddz:g} m, from {cell_name(c, r)}. In the tab their ends, '
        f"centres and crossings snap, from this family's own hook, whenever the matching "
        f'Precision switch (Endpoint / Midpoint / Intersection) is on.'
    )


# ── rooms and zones ─────────────────────────────────────────────────────────
def t_add_zone(d: Drawing, a, cells=None, name='Room', use='living', height=0.05, storey=0, material=''):
    cl = cells if isinstance(cells, list) else []
    if len(cl) < 3:
        return 'refused: a zone needs at least three corner cells, in order round the room'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at its {MAX_OBJECTS}-object ceiling'
    pts = []
    for cell in cl[:200]:
        c, r = parse_cell(cell)
        pts.append(list(cell_centre(c, r)))
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    cx, cz = (min(xs) + max(xs)) / 2.0, (min(zs) + max(zs)) / 2.0
    local = [[round(p[0] - cx, 4), round(p[1] - cz, 4)] for p in pts]
    u = str(use or 'living').strip().lower()
    nm = str(name or 'Room').strip() or 'Room'
    h = _num(height, 0.05)
    o = d.new(
        'zone',
        {'pts': local, 'name': nm, 'use': u, 'h': round(max(0.005, h), 4)},
        cx,
        cz,
        int(_num(storey, 0)) * d.storey_h,
        0.0,
        material if material in MATERIALS else None,
        name=nm,
        grp='zones',
    )
    d.selected = [o['id']]
    area = _shoelace(local)
    return (
        f'{o["id"]}: zone "{nm}" ({u}) over {len(local)} corners, {area:.2f} m2 '
        f'(shoelace of the cell centres), centred on {cell_name(*_cell_of(cx, cz))}. '
        f'Its label in the tab reads the same area.'
    )


_LIST = {'type': 'array', 'items': {'type': 'string'}}

TOOLS = [
    (
        {
            'name': 'make_component',
            'description': 'Turn objects into ONE component: a single record holding them as children, with a named shared '
            'definition. Use it when the user wants a repeated thing (a bay, a bathroom pod, a shopfront) that '
            'should change everywhere at once.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'which': {
                        'type': 'string',
                        'description': '"all", "new" (default), a kind, a group name, or an object id',
                    },
                    'name': {'type': 'string', 'description': 'the definition name every instance shares'},
                },
                'required': ['name'],
            },
        },
        t_make_component,
    ),
    (
        {
            'name': 'place_component',
            'description': 'Drop another instance of a named component on a cell. Every instance shares the definition, so '
            'editing it later changes all of them.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string'},
                    'cell': {'type': 'string'},
                    'rotation_deg': {'type': 'number'},
                    'storey': {'type': 'integer'},
                },
                'required': ['name', 'cell'],
            },
        },
        t_place_component,
    ),
    (
        {
            'name': 'add_storeys',
            'description': 'Name the levels of the building: each storey gets its own height and its elevation stacks on the '
            'one below. Call it with no argument to read the storeys the drawing already has.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'storeys': {
                        'type': 'array',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'name': {'type': 'string'},
                                'h': {'type': 'number'},
                                'el': {'type': 'number'},
                            },
                        },
                    }
                },
                'required': [],
            },
        },
        t_add_storeys,
    ),
    (
        {
            'name': 'draw_grid',
            'description': 'Lay a structural grid: lettered lines one way, numbered lines the other, at the spacings given. '
            'Draw it before the columns — their ends, centres and crossings snap in the tab.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'letters': {'type': 'string', 'description': 'e.g. "A-F" or "A,B,C"'},
                    'numbers': {'type': 'string', 'description': 'e.g. "1-8"'},
                    'dx': {'type': 'number', 'description': 'metres between the lettered lines'},
                    'dz': {'type': 'number', 'description': 'metres between the numbered lines'},
                    'origin_cell': {'type': 'string'},
                    'storey': {'type': 'integer'},
                },
                'required': [],
            },
        },
        t_draw_grid,
    ),
    (
        {
            'name': 'add_zone',
            'description': 'Outline a room or zone over the cells given (in order round the room) and label it with its own '
            'floor area in m2. Use it to schedule what the plan is for, not to build walls.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': _LIST,
                    'name': {'type': 'string'},
                    'use': {'type': 'string', 'enum': USES},
                    'height': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['cells', 'name'],
            },
        },
        t_add_zone,
    ),
]

EXAMPLES = [
    {
        'ask': 'make the two columns and the beam into a component called bay, then put another one on F4',
        'calls': [
            {'tool': 'make_component', 'args': {'which': 'new', 'name': 'bay'}},
            {'tool': 'place_component', 'args': {'name': 'bay', 'cell': 'F4'}},
        ],
    },
    {
        'ask': 'give me a 6 m grid, A to F and 1 to 8, from C3',
        'calls': [
            {'tool': 'draw_grid', 'args': {'letters': 'A-F', 'numbers': '1-8', 'dx': 6, 'dz': 6, 'origin_cell': 'C3'}}
        ],
    },
    {
        'ask': 'the first floor is 3 m high, add it',
        'calls': [{'tool': 'add_storeys', 'args': {'storeys': [{'name': 'First', 'h': 3.0}]}}],
    },
    {
        'ask': 'mark the hall between C3 and F6',
        'calls': [
            {'tool': 'add_zone', 'args': {'cells': ['C3', 'F3', 'F6', 'C6'], 'name': 'Hall', 'use': 'circulation'}}
        ],
    },
    {'ask': 'open the component browser', 'calls': [{'tool': 'press_button', 'args': {'id': 'o_browse'}}]},
]
