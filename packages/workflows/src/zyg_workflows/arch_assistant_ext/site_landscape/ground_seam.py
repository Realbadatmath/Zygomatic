# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""site_landscape.ground_seam — the ground seam and what is already on the site.

Moved verbatim out of the 1,180-line site_landscape.py; original lines
221-441.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
    cell_centre,
    cell_of,
    cell_size,
    ground_height,
    ground_plane,
    parse_cell,
)

from zyg_workflows.arch_assistant_ext.site_landscape.constants import (
    CANOPY_CLEAR,
    CANOPY_KINDS,
    CANOPY_NEAR,
    FENCE_LEAN,
    FENCE_PIECE,
    MAX_TILES,
    ROAD_CLEAR,
    ROAD_OFFSET,
    SOFFIT_GAP,
    TILE_SPREAD,
    _clamp,
    _ry,
)


# ── the ground seam, used by every tool below ────────────────────────────────
def _local_slopes(glx, glz, ry):
    """World-frame ground slopes turned into a record's LOCAL x/z slopes."""
    c, s = math.cos(ry), math.sin(ry)
    return glx * c - glz * s, glx * s + glz * c


def _leg_pieces(d, A, B, base_height, split=False):
    """Split a leg A->B into pieces and give each (centre, len, ry, y, rz) — R4.
    A piece sits at the ground under its own centre and leans along its run."""
    L = math.hypot(B[0] - A[0], B[1] - A[1])
    ry = _ry(A, B)
    n = 1
    if split and base_height is None and L > FENCE_PIECE:
        ya, yb = ground_height(d, *A), ground_height(d, *B)
        if abs(yb - ya) / L > FENCE_LEAN:
            n = min(MAX_TILES, int(math.ceil(L / FENCE_PIECE)))
    out = []
    for i in range(n):
        t0, t1 = i / n, (i + 1) / n
        p0 = (A[0] + (B[0] - A[0]) * t0, A[1] + (B[1] - A[1]) * t0)
        p1 = (A[0] + (B[0] - A[0]) * t1, A[1] + (B[1] - A[1]) * t1)
        cx, cz = (p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2
        li = L / n
        if base_height is None:
            y0, y1 = ground_height(d, *p0), ground_height(d, *p1)
            y = round(ground_height(d, cx, cz), 4)
            rz = math.atan((y1 - y0) / li) if li > 1e-6 else 0.0
        else:
            y0 = y1 = y = _num(base_height, 0.0)
            rz = 0.0
        out.append({'cx': cx, 'cz': cz, 'len': li, 'ry': ry, 'y': y, 'rz': rz, 'y0': y0, 'y1': y1})
    return out


def _tile_block(d, xmin, zmin, xmax, zmax, base_height=None, limit=TILE_SPREAD):
    """R2 — the block cut into as few tiles as it takes for every tile's ground to
    be planar within `limit`. Each tile: (cx, cz, w, d, y, gx, gz)."""
    W, D = xmax - xmin, zmax - zmin
    nx = max(1, int(math.ceil(W / 25.0)))
    nz = max(1, int(math.ceil(D / 25.0)))
    tiles = []
    for _ in range(7):
        tiles, worst = [], 0.0
        tw, td = W / nx, D / nz
        for j in range(nz):
            for i in range(nx):
                cx = xmin + (i + 0.5) * tw
                cz = zmin + (j + 0.5) * td
                if base_height is None:
                    y0, glx, glz, sp = ground_plane(d, cx, cz, tw, td, 0.0)
                else:
                    y0, glx, glz, sp = _num(base_height, 0.0), 0.0, 0.0, 0.0
                worst = max(worst, sp)
                tiles.append((cx, cz, tw, td, round(y0, 4), round(glx, 4), round(glz, 4)))
        if worst <= limit or nx * nz * 4 > MAX_TILES:
            break
        nx, nz = nx * 2, nz * 2
    return tiles


def _fall(ys):
    """A human sentence about how far a run of records drops."""
    if len(ys) < 2 or max(ys) - min(ys) < 0.05:
        return ''
    return f', dropping {max(ys) - min(ys):.1f} m down the ground'


# ── what is already on the site: canopies and carriageways ───────────────────
def _canopies(d: Drawing) -> list:
    """[(record, footprint)] for every canopy or awning plate in the drawing.

    A canopy record sits on the OUTER FACE of its wall, turned so that local -Z
    points away from the building: p.w runs ALONG the facade and p.d projects
    OUT from it, exactly the frame add_canopy uses to space its columns (their
    centres land p.d - 0.35 m out, on the plate's outer edge). `soffit` is the
    record's own y — the underside of the plate."""
    out = []
    for o in d.objs:
        if o['kind'] not in CANOPY_KINDS:
            continue
        p = o.get('p') or {}
        w, dd = _num(p.get('w'), 0.0), _num(p.get('d'), 0.0)
        if w <= 0 or dd <= 0:
            continue
        ry = _num(o.get('ry'), 0.0)
        out.append(
            (
                o,
                {
                    'x': _num(o.get('x'), 0.0),
                    'z': _num(o.get('z'), 0.0),
                    'w': w,
                    'd': dd,
                    'ax': math.cos(ry),
                    'az': -math.sin(ry),  # along the facade
                    'ox': -math.sin(ry),
                    'oz': -math.cos(ry),  # out from it
                    'soffit': _num(o.get('y'), 0.0),
                },
            )
        )
    return out


def _canopy_dist(f: dict, x: float, z: float) -> float:
    """Distance in plan from (x, z) to a canopy's rectangle — 0.0 when under it."""
    dx, dz = x - f['x'], z - f['z']
    u = dx * f['ax'] + dz * f['az']  # 0 at the centre of the width
    v = dx * f['ox'] + dz * f['oz']  # 0 at the wall, p.d at the outer edge
    return math.hypot(max(0.0, abs(u) - f['w'] / 2), max(0.0, -v, v - f['d']))


def _clear_cell(fps: list, f: dict, x: float, z: float) -> str:
    """The nearest cell straight out along the facade normal that is clear of
    every canopy footprint — the cell a refusal tells the caller to use."""
    step = cell_size()
    for i in range(1, 200):
        c = cell_of(x + f['ox'] * step * i, z + f['oz'] * step * i)
        cx, cz = cell_centre(*parse_cell(c))
        if all(_canopy_dist(g, cx, cz) > CANOPY_CLEAR + 1e-9 for _, g in fps):
            return c
    return ''


def _canopy_refusal(d: Drawing, names: list, pts: list) -> str:
    """Nothing stands under a canopy (or within CANOPY_CLEAR of its edge)."""
    fps = _canopies(d)
    if not fps:
        return ''
    bad = []
    for c, (x, z) in zip(names, pts):
        for o, f in fps:
            if _canopy_dist(f, x, z) <= CANOPY_CLEAR + 1e-9:
                bad.append((c, o, _clear_cell(fps, f, x, z)))
                break
    if not bad:
        return ''
    moves = ', '.join(f'{c} -> {to or "further out"}' for c, _, to in bad)
    plate = bad[0][1]
    return (
        f'refused: {", ".join(c for c, _, _ in bad)} '
        f'{"is" if len(bad) == 1 else "are"} under the {plate["kind"]} {plate["id"]} '
        f'({plate["p"].get("w")} x {plate["p"].get("d")} m, soffit {plate["y"]:g} m) or inside its '
        f'{CANOPY_CLEAR:g} m clearance — a lamp post there is in the way of everything arriving. '
        f'Move it out from under the plate: {moves}.'
    )


def _roads(d: Drawing) -> list:
    """[(record, centreline)] for every road piece: one straight run of p.len
    centred on x/z, running along the record's own ry (as t_add_road lays it)."""
    out = []
    for o in d.objs:
        if o['kind'] != 'road':
            continue
        p = o.get('p') or {}
        L, w = _num(p.get('len'), 0.0), _num(p.get('w'), 0.0)
        if L <= 0 or w <= 0:
            continue
        ry = _num(o.get('ry'), 0.0)
        out.append(
            (
                o,
                {
                    'x': _num(o.get('x'), 0.0),
                    'z': _num(o.get('z'), 0.0),
                    'ux': math.cos(ry),
                    'uz': -math.sin(ry),
                    'len': L,
                    'w': w,
                },
            )
        )
    return out


def _road_dist(r: dict, x: float, z: float) -> float:
    """Distance in plan from (x, z) to a road's centreline segment."""
    t = _clamp((x - r['x']) * r['ux'] + (z - r['z']) * r['uz'], -r['len'] / 2, r['len'] / 2)
    return math.hypot(x - (r['x'] + t * r['ux']), z - (r['z'] + t * r['uz']))


def _verge_cells(r: dict, x: float, z: float, off: float) -> tuple:
    """The two cells `off` metres either side of the centreline, abreast of (x, z)."""
    t = _clamp((x - r['x']) * r['ux'] + (z - r['z']) * r['uz'], -r['len'] / 2, r['len'] / 2)
    bx, bz = r['x'] + t * r['ux'], r['z'] + t * r['uz']
    px, pz = -r['uz'], r['ux']
    return cell_of(bx + px * off, bz + pz * off), cell_of(bx - px * off, bz - pz * off)


def _carriageway_refusal(d: Drawing, names: list, pts: list, what: str) -> str:
    """Nothing stands in the carriageway: a lamp or a tree must clear the road
    edge (w/2) by ROAD_CLEAR, and a refusal names the offset that does."""
    for o, r in _roads(d):
        keep = r['w'] / 2 + ROAD_CLEAR
        hits = [(c, _road_dist(r, x, z), x, z) for c, (x, z) in zip(names, pts) if _road_dist(r, x, z) < keep - 1e-9]
        if not hits:
            continue
        off = r['w'] / 2 + ROAD_OFFSET
        a, b = _verge_cells(r, hits[0][2], hits[0][3], off)
        return (
            f'refused: {", ".join(c for c, _, _, _ in hits)} '
            f'{"is" if len(hits) == 1 else "are"} in the carriageway — '
            f'{min(dd for _, dd, _, _ in hits):.2f} m from the centreline of the {r["w"]:g} m road '
            f'{o["id"]}, whose edge is {r["w"] / 2:.2f} m out. A {what} stands at least {keep:.2f} m '
            f'off the centreline: use an offset of {off:.2f} m (here that is {a} or {b}), '
            f'or move the road.'
        )


def _soffit_cap(d: Drawing, pts: list) -> tuple:
    """(cap, soffit) — the tallest a lamp near a canopy may be, and the soffit
    that says so; (None, None) when nothing stands within CANOPY_NEAR of one."""
    best = (None, None)
    for _o, f in _canopies(d):
        if any(_canopy_dist(f, x, z) <= CANOPY_NEAR + 1e-9 for x, z in pts):
            cap = round(f['soffit'] - SOFFIT_GAP, 3)
            if best[0] is None or cap < best[0]:
                best = (cap, f['soffit'])
    return best
