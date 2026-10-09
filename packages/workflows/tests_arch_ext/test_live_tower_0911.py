# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_live_tower_0911 — the three dishonest checks of job 94f5813b, on the
operator's own drawing.

The fixture is the real 20-storey tower the operator asked for on 2026-09-11
(336 records, luxury programme, a lift void cut through every storey). Three
findings on it were wrong, and the model spent 4 of its 28 draw calls obeying
one of them:

  1. `finish_deck_guard` said 'the roof deck of "tower" carries 2 sun loungers
     but its WEST edge has no guarding >= 1.1 m — add_parapet("tower", ...)'.
     The west edge in question is the VOID edge of the roof piece east of the
     lift, the lift shaft stands in it 1.5 m proud of the deck, and a parapet
     around the tower already exists. The shaft now guards on all four faces
     (analyse_geometry.guard_segments) and the message, when it does fire,
     names the roof PIECE, the edge midpoint in metres AND its cell, and asks
     for the shaft overrun rather than a parapet.
  2. eight identical `unsupported` warnings about the one u-stair, which
     stands in its own slab void (object_specs._in_core_void).
  3. finish_rules.GLASS_KINDS must stay a superset of
     building_program.GLASS_OK_KINDS — the two lists diverging is what turned
     a glass canopy into concrete.

No new kinds, so no browser/Blender pass: every check here is a relation over
records that already exist on disk.
"""

import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
DR = A.EXT_MODULES['design_rules']
FR = A.EXT_MODULES['finish_rules']
BP = A.EXT_MODULES['building_program']
G = A.EXT_MODULES['analyse_geometry']
OS_ = A.EXT_MODULES['object_specs']

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')
RAW = json.load(open(FIX))


def drawing(raw=None):
    return A.Drawing(copy.deepcopy(raw if raw is not None else RAW))


def codes(findings, code):
    return [f for f in findings if f.get('code') == code]


# ── the fixture is the live drawing, unchanged ──────────────────────────────
d = drawing()
check('the fixture is job 94f5813b: 336 records', len(d.objs) == 336, len(d.objs))
check(
    'it carries the void registry and the luxury programme',
    len(d.ext.get('slab_voids') or []) == 20 and (d.ext.get('building_program') or {}).get('finish_level') == 'luxury',
    (len(d.ext.get('slab_voids') or []), d.ext.get('building_program')),
)

found = DR.run_checks(d)
check('design_check runs on it and returns findings', isinstance(found, list) and found, len(found))

# ── 1. the shaft guards the void edge it stands in ──────────────────────────
guard = codes(found, 'finish_deck_guard')
check(
    'no finish_deck_guard: the lift shaft guards the roof void edges', not guard, ' | '.join(f['text'] for f in guard)
)
check(
    'elevator_shaft is a guard kind, and a box one',
    G.is_guard_kind({'kind': 'elevator_shaft', 'p': {'w': 1.8, 'd': 2.0}})
    and G.is_guard_box({'kind': 'elevator_shaft', 'p': {'w': 1.8, 'd': 2.0}}),
)
check(
    'a wall is a guard but NOT a box — one segment, as always',
    G.is_guard_kind({'kind': 'wall', 'p': {'len': 4.0, 't': 0.24}})
    and not G.is_guard_box({'kind': 'wall', 'p': {'len': 4.0, 't': 0.24}}),
)
shaft = next(o for o in d.objs if o['id'] == 'o416')
segs = G.guard_segments(shaft)
check('the shaft offers four faces', len(segs) == 4, [(s[0], s[1]) for s in segs])
check(
    'one of them is the east face at x 16.40 over the full 2.0 m depth',
    any(
        abs(p0[0] - 16.4) < 1e-6 and abs(p1[0] - 16.4) < 1e-6 and abs(abs(p1[1] - p0[1]) - 2.0) < 1e-6
        for p0, p1, _t in segs
    ),
    [(p0, p1) for p0, p1, _t in segs],
)
check(
    'a wall still gives exactly one segment along its length',
    len(G.guard_segments(next(o for o in d.objs if o['id'] == 'o331'))) == 1,
)

# ── 2. the stair stands in its own void, not on nothing ─────────────────────
unsup = codes(found, 'unsupported')
check(
    'no unsupported warning names a stair',
    not [f for f in unsup if 'stair' in f['text']],
    ' | '.join(f['text'] for f in unsup),
)
stair = next(o for o in d.objs if o['id'] == 'o229')
check('o229 u stair st1-2 is read as standing in the cut slab of its own void', OS_._in_core_void(d, stair))
check(
    'a lounger on the open deck is NOT excused by the void rule',
    not OS_._in_core_void(d, next(o for o in d.objs if o['id'] == 'o572')),
)

# ── 2b. 2026-09-12: the 09-11 defects are NAMED on the operator's own drawing ─
# The fixture is the drawing as it was built: stair FH96 with the lifts at FF96/FJ96
# 0.62 m inside it, a lift in the 1.2 m of floor at the stair's foot, and a partition
# doubling a glazed facade. The tools refuse those calls now; on a drawing that already
# carries them, design_check must say so rather than stay silent.
clash = codes(found, 'circ_core_clash')
# 2026-09-16: ONE line per clashing PAIR of cores, not one per stair record. The
# 20 records of main_stair against a shaft are one defect and the operator gets
# one line for it, naming the storey range and the WORST overlap (0.62 m, the
# 0.62 the lifts really stand inside the stair — the old per-record lines quoted
# the 0.48 of whichever record happened to be capped first).
check(
    'the clashing cores are caught: 2 circ_core_clash errors (one per lift shaft)',
    len(clash) == 2,
    [f['text'][:80] for f in clash[:2]] or len(clash),
)
check(
    'every one is an error and names both records and the overlap in metres',
    all(f['sev'] == 'error' and '0.62 x 2.00 m' in f['text'] for f in clash),
    [(f['sev'], f['text'][:120]) for f in clash[:2]],
)
check(
    'each line folds the 20 stair records and names the storey range',
    all('(20 stair records)' in f['text'] and 'storeys 0..19' in f['text'] for f in clash),
    [f['text'][:140] for f in clash],
)
check(
    'the pair named is the u stair and the two lift shafts o334 / o416',
    {'o334', 'o416'} <= {w for f in clash for w in f['text'].split()},
    sorted({w for f in clash for w in f['text'].split() if w.startswith('o')}),
)
approach = codes(found, 'circ_stair_approach')
check(
    'the lift standing on the stair foot is caught: 1 circ_stair_approach error',
    len(approach) == 1 and approach[0]['sev'] == 'error',
    [(f['sev'], f['text'][:120]) for f in approach],
)
check(
    'and it says there is nothing to step onto',
    'nothing to step onto' in approach[0]['text'] if approach else False,
    approach[0]['text'][:200] if approach else None,
)
facade = codes(found, 'env_facade_partition')
check(
    'the partition doubling the glazed facade is caught: 1 env_facade_partition error',
    len(facade) == 1 and facade[0]['sev'] == 'error',
    [(f['sev'], f['text'][:140]) for f in facade],
)
check(
    "it is o528 on the east facade, and it says the facade is the room's wall",
    'o528' in facade[0]['text'] and 'the facade is the room' in facade[0]['text'],
    facade[0]['text'][:220] if facade else None,
)
check(
    'the three 09-12 rules add 4 errors to this drawing and nothing else is downgraded',
    len(clash) + len(approach) + len(facade) == 4 and all(f['sev'] == 'error' for f in clash + approach + facade),
    sorted((f['code'], f['sev']) for f in found),
)

# ── 2c. 2026-09-16: the clash gate on the same drawing ──────────────────────
CLASH = A.EXT_MODULES['clash_rules']
solid = CLASH.check_clashes(d)
check(
    'the clash gate finds 3 records standing inside another solid',
    len(solid) == 3 and all(f['code'] == 'clash_core_wall' for f in solid),
    [f['text'][:110] for f in solid],
)
check(
    'two are the head-house walls built inside the lift overruns (o330, o331)',
    sum(1 for f in solid if 'head house' in f['text']) == 2,
    [f['text'][:110] for f in solid],
)
check(
    'the third is the ground corridor partition poking into the stair well',
    any('o228' in f['text'] and 'o535' in f['text'] for f in solid),
    [f['text'][:140] for f in solid],
)


# ── 3. the two glass lists may never diverge again ──────────────────────────
check(
    'finish_rules.GLASS_KINDS >= building_program.GLASS_OK_KINDS',
    FR.GLASS_KINDS >= frozenset(BP.GLASS_OK_KINDS),
    sorted(frozenset(BP.GLASS_OK_KINDS) - FR.GLASS_KINDS),
)

# ── the negative case: take the shafts away and the error must come back ────
bare = copy.deepcopy(RAW)
gone = [o['id'] for o in bare['objects'] if o['kind'] == 'elevator_shaft']
bare['objects'] = [o for o in bare['objects'] if o['kind'] != 'elevator_shaft']
check(
    'the negative drawing lost both lift shafts',
    len(gone) == 2 and len(bare['objects']) == 334,
    (gone, len(bare['objects'])),
)

dn = A.Drawing(bare)
gn = codes(DR.run_checks(dn), 'finish_deck_guard')
check('with no shaft the guard error RETURNS', len(gn) >= 1, len(gn))
txt = ' | '.join(f['text'] for f in gn)
check('it names the roof PIECE, not the group', 'flat roof (E of lift void)' in txt, txt)
check(
    'it names the opening, not a parapet to add', ('lift' in txt or 'opening' in txt) and 'add_parapet' not in txt, txt
)
check('it names the edge midpoint in metres and its cell', 'x 16.45' in txt and 'cell FK96' in txt, txt)
check('it quotes the covered percentage and the drop', '0% of its length' in txt and '2.78 m drop' in txt, txt)

# and an edge that is NOT a void edge still gets the parapet advice
noguard = copy.deepcopy(RAW)
noguard['objects'] = [
    o for o in noguard['objects'] if not (o['kind'] == 'wall' and str(o.get('name') or '') == 'parapet')
]
dp = A.Drawing(noguard)
gp = codes(DR.run_checks(dp), 'finish_deck_guard')
ptxt = ' | '.join(f['text'] for f in gp)
check('an outside deck edge with the parapets gone still says add_parapet', gp and 'add_parapet' in ptxt, ptxt[:300])

finish()
