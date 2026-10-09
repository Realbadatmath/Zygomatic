# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""landscape_composer/recipes_more.py — the coast / polder / heath / canyon recipes and the RECIPES table.

Moved verbatim out of landscape_composer.py (lines 1093-1507).
"""

from __future__ import annotations

from zyg_workflows.arch_assistant_ext.landscape_composer.constants import (
    BERM_H,
    BERM_W,
    BOULDER_M,
    CANYON_DEPTH,
    CLIFF_M,
    DUNE_M,
    MESA_H_OF_R,
    MESA_R_OF_W,
    POLDER_MAX_M,
    RIVER_W,
    SEA_LEVEL,
    SMALL_BOULDER_M,
    SWELL_H_CAP,
    SWELL_H_OF_R,
    SWELL_R_OF_W,
    TREE_H,
    WINDMILL_M,
    block_bounds,
    cell_name,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.checks import (
    _at,
    _block_cells,
    _cells_m,
    _clamp,
    _meander_m,
    _mid,
    _river_nodes,
    _span,
    _sq,
    _walk,
)
from zyg_workflows.arch_assistant_ext.landscape_composer.recipes_core import (
    _drape,
    _ground_step,
    _r_alpine,
    _r_forest_lake,
    _r_river_valley,
)


def _r_coast(cf, ct, seed, nm):
    """The old verdict: 'sea and beach the same value so the waterline is
    invisible'. Both were solids of nearly the same grey. Now the sea is a
    translucent water_plane at SEA_LEVEL over a shelf dug into the ground, and
    the beach is the GROUND pulled down to just above that same datum and
    painted sand — so the line between them is a real edge."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, D = x1 - x0, z1 - z0
    sea = _span(ra, rb, 0.00, 0.40)
    shore = _at(ra, rb, 0.42)  # the waterline row
    dun = _span(ra, rb, 0.55, 0.80)
    ec0, ec1 = _span(ca, cb, 0.75, 1.00)  # the eastern quarter
    back = _at(ra, rb, 0.97)  # the BACK of it
    bw = round(_clamp(min(W, D) * 0.08, 4.0, 60.0), 2)
    return [
        _ground_step(cf, ct, 'coast', seed, nm, water_level=SEA_LEVEL),
        (
            'sea',
            'the sea: a shelf dug into the ground with a water plane at %g m' % SEA_LEVEL,
            'fill_sea',
            {
                'cell_from': cell_name(ca, sea[0]),
                'cell_to': cell_name(cb, sea[1]),
                'depth': 6.0,
                'level': SEA_LEVEL,
                'wave': 0.15,
                'seed': seed,
                'name': (nm + ' sea') if nm else 'coast sea',
            },
        ),
        (
            'beach',
            'a %g m beach: the ground itself pulled to the waterline and painted sand' % bw,
            'add_beach',
            {
                'cells': [cell_name(c, shore) for c in _walk(ca, cb, 200.0)],
                'width': bw,
                'height': 1.5,
                'seed': seed,
                'name': (nm + ' beach') if nm else 'coast beach',
            },
        ),
        (
            'dunes',
            '%g m dunes sculpted into the ground behind the beach' % DUNE_M,
            'add_dunes',
            {
                'cell_from': cell_name(ca, dun[0]),
                'cell_to': cell_name(cb, dun[1]),
                'height': DUNE_M,
                'seed': seed,
                'name': (nm + ' dunes') if nm else 'coast dunes',
            },
        ),
        (
            'cliff',
            'a %g m step in the ground at the BACK of the eastern quarter' % CLIFF_M[1],
            'add_cliff',
            {
                'cells': [cell_name(ec1, back), cell_name(ec0, back)],
                'height': CLIFF_M[1],
                'depth': 12.0,
                'ruggedness': 0.4,
                'seed': seed,
                'name': (nm + ' cliff') if nm else 'coastal cliff',
            },
        ),
        # no breakwater: fill_sea digs a 6 m shelf, and add_breakwater seats its
        # mole on the base plane, so it stood 6 m clear of the bed it is supposed
        # to be built up from. A mole belongs in the harbour scene, not here.
        (
            'stack',
            'a sea stack standing offshore',
            'add_sea_stack',
            {
                'centre': cell_name(_at(ca, cb, 0.12), _mid(sea[0], sea[1])),
                'radius': round(_clamp(min(W, D) * 0.03, 2.0, 12.0), 2),
                'height': 18.0,
                'seed': seed,
                'name': (nm + ' sea stack') if nm else 'sea stack',
            },
        ),
    ]


def _r_polder(cf, ct, seed, nm):
    """The one scene the operator passed. It keeps its shape; only the ground
    under it changed, from a solid terrain to a flat sculpted ground."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W = x1 - x0
    dyke = _span(ra, rb, 0.00, 0.12)
    fld = _span(ra, rb, 0.20, 0.78)
    low = _span(ra, rb, 0.80, 1.00)
    cmid = _mid(ca, cb)
    mc = _span(ca, cb, 0.0, 0.7)[1]
    drow = _mid(dyke[0], dyke[1])  # the dyke crest row
    steps = [
        _ground_step(cf, ct, 'polder', seed, nm),
        (
            'dyke',
            'a %g m berm %g m wide along the northern edge' % (BERM_H, BERM_W),
            'add_object',
            {
                'kind': 'berm',
                'cell': cell_name(cmid, drow),
                'params': {'len': round(W, 2), 'w': BERM_W, 'h': BERM_H},
                'material': 'mat_grass',
                'name': (nm + ' dyke') if nm else 'dyke',
            },
        ),
    ]
    steps += _drape(
        'polder_west',
        'a grass polder ringed by ditches',
        'make_polder',
        ca,
        fld[0],
        cmid,
        fld[1],
        {'ditch_width': 3.0, 'crop': 'grass', 'depth': 1.2},
        seed,
        nm,
        max_m=POLDER_MAX_M,
        seeded=False,
    )
    steps += _drape(
        'polder_east',
        'a tulip polder beside it',
        'make_polder',
        min(cmid + 1, cb),
        fld[0],
        cb,
        fld[1],
        {'ditch_width': 3.0, 'crop': 'tulips', 'depth': 1.2},
        seed,
        nm,
        max_m=POLDER_MAX_M,
        seeded=False,
    )
    steps += [
        (
            'poplars',
            '20 m poplars along the boundary between the two polders',
            'plant_tree_line',
            {
                'model': 'parametric',
                'cells': [cell_name(cmid, i) for i in _walk(fld[0], fld[1])],
                'spacing': 8.0,
                'kind': 'poplar',
                'height': TREE_H['poplar'],
                'seed': seed,
                'name': (nm + ' poplars') if nm else 'polder poplars',
            },
        ),
    ]
    steps += _drape(
        'meadow',
        'a flowering meadow on the low ground',
        'add_meadow',
        ca,
        low[0],
        mc,
        low[1],
        {'flowers': int(_clamp(round(W * 2), 20, 600))},
        seed,
        nm,
    )
    steps += _drape(
        'marsh',
        'a reed marsh in the far corner',
        'add_marsh',
        min(mc + 1, cb),
        low[0],
        cb,
        low[1],
        {'reeds': int(_clamp(round(W * 1.5), 15, 600))},
        seed,
        nm,
    )
    steps.append(
        (
            'windmill',
            'a %g m windmill standing on the dyke crest' % WINDMILL_M,
            'add_landmark',
            {
                'kind': 'windmill',
                'cell': cell_name(_at(ca, cb, 0.25), drow),
                'size': WINDMILL_M,
                'name': (nm + ' windmill') if nm else 'windmill',
            },
        )
    )
    return steps


def _r_heath(cf, ct, seed, nm):
    """The old verdict: 'empty'. It was flat ground with a few bushes on it.
    Now the ground itself rolls (two wide low swells raised out of it), the
    heather is three times as thick, the pond is a real basin and there is a
    tree line to give the horizon a scale."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, D = x1 - x0, z1 - z0
    u0 = _span(ra, rb, 0.02, 0.46)
    u1 = _span(ra, rb, 0.54, 0.98)
    cmid, rmid = _mid(ca, cb), _mid(ra, rb)
    # raise_ground will not build a peak flatter than 1:4, so the only way to
    # keep a swell a swell on a big heath is to keep it NARROW as well as low
    swell_r = min(SWELL_R_OF_W * min(W, D), SWELL_H_CAP / SWELL_H_OF_R)
    steps = [_ground_step(cf, ct, 'heath', seed, nm)]
    for i, (fx, fz) in enumerate(((0.28, 0.30), (0.70, 0.68))):
        c0, c1, r = _sq(_at(ca, cb, fx), _at(ra, rb, fz), swell_r, ca, ra, cb, rb)
        h = round(_clamp(SWELL_H_OF_R * r, 0.26 * r, 0.98 * r), 2)
        steps.append(
            (
                'swell_%d' % (i + 1),
                'a %g m swell raised out of the ground itself' % h,
                'raise_ground',
                {
                    'cell_from': c0,
                    'cell_to': c1,
                    'height': h,
                    'shape': 'peak',
                    'seed': seed + i,
                    'name': ('%s swell %d' % (nm, i + 1)) if nm else 'heath swell %d' % (i + 1),
                },
            )
        )
    steps.append(
        (
            'pond',
            'a pond lying in a basin dug into the heath',
            'fill_lake',
            {
                'centre': cell_name(cmid, rmid),
                'radius': round(_clamp(0.09 * min(W, D), 5.0, 60.0), 2),
                'depth': 1.5,
                'irregularity': 0.4,
                'seed': seed,
                'name': (nm + ' pond') if nm else 'heath pond',
            },
        )
    )
    steps.append(
        (
            'erratic',
            'a glacial erratic left standing on the heath',
            'add_boulder',
            {
                'centre': cell_name(_at(ca, cb, 0.82), _at(ra, rb, 0.18)),
                'size': 3.5,
                'seed': seed,
                'name': (nm + ' erratic') if nm else 'glacial erratic',
            },
        )
    )
    # 3x the old density: 'empty' was the verdict, and this is the answer to it
    for tag, bd, sd in (('north', u0, seed), ('south', u1, seed + 7)):
        steps += _drape(
            'heather_' + tag,
            'thick heather across the %s half (3x the old density)' % tag,
            'add_undergrowth',
            ca,
            bd[0],
            cb,
            bd[1],
            {'count': int(_clamp(round(W * 3.6), 30, 1200)), 'bush_radius': 0.7},
            sd,
            nm,
        )
    steps += _drape(
        'boulders',
        'boulders strewn through the heather',
        'scatter_rocks',
        ca,
        ra,
        cb,
        rb,
        {'count': int(_clamp(round(W * D * 0.004), 4, 300)), 'size': SMALL_BOULDER_M},
        seed,
        nm,
    )
    steps.append(
        (
            'tree_line',
            'a wind-bent line of 12 m trees along the southern edge',
            'plant_tree_line',
            {
                'model': 'parametric',
                'cells': [cell_name(i, rb) for i in _walk(ca, cb)],
                'spacing': 8.0,
                'kind': 'deciduous',
                'height': TREE_H['deciduous'],
                'seed': seed,
                'name': (nm + ' tree line') if nm else 'heath trees',
            },
        )
    )
    return steps


def _r_canyon(cf, ct, seed, nm):
    """The old verdict: 'two grey cones sitting ON a green lawn'. There was no
    canyon at all — two solid mesas and an escarpment stacked on flat terrain.
    Now a CANYON_DEPTH trough is cut clean through the block, a mesa stands on
    either side of it and the river runs on the floor of the cut."""
    ca, ra, cb, rb = _block_cells(cf, ct)
    x0, z0, x1, z1 = block_bounds(cf, ct)
    W, D = x1 - x0, z1 - z0
    cut = _span(ra, rb, 0.26, 0.74)  # the canyon, right through the block
    nb = _span(ra, rb, 0.00, 0.24)  # the north rim
    sb = _span(ra, rb, 0.76, 1.00)  # the south rim
    across = _cells_m(cut[0], cut[1])
    depth = round(min(CANYON_DEPTH, 0.38 * across), 2)
    rmid = _mid(cut[0], cut[1])
    rw = round(_clamp(min(W, D) * 0.03, RIVER_W[0], RIVER_W[1]), 2)
    mesa_r = min(MESA_R_OF_W * W, 0.5 * _cells_m(nb[0], nb[1]))
    steps = [
        _ground_step(cf, ct, 'canyon', seed, nm),
        (
            'canyon',
            'a %g m canyon cut clean THROUGH the block, walls following the rock' % depth,
            'lower_ground',
            {
                'cell_from': cell_name(ca, cut[0]),
                'cell_to': cell_name(cb, cut[1]),
                'depth': depth,
                'shape': 'valley',
                'profile': 0.1,
                'seed': seed,
                'name': (nm + ' canyon') if nm else 'canyon',
            },
        ),
    ]
    for i, (tag, fx, bd) in enumerate((('north', 0.32, nb), ('south', 0.68, sb))):
        c0, c1, r = _sq(_at(ca, cb, fx), _mid(bd[0], bd[1]), mesa_r, ca, ra, cb, rb)
        h = round(_clamp(MESA_H_OF_R * r, 3.0, 0.78 * r), 2)
        steps.append(
            (
                'mesa_' + tag,
                'a %g m table mountain on the %s rim' % (h, tag),
                'raise_ground',
                {
                    'cell_from': c0,
                    'cell_to': c1,
                    'height': h,
                    'shape': 'mesa',
                    'seed': seed + i,
                    'name': ('%s %s mesa' % (nm, tag)) if nm else '%s mesa' % tag,
                },
            )
        )
    steps.append(
        (
            'river',
            'a %g m river carved down the canyon FLOOR' % rw,
            'carve_river',
            {
                'cells': [cell_name(c, rmid) for c in _river_nodes(ca, cb)],
                'width': rw,
                'depth': round(_clamp(rw * 0.25, 0.5, 4.0), 2),
                'meander': _meander_m(W, rw, rw * 0.6),
                'seed': seed,
                'name': (nm + ' river') if nm else 'canyon river',
            },
        )
    )
    # SCREE AS STONES, NOT AS A SLAB. add_scree is the one cliffs_rocks tool with
    # no v3 branch: it still draws a solid `scree` box, and on a sculpted ground
    # a 300 x 12 m box lying at the wall foot renders as a white painted stripe —
    # the very 'thing parked on the lawn' this rebuild was for (both were looked
    # at: one long ribbon, then six short slabs, and the slabs were worse). A
    # talus is loose rock, so it is drawn as loose rock, thickest at the foot.
    for tag, bd in (('north', (0.26, 0.34)), ('south', (0.66, 0.74))):
        b0, b1 = _span(ra, rb, bd[0], bd[1])
        steps += _drape(
            'scree_' + tag,
            'a talus of loose rock at the %s wall foot' % tag,
            'scatter_rocks',
            ca,
            b0,
            cb,
            b1,
            {'count': int(_clamp(round(W * 0.9), 20, 400)), 'size': SMALL_BOULDER_M},
            seed + (11 if tag == 'south' else 0),
            nm,
        )
    steps += _drape(
        'rocks',
        'broken rock over the canyon floor',
        'scatter_rocks',
        ca,
        _at(ra, rb, 0.38),
        cb,
        _at(ra, rb, 0.62),
        {'count': int(_clamp(round(W * D * 0.002), 5, 300)), 'size': BOULDER_M},
        seed,
        nm,
    )
    return steps


RECIPES = {
    'alpine': _r_alpine,
    'river_valley': _r_river_valley,
    'forest_lake': _r_forest_lake,
    'coast': _r_coast,
    'polder': _r_polder,
    'heath': _r_heath,
    'canyon': _r_canyon,
}
