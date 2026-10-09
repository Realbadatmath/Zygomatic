# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.tiling — tiling a whole floor with REAL units: the band/run search,
the candidate fill and `t_tile_units`. Moved verbatim out of floor_plans.py
(2026-10-06)."""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import (
    Drawing,
    MAX_OBJECTS,
    _num,
)

from zyg_workflows.arch_assistant_ext.floor_plans.plan_packs import (
    EXT_KEY,
    SCALE_MAX,
    SCALE_MIN,
    SIDES_CW,
    _approach_rects,
    _clamp,
    _core_rects,
    _group_plate,
    _group_wall_mat,
    _landing_rects,
    attribution_of,
    load_plan,
    packs,
    plans_dir,
)
from zyg_workflows.arch_assistant_ext.floor_plans.placing import (
    _place,
    record_attribution,
)


# ── tiling a whole floor with REAL units ─────────────────────────────────────
# layout_floor cuts a double-loaded corridor with equal generic boxes either side.
# This does the same move with surveyed apartments: pick the units whose DEPTH
# matches the band, fill the run with their real widths, turn each so its own
# front door faces the corridor, and let their plans draw themselves.
CORRIDOR_MIN = 1.2  # spec("corridor"): two people pass
BAND_MIN = 2.0  # a shallower band is not a dwelling
FILL_STEP = 0.05  # the grid the width search runs on
DEDUPE_TOL = 0.15  # two partitions closer than this are one wall
FILL_OK = 0.3  # "the sum matches the run" within this
WALL_T = 0.1


def _rects_overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def _seg_point_dist(a, b, p) -> float:
    vx, vz = b[0] - a[0], b[1] - a[1]
    L2 = vx * vx + vz * vz or 1e-9
    u = _clamp(((p[0] - a[0]) * vx + (p[1] - a[1]) * vz) / L2, 0.0, 1.0)
    return math.hypot(p[0] - (a[0] + u * vx), p[1] - (a[1] + u * vz))


def _free_spans(span: tuple, blocked: list) -> list:
    """`span` minus the blocked intervals, in order."""
    out, lo = [], span[0]
    for b0, b1 in sorted(blocked):
        if b1 <= lo:
            continue
        if b0 > lo:
            out.append((lo, min(b0, span[1])))
        lo = max(lo, b1)
        if lo >= span[1]:
            break
    if lo < span[1]:
        out.append((lo, span[1]))
    return [s for s in out if s[1] > s[0]]


def _unit_rows(pack_name: str) -> list:
    return [r for r in ((packs().get(pack_name) or {}).get('rows') or []) if str(r.get('kind')) == 'unit']


def _orient(row: dict) -> tuple:
    """(depth across the band, width along the corridor) — the ONE orientation in
    which this unit's front door can face the corridor, or (None, None).

    It is not a free choice: _place derives its rotation from the entrance side,
    so a unit whose door is north or south can only turn 0/180 (its bbox stays
    w x d) and one whose door is east or west only 90/270 (bbox d x w). Mirroring
    swaps east for west, which flips 90 for 270 and changes nothing else — so the
    depth/width pair below holds for both corridor directions and both mirrors."""
    es = str(row.get('entrance') or '').strip().lower()
    if es not in SIDES_CW:
        return None, None
    w, dd = _num(row.get('w'), 0.0), _num(row.get('d'), 0.0)
    if w <= 0 or dd <= 0:
        return None, None
    return (dd, w) if es in ('north', 'south') else (w, dd)


def _candidates(rows: list, band_d: float, tol: float, min_w: float, max_scale: float) -> tuple:
    """(usable units, depths that were near enough but could not be used).

    A unit deeper than the band is shrunk onto it — but only inside the family's
    own ±12 % contract, never further: past that it is a different flat. A unit
    shallower than the band simply sits centred in it, which is what depth_tol
    bounds. max_scale is the LAST unit's run-closing stretch, nothing else."""
    out, near_miss = [], []
    for r in rows:
        depth, width = _orient(r)
        if depth is None or abs(depth - band_d) > tol:
            continue
        s0 = min(1.0, band_d / depth)
        s_hi = min(SCALE_MAX, 1.0 + max_scale, band_d / depth)
        s_lo = max(SCALE_MIN, 1.0 - max_scale)
        if s0 < SCALE_MIN - 1e-9:  # too deep: it would have to be redrawn
            near_miss.append((depth, f'{r["id"]} is {depth:.1f} m deep, {s0:.2f} of the band'))
            continue
        if width * s_hi < min_w:
            near_miss.append((depth, f'{r["id"]} is only {width * s_hi:.1f} m wide'))
            continue
        out.append(
            {
                'id': r['id'],
                'uw': width * s0,
                'scale': s0,
                'w0': width,
                'd0': depth,
                'uw_lo': max(min_w, width * s_lo),
                'uw_hi': width * s_hi,
            }
        )
    return out, near_miss


def _nearest_depths(rows: list, band_d: float, n: int = 2) -> list:
    ds = sorted({round(_orient(r)[0], 1) for r in rows if _orient(r)[0]}, key=lambda v: abs(v - band_d))
    return sorted(ds[:n])


def _fill(cands: list, run: float, min_w: float) -> tuple:
    """(chosen units, leftover metres) — the row that closes on `run`.

    Largest-first is the seed; the search below is the same heuristic run to the
    end, so a row of three 6.6 m flats beats one 13 m flat and 7 m of nothing.
    Only the LAST unit is rescaled, inside the bounds _candidates worked out."""
    pool = [c for c in cands if min_w - 1e-9 <= c['uw'] <= run + 1e-9]
    if not pool:
        return [], run
    pool.sort(key=lambda c: -c['uw'])
    over = max(c['uw_hi'] - c['uw'] for c in pool)
    NN = int(round((run + over) / FILL_STEP)) + 2
    best = [None] * (NN + 1)
    best[0] = (0.0, ())
    for j in range(NN + 1):
        cur = best[j]
        if cur is None:
            continue
        s, ch = cur
        for i, c in enumerate(pool):
            ns = s + c['uw']
            if ns > run + (c['uw_hi'] - c['uw']) + 1e-9:
                continue
            k = int(round(ns / FILL_STEP))
            if k > NN:
                continue
            if best[k] is None or len(ch) + 1 < len(best[k][1]):
                best[k] = (ns, ch + (i,))
    pick, score = None, None
    for cur in best:
        if not cur or not cur[1]:
            continue
        s, ch = cur
        last = pool[ch[-1]]
        target = _clamp(last['uw'] + (run - s), last['uw_lo'], last['uw_hi'])
        left = run - s - (target - last['uw'])
        if left < -0.01:  # would run past the end of the plate
            continue
        sc = (round(abs(left), 3), len(ch))
        if score is None or sc < score:
            pick, score = (ch, target, left), sc
    if pick is None:
        return [], run
    ch, target, left = pick
    chosen = [dict(pool[i]) for i in ch]
    last = chosen[-1]
    if abs(target - last['uw']) > 1e-6:
        last['scale'] *= target / last['uw']
        last['rescaled'] = round(target / last['uw'], 4)
        last['uw'] = target
    return chosen, left


def _dedupe_partitions(d: Drawing, ids: list, tol: float = DEDUPE_TOL) -> set:
    """One partition per shared edge. A party wall that a unit's own plan also
    drew is the same wall twice — keep the first, drop the copy, unless a door
    hangs on it (then it is a real wall with an opening, not a spare)."""
    doors = [(o['x'], o['z']) for o in d.objs if o['kind'] == 'door']
    seen, drop = [], []
    for i in ids:
        o = d.find(i)
        if not o or o['kind'] != 'partition':
            continue
        L = _num((o['p'] or {}).get('len'), 0.0)
        pa, pb = A._wall_world(o, 0.0), A._wall_world(o, L)
        hit = None
        for qa, qb in seen:
            if (
                math.hypot(pa[0] - qa[0], pa[1] - qa[1]) <= tol and math.hypot(pb[0] - qb[0], pb[1] - qb[1]) <= tol
            ) or (math.hypot(pa[0] - qb[0], pa[1] - qb[1]) <= tol and math.hypot(pb[0] - qa[0], pb[1] - qa[1]) <= tol):
                hit = True
                break
        if hit is None:
            seen.append((pa, pb))
        elif not any(_seg_point_dist(pa, pb, p) < 0.6 for p in doors):
            drop.append(o)
    if drop:
        d.remove(drop)
    return {o['id'] for o in drop}


def t_tile_units(
    d: Drawing,
    a,
    group='',
    storey=0,
    corridor_w=1.8,
    pack='swiss_dwellings',
    depth_tol=0.8,
    min_unit_w=4.5,
    max_scale=0.08,
    keep_core=True,
    name='',
):
    pk = packs()
    if not pk:
        return (
            f'refused: no plan packs under {plans_dir()} — the converters write them to data/architecture/plans/<pack>/'
        )
    pname = str(pack or 'swiss_dwellings').strip()
    if pname not in pk:
        return f'refused: no pack "{pname}" — the packs here are {", ".join(sorted(pk))}'
    rows = _unit_rows(pname)
    if not rows:
        return (
            f'refused: "{pname}" holds no unit plans, only '
            + ', '.join(f'{c} {kk}' for kk, c in sorted((pk[pname]['manifest'].get('count') or {}).items()) if c)
            + ' — tile_units needs kind="unit"'
        )
    grp_in = str(group or '').strip()
    if not grp_in:
        return (
            'refused: tile_units needs group="<the name draw_box returned>" — the box whose slab at '
            '`storey` is the floor to fill'
        )
    st = int(_num(storey, 0))
    rect, y, err = _group_plate(d, grp_in, st)
    if err:
        return err
    x0, z0, x1, z1 = rect
    W, D = x1 - x0, z1 - z0
    cw = _num(corridor_w, 1.8)
    if cw < CORRIDOR_MIN:
        return (
            f'refused: a {cw:g} m corridor is under the {CORRIDOR_MIN:g} m clear minimum — two people '
            f'cannot pass and a wheelchair cannot turn. Use corridor_w=1.8 (spec("corridor"))'
        )
    min_w = max(2.0, _num(min_unit_w, 4.5))
    tol = max(0.05, _num(depth_tol, 0.8))
    ms = _clamp(_num(max_scale, 0.08), 0.0, 0.12)
    along_x = W >= D
    span, run = (D, W) if along_x else (W, D)
    if span < 2 * min_w:
        return (
            f'refused: "{grp_in}" is {W:g} x {D:g} m — {span:g} m across cannot hold two bands of '
            f'{min_w:g} m units either side of a corridor; it needs at least {2 * min_w:g} m across. '
            f'Use place_plan for a single plan in a block this narrow'
        )

    # the corridor band, shifted so the core it has to serve stands IN it -------
    cores = (
        (_core_rects(d, grp_in, st, rect) + _approach_rects(d, grp_in, st, rect) + _landing_rects(d, grp_in, st, rect))
        if keep_core
        else []
    )
    band_w = cw
    lo_ax, hi_ax = (z0, z1) if along_x else (x0, x1)
    c_lo = (lo_ax + hi_ax) / 2 - band_w / 2
    core_note = ''
    if cores:
        k0 = min((r[1] if along_x else r[0]) for r in cores)
        k1 = max((r[3] if along_x else r[2]) for r in cores)
        band_w = max(cw, (k1 - k0) + 0.2)
        c_lo = _clamp((k0 + k1) / 2 - band_w / 2, lo_ax, hi_ax - band_w)
        if band_w > cw + 1e-6:
            core_note = (
                f'the corridor was widened to {band_w:.2f} m and moved beside the core so the stair/lift stands in it'
            )
        elif abs((c_lo + band_w / 2) - (lo_ax + hi_ax) / 2) > 0.05:
            core_note = 'the corridor was moved off centre so the core stands in it'
    c_hi = c_lo + band_w
    dA, dB = c_lo - lo_ax, hi_ax - c_hi
    if min(dA, dB) < BAND_MIN:
        return (
            f'refused: a {band_w:.2f} m corridor across a {span:g} m plate leaves bands of {dA:.1f} and '
            f'{dB:.1f} m — under the {BAND_MIN:g} m a dwelling needs. Widen the box, drop corridor_w, '
            f'or pass keep_core=false'
        )

    bands = (
        [('north', z0, c_lo, dA, 'south'), ('south', c_hi, z1, dB, 'north')]
        if along_x
        else [('west', x0, c_lo, dA, 'east'), ('east', c_hi, x1, dB, 'west')]
    )

    # who fits, and how the run is filled -------------------------------------
    picks = []
    for bname, b0, b1, bd, want in bands:
        cands, near_miss = _candidates(rows, bd, tol, min_w, ms)
        if not cands:
            if near_miss:  # the depth was near enough; the unit itself was not
                near_miss.sort(key=lambda t: abs(t[0] - bd))
                return (
                    f'refused: no {pname} unit can fill the {bd:.1f} m {bname} band — '
                    + '; '.join(t[1] for t in near_miss[:3])
                    + '. Pass a smaller min_unit_w, or a corridor_w that lands the band on a '
                    'depth the pack stocks'
                )
            near = _nearest_depths(rows, bd)
            need = math.ceil((max(abs(v - bd) for v in near) + 0.05) * 10) / 10 if near else tol * 2
            # a corridor is only worth naming if widening it actually lands the band
            # on a depth the pack stocks — and still leaves a corridor you can walk
            alt = [round(span - 2 * v, 1) for v in near if span - 2 * v >= CORRIDOR_MIN]
            return (
                f'refused: no unit in {pname} is {bd:.1f} ± {tol:g} m deep — nearest depths '
                + ' and '.join(f'{v:g}' for v in near)
                + f'; pass depth_tol={need:g}'
                + (
                    f' or corridor_w={min(alt):g}'
                    if alt
                    else f' — no corridor_w lands a {span:g} m plate on one of those depths'
                )
            )
        chosen, left = _fill(cands, run, min_w)
        if not chosen:
            return (
                f'refused: the {bd:.1f} m {bname} band runs {run:g} m and the narrowest {pname} unit '
                f'that suits it is {min(c["uw"] for c in cands):.1f} m wide — nothing tiles it; pass '
                f'min_unit_w={min(c["uw"] for c in cands):.1f} or a longer box'
            )
        picks.append((bname, b0, b1, bd, want, chosen, left))

    # the object budget, before a single record is drawn ----------------------
    need = 6
    for _b in picks:
        for c in _b[5]:
            pl = load_plan(c['id']) or {}
            need += 3 + sum(len(pl.get(k) or []) for k in ('walls', 'rooms', 'doors', 'windows', 'fixtures'))
    if len(d.objs) + need > MAX_OBJECTS:
        return (
            f'refused: this floor is about {need} records and the drawing is at {len(d.objs)} of the '
            f'{MAX_OBJECTS} ceiling — tile a smaller plate, or place_plan one unit at a time'
        )

    IR = A.EXT_MODULES.get('interior_rooms')
    FL = A.EXT_MODULES.get('floor_layouts')
    if IR is None or FL is None:
        return (
            'refused: the interior_rooms and floor_layouts families must be loaded — tile_units draws '
            'its partitions and its corridor zone with theirs'
        )

    plate = str(name or '').strip() or f'{pname} floor'
    wall_mat = _group_wall_mat(d, grp_in)
    H = max(0.5, d.storey_h - 0.3)
    cgrp = f'{plate} st{st} corridor'
    ids: list = []
    if along_x:
        wlo = IR._partition(d, x0, c_lo, x1, c_lo, y, H, WALL_T, wall_mat, f'corridor wall north st{st}', cgrp)
        whi = IR._partition(d, x0, c_hi, x1, c_hi, y, H, WALL_T, wall_mat, f'corridor wall south st{st}', cgrp)
    else:
        wlo = IR._partition(d, c_lo, z0, c_lo, z1, y, H, WALL_T, wall_mat, f'corridor wall west st{st}', cgrp)
        whi = IR._partition(d, c_hi, z0, c_hi, z1, y, H, WALL_T, wall_mat, f'corridor wall east st{st}', cgrp)
    ids += [wlo['id'], whi['id']]

    core_runs = [((r[0], r[2]) if along_x else (r[1], r[3])) for r in cores]
    placed: list = []
    notes: list = []
    skipped = 0
    for bname, b0, b1, _bd, want, chosen, left in picks:
        host = wlo if abs(b1 - c_lo) < 1e-6 else whi
        off = x0 if along_x else z0
        for i, c in enumerate(chosen):
            a0, a1 = off, off + c['uw']
            off = a1
            urect = (a0, b0, a1, b1) if along_x else (b0, a0, b1, a1)
            if cores and any(_rects_overlap(urect, r) for r in cores):
                skipped += 1
                continue
            plan = load_plan(c['id'])
            if not plan:
                continue
            mirror = bool(i % 2)  # neighbours mirror, so party walls line up
            ugrp = f'{plate} st{st} {bname} {i + 1:02d}'
            if i > 0:
                pw_rec = (
                    IR._partition(d, a0, b0, a0, b1, y, H, WALL_T, wall_mat, f'party wall {ugrp}', ugrp)
                    if along_x
                    else IR._partition(d, b0, a0, b1, a0, y, H, WALL_T, wall_mat, f'party wall {ugrp}', ugrp)
                )
                ids.append(pw_rec['id'])
            res = _place(
                d,
                plan,
                urect,
                st,
                {
                    'y': y,
                    'grp': ugrp,
                    'group': grp_in,
                    'mirror': mirror,
                    'align': 'entrance',
                    'entrance_side': want,
                    'scale': c['scale'],
                    'snap': 0.05,
                    'shell': False,
                    'entrance_wall': host,
                    'window_sides': {bname},
                    'wall_mat': wall_mat,
                    'keep_out': cores,
                },
            )
            if res['error']:
                notes.append(f'{c["id"]} was left out: {res["error"].replace("refused: ", "")}')
                continue
            ids += res['ids']
            placed.append(
                {
                    'id': c['id'],
                    'uw': c['uw'],
                    'mirror': mirror,
                    'band': bname,
                    'scale': res['scale'],
                    'rescaled': c.get('rescaled'),
                }
            )
            record_attribution(d, pname, c['id'])
        if left > FILL_OK:
            notes.append(f'{left:.1f} m of the {bname} band is left over — no unit in {pname} fills it')

    # the corridor itself, in the bays the core does not take ----------------
    for g0, g1 in _free_spans((x0, x1) if along_x else (z0, z1), core_runs):
        if g1 - g0 < 0.5:
            continue
        zr = (g0, c_lo, g1, c_hi) if along_x else (c_lo, g0, c_hi, g1)
        ids.append(FL._zone(d, zr[0], zr[1], zr[2], zr[3], y, f'Corridor st{st}', 'corridor', cgrp)['id'])

    if not placed:
        d.remove([o for o in (d.find(i) for i in ids) if o])
        return (
            f'refused: no unit could be drawn on storey {st} of "{grp_in}" — every bay was taken by the '
            f'core. Pass keep_core=false, or move the stair'
        )
    gone = _dedupe_partitions(d, ids, DEDUPE_TOL)
    ids = [i for i in ids if i not in gone]

    store = d.ext.get(EXT_KEY)
    if not isinstance(store, dict):
        store = {}
    with A._Scale(d.cell_m):
        cf, ct = A.cell_of(x0, z0), A.cell_of(x1 - 1e-6, z1 - 1e-6)
    store[str(st)] = {
        'use': 'plan_tiles',
        'ids': ids,
        'cell_from': cf,
        'cell_to': ct,
        'pack': pname,
        'plans': [p['id'] for p in placed],
        'plate': plate,
        'units': len(placed),
        'corridor_w': round(band_w, 2),
        'unit_w': round(sum(p['uw'] for p in placed) / len(placed), 2),
        'depth': round(min(dA, dB), 2),
        'bands': [round(dA, 2), round(dB, 2)],
        'along': 'x' if along_x else 'z',
    }
    d.ext[EXT_KEY] = store
    d.selected = ids[:200]

    shown = ', '.join(f'{p["id"]} {"mirrored " if p["mirror"] else ""}{p["uw"]:.1f} m' for p in placed[:6])
    depths = f'{dA:.1f} m' if abs(dA - dB) < 0.05 else f'{dA:.1f} and {dB:.1f} m'
    return (
        f'storey {st}: {len(placed)} units ({shown}{", …" if len(placed) > 6 else ""}) in two bands of '
        f'{depths} depth, corridor {band_w:.2f} m running '
        f'{"east-west" if along_x else "north-south"} for {run:g} m, {len(ids)} records'
        + (f'; {skipped} core bay(s) kept free' if skipped else '')
        + (f'; {len(gone)} duplicate party wall(s) deduped' if gone else '')
        + (f'. {core_note[0].upper()}{core_note[1:]}.' if core_note else '.')
        + (' ' + ' '.join(n.rstrip('.') + '.' for n in notes) if notes else '')
        + f' repeat_floor(from_storey, to_storey, source_storey={st}) carries it up.'
        + f' CREDIT: {attribution_of(pname)}'
    )
