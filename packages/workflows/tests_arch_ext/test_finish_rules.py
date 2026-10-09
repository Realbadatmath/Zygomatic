# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_finish_rules — luxury means library materials, and an occupied deck is
guarded at 1.1 m.

No new kinds, so no browser/Blender pass: this family is pure relation over the
records the other families make. The proof is a real 20-storey draw_box, a real
add_stair, a real add_pool and a real add_parapet — the four calls of job
71ac02b0 that between them produced 285 concrete steps beside an unguarded
infinity pool while design_check said "0 errors".
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

A.load_extensions()
F = A.EXT_MODULES['finish_rules']
DR = A.EXT_MODULES['design_rules']
LIB_FLOOR = A.FINISHES['luxury']['floor']  # acg_Marble006


def tower(storeys=20, level='luxury'):
    d = A.Drawing(None)
    if level:
        d.ext['building_program'] = {'finish_level': level}
    A.call_tool(
        d,
        'draw_box',
        dict(
            centre='FH100',
            width=20,
            depth=20,
            storeys=storeys,
            roof='flat',
            name='tower',
            material='pht_rough_concrete',
        ),
    )
    return d


def texts(fn, d):
    return ' | '.join(f['text'] for f in fn(d))


def arriving_presets(d, kind, n, mat='mat_concrete', p=None, grp='tower'):
    """Write n records that ARRIVE on the drawing carrying a flat preset.

    Since 2026-09-16 a luxury job is born finished: Drawing.new asks
    finish_schedule.default_mat for every record, so no tool can leave a
    mat_concrete stair on a luxury drawing any more. A preset can still ARRIVE
    — an older drawing reopened, a hand edit in the tab — and catching it is
    exactly what check_luxury_finishes is for. So the programme is lifted for
    the write and put back straight after, which is the order those drawings
    were really made in. (Only for kinds the STANDARD schedule has no opinion
    about, or the hook would fill them too.)
    """
    prog = (d.ext or {}).pop('building_program', None)
    try:
        for i in range(n):
            d.new(kind, dict(p or {}), 0.0, 0.0, i * d.storey_h, 0.0, mat, name=f'{kind} st{i}', grp=grp)
    finally:
        if prog is not None:
            d.ext['building_program'] = prog
    return [o for o in d.objs if o['kind'] == kind]


# ── the library / preset split every check rests on ─────────────────────────
check('is_preset(mat_concrete) — a flat preset', F.is_preset('mat_concrete'))
check('is_preset(acg_Marble006) is False — the library holds it', not F.is_preset(LIB_FLOOR))
check('is_preset("nope") is False — it is not a material at all', not F.is_preset('nope'))
check('is_library(pht_rough_concrete)', F.is_library('pht_rough_concrete'))

# ── (1) the run that started this: 20 storeys of concrete stair on a luxury job
d = tower()
st = A.call_tool(d, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u', material='mat_concrete'))
check('add_stair drew one record per storey', '20 record(s)' in st, st[:120])
check(
    'draw_box already put the library floor on the slabs at luxury',
    sum(1 for o in d.objs if o['kind'] == 'slab' and o['mat'] == LIB_FLOOR) > 10,
    {o['mat'] for o in d.objs if o['kind'] == 'slab'},
)
# 2026-09-16: that same call can no longer PRODUCE the defect — finishes arrive
# by construction, so a stair asked for in mat_concrete is born in the library
# stone and the check is rightly silent.
check(
    'the stairs the tools drew today are library stone, not mat_concrete',
    all(not F.is_preset(o['mat']) for o in d.objs if o['kind'] == 'stair_u') and F.check_luxury_finishes(d) == [],
    sorted({o['mat'] for o in d.objs if o['kind'] == 'stair_u'}),
)

# the defect as it still ARRIVES: an older drawing / a hand edit in the tab
d1 = tower()
stairs1 = arriving_presets(d1, 'stair_u', 20, p={'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2})
check(
    'the 20 arriving stair records really carry mat_concrete',
    len(stairs1) == 20 and all(o['mat'] == 'mat_concrete' for o in stairs1),
    sorted({o['mat'] for o in stairs1}),
)
f1 = F.check_luxury_finishes(d1)
t1 = texts(F.check_luxury_finishes, d1)
check('a luxury job with preset stairs is ONE error', len(f1) == 1 and f1[0]['sev'] == 'error', f1)
check('the error is grouped by kind and names stair_u x20 (mat_concrete)', 'stair_u x20 (mat_concrete)' in t1, t1)
check(
    'the error counts the records and names both repaint tools',
    t1.startswith('20 records use flat presets on a luxury job:')
    and 'set_finish(' in t1
    and 'set_material(ids' in t1
    and 'search_materials("marble")' in t1,
    t1,
)
check(
    'apply_finishes repaints the arrived presets and silences the error',
    'records finished' in A.call_tool(d1, 'apply_finishes', {}) and F.check_luxury_finishes(d1) == [],
    texts(F.check_luxury_finishes, d1)[:200],
)

# the same drawing at 'standard' — the presets are the right answer there
d_std = tower(level='standard')
A.call_tool(d_std, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=20, kind='u', material='mat_concrete'))
check(
    'level standard raises no preset error', F.check_luxury_finishes(d_std) == [], texts(F.check_luxury_finishes, d_std)
)
check('no programme at all raises no preset error', F.check_luxury_finishes(tower(storeys=3, level=None)) == [])

# repainting the arrived stairs with a library id silences it
d_sm = tower()
arriving_presets(d_sm, 'stair_u', 20, p={'steps': 15, 'rise': 0.18, 'run': 0.28, 'w': 1.2})
check(
    'the arrived drawing errors before the repaint',
    len(F.check_luxury_finishes(d_sm)) == 1,
    texts(F.check_luxury_finishes, d_sm)[:160],
)
A.call_tool(
    d_sm, 'set_material', dict(which=[o['id'] for o in d_sm.objs if o['kind'] == 'stair_u'], material=LIB_FLOOR)
)
check(
    'set_material to a library id silences the preset error',
    F.check_luxury_finishes(d_sm) == [],
    texts(F.check_luxury_finishes, d_sm),
)

# set_finish is the other half of the hint: it repaints the three surfaces
d_sf = tower(storeys=3)
A.call_tool(d_sf, 'set_material', dict(which='all', material='mat_concrete'))
check(
    'painting the whole tower concrete brings the error back',
    len(F.check_luxury_finishes(d_sf)) == 1,
    texts(F.check_luxury_finishes, d_sf),
)
sf = A.call_tool(
    d_sf, 'set_finish', dict(group='tower', floor_material=LIB_FLOOR, roof_material=LIB_FLOOR, wall_material=LIB_FLOOR)
)
check('set_finish repainted the three surfaces', 'set on "tower"' in sf, sf[:120])
check(
    'set_finish to library ids silences the preset error',
    F.check_luxury_finishes(d_sf) == [],
    texts(F.check_luxury_finishes, d_sf),
)

# mat_glass is glass — exempt on the kinds that are made of it
d_g = tower(storeys=3)
A.call_tool(
    d_g, 'set_finish', dict(group='tower', floor_material=LIB_FLOOR, roof_material=LIB_FLOOR, wall_material=LIB_FLOOR)
)
d_g.new('curtain_wall', {'len': 6, 'h': 2.7, 't': 0.06}, 0.0, 0.0, 0.0, 0.0, 'mat_glass', name='glazing', grp='tower')
check(
    'mat_glass on a curtain wall is not a finish error',
    F.check_luxury_finishes(d_g) == [],
    texts(F.check_luxury_finishes, d_g),
)

# ── (2) a material id that is in neither list ───────────────────────────────
d2 = tower(storeys=3)
d2.new('wall', {'len': 4, 'h': 2.7, 't': 0.24}, 0.0, 0.0, 0.0, 0.0, 'nope', name='odd wall', grp='tower')
f2 = F.check_unknown_materials(d2)
check('a record with mat "nope" is an error', len(f2) == 1 and f2[0]['sev'] == 'error', f2)
check(
    'the unknown-material error names the id and the record',
    '"nope"' in f2[0]['text'] and 'search_materials(' in f2[0]['text'],
    f2[0]['text'],
)
check('a drawing with only real materials is silent', F.check_unknown_materials(tower(storeys=3)) == [])

# ── (3) an occupied roof deck must be guarded at 1.1 m ──────────────────────
d3 = tower(storeys=3)
pool = A.call_tool(d3, 'add_pool', dict(cell_from='FB97', cell_to='FF101', storey=3, depth=1.4))
check('add_pool put the pool on the roof deck', 'pool o' in pool, pool[:100])
roof = [o for o in d3.objs if o['kind'] == 'roof_flat'][0]
check(
    'deck_occupants sees the pool on that roof',
    [o['kind'] for o in F.deck_occupants(d3, roof)] == ['pool'],
    [(o['id'], o['kind']) for o in F.deck_occupants(d3, roof)],
)
f3 = F.check_deck_guarding(d3)
t3 = texts(F.check_deck_guarding, d3)
check('an unguarded occupied deck is an error', f3 and all(x['sev'] == 'error' for x in f3), f3)
check(
    'the finding names the group, what it carries, an edge and the fix',
    '"tower"' in t3
    and 'carries a pool' in t3
    and 'north edge' in t3
    and '>= 1.1 m' in t3
    and 'add_parapet("tower", height=1.1)' in t3,
    t3,
)
check('all four open edges are reported', len(f3) == 4, len(f3))

par = A.call_tool(d3, 'add_parapet', dict(group='tower', height=1.1))
check('add_parapet stood 1.1 m walls on the deck', '1.1 m high' in par, par[:120])
check('a 1.1 m parapet silences the guarding error', F.check_deck_guarding(d3) == [], texts(F.check_deck_guarding, d3))

# 1.0 m passes analyse_geometry's default but not an occupied deck
d3b = tower(storeys=3)
A.call_tool(d3b, 'add_pool', dict(cell_from='FB97', cell_to='FF101', storey=3, depth=1.4))
A.call_tool(d3b, 'add_parapet', dict(group='tower', height=1.0))
G = A.EXT_MODULES['analyse_geometry']
check('a 1.0 m parapet passes the generic guarding rule', G.run_guard(d3b)['ok'], G.run_guard(d3b)['issues'][:1])
check('but an OCCUPIED deck still fails at 1.1 m', F.check_deck_guarding(d3b) != [], texts(F.check_deck_guarding, d3b))

# an EMPTY deck carries nothing, so the 1.1 m rule does not apply to it
check(
    'a bare roof deck raises no guarding error',
    F.check_deck_guarding(tower(storeys=3)) == [],
    texts(F.check_deck_guarding, tower(storeys=3)),
)
# ...and the stair's head house is a lid, not an occupation
d3c = tower(storeys=3)
A.call_tool(d3c, 'add_stair', dict(cell='FH96', from_storey=0, to_storey=3, kind='u'))
check(
    'a head house on the deck is not an occupation', F.check_deck_guarding(d3c) == [], texts(F.check_deck_guarding, d3c)
)

# ── (4) a bare luxury deck, only when no real programme exists ──────────────
f4 = F.check_deck_furniture(tower(storeys=3))
check('a bare luxury deck with no programme is a WARN', len(f4) == 1 and f4[0]['sev'] == 'warn', f4)
check(
    'the warn names the deck height and add_beach_set',
    '8.4 m roof deck' in f4[0]['text'] and 'add_beach_set(' in f4[0]['text'],
    f4[0]['text'],
)
d4 = tower(storeys=3)
d4.ext['building_program'] = {'finish_level': 'luxury', 'items': [{'key': 'deck_furniture'}]}
check(
    'a REAL programme owns the case — no duplicate warning',
    F.check_deck_furniture(d4) == [],
    texts(F.check_deck_furniture, d4),
)
check('a standard deck is not warned about', F.check_deck_furniture(tower(storeys=3, level='standard')) == [])
d4b = tower(storeys=3)
r4 = [o for o in d4b.objs if o['kind'] == 'roof_flat'][0]
top = A.EXT_MODULES['analyse_geometry'].deck_top(r4)
for i in range(4):
    d4b.new(
        'sun_lounger',
        {'w': 0.7, 'l': 2.0, 'h': 0.4},
        r4['x'] + i,
        r4['z'],
        top,
        0.0,
        LIB_FLOOR,
        name=f'lounger {i}',
        grp='tower',
    )
check(
    'four loungers on the deck silence the warning',
    F.check_deck_furniture(d4b) == [],
    texts(F.check_deck_furniture, d4b),
)

# ── (5) a canopy whose plate and columns come from different worlds ─────────
d5 = tower(storeys=2, level=None)
can = A.call_tool(
    d5,
    'add_canopy',
    dict(
        group='tower',
        side='south',
        width=10,
        depth=4,
        height=4,
        columns=4,
        material=LIB_FLOOR,
        column_material='mat_concrete',
    ),
)
check('add_canopy drew the plate and four columns', 'carried by 4 round columns' in can, can[:160])
f5 = F.check_canopy_materials(d5)
check('a library fascia on preset columns is an INFO', len(f5) == 1 and f5[0]['sev'] == 'info', f5)
check(
    'the info names the canopy, both materials and the two arguments',
    LIB_FLOOR in f5[0]['text'] and 'mat_concrete' in f5[0]['text'] and 'column_material=' in f5[0]['text'],
    f5[0]['text'],
)
d5b = tower(storeys=2, level=None)
A.call_tool(
    d5b,
    'add_canopy',
    dict(
        group='tower',
        side='south',
        width=10,
        depth=4,
        height=4,
        columns=4,
        material=LIB_FLOOR,
        column_material=LIB_FLOOR,
    ),
)
check('one world on both is silent', F.check_canopy_materials(d5b) == [], texts(F.check_canopy_materials, d5b))

# ── the family contract ────────────────────────────────────────────────────
check('an empty drawing produces no findings at all', [f for fn in F.DESIGN_CHECKS for f in fn(A.Drawing(None))] == [])
check(
    'DESIGN_CHECKS exports all five checks',
    len(F.DESIGN_CHECKS) == 5
    and F.check_luxury_finishes in F.DESIGN_CHECKS
    and F.check_deck_guarding in F.DESIGN_CHECKS,
)
check(
    'design_rules collects them',
    F.check_luxury_finishes in DR.contributed() and F.check_deck_guarding in DR.contributed(),
)
codes = {f['code'] for f in DR.run_checks(d3b)}
check('run_checks reports the deck-guarding error', 'finish_deck_guard' in codes, codes)
check('PROMPT is one paragraph under 400 chars', 0 < len(F.PROMPT) <= 400 and '\n' not in F.PROMPT, len(F.PROMPT))
check(
    'the PROMPT says what luxury means and that design_check names the presets',
    'luxury' in F.PROMPT and 'design_check' in F.PROMPT and 'preset' in F.PROMPT,
)
check('two worked examples', len(F.EXAMPLES) >= 2 and all(x.get('ask') and x.get('calls') for x in F.EXAMPLES))
check('the family owns no kinds and no tools', F.KINDS == {} and F.OPENINGS == [] and F.TOOLS == [])

finish()
