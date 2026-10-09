# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""cliffs_rocks — rock faces, boulders and rubble.

Six kinds: cliff, escarpment, boulder, rock_field, scree, sea_stack.

The noise below is the SAME arithmetic as arch_ext/cliffs_rocks.js and
arch_blender_ext/cliffs_rocks.py (all three copied verbatim from terrain). It
lives here too so the assistant — and the test — can say how big a rock really
is without rendering it: cliff_z_size(), boulder_bbox(), rock_field_bbox() and
sea_stack_bbox() predict the bounding boxes the tab must produce.

GROUND (2026-09-07). Every tool lands its record on the ground under it —
base_height defaults to None and means "whatever is there". cliff, escarpment,
scree and sea_stack are themselves GROUND: they export HEIGHTS, so a boulder
dropped on a cliff edge stands on the cliff top instead of 15 m below it.
boulder and rock_field export a height of None — you do not stand on a rock.

Two sampling rules follow from that:
  · a cliff / escarpment / scree asks the ground with the family's own rock
    faces taken OUT (_without_rock). Otherwise the second cliff of a chain
    stands on the first one at the corner where their footprints overlap, and
    the scree at a cliff's foot climbs onto the cliff top.
  · a boulder / rock field / sea stack asks the FULL ground, cliffs included —
    that is the whole point of a rock sitting on the edge.

REAL SIZES (R7) are absolute and never scale with the block: a cliff is 3-60 m,
an escarpment 3-80 m, a boulder 0.3-4 m ACROSS (`size` is the diameter now, not
the radius), a rock field's `size` is its LARGEST boulder's diameter.

SCULPTED GROUND (v3, 2026-09-07). When the drawing has a `ground` record a rock
FACE is no longer a solid standing on the land — it is a parameter OF the land.
add_cliff lays one `sculpt_step` per consecutive pair and add_escarpment lays one
`sculpt_step` with a wide feather on its back, so the ground itself steps up and
a valley reads as a valley instead of a plinth. Only the faces convert: boulders,
rock fields, scree and sea stacks stay solids and drape on the new ground by the
same seam as before. With no `ground` record every tool draws exactly what it
drew yesterday.

The step's raised side is its local +Z, and on the sculpt path the tool turns each
record so that side is on the LEFT of the walk cell_i -> cell_i+1 — the high
ground is on your left, the fall on your right. (The old SOLID cliff is turned
the other way, drop on the left; that is the old path and it is unchanged.)
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    block_bounds,
    MATERIALS,
    MAX_OBJECTS,
    _num,
    ground_height,
    ground_plane,
    place_height,
)

KINDS = {
    'cliff': {'len': 40, 'h': 15, 'd': 12, 'rug': 0.35, 'seed': 1, 'res': 24, 'ledge': 1},
    'escarpment': {'len': 60, 'h': 20, 'd': 40, 'rug': 0.3, 'seed': 1, 'res': 24, 'ledge': 1},
    'boulder': {'r': 1.5, 'rug': 0.35, 'seed': 1, 'seg': 12},
    'rock_field': {'w': 30, 'd': 30, 'count': 20, 'size': 1.2, 'seed': 1, 'rug': 0.35, 'gx': 0, 'gz': 0},
    'scree': {'len': 30, 'w': 12, 'h': 6},
    'sea_stack': {'r': 6, 'h': 25, 'rug': 0.3, 'seed': 1, 'seg': 24, 'rings': 10},
}
OPENINGS: list = []

PROMPT = (
    'Cliffs and rock: everything here lands on the ground under it and base_height '
    'overrides that. add_cliff(cells, height, depth) draws a rock face along a chain of cells, one cliff per '
    'consecutive pair, walked with the drop on your left; it steps with the ground. '
    'A cliff line is usually drawn ON the plateau edge: draw the plateau, then '
    'add_cliff with base_height omitted. Cliffs are 3-60 m tall, escarpments 3-80 m. '
    'With a sculpted ground (make_ground) add_cliff and add_escarpment step THE GROUND ITSELF, not a '
    'solid on it, the HIGH side on your left; boulders, rock fields, scree and sea stacks stay solids on it. '
    'add_escarpment(cell_from, cell_to, height, direction) fills a block with a tilted plateau whose face looks '
    "'north', 'south', 'east' or 'west'. add_boulder(centre, size) is one rock: "
    'size is the DIAMETER across, 0.3-4 m. scatter_rocks(cell_from, cell_to, count, size) '
    'strews stony ground draped over the slope (size = the LARGEST boulder). '
    'add_scree(cells, height, width) piles rubble at a cliff foot, leaning left. '
    'add_sea_stack(centre, radius, height) stands a rock column in water.'
)


# ── the shared noise (identical in the JS and the Blender copies) ────────────
def _hash(ix: float, iy: float, seed: float) -> float:
    v = math.sin(ix * 127.1 + iy * 311.7 + seed * 74.7) * 43758.5453
    return v - math.floor(v)


def value_noise(u: float, v: float, seed: float) -> float:
    ix, iy = math.floor(u), math.floor(v)
    fx, fy = u - ix, v - iy
    a = _hash(ix, iy, seed)
    b = _hash(ix + 1, iy, seed)
    c = _hash(ix, iy + 1, seed)
    e = _hash(ix + 1, iy + 1, seed)
    return a + (b - a) * fx + (c - a) * fy + (a - b - c + e) * fx * fy


# ── what the geometry will measure ──────────────────────────────────────────
def cliff_z_size(d: float = 12.0, rug: float = 0.35, res: int = 24, seed: float = 1) -> float:
    """Depth of the bounding box of a cliff/escarpment: the back is at +d/2 and
    the roughest point of the face reaches -d/2 - rug + 2*rug*min(noise)."""
    res = max(2, min(64, int(round(res))))
    lo = min(value_noise(i / res * 3, j / res * 3, seed) for j in range(res + 1) for i in range(res + 1))
    return d + rug * (1 - 2 * lo)


def boulder_verts(r: float, rug: float, seed: float, seg: int, rings: int) -> list:
    """The boulder's vertices in the record's local frame, lowest one at y=0."""

    def R(u, v):
        return r * (1 + rug * (2 * value_noise(u * 3, v * 3, seed) - 1))

    pts = [(0.0, R(0.0, 0.0), 0.0)]
    for j in range(1, rings):
        v = j / rings
        phi = math.pi * v
        for i in range(seg):
            u = i / seg
            th = 2 * math.pi * u
            rad = R(u, v)
            pts.append((rad * math.sin(phi) * math.cos(th), rad * math.cos(phi), -rad * math.sin(phi) * math.sin(th)))
    pts.append((0.0, -R(0.0, 1.0), 0.0))
    lo = min(q[1] for q in pts)
    return [(q[0], q[1] - lo, q[2]) for q in pts]


def _bbox(pts: list) -> tuple:
    xs = [q[0] for q in pts]
    ys = [q[1] for q in pts]
    zs = [q[2] for q in pts]
    return (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))


def boulder_bbox(r: float = 1.5, rug: float = 0.35, seed: float = 1, seg: int = 12) -> tuple:
    seg = max(6, min(48, int(round(seg))))
    return _bbox(boulder_verts(r, rug, seed, seg, max(2, int(round(seg / 2)))))


def field_radius(n: int, size: float, seed: float) -> float:
    """The radius of boulder n in a rock field. `size` is the LARGEST boulder's
    DIAMETER, so a radius runs from 0.2*size to 0.5*size — a 'size 3' field
    holds 1.2 to 3 m rocks, never the 11 m ones the old size*(0.5+hash) gave."""
    return size / 2.0 * (0.4 + 0.6 * _hash(n, 3, seed))


def field_is_stone(n: int, seed: float) -> bool:
    """30 % of a field's boulders are the lighter mat_stone, so it is not one grey."""
    return _hash(n, 4, seed) < 0.3


def rock_field_bbox(
    w: float = 30.0,
    d: float = 30.0,
    count: int = 20,
    size: float = 1.2,
    seed: float = 1,
    rug: float = 0.35,
    gx: float = 0.0,
    gz: float = 0.0,
) -> tuple:
    count = max(1, min(400, int(round(count))))
    pts = []
    for n in range(count):
        rr = field_radius(n, size, seed)
        px = -w / 2 + _hash(n, 1, seed) * w
        pz = -d / 2 + _hash(n, 2, seed) * d
        dy = gx * px + gz * pz
        for q in boulder_verts(rr, rug, seed + n + 1, 8, 4):
            pts.append((q[0] + px, q[1] + dy, q[2] + pz))
    return _bbox(pts)


def sea_stack_bbox(
    r: float = 6.0, h: float = 25.0, rug: float = 0.3, seed: float = 1, seg: int = 24, rings: int = 10
) -> tuple:
    seg = max(6, min(64, int(round(seg))))
    rings = max(2, min(48, int(round(rings))))
    pts = []
    for j in range(rings + 1):
        v = j / rings
        for i in range(seg):
            u = i / seg
            th = 2 * math.pi * u
            rad = r * (1 + rug * (2 * value_noise(u * 3, v * 3, seed) - 1))
            pts.append((rad * math.cos(th), h * v, -rad * math.sin(th)))
    pts.append((0.0, h, 0.0))
    pts.append((0.0, 0.0, 0.0))
    return _bbox(pts)


# ── ground heights (the seam, 2026-09-07) ───────────────────────────────────
# fn(p, lx, lz) -> metres above the record's base at a LOCAL plan point, or None
# outside the footprint. Same arithmetic as the geometry in arch_ext/cliffs_rocks.js.
def h_cliff(p, lx, lz):
    """The cliff TOP: h everywhere behind the face over the depth d. The face
    band itself (the rug metres in front of -d/2) counts as h too, so a thing
    put right on the edge sits on the ledge and not at its foot."""
    ln, h, dep = _num(p.get('len'), 40.0), _num(p.get('h'), 15.0), _num(p.get('d'), 12.0)
    rug = max(0.0, _num(p.get('rug'), 0.35))
    if abs(lx) > ln / 2 + 1e-9:
        return None
    if lz > dep / 2 + 1e-9 or lz < -dep / 2 - rug - 1e-9:
        return None
    return h


def h_escarpment(p, lx, lz):
    """h at the front edge (the face), falling linearly to 0 at the back."""
    ln, h, dep = _num(p.get('len'), 60.0), _num(p.get('h'), 20.0), _num(p.get('d'), 40.0)
    rug = max(0.0, _num(p.get('rug'), 0.3))
    if abs(lx) > ln / 2 + 1e-9 or lz > dep / 2 + 1e-9:
        return None
    if lz < -dep / 2:
        return h if lz >= -dep / 2 - rug - 1e-9 else None
    return h * (dep / 2 - lz) / dep


def h_scree(p, lx, lz):
    """The wedge surface: h at the -Z edge (against the rock), 0 at +Z."""
    ln, w, h = _num(p.get('len'), 30.0), _num(p.get('w'), 12.0), _num(p.get('h'), 6.0)
    if abs(lx) > ln / 2 + 1e-9 or abs(lz) > w / 2 + 1e-9:
        return None
    return h * (w / 2 - lz) / w


def h_sea_stack(p, lx, lz):
    """h on the flat top disc, whose radius wanders with the same noise."""
    r, h = _num(p.get('r'), 6.0), _num(p.get('h'), 25.0)
    rug = max(0.0, min(0.9, _num(p.get('rug'), 0.3)))
    rad = math.hypot(lx, lz)
    if rad > r * (1 + rug) + 1e-9:
        return None
    if rad <= 1e-9:
        return h
    th = math.atan2(-lz, lx) % (2 * math.pi)  # geometry: (rad cos th, y, -rad sin th)
    u = th / (2 * math.pi)
    top = r * (1 + rug * (2 * value_noise(u * 3, 3.0, _num(p.get('seed'), 1)) - 1))
    return h if rad <= top else None


def h_boulder(p, lx, lz):
    """You do not stand on a boulder."""
    return None


def h_rock_field(p, lx, lz):
    """Nor on a field of them."""
    return None


HEIGHTS = {
    'cliff': h_cliff,
    'escarpment': h_escarpment,
    'scree': h_scree,
    'sea_stack': h_sea_stack,
    'boulder': h_boulder,
    'rock_field': h_rock_field,
}


# ── plumbing ────────────────────────────────────────────────────────────────
_DIR_RY = {'north': 0.0, 'south': math.pi, 'east': -math.pi / 2, 'west': math.pi / 2}
_ROCK_FACES = ('cliff', 'escarpment', 'scree', 'sculpt_step')
TILE_M = 25.0  # a draped block is cut into tiles no bigger than this
MAX_TILES = 64


def the_ground(d):
    """The drawing's one `ground` record, or None. A hidden ground is no ground:
    hiding it in the outliner puts every tool back on the old solid path."""
    for o in getattr(d, 'objs', None) or ():
        if o.get('kind') == 'ground' and not o.get('hidden'):
            return o
    return None


def _mat(m, default='mat_rock'):
    return m if m in MATERIALS else default


def _given(base_height) -> bool:
    return not (base_height is None or base_height == '')


class _without_rock:
    """Sample the ground with this family's own rock FACES hidden. A cliff must
    not stand on the cliff beside it (their footprints overlap at every corner
    of a chain) and scree lies at a cliff's foot, not on its ledge. On a v3
    ground the faces are `sculpt_step` records, so those are hidden too — hiding
    a sculpt takes its feature out of the heightfield, which is exactly the
    'ground as it would be without the rock' the placement wants."""

    def __init__(self, d):
        self.marked = [o for o in d.objs if o['kind'] in _ROCK_FACES and not o.get('hidden')]

    def __enter__(self):
        for o in self.marked:
            o['hidden'] = True
        return self

    def __exit__(self, *a):
        for o in self.marked:
            o['hidden'] = False
        return False


def _pairs(cells):
    """[(x, z), ...] for a list of cells, or a refusal string."""
    if not isinstance(cells, (list, tuple)) or len(cells) < 2:
        return 'refused: give a list of at least two cells — one length of rock is drawn between each pair'
    return [cell_centre(*parse_cell(c)) for c in cells]


def _chain(d, cells, kind, p_of, mat, grp, label, base_height):
    """One record per consecutive pair, turned so the record's -Z (its rock
    face) sits on the LEFT of the walk cell_i -> cell_i+1 (R4): the record's y
    is the ground at the reach CENTRE and rz = atan(rise / run) so the rock
    steps down a falling slope with the ground it stands on."""
    pts = _pairs(cells)
    if isinstance(pts, str):
        return pts, None
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling', None
    for i in range(need):
        if math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) < 0.5:
            return (
                f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a rock face needs two different cells'
            ), None
    # every height is sampled BEFORE a single record exists, so the chain never
    # climbs onto itself at a corner
    if _given(base_height):
        y0 = _num(base_height, 0.0)
        seats = [(y0, 0.0, 0.0) for _ in range(need)]
    else:
        seats = []
        with _without_rock(d):
            for i in range(need):
                (x0, z0), (x1, z1) = pts[i], pts[i + 1]
                L = math.hypot(x1 - x0, z1 - z0)
                ya, yb = ground_height(d, x0, z0), ground_height(d, x1, z1)
                seats.append(
                    (round(ground_height(d, (x0 + x1) / 2, (z0 + z1) / 2), 4), math.atan2(yb - ya, L), yb - ya)
                )
    ids, total, fall = [], 0.0, 0.0
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        ry = math.atan2(-(z1 - z0), x1 - x0)
        y, rz, drop = seats[i]
        o = d.new(kind, p_of(L), (x0 + x1) / 2, (z0 + z1) / 2, y, ry, mat, name=f'{label} {i + 1}', grp=grp)
        o['rz'] = round(rz, 6)
        ids.append(o['id'])
        total += L
        fall += drop
    return '', (ids, total, fall, seats[0][0])


def step_ry(x0, z0, x1, z1) -> float:
    """The `ry` that puts a sculpt_step's RAISED side (its local +Z) on the LEFT
    of the walk (x0, z0) -> (x1, z1). THREE sends local +Z to world
    (sin ry, cos ry); left of a heading (dx, dz) on the plan is (dz, -dx); so
    ry = atan2(dz, -dx), which is the old solid cliff's ry turned by pi."""
    return math.atan2(z1 - z0, -(x1 - x0))


def step_feather(L: float, dep: float) -> float:
    """How far a cliff step's rim melts into the land — the same distance at the
    ends of the run and down its back, never more than a quarter of the run nor
    half the depth."""
    return round(max(0.25, min(L / 4.0, dep / 2.0)), 4)


def _sculpt_chain(d, cells, p_of, fe_of, grp, label):
    """One `sculpt_step` per consecutive pair, each turned so the ground on the
    LEFT of the walk is the high side. The records carry y = 0: a sculpt is a
    parameter of the one ground, so it LIFTS the land by h wherever it runs
    rather than standing at some height of its own.

    Raises ADD, so a chain must overlap by EXACTLY one feather and no more: each
    record is `L + fe` long and pushed fe/2 FORWARD along its own walk, which
    puts its falling rim on top of the next record's rising rim. The two are
    smoothstep(1-t) and smoothstep(t) over the same fe metres and sum to one, so
    the joint is neither a notch nor a double-height bump."""
    pts = _pairs(cells)
    if isinstance(pts, str):
        return pts, None
    need = len(pts) - 1
    if len(d.objs) + need > MAX_OBJECTS:
        return f'refused: that is {need} objects past the {MAX_OBJECTS} ceiling', None
    for i in range(need):
        if math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) < 0.5:
            return (
                f'refused: {cells[i]} and {cells[i + 1]} are the same cell — a rock face needs two different cells'
            ), None
    ids, total = [], 0.0
    for i in range(need):
        (x0, z0), (x1, z1) = pts[i], pts[i + 1]
        L = math.hypot(x1 - x0, z1 - z0)
        fe = fe_of(L)
        ux, uz = (x1 - x0) / L, (z1 - z0) / L
        o = d.new(
            'sculpt_step',
            p_of(L, fe),
            (x0 + x1) / 2 + fe / 2 * ux,
            (z0 + z1) / 2 + fe / 2 * uz,
            0.0,
            step_ry(x0, z0, x1, z1),
            'mat_rock',
            name=f'{label} {i + 1}',
            grp=grp,
        )
        ids.append(o['id'])
        total += L
    return '', (ids, total)


def _run_note(total, fall):
    if abs(fall) < 0.05:
        return ''
    return f', running {"downhill" if fall < 0 else "uphill"} {abs(fall):.1f} m over {total:.0f} m'


def _tiles(d, cx, cz, W, D, cap=MAX_TILES):
    """[(tx, tz, tw, td, y, glx, glz)] over the block, halved again and again
    until every tile's ground is planar to 1 m (R2), `cap` tiles at most (never
    more than there are boulders to put in them)."""
    cap = max(1, min(MAX_TILES, int(cap)))
    nx = max(1, int(math.ceil(W / TILE_M)))
    nz = max(1, int(math.ceil(D / TILE_M)))
    while True:
        tiles, worst = [], 0.0
        tw, td = W / nx, D / nz
        for j in range(nz):
            for i in range(nx):
                tx = cx - W / 2 + (i + 0.5) * tw
                tz = cz - D / 2 + (j + 0.5) * td
                y0, glx, glz, spread = ground_plane(d, tx, tz, tw, td, 0.0)
                tiles.append((tx, tz, tw, td, y0, glx, glz))
                worst = max(worst, spread)
        if worst <= 1.0 or nx * nz * 4 > cap:
            return tiles
        nx, nz = nx * 2, nz * 2


# ── tools ───────────────────────────────────────────────────────────────────
def t_add_cliff(
    d: Drawing, a, cells, height=15.0, depth=12.0, ruggedness=0.35, seed=1, base_height=None, material='', name=''
):
    h = _num(height, 15.0)
    dep = _num(depth, 12.0)
    rug = max(0.0, _num(ruggedness, 0.35))
    if h < 3.0 or h > 60.0:
        return (
            'refused: a cliff is 3 to 60 m tall — under 3 m use add_retaining_wall or a berm, '
            'over 60 m use add_escarpment (3-80 m) or a mountain'
        )
    if dep < 1:
        return 'refused: depth must be at least 1 m — the rock has to run back somewhere'
    sd = _num(seed, 1)
    grp = name or 'cliffs'

    if the_ground(d) is not None:

        def p_step(L, fe):
            return {
                'len': round(L + fe, 4),
                'h': round(h, 3),
                'd': round(2 * dep, 4),
                'rug': round(rug, 3),
                'seed': sd,
                'feather': fe,
            }

        err, got = _sculpt_chain(d, cells, p_step, lambda L: step_feather(L, dep), grp, name or 'cliff')
        if err:
            return err
        ids, total = got
        return (
            f'stepped the ground up {h:g} m along {", ".join(str(c) for c in cells)}: '
            f'{len(ids)} sculpt_step(s) {ids[0]}..{ids[-1]}, {total:.1f} m of rock face, the '
            f'lifted bench running {dep:g} m back, ruggedness {rug:g} — the HIGH ground is on '
            f'your left walking the cells, the fall on your right. This is the one ground '
            f'sculpted, not a solid on it, so a valley beside it stays a valley'
            + (' (base_height does not apply to a sculpted ground)' if _given(base_height) else '')
        )

    def p_of(L):
        return {
            'len': round(L, 4),
            'h': round(h, 3),
            'd': round(dep, 3),
            'rug': round(rug, 3),
            'seed': sd,
            'res': 24,
            'ledge': 1,
        }

    err, got = _chain(d, cells, 'cliff', p_of, _mat(material), grp, name or 'cliff', base_height)
    if err:
        return err
    ids, total, fall, y = got
    return (
        f'drew {len(ids)} cliff(s) {ids[0]}..{ids[-1]} along {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m of rock face, {h:g} m tall, {dep:g} m deep, ruggedness {rug:g}, '
        f'foot on the ground at {y:g} m{_run_note(total, fall)} — the drop is on your left '
        f'walking the cells'
    )


def t_add_escarpment(
    d: Drawing,
    a,
    cell_from,
    cell_to,
    height=20.0,
    direction='north',
    ruggedness=0.3,
    seed=1,
    ledge=1.0,
    base_height=None,
    material='',
    name='',
):
    dr = str(direction or 'north').strip().lower()
    if dr not in _DIR_RY:
        return "refused: direction must be 'north', 'south', 'east' or 'west' — the way the rock face looks"
    h = _num(height, 20.0)
    if h < 3.0 or h > 80.0:
        return (
            'refused: an escarpment is 3 to 80 m tall — under 3 m it is a bank or a berm, '
            'over 80 m it is a mountain flank'
        )
    rug = max(0.0, _num(ruggedness, 0.3))
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    # the face looks along the record's -Z, so `d` is the block side along the
    # direction and `len` the side across it
    ln, dep = (W, D) if dr in ('north', 'south') else (D, W)
    if dep < 1:
        return 'refused: depth must be at least 1 m — give the escarpment more cells to fall back over'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    ry = _DIR_RY[dr]
    if the_ground(d) is not None:
        # one step whose face sits on the block edge the face LOOKS out of, and
        # whose back feather is the whole lifted depth: h at the face falling
        # smoothly to the surrounding land dep metres behind it.
        fx = cx - dep / 2 * math.sin(ry)
        fz = cz - dep / 2 * math.cos(ry)
        o = d.new(
            'sculpt_step',
            {
                'len': round(ln + 2 * dep, 4),
                'h': round(h, 3),
                'd': round(2 * dep, 4),
                'rug': round(rug, 3),
                'seed': _num(seed, 1),
                'feather': round(dep, 4),
            },
            fx,
            fz,
            0.0,
            ry,
            'mat_rock',
            name=name or f'escarpment {cell_name(*parse_cell(cell_from))}',
            grp=name or 'escarpments',
        )
        return (
            f'sculpted escarpment {o["id"]} into the ground over '
            f'{cell_name(*parse_cell(cell_from))}..{cell_name(*parse_cell(cell_to))}: '
            f'{ln:g} m of face looking {dr}, the land {h:g} m up at the face and feathering '
            f'back down to the surrounding ground over {dep:g} m — one sculpt_step on the one '
            f'ground, not a solid standing on it'
            + (' (base_height and ledge do not apply to a sculpted ground)' if _given(base_height) else '')
        )
    if _given(base_height):
        y = _num(base_height, 0.0)
    else:
        with _without_rock(d):
            y = place_height(d, cx, cz, None)
    lg = max(0.0, min(_num(ledge, 1.0), dep * 0.5))
    o = d.new(
        'escarpment',
        {
            'len': round(ln, 4),
            'h': round(h, 3),
            'd': round(dep, 4),
            'rug': round(rug, 3),
            'seed': _num(seed, 1),
            'res': 24,
            'ledge': round(lg, 3),
        },
        cx,
        cz,
        y,
        ry,
        _mat(material),
        name=name or f'escarpment {cell_name(*parse_cell(cell_from))}',
        grp=name or 'escarpments',
    )
    return (
        f'drew escarpment {o["id"]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))}: {ln:g} m of face looking {dr}, {h:g} m tall, '
        f'the tilted top falling {dep:g} m back to the ground, a {lg:g} m grass strip on the '
        f'top edge, foot on the ground at {y:g} m'
    )


def t_add_boulder(d: Drawing, a, centre, size=1.5, seed=1, base_height=None, material='', name=''):
    dia = _num(size, 1.5)
    if dia < 0.3:
        return (
            'refused: a boulder is 0.3 to 4 m across — size is the DIAMETER; '
            'anything smaller is gravel, use scatter_rocks or add_scree'
        )
    if dia > 4.0:
        return (
            'refused: a boulder over 4 m is a rock outcrop — use add_sea_stack or a mesa '
            '(a boulder is 0.3 to 4 m across)'
        )
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = cell_centre(*parse_cell(centre))
    cn = cell_name(*parse_cell(centre))
    y = place_height(d, cx, cz, base_height)
    o = d.new(
        'boulder',
        {'r': round(dia / 2.0, 4), 'rug': 0.35, 'seed': _num(seed, 1), 'seg': 12},
        cx,
        cz,
        y,
        0.0,
        _mat(material),
        name=name or f'boulder {cn}',
        grp=name or 'rocks',
    )
    return f'drew boulder {o["id"]} on {cn}: {dia:g} m across, sitting on the ground at {y:g} m'


def t_scatter_rocks(
    d: Drawing, a, cell_from, cell_to, count=20, size=1.2, seed=1, base_height=None, material='', name=''
):
    n = int(_num(count, 20))
    if n < 1:
        return 'refused: count must be at least 1'
    if n > 400:
        return 'refused: count must be 400 or fewer rocks in one field'
    sz = _num(size, 1.2)
    if sz < 0.3 or sz > 4.0:
        return (
            'refused: size is the LARGEST boulder across and a boulder is 0.3 to 4 m — '
            'bigger is an outcrop (add_sea_stack), smaller is gravel (add_scree)'
        )
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)
    W, D = xmax - xmin, zmax - zmin
    cx, cz = (xmin + xmax) / 2, (zmin + zmax) / 2
    if _given(base_height):
        tiles = [(cx, cz, W, D, _num(base_height, 0.0), 0.0, 0.0)]
    else:
        tiles = _tiles(d, cx, cz, W, D, cap=n)  # never a tile with no rocks in it
    if len(d.objs) + len(tiles) > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    per, extra = divmod(n, len(tiles))
    grp = name or 'rocks'
    ids = []
    for i, (tx, tz, tw, td, y, glx, glz) in enumerate(tiles):
        cnt = per + (1 if i < extra else 0)
        o = d.new(
            'rock_field',
            {
                'w': round(tw, 4),
                'd': round(td, 4),
                'count': cnt,
                'size': round(sz, 3),
                'seed': _num(seed, 1) + i,
                'rug': 0.35,
                'gx': round(glx, 5),
                'gz': round(glz, 5),
            },
            tx,
            tz,
            round(y, 4),
            0.0,
            _mat(material),
            name=(name or 'rocks') + (f' {i + 1}' if len(tiles) > 1 else f' {cell_name(*parse_cell(cell_from))}'),
            grp=grp,
        )
        ids.append(o['id'])
    slope = math.hypot(tiles[0][5], tiles[0][6])
    return (
        f'strewed {n} boulders {ids[0]}..{ids[-1]} over {cell_name(*parse_cell(cell_from))}..'
        f'{cell_name(*parse_cell(cell_to))}: {W:g} x {D:g} m, the largest {sz:g} m across, '
        f'in {len(tiles)} tile(s) draped on the ground'
        f'{f" (1:{1 / slope:.0f} slope)" if slope > 0.01 else ""}, '
        f'each rock standing upright at {tiles[0][4]:g} m and up'
    )


def t_add_scree(d: Drawing, a, cells, height=6.0, width=12.0, base_height=None, material='', name=''):
    h = _num(height, 6.0)
    if h < 0.5 or h > 40.0:
        return 'refused: a scree slope is 0.5 to 40 m tall — that is the top of the pile against the rock'
    w = _num(width, 12.0)
    if w < 1:
        return 'refused: width must be at least 1 m — that is how far the rubble spreads out'
    grp = name or 'scree'

    def p_of(L):
        return {'len': round(L, 4), 'w': round(w, 3), 'h': round(h, 3)}

    err, got = _chain(d, cells, 'scree', p_of, _mat(material, 'mat_gravel'), grp, name or 'scree', base_height)
    if err:
        return err
    ids, total, fall, y = got
    return (
        f'piled {len(ids)} scree slope(s) {ids[0]}..{ids[-1]} along {", ".join(str(c) for c in cells)}: '
        f'{total:.1f} m long, {h:g} m tall against the rock on your left, spreading {w:g} m out, '
        f'foot on the ground at {y:g} m{_run_note(total, fall)}'
    )


def t_add_sea_stack(d: Drawing, a, centre, radius=6.0, height=25.0, seed=1, base_height=None, material='', name=''):
    r = _num(radius, 6.0)
    if r < 0.5 or r > 30.0:
        return 'refused: a sea stack is 0.5 to 30 m in radius — wider is an island, use a mesa'
    h = _num(height, 25.0)
    if h < 3.0 or h > 80.0:
        return 'refused: a sea stack is 3 to 80 m tall — shorter is a boulder, taller is a mountain'
    if len(d.objs) + 1 > MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    cx, cz = cell_centre(*parse_cell(centre))
    cn = cell_name(*parse_cell(centre))
    y = place_height(d, cx, cz, base_height)
    o = d.new(
        'sea_stack',
        {'r': round(r, 3), 'h': round(h, 3), 'rug': 0.3, 'seed': _num(seed, 1), 'seg': 24, 'rings': 10},
        cx,
        cz,
        y,
        0.0,
        _mat(material),
        name=name or f'sea stack {cn}',
        grp=name or 'sea stacks',
    )
    return f'stood sea stack {o["id"]} on {cn}: {2 * r:g} m across, {h:g} m tall, base on the ground at {y:g} m'


_BASE = {
    'type': 'number',
    'description': 'metres the foot of the rock sits at. LEAVE IT OUT and the rock lands on '
    'the ground under it (a plateau, a hill, a slope); give a number to force it',
}

TOOLS = [
    (
        {
            'name': 'add_cliff',
            'description': 'A rugged rock face along a chain of cells: one length of rock per consecutive pair (3 cells = 2 lengths). height is the face from foot to ledge (3-60 m), depth how far the rock runs back. On a sculpted ground (make_ground) it lifts the LAND itself by height, with the high ground on your LEFT walking the cells; with no ground it draws the old solid, which lands on whatever is under it and steps down a falling run. Use for a cliff edge, a quarry face, the rock under a castle.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'depth': {'type': 'number'},
                    'ruggedness': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_cliff,
    ),
    (
        {
            'name': 'add_escarpment',
            'description': "A tilted plateau with a rock face over a block of cells: height tall at the face (3-80 m), sloping down to the ground at the back, with a grass strip along the top edge. direction is the way the face LOOKS ('north' = up the plan). On a sculpted ground (make_ground) it lifts the LAND itself, height up at the face and feathering back down to the surrounding ground over the block; with no ground it draws the old solid on whatever is under it. Use for a ridge edge, a scarp, high ground falling away.",
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'height': {'type': 'number'},
                    'direction': {'type': 'string', 'enum': ['north', 'south', 'east', 'west']},
                    'ruggedness': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'ledge': {
                        'type': 'number',
                        'description': 'width in metres of the grass strip on the top edge (0 = bare rock)',
                    },
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_add_escarpment,
    ),
    (
        {
            'name': 'add_boulder',
            'description': 'One rock sitting on the ground at a cell. size is the DIAMETER across and a real boulder is 0.3 to 4 m — anything bigger is an outcrop or a sea stack. It lands on the ground under it, cliff tops included. Use for an erratic, a rock in a garden; change seed for a differently shaped lump.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'size': {'type': 'number', 'description': 'the boulder DIAMETER in metres, 0.3 to 4'},
                    'seed': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_boulder,
    ),
    (
        {
            'name': 'scatter_rocks',
            'description': 'count boulders strewn over a block of cells (400 at most). size is the LARGEST boulder DIAMETER, 0.3 to 4 m; the rest are smaller and 30 % of them are a lighter stone. The field drapes over the ground and tiles itself when the ground is not planar, every rock standing upright. Use for stony ground, a moraine, a boulder field, rubble across a site.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'count': {'type': 'number'},
                    'size': {'type': 'number', 'description': 'the LARGEST boulder DIAMETER in metres, 0.3 to 4'},
                    'seed': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cell_from', 'cell_to'],
            },
        },
        t_scatter_rocks,
    ),
    (
        {
            'name': 'add_scree',
            'description': 'A slope of loose rubble along a chain of cells, one per consecutive pair, leaning on the rock on your left exactly as add_cliff does. height is the top of the pile (0.5-40 m), width how far it spreads out from the face. It lands on the ground at the cliff FOOT, not on its ledge.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'height': {'type': 'number'},
                    'width': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['cells'],
            },
        },
        t_add_scree,
    ),
    (
        {
            'name': 'add_sea_stack',
            'description': 'A tall rock column with a flat top standing on one cell: 2 x radius across (radius 0.5-30 m), height tall (3-80 m). It lands on the ground under it. Use in water off a cliff coast, or on land as a pinnacle.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'centre': {'type': 'string'},
                    'radius': {'type': 'number'},
                    'height': {'type': 'number'},
                    'seed': {'type': 'number'},
                    'base_height': _BASE,
                    'material': {'type': 'string', 'enum': MATERIALS},
                    'name': {'type': 'string'},
                },
                'required': ['centre'],
            },
        },
        t_add_sea_stack,
    ),
]

EXAMPLES = [
    {
        'ask': 'a 20 m cliff running along E10, E16 and J16, with the drop on the west side',
        'calls': [{'tool': 'add_cliff', 'args': {'cells': ['E10', 'E16', 'J16'], 'height': 20}}],
    },
    {
        'ask': 'put scree at the foot of that cliff',
        'calls': [{'tool': 'add_scree', 'args': {'cells': ['E10', 'E16', 'J16'], 'height': 6, 'width': 12}}],
    },
    {
        'ask': 'the ground from C4 to L13 is a ridge falling away to the south, 15 m high',
        'calls': [
            {
                'tool': 'add_escarpment',
                'args': {'cell_from': 'C4', 'cell_to': 'L13', 'height': 15, 'direction': 'south'},
            }
        ],
    },
    {
        'ask': 'a big rock at P30 and stony ground all over Q28 to V34',
        'calls': [
            {'tool': 'add_boulder', 'args': {'centre': 'P30', 'size': 2.5}},
            {'tool': 'scatter_rocks', 'args': {'cell_from': 'Q28', 'cell_to': 'V34', 'count': 40}},
        ],
    },
    {
        'ask': 'two sea stacks in the water at B20 and D22, about 30 m tall',
        'calls': [
            {'tool': 'add_sea_stack', 'args': {'centre': 'B20', 'radius': 6, 'height': 30}},
            {'tool': 'add_sea_stack', 'args': {'centre': 'D22', 'radius': 5, 'height': 28, 'seed': 4}},
        ],
    },
    {
        'ask': 'a plateau at H5..H12 with a 12 m cliff along its edge',
        'calls': [
            {'tool': 'add_object', 'args': {'kind': 'plateau', 'cell': 'H8', 'params': {'w': 8, 'd': 8, 'h': 4}}},
            {'tool': 'add_cliff', 'args': {'cells': ['H5', 'H12'], 'height': 12}},
        ],
    },
]
