# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_ground_v3.py — the V3 GROUND (2026-09-07).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_ground_v3.py

v3 says: a drawing has ONE ground, and every landform is a SCULPT of it —

    H(lx, lz) = base + amp * vnoise(lx, lz, seed)
                + SUM over every sculpt_* record of its contribution there

so a valley is a hollow instead of a raised plinth, a peak grows out of the land
instead of standing on it, and the whole surface is one mesh that can be grass,
rock, sand and snow at once. That claim is only true if FOUR things hold, and
this file proves each of them in all three engines:

  1. THE ARITHMETIC IS ONE ARITHMETIC. arch_assistant_ext/ground_v3.py,
     arch_blender_ext/ground_v3.py and arch_ext/ground_v3.js are three copies of
     the same functions. The Blender copy is imported and compared number for
     number; the tab copy is called in the browser and compared number for
     number. Not "close" — the same double.
  2. THE SUM IS REAL. A peak raises the centre by exactly its height and the rim
     by nothing; a cut lowers it by exactly its depth; a flat SETS it; a hidden
     sculpt is not in the sum; the record's y, s and ry are honoured.
  3. THE MESH IS THE SUM. The tab's and Blender's ground bounding boxes equal
     the relief of a lattice computed in Python, and both carry vertex colours.
     The ten sculpt kinds build NO geometry in either engine.
  4. THE STUDIO STAYS WITH IT. HEIGHTS['ground'] is the same H, so a forest
     drapes over a hill made of two peaks; and the tab rebuilds the ground when
     a sculpt is added, moved or deleted.
"""

import importlib.util
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    kinds_of,
    tool_names,  # noqa: E402
    rail_has,
    browser_kinds,
    blender_kinds,
    URL,
)  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402
import zyg_workflows.arch_assistant_ext.ground_v3 as G  # noqa: E402

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS = os.path.join(HERE, 'arch_ext', 'ground_v3.js')
RAIL = os.path.join(HERE, 'arch_ext', 'ground_v3.json')
BL_PY = os.path.join(HERE, 'arch_blender_ext', 'ground_v3.py')

# the Blender half is a plain module (it imports only `math`), so the two Python
# copies of the contract can be compared directly, number for number
_spec = importlib.util.spec_from_file_location('bl_ground_v3', BL_PY)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

SCULPT_KINDS = [
    'sculpt_peak',
    'sculpt_ridge',
    'sculpt_mesa',
    'sculpt_cut',
    'sculpt_channel',
    'sculpt_basin',
    'sculpt_flat',
    'sculpt_step',
    'sculpt_dunes',
    'sculpt_shelf',
]

GP = {
    'w': 200,
    'd': 200,
    'res': 100,
    'seed': 3,
    'base': 0,
    'amp': 1.5,
    'snow_h': 60,
    'water_h': -0.15,
    'grass_max_slope': 32,
}


def rec(kind, p, x=0.0, z=0.0, y=0.0, ry=0.0, s=1.0, hidden=False):
    return {
        'id': 'r',
        'kind': kind,
        'name': kind,
        'p': p,
        'x': x,
        'y': y,
        'z': z,
        'rx': 0,
        'ry': ry,
        'rz': 0,
        's': s,
        'mat': 'mat_soil',
        'hidden': hidden,
        'grp': '',
    }


def relief(p, recs):
    hs, _sd = G.lattice(p, recs)
    flat = [v for row in hs for v in row]
    return max(flat) - min(flat), min(flat), max(flat)


PEAK = {'r': 40, 'h': 30, 'rug': 0.45, 'seed': 1, 'feather': 8}
CUT = {'len': 200, 'w': 60, 'depth': 10, 'floor_w': 15, 'profile': 0, 'feather': 20}
FLAT5 = {'w': 40, 'd': 40, 'level': 5, 'feather': 6}

# A SET channel: the bed a river gets since 2026-09-07. `level0`/`level1` are the
# bed height at the reach's two ends, and with BOTH of them the channel stops
# digging `depth` below whatever rolls past and SETS the ground to that straight
# fall. Straight down the middle of the ground (meander 0), so the lattice has a
# vertex exactly on the downstream end at (50, 0) and the mesh's lowest point is
# level1 to the millimetre.
CH_SET = {'len': 100, 'w': 12, 'depth': 2, 'meander': 0, 'seed': 1, 'bank': 4, 'feather': 0, 'level0': -5, 'level1': -8}
CH_OLD = {k: v for k, v in CH_SET.items() if not k.startswith('level')}
GFLAT = dict(GP, amp=0)  # base 0, no roll: H is the sculpts and nothing else

# ── 1. the family is wired in ────────────────────────────────────────────────
print('python: the family')
check(
    'all eleven kinds reached arch_assistant.KINDS',
    all(k in A.KINDS for k in ['ground'] + SCULPT_KINDS),
    [k for k in ['ground'] + SCULPT_KINDS if k not in A.KINDS],
)
check(
    "HEIGHTS['ground'] is registered — the whole studio reads the ground through it",
    callable(A.EXT_HEIGHTS.get('ground')) and A.EXT_HEIGHTS['ground'].__name__ == G.h_ground.__name__,
    A.EXT_HEIGHTS.get('ground'),
)
check('the family declares NO openings', G.OPENINGS == [], G.OPENINGS)
check(
    'VOID_KINDS is exported for the sweep to union (test_all.py is not ours to edit)',
    sorted(G.VOID_KINDS) == sorted(SCULPT_KINDS),
    G.VOID_KINDS,
)
check(
    'every void kind is a sculpt_* kind and has a contribution function',
    all(k.startswith('sculpt_') and k in G.SCULPTS for k in G.VOID_KINDS),
)
check('the Blender half exports the same VOID_KINDS', sorted(B.VOID_KINDS) == sorted(G.VOID_KINDS))
check(
    'the five tools are registered with the assistant',
    all(t in tool_names() for t in ['make_ground', 'raise_ground', 'lower_ground', 'level_ground', 'describe_ground']),
    [
        t
        for t in ['make_ground', 'raise_ground', 'lower_ground', 'level_ground', 'describe_ground']
        if t not in tool_names()
    ],
)
check(
    'the library rail lists all eleven kinds',
    rail_has(['ground'] + SCULPT_KINDS) == [],
    rail_has(['ground'] + SCULPT_KINDS),
)
check(
    'the rail JSON is valid and lands in an existing section',
    json.load(open(RAIL, encoding='utf-8'))['section_key'] == 'site',
)
check(
    'the prompt paragraph says a drawing has ONE ground',
    'ONE ground' in G.PROMPT and 'make_ground' in G.PROMPT and 'sculpt' in G.PROMPT,
)

# ── 2. the noise is the studio's noise ───────────────────────────────────────
print('python: the shared contract')
import zyg_workflows.arch_assistant_ext.terrain as T  # noqa: E402

check(
    'value_noise is verbatim the studio terrain noise',
    all(
        abs(G.value_noise(u, v, s) - T.value_noise(u, v, s)) < 1e-12
        for u, v, s in [(0.3, 1.7, 1), (12.5, -3.25, 7), (-0.9, 0.9, 3)]
    ),
)
import zyg_workflows.arch_assistant_ext.rivers_lakes as RL  # noqa: E402

check(
    'meander_offset is verbatim the river kind wander',
    all(abs(G.meander_offset(t, 6, 2) - RL.meander_offset(t, 6, 2)) < 1e-12 for t in (0.1, 0.5, 0.9)),
)
check(
    'lake_factor is verbatim the lake kind shoreline',
    all(abs(G.lake_factor(a, 0.25, 4) - RL.lake_factor(a, 0.25, 4)) < 1e-12 for a in (0.0, 1.3, -2.2)),
)
check(
    'the Blender copy of value_noise is the same double',
    all(
        G.value_noise(u, v, s) == B.value_noise(u, v, s)
        for u, v, s in [(0.3, 1.7, 1), (12.5, -3.25, 7), (-0.9, 0.9, 3), (2.0, 2.0, 3)]
    ),
)
check(
    'the Blender copy of smoothstep/band/feather_of is the same double',
    G.smoothstep(0.37) == B.smoothstep(0.37)
    and G.band(3.0, 20.0) == B.band(3.0, 20.0)
    and G.feather_of({'r': 40}, 40) == B.feather_of({'r': 40}, 40),
)
check(
    'the JS file carries hash/vnoise verbatim (43758.5453, 127.1, 311.7, 74.7)',
    all(s in open(JS, encoding='utf-8').read() for s in ['43758.5453', '127.1', '311.7', '74.7']),
)

# ── 3. every sculpt: nothing outside, something inside, nothing at the rim ──
print('python: the ten sculpts')
INSIDE = {
    'sculpt_peak': ({'r': 40, 'h': 30, 'rug': 0.45, 'seed': 1, 'feather': 8}, (0.0, 0.0), +1, (40.0, 0.0)),
    'sculpt_ridge': (
        {'len': 120, 'w': 40, 'h': 25, 'rug': 0.35, 'seed': 1, 'feather': 12},
        (0.0, 0.0),
        +1,
        (60.0, 0.0),
    ),
    'sculpt_mesa': ({'r': 40, 'h': 25, 'top_r': 28, 'rug': 0.25, 'seed': 1, 'feather': 8}, (0.0, 0.0), +1, (40.0, 0.0)),
    'sculpt_cut': (
        {'len': 200, 'w': 60, 'depth': 15, 'floor_w': 15, 'profile': 0, 'feather': 20},
        (0.0, 0.0),
        -1,
        (0.0, 30.0),
    ),
    'sculpt_basin': (
        {'rx': 40, 'rz': 28, 'depth': 6, 'wobble': 0.25, 'seed': 1, 'shore': 6, 'feather': 0},
        (0.0, 0.0),
        -1,
        (60.0, 0.0),
    ),
    'sculpt_flat': ({'w': 40, 'd': 40, 'level': 5, 'feather': 6}, (0.0, 0.0), 0, (21.0, 0.0)),
    'sculpt_step': (
        {'len': 120, 'h': 20, 'd': 40, 'rug': 0.3, 'seed': 1, 'feather': 12},
        (0.0, 15.0),
        +1,
        (0.0, -19.0),
    ),
    'sculpt_dunes': ({'w': 160, 'd': 80, 'h': 10, 'seed': 1, 'dir': 0, 'feather': 16}, (0.0, 0.0), +1, (81.0, 0.0)),
    'sculpt_shelf': ({'w': 200, 'd': 120, 'depth': 8, 'feather': 20}, (0.0, 0.0), -1, (101.0, 0.0)),
}
CH_P = {'len': 120, 'w': 12, 'depth': 2, 'meander': 6, 'seed': 1, 'bank': 2, 'feather': 12}
INSIDE['sculpt_channel'] = (CH_P, (0.0, G.meander_offset(0.5, 6, 1)), -1, (0.0, 40.0))
for k in SCULPT_KINDS:
    p, inside, sign, outside = INSIDE[k]
    dh, mask = G.SCULPTS[k](p, *inside)
    odh, omask = G.SCULPTS[k](p, *outside)
    check(
        '%s: felt at its heart, dead outside its footprint' % k,
        mask > 0.2 and (dh * sign > 0 if sign else dh == 5) and omask == 0.0 and odh == 0.0,
        (dh, mask, odh, omask),
    )
for k in SCULPT_KINDS:
    p = INSIDE[k][0]
    check(
        '%s: the Blender copy returns the same two doubles' % k,
        all(
            G.SCULPTS[k](p, x, z) == B.SCULPTS[k](p, x, z)
            for x, z in [(0, 0), (5.5, -3.25), (17.0, 11.0), (-31.0, 8.5), (0.0, 15.0)]
        ),
        (G.SCULPTS[k](p, 5.5, -3.25), B.SCULPTS[k](p, 5.5, -3.25)),
    )
check(
    'a peak is exactly h at its summit and nothing at its rim',
    abs(G.s_peak(PEAK, 0, 0)[0] - 30.0) < 1e-9 and G.s_peak(PEAK, 40, 0) == (0.0, 0.0),
    G.s_peak(PEAK, 0, 0),
)
check(
    'a peak feathers: no step at the rim (39.99 m and 40.01 m differ by < 1 mm)',
    abs(G.s_peak(PEAK, 39.99, 0)[0] - G.s_peak(PEAK, 40.01, 0)[0]) < 1e-3,
    G.s_peak(PEAK, 39.99, 0),
)
check(
    'a mesa is flat over its whole top',
    abs(G.s_mesa(INSIDE['sculpt_mesa'][0], 0, 0)[0] - G.s_mesa(INSIDE['sculpt_mesa'][0], 20, 0)[0]) < 1e-9,
)
check(
    'sculpt_flat returns the LEVEL as dh and the pull as mask, and its mask is '
    'byte-for-byte arch_assistant._sculpt_flat_weight',
    G.s_flat(FLAT5, 3, -4) == (5.0, A._sculpt_flat_weight(FLAT5, 3, -4))
    and G.s_flat(FLAT5, 18.5, 0)[1] == A._sculpt_flat_weight(FLAT5, 18.5, 0),
    (G.s_flat(FLAT5, 18.5, 0), A._sculpt_flat_weight(FLAT5, 18.5, 0)),
)
STEP_P = INSIDE['sculpt_step'][0]
check(
    'an escarpment lifts behind its face and not in front of it',
    G.s_step(STEP_P, 0, 5)[0] > 10 and G.s_step(STEP_P, 0, -5) == (0.0, 0.0) and G.s_step(STEP_P, 0, -15) == (0.0, 0.0),
    (G.s_step(STEP_P, 0, 5), G.s_step(STEP_P, 0, -5)),
)
check(
    'the escarpment fades away to nothing at the back of its footprint',
    G.s_step(STEP_P, 0, 5)[1] > G.s_step(STEP_P, 0, 15)[1] > 0.0 and G.s_step(STEP_P, 0, 25) == (0.0, 0.0),
    [G.s_step(STEP_P, 0, z)[1] for z in (5, 15, 25)],
)
check('only the dune belt and the sea bed read as sand', G.SAND_KINDS == ('sculpt_dunes', 'sculpt_shelf'))

# ── 4. H = base + the sum ────────────────────────────────────────────────────
print('python: the field')
base00 = G.base_height(GP, 0, 0)
r_peak = [rec('sculpt_peak', PEAK)]
check(
    'a bare ground is just its base roll',
    G.height_at(GP, 0, 0, []) == base00 and G.height_at(GP, 17, -33, []) == G.base_height(GP, 17, -33),
)
check(
    'one sculpt_peak r 40 h 30 at the centre: H(centre) == base + 30 exactly',
    abs(G.height_at(GP, 0, 0, r_peak) - (base00 + 30.0)) < 1e-6,
    G.height_at(GP, 0, 0, r_peak) - base00,
)
check(
    'at r = 40 the peak is spent: H == the base noise alone (the feather ends at the rim)',
    abs(G.height_at(GP, 40, 0, r_peak) - G.base_height(GP, 40, 0)) < 1e-6,
    G.height_at(GP, 40, 0, r_peak) - G.base_height(GP, 40, 0),
)
check('outside the peak nothing changed at all', G.height_at(GP, 70, 20, r_peak) == G.base_height(GP, 70, 20))
r_cut = [rec('sculpt_cut', CUT)]
check(
    'a sculpt_cut depth 10 LOWERS the centre by exactly 10 — a valley, not a plinth',
    abs(G.height_at(GP, 0, 0, r_cut) - (base00 - 10.0)) < 1e-6,
    G.height_at(GP, 0, 0, r_cut) - base00,
)
check(
    'the cut leaves its rim untouched (lz = w/2 and lx = len/2)',
    abs(G.height_at(GP, 0, 30, r_cut) - G.base_height(GP, 0, 30)) < 1e-9
    and abs(G.height_at(GP, 100, 0, r_cut) - G.base_height(GP, 100, 0)) < 1e-9,
)
r_flat = [rec('sculpt_flat', FLAT5)]
check(
    'a sculpt_flat level 5 gives EXACTLY 5 at the centre (SET, not add)',
    G.height_at(GP, 0, 0, r_flat) == 5.0,
    G.height_at(GP, 0, 0, r_flat),
)
check(
    'sculpt_flat cuts AND fills: 5 whether the land under it was higher or lower',
    G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK), rec('sculpt_flat', FLAT5)]) == 5.0
    and G.height_at(GP, 0, 0, [rec('sculpt_cut', CUT), rec('sculpt_flat', FLAT5)]) == 5.0,
)
check(
    'sculpt_flat is applied LAST whatever the record order',
    G.height_at(GP, 0, 0, [rec('sculpt_flat', FLAT5), rec('sculpt_peak', PEAK)]) == 5.0,
)
check(
    'the flat feathers back into the land at its edge',
    abs(G.height_at(GP, 20, 0, r_flat) - G.base_height(GP, 20, 0)) < 1e-9,
    G.height_at(GP, 20, 0, r_flat) - G.base_height(GP, 20, 0),
)
check(
    'sculpts SUM: a peak and a cut at the same spot are +30 and -10 together',
    abs(G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK), rec('sculpt_cut', CUT)]) - (base00 + 20.0)) < 1e-6,
)
check(
    'a hidden sculpt is out of the sum — hiding it takes its feature out of the land',
    G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK, hidden=True)]) == base00,
)
check(
    "a sculpt's own y shifts its base without a step at the rim",
    abs(G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK, y=7.0)]) - (base00 + 37.0)) < 1e-6
    and abs(G.height_at(GP, 40, 0, [rec('sculpt_peak', PEAK, y=7.0)]) - G.base_height(GP, 40, 0)) < 1e-9,
)
check(
    "a sculpt's scale s scales both its footprint and its height",
    abs(G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK, s=2.0)]) - (base00 + 60.0)) < 1e-6
    and G.height_at(GP, 70, 0, [rec('sculpt_peak', PEAK, s=2.0)]) != G.base_height(GP, 70, 0),
)
check(
    'a sculpt at an offset x/z acts THERE, not at the origin',
    G.height_at(GP, 50, 0, [rec('sculpt_peak', PEAK, x=50)]) > base00 + 25
    and G.height_at(GP, 0, 0, [rec('sculpt_peak', PEAK, x=50)]) == base00,
)
r_ry = [rec('sculpt_cut', CUT, ry=math.pi / 2)]
check(
    "a sculpt's ry turns it: a cut along X becomes a cut along Z",
    abs(G.height_at(GP, 0, 70, r_ry) - (G.base_height(GP, 0, 70) - 10.0)) < 1e-6
    and abs(G.height_at(GP, 70, 0, r_ry) - G.base_height(GP, 70, 0)) < 1e-9,
    (G.height_at(GP, 0, 70, r_ry) - G.base_height(GP, 0, 70), G.height_at(GP, 70, 0, r_ry) - G.base_height(GP, 70, 0)),
)
check(
    'a non-sculpt record (a box) contributes nothing to the ground',
    G.height_at(GP, 0, 0, [rec('box', {'w': 5, 'd': 5, 'h': 5})]) == base00,
)
check(
    'the Blender copy of the whole field agrees to the last bit',
    all(
        G.height_at(
            GP,
            x,
            z,
            [rec('sculpt_peak', PEAK), rec('sculpt_cut', CUT, ry=0.7, x=20), rec('sculpt_flat', FLAT5, x=-60, z=40)],
        )
        == B.height_at(
            GP,
            x,
            z,
            [rec('sculpt_peak', PEAK), rec('sculpt_cut', CUT, ry=0.7, x=20), rec('sculpt_flat', FLAT5, x=-60, z=40)],
        )
        for x, z in [(0, 0), (13.5, -47.25), (-62.0, 33.0), (-60, 40), (99.5, 99.5)]
    ),
)

# ── 5. the lattice and the slope ─────────────────────────────────────────────
print('python: the lattice')
hs, sd = G.lattice(GP, r_peak)
check('the lattice is (res+1)^2 vertices, row major', len(hs) == 101 and all(len(r) == 101 for r in hs), len(hs))
check(
    'the lattice vertices ARE height_at at the same points',
    abs(hs[50][50] - G.height_at(GP, 0.0, 0.0, r_peak)) < 1e-12
    and abs(hs[0][0] - G.height_at(GP, -100.0, -100.0, r_peak)) < 1e-12,
)
check(
    'the relief of a 200 m ground with a 30 m peak is a little over 30 m',
    30.0 < relief(GP, r_peak)[0] < 32.0,
    relief(GP, r_peak),
)
check('the sand lattice is 0 everywhere with no dunes and no sea bed', not any(any(r) for r in sd))
hs_d, sd_d = G.lattice(GP, [rec('sculpt_dunes', INSIDE['sculpt_dunes'][0])])
check(
    'a dune belt marks its own footprint as sand and nothing outside it',
    sd_d[50][50] > 0.9 and sd_d[0][0] == 0.0,
    (sd_d[50][50], sd_d[0][0]),
)
check('slope_deg is 0 on a level lattice', abs(G.slope_deg([[3.0] * 5 for _ in range(5)], 2, 2, 1.0, 1.0)) < 1e-9)
check(
    'slope_deg reads a 45 degree ramp as 45 degrees',
    abs(G.slope_deg([[float(i) for i in range(5)] for _ in range(5)], 2, 2, 1.0, 1.0) - 45.0) < 1e-9,
)
check(
    'slope_deg is one-sided at the rim, not a crash',
    abs(G.slope_deg([[float(i) for i in range(5)] for _ in range(5)], 0, 0, 1.0, 1.0) - 45.0) < 1e-9,
)
check(
    'the Blender copy of slope_deg is the same double (flat-array indexing)',
    abs(
        G.slope_deg([[float(i * j) for i in range(5)] for j in range(5)], 2, 3, 2.0, 2.0)
        - B.slope_deg([float(i * j) for j in range(5) for i in range(5)], 5, 2, 3, 2.0, 2.0)
    )
    < 1e-12,
)

# ── 6. the colour ────────────────────────────────────────────────────────────
print('python: the colour')
W = dict(water_h=-0.15, snow_h=60.0, grass_max_slope=32.0)
check(
    'the five weights always sum to 1',
    all(
        abs(sum(G.colour_weights(h, s, sa, **W)) - 1.0) < 1e-12
        for h in (-5, 0, 3, 30, 59, 61, 200)
        for s in (0, 20, 32, 40, 80)
        for sa in (0, 0.5, 1)
    ),
)
check(
    'flat land well above the water is grass',
    G.colour_weights(10, 0, 0, **W)[0] > 0.999,
    G.colour_weights(10, 0, 0, **W),
)
check('anything above snow_h is snow', G.colour_weights(70, 0, 0, **W)[3] > 0.999)
check('anything steeper than grass_max_slope is rock', G.colour_weights(10, 45, 0, **W)[2] > 0.999)
check('a dune belt or a sea bed is sand', G.colour_weights(10, 0, 1, **W)[1] > 0.999)
check(
    'the waterline is a wet soil bed, and it beats rock (a river bed is soil even where it is steep)',
    G.colour_weights(-0.15, 0, 0, **W)[4] > 0.999 and G.colour_weights(-2, 60, 0, **W)[4] > 0.999,
)
check(
    'the bands BLEND — nothing is a cut-out on the hillside',
    0.2 < G.colour_weights(61, 0, 0, **W)[3] < 0.8 and 0.2 < G.colour_weights(10, 36, 0, **W)[2] < 0.8,
    (G.colour_weights(61, 0, 0, **W), G.colour_weights(10, 36, 0, **W)),
)
check(
    'and the bands have no step at either edge — the blend is continuous',
    abs(G.colour_weights(59.99, 0, 0, **W)[3] - G.colour_weights(60.01, 0, 0, **W)[3]) < 0.01
    and abs(G.colour_weights(61.99, 0, 0, **W)[3] - G.colour_weights(62.01, 0, 0, **W)[3]) < 0.01
    and abs(G.colour_weights(10, 31.99, 0, **W)[2] - G.colour_weights(10, 32.01, 0, **W)[2]) < 0.01,
    [G.colour_weights(h, 0, 0, **W)[3] for h in (59.99, 60.01, 61.99, 62.01)],
)
check(
    'the Blender copy of colour_weights is the same five doubles',
    all(
        G.colour_weights(h, s, sa, **W) == B.colour_weights(h, s, sa, **W)
        for h in (-5, 0.5, 30, 61)
        for s in (0, 33, 90)
        for sa in (0, 0.4, 1)
    ),
)
check(
    'the palette is read from the studio material hexes',
    G.studio_rgb('mat_grass') == (0x5E / 255, 0x7D / 255, 0x43 / 255),
    G.studio_rgb('mat_grass'),
)
check(
    'the five colour materials are grass, sand, rock, snow, soil in that order',
    G.COLOUR_MATS == ('mat_grass', 'mat_sand', 'mat_rock', 'mat_snow', 'mat_soil') and B.COLOUR_MATS == G.COLOUR_MATS,
)
check(
    'a grass vertex comes out the grass hex and a snow vertex the snow hex',
    all(abs(a - b) < 1e-9 for a, b in zip(G.colour_at(GP, 10, 0, 0), G.studio_rgb('mat_grass')))
    and all(abs(a - b) < 1e-9 for a, b in zip(G.colour_at(GP, 90, 0, 0), G.studio_rgb('mat_snow'))),
    G.colour_at(GP, 10, 0, 0),
)

# ── 7. HEIGHTS: the seam the studio reads ────────────────────────────────────
print('python: the studio seam')
d = A.Drawing({'objects': []})
txt = A.call_tool(d, 'make_ground', {'cell_from': 'A1', 'cell_to': 'KN300', 'style': 'rolling', 'seed': 3})
check('make_ground lays exactly one ground over the block', kinds_of(d) == {'ground': 1}, txt)
g = d.objs[0]
check(
    'the ground it laid is 300 x 300 m and its res is capped',
    abs(G._N(g['p'], 'w', 0) - 300) < 1e-6 and 4 <= G._N(g['p'], 'res', 0) <= 200,
    g['p'],
)
check(
    'make_ground refuses a SECOND ground',
    str(A.call_tool(d, 'make_ground', {'cell_from': 'A1', 'cell_to': 'CV100'})).startswith('refused:'),
)
check(
    'make_ground refuses a style it does not have',
    str(
        A.call_tool(
            A.Drawing({'objects': []}), 'make_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'style': 'lunar'}
        )
    ).startswith('refused:'),
)
NO_GROUND = [('raise_ground', {'height': 10}), ('lower_ground', {'depth': 5}), ('level_ground', {})]
check(
    'raise_ground/lower_ground/level_ground refuse when there is no ground yet',
    all(
        str(A.call_tool(A.Drawing({'objects': []}), t, dict({'cell_from': 'A1', 'cell_to': 'CV100'}, **a))).startswith(
            'refused:'
        )
        for t, a in NO_GROUND
    ),
    [
        str(A.call_tool(A.Drawing({'objects': []}), t, dict({'cell_from': 'A1', 'cell_to': 'CV100'}, **a)))
        for t, a in NO_GROUND
    ],
)
A.call_tool(d, 'raise_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 40, 'shape': 'peak'})
A.call_tool(d, 'raise_ground', {'cell_from': 'GS201', 'cell_to': 'KN300', 'height': 40, 'shape': 'peak', 'seed': 7})
check(
    'raise_ground made two sculpt_peak records, no solids',
    kinds_of(d).get('sculpt_peak') == 2 and set(kinds_of(d)) == {'ground', 'sculpt_peak'},
    kinds_of(d),
)
check(
    'every sculpt is grouped "ground sculpts" and readably named',
    all(o.get('grp') == 'ground sculpts' and 'peak' in o['name'] and ' m at ' in o['name'] for o in A.sculpts_of(d)),
    [o['name'] for o in A.sculpts_of(d)],
)
check(
    'HEIGHTS is the SAME H the mesh is built from, everywhere',
    all(
        abs(A.ground_height(d, x, z) - G.height_at(g['p'], *A.world_to_local(g, x, z), d.objs, g['x'], g['z'], 0.0))
        < 1e-9
        for x, z in [(0, 0), (-100, -100), (100, 100), (33.5, -71.25), (-149, 12)]
    ),
    [
        (A.ground_height(d, x, z), G.height_at(g['p'], *A.world_to_local(g, x, z), d.objs, g['x'], g['z'], 0.0))
        for x, z in [(0, 0), (-100, -100)]
    ],
)
check(
    'the ground stands 40 m higher at a peak than between the peaks',
    A.ground_height(d, -100, -100) - A.ground_height(d, 0, 0) > 35,
    (A.ground_height(d, -100, -100), A.ground_height(d, 0, 0)),
)
check(
    "HEIGHTS['ground'] is None outside the footprint — the ground ends where it ends",
    G.h_ground(g['p'], 400, 0) is None and G.h_ground(g['p'], 0, -400) is None,
)
check('current_drawing() is None again once ground_height returned', A.current_drawing() is None)
ftxt = A.call_tool(d, 'plant_forest', {'cell_from': 'CW101', 'cell_to': 'GR200', 'density': 0.004})
fy = [o['y'] for o in d.objs if o['kind'] == 'forest']
check(
    'a forest DRAPES on the v3 ground: several tiles, each at its own height',
    len(fy) >= 3 and len(set(round(v, 2) for v in fy)) >= 3,
    (len(fy), sorted(set(round(v, 2) for v in fy))[:6]),
)
check(
    'every forest tile sits on the ground under it, not on a flat lawn',
    all(abs(v - A.ground_height(d, o['x'], o['z'])) < 3.0 for o in d.objs if o['kind'] == 'forest' for v in [o['y']]),
    ftxt[:150],
)
ltxt = A.call_tool(d, 'level_ground', {'cell_from': 'DP110', 'cell_to': 'EX140', 'level': 12})
x0, z0, x1, z1 = A.block_bounds('DP110', 'EX140')
check('level_ground creates a sculpt_flat', kinds_of(d).get('sculpt_flat') == 1, ltxt)
check(
    'ground_height at the centre of a level_ground block is EXACTLY the level',
    A.ground_height(d, (x0 + x1) / 2, (z0 + z1) / 2) == 12.0,
    A.ground_height(d, (x0 + x1) / 2, (z0 + z1) / 2),
)
check(
    'the level pad is battered, so the land around it is untouched',
    abs(A.ground_height(d, x0 - 20, (z0 + z1) / 2) - 12.0) > 0.5,
)
ltxt2 = A.call_tool(d, 'level_ground', {'cell_from': 'FM160', 'cell_to': 'FW170'})
lvl2 = [o for o in d.objs if o['kind'] == 'sculpt_flat'][-1]['p']['level']
x0b, z0b, x1b, z1b = A.block_bounds('FM160', 'FW170')
check(
    'level_ground with no level takes the mean ground there',
    abs(A.ground_height(d, (x0b + x1b) / 2, (z0b + z1b) / 2) - lvl2) < 1e-9,
    (lvl2, ltxt2[:120]),
)
check('a second level pad does not disturb the first', A.ground_height(d, (x0 + x1) / 2, (z0 + z1) / 2) == 12.0)
check(
    'raise_ground refuses a needle and a pancake on the same footprint',
    str(A.call_tool(d, 'raise_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 400})).startswith('refused:')
    and str(A.call_tool(d, 'raise_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 2})).startswith(
        'refused:'
    ),
)
check(
    'lower_ground refuses a shaft',
    str(A.call_tool(d, 'lower_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'depth': 90})).startswith('refused:'),
)
check(
    'raise_ground shape mesa and ridge make the right kinds',
    A.call_tool(d, 'raise_ground', {'cell_from': 'A1', 'cell_to': 'CV100', 'height': 30, 'shape': 'mesa'})
    and A.call_tool(d, 'raise_ground', {'cell_from': 'CW1', 'cell_to': 'KN60', 'height': 20, 'shape': 'ridge'})
    and kinds_of(d).get('sculpt_mesa') == 1
    and kinds_of(d).get('sculpt_ridge') == 1,
    kinds_of(d),
)
check(
    'lower_ground shape valley and basin make the right kinds',
    A.call_tool(d, 'lower_ground', {'cell_from': 'A150', 'cell_to': 'KN180', 'depth': 8, 'shape': 'valley'})
    and A.call_tool(d, 'lower_ground', {'cell_from': 'CW220', 'cell_to': 'GR260', 'depth': 8, 'shape': 'basin'})
    and kinds_of(d).get('sculpt_cut') == 1
    and kinds_of(d).get('sculpt_basin') == 1,
    kinds_of(d),
)
desc = A.call_tool(d, 'describe_ground', {})
check(
    'describe_ground reports the extent, the relief and every sculpt',
    'ground o1' in desc and 'height ' in desc and 'relief' in desc and str(len(A.sculpts_of(d))) + ' sculpt' in desc,
    desc[:300],
)
check(
    'describe_ground on an empty drawing says so, without crashing',
    'no ground' in A.call_tool(A.Drawing({'objects': []}), 'describe_ground', {}),
)
check(
    'the whole shaped drawing is still one ground and nothing but sculpts on it',
    kinds_of(d).get('ground') == 1
    and all(o['kind'] == 'ground' or o['kind'] in SCULPT_KINDS or o['kind'] == 'forest' for o in d.objs),
    kinds_of(d),
)

# ── 8. the tab ───────────────────────────────────────────────────────────────
print('tab')
PY_RELIEF = {
    'bare': relief(GP, []),
    'peak': relief(GP, [rec('sculpt_peak', PEAK)]),
    'cut': relief(GP, [rec('sculpt_cut', CUT)]),
    'flat': relief(GP, [rec('sculpt_flat', FLAT5)]),
}
cases = (
    [
        {'kind': 'ground', 'p': GP},
        {'kind': 'ground', 'p': GP, 'others': [{'kind': 'sculpt_peak', 'p': PEAK}]},
        {'kind': 'ground', 'p': GP, 'others': [{'kind': 'sculpt_cut', 'p': CUT}]},
        {'kind': 'ground', 'p': GP, 'others': [{'kind': 'sculpt_flat', 'p': FLAT5}]},
    ]
    + [{'kind': k, 'p': INSIDE[k][0]} for k in SCULPT_KINDS]
    + [
        {'kind': 'ground', 'p': GP, 'others': [{'kind': 'sculpt_channel', 'p': CH_SET}]},
    ]
)
b = browser_kinds(cases)
bare, bpeak, bcut, bflat = b[0], b[1], b[2], b[3]
check(
    'tab: the ground builds real geometry, one part, vertex coloured',
    bpeak['ok'] and bpeak['registered'] and bpeak['parts'] == 1 and bpeak['vcolors'] is True,
    bpeak,
)
check('tab: it is a res x res lattice — 100 x 100 cells is 20 000 triangles', bpeak['tris'] == 20000, bpeak['tris'])
check(
    'tab: the ground is w x d in plan',
    abs(bpeak['size'][0] - 200) < 1e-3 and abs(bpeak['size'][2] - 200) < 1e-3,
    bpeak['size'],
)
check(
    'tab: the bare ground relief is the Python base roll (within 1.5 %)',
    abs(bare['size'][1] - PY_RELIEF['bare'][0]) <= 0.015 * max(1e-6, PY_RELIEF['bare'][0]),
    (bare['size'][1], PY_RELIEF['bare'][0]),
)
check(
    'tab: with a 30 m peak the mesh really is 30 m taller (within 1.5 % of the Python lattice)',
    abs(bpeak['size'][1] - PY_RELIEF['peak'][0]) <= 0.015 * PY_RELIEF['peak'][0]
    and bpeak['size'][1] > bare['size'][1] + 29,
    (bpeak['size'][1], PY_RELIEF['peak'][0]),
)
check(
    'tab: a sculpt_cut CUTS — the mesh is deeper, and matches the Python lattice',
    abs(bcut['size'][1] - PY_RELIEF['cut'][0]) <= 0.015 * PY_RELIEF['cut'][0] and bcut['min'][1] < bare['min'][1] - 9,
    (bcut['size'][1], PY_RELIEF['cut'][0], bcut['min'], bare['min']),
)
check(
    'tab: a sculpt_flat SETS — the mesh matches the Python lattice there too',
    abs(bflat['size'][1] - PY_RELIEF['flat'][0]) <= 0.015 * max(1e-6, PY_RELIEF['flat'][0]),
    (bflat['size'][1], PY_RELIEF['flat'][0]),
)
check(
    'tab: every ground build carries vertex colours',
    all(r['vcolors'] is True for r in b[:4]),
    [r['vcolors'] for r in b[:4]],
)
check("tab: the ground's label is Ground, not the raw kind", bpeak['label'] == 'Ground', bpeak['label'])
for i, k in enumerate(SCULPT_KINDS):
    r = b[4 + i]
    check(
        'tab: %s is VOID — registered, an outline, no triangles at all' % k,
        r['registered'] and r['tris'] == 0 and r['parts'] == 0 and not r['err'],
        r,
    )
check(
    'tab: a sculpt outline sits on the ground plane at y = 0.05 so it can be picked',
    all(abs(b[4 + i]['min'][1] - 0.05) < 1e-6 for i in range(len(SCULPT_KINDS))),
    [b[4 + i]['min'] for i in range(3)],
)
check(
    'tab: the peak outline is a circle of its own radius (80 m across)',
    abs(b[4]['size'][0] - 80) < 0.2 and abs(b[4]['size'][2] - 80) < 0.2,
    b[4]['size'],
)
check(
    'tab: the cut outline is the trough footprint, 200 x 60 m',
    abs(b[7]['size'][0] - 200) < 1e-3 and abs(b[7]['size'][2] - 60) < 1e-3,
    b[7]['size'],
)
check(
    'tab: every sculpt has its own readable label, none of them the raw kind',
    all(b[4 + i]['label'] and b[4 + i]['label'] != SCULPT_KINDS[i] for i in range(len(SCULPT_KINDS))),
    [b[4 + i]['label'] for i in range(len(SCULPT_KINDS))],
)
check(
    'tab: no page errors while building the ground and all ten sculpts',
    not any(r.get('page_errors') for r in b),
    [r.get('page_errors') for r in b if r.get('page_errors')][:1],
)

# ── 9. the tab's own arithmetic, and the rebuild ────────────────────────────
_LIVE = r"""
(cfg) => {
  const K = AR_EXT.ground_v3, out = {};
  /* the tab's copy of the contract, called on the very numbers Python used */
  out.heights = cfg.pts.map(q => K.heightAt(cfg.gp, q[0], q[1], cfg.recs, 0, 0, 0));
  out.weights = cfg.cw.map(q => K.colourWeights(q[0], q[1], q[2], cfg.gp.water_h, cfg.gp.snow_h, cfg.gp.grass_max_slope));
  out.noise = cfg.nz.map(q => K.vnoise(q[0], q[1], q[2]));
  /* the ground must REBUILD when a sculpt is added, moved and deleted */
  const yOf = o => new THREE.Box3().expandByObject(o.node).getSize(new THREE.Vector3()).y;
  const frame = () => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  const g = arNewObj('ground', JSON.parse(JSON.stringify(cfg.gp)), 0, 0, 0);
  out.y0 = yOf(g);
  const s = arNewObj('sculpt_peak', JSON.parse(JSON.stringify(cfg.peak)), 0, 0, 0);
  return frame().then(() => {
    out.y1 = yOf(g);
    s.x = 400; arApplyTransform(s);
    return frame();
  }).then(() => {
    out.y2 = yOf(g);
    s.x = 0; arApplyTransform(s);
    return frame();
  }).then(() => {
    out.y3 = yOf(g);
    arRemove(s);
    return frame();
  }).then(() => {
    out.y4 = yOf(g);
    arRemove(g);
    out.groundRefresh = (typeof arGroundRefresh === 'function');
    out.isSculpt = arIsSculpt('sculpt_peak') && !arIsSculpt('box');
    return out;
  });
}
"""
PTS = [(0.0, 0.0), (13.5, -47.25), (-62.0, 33.0), (99.5, 99.5), (-100.0, -100.0)]
CW = [(-5.0, 0.0, 0.0), (0.5, 10.0, 0.0), (30.0, 33.0, 0.0), (61.0, 90.0, 1.0), (10.0, 0.0, 0.4)]
NZ = [(0.3, 1.7, 1), (12.5, -3.25, 7), (-0.9, 0.9, 3)]
RECS = [rec('sculpt_peak', PEAK), rec('sculpt_cut', CUT, ry=0.7, x=20), rec('sculpt_flat', FLAT5, x=-60, z=40)]


def live(cfg, timeout_s=120):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        br = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        pg = br.new_page(viewport={'width': 1400, 'height': 900})
        pg.on('dialog', lambda dlg: dlg.accept())
        pg.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        pg.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        pg.evaluate('goToView("architecture")')
        pg.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        pg.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        out = pg.evaluate(_LIVE, cfg)
        br.close()
    return out


L = live(
    {
        'gp': GP,
        'peak': PEAK,
        'recs': RECS,
        'pts': [list(q) for q in PTS],
        'cw': [list(q) for q in CW],
        'nz': [list(q) for q in NZ],
    }
)
check(
    'tab: vnoise is the same double as the Python',
    all(abs(L['noise'][i] - G.value_noise(*NZ[i])) < 1e-12 for i in range(len(NZ))),
    L['noise'],
)
check(
    'tab: heightAt over a peak + a turned cut + a flat is the same H as the Python, to 1e-9',
    all(abs(L['heights'][i] - G.height_at(GP, PTS[i][0], PTS[i][1], RECS)) < 1e-9 for i in range(len(PTS))),
    [(L['heights'][i], G.height_at(GP, *PTS[i], RECS)) for i in range(len(PTS))],
)
check(
    'tab: colourWeights is the same five doubles as the Python',
    all(
        abs(L['weights'][i][k] - G.colour_weights(CW[i][0], CW[i][1], CW[i][2], **W)[k]) < 1e-12
        for i in range(len(CW))
        for k in range(5)
    ),
    L['weights'][:2],
)
check('tab: arGroundRefresh and arIsSculpt are the seam the studio ships', L['groundRefresh'] and L['isSculpt'], L)
check(
    'tab: ADDING a sculpt rebuilds the ground — it grows by the peak height', L['y1'] > L['y0'] + 29, (L['y0'], L['y1'])
)
check(
    'tab: MOVING a sculpt off the ground rebuilds it back to the bare roll',
    abs(L['y2'] - L['y0']) < 1e-3,
    (L['y0'], L['y2']),
)
check('tab: moving it back rebuilds the hill again', abs(L['y3'] - L['y1']) < 1e-3, (L['y1'], L['y3']))
check('tab: DELETING a sculpt rebuilds the ground without it', abs(L['y4'] - L['y0']) < 1e-3, (L['y0'], L['y4']))
check(
    'tab: the ground the browser built is the Python lattice relief (within 1.5 %)',
    abs(L['y1'] - PY_RELIEF['peak'][0]) <= 0.015 * PY_RELIEF['peak'][0],
    (L['y1'], PY_RELIEF['peak'][0]),
)

# ── 10. Blender ──────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds([{'kind': 'ground', 'p': GP, 'others': [{'kind': 'sculpt_peak', 'p': PEAK}]}])
r = bl.get('ground') or {}
check('blender: the ground builds a real mesh', r.get('polys', 0) > 0, bl)
check(
    'blender: the same 101 x 101 lattice, 20 000 triangles',
    r.get('verts') == 101 * 101 and r.get('polys') == 20000,
    (r.get('verts'), r.get('polys')),
)
check(
    'blender: 200 x 200 m in plan, the same ground as the tab',
    r.get('size') and abs(r['size'][0] - 200) < 1e-3 and abs(r['size'][2] - 200) < 1e-3,
    r.get('size'),
)
check("blender: the mesh carries a colour attribute ('Col')", r.get('vcol') is True, r)
check(
    'blender: the relief is the Python lattice relief (within 1.5 %)',
    r.get('size') and abs(r['size'][1] - PY_RELIEF['peak'][0]) <= 0.015 * PY_RELIEF['peak'][0],
    (r.get('size'), PY_RELIEF['peak'][0]),
)
check(
    'blender and the tab agree about the ground to the millimetre',
    r.get('size') and abs(r['size'][1] - bpeak['size'][1]) < 1e-3,
    (r.get('size'), bpeak['size']),
)
check(
    'blender: the lowest vertex is where Python says it is',
    r.get('min_y') is not None and abs(r['min_y'] - PY_RELIEF['peak'][1]) < 1e-2,
    (r.get('min_y'), PY_RELIEF['peak'][1]),
)
check(
    'blender: remove_doubles did not merge the colours away (101^2 vertices survive)',
    r.get('verts') == 101 * 101,
    r.get('verts'),
)
blv = blender_kinds([{'kind': k, 'p': INSIDE[k][0]} for k in SCULPT_KINDS])
for k in SCULPT_KINDS:
    rr = blv.get(k) or {}
    check(
        'blender: %s is VOID — an empty mesh, no faces, no vertices' % k,
        rr.get('polys') == 0 and rr.get('verts') == 0,
        rr or blv.get('_info'),
    )
check(
    'blender: the ten void sculpts built without an error', (blv.get('_info') or {}).get('ok') is True, blv.get('_info')
)

# ── 11. the SET channel: a riverbed is a FALLING PROFILE, not 'ground minus 2' ─
# The creator's visual check on 2026-09-07 found the river in broken blue pieces.
# The cause: the bed was cut `depth` below the LOCAL ground, so it followed the
# valley's own +-1.5 m of base noise, while the water over it sat at ONE level —
# wherever the noise rolled up, the bed came up through the water with it. A bed
# has to be a smooth fall from one end of the reach to the other. So a channel
# that names level0 AND level1 is now a SET sculpt, like sculpt_flat: it does not
# add a delta, it decides the height, and it is applied LAST.
print('python: the SET channel (the falling riverbed)')
SETREC = [rec('sculpt_channel', CH_SET)]
OLDREC = [rec('sculpt_channel', CH_OLD)]
check(
    'channel_levels is None until the record names BOTH ends — an old channel is untouched',
    G.channel_levels(CH_OLD) is None
    and G.channel_levels({'level0': -5}) is None
    and G.channel_levels({'level1': -8}) is None
    and G.channel_levels(None) is None,
    (G.channel_levels(CH_OLD), G.channel_levels({'level0': -5})),
)
check(
    'channel_levels reads the pair as two metres readings',
    G.channel_levels(CH_SET) == (-5.0, -8.0),
    G.channel_levels(CH_SET),
)
check(
    'the Blender copy of channel_levels is the same function',
    B.channel_levels(CH_SET) == G.channel_levels(CH_SET) and B.channel_levels(CH_OLD) is None,
    (B.channel_levels(CH_SET), B.channel_levels(CH_OLD)),
)
check(
    'a SET channel puts the bed at level0 at the reach START (-len/2), exactly',
    abs(G.height_at(GFLAT, -50.0, 0.0, SETREC) - (-5.0)) < 1e-6,
    G.height_at(GFLAT, -50.0, 0.0, SETREC),
)
check(
    'and at level1 at the reach END (+len/2), exactly',
    abs(G.height_at(GFLAT, 50.0, 0.0, SETREC) - (-8.0)) < 1e-6,
    G.height_at(GFLAT, 50.0, 0.0, SETREC),
)
check(
    'and it FALLS in a straight line between them — half way down is -6.5 m',
    abs(G.height_at(GFLAT, 0.0, 0.0, SETREC) - (-6.5)) < 1e-6
    and abs(G.height_at(GFLAT, -25.0, 0.0, SETREC) - (-5.75)) < 1e-6,
    (G.height_at(GFLAT, 0.0, 0.0, SETREC), G.height_at(GFLAT, -25.0, 0.0, SETREC)),
)
check(
    'the ribbon is FLAT ACROSS: the whole 12 m width is at the same falling level',
    all(abs(G.height_at(GFLAT, 0.0, zz, SETREC) - (-6.5)) < 1e-6 for zz in (-6.0, -3.0, 0.0, 3.0, 6.0)),
    [G.height_at(GFLAT, 0.0, zz, SETREC) for zz in (-6.0, 0.0, 6.0)],
)
check(
    'and it FEATHERS UP to the ground over the 4 m banks — at the bank edge the land is untouched',
    abs(G.height_at(GFLAT, 0.0, 10.0, SETREC) - G.base_height(GFLAT, 0.0, 10.0)) < 1e-9
    and -6.5 < G.height_at(GFLAT, 0.0, 8.0, SETREC) < G.base_height(GFLAT, 0.0, 8.0),
    [G.height_at(GFLAT, 0.0, zz, SETREC) for zz in (7.0, 8.0, 9.0, 10.0)],
)
check(
    'WITHOUT the pair a channel still just lowers the ground by depth — the old checks stand',
    abs(G.height_at(GP, 0.0, 0.0, OLDREC) - (G.base_height(GP, 0.0, 0.0) - 2.0)) < 1e-9,
    (G.height_at(GP, 0.0, 0.0, OLDREC), G.base_height(GP, 0.0, 0.0) - 2.0),
)
check(
    'a SET channel is applied LAST: a 30 m peak right on top of it does not lift the bed',
    abs(G.height_at(GFLAT, 0.0, 0.0, SETREC + [rec('sculpt_peak', PEAK)]) - (-6.5)) < 1e-6
    and G.height_at(GFLAT, 0.0, 30.0, SETREC + [rec('sculpt_peak', PEAK)]) > 3,
    (
        G.height_at(GFLAT, 0.0, 0.0, SETREC + [rec('sculpt_peak', PEAK)]),
        G.height_at(GFLAT, 0.0, 30.0, SETREC + [rec('sculpt_peak', PEAK)]),
    ),
)
SETPTS = [(-50.0, 0.0), (-13.0, 2.5), (0.0, 0.0), (17.5, -7.0), (50.0, 0.0), (0.0, 10.0)]
check(
    'the Blender copy of height_at gives the same double over a SET channel',
    all(abs(B.height_at(GP, q[0], q[1], SETREC) - G.height_at(GP, q[0], q[1], SETREC)) < 1e-12 for q in SETPTS),
    [(B.height_at(GP, *q, SETREC), G.height_at(GP, *q, SETREC)) for q in SETPTS[:2]],
)
PY_SET = relief(GP, SETREC)
bset = b[-1]
check(
    'tab: the SET channel reaches the browser and the ground mesh goes down to level1 (-8 m, within 1.5 %)',
    abs(bset['min'][1] - (-8.0)) <= 0.015 * 8.0,
    (bset['min'], PY_SET),
)
check(
    'tab: the whole relief over a SET channel is the Python lattice relief (within 1.5 %)',
    abs(bset['size'][1] - PY_SET[0]) <= 0.015 * PY_SET[0] and not bset['err'],
    (bset['size'], PY_SET, bset['err']),
)
check(
    'tab: and the Python lattice agrees the lowest point IS the downstream end of the bed',
    abs(PY_SET[1] - (-8.0)) < 1e-6,
    PY_SET,
)

finish()
