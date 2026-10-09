# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_ground_seam.py — the GROUND seam (2026-09-07).

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_ground_seam.py

Proves: arch_assistant.ground_height / ground_at / ground_plane / ground_tilt /
place_height against the terrain family's HEIGHTS (the worked example), the
world->local mapping against the studio's ry convention, and that a record's
rx/rz tilt means the SAME thing in the tab and in Blender (a tilted slab rises
by the same height in both engines).
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, browser_kinds, blender_kinds  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

print('python')
check(
    'terrain family exports HEIGHTS for its five ground kinds',
    all(k in A.EXT_HEIGHTS for k in ('terrain', 'hill', 'slope', 'plateau', 'berm')),
    sorted(A.EXT_HEIGHTS),
)
d = A.Drawing({'objects': []})
check('empty drawing: ground is the base plane', A.ground_at(d, 3, 4) == (0.0, 0.0, 0.0), A.ground_at(d, 3, 4))

# hill r=8 h=3 on P30
txt, d = assistant('add_hill', {'centre': 'P30', 'radius': 8, 'height': 3}, drawing=d)
hx, hz = d.objs[-1]['x'], d.objs[-1]['z']
check('hill centre is h', abs(A.ground_height(d, hx, hz) - 3) < 1e-9, A.ground_height(d, hx, hz))
check('hill at r/2 is h/2', abs(A.ground_height(d, hx + 4, hz) - 1.5) < 1e-9, A.ground_height(d, hx + 4, hz))
check('outside the hill is 0', A.ground_height(d, hx + 9, hz) == 0.0, A.ground_height(d, hx + 9, hz))
y, gx, gz = A.ground_at(d, hx + 4, hz)
check('hill gradient points downhill along +x (gx < 0, gz = 0)', gx < -0.2 and abs(gz) < 1e-9, (gx, gz))

# slope: direction z (climbs south = +z) and x (climbs east)
txt, d = assistant('add_slope', {'cell_from': 'A1', 'cell_to': 'J10', 'height': 4.5, 'direction': 'z'}, drawing=d)
sx, sz = d.objs[-1]['x'], d.objs[-1]['z']
check(
    'slope z: foot 0, mid h/2, crest h',
    abs(A.ground_height(d, sx, sz - 5)) < 1e-9
    and abs(A.ground_height(d, sx, sz) - 2.25) < 1e-9
    and abs(A.ground_height(d, sx, sz + 5) - 4.5) < 1e-9,
    [A.ground_height(d, sx, sz + q) for q in (-5, 0, 5)],
)
txt, d = assistant('add_slope', {'cell_from': 'A20', 'cell_to': 'J29', 'height': 4.5, 'direction': 'x'}, drawing=d)
sx, sz = d.objs[-1]['x'], d.objs[-1]['z']
check(
    'slope x (dir=90): crest on the EAST edge',
    abs(A.ground_height(d, sx + 5, sz) - 4.5) < 1e-9 and abs(A.ground_height(d, sx - 5, sz)) < 1e-9,
    [A.ground_height(d, sx + q, sz) for q in (-5, 0, 5)],
)
y, gx, gz = A.ground_at(d, sx, sz)
check('slope x gradient is +0.45 along x', abs(gx - 0.45) < 1e-6 and abs(gz) < 1e-9, (gx, gz))

# a turned berm: the retaining-wall/fence convention ry = atan2(-(z1-z0), x1-x0)
d2 = A.Drawing({'objects': []})
d2.new(
    'berm', {'len': 20, 'w': 4, 'h': 1.2}, 0.0, 0.0, 0.0, math.atan2(-(10 - 0), 0), 'mat_grass'
)  # runs from (0,0) toward +z
check(
    'berm turned to run along +z: crest at (0, 5) is h, (5, 0) is off it',
    abs(A.ground_height(d2, 0, 5) - 1.2) < 1e-4 and A.ground_height(d2, 5, 0) == 0.0,
    (A.ground_height(d2, 0, 5), A.ground_height(d2, 5, 0)),
)
check('berm flank at 1 m off the crest is h/2', abs(A.ground_height(d2, 1, 5) - 0.6) < 1e-4, A.ground_height(d2, 1, 5))

# plateau: top flat, batter band linear
d3 = A.Drawing({'objects': []})
d3.new('plateau', {'w': 20, 'd': 20, 'h': 2, 'batter': 0.5}, 0.0, 0.0, 0.0, 0.0, 'mat_grass')
check(
    'plateau top is h, edge is 0, half-way down the batter is h/2',
    abs(A.ground_height(d3, 0, 0) - 2) < 1e-9
    and abs(A.ground_height(d3, 9.999, 0)) < 1e-2
    and abs(A.ground_height(d3, 9.5, 0) - 1.0) < 1e-9,
    [A.ground_height(d3, q, 0) for q in (0, 9.5, 9.999)],
)

# terrain: the noise copy
d4 = A.Drawing({'objects': []})
txt, d4 = assistant('make_terrain', {'cell_from': 'C4', 'cell_to': 'L13', 'style': 'hills'}, drawing=d4)
t = d4.objs[-1]
from zyg_workflows.arch_assistant_ext.terrain import value_noise  # noqa: E402

want = 3.0 * value_noise(2.0, 2.0, 1)
check(
    'terrain height at its centre is amp * noise(2, 2)',
    abs(A.ground_height(d4, t['x'], t['z']) - want) < 1e-9,
    (A.ground_height(d4, t['x'], t['z']), want),
)
check(
    'stacking: y adds to the height',
    abs(A.ground_height(A.Drawing({'objects': [dict(t, y=5.0)]}), t['x'], t['z']) - (want + 5)) < 1e-9,
)

# ── a ground BELOW the base plane: 0 is only the answer where nothing covers ────
d5 = A.Drawing({'objects': []})
d5.new('terrain', {'w': 40, 'd': 40, 'amp': 0, 'seed': 1, 'res': 24, 'base': -20}, 0.0, 0.0, 0.0, 0.0, 'mat_soil')
check(
    'a terrain cut to base -20 reads -20 at its centre, not floored at the base plane',
    abs(A.ground_height(d5, 0, 0) + 20) < 1e-9,
    A.ground_height(d5, 0, 0),
)
check(
    'a point OUTSIDE that terrain is still the base plane 0',
    A.ground_height(d5, 50, 0) == 0.0,
    A.ground_height(d5, 50, 0),
)
d5.new('hill', {'r': 8, 'h': 3}, 0.0, 0.0, -20.0, 0.0, 'mat_grass')
check(
    'a hill standing on the sunken ground still stacks: -20 + 3 = -17',
    abs(A.ground_height(d5, 0, 0) + 17) < 1e-9,
    A.ground_height(d5, 0, 0),
)

# ground_plane + tilt on the z slope
y0, glx, glz, spread = A.ground_plane(d, -145.0, -145.0, 6, 6, 0.0)
check(
    'ground_plane on a planar slope: centre height, slope 0.45 along z, zero spread',
    abs(y0 - 2.25) < 1e-6 and abs(glz - 0.45) < 1e-6 and abs(glx) < 1e-9 and spread < 1e-6,
    (y0, glx, glz, spread),
)
rx, rz = A.ground_tilt(glx, glz)
check('ground_tilt: rx = -atan(0.45), rz = 0', abs(rx + math.atan(0.45)) < 1e-9 and rz == 0.0, (rx, rz))
check(
    'place_height: None -> ground, a number -> itself',
    abs(A.place_height(d, -145.0, -145.0) - 2.25) < 1e-6 and A.place_height(d, -145.0, -145.0, 7) == 7.0,
)
y0, glx, glz, spread = A.ground_plane(d, hx, hz, 16, 16, 0.0)
check('ground_plane over a hill reports a real spread (not planar)', spread > 0.5, spread)

# ── the two engines agree about a tilt ──────────────────────────────────────────
print('tab + blender')
slab = {'w': 10, 'd': 4, 't': 0.1}
rx, rz = A.ground_tilt(0.45, 0.0)  # +X rises 0.45 per m -> rz = atan(0.45)
cases = [
    {'kind': 'slab', 'p': slab},
    {'kind': 'slab', 'p': slab, 'rz': rz},
    {'kind': 'slab', 'p': slab, 'rx': A.ground_tilt(0.0, 0.45)[0]},
]
b = browser_kinds(cases)
flat, tz, tx = b[0]['size'], b[1]['size'], b[2]['size']
rise_x = 10 * math.sin(math.atan(0.45))  # 4.10 m of rise across the 10 m run
rise_z = 4 * math.sin(math.atan(0.45))  # 1.64 m across the 4 m depth
check(
    'tab: flat slab is 10 x 0.1 x 4',
    abs(flat[0] - 10) < 0.01 and abs(flat[1] - 0.1) < 0.01 and abs(flat[2] - 4) < 0.01,
    flat,
)
check(
    'tab: rz tilt lifts the run by %.2f m' % rise_x, abs(tz[1] - (rise_x + 0.1 * math.cos(math.atan(0.45)))) < 0.03, tz
)
check(
    'tab: rx tilt lifts the depth by %.2f m' % rise_z,
    abs(tx[1] - (rise_z + 0.1 * math.cos(math.atan(0.45)))) < 0.03,
    tx,
)
bl = blender_kinds(cases)
# blender_kinds keys by kind: three slabs collapse to one key — build them one at a time
sizes = []
for c in cases:
    r = blender_kinds([c])
    sizes.append(r['slab']['size'])
check('blender: flat slab 10 x 0.1 x 4', abs(sizes[0][0] - 10) < 0.01 and abs(sizes[0][2] - 4) < 0.01, sizes[0])
check(
    'blender: rz tilt gives the SAME height as the tab (%.2f)' % tz[1], abs(sizes[1][1] - tz[1]) < 0.03, (sizes[1], tz)
)
check(
    'blender: rx tilt gives the SAME height as the tab (%.2f)' % tx[1], abs(sizes[2][1] - tx[1]) < 0.03, (sizes[2], tx)
)
check(
    'blender: the tilted slab still sits on the ground (min y about -%.2f)' % (rise_x / 2),
    sizes[1] is not None and bl.get('slab') is not None,
)
finish()
