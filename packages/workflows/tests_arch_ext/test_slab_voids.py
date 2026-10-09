# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_slab_voids — the floor-opening family.

Proves the two halves of the contract tasks 8/9 (stairs, lifts) lean on:
  · cut_slab_void() replaces ONE slab with the pieces around a void, keeps the
    slab's y / t / material / group, merges an overlapping second cut, drops a
    piece the void has eaten, works on a flat roof, and refuses a storey that
    has no floor — naming the storeys that do.
  · check_voids() finds a stair that crosses floors with no opening, caps the
    findings at 8 + a count, and goes silent once every crossing is cut.

No GPU, no model, no browser: the assistant alone.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
SV = A.EXT_MODULES.get('slab_voids')  # the module the assistant really runs, not a second import
H = 2.7


def tower(storeys=3, roof='flat'):
    d = A.Drawing(None)
    txt = A.call_tool(
        d, 'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': storeys, 'roof': roof, 'name': 'tower'}
    )
    return d, txt


def slabs(d, storey=None):
    out = [o for o in d.objs if o['kind'] in SV.SLAB_KINDS and o['grp'] == 'tower']
    if storey is not None:
        out = [o for o in out if SV._storey_of_rec(d, o, H) == storey]
    return out


def area(d, storey):
    return sum(o['p']['w'] * o['p']['d'] for o in slabs(d, storey))


# ── the family is loaded and wired ───────────────────────────────────────────
check(
    'family loaded',
    SV is not None
    and SV.__file__.endswith('arch_assistant_ext/slab_voids.py')
    and SV.KINDS == {}
    and SV.OPENINGS == [],
    SV,
)
check(
    'tools registered', 'cut_floor_opening' in tool_names() and 'list_floor_openings' in tool_names(), tool_names()[:5]
)
check('PROMPT is one paragraph <= 500 chars', 0 < len(SV.PROMPT) <= 500 and '\n' not in SV.PROMPT, len(SV.PROMPT))
check(
    '2 examples, design check registered',
    len(SV.EXAMPLES) >= 2 and SV.check_voids in SV.DESIGN_CHECKS,
    (len(SV.EXAMPLES), SV.DESIGN_CHECKS),
)

# ── one void in the middle of a floor ────────────────────────────────────────
d, made = tower()
orig = slabs(d, 1)[0]
oid, oy, omat, ot = orig['id'], orig['y'], orig['mat'], orig['p']['t']
ids, note = SV.cut_slab_void(d, 'tower', 1, 11.5, -52.3, 14.5, -49.7, 'stair')
pieces = slabs(d, 1)
check('the storey 1 slab is gone', d.find(oid) is None, note)
check('4 pieces, all returned', len(ids) == 4 and len(pieces) == 4 and {p['id'] for p in pieces} == set(ids), note)
check(
    'pieces keep y / t / mat / grp / kind',
    all(
        abs(p['y'] - oy) < 1e-9
        and abs(p['p']['t'] - ot) < 1e-9
        and p['mat'] == omat
        and p['grp'] == 'tower'
        and p['kind'] == 'slab'
        for p in pieces
    ),
    [(p['id'], p['y'], p['p']['t'], p['mat'], p['kind']) for p in pieces],
)
check('area == 20*20 - 3.0*2.6', abs(area(d, 1) - (400 - 3.0 * 2.6)) < 0.01, area(d, 1))
check(
    'names say which side of the void',
    sorted(p['name'].split('(')[-1][0] for p in pieces) == ['E', 'N', 'S', 'W'],
    [p['name'] for p in pieces],
)
reg = d.ext['slab_voids']
check(
    'registry: 1 entry, 4 ids, the original recorded',
    len(reg) == 1
    and reg[0]['ids'] == ids
    and reg[0]['orig']['id'] == oid
    and reg[0]['group'] == 'tower'
    and reg[0]['storey'] == 1
    and reg[0]['reason'] == 'stair',
    reg,
)
check('voids_at finds it', len(SV.voids_at(d, 'tower', 1)) == 1 and SV.voids_at(d, 'tower', 5) == [])

# ── an overlapping second cut merges into the union ──────────────────────────
ids2, note2 = SV.cut_slab_void(d, 'tower', 1, 13.0, -51.0, 16.0, -48.0, 'lift')
reg = d.ext['slab_voids']
uni_area = (16.0 - 11.5) * (-48.0 - -52.3)
check(
    'still one entry — the union',
    len(reg) == 1 and [reg[0]['xmin'], reg[0]['zmin'], reg[0]['xmax'], reg[0]['zmax']] == [11.5, -52.3, 16.0, -48.0],
    reg,
)
check('union: 4 pieces again', len(ids2) == 4 and len(slabs(d, 1)) == 4, note2)
check('union area removed', abs(area(d, 1) - (400 - uni_area)) < 0.01, (area(d, 1), 400 - uni_area))
check("the first cut's pieces are gone", all(d.find(i) is None for i in ids), ids)

# ── a second void that does NOT overlap stays a second opening ───────────────
n, _ = tower()
SV.cut_slab_void(n, 'tower', 1, 5.0, -55.0, 8.0, -52.0, 'stair')
idsn, noten = SV.cut_slab_void(n, 'tower', 1, 17.0, -47.0, 20.0, -44.0, 'lift')
regn = n.ext['slab_voids']
check(
    'two openings on one floor, rebuilt from the original around both',
    len(regn) == 2 and len(idsn) == 7 and len(slabs(n, 1)) == 7 and regn[0]['ids'] == idsn and regn[1]['ids'] == idsn,
    (len(regn), noten),
)
check('both voids removed from the original area', abs(area(n, 1) - (400 - 9.0 - 9.0)) < 0.01, area(n, 1))

# ── a void that reaches the west edge loses that piece ───────────────────────
ids3, note3 = SV.cut_slab_void(d, 'tower', 2, 3.0, -52.0, 7.0, -50.0, 'stair')
check('3 pieces when the void eats the west edge', len(ids3) == 3 and len(slabs(d, 2)) == 3, note3)
check('west-edge area', abs(area(d, 2) - (400 - 4.0 * 2.0)) < 0.01, area(d, 2))

# ── the flat roof is a floor too ─────────────────────────────────────────────
ids4, note4 = SV.cut_slab_void(d, 'tower', 3, 11.5, -52.3, 14.5, -49.7, 'stair')
roofs = slabs(d, 3)
check(
    'roof_flat pieces, 0.3 m thick',
    len(ids4) == 4 and all(r['kind'] == 'roof_flat' and abs(r['p']['t'] - 0.3) < 1e-9 for r in roofs),
    note4,
)

# ── a storey with no floor is refused, and says which storeys exist ──────────
ids5, note5 = SV.cut_slab_void(d, 'tower', 7, 11.5, -52.3, 14.5, -49.7, 'stair')
check(
    'storey 7 refused, naming 0..3',
    ids5 == [] and note5.startswith('refused:') and 'storeys 0, 1, 2, 3' in note5,
    note5,
)
ids6, note6 = SV.cut_slab_void(d, 'nosuchgroup', 0, 11.5, -52.3, 14.5, -49.7)
check('an unknown group is refused', ids6 == [] and note6.startswith('refused:'), note6)

# ── check_voids: the 285-step stair of job 71ac02b0 ──────────────────────────
t, _ = tower(storeys=20)
stair = t.new(
    'stair_u',
    {'steps': 285, 'rise': 0.18, 'run': 0.28, 'w': 1.2, 'gap': 0.2},
    13.0,
    -51.0,
    0.0,
    0.0,
    'mat_concrete',
    name='u stair st0-19',
    grp='tower',
)
bb = SV.footprint_of(stair)
crossings = [o for o in slabs(t) if 0.05 < o['y'] < 285 * 0.18 - 0.05]
f = SV.check_voids(t)
check(
    'the stair spans 51.3 m and crosses 18 floors',
    abs(SV._span(stair)[1] - 51.3) < 1e-6 and len(crossings) == 18,
    (SV._span(stair), len(crossings)),
)
check(
    'check_voids caps at 8 findings + one count line',
    len(f) == 9 and f[0]['sev'] == 'error',
    [x['text'] for x in f[:1]],
)
check(
    'the finding names the record, the slab, the storey and the fix',
    stair['id'] in f[0]['text']
    and 'u stair passes through slab' in f[0]['text']
    and 'no floor opening' in f[0]['text']
    and 'cut_floor_opening("tower"' in f[0]['text'],
    f[0]['text'],
)
check(
    'the count line says how many were suppressed',
    f[-1]['code'] == 'void_missing_more' and '18 in total' in f[-1]['text'] and '10 more' in f[-1]['text'],
    f[-1]['text'],
)
check(
    'design_check surfaces it',
    'no floor opening' in A.call_tool(t, 'design_check', {}),
    A.call_tool(t, 'design_check', {})[:200],
)

for s in range(1, 20):
    got, msg = SV.cut_slab_void(t, 'tower', s, bb[0], bb[1], bb[2], bb[3], 'stair')
    if not got:
        check(f'cut storey {s}', False, msg)
check('every crossing cut -> check_voids is silent', SV.check_voids(t) == [], SV.check_voids(t))

# ── the model's tools ────────────────────────────────────────────────────────
m, _ = tower()
cf, ct = A.block_around('FH100', 4, 4)
out = A.call_tool(
    m, 'cut_floor_opening', {'group': 'tower', 'storey': 1, 'cell_from': cf, 'cell_to': ct, 'reason': 'atrium'}
)
check(
    'cut_floor_opening cut a 4 x 4 m atrium',
    'atrium void' in out and 'm2 of floor removed' in out and len(slabs(m, 1)) == 4,
    out,
)
check('16 m2 removed', abs(area(m, 1) - (400 - 16.0)) < 0.01, area(m, 1))
listed = A.call_tool(m, 'list_floor_openings', {'group': 'tower'})
check(
    'list_floor_openings lists it',
    '1 floor opening' in listed and 'tower storey 1' in listed and 'atrium' in listed,
    listed,
)
check(
    'list_floor_openings on an empty drawing says so',
    A.call_tool(A.Drawing(None), 'list_floor_openings', {}).startswith('no floor openings'),
)
check(
    'a bad cell is refused, not raised',
    A.call_tool(m, 'cut_floor_opening', {'group': 'tower', 'storey': 1, 'cell_from': 'zz', 'cell_to': ct}).startswith(
        'refused:'
    ),
)

finish()
