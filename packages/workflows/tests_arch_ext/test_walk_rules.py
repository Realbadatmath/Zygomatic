# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_walk_rules — can a person actually walk the building?

"Cannot walk it" was the operator's third defect on 2026-09-12: the stair
arrived inside a lift shaft, with no landing anywhere outside a shaft, and no
check noticed because no check ever walked. walk_rules rasterises each storey
at 0.25 m and floods it from the way in.

Every scenario here is an A/B: build the thing, prove the check is SILENT on
it, then put one partition in the way and prove the check names THAT partition
— not the wall the person walked through by its door ten metres back.
"""

import json
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
W = A.EXT_MODULES['walk_rules']
E = A.EXT_MODULES['envelope_rules']

FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')


# ── helpers ──────────────────────────────────────────────────────────────────
def findings(d):
    return W.check_walkable(d)


def codes(d):
    return [f['code'] for f in findings(d)]


def texts(d):
    return ' | '.join(f['text'] for f in findings(d))


def tower(storeys=8):
    """A box with a core that goes all the way up and one door to come in by.

    add_stair/add_elevator default to to_storey=1 and 3; leave the defaults and
    the upper storeys have no core at all, so the walk has nowhere to start
    and the whole check is vacuously silent.
    """
    d = A.Drawing(None)
    A.call_tool(d, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=storeys, roof='flat', name='tower'))
    A.call_tool(d, 'add_stair', dict(cell='FH93', kind='u', from_storey=0, to_storey=storeys, name='st'))
    A.call_tool(d, 'add_elevator', dict(cell='FD93', from_storey=0, to_storey=storeys, door_side='south', name='lift'))
    A.call_tool(d, 'add_opening', dict(wall_id='o2', kind='double_door', at='middle'))
    return d


def wall_across(d, x, z, y, length=20.0, name='screen', turned=False):
    """A partition dropped straight across the route.

    d.new's ry is RADIANS, not degrees — passing 90 gives a wall at 63.6 deg
    that still looks plausible in a bbox and quietly misses what it is meant
    to block.
    """
    ry = math.pi / 2 if turned else 0.0
    d.new('partition', {'len': length, 't': 0.1, 'h': 2.4}, x, z, y, ry, None, name, 'tower')
    return d.objs[-1]['id']


# ── the contract ─────────────────────────────────────────────────────────────
check(
    'the family is check-only',
    W.PROMPT == '' and W.TOOLS == [] and W.KINDS == {},
    f'PROMPT={len(W.PROMPT)} chars, TOOLS={len(W.TOOLS)}, KINDS={len(W.KINDS)}',
)
check(
    'it exports one design check',
    [f.__name__ for f in W.DESIGN_CHECKS] == ['check_walkable'],
    str([f.__name__ for f in W.DESIGN_CHECKS]),
)

_junk = W.check_walkable(object())
check(
    'a check never raises', isinstance(_junk, list) and all(f['sev'] == 'info' for f in _junk), f'garbage in -> {_junk}'
)

_shape = all(
    set(f) >= {'sev', 'code', 'text'} and f['sev'] in ('error', 'warn', 'info') and f['code'].startswith('walk_')
    for f in findings(A.Drawing(json.load(open(FIXTURE))))
)
check('findings keep the design-check shape', _shape)


# ── (a) entrance -> core, storey 0 ───────────────────────────────────────────
d = tower()
check('a bare tower with a core and a door is walkable', not codes(d), texts(d))

A.call_tool(d, 'add_room', dict(cell_from='FD104', cell_to='FM108', name='Lobby'))
check(
    'adding the Lobby keeps it walkable',
    not codes(d),
    'The brief expected the lobby partitions to be the obstacle. They are not: '
    'add_room puts the Lobby 9..19 x -47..-42 inside a 20 m wide plate, so the '
    '1 m strip behind the entrance runs on past both ends of it and up the west '
    'and east flanks to the core. Nothing is sealed, so the check is right to be '
    'silent. detail: ' + (texts(d) or 'silent'),
)

blocker = wall_across(d, 13.0, -51.0, 0.0)
c = codes(d)
check(
    'a partition across the corridor to the core -> walk_entrance_core',
    c.count('walk_entrance_core') == 2 and set(c) == {'walk_entrance_core'},
    f'{c} :: {texts(d)}',
)
check(
    '...and it names the partition, not a wall with a door in it',
    all(blocker in f['text'] for f in findings(d) if f['sev'] == 'error'),
    f'expected {blocker} in every error; got: {texts(d)}',
)

d.objs.pop()
check('taking the partition away goes silent again', not codes(d), texts(d))


# ── (b) a laid-out storey, core -> every unit door ───────────────────────────
d = tower()
A.call_tool(
    d,
    'layout_floor',
    dict(cell_from='EX90', cell_to='FQ109', use='residential', storey=1, core_from='FC92', core_to='FK97'),
)
A.call_tool(d, 'repeat_floor', dict(from_storey=2, to_storey=7, source_storey=1))
base_f = findings(d)
base_c = [f['code'] for f in base_f]
# HISTORY. Until 2026-09-16 these two checks were the other way round: they PINNED a
# product defect, because layout_floor ran "corridor wall north" the full 20 m of the
# plate and cut no opening in it where the core block is, so the stair reached no unit
# door on any repeated storey and every laid-out storey was one walk_storey error. The
# tool now cuts the core doors itself (and repeat_floor carries them up with the right
# host), so the defect is gone and the correct assertion is silence.
check(
    'layout_floor cuts the core doors, so the corridor is NOT sealed off',
    not base_c,
    'expected no walk finding on 7 laid-out storeys; got: ' + (texts(d) or 'silent'),
)
check(
    'and every storey the repeat carried up is walkable too',
    not [f for f in base_f if 'on storey' in f['text']],
    [f['text'] for f in base_f],
)

blocker = wall_across(d, 9.0, -51.0, 5 * 2.7, length=2.0, name='corridor blocker', turned=True)
st5 = [f for f in findings(d) if 'on storey 5' in f['text']]
check(
    'a partition across the storey-5 corridor -> walk_storey on storey 5',
    len(st5) == 1 and st5[0]['code'] == 'walk_storey' and blocker in st5[0]['text'],
    f'{[f["text"] for f in st5]}',
)

d.objs.pop()
check('removing it clears storey 5 again', not [f for f in findings(d) if 'on storey 5' in f['text']], texts(d))


# ── (c) the roof deck ────────────────────────────────────────────────────────
d = tower()
A.call_tool(d, 'add_infinity_pool', dict(cell_from='FA100', cell_to='FO109', view='south', storey=8))
check('a pool deck reached from the head house is walkable', not codes(d), texts(d))

blocker = wall_across(d, 13.0, -54.0, 21.9)
c = codes(d)
check(
    'a wall between the head house door and the pool -> walk_deck',
    c and set(c) == {'walk_deck'} and all(blocker in f['text'] for f in findings(d)),
    f'{c} :: {texts(d)}',
)
check(
    '...and it reports the pool AND the loungers',
    any('infinity pool' in f['text'] for f in findings(d)) and any('lounger' in f['text'] for f in findings(d)),
    texts(d),
)

d.objs.pop()
check('removing it goes silent again', not codes(d), texts(d))


# ── (d) the live fixture: the stair standing inside the lift shafts ──────────
dl = A.Drawing(json.load(open(FIXTURE)))
t0 = time.time()
fx = findings(dl)
elapsed = time.time() - t0
fx_c = [f['code'] for f in fx]
counts = {k: fx_c.count(k) for k in sorted(set(fx_c))}

check(
    'the fixture reports the walk defect the operator saw',
    'walk_storey' in counts and counts['walk_storey'] >= 1,
    f'codes {counts}',
)
check(
    '...naming the shaft that the stair foot arrives inside',
    all('lift shaft' in f['text'] and 'nowhere to step off' in f['text'] for f in fx if f['code'] == 'walk_storey'),
    ' || '.join(f['text'] for f in fx if f['code'] == 'walk_storey')[:400],
)
check(
    'the fixture is capped and folded, not dumped',
    len(fx) <= W.MAX_FINDINGS + 1 and fx_c[-1] == 'walk_more',
    f'{len(fx)} findings, codes {counts}',
)
check(
    'storey 0 is a width warning, not an error',
    [f['code'] for f in fx if 'storey 0' in f['text']] == ['walk_narrow'],
    'The stair foot on storey 0 is not buried — a strip of its approach pokes '
    'out south of the shaft — but that strip is under 1.0 m, so the honest '
    'answer is WARN. detail: ' + ' || '.join(f['text'] for f in fx if 'storey 0' in f['text']),
)
check(
    'every finding names a record and a tool',
    all(' o' in f['text'] or f['text'].startswith('o') for f in fx if f['sev'] == 'error')
    and all('(' in f['text'] for f in fx if f['sev'] == 'error'),
    ' || '.join(f['text'] for f in fx if f['sev'] == 'error')[:300],
)


# ── (e) the cost ─────────────────────────────────────────────────────────────
check(
    f'the fixture checks in {elapsed:.3f} s',
    elapsed < 6.0,
    f'{elapsed:.3f} s over a 21-storey, 336-record drawing at 0.25 m (the brief asked for under 3 s; the gate is 6 s)',
)


# ── the raster itself ────────────────────────────────────────────────────────
g, env = list(E.envelopes(tower()).items())[0]
B = W._Building(tower(), E, g, env, 2.7)
gr = W._storey_grid(B, 1)
# rows 12 and 91 are the north and south walls themselves; 13..90 is the inside
bare = [iz for iz in range(13, 91) if not any(gr.free[iz * gr.nx + ix] for ix in range(13, 91))]
check(
    'the slab joints add_stair cuts are not holes in the floor',
    not bare,
    'add_stair cuts its plate into pieces that stop 0.05 m short of each other. '
    'Rasterised by cell centre those 0.1 m joints read as bare rows right across '
    'the storey and cut the building in two, so FLOOR is painted by touch and '
    'only SOLIDS are taken by centre. bare rows: ' + str(bare),
)

gr0 = W._Grid(0.0, 0.0, 5.0, 5.0)
gr0.paint((0.0, 0.0, 5.0, 5.0), 1, touch=True)
gr0.block((2.0, 0.0, 2.1, 5.0), 'thin')
sealed = all(not gr0.free[iz * gr0.nx + 8] for iz in range(gr0.nz))
check(
    'a partition thinner than a cell still stops you',
    sealed,
    'a 0.1 m wall falls between two cell centres about half the time; span_solid '
    'keeps one line of cells so it is 0.25 m thick, never 0',
)

gr1 = W._Grid(0.0, 0.0, 5.0, 5.0)
gr1.paint((0.0, 0.0, 5.0, 5.0), 1, touch=True)
gr1.block((0.0, 0.0, 2.0, 2.4), 'a')  # a 1.2 m slot between two blocks
gr1.block((0.0, 3.6, 2.0, 5.0), 'b')
gr1.erode()
check(
    'a 1.2 m gap is walked, not flagged',
    any(gr1.wide[iz * gr1.nx + 4] for iz in range(gr1.nz)),
    'erosion must not eat an honest corridor',
)

gr2 = W._Grid(0.0, 0.0, 5.0, 5.0)
gr2.paint((0.0, 0.0, 5.0, 5.0), 1, touch=True)
gr2.block((0.0, 0.0, 2.0, 2.45), 'a')  # a 0.9 m slot
gr2.block((0.0, 3.35, 2.0, 5.0), 'b')
gr2.erode()
check(
    'a 0.9 m gap is not "wide"',
    not any(gr2.wide[iz * gr2.nx + 4] for iz in range(gr2.nz)),
    'the WARN tier exists precisely for this',
)


# ── a wall turned off the grid blocks the wall, not its bbox ─────────────────
# A: the defect. A 5.0 x 0.18 m partition turned 17.5 deg has a 4.82 x 1.66 m
# bounding box — 8.0 m2 of blocked floor for 0.90 m2 of wall. The surveyed plan
# packs are full of such walls; eleven of them rastered one replayed storey into
# a solid mass and thirteen room doors read as unreachable.

ANG = math.radians(17.5)
CW, CD = 5.0, 0.18
bb_area = (CW * abs(math.cos(ANG)) + CD * abs(math.sin(ANG))) * (CW * abs(math.sin(ANG)) + CD * abs(math.cos(ANG)))
check(
    '(obb) the bbox of a wall turned 17.5 deg is 8x its own area',
    bb_area > 8 * CW * CD,
    f'{bb_area:.2f} m2 of bbox for {CW * CD:.2f} m2 of wall',
)

gr3 = W._Grid(0.0, 0.0, 10.0, 10.0)
gr3.paint((0.0, 0.0, 10.0, 10.0), 1, touch=True)
gr3.block(W._rot_rect(E, 5.0, 5.0, CW, CD, ANG), 'oblique')  # the old way
flat = sum(1 for v in gr3.free if not v) * W.CELL * W.CELL

gr4 = W._Grid(0.0, 0.0, 10.0, 10.0)
gr4.paint((0.0, 0.0, 10.0, 10.0), 1, touch=True)
gr4.block_obb(5.0, 5.0, CW, CD, ANG, 'oblique')  # the new way
turned = sum(1 for v in gr4.free if not v) * W.CELL * W.CELL
check(
    '(obb) block_obb blocks the wall, block blocks the bbox',
    turned < flat / 3.0,
    f'block_obb {turned:.2f} m2 vs block {flat:.2f} m2 for a {CW} x {CD} m wall',
)
check(
    '(obb) block_obb still covers the wall itself',
    turned >= CW * CD,
    f'{turned:.2f} m2 for a {CW * CD:.2f} m2 leaf — a cell is 0.25 m, so a 0.18 m leaf costs a whole one',
)
gr5 = W._Grid(0.0, 0.0, 5.0, 5.0)  # a wall long enough to cut the room
gr5.paint((0.0, 0.0, 5.0, 5.0), 1, touch=True)
gr5.block_obb(2.5, 2.5, 8.0, 0.18, ANG, 'oblique')
check(
    '(obb) a wall turned off the grid is still sealed — you cannot walk through it',
    not W._fill(gr5, [gr5.at(2.5, 0.2)], 'free')[gr5.at(2.5, 4.8)],
    'a 0.18 m leaf is thinner than a cell; block_obb walks it on half-cell steps '
    'so it is never a dotted line the fill leaks through',
)
check(
    '(obb) a wall SQUARE to the grid keeps the cheap slice-wise path',
    W._obb_of(E, {'kind': 'partition', 'x': 5.0, 'z': 5.0, 'ry': 0.0, 'p': {'len': 5.0, 't': 0.18, 'h': 2.4}}) is None,
    'its bbox IS the wall — walking its cells would buy nothing',
)
check(
    '(obb) a wall turned off the grid takes the oriented path',
    W._obb_of(E, {'kind': 'partition', 'x': 5.0, 'z': 5.0, 'ry': ANG, 'p': {'len': 5.0, 't': 0.18, 'h': 2.4}})
    is not None,
    f'ry = {ANG:.3f} rad is {math.degrees(ANG):.1f} deg off the grid, over the '
    f'{math.degrees(W.SQUARE_TOL):.1f} deg tolerance',
)

# B: the same wall in a drawing — the corridor beside it stays walkable
dob = tower()
gob, eob = list(E.envelopes(dob).items())[0]
sq = dob.new(
    'partition',
    {'len': 5.0, 't': 0.18, 'h': 2.4},
    (eob['xmin'] + eob['xmax']) / 2,
    (eob['zmin'] + eob['zmax']) / 2 - 1.0,
    2.7,
    0.0,
    'mat_plaster',
    'square party wall',
    gob,
)
ob = dob.new(
    'partition',
    {'len': 5.0, 't': 0.18, 'h': 2.4},
    (eob['xmin'] + eob['xmax']) / 2,
    (eob['zmin'] + eob['zmax']) / 2 + 1.0,
    2.7,
    ANG,
    'mat_plaster',
    'oblique party wall',
    gob,
)
Bob = W._Building(dob, E, gob, eob, 2.7)
check(
    '(obb-B) _Building keeps an oriented footprint for the oblique wall',
    ob['id'] in Bob.obb and abs(Bob.obb[ob['id']][4] - (ob.get('ry') or 0.0)) < 1e-9,
    f'{len(Bob.obb)} oriented of {len(Bob.solids)} solids; ry stored {ob.get("ry")} vs asked {ANG}',
)
check('(obb-B) ...and none for its square twin', sq['id'] not in Bob.obb, sorted(Bob.obb))


# ── the replay tower ─────────────────────────────────────────────────────────
REPLAY = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'test_tower_replay.py')
check(
    'the replay test is left untouched',
    os.path.exists(REPLAY),
    'test_tower_replay.py is run separately; see the report for its state — '
    'walk_rules adds walk_entrance_core to it, and that finding is TRUE '
    '(the replay Lobby has a door in its south partition only, so a person '
    'entering is shut in a 2 m deep box and reaches neither stair nor lift)',
)

finish()
