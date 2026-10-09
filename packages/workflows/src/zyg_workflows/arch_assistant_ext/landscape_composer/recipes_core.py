# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landscape_composer/recipes_core.py — the step runner and the alpine / river_valley / forest_lake recipes.

Moved verbatim out of landscape_composer.py (lines 714-1092).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.landscape_composer.constants import (
    BOULDER_M,
    CLEARING_M,
    DRAPE_MAX_M,
    GROUND_STYLE,
    MAX_TREE_OF_PEAK,
    PEAK_H_CAP,
    PEAK_H_OF_R,
    PEAK_R_OF_W,
    RANGE_PEAKS,
    RIVER_W,
    STREAM_W,
    TREE_H,
    VALLEY_D_OF_W,
    _A,
    block_bounds,
    cell_name,
    math,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.checks import (
    _at,
    _bands,
    _block_cells,
    _cell_m,
    _cells_m,
    _clamp,
    _f,
    _meander_m,
    _mid,
    _river_nodes,
    _span,
    _sq,
    _walk,
)


# ── the step runner ───────────────────────────────────────────────────────────
def _run(d, scene, steps):
    """steps: [(label, sentence, tool, args)]. Runs them in order, stopping dead
    on the first refusal. Returns the summary text."""
    lines, tools = [], []
    for label, sentence, tool, args in steps:
        res = _A.call_tool(d, tool, args)
        low = (res or '').lower()
        if low.startswith('refused') or low.startswith('bad arguments') or low.startswith('unknown tool'):
            return 'refused: %s stopped at step "%s" — %s' % (scene, label, res)
        tools.append(tool)
        ids = [w.strip('.,') for w in str(res).split() if w.startswith('o') and w[1:].isdigit()]
        lines.append('  %s: %s (%s%s)' % (label, sentence, tool, (' -> ' + ', '.join(ids[:6])) if ids else ''))
    head = '%s landscape over %d elements, %d tool calls: %s' % (scene, len(steps), len(steps), ', '.join(tools))
    return head + '\n' + '\n'.join(lines)


def _ground_step(cf, ct, scene, seed, nm, water_level=None):
    """Step one of every recipe: THE ground, the one surface the scene is cut
    out of. Nothing after this may add a second."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    style = GROUND_STYLE[scene]
    args = {
        'cell_from': cell_name(ca, ra),
        'cell_to': cell_name(cb, rb),
        'style': style,
        'seed': seed,
        'name': ('%s ground' % nm) if nm else '%s ground' % scene,
    }
    if water_level is not None:
        args['water_level'] = water_level
    return ('ground', 'one %s sculpted ground under the whole block' % style, 'make_ground', args)


SPLIT_ARGS = ('count', 'flowers', 'reeds')


def _drape(label, sentence, tool, ca, ra, cb, rb, args, seed, nm, max_m=DRAPE_MAX_M, seeded=True):
    """One block tool laid over a block in a GRID of patches, each at most
    max_m a side.

    Every tool that covers an area has its own per-CALL ceiling, and they are
    all different: a forest holds 3000 trees, a polder 400 ditch rows, a rock
    field 400 boulders, and all of them refuse a block over 600 m. A kilometre
    block trips every one of those, so the composer hands them patches instead
    and lets the tool tile inside each. Counts in SPLIT_ARGS are the whole
    scene's, so they are divided over the patches — the scene keeps its
    density whatever the block size. On a block already under max_m this is
    exactly one patch with the args untouched."""
    cols, rows = _bands(ca, cb, max_m), _bands(ra, rb, max_m)
    n = len(cols) * len(rows)
    out, i = [], 0
    for r0, r1 in rows:
        for c0, c1 in cols:
            a = dict(args)
            a['cell_from'] = cell_name(c0, r0)
            a['cell_to'] = cell_name(c1, r1)
            if seeded:
                a['seed'] = seed + i
            if n > 1:
                for key in SPLIT_ARGS:
                    if key in a:
                        a[key] = int(_clamp(round(_f(a[key]) / n), 1, 1e9))
            if nm:
                a['name'] = '%s %s %d' % (nm, label, i + 1)
            out.append((label if n == 1 else '%s_%d' % (label, i + 1), sentence, tool, a))
            i += 1
    return out


# ── the recipes ───────────────────────────────────────────────────────────────
def _r_alpine(cf, ct, seed, nm):
    """The old verdict: 'the valley is a raised straight-edged plinth'. It was —
    a solid `valley` box added on top of a flat terrain. Now the valley is a
    HOLE cut through the ground and the peaks are sculpts of the same surface."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, _D = x1 - x0, z1 - z0
    mr0, mr1 = _span(ra, rb, 0.00, 0.34)  # the range, on the far (north) side
    vr0, vr1 = _span(ra, rb, 0.36, 0.62)  # the valley cut across the middle
    sr0, sr1 = _span(ra, rb, 0.62, 0.80)  # open shore below the valley mouth
    fr0, fr1 = _span(ra, rb, 0.80, 1.00)  # the conifer wood on the near flat
    vmid = _mid(vr0, vr1)
    across = _cells_m(vr0, vr1)  # the valley's width, in METRES
    band = _cells_m(mr0, mr1)  # how deep the range band is
    # R7-for-mountains: the ONE landform that scales with its block
    peak_r = min(PEAK_R_OF_W * W, 0.5 * band)
    peak_h = min(PEAK_H_OF_R * peak_r, PEAK_H_CAP)
    # R8: a conifer is 16 m, but never more than 0.3 of the summit it stands under
    conifer = round(_clamp(min(TREE_H['conifer'], MAX_TREE_OF_PEAK * peak_h * 0.98), 8.0, 25.0), 2)
    depth = round(_clamp(VALLEY_D_OF_W * across, 2.0, 0.38 * across), 2)
    lake_r = round(_clamp(min(0.20 * W, 0.42 * _cells_m(vr0, vr1)), 5.0, 120.0), 2)
    lake_c = _at(ca, cb, 0.82)
    steps = [
        _ground_step(cf, ct, 'alpine', seed, nm),
        (
            'valley',
            'a %g m trough CUT through the middle of the ground, not a box on it' % depth,
            'lower_ground',
            {
                'cell_from': cell_name(ca, vr0),
                'cell_to': cell_name(cb, vr1),
                'depth': depth,
                'shape': 'valley',
                'profile': 0.35,
                'seed': seed,
                'name': (nm + ' valley') if nm else 'alpine valley',
            },
        ),
    ]
    rmid = _mid(mr0, mr1)
    for i in range(RANGE_PEAKS):
        fx = (2.0 * i + 1.0) / (2.0 * RANGE_PEAKS)
        c0, c1, r = _sq(_at(ca, cb, fx), rmid, peak_r, ca, ra, cb, rb)
        h = round(_clamp(peak_h, 0.26 * r, 0.98 * r), 2)
        steps.append(
            (
                'peak_%d' % (i + 1),
                'a %g m summit sculpted out of the ground itself' % h,
                'raise_ground',
                {
                    'cell_from': c0,
                    'cell_to': c1,
                    'height': h,
                    'shape': 'peak',
                    'seed': seed + i,
                    'name': ('%s peak %d' % (nm, i + 1)) if nm else 'alpine peak %d' % (i + 1),
                },
            )
        )
    steps.append(
        (
            'stream',
            'a %g m stream carved down the valley FLOOR to the tarn' % STREAM_W[0],
            'carve_river',
            {
                'cells': [cell_name(c, vmid) for c in _river_nodes(_at(ca, cb, 0.04), _at(ca, cb, 0.66))],
                'width': STREAM_W[0],
                'depth': STREAM_W[1],
                'meander': _meander_m(W, STREAM_W[0], 2.0),
                'seed': seed,
                'name': (nm + ' stream') if nm else 'alpine stream',
            },
        )
    )
    steps.append(
        (
            'tarn',
            'a tarn in a basin at the valley mouth',
            'fill_lake',
            {
                'centre': cell_name(lake_c, vmid),
                'radius': lake_r,
                'radius_z': round(lake_r * 0.7, 2),
                'depth': 3.0,
                'irregularity': 0.3,
                'seed': seed,
                'name': (nm + ' tarn') if nm else 'alpine tarn',
            },
        )
    )
    steps += _drape(
        'rocks',
        'loose rock down the northern valley side',
        'scatter_rocks',
        ca,
        _span(ra, rb, 0.33, 0.37)[0],
        cb,
        _span(ra, rb, 0.33, 0.37)[1],
        {'count': int(_clamp(round(W * 0.35), 20, 300)), 'size': BOULDER_M},
        seed,
        nm,
    )
    steps += _drape(
        'forest',
        'a %g m conifer wood on the flat below the shore' % conifer,
        'plant_forest',
        ca,
        fr0,
        cb,
        fr1,
        {'density': 0.025, 'mix': 'conifer', 'height': conifer},
        seed,
        nm,
    )
    return steps


def _r_river_valley(cf, ct, seed, nm):
    """The old verdict: 'one lozenge'. One `river` solid lying on a lawn. Now
    the river is carved: 4+ reaches of sculpt_channel crossing the whole block
    with a water_path lying in each."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, D = x1 - x0, z1 - z0
    along_x = W >= D
    a, b = (ra, rb) if along_x else (ca, cb)
    f0 = _span(a, b, 0.00, 0.20)  # forest, far edge
    m0 = _span(a, b, 0.20, 0.32)  # meadow, far bank
    vv = _span(a, b, 0.32, 0.68)  # the trough
    m1 = _span(a, b, 0.68, 0.80)  # meadow, near bank
    f1 = _span(a, b, 0.80, 1.00)  # forest, near edge
    across = _cells_m(vv[0], vv[1])
    run = W if along_x else D
    vmid = _mid(vv[0], vv[1])
    rw = round(_clamp(run * 0.04, RIVER_W[0], RIVER_W[1]), 2)
    depth = round(_clamp(across * VALLEY_D_OF_W, 2.0, 0.38 * across), 2)

    def blk(band):
        return (ca, band[0], cb, band[1]) if along_x else (band[0], ra, band[1], rb)

    # far more than the 3 reaches the brief asks for, and each short enough to
    # follow the trough it lies in — see _river_nodes
    ends = (ca, cb) if along_x else (ra, rb)
    idx = _river_nodes(ends[0], ends[1])
    cells = [cell_name(i, vmid) for i in idx] if along_x else [cell_name(vmid, i) for i in idx]

    steps = [
        _ground_step(cf, ct, 'river_valley', seed, nm),
        (
            'valley',
            'a %g m U-trough cut down the long axis of the ground' % depth,
            'lower_ground',
            {
                'cell_from': cell_name(blk(vv)[0], blk(vv)[1]),
                'cell_to': cell_name(blk(vv)[2], blk(vv)[3]),
                'depth': depth,
                'shape': 'valley',
                'profile': 0.75,
                'seed': seed,
                'name': (nm + ' valley') if nm else 'river valley',
            },
        ),
        (
            'river',
            'a %g m river carved in %d reaches across the WHOLE block' % (rw, len(idx) - 1),
            'carve_river',
            {
                'cells': cells,
                'width': rw,
                'depth': round(_clamp(rw * 0.25, 0.5, 4.0), 2),
                'meander': _meander_m(run, rw, rw * 0.8),
                'seed': seed,
                'name': (nm + ' river') if nm else 'river',
            },
        ),
    ]
    for tag, bd in (('far', m0), ('near', m1)):
        q = blk(bd)
        steps += _drape(
            'meadow_' + tag,
            'a flowering meadow draped on the %s bank' % tag,
            'add_meadow',
            q[0],
            q[1],
            q[2],
            q[3],
            {'flowers': int(_clamp(round(run * 2), 20, 600))},
            seed,
            nm,
        )
    for tag, bd in (('far', f0), ('near', f1)):
        q = blk(bd)
        steps += _drape(
            'forest_' + tag,
            '12 m mixed woodland on the %s edge' % tag,
            'plant_forest',
            q[0],
            q[1],
            q[2],
            q[3],
            {'density': 0.03, 'mix': 'mixed', 'height': TREE_H['deciduous']},
            seed,
            nm,
        )
    line = [cell_name(i, m1[0]) for i in _walk(ca, cb)] if along_x else [cell_name(m1[0], i) for i in _walk(ra, rb)]
    steps.append(
        (
            'poplars',
            'a line of 20 m poplars along the near bank',
            'plant_tree_line',
            {
                'model': 'parametric',
                'cells': line,
                'spacing': 8.0,
                'kind': 'poplar',
                'height': TREE_H['poplar'],
                'seed': seed,
                'name': (nm + ' poplars') if nm else 'poplars',
            },
        )
    )
    return steps


def _r_forest_lake(cf, ct, seed, nm):
    """The old verdict: 'the wood covers the block wall to wall and the lake is
    not visible'. The wood WAS planted over the whole block, lake and all. Now
    the basin is dug FIRST and the wood goes in four strips around it, held
    CLEARING_M back from the water on every side."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, D = x1 - x0, z1 - z0
    cm = _cell_m()
    cc, rc = _mid(ca, cb), _mid(ra, rb)
    rx = round(_clamp(min(0.16 * W, 0.16 * D), 5.0, 120.0), 2)
    rz = round(rx * 0.75, 2)
    # the clearing: the lake's own footprint plus CLEARING_M of open shore, in
    # whole cells and then one more, so the MEASURED gap is never under it
    hcx = int(math.ceil((rx + CLEARING_M) / cm))
    hcz = int(math.ceil((rz + CLEARING_M) / cm))
    kc0, kc1 = cc - hcx, cc + hcx
    kr0, kr1 = rc - hcz, rc + hcz
    steps = [
        _ground_step(cf, ct, 'forest_lake', seed, nm),
        (
            'lake',
            'the lake basin dug FIRST, %g x %g m, so the wood can be kept off it' % (2 * rx, 2 * rz),
            'fill_lake',
            {
                'centre': cell_name(cc, rc),
                'radius': rx,
                'radius_z': rz,
                'depth': 4.0,
                'irregularity': 0.35,
                'seed': seed,
                'name': (nm + ' lake') if nm else 'forest lake',
            },
        ),
    ]
    strips = [
        ('north', ca, ra, cb, min(kr0 - 1, rb)),
        ('south', ca, max(kr1 + 1, ra), cb, rb),
        ('west', ca, max(kr0, ra), min(kc0 - 1, cb), min(kr1, rb)),
        ('east', max(kc1 + 1, ca), max(kr0, ra), cb, min(kr1, rb)),
    ]
    for i, (tag, c0, r0, c1, r1) in enumerate(strips):
        if c1 < c0 or r1 < r0:
            continue
        steps += _drape(
            'forest_' + tag,
            'the %s arm of the wood, %g m clear of the water' % (tag, CLEARING_M),
            'plant_forest',
            c0,
            r0,
            c1,
            r1,
            {'density': 0.025, 'mix': 'mixed', 'height': TREE_H['deciduous']},
            seed + 3 * i,
            nm,
        )
    er0, er1 = _span(ra, rb, 0.00, 0.10)
    steps += _drape(
        'undergrowth',
        'brush along the northern forest edge',
        'add_undergrowth',
        ca,
        er0,
        cb,
        er1,
        {'count': int(_clamp(round(W * 1.2), 10, 400))},
        seed,
        nm,
    )
    steps += _drape(
        'rocks',
        'a rocky western shore',
        'scatter_rocks',
        ca,
        max(kr0, ra),
        max(min(kc0 - 1, cb), ca),
        min(kr1, rb),
        {'count': int(_clamp(round(W * 0.4), 5, 200)), 'size': BOULDER_M},
        seed,
        nm,
    )
    return steps
