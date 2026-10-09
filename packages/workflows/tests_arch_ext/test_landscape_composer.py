# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_landscape_composer.py — the recipe family's proof.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_landscape_composer.py

landscape_composer adds NO kinds, so there is no tab geometry and no Blender
builder of its own. What CAN be wrong is the wiring: a recipe that calls a tool
with an argument the callee refuses, a recipe that half-builds a scene and
leaves it, a scene that quietly drops one of the elements it promised.

Then there is what the eye caught in the v2 renders, and what this file is now
mostly about. Every old landform was a SEPARATE SOLID laid on a flat base, so
nothing could cut into the ground: the alpine valley came out as a raised
straight-edged plinth, the canyon as two grey cones sitting on a lawn, the wood
covered the block wall to wall with the lake nowhere to be seen. v3 has one
sculpted heightfield per drawing and every landform is a sculpt that is summed
into it. So each recipe is now checked to lay ONE make_ground over the block
first and then only to cut, fill or drape — and to leave behind not a single
record of the old solid set (terrain, hill, valley, mountain, sea, beach,
river, lake...). Sizes are measured in real metres, the ground under each
record is sampled with that record hidden, and three scenes are rendered from
the air and looked at by a human.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    assistant,
    kinds_of,
    blender_doc,
    rail_has,  # noqa: E402
    tool_names,
    save_render,
)
from zyg_workflows import arch_assistant as A  # noqa: E402
import zyg_workflows.arch_assistant_ext.landscape_composer as L  # noqa: E402

G = A.EXT_MODULES['glossary_examples']
BLOCK = ('A1', A.cell_name(299, 299))  # 300 x 300 m at 1 m/cell: over every scene's minimum
SMALL = ('A1', A.cell_name(239, 239))  # 240 x 240 m: exactly the alpine floor
HALF_KM = ('A1', A.cell_name(299, 299))  # 600 m, on a 2 m grid
KM = ('A1', A.cell_name(199, 199))  # 1000 m, on a 5 m grid
RENDER_DIR = os.environ.get('ZYG_LANDSCAPE_RENDERS_DIR') or os.path.join(
    os.path.expanduser('~'), 'Documents', 'landscape_renders'
)
RENDERS = {
    'alpine': os.path.join(RENDER_DIR, 'qa_alpine_aerial.png'),
    'canyon': os.path.join(RENDER_DIR, 'qa_canyon_aerial.png'),
    'forest_lake': os.path.join(RENDER_DIR, 'qa_forest_lake_aerial.png'),
}

# what each recipe promises to put on the ground, in v3 kinds
PROMISED = {
    'alpine': (
        'ground',
        'sculpt_cut',
        'sculpt_peak',
        'sculpt_channel',
        'water_path',
        'sculpt_basin',
        'water_body',
        'rock_field',
        'forest',
    ),
    'river_valley': ('ground', 'sculpt_cut', 'sculpt_channel', 'water_path', 'meadow', 'forest', 'tree_line'),
    'forest_lake': ('ground', 'sculpt_basin', 'water_body', 'forest', 'undergrowth', 'rock_field'),
    'coast': ('ground', 'sculpt_shelf', 'water_plane', 'sculpt_flat', 'sculpt_dunes', 'sculpt_step', 'sea_stack'),
    'polder': ('ground', 'berm', 'crop_field', 'canal', 'tree_line', 'meadow', 'marsh', 'windmill'),
    'heath': (
        'ground',
        'sculpt_peak',
        'sculpt_basin',
        'water_body',
        'boulder',
        'undergrowth',
        'rock_field',
        'tree_line',
    ),
    'canyon': ('ground', 'sculpt_cut', 'sculpt_mesa', 'sculpt_channel', 'water_path', 'rock_field'),
}


def block_of(d, blk):
    """The block in REAL metres. A._Current does not restore the cell scale, so
    block_bounds on a 2 m or 5 m grid lies by that factor unless it is asked
    inside the drawing's own scale."""
    with A._Scale(d.cell_m):
        return A.block_bounds(blk[0], blk[1])


def rect_of(o):
    p = o.get('p') or {}
    hw, hd = 0.5 * L._f(p.get('w')), 0.5 * L._f(p.get('d'))
    return (o['x'] - hw, o['z'] - hd, o['x'] + hw, o['z'] + hd)


def reach_span_x(o):
    """(x0, x1) of a reach or its bed. A sculpt_channel is a LINE, not a box —
    it carries `len` along its own axis and `w` across it, and no `d` at all, so
    rect_of would read both halves as zero and every reach would measure as a
    point at its own centre."""
    p = o.get('p') or {}
    ry = L._f(o.get('ry'))
    half = abs(0.5 * L._f(p.get('len')) * math.cos(ry)) + abs(0.5 * L._f(p.get('w')) * math.sin(ry))
    return (o['x'] - half, o['x'] + half)


def clearing_m(d):
    """The narrowest gap between the lake's footprint and any forest tile edge."""
    wb = [o for o in d.objs if o['kind'] == 'water_body'][0]
    hx, hz = L.water_extent(wb)
    lx0, lz0, lx1, lz1 = wb['x'] - hx, wb['z'] - hz, wb['x'] + hx, wb['z'] + hz
    gaps = []
    for o in d.objs:
        if o['kind'] != 'forest':
            continue
        fx0, fz0, fx1, fz1 = rect_of(o)
        gaps.append(max(max(fx0 - lx1, lx0 - fx1), max(fz0 - lz1, lz0 - fz1)))
    return min(gaps) if gaps else 0.0


print('counts')
print('  scenes   %d' % len(L.SCENES))
print('  minimums %s' % L.MIN_METRES)

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in ('compose_landscape', 'describe_landscape', 'suggest_scene')), names)
check('no new kinds', L.KINDS == {} and L.OPENINGS == [], (L.KINDS, L.OPENINGS))
check('PROMPT is one paragraph under 1100 chars', 0 < len(L.PROMPT) <= 1100 and '\n' not in L.PROMPT, len(L.PROMPT))
check(
    'the PROMPT teaches the sculpted ground, the real sizes and the grid it needs',
    all(w in L.PROMPT for w in ('sculpted ground', 'REAL metres', '16 m', '240 m', '1000 m max', '10 m grid')),
    L.PROMPT[:200],
)
check('seven scenes, each with a recipe', len(L.SCENES) == 7 and sorted(L.SCENES) == sorted(L.RECIPES), L.SCENES)
check('every scene declares a minimum in metres', sorted(L.MIN_METRES) == sorted(L.SCENES), L.MIN_METRES)
check('every scene declares the ground style it is laid on', sorted(L.GROUND_STYLE) == sorted(L.SCENES), L.GROUND_STYLE)

# the real sizes are constants, not fractions of anything
check(
    'trees are absolute metres (conifer 16, deciduous 12, poplar 20, fruit 4)',
    L.TREE_H == {'conifer': 16.0, 'deciduous': 12.0, 'poplar': 20.0, 'fruit': 4.0},
    L.TREE_H,
)
check(
    'boulder 2.5 m, windmill tower 12 m, lamp 4 m',
    (L.BOULDER_M, L.WINDMILL_M, L.LAMP_M) == (2.5, 12.0, 4.0),
    (L.BOULDER_M, L.WINDMILL_M, L.LAMP_M),
)
check('a berm dyke is 4 m tall and 12 m wide', (L.BERM_H, L.BERM_W) == (4.0, 12.0), (L.BERM_H, L.BERM_W))
check(
    'R8 caps: tree <= 0.3 of the summit, boulder 4 m, windmill 22 m',
    (L.MAX_TREE_OF_PEAK, L.MAX_BOULDER_M, L.MAX_WINDMILL_M) == (0.3, 4.0, 22.0),
    (L.MAX_TREE_OF_PEAK, L.MAX_BOULDER_M, L.MAX_WINDMILL_M),
)
check(
    'a mountain is the ONE thing that scales with the block (r 0.15 W, h 0.8 r, cap 150 m)',
    (L.PEAK_R_OF_W, L.PEAK_H_OF_R, L.PEAK_H_CAP) == (0.15, 0.8, 150.0),
    (L.PEAK_R_OF_W, L.PEAK_H_OF_R, L.PEAK_H_CAP),
)
check(
    'the canyon is cut 25 m deep and the wood is held 15 m back from the water',
    (L.CANYON_DEPTH, L.CLEARING_M) == (25.0, 15.0),
    (L.CANYON_DEPTH, L.CLEARING_M),
)
check(
    'the old 400 m solid-terrain cap is gone; the ceiling is now a measured 1000 m',
    L.MAX_METRES == 1000.0 and L.DRAPE_MAX_M <= 300.0,
    (L.MAX_METRES, L.DRAPE_MAX_M),
)
check(
    'the old solid ground set is named so a scene can be checked clean of it',
    L.OLD_SOLID_GROUND
    == frozenset(
        (
            'terrain',
            'hill',
            'slope',
            'valley',
            'mountain',
            'mountain_range',
            'sea',
            'beach',
            'dune_field',
            'river',
            'lake',
        )
    ),
    sorted(L.OLD_SOLID_GROUND),
)

# ── the ground helper itself ──────────────────────────────────────────────────
print('ground_under')
dh = A.Drawing({'objects': []})
_t, dh = assistant('add_hill', {'centre': A.cell_name(149, 149), 'radius': 20, 'height': 6}, drawing=dh)
hill = dh.objs[-1]
check(
    'a hill reports its own summit under itself',
    abs(A.ground_height(dh, hill['x'], hill['z']) - 6.0) < 1e-6,
    A.ground_height(dh, hill['x'], hill['z']),
)
check(
    'ground_under hides the record and finds the base plane',
    abs(L.ground_under(dh, hill)) < 1e-9,
    L.ground_under(dh, hill),
)
check(
    '...and puts the record back exactly as it found it',
    hill.get('hidden') in (None, False) and abs(A.ground_height(dh, hill['x'], hill['z']) - 6.0) < 1e-6,
    hill.get('hidden'),
)
hill['hidden'] = True
check('a record that was already hidden stays hidden', L.ground_under(dh, hill) == 0.0 and hill['hidden'] is True)
hill['hidden'] = False
_t, dh = assistant('add_boulder', {'centre': A.cell_name(149, 149), 'size': 2.5}, drawing=dh)
rock = dh.objs[-1]
check(
    'ground_under a stone ON the hill reports the hill, not the base',
    abs(L.ground_under(dh, rock) - 6.0) < 1e-6,
    L.ground_under(dh, rock),
)
check('and that stone was placed on it (R1: no base_height means the ground)', abs(rock['y'] - 6.0) < 0.35, rock['y'])
check('ground_fault is quiet for a record on its ground', L.ground_fault(dh, rock) == '', L.ground_fault(dh, rock))
rock['y'] = 20.0
check(
    'ground_fault calls a lifted record FLOATING',
    L.ground_fault(dh, rock).startswith('floating'),
    L.ground_fault(dh, rock),
)
rock['y'] = 6.0
# 2026-09-08: plant_tree_line places real trees by default; this check is about
# the one-object tree_line record, so it asks for the parametric row
_t, dh = assistant(
    'plant_tree_line',
    {'cells': [A.cell_name(145, 149), A.cell_name(153, 149)], 'kind': 'conifer', 'height': 16, 'model': 'parametric'},
    drawing=dh,
)
tl = dh.objs[-1]
check(
    'a tree line planted on the hill lands on it (R1: no base_height means the ground)',
    tl['kind'] == 'tree_line' and abs(L._f(tl['y']) - L.ground_under(dh, tl)) <= L.GROUND_TOL,
    (tl['y'], L.ground_under(dh, tl)),
)
tl['y'] = L._f(tl['y']) - 4.0
check('ground_fault calls a sunk record BURIED', L.ground_fault(dh, tl).startswith('buried'), L.ground_fault(dh, tl))
check(
    'a ground SURFACE under another one is stacking, not burial',
    L.is_ground_kind('hill') and L.ground_fault(dh, hill) == '',
    L.ground_fault(dh, hill),
)
check(
    'a sculpt is a parameter of the ground, never a record standing on it',
    all(L.ground_fault(dh, {'kind': k, 'id': 'x', 'x': 0, 'z': 0, 'y': 99.0, 'p': {}}) == '' for k in L.SCULPT_KINDS),
    sorted(L.SCULPT_KINDS),
)

# ── every scene, composed for real ────────────────────────────────────────────
print('scenes')
DRAWINGS = {}
for scene in L.SCENES:
    txt, d = assistant('compose_landscape', {'cell_from': BLOCK[0], 'cell_to': BLOCK[1], 'scene': scene, 'seed': 3})
    DRAWINGS[scene] = (txt, d)
    check(
        '%s composes without a refusal' % scene,
        not txt.lower().startswith(('refused', 'bad arguments', 'unknown')),
        txt[:200],
    )
    got = kinds_of(d)
    missing = [k for k in PROMISED[scene] if not got.get(k)]
    check('%s draws all %d promised kinds' % (scene, len(PROMISED[scene])), not missing, (missing, sorted(got)))
    check('%s: no step in the summary reported a refusal' % scene, 'refused' not in txt.lower(), txt[:200])

sizes = {s: len(L.RECIPES[s](BLOCK[0], BLOCK[1], 3, '')) for s in L.SCENES}
check('every recipe is 6 to 12 calls %s' % sizes, all(6 <= n <= 12 for n in sizes.values()), sizes)
check(
    'every summary names its tools and ids',
    all(DRAWINGS[s][0].count('\n') == sizes[s] and ' -> o' in DRAWINGS[s][0] for s in L.SCENES),
    {s: DRAWINGS[s][0].count('\n') for s in L.SCENES},
)
STEPS = {s: L.RECIPES[s](BLOCK[0], BLOCK[1], 3, '') for s in L.SCENES}  # (label, sentence, tool, args)
check(
    'every recipe starts by laying ONE sculpted ground (make_ground, step 1)',
    all(STEPS[s][0][2] == 'make_ground' for s in L.SCENES),
    {s: STEPS[s][0][2] for s in L.SCENES},
)
(
    check(
        'no recipe calls a solid-ground tool after it',
        not [
            (s, c[2])
            for s in L.SCENES
            for c in STEPS[s][1:]
            if c[2]
            in (
                'make_terrain',
                'add_hill',
                'add_valley',
                'add_mountain',
                'add_mountain_range',
                'add_river',
                'add_lake',
                'make_coast',
            )
        ],
        [(s, c[2]) for s in L.SCENES for c in STEPS[s][1:]],
    ),
)
check(
    'no step passes base_height any more',
    not [(s, c[2]) for s in L.SCENES for c in STEPS[s] if 'base_height' in c[3]],
    [(s, c[2]) for s in L.SCENES for c in STEPS[s] if 'base_height' in c[3]],
)
check(
    'the ground is rolling under the alpine, gentle inland and flat on the reclaimed scenes',
    {s: STEPS[s][0][3]['style'] for s in L.SCENES}
    == dict(L.GROUND_STYLE)
    == {
        'alpine': 'rolling',
        'river_valley': 'gentle',
        'forest_lake': 'gentle',
        'heath': 'gentle',
        'canyon': 'gentle',
        'coast': 'flat',
        'polder': 'flat',
    },
    {s: STEPS[s][0][3]['style'] for s in L.SCENES},
)

x0, z0, x1, z1 = block_of(DRAWINGS['alpine'][1], BLOCK)
check(
    'nothing is drawn outside the block',
    all(all(x0 <= o['x'] <= x1 and z0 <= o['z'] <= z1 for o in DRAWINGS[s][1].objs) for s in L.SCENES),
    [
        (s, o['kind'], o['x'], o['z'])
        for s in L.SCENES
        for o in DRAWINGS[s][1].objs
        if not (x0 <= o['x'] <= x1 and z0 <= o['z'] <= z1)
    ][:4],
)
for scene in L.SCENES:
    d = DRAWINGS[scene][1]
    base = [o for o in d.objs if o['kind'] == L.GROUND_KIND]
    p = (base[0].get('p') or {}) if base else {}
    check(
        '%s: one ground record spans the whole block (%.0f x %.0f m)' % (scene, p.get('w', 0), p.get('d', 0)),
        len(base) == 1 and abs(p.get('w', 0) - (x1 - x0)) < 1.5 and abs(p.get('d', 0) - (z1 - z0)) < 1.5,
        (len(base), p.get('w'), p.get('d'), x1 - x0),
    )
    check(
        '%s: not one record of the old solid ground set survives' % scene,
        L.solid_ground_kinds(d) == [],
        L.solid_ground_kinds(d),
    )
    check(
        '%s: every landform is a sculpt of that ground, not a thing parked on it' % scene,
        all(o['kind'] not in L.OLD_SOLID_GROUND for o in d.objs) and any(o['kind'] in L.SCULPT_KINDS for o in d.objs)
        if scene != 'polder'
        else L.solid_ground_kinds(d) == [],
        sorted({o['kind'] for o in d.objs}),
    )

# ── R8: real sizes, real proportions ──────────────────────────────────────────
print('proportion')
for scene in L.SCENES:
    d = DRAWINGS[scene][1]
    trees = [o for o in d.objs if o['kind'] in L.TREE_KINDS]
    peaks = [o for o in d.objs if o['kind'] in L.PEAK_KINDS]
    th = max([L._hh(o) for o in trees] or [0.0])
    ph = max([L._hh(o) for o in peaks] or [0.0])
    if trees and peaks and ph >= L.PEAK_MIN_M:
        check(
            '%s: tallest tree %.1f m is at most 0.3 of the %.1f m summit' % (scene, th, ph),
            th <= L.MAX_TREE_OF_PEAK * ph + 1e-6,
            (th, ph, L.MAX_TREE_OF_PEAK * ph),
        )
    else:
        check(
            '%s: trees %.1f m stand alone (no mountain to be dwarfed by)' % (scene, th),
            6.0 <= th <= 25.0 or not trees,
            (th, len(trees), ph),
        )
    b = max(
        [L.boulder_across(o) for o in d.objs if o['kind'] == 'boulder']
        + [L._f((o.get('p') or {}).get('size')) for o in d.objs if o['kind'] == 'rock_field']
        or [0.0]
    )
    check(
        '%s: the biggest stone is %.1f m across (cap %g)' % (scene, b, L.MAX_BOULDER_M), b <= L.MAX_BOULDER_M + 1e-6, b
    )
w = [o for o in DRAWINGS['polder'][1].objs if o['kind'] == 'windmill'][0]
check(
    'polder: the mill is %.1f m to the sail tip (cap 22)' % L.windmill_top(w),
    L.windmill_top(w) <= L.MAX_WINDMILL_M,
    w['p'],
)
check(
    'polder: the dyke berm is 4 m tall and 12 m wide',
    any(
        abs(L._f(o['p'].get('h')) - 4.0) < 1e-6 and abs(L._f(o['p'].get('w')) - 12.0) < 1e-6
        for o in DRAWINGS['polder'][1].objs
        if o['kind'] == 'berm'
    ),
    [o['p'] for o in DRAWINGS['polder'][1].objs if o['kind'] == 'berm'],
)

# ── nothing buried, nothing floating ──────────────────────────────────────────
print('burial')
for scene in L.SCENES:
    d = DRAWINGS[scene][1]
    loose = [
        o
        for o in d.objs
        if o['kind'] not in L.WATER_KINDS
        and o['kind'] not in L.V3_WATER
        and o['kind'] not in L.SCULPT_KINDS
        and not L.is_ground_kind(o['kind'])
        and not L.is_tiled_drape(o)
    ]
    bad = [
        (o['kind'], o['id'], round(L._f(o['y']) - L.ground_under(d, o), 3))
        for o in loose
        if abs(L._f(o['y']) - L.ground_under(d, o)) > L.GROUND_TOL
    ]
    check(
        '%s: every one of its %d records sits within %g m of the ground under it' % (scene, len(d.objs), L.GROUND_TOL),
        not bad,
        bad,
    )
    # a tiled drape is seated on a least-squares plane over its own tile, so its
    # y is the plane's height and not the ground at its centre — drape_band is
    # what judges those, in the `loose` list above
    surf = [
        (o['kind'], o['id'], round(L._f(o['y']) - L.ground_under(d, o), 3))
        for o in d.objs
        if L.is_ground_kind(o['kind'])
        and o['kind'] != L.GROUND_KIND
        and not L.is_tiled_drape(o)
        and L._f(o['y']) - L.ground_under(d, o) > L.GROUND_TOL
    ]
    check('%s: no ground surface floats over the base' % scene, not surf, surf)
    wet = [
        (o['kind'], o['id'], round(L._f(o['y']) - L.ground_under(d, o), 3))
        for o in d.objs
        if o['kind'] in L.V3_LEVEL_WATER and L._f(o['y']) < L.ground_under(d, o) - 1e-3
    ]
    check('%s: still water never lies under its own bed' % scene, not wet, wet)
    # a reach FALLS, so it is asked at its middle station and against the lowest
    # ground across its own meander band — see surface_y / reach_bed
    flow = [
        (o['kind'], o['id'], round(L.surface_y(o, 0.5) - L.reach_bed(d, o), 3))
        for o in d.objs
        if o['kind'] in L.V3_FLOW_WATER and L.surface_y(o, 0.5) < L.reach_bed(d, o) - L.POOL_TOL
    ]
    check('%s: running water never runs above its bed' % scene, not flow, flow)
    check(
        '%s: landscape_warnings finds nothing to say' % scene,
        L.landscape_warnings(d) == [],
        L.landscape_warnings(d)[:3],
    )

# ── the seven verdicts the eye gave on v2, one scene at a time ────────────────
print('verdicts')
al = DRAWINGS['alpine'][1]
cut = [o for o in al.objs if o['kind'] == 'sculpt_cut'][0]
pk = [o for o in al.objs if o['kind'] == 'sculpt_peak']
check(
    'alpine: the valley is a %.0f m CUT %.0f m across, not a plinth added on top'
    % (L._f(cut['p'].get('depth')), L._f(cut['p'].get('w'))),
    L._f(cut['p'].get('depth')) > 10.0
    and L._f(cut['p'].get('len')) >= (x1 - x0) - 1.5
    and L._f(cut['p'].get('depth')) <= 0.4 * L._f(cut['p'].get('w')) + 1e-6,
    cut['p'],
)
check(
    'alpine: the floor of that cut really is below the plain (%.1f m at the middle)'
    % A.ground_height(al, cut['x'], cut['z']),
    A.ground_height(al, cut['x'], cut['z']) < -5.0,
    A.ground_height(al, cut['x'], cut['z']),
)
check(
    'alpine: the range is %d sculpted peaks of %.0f m on a radius of %.0f m (R7: h 0.25-1.0 r)'
    % (len(pk), L._f(pk[0]['p'].get('h')), L._f(pk[0]['p'].get('r'))),
    len(pk) == L.RANGE_PEAKS
    and all(0.25 * L._f(o['p'].get('r')) <= L._f(o['p'].get('h')) <= L._f(o['p'].get('r')) + 1e-6 for o in pk),
    [o['p'] for o in pk],
)
wp = [o for o in al.objs if o['kind'] in L.V3_FLOW_WATER]
check(
    'alpine: the stream lies on the carved valley floor, not on a hand-written 0.25',
    wp
    and all(
        L.reach_bed(al, o) - L.POOL_TOL
        <= L.surface_y(o, 0.5)
        <= L.reach_bed(al, o) + L.WATER_TOL + L._f((o.get('p') or {}).get('meander'))
        for o in wp
    )
    and all(L.surface_y(o, 0.5) < -5.0 for o in wp),
    [(round(L.surface_y(o, 0.5), 2), round(L.reach_bed(al, o), 2)) for o in wp],
)
check(
    'alpine: the tarn sits in a basin at the mouth, its rim standing over the water',
    any(o['kind'] == 'sculpt_basin' for o in al.objs)
    and all(
        sum(1 for g, wy in L.water_rim(al, o) if g > wy) >= len(L.water_rim(al, o)) // 2
        for o in al.objs
        if o['kind'] == 'water_body'
    ),
    [
        (round(L._f(o['y']), 2), [round(g, 1) for g, _ in L.water_rim(al, o)])
        for o in al.objs
        if o['kind'] == 'water_body'
    ],
)
check(
    'alpine: the wood stands on ground within 0.35 m of flat, not up the valley wall',
    all(
        A.ground_plane(al, o['x'], o['z'], L._f(o['p'].get('w')), L._f(o['p'].get('d')), L._f(o.get('ry')))[3] < 6.0
        for o in al.objs
        if o['kind'] == 'forest'
    ),
    [
        round(A.ground_plane(al, o['x'], o['z'], L._f(o['p'].get('w')), L._f(o['p'].get('d')), L._f(o.get('ry')))[3], 3)
        for o in al.objs
        if o['kind'] == 'forest'
    ],
)

rvd = DRAWINGS['river_valley'][1]
reaches = [o for o in rvd.objs if o['kind'] in L.V3_FLOW_WATER]
rx = [reach_span_x(o) for o in rvd.objs if o['kind'] == 'sculpt_channel']
check('river_valley: the river is %d reaches, not one lozenge' % len(reaches), len(reaches) >= 3, len(reaches))
check(
    'river_valley: those reaches cross the whole block (%.0f of %.0f m)'
    % ((max(r[1] for r in rx) - min(r[0] for r in rx)) if rx else 0.0, x1 - x0),
    rx and (max(r[1] for r in rx) - min(r[0] for r in rx)) >= 0.85 * (x1 - x0),
    rx,
)
check(
    'river_valley: meadows are draped on the banks, on the ground',
    [o for o in rvd.objs if o['kind'] == 'meadow']
    and all(L.ground_fault(rvd, o) == '' for o in rvd.objs if o['kind'] == 'meadow'),
    [L.ground_fault(rvd, o) for o in rvd.objs if o['kind'] == 'meadow'],
)

fl = DRAWINGS['forest_lake'][1]
lake = [o for o in fl.objs if o['kind'] == 'water_body'][0]
lhx, lhz = L.water_extent(lake)
check(
    'forest_lake: the lake is inside the block (%.0f x %.0f m at %.0f, %.0f)'
    % (2 * lhx, 2 * lhz, lake['x'], lake['z']),
    x0 <= lake['x'] - lhx and lake['x'] + lhx <= x1 and z0 <= lake['z'] - lhz and lake['z'] + lhz <= z1,
    (lake['x'], lake['z'], lhx, lhz, (x0, z0, x1, z1)),
)
check(
    'forest_lake: the basin is dug FIRST, before a single tree',
    [c[2] for c in STEPS['forest_lake']].index('fill_lake')
    < [c[2] for c in STEPS['forest_lake']].index('plant_forest'),
    [c[2] for c in STEPS['forest_lake']],
)
check(
    'forest_lake: the wood is 4 strips around a clearing, %.1f m clear of the water (>= 15)' % clearing_m(fl),
    len([o for o in fl.objs if o['kind'] == 'forest']) >= 4 and clearing_m(fl) >= L.CLEARING_M - 1e-6,
    (len([o for o in fl.objs if o['kind'] == 'forest']), clearing_m(fl)),
)
check(
    'forest_lake: the undergrowth is thin enough to walk through (density 0.025)',
    all(abs(L._f((o.get('p') or {}).get('density')) - 0.025) < 1e-9 for o in fl.objs if o['kind'] == 'forest'),
    [(o.get('p') or {}).get('density') for o in fl.objs if o['kind'] == 'forest'],
)

co = DRAWINGS['coast'][1]
sea = [o for o in co.objs if o['kind'] == 'water_plane'][0]
sand = [o for o in co.objs if o['kind'] == 'sculpt_flat']
step = [o for o in co.objs if o['kind'] == 'sculpt_step'][0]
shelf = [o for o in co.objs if o['kind'] == 'sculpt_shelf']
# the beach is a shelf too (add_beach lays a 0 m one to hold the sand level), so
# the one to ask about is the sea's own — the shelf under the water plane
seabed = [o for o in shelf if abs(o['z'] - sea['z']) <= 0.5 * L._f(sea['p'].get('d'))]
check(
    'coast: the sea is a plane over a shelf DUG into the ground, so the waterline shows',
    seabed
    and all(L._f(o['p'].get('depth')) > 1.0 for o in seabed)
    and L._f(sea['y']) == L.SEA_LEVEL
    and A.ground_height(co, sea['x'], sea['z']) < L._f(sea['y']),
    (sea['y'], A.ground_height(co, sea['x'], sea['z']), [(o['z'], o['p'].get('depth')) for o in shelf]),
)
check(
    'coast: the beach is the ground pulled to the waterline, landward of the sea',
    sand and all(s['z'] > sea['z'] for s in sand),
    [(s['z'], sea['z']) for s in sand],
)
check(
    'coast: the cliff is a step at the BACK, inland of the beach (%.0f m vs %.0f m)' % (step['z'], sand[0]['z']),
    step['z'] > max(s['z'] for s in sand) and L.CLIFF_M[0] <= L._f(step['p'].get('h')) <= L.CLIFF_M[1],
    (step['z'], [s['z'] for s in sand], step['p']),
)

pl = DRAWINGS['polder'][1]
wm = [o for o in pl.objs if o['kind'] == 'windmill'][0]
check(
    'polder: the mill stands on the dyke crest (%.2f m up, berm h 4)' % wm['y'],
    wm['y'] > 3.0 and abs(wm['y'] - L.ground_under(pl, wm)) <= L.GROUND_TOL,
    wm['y'],
)

he = DRAWINGS['heath'][1]
check(
    'heath: the empty lawn is gone — %d swells, a pond, boulders, undergrowth and a tree line'
    % len([o for o in he.objs if o['kind'] == 'sculpt_peak']),
    len([o for o in he.objs if o['kind'] == 'sculpt_peak']) >= 2
    and any(o['kind'] == 'water_body' for o in he.objs)
    and len([o for o in he.objs if o['kind'] == 'undergrowth']) >= 2
    and len([o for o in he.objs if o['kind'] == 'rock_field']) >= 20,
    kinds_of(he),
)
check(
    'heath: a swell is a swell, not a mountain (%.1f m, cap %g)'
    % (max(L._hh(o) for o in he.objs if o['kind'] == 'sculpt_peak'), L.SWELL_H_CAP),
    max(L._hh(o) for o in he.objs if o['kind'] == 'sculpt_peak') <= L.SWELL_H_CAP + 1e-6,
    [o['p'] for o in he.objs if o['kind'] == 'sculpt_peak'],
)

cy = DRAWINGS['canyon'][1]
ccut = [o for o in cy.objs if o['kind'] == 'sculpt_cut'][0]
mesas = [o for o in cy.objs if o['kind'] == 'sculpt_mesa']
check(
    'canyon: a %.0f m cut runs THROUGH the block (%.0f of %.0f m)'
    % (L._f(ccut['p'].get('depth')), L._f(ccut['p'].get('len')), x1 - x0),
    abs(L._f(ccut['p'].get('depth')) - L.CANYON_DEPTH) < 1e-6 and L._f(ccut['p'].get('len')) >= (x1 - x0) - 1.5,
    ccut['p'],
)
check(
    'canyon: the floor really is 20 m down (%.1f m at the middle)' % A.ground_height(cy, ccut['x'], ccut['z']),
    A.ground_height(cy, ccut['x'], ccut['z']) < -15.0,
    A.ground_height(cy, ccut['x'], ccut['z']),
)
check(
    'canyon: two mesas, one on either side of the cut, not two cones on a lawn',
    len(mesas) == 2 and mesas[0]['z'] * mesas[1]['z'] < 0.0 and all(L._f(o['p'].get('top_r')) > 0.0 for o in mesas),
    [(o['x'], o['z'], o['p']) for o in mesas],
)
# the first reach starts on the rim by construction — the cut is feathered, so
# the river has to come down the headwall to get to the floor. It is the rest of
# it, once it is off the ramp, that has to be down in the canyon.
cwp = [o for o in cy.objs if o['kind'] in L.V3_FLOW_WATER]
onfloor = [o for o in cwp if o['x'] > x0 + (L.HEAD_FRAC + 0.02) * (x1 - x0)]
check(
    'canyon: the river is carved on the canyon floor, not on the rim (%d of %d reaches below -15 m)'
    % (len(onfloor), len(cwp)),
    len(onfloor) >= L.BODY_REACHES - 2 and all(L.surface_y(o, 0.5) < -15.0 for o in onfloor),
    [(round(o['x'], 1), round(L.surface_y(o, 0.5), 2)) for o in cwp],
)
check(
    'canyon: the scree is loose stone at the wall feet, not a solid slab',
    not [o for o in cy.objs if o['kind'] == 'scree'] and len([o for o in cy.objs if o['kind'] == 'rock_field']) >= 40,
    kinds_of(cy),
)

# ── the same scenes at other block sizes, up to a kilometre ───────────────────
print('block sizes')
for scene in L.SCENES:
    for tag, blk, doc in (('240 m', SMALL, None), ('600 m', HALF_KM, {'cell_m': 2}), ('1 km', KM, {'cell_m': 5})):
        txt, d = assistant(
            'compose_landscape', {'cell_from': blk[0], 'cell_to': blk[1], 'scene': scene, 'seed': 3}, doc=doc
        )
        warn = L.landscape_warnings(d)
        check(
            '%s at %s: composes clean, %d records, no warnings, no old solids' % (scene, tag, len(d.objs)),
            not txt.lower().startswith('refused') and not warn and L.solid_ground_kinds(d) == [],
            (txt[:120], warn[:2], L.solid_ground_kinds(d)),
        )

# ── the kilometre scene: one ground, one range, no tiles ──────────────────────
print('kilometre')
_t, km = assistant(
    'compose_landscape', {'cell_from': KM[0], 'cell_to': KM[1], 'scene': 'alpine', 'seed': 3}, doc={'cell_m': 5}
)
kx0, kz0, kx1, kz1 = block_of(km, KM)
W = kx1 - kx0
check('a 5 m grid over 200 x 200 cells really is a kilometre block (%.0f m)' % W, abs(W - 1000.0) < 1e-6, W)
kg = [o for o in km.objs if o['kind'] == L.GROUND_KIND]
check(
    'ONE ground record, not nine tiled copies (%d, %.0f x %.0f m, res %s)'
    % (
        len(kg),
        L._f(kg[0]['p'].get('w')) if kg else 0,
        L._f(kg[0]['p'].get('d')) if kg else 0,
        kg[0]['p'].get('res') if kg else '-',
    ),
    len(kg) == 1 and abs(L._f(kg[0]['p'].get('w')) - W) < 1.5 and abs(L._f(kg[0]['p'].get('d')) - W) < 1.5,
    [(o['p'].get('w'), o['p'].get('d')) for o in kg],
)
check('that ground is meshed at res 200', kg[0]['p'].get('res') == 200, kg[0]['p'].get('res'))
kp = [o for o in km.objs if o['kind'] == 'sculpt_peak']
want_r = L.PEAK_R_OF_W * W
want_h = min(L.PEAK_H_OF_R * want_r, L.PEAK_H_CAP)
check(
    'the peak scales with the block: r %.1f m (0.15 W), h %.1f m (0.8 r, cap 150)'
    % (L._f(kp[0]['p'].get('r')) if kp else 0, L._f(kp[0]['p'].get('h')) if kp else 0),
    kp and all(abs(L._f(o['p'].get('r')) - want_r) <= 8.0 and abs(L._f(o['p'].get('h')) - want_h) <= 6.0 for o in kp),
    [(o['p'].get('r'), o['p'].get('h'), want_r, want_h) for o in kp],
)
check(
    'a kilometre block gets a 120 m range, not a 36 m one',
    abs(max(L._f(o['p'].get('h')) for o in kp) - 120.0) < 6.0,
    max(L._f(o['p'].get('h')) for o in kp),
)
lo = min(o['x'] - L._f(o['p'].get('r')) for o in kp)
hi = max(o['x'] + L._f(o['p'].get('r')) for o in kp)
check(
    'ONE range spanning the block (%d peaks over %.0f%% of %.0f m)' % (len(kp), 100.0 * (hi - lo) / W, W),
    len(kp) == L.RANGE_PEAKS and (hi - lo) >= 0.9 * W,
    (lo, hi, W),
)
check(
    'not a single old solid record at a kilometre',
    L.solid_ground_kinds(km) == [] and not [o for o in km.objs if o['kind'] in ('terrain', 'mountain_range')],
    sorted(kinds_of(km)),
)
check(
    'the kilometre lake is still inside the block and the wood still %.1f m clear of it'
    % clearing_m(
        assistant(
            'compose_landscape',
            {'cell_from': KM[0], 'cell_to': KM[1], 'scene': 'forest_lake', 'seed': 3},
            doc={'cell_m': 5},
        )[1]
    ),
    clearing_m(
        assistant(
            'compose_landscape',
            {'cell_from': KM[0], 'cell_to': KM[1], 'scene': 'forest_lake', 'seed': 3},
            doc={'cell_m': 5},
        )[1]
    )
    >= L.CLEARING_M - 1e-6,
    clearing_m(
        assistant(
            'compose_landscape',
            {'cell_from': KM[0], 'cell_to': KM[1], 'scene': 'forest_lake', 'seed': 3},
            doc={'cell_m': 5},
        )[1]
    ),
)

# ── refusals ──────────────────────────────────────────────────────────────────
print('refusals')
txt, d = assistant('compose_landscape', {'cell_from': 'A1', 'cell_to': 'D4', 'scene': 'alpine'})
check(
    'alpine refuses a 4 x 4 m block and says its own 240 m minimum',
    txt.startswith('refused') and '240 x 240 m' in txt and d.objs == [],
    txt[:200],
)
for scene in ('coast', 'canyon'):
    txt, d = assistant('compose_landscape', {'cell_from': 'A1', 'cell_to': 'D4', 'scene': scene})
    check(
        '%s refuses a 4 x 4 m block and says the minimum in metres' % scene,
        txt.startswith('refused') and '120 x 120 m' in txt and d.objs == [],
        txt[:200],
    )
txt, d = assistant('compose_landscape', {'cell_from': 'A1', 'cell_to': A.cell_name(299, 299), 'scene': 'lunar'})
check(
    'an unknown scene is refused and lists the seven',
    txt.startswith('refused') and 'river_valley' in txt and d.objs == [],
    txt[:160],
)
txt, d = assistant('compose_landscape', {'cell_from': 'A1', 'cell_to': A.cell_name(79, 79), 'scene': 'polder'})
check('polder has a lower floor and works on an 80 x 80 m block', not txt.startswith('refused'), txt[:160])
txt, d = assistant('compose_landscape', {'cell_from': 'A1', 'cell_to': A.cell_name(59, 59), 'scene': 'heath'})
check('heath has the lowest floor of all and works on 60 x 60 m', not txt.startswith('refused'), txt[:160])
txt, d = assistant(
    'compose_landscape', {'cell_from': 'A1', 'cell_to': A.cell_name(299, 299), 'scene': 'heath'}, doc={'cell_m': 10}
)
check(
    '3 km is refused: a sculpted ground is one heightfield and 1000 m is where it still reads',
    txt.startswith('refused') and '1000 m' in txt and '3000 x 3000 m' in txt and d.objs == [],
    txt[:220],
)

# a callee refusing mid-recipe must stop the whole thing
_real = A.call_tool
_seen = []


def _refuse_second(d, name, args):
    _seen.append(name)
    if len(_seen) == 2:
        return 'refused: the test says no'
    return _real(d, name, args)


d2 = A.Drawing({'objects': []})
A.call_tool = _refuse_second
try:
    stopped = L.t_compose_landscape(d2, {}, cell_from=BLOCK[0], cell_to=BLOCK[1], scene='alpine')
finally:
    A.call_tool = _real
check(
    'a callee refusal stops the recipe and names the step',
    stopped.startswith('refused') and 'alpine' in stopped and 'the test says no' in stopped,
    stopped[:200],
)
check(
    '...and nothing past the sculpted ground was drawn',
    len(_seen) == 2 and set(kinds_of(d2)) == {'ground'},
    (_seen, kinds_of(d2)),
)
txt, d = assistant(
    'compose_landscape', {'cell_from': BLOCK[0], 'cell_to': BLOCK[1], 'scene': 'alpine'}, drawing=DRAWINGS['heath'][1]
)
check(
    'a second scene will not be laid over a drawing that already has a ground',
    txt.startswith('refused') and 'ground' in txt,
    txt[:200],
)

# ── the read tools ────────────────────────────────────────────────────────────
print('read tools')
txt, d = assistant('describe_landscape', {})
check('describe_landscape on an empty drawing says so', 'no landscape records' in txt and d.objs == [], txt[:120])
d3 = DRAWINGS['coast'][1]
before = len(d3.objs)
txt = A.call_tool(d3, 'describe_landscape', {})
check(
    'describe_landscape lists the coast by v3 family and kind',
    all(k in txt for k in ('ground_v3', 'water_v3', 'water_plane', 'sculpt_dunes', 'sculpt_step'))
    and 'cliffs_rocks' in txt,
    txt[:400],
)
check('describe_landscape draws nothing', len(d3.objs) == before, (before, len(d3.objs)))
check('a clean scene is reported as clean', 'warnings: none' in txt, txt[-200:])
for scene in L.SCENES:
    got = A.call_tool(DRAWINGS[scene][1], 'describe_landscape', {})
    check('%s: describe_landscape ends with a warnings verdict' % scene, 'warnings' in got, got[-120:])

# the warnings section has to actually catch what the tree was cut for
d4 = A.Drawing({'objects': list(DRAWINGS['alpine'][1].to_doc()['objects'])})
for o in d4.objs:
    if o['kind'] == 'forest':
        o['p']['h'] = 38.9  # the measured bug: trees taller than the mountains
    if o['kind'] == 'rock_field':
        o['p']['size'] = 11.0  # the measured bug: 11 m 'boulders'
txt = A.call_tool(d4, 'describe_landscape', {})
check('warnings catch a wood that out-tops its own mountains', 'proportion:' in txt and '38.9' in txt, txt[-500:])
check('warnings catch an 11 m boulder', 'size:' in txt and '11.0 m boulders' in txt, txt[:1200] + txt[-400:])
check(
    'landscape_warnings and the description agree on the count',
    ('warnings (%d)' % len(L.landscape_warnings(d4))) in txt,
    (len(L.landscape_warnings(d4)), txt[-500:]),
)

d6 = A.Drawing({'objects': list(DRAWINGS['alpine'][1].to_doc()['objects'])})
lk = [o for o in d6.objs if o['kind'] == 'water_body'][0]
lk['y'] = L.ground_under(d6, lk) - 6.0
check(
    'warnings catch water sunk under its own bed',
    any(w.startswith('water:') and 'UNDER its own bed' in w for w in L.landscape_warnings(d6)),
    L.landscape_warnings(d6)[:3],
)
d7 = A.Drawing({'objects': list(DRAWINGS['alpine'][1].to_doc()['objects'])})
lk = [o for o in d7.objs if o['kind'] == 'water_body'][0]
lk['y'] = L._f(lk['y']) + 20.0
check(
    'warnings catch a puddle standing on a plinth',
    any('puddle on a plinth' in w for w in L.landscape_warnings(d7)),
    L.landscape_warnings(d7)[:3],
)

d5 = A.Drawing({'objects': list(DRAWINGS['polder'][1].to_doc()['objects'])})
for o in d5.objs:
    if o['kind'] == 'windmill':
        o['p']['h'] = 60.0
    if o['kind'] == 'tree_line':
        o['y'] = L._f(o['y']) - 6.0
txt = A.call_tool(d5, 'describe_landscape', {})
check('warnings catch a 60 m windmill', 'to the sail tip' in txt, txt[-400:])
check('warnings catch a buried tree line', 'buried:' in txt and 'tree_line' in txt.split('warnings')[-1], txt[-400:])

for words, why in (
    ('bergen met een meer', 'Dutch mountains'),
    ('een kustlandschap', 'Dutch coast'),
    ('Wald mit einem See', 'German forest and lake'),
    ('polder met een molen', 'Dutch polder'),
):
    txt, d = assistant('suggest_scene', {'words': words})
    check(
        'suggest_scene(%r) names one of the seven (%s)' % (words, why),
        txt.split(' ')[0] in L.SCENES and d.objs == [],
        txt[:140],
    )
txt, d = assistant('suggest_scene', {'words': 'zxqwerty'})
check('suggest_scene refuses words that point nowhere', txt.startswith('refused'), txt[:140])

# ── the glossary this family fed ──────────────────────────────────────────────
print('glossary')
check("translate('rivier') == 'river'", G.translate('rivier') == 'river', G.translate('rivier'))
check("translate('Wald') == 'forest'", G.translate('Wald') == 'forest', G.translate('Wald'))
check("translate('falaise') == 'cliff'", G.translate('falaise') == 'cliff', G.translate('falaise'))
SPOT = [
    ('gebergte', 'mountain range'),
    ('vallei', 'valley'),
    ('beek', 'stream'),
    ('meer', 'lake'),
    ('duin', 'dune'),
    ('eiland', 'island'),
    ('moeras', 'marsh'),
    ('heide', 'heath'),
    ('Gebirge', 'mountain range'),
    ('Tal', 'valley'),
    ('Fluss', 'river'),
    ('Insel', 'island'),
    ('montagne', 'mountain'),
    ('vallée', 'valley'),
    ('lac', 'lake'),
    ('plage', 'beach'),
    ('île', 'island'),
]
bad = [(w, want, G.translate(w)) for w, want in SPOT if G.translate(w) != want]
check('%d more nature words in three languages' % len(SPOT), not bad, bad)
check(
    'the entries that were already there are untouched',
    G.translate('dijk') == 'embankment'
    and G.translate('heuvel') == 'hill'
    and G.translate('boom') == 'tree'
    and G.translate('Baum') == 'tree'
    and G.translate('arbre') == 'tree'
    and G.translate('gevel') == 'facade',
    (G.translate('dijk'), G.translate('heuvel'), G.translate('gevel')),
)

for topic, must in (
    ('landscape', 'compose_landscape'),
    ('mountains', 'add_mountain_range'),
    ('rivers', 'add_river'),
    ('forests', 'plant_forest'),
    ('cliffs', 'add_cliff'),
    ('coast', 'make_coast'),
    ('fields', 'make_polder'),
):
    got = G.explain(topic)
    check('explain(%r) names %s' % (topic, must), must in got and len(got) > 120, got[:120])

check(
    'the rail still merges this family (it adds no leaves)',
    rail_has(['wall_arc', 'wall_ring']) == [],
    rail_has(['wall_arc', 'wall_ring']),
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
doc = DRAWINGS['polder'][1].to_doc()
info = blender_doc(doc)
n = len(doc['objects'])
check('the polder scene builds headless (%d records)' % n, info.get('ok') is True, info)
check(
    'blender kept every record it was given (%s built, %s skipped)' % (info.get('objects'), info.get('skipped')),
    int(info.get('objects') or 0) >= n - int(info.get('skipped') or 0) and int(info.get('skipped') or 0) == 0,
    info,
)
doc = DRAWINGS['canyon'][1].to_doc()
info = blender_doc(doc)
check(
    'the canyon scene builds headless too (%d records, the sculpts are ground parameters)' % len(doc['objects']),
    info.get('ok') is True and int(info.get('skipped') or 0) == 0,
    info,
)

# ── the three scenes the eye rejected, rendered from the air ──────────────────
print('render')
for scene in ('alpine', 'canyon', 'forest_lake'):
    path = RENDERS[scene]
    save_render(DRAWINGS[scene][1], path, view='aerial')
    check(
        '%s renders to %s' % (scene, os.path.basename(path)),
        os.path.exists(path) and os.path.getsize(path) > 20000,
        os.path.getsize(path) if os.path.exists(path) else 'missing',
    )
finish()
