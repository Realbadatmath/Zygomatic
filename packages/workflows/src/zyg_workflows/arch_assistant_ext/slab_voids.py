# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""slab_voids — the hole a stair, a lift or an atrium needs in the floor it passes.

A slab record is one box; nothing in the record model can carry a hole. So a
void is made by REPLACING the slab with the rectangles around the void, and by
writing what was cut into a registry on the document (`d.ext['slab_voids']`) so
that a second cut on the same floor can rebuild the pieces from the ORIGINAL
rectangle instead of cutting pieces out of pieces.

The decomposition is a band split, not a general polygon subtraction: the void
edges cut the slab into horizontal bands (z), and inside each band the voids
that cross it cut the remaining x intervals. One void therefore always gives the
four named pieces — a north strip, a south strip, a west piece and an east piece
— and a void that reaches an edge simply drops that piece. Two voids give more
bands and more pieces; correctness beats minimality here.

check_voids() is the other half: it reads every stair and lift shaft, works out
the vertical span it occupies, and reports every slab of its own group that lies
strictly inside that span without a registered opening under the record. That is
the relation the tools could not see — job 71ac02b0 drove a 285-step stair
through nineteen floors and the design check said "0 errors".
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, MAX_OBJECTS, _num, block_bounds, storey_index, storey_of
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

SLAB_KINDS = ('slab', 'roof_flat')
VERT_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral', 'elevator_shaft')
MIN_PIECE = 0.3  # a strip thinner than this is not a floor, it is a fin — drop it
TOL = 0.05  # containment slack, and the "strictly inside the span" margin
MAX_FINDINGS = 8

_WORD = {
    'stair_straight': 'straight stair',
    'stair_u': 'u stair',
    'stair_l': 'l stair',
    'stair_winder': 'winder stair',
    'stair_spiral': 'spiral stair',
    'elevator_shaft': 'lift shaft',
}

PROMPT = (
    'Floor openings: cut_floor_opening(group, storey, cell_from, cell_to, reason) cuts a rectangular void '
    "through that storey's slab or flat roof — the slab is replaced by the pieces around the hole, and a "
    'second cut that overlaps the first merges into one opening. Every stair, lift shaft, atrium or duct '
    'that passes a floor needs one, one per storey crossed. list_floor_openings(group) lists what was cut; '
    'design_check names every stair or shaft that crosses a slab with no opening.'
)


# ── rectangles ───────────────────────────────────────────────────────────────
def _norm(xmin, zmin, xmax, zmax) -> list:
    x0, x1 = sorted((_num(xmin, 0.0), _num(xmax, 0.0)))
    z0, z1 = sorted((_num(zmin, 0.0), _num(zmax, 0.0)))
    return [round(x0, 4), round(z0, 4), round(x1, 4), round(z1, 4)]


def _area(r) -> float:
    return max(0.0, r[2] - r[0]) * max(0.0, r[3] - r[1])


def _clip(r, bnd) -> list:
    return [max(r[0], bnd[0]), max(r[1], bnd[1]), min(r[2], bnd[2]), min(r[3], bnd[3])]


def _overlaps(a, b, tol: float = 1e-9) -> bool:
    return (min(a[2], b[2]) - max(a[0], b[0])) > tol and (min(a[3], b[3]) - max(a[1], b[1])) > tol


def _union(a, b) -> list:
    return [min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])]


def _contains(outer, inner, tol: float = TOL) -> bool:
    return (
        outer[0] <= inner[0] + tol
        and outer[1] <= inner[1] + tol
        and outer[2] >= inner[2] - tol
        and outer[3] >= inner[3] - tol
    )


def _pieces_around(bnd, voids) -> list:
    """`bnd` minus `voids` (each already clipped to bnd) as axis-aligned bands.
    One void -> [north strip, west, east, south strip]."""
    zs = {round(bnd[1], 6), round(bnd[3], 6)}
    for v in voids:
        zs.add(round(v[1], 6))
        zs.add(round(v[3], 6))
    zs = sorted(z for z in zs if bnd[1] - 1e-9 <= z <= bnd[3] + 1e-9)
    out = []
    for i in range(len(zs) - 1):
        z0, z1 = zs[i], zs[i + 1]
        if z1 - z0 < MIN_PIECE:
            continue
        zc = (z0 + z1) / 2
        cuts = sorted((v[0], v[2]) for v in voids if v[1] < zc < v[3])
        spans, cur = [], bnd[0]
        for a, b in cuts:
            if b <= cur:
                continue
            if a > cur:
                spans.append((cur, min(a, bnd[2])))
            cur = max(cur, b)
            if cur >= bnd[2]:
                break
        if cur < bnd[2]:
            spans.append((cur, bnd[2]))
        for a, b in spans:
            if b - a >= MIN_PIECE:
                out.append([a, z0, b, z1])
    return out


def _side_word(piece, uni) -> str:
    if piece[3] <= uni[1] + 1e-6:
        return 'N'
    if piece[1] >= uni[3] - 1e-6:
        return 'S'
    if piece[2] <= uni[0] + 1e-6:
        return 'W'
    if piece[0] >= uni[2] - 1e-6:
        return 'E'
    return 'part'


# ── the drawing ──────────────────────────────────────────────────────────────
def _slab_bounds(rec) -> list:
    w, dd = _num((rec.get('p') or {}).get('w'), 0.0), _num((rec.get('p') or {}).get('d'), 0.0)
    x, z = _num(rec.get('x'), 0.0), _num(rec.get('z'), 0.0)
    return [x - w / 2, z - dd / 2, x + w / 2, z + dd / 2]


def _storey_of_rec(d, rec, H: float) -> int:
    try:
        return int(storey_index(d, rec, H))
    except Exception:  # noqa: BLE001 — never block a check
        return storey_of(_num(rec.get('y'), 0.0), H)


def _slabs_of(d, group: str) -> list:
    return [o for o in d.objs if o['kind'] in SLAB_KINDS and o['grp'] == group]


def _slab_at(d, group: str, storey: int, H: float):
    """The ONE slab / flat roof of `group` on `storey`. storey_index counts from
    the record's own base, so a building on a hill answers the same as one at
    y = 0; a raw y within 0.35 m of storey * H is accepted as a fallback."""
    here = [o for o in _slabs_of(d, group) if _storey_of_rec(d, o, H) == storey]
    if not here:
        here = [o for o in _slabs_of(d, group) if abs(_num(o.get('y'), 0.0) - storey * H) <= 0.35]
    if not here:
        return None
    here.sort(key=lambda o: abs(_num(o.get('y'), 0.0) - storey * H))
    return here[0]


def _registry(d) -> list:
    reg = d.ext.get('slab_voids')
    if not isinstance(reg, list):
        reg = []
        d.ext['slab_voids'] = reg
    return reg


def _rect_of(entry) -> list:
    return [
        _num(entry.get('xmin'), 0.0),
        _num(entry.get('zmin'), 0.0),
        _num(entry.get('xmax'), 0.0),
        _num(entry.get('zmax'), 0.0),
    ]


def voids_at(d, group: str, storey: int) -> list:
    """The registered void entries of one floor."""
    return [
        e
        for e in _registry(d)
        if e.get('group') == str(group or '') and int(_num(e.get('storey'), -9999)) == int(_num(storey, 0))
    ]


# ── the cut ──────────────────────────────────────────────────────────────────
def cut_slab_void(d, group, storey, xmin, zmin, xmax, zmax, reason='stair') -> tuple:
    """Cut a rectangular void through the slab / flat roof of `group` on `storey`.
    Returns (piece_ids, note); ([], 'refused: …') when there is no such slab."""
    H = getattr(d, 'storey_h', 0.0) or 2.7
    grp = str(group or '')
    st = int(_num(storey, 0))
    why = str(reason or 'stair').strip() or 'stair'
    reg = _registry(d)
    mine = voids_at(d, grp, st)

    slab = None
    if mine:
        orig = dict(mine[0].get('orig') or {})
    else:
        slab = _slab_at(d, grp, st, H)
        if slab is None:
            have = sorted({_storey_of_rec(d, o, H) for o in _slabs_of(d, grp)})
            if not have:
                return (
                    [],
                    f'refused: no slab or flat roof belongs to a group called "{grp}" — use the group name '
                    f'draw_box printed, and draw it with slabs=true',
                )
            return (
                [],
                f'refused: group "{grp}" has no slab at storey {st} — its floors are storeys '
                + ', '.join(str(s) for s in have),
            )
        p = dict(slab.get('p') or {})
        orig = {
            'x': _num(slab.get('x'), 0.0),
            'z': _num(slab.get('z'), 0.0),
            'w': _num(p.get('w'), 0.0),
            'd': _num(p.get('d'), 0.0),
            'y': _num(slab.get('y'), 0.0),
            't': _num(p.get('t'), 0.22),
            'kind': slab['kind'],
            'mat': slab['mat'],
            'name': slab['name'],
            'id': slab['id'],
            'p': p,
        }

    bnd = [orig['x'] - orig['w'] / 2, orig['z'] - orig['d'] / 2, orig['x'] + orig['w'] / 2, orig['z'] + orig['d'] / 2]
    new = _clip(_norm(xmin, zmin, xmax, zmax), bnd)
    if (new[2] - new[0]) < 1e-6 or (new[3] - new[1]) < 1e-6:
        return (
            [],
            f'refused: that rectangle falls outside the storey {st} floor of "{grp}", which spans '
            f'x {bnd[0]:g}..{bnd[2]:g} m, z {bnd[1]:g}..{bnd[3]:g} m',
        )

    # merge every registered void this one touches (transitively), keep the rest
    rects = [_rect_of(e) for e in mine]
    absorbed, merged, again = set(), new, True
    while again:
        again = False
        for i, r in enumerate(rects):
            if i in absorbed or not _overlaps(merged, r):
                continue
            merged = _union(merged, r)
            absorbed.add(i)
            again = True
    merged = _clip(merged, bnd)
    survivors = [e for i, e in enumerate(mine) if i not in absorbed]
    voids = [_clip(_rect_of(e), bnd) for e in survivors] + [merged]

    pieces = _pieces_around(bnd, voids)
    old = [r for r in (d.find(i) for e in mine for i in (e.get('ids') or [])) if r is not None]
    if slab is not None:
        old.append(slab)
    if len(d.objs) - len(old) + len(pieces) > MAX_OBJECTS:
        return (
            [],
            f'refused: rebuilding that floor is {len(pieces)} objects and the drawing may hold {MAX_OBJECTS} in total',
        )

    for i in sorted(absorbed, reverse=True):
        reg.remove(mine[i])
    entry = {
        'group': grp,
        'storey': st,
        'xmin': round(merged[0], 4),
        'zmin': round(merged[1], 4),
        'xmax': round(merged[2], 4),
        'zmax': round(merged[3], 4),
        'reason': why,
        'orig': orig,
        'ids': [],
    }
    reg.append(entry)

    if old:
        d.remove(old)
    uni = voids[0]
    for v in voids[1:]:
        uni = _union(uni, v)
    ids = []
    for pc in pieces:
        p = dict(orig.get('p') or {})
        p['w'] = round(pc[2] - pc[0], 4)
        p['d'] = round(pc[3] - pc[1], 4)
        p['t'] = orig['t']
        rec = d.new(
            orig['kind'],
            p,
            (pc[0] + pc[2]) / 2,
            (pc[1] + pc[3]) / 2,
            orig['y'],
            0.0,
            orig['mat'],
            name=f'{orig["name"]} ({_side_word(pc, uni)} of {why} void)',
            grp=grp,
        )
        ids.append(rec['id'])
    for e in survivors + [entry]:
        e['ids'] = list(ids)

    kept = sum(_area(pc) for pc in pieces)
    return (
        ids,
        f'cut a {merged[2] - merged[0]:.2f} x {merged[3] - merged[1]:.2f} m {why} void through the storey '
        f'{st} {"flat roof" if orig["kind"] == "roof_flat" else "slab"} of "{grp}": {orig["id"]} is now '
        f'{len(ids)} piece(s) {", ".join(ids)} — {_area(bnd) - kept:.2f} m2 of floor removed, '
        f'{len(survivors) + 1} opening(s) on this floor',
    )


# ── the model's tools ────────────────────────────────────────────────────────
def t_cut_floor_opening(d: Drawing, a, group, storey=0, cell_from='', cell_to='', reason='atrium'):
    xmin, zmin, xmax, zmax = block_bounds(cell_from, cell_to)  # ValueError -> refused
    ids, note = cut_slab_void(d, group, storey, xmin, zmin, xmax, zmax, reason)
    if not ids:
        return note
    d.selected = list(ids)
    return note


def t_list_floor_openings(d: Drawing, a, group=''):
    reg = [e for e in _registry(d) if not group or e.get('group') == group]
    if not reg:
        return (
            'no floor openings are registered'
            + (f' for "{group}"' if group else '')
            + ' — cut_floor_opening(group, storey, cell_from, cell_to) makes one'
        )
    rows = []
    for e in sorted(reg, key=lambda x: (str(x.get('group')), int(_num(x.get('storey'), 0)))):
        r = _rect_of(e)
        rows.append(
            f'{e.get("group")} storey {int(_num(e.get("storey"), 0))}: {r[2] - r[0]:.2f} x {r[3] - r[1]:.2f} m '
            f'{e.get("reason")} void, floor in {len(e.get("ids") or [])} piece(s)'
        )
    return f'{len(rows)} floor opening(s):\n' + '\n'.join(rows)


# ── the check ────────────────────────────────────────────────────────────────
def footprint_of(rec) -> list:
    """Plan bbox of a stair / lift record, from the same numbers the mesh
    builders read (arch_blender_ext/stairs_vertical.py), turned by its ry."""
    p = rec.get('p') or {}
    k = rec.get('kind')

    def n(key, dflt):
        return _num(p.get(key), dflt)

    if k == 'stair_straight':
        w, dd = n('steps', 16) * n('run', 0.28), n('w', 1.0)
    elif k == 'stair_u':
        steps = max(2, int(n('steps', 16)))
        w = (steps // 2) * n('run', 0.28) + n('w', 1.0)
        dd = 2 * n('w', 1.0) + n('gap', 0.2)
    elif k == 'stair_l':
        w = n('steps_a', 8) * n('run', 0.28) + n('w', 1.0)
        dd = n('steps_b', 8) * n('run', 0.28) + n('w', 1.0)
    elif k == 'stair_winder':
        steps = max(3, int(n('steps', 16)))
        nw = max(1, int(round(steps / 4.0)))
        nw = max(1, min(nw, steps - 2))
        n1 = (steps - nw) // 2
        w = (n1 + nw) * n('run', 0.28) + n('w', 1.0)
        dd = (steps - nw - n1 + nw) * n('run', 0.28) + n('w', 1.0)
    elif k == 'stair_spiral':
        w = dd = 2 * n('r_out', 1.1)
    else:
        w, dd = n('w', 1.8), n('d', 2.0)
    ry = _num(rec.get('ry'), 0.0)
    c, s = abs(math.cos(ry)), abs(math.sin(ry))
    W, D = w * c + dd * s, w * s + dd * c
    x, z = _num(rec.get('x'), 0.0), _num(rec.get('z'), 0.0)
    return [x - W / 2, z - D / 2, x + W / 2, z + D / 2]


def _bbox(rec) -> list:
    env = A.EXT_MODULES.get('envelope_rules')
    fn = getattr(env, 'bbox_of', None) if env is not None else None
    if callable(fn):
        try:
            r = fn(rec)
            if r and len(r) == 4:
                return [float(v) for v in r]
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('envelope bbox unavailable, using the footprint: %s', _exc)
    return footprint_of(rec)


def _span(rec) -> tuple:
    p = rec.get('p') or {}
    h = _num(p.get('h'), 0.0)
    if h <= 0:
        steps = _num(p.get('steps'), 0.0) or (_num(p.get('steps_a'), 0.0) + _num(p.get('steps_b'), 0.0))
        h = steps * _num(p.get('rise'), 0.0)
    y = _num(rec.get('y'), 0.0)
    return y, y + h


def _group_for(d, rec, slabs_by_grp) -> str:
    g = str(rec.get('grp') or '')
    if g and slabs_by_grp.get(g):
        return g
    env = A.EXT_MODULES.get('envelope_rules')
    fn = getattr(env, 'group_at', None) if env is not None else None
    if callable(fn):
        try:
            g2 = fn(d, _num(rec.get('x'), 0.0), _num(rec.get('z'), 0.0))
            if g2 and slabs_by_grp.get(str(g2)):
                return str(g2)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('envelope group_at failed, scanning the slabs instead: %s', _exc)
    x, z = _num(rec.get('x'), 0.0), _num(rec.get('z'), 0.0)
    for grp, slabs in slabs_by_grp.items():
        for o in slabs:
            b = _slab_bounds(o)
            if b[0] <= x <= b[2] and b[1] <= z <= b[3]:
                return grp
    return g


def check_voids(d) -> list:
    """Every stair / lift shaft that crosses a floor with no registered opening."""
    H = getattr(d, 'storey_h', 0.0) or 2.7
    reg = _registry(d)
    slabs_by_grp: dict = {}
    for o in d.objs:
        if o['kind'] in SLAB_KINDS:
            slabs_by_grp.setdefault(o['grp'], []).append(o)
    hits = []
    for rec in d.objs:
        if rec['kind'] not in VERT_KINDS:
            continue
        lo, hi = _span(rec)
        if hi - lo <= 2 * TOL:
            continue
        grp = _group_for(d, rec, slabs_by_grp)
        bb = _bbox(rec)
        for slab in slabs_by_grp.get(grp, []):
            y = _num(slab.get('y'), 0.0)
            if not (lo + TOL < y < hi - TOL):
                continue
            sb = _slab_bounds(slab)
            need = _clip(bb, sb)
            if _area(need) <= 1e-9:
                continue  # the stair does not stand over this floor
            st = _storey_of_rec(d, slab, H)
            if any(
                _contains(_rect_of(e), need)
                for e in reg
                if e.get('group') == grp and int(_num(e.get('storey'), -9999)) == st
            ):
                continue
            hits.append((rec, slab, st, grp))
    out = []
    for rec, slab, st, grp in hits[:MAX_FINDINGS]:
        out.append(
            {
                'sev': 'error',
                'code': 'void_missing',
                'text': f'{rec["id"]} {_WORD.get(rec["kind"], rec["kind"])} passes through '
                f'{"flat roof" if slab["kind"] == "roof_flat" else "slab"} {slab["id"]} (storey {st}) '
                f'with no floor opening — add_stair draws stairs storey by storey and cuts the '
                f'openings; for an existing stair: cut_floor_opening("{grp}", {st}, ...)',
            }
        )
    if len(hits) > MAX_FINDINGS:
        out.append(
            {
                'sev': 'error',
                'code': 'void_missing_more',
                'text': f'… and {len(hits) - MAX_FINDINGS} more floors crossed with no opening '
                f'({len(hits)} in total) — one opening per storey crossed',
            }
        )
    return out


DESIGN_CHECKS = [check_voids]

TOOLS = [
    (
        {
            'name': 'cut_floor_opening',
            'description': "Cut a rectangular void through one storey's floor slab or flat roof of a group, so a stair, "
            'lift, atrium or duct can pass. The slab is replaced by the pieces around the hole; a second '
            'cut that overlaps the first merges into one opening. Cells are inclusive.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'the group name draw_box printed'},
                    'storey': {
                        'type': 'integer',
                        'description': 'which floor to cut; the flat roof is storey = storeys',
                    },
                    'cell_from': {'type': 'string'},
                    'cell_to': {'type': 'string'},
                    'reason': {'type': 'string', 'description': 'stair, lift, atrium, duct …'},
                },
                'required': ['group', 'storey', 'cell_from', 'cell_to'],
            },
        },
        t_cut_floor_opening,
    ),
    (
        {
            'name': 'list_floor_openings',
            'description': 'List the floor openings that have been cut, per group and storey.',
            'input_schema': {'type': 'object', 'properties': {'group': {'type': 'string'}}, 'required': []},
        },
        t_list_floor_openings,
    ),
]

EXAMPLES = [
    {
        'ask': 'cut a three storey atrium through the middle of the tower',
        'calls': [
            {
                'tool': 'cut_floor_opening',
                'args': {'group': 'tower', 'storey': 1, 'cell_from': 'FF98', 'cell_to': 'FJ102', 'reason': 'atrium'},
            },
            {
                'tool': 'cut_floor_opening',
                'args': {'group': 'tower', 'storey': 2, 'cell_from': 'FF98', 'cell_to': 'FJ102', 'reason': 'atrium'},
            },
        ],
    },
    {
        'ask': 'does the stair actually get through the floors?',
        'calls': [{'tool': 'design_check', 'args': {}}, {'tool': 'list_floor_openings', 'args': {'group': 'tower'}}],
    },
]
