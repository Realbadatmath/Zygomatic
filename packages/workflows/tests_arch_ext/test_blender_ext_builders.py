# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_blender_ext_builders.py — the Blender builders for the
kinds the operator's own 20-storey tower uses on its roof deck and its escape.

Every `p` below is lifted verbatim from the live drawing
tests_arch_ext/fixtures/live_tower_20260911.json (job 94f5813b), so the test
fails the day a builder stops agreeing with what the assistant actually writes.

    /usr/bin/python3 tests_arch_ext/test_blender_ext_builders.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, blender_kinds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'live_tower_20260911.json')

# id -> kind, exactly as the live tower records them.
WANTED = {
    'o507': 'pool',
    'o572': 'sun_lounger',
    'o573': 'umbrella',
    'o334': 'elevator_shaft',
    'o335': 'elevator_car',
    'o228': 'stair_u',
    'o498': 'fire_stair_exterior',
}
KINDS = ['pool', 'sun_lounger', 'umbrella', 'elevator_shaft', 'elevator_car', 'stair_u', 'fire_stair_exterior']

print('fixture')
doc = json.load(open(FIXTURE, encoding='utf-8'))
by_id = {o['id']: o for o in doc['objects']}
check('live tower fixture has 336 records', len(doc['objects']) == 336, len(doc['objects']))
found = {i: by_id.get(i) for i in WANTED}
check(
    'every sample record is present and of the expected kind',
    all(found[i] and found[i]['kind'] == k for i, k in WANTED.items()),
    {i: (found[i] or {}).get('kind') for i in WANTED},
)

params = {WANTED[i]: found[i]['p'] for i in WANTED}
# The escape the brief measures: 20 storeys of 2.7 m, 0.28 run, 0.18 rise, 1.2 wide.
fse = params['fire_stair_exterior']
check(
    'fire escape params are the measured ones',
    fse.get('storeys') == 20
    and fse.get('h') == 2.7
    and fse.get('w') == 1.2
    and fse.get('run') == 0.28
    and fse.get('rise') == 0.18,
    fse,
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
cases = [{'kind': k, 'p': params[k]} for k in KINDS]
bl = blender_kinds(cases)

for kind in KINDS:
    r = bl.get(kind) or {}
    check(f'blender builds {kind}', r.get('verts', 0) > 8 and r.get('polys', 0) > 0, r)

# 20 storeys x (15 treads + 1 landing) = 320 boxes = 1920 faces. The raw 2560
# verts never survive: arch_blender_build.py:587 runs remove_doubles on every
# builder that does not own vertex colours, and consecutive treads share their
# corners, so the mesh lands at 1915 verts / 1907 faces. Both counts still scale
# with the storey count, so a builder that quietly dropped a flight fails here.
fs = bl.get('fire_stair_exterior') or {}
check('fire escape is 320 welded boxes (>= 1890 faces)', fs.get('polys', 0) >= 1890, fs)
check('fire escape keeps >= 1900 verts after welding', fs.get('verts', 0) >= 1900, fs)

# size = world bbox [x, y_up, z]; flights run 4.2 m with a 1.2 m landing hanging
# off each end -> 6.60 m of x, and 20 x 2.7 = 54.00 m of climb.
sz = fs.get('size') or [0, 0, 0]
check('fire escape x extent is 6.60 m', abs(sz[0] - 6.60) < 0.05, sz)
check('fire escape is 54.00 m tall', abs(sz[1] - 54.00) < 0.05, sz)

# The lift shaft is the tower's full 55.8 m; the car is one storey of it.
shaft = (bl.get('elevator_shaft') or {}).get('size') or [0, 0, 0]
check(
    'lift shaft is 1.8 x 55.8 x 2.0 m',
    abs(shaft[0] - 1.8) < 0.06 and abs(shaft[1] - 55.8) < 0.06 and abs(shaft[2] - 2.0) < 0.06,
    shaft,
)
car = (bl.get('elevator_car') or {}).get('size') or [0, 0, 0]
check(
    'lift car is 1.4 x 2.2 x 1.6 m',
    abs(car[0] - 1.4) < 0.06 and abs(car[1] - 2.2) < 0.06 and abs(car[2] - 1.6) < 0.06,
    car,
)

# The roof pool is raised 1.5 m onto its deck, so nothing of it digs below z=0.
# In plan it is w=12.0 by d=5.7 PLUS the 0.5 m catch trough that the inf:'s'
# edge hangs outside the south wall -> 6.2 m of depth, not 5.7.
pool = bl.get('pool') or {}
psz = pool.get('size') or [0, 0, 0]
check(
    'roof pool is 12.0 x 6.2 m in plan (5.7 basin + 0.5 infinity trough)',
    abs(psz[0] - 12.0) < 0.06 and abs(psz[2] - 6.2) < 0.06,
    psz,
)
check('raised pool sits on its deck (min y >= -0.01)', (pool.get('min_y') or 0) > -0.01, pool.get('min_y'))

finish()
