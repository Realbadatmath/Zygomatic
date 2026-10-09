# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_envelope_rules — the building envelope and what may stand where.

No new kinds, so no browser/Blender pass: this family is pure geometry over the
records other families make. The proof is the numbers of a real draw_box.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
E = A.EXT_MODULES['envelope_rules']
DR = A.EXT_MODULES['design_rules']


def tower():
    d = A.Drawing(None)
    txt = A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=3, roof='flat', name='tower'))
    return d, txt


def codes(d):
    return [f['code'] for f in E.check_envelope(d)]


def texts(d):
    return ' | '.join(f['text'] for f in E.check_envelope(d))


# ── the envelope of a real draw_box ──────────────────────────────────────────
d, txt = tower()
env = E.group_envelope(d, 'tower')
check('draw_box drew the tower', 'drew group "tower"' in txt, txt[:120])
check('group_envelope finds the group', env is not None, env)
check(
    'envelope spans 20 x 20 m',
    abs((env['xmax'] - env['xmin']) - 20) < 0.3 and abs((env['zmax'] - env['zmin']) - 20) < 0.3,
    env,
)
check('top_deck is the flat roof top 3 x 2.7 + 0.3', abs(env['top_deck'] - (3 * 2.7 + 0.3)) < 0.05, env)
check('storeys reads 3', env['storeys'] == 3, env)
check('envelopes() lists exactly the tower', list(E.envelopes(d)) == ['tower'], list(E.envelopes(d)))
check('a group that is not a building has no envelope', E.group_envelope(d, 'nothing here') is None)

cx, cz = (env['xmin'] + env['xmax']) / 2, (env['zmin'] + env['zmax']) / 2
check('inside() at the centre', E.inside(env, cx, cz))
check('inside() is False 1 m east of the east wall', not E.inside(env, env['xmax'] + 1.0, cz))
check('group_at() names the tower at the centre', E.group_at(d, cx, cz) == 'tower', E.group_at(d, cx, cz))
check('group_at() is None 1 m outside', E.group_at(d, env['xmax'] + 1.0, cz) is None)

# north = -Z (zmin), south = +Z, west = -X, east = +X — wall_on_side's naming
check(
    'touches_facade north = zmin edge',
    E.touches_facade(env, cx, env['zmin'] - 0.2) == 'north',
    E.touches_facade(env, cx, env['zmin'] - 0.2),
)
check(
    'touches_facade south = zmax edge',
    E.touches_facade(env, cx, env['zmax'] + 0.2) == 'south',
    E.touches_facade(env, cx, env['zmax'] + 0.2),
)
check(
    'touches_facade west = xmin edge',
    E.touches_facade(env, env['xmin'] - 0.2, cz) == 'west',
    E.touches_facade(env, env['xmin'] - 0.2, cz),
)
check(
    'touches_facade east = xmax edge',
    E.touches_facade(env, env['xmax'] + 0.2, cz) == 'east',
    E.touches_facade(env, env['xmax'] + 0.2, cz),
)
check('touches_facade None 5 m off the plan', E.touches_facade(env, cx, env['zmax'] + 5.0) is None)

# ── bbox_of: the footprints the stair kinds really have ──────────────────────
su = {
    'id': 'oX',
    'kind': 'stair_u',
    'name': 'u stair',
    'x': 0.0,
    'z': 0.0,
    'y': 0.0,
    'ry': 0.0,
    's': 1,
    'p': {'steps': 16, 'rise': 0.175, 'run': 0.28, 'w': 1.0, 'gap': 0.2},
}
bb = E.bbox_of(su)
check(
    'bbox_of(stair_u) = 8*0.28 + 1.0 along X by 2*1 + 0.2 across',
    abs((bb[2] - bb[0]) - (8 * 0.28 + 1.0)) < 1e-6 and abs((bb[3] - bb[1]) - 2.2) < 1e-6,
    bb,
)
su90 = dict(su, ry=1.5707963267948966)
bb90 = E.bbox_of(su90)
check(
    'bbox_of turns with ry: 90 deg swaps the sides',
    abs((bb90[2] - bb90[0]) - 2.2) < 1e-4 and abs((bb90[3] - bb90[1]) - (8 * 0.28 + 1.0)) < 1e-4,
    bb90,
)
fs = {
    'id': 'oY',
    'kind': 'fire_stair_exterior',
    'name': 'fire escape',
    'x': 0.0,
    'z': 0.0,
    'y': 0.0,
    'ry': 0.0,
    's': 1,
    'p': {'storeys': 3, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18},
}
bbf = E.bbox_of(fs)
check(
    'bbox_of(fire_stair_exterior) = 15*0.28 + 1.2 by 1.2',
    abs((bbf[2] - bbf[0]) - (15 * 0.28 + 1.2)) < 1e-6 and abs((bbf[3] - bbf[1]) - 1.2) < 1e-6,
    bbf,
)

# ── (b) an interior room standing outside every building ─────────────────────
d2, _ = tower()
e2 = E.group_envelope(d2, 'tower')
d2.new(
    'partition',
    {'len': 4, 'h': 2.7, 't': 0.10},
    e2['xmax'] + 5.0,
    (e2['zmin'] + e2['zmax']) / 2,
    0.0,
    0.0,
    name='WC wall',
    grp='WC',
)
c2, t2 = codes(d2), texts(d2)
check('a partition 5 m outside the plan is an error', 'envelope_outside' in c2, c2)
check('the finding names the group of the partition', 'WC' in t2 and 'outside every building' in t2, t2)
check('the finding names the plan cells', 'EX90..FQ109' in t2, t2)

# ── (a) an interior record whose footprint pokes out of its own envelope ─────
d3, _ = tower()
e3 = E.group_envelope(d3, 'tower')
d3.new(
    'partition',
    {'len': 6, 'h': 2.7, 't': 0.10},
    e3['xmax'] - 1.0,
    (e3['zmin'] + e3['zmax']) / 2,
    0.0,
    0.0,
    name='long partition',
    grp='tower',
)
c3, t3 = codes(d3), texts(d3)
check('a partition poking 2 m out of its envelope is an error', 'envelope_poke' in c3, c3)
check(
    'the poke finding names the group, the overhang and the side', 'tower' in t3 and '2.0 m' in t3 and 'east' in t3, t3
)
check('nothing pokes when it fits', 'envelope_poke' not in codes(tower()[0]), codes(tower()[0]))

# ── (c) a fire escape inside the plan, and one on the facade ────────────────
d4, _ = tower()
e4 = E.group_envelope(d4, 'tower')
d4.new(
    'fire_stair_exterior',
    {'storeys': 3, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18},
    (e4['xmin'] + e4['xmax']) / 2,
    (e4['zmin'] + e4['zmax']) / 2,
    0.0,
    0.0,
    name='fire escape',
)
c4, t4 = codes(d4), texts(d4)
check('a fire escape in the middle of the plan is an error', 'envelope_exterior' in c4, c4)
check('the fire escape finding says INSIDE and names the group', 'INSIDE' in t4 and '"tower"' in t4, t4)

d5, _ = tower()
e5 = E.group_envelope(d5, 'tower')
d5.new(
    'fire_stair_exterior',
    {'storeys': 3, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18},
    (e5['xmin'] + e5['xmax']) / 2,
    e5['zmin'] - 0.8,
    0.0,
    0.0,
    name='fire escape',
)
check('a fire escape 0.8 m north of the north wall is clean', codes(d5) == [], texts(d5))

# ── (d) a canopy hanging in mid air ─────────────────────────────────────────
d6, _ = tower()
e6 = E.group_envelope(d6, 'tower')
d6.new(
    'canopy',
    {'w': 3, 'd': 1.5, 't': 0.12, 'h_drop': 0},
    (e6['xmin'] + e6['xmax']) / 2,
    e6['zmax'] + 5.0,
    2.7,
    0.0,
    name='entrance canopy',
)
c6, t6 = codes(d6), texts(d6)
check('a canopy 5 m off the wall is an error', 'envelope_exterior' in c6, c6)
check('the canopy finding says it touches no facade', 'touches no facade' in t6, t6)

# ── an empty drawing, and the family contract ───────────────────────────────
check(
    'an empty drawing has no envelope findings',
    E.check_envelope(A.Drawing(None)) == [],
    E.check_envelope(A.Drawing(None)),
)
d7 = A.Drawing(None)
d7.new('partition', {'len': 4, 'h': 2.7, 't': 0.10}, 5.0, 5.0, 0.0, 0.0, name='WC wall', grp='WC')
check(
    'a drawing with no building at all is silent (nothing to be outside of)',
    E.check_envelope(d7) == [],
    E.check_envelope(d7),
)
check('DESIGN_CHECKS exports check_envelope', E.check_envelope in (E.DESIGN_CHECKS or []))
check('design_rules collects it', E.check_envelope in DR.contributed())
check(
    'run_checks reports the envelope error',
    'envelope_outside' in {f['code'] for f in DR.run_checks(d2)},
    {f['code'] for f in DR.run_checks(d2)},
)
check('PROMPT is one paragraph under 600 chars', 0 < len(E.PROMPT) <= 600 and '\n' not in E.PROMPT, len(E.PROMPT))
check('two worked examples', len(E.EXAMPLES) >= 2 and all(x.get('ask') and x.get('calls') for x in E.EXAMPLES))
check(
    'INTERIOR_KINDS holds the stair and lift kinds',
    {'stair_u', 'stair_straight', 'elevator_shaft', 'partition'} <= set(E.INTERIOR_KINDS),
)
check(
    'interior_kinds() picks up the furniture families lazily',
    'sofa' in E.interior_kinds() and 'toilet' in E.interior_kinds(),
)
check(
    'EXTERIOR_KINDS holds the facade kinds',
    {'fire_stair_exterior', 'canopy', 'balcony', 'awning', 'porch'} == set(E.EXTERIOR_KINDS),
)


# ── (e) a partition drawn ON a facade line ──────────────────────────────────
# The live tower's lobby: add_room put the south partition on the facade line with
# its own door a metre beside the facade's glass double door.
def shell():
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=3, roof='flat', name='shell'))
    return d


def fcodes(d):
    return [f['code'] for f in E.check_facade_partitions(d)]


def ftexts(d):
    return ' | '.join(f['text'] for f in E.check_facade_partitions(d))


d8 = shell()
d8.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 14.0, -41.0, 0, 0, 'mat_plaster', grp='Lobby')
f8 = E.check_facade_partitions(d8)
check('a partition on the south facade line is reported once', fcodes(d8) == ['env_facade_partition'], fcodes(d8))
check('on an opaque storey it is a warning, not an error', f8[0]['sev'] == 'warn', f8[0]['sev'])
check(
    'the finding names the side and the group',
    'south facade' in f8[0]['text'] and '"shell"' in f8[0]['text'],
    f8[0]['text'],
)
check(
    'it names the storey and says the facade is the room wall',
    'storey 0' in f8[0]['text'] and "the facade is the room's wall" in f8[0]['text'],
    f8[0]['text'],
)
check('it warns that a door here is a second entrance', 'second entrance' in f8[0]['text'], f8[0]['text'])

d9 = shell()
A.call_tool(d9, 'add_curtain_wall', dict(walls='shell', storeys=[0]))
d9.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 14.0, -41.0, 0, 0, 'mat_plaster', grp='Lobby')
f9 = E.check_facade_partitions(d9)
check('the same partition on a GLAZED storey is an error', len(f9) == 1 and f9[0]['sev'] == 'error', f9)
check(
    'the glazed finding says curtain wall and the blocked view',
    'curtain wall' in f9[0]['text'] and 'blocks the view' in f9[0]['text'],
    f9[0]['text'],
)

d10 = shell()
d10.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 14.0, -42.0, 0, 0, 'mat_plaster', grp='Lobby')
check(
    'a partition 1 m inside the facade is a real room wall — silent', E.check_facade_partitions(d10) == [], ftexts(d10)
)

d11 = shell()
d11.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 3.0, -51.0, 0, math.pi / 2, 'mat_plaster', grp='Lobby')
check('a partition along Z on the x-min line doubles the WEST facade', 'west facade' in ftexts(d11), ftexts(d11))

d12 = shell()
d12.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 3.0, -51.0, 0, 0, 'mat_plaster', grp='Lobby')
check(
    'a partition running along X that merely reaches the west line is not doubling it',
    E.check_facade_partitions(d12) == [],
    ftexts(d12),
)

d13 = A.Drawing(None)
d13.new('partition', {'len': 10, 'h': 2.5, 't': 0.15}, 14.0, -41.0, 0, 0, 'mat_plaster', grp='Lobby')
check(
    'a partition with no building around it is silent',
    E.check_facade_partitions(d13) == [],
    E.check_facade_partitions(d13),
)

check('DESIGN_CHECKS exports check_facade_partitions', E.check_facade_partitions in (E.DESIGN_CHECKS or []))
check('design_rules collects it too', E.check_facade_partitions in DR.contributed())
check(
    'run_checks reports the facade partition',
    'env_facade_partition' in {f['code'] for f in DR.run_checks(d8)},
    {f['code'] for f in DR.run_checks(d8)},
)

finish()
