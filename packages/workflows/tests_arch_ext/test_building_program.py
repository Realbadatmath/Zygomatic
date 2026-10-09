# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_building_program — the checklist: it resolves deterministically in one
call, it is stored on the drawing, its evidence matches what the drawing tools
actually make, and done refuses while a required item is missing."""

import inspect
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

BP = A.EXT_MODULES['building_program']
DR = A.EXT_MODULES['design_rules']

check('both tools are registered', {'plan_building', 'program_status'} <= set(tool_names()))

# ── the operator's own rules ─────────────────────────────────────────────────
p3 = BP.resolve('office', 3, 'K20', 'X34')
p2 = BP.resolve('office', 2, 'K20', 'X34')
need = {i['key']: i['need'] for i in p3['items']}
check('3 storeys REQUIRES a lift', need.get('elevator') == 'required', need.get('elevator'))
check('2 storeys does not', {i['key']: i['need'] for i in p2['items']}.get('elevator') == 'recommended')
check('every building requires an entrance', need.get('entrance') == 'required')
check(
    'an entrance TYPE is always chosen',
    [i for i in p3['items'] if i['key'] == 'entrance'][0]['pick']
    in ('porte_cochere', 'recessed', 'glazed_lobby', 'shopfront'),
)
check(
    'a house of 1 storey needs no stair and no lift',
    {i['key'] for i in BP.resolve('house', 1, 'K20', 'N24')['items']}.isdisjoint({'stair', 'elevator'}),
)

# deterministic
check(
    'the same request resolves identically twice',
    BP.resolve('office', 20, 'EW140', 'FQ160') == BP.resolve('office', 20, 'EW140', 'FQ160'),
)

# the lift count follows the occupancy, not a constant
n_small = [i for i in BP.resolve('office', 4, 'K20', 'N24')['items'] if i['key'] == 'elevator'][0]['n']
n_big = [i for i in BP.resolve('office', 20, 'EW140', 'FQ160')['items'] if i['key'] == 'elevator'][0]['n']
check('lift count grows with the building', n_big > n_small, f'{n_small} -> {n_big}')

# ── one call, no interview ───────────────────────────────────────────────────
txt, d = assistant(
    'plan_building', {'use': 'office', 'storeys': 20, 'cell_from': 'EW140', 'cell_to': 'FQ160', 'glass': True}
)
check('the whole checklist comes back in ONE call', 'REQUIRED' in txt and 'DECIDE' in txt)
check('the defaults are already chosen', 'defaults already chosen' in txt)
check('it names ONE batched ask_user, not an interview', 'ONE ask_user' in txt)
check('it is stored on the drawing', isinstance(d.ext.get('building_program'), dict))
check(
    'the programme survives a round trip through the document',
    A.Drawing(d.to_doc()).ext.get('building_program', {}).get('storeys') == 20,
)
check('the build order is given', 'core (stair + lift)' in txt and 'design_check' in txt)

for bad, why in (
    ({'use': 'castle', 'storeys': 3, 'cell_from': 'K20', 'cell_to': 'X34'}, 'unknown use'),
    ({'use': 'office', 'storeys': 3, 'cell_from': 'K20', 'cell_to': ''}, 'no footprint'),
    ({'use': 'office', 'storeys': 0, 'cell_from': 'K20', 'cell_to': 'X34'}, 'zero storeys'),
    ({'use': 'office', 'storeys': 3, 'cell_from': 'K20', 'cell_to': 'X34', 'skip': ['helipad']}, 'unknown skip key'),
):
    t, _ = assistant('plan_building', bad)
    check(f'refused: {why}', t.startswith('refused:'), t[:80])

# ── evidence matches what the tools really build ─────────────────────────────
# a lift is ONE elevator_shaft record carrying the whole height, not one per storey
txt, d = assistant('plan_building', {'use': 'residential', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'})
rows = {r['key']: r for r in BP.status(d, BP.get_program(d))}
check('nothing is built yet', not rows['elevator']['ok'] and not rows['stair']['ok'])
# add_stair now refuses a cell that is not inside a building, so the shell first
assistant('draw_box', {'cell_from': 'K20', 'cell_to': 'X34', 'storeys': 6}, drawing=d)
assistant('add_stair', {'cell': 'L21', 'from_storey': 0, 'to_storey': 5, 'kind': 'u'}, drawing=d)
rows = {r['key']: r for r in BP.status(d, BP.get_program(d))}
check('the stair the tool builds satisfies the stair item', rows['stair']['ok'], rows['stair']['detail'])
# O21, not M21: add_elevator refuses a shaft inside a stair's plan since 2026-09-12,
# and a 1 m u stair at L21 is 3.0 x 2.2 m — O21 is the nearest clear cell it names.
assistant('add_elevator', {'cell': 'O21', 'from_storey': 0, 'to_storey': 5}, drawing=d)
rows = {r['key']: r for r in BP.status(d, BP.get_program(d))}
check('one lift satisfies a 6-storey residential', rows['elevator']['ok'], rows['elevator']['detail'])
assistant('add_windows', {'walls': 'all', 'kind': 'double_door'}, drawing=d)

# a lift that stops a storey short must NOT pass
_, d2 = assistant('plan_building', {'use': 'residential', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'})
assistant('add_elevator', {'cell': 'M21', 'from_storey': 0, 'to_storey': 3}, drawing=d2)
rows2 = {r['key']: r for r in BP.status(d2, BP.get_program(d2))}
check('a shaft that stops short does not pass', not rows2['elevator']['ok'], rows2['elevator']['detail'])

# ── the gate ─────────────────────────────────────────────────────────────────
findings = DR.run_checks(d)
prog_errs = [f for f in findings if f['code'] == 'program' and f['sev'] == 'error']
check('missing required items are ERRORS on the gate', prog_errs, len(findings))
# the last error may be the "N more" roll-up, which is a summary, not an item
items = [f for f in prog_errs if f['text'].startswith('the program') is not False and 'Build it:' in f['text']]
check(
    'each itemised finding names the tool call that fixes it',
    items and len(items) >= len(prog_errs) - 1,
    [f['text'][:60] for f in prog_errs],
)
check('each itemised finding names its spec sheet', all('spec("' in f['text'] for f in items))
check('the finding list is capped', len(prog_errs) <= 7, len(prog_errs))
check(
    'the overflow is rolled up, not dropped',
    len(prog_errs) < 7 or 'more required item' in prog_errs[-1]['text'],
    prog_errs[-1]['text'][:80],
)

# waiving
txt, _ = assistant('program_status', {'skip': ['parking', 'balconies']}, drawing=d)
check('skip waives an item', 'WAIVED' in txt, txt[:60])
waived = {r['key']: r['need'] for r in BP.get_program(d)['items']}
check('the waiver is stored', waived.get('parking') == 'waived')
check(
    'a waived item raises no finding',
    not [
        f for f in DR.run_checks(d) if f['code'] == 'program' and 'parking' in f['text'].lower() and f['sev'] == 'error'
    ],
)

# no programme, no findings — the gate never fires on a drawing that never planned
check('a drawing with no programme is not judged', not BP.check_program(A.Drawing({'objects': []})))

# status reads the drawing, not the plan
txt, _ = assistant('program_status', {}, drawing=d)
check('status marks what is built', '[built]' in txt and '[TODO]' in txt, txt[:80])
txt, _ = assistant('program_status', {}, drawing=A.Drawing({'objects': []}))
check('status without a programme says how to make one', 'plan_building' in txt, txt[:80])

# ── evidence must recognise what the tools ACTUALLY make (2026-09-08) ────────
# Three bugs that each made a required item unsatisfiable by the very tool
# meant to satisfy it, and each of which passed a green unit test before:
#   · add_street_furniture places a REAL model, so a lamp is an `asset` record
#     with p.item 'street_lamp_01_2k', not a `lamp_post` kind;
#   · add_parapet writes plain `wall` records NAMED parapet;
#   · substring matching counted every lamp as a tree, because 'street'
#     contains 'tree'.
_, dz = assistant('plan_building', {'use': 'residential', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'})
assistant('draw_box', {'cell_from': 'K20', 'cell_to': 'X34', 'storeys': 6}, drawing=dz)
assistant('add_parapet', {'group': 'box K20-X34', 'height': 1.1}, drawing=dz)
assistant('add_road', {'cells': ['Y26', 'AF26'], 'width': 6}, drawing=dz)
assistant(
    'add_street_furniture', {'cells': ['Y22', 'AB22', 'Y30', 'AB30'], 'kind': 'lamp_post', 'height': 5}, drawing=dz
)
assistant('plant_trees', {'cell_from': 'AH20', 'cell_to': 'AP34', 'count': 4, 'height': 7}, drawing=dz)
rz = {r['key']: r for r in BP.status(dz, BP.get_program(dz))}
check('a parapet built as `wall` records satisfies the parapet item', rz['parapet']['ok'], rz['parapet']['detail'])
check('real-model lamps satisfy the approach item', rz['approach']['ok'], rz['approach']['detail'])
check('real-model trees satisfy the planting item', rz['landscape']['ok'], rz['landscape']['detail'])
check(
    '"street" is not counted as a "tree"',
    BP._count(dz, BP.TREES, words=('tree', 'oak', 'pine', 'fir')) == 4,
    BP._count(dz, BP.TREES, words=('tree',)),
)
check('whole-word matching still finds the word it should', BP._count(dz, ('lamp_post',), words=('lamp',)) == 4)
assistant('add_room', {'cell_from': 'K21', 'cell_to': 'L23', 'storey': 0, 'name': 'Refuse store'}, drawing=dz)
check(
    'a room is recognised by its group name',
    BP._groups(dz, ('refuse',)) == {'Refuse store'},
    BP._groups(dz, ('refuse',)),
)


# ── the core serves the ROOF DECK, not the top flat (2026-09-10) ─────────────
# Job 71ac02b0 built a 20-storey tower whose stair and lifts stopped at storey
# 19 while the infinity pool sat on the deck at storey 20, and the checklist
# said "0 errors" three times.  storeys - 1 was the bug: an accessible flat
# deck IS a storey people stand on.
c20 = {'use': 'residential', 'storeys': 20, 'pick_of': {'roof': 'flat_deck'}}
c20b = {'use': 'residential', 'storeys': 20, 'pick_of': {'roof': 'flat'}}
check('an accessible deck is the top of the core', BP._top_storey(c20) == 20, BP._top_storey(c20))
check('a roof nobody stands on is not', BP._top_storey(c20b) == 19, BP._top_storey(c20b))
# 2026-09-16: the stair how-line is a _macro() now — with core_kit loaded it names
# add_core(), the ONE call that draws the stair, the lifts and the shared landing from
# storey 0 to the deck, so it no longer spells "to_storey=20" itself.  The deck storey
# is still stated to the model, on the roof_access line ("already runs to storey 20 —
# the deck").  What must never happen is that NO core how-line says how far up it goes.
_h20 = {i['key']: i['how'] for i in BP.resolve('residential', 20, 'EX90', 'FQ109')['items']}
check(
    'the deck reaches the how-lines before the roof item is picked',
    ('to_storey=20' in _h20['stair'] or 'to the deck' in _h20['stair']) and 'storey 20' in _h20['roof_access'],
    (_h20['stair'], _h20['roof_access']),
)

pr20 = BP.resolve('residential', 20, 'EX90', 'FQ109')
n20 = {i['key']: i['need'] for i in pr20['items']}
check('a flat deck makes roof access REQUIRED', n20.get('roof_access') == 'required', n20.get('roof_access'))
check(
    'roof access is on the checklist of every tall building',
    {i['key']: i['need'] for i in BP.resolve('office', 8, 'K20', 'X34')['items']}.get('roof_access') == 'required',
)
check(
    'a 2-storey house is only recommended one',
    {i['key']: i['need'] for i in BP.resolve('house', 2, 'K20', 'N24')['items']}.get('roof_access') == 'recommended',
)


# ── THE PROOF: every required how-line, called literally ─────────────────────
# The claim _fmt now prints is "Every how-line above is literal: call it with
# real cells; its reply names what it made."  This runs them.  Where a tool has
# not grown the signature the how-line names yet, the item is SKIPped out loud
# and listed in the task report — never faked.
def accepts(tool, *params) -> bool:
    fn = A.TOOL_FN.get(tool)
    if fn is None:
        return False
    ps = inspect.signature(fn).parameters
    return all(p in ps for p in params)


SKIPPED: list = []


def literal(tool, **args):
    """Run one how-line. A refusal is a how-line that is not literal."""
    r = A.call_tool(dp, tool, args)
    check(f'how-line runs: {tool}', not str(r).startswith('refused:'), str(r)[:200])
    return r


txt, dp = assistant('plan_building', {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20})
check('the how-lines announce themselves as literal', 'Every how-line above is literal' in txt)
check('present is in the build order, and blender_render is not the last word', '-> present -> done' in txt, txt[-260:])
prog = BP.get_program(dp)
req = [r['key'] for r in prog['items'] if r['need'] == 'required']
check(
    'the 20-storey block of flats needs a core, a deck and roof access',
    {'stair', 'elevator', 'second_escape', 'roof_access', 'plant'} <= set(req),
    req,
)

GRP = 'box EX90-FQ109'
literal('draw_box', centre='FH100', width=20, depth=20, storeys=20, roof='flat')
literal('add_opening', group=GRP, side='south', storey=0, kind='double_door')  # entrance
literal('add_canopy', group=GRP, side='south', storey=0, width=8, depth=5, height=4, columns=4)
literal('add_stair', cell='FH96', from_storey=0, to_storey=20, kind='u', width=1.2)  # stair + roof access
# FD96 / FK96, not FF96 / FJ96: the 1.2 m u stair at FH96 is 3.44 x 2.60 m in plan
# and needs 1.2 m of floor at its foot (its -X side), so add_elevator refuses both of
# the cells job 038ca075c052 used.  These two are what the elevator how-line and the
# refusal itself now name: >= 4 cells west / >= 3 cells east of the stair cell.
literal('add_elevator', cell='FD96', from_storey=0, to_storey=20, w=1.8, depth=2.0)  # lift 1 of 2
literal('add_elevator', cell='FK96', from_storey=0, to_storey=20, w=1.8, depth=2.0)  # lift 2 of 2
literal('add_room', cell_from='EY91', cell_to='FC95', storey=0, name='Lobby')
literal('add_corridor', cell_from='EY97', cell_to='FP99', storey=0, width=1.8)
# the typical floors: search_plans -> place_plan(align="core") -> repeat_floor.
# Job 94f5813b's tower had slab and facade on storeys 1-19 and nothing else.
_sr = literal('search_plans', kind='floor', width=20, depth=20)
_pid = re.search(r'\bsd_f_\w+', str(_sr))
check('search_plans finds a real whole floor for a 20 x 20 m plate', _pid is not None, str(_sr)[:90])
literal('place_plan', plan_id=_pid.group(0) if _pid else '', group=GRP, storey=1, align='core')
literal('repeat_floor', from_storey=2, to_storey=19, source_storey=1)
literal('add_room', cell_from='FL91', cell_to='FN94', storey=0, name='WC')
literal('furnish_bathroom', cell_from='FL91', cell_to='FN94', storey=0)
literal('add_roof', cell_from='EX90', cell_to='FQ109', storey=20, kind='flat')
literal('add_parapet', group=GRP, height=1.1)
literal('add_rooftop_plant', group=GRP)
literal('add_road', cells=['FS100', 'GB100'], width=6)
literal('add_street_furniture', cells=['FS96', 'FV96', 'FS104', 'FV104'], kind='lamp_post', height=5)
literal('add_room', cell_from='EY105', cell_to='FB108', storey=0, name='Cycle store')
literal('add_room', cell_from='FM105', cell_to='FP108', storey=0, name='Refuse store')

# second escape: the how-line is add_fire_escape(group, side=...) — OUTSIDE the
# facade.  Task 9 adds those parameters; until then the only call available
# puts the stair at a cell, which is what put job 71ac02b0's escape inside the
# plan, so it is NOT run here.
if accepts('add_fire_escape', 'group', 'side'):
    literal('add_fire_escape', group=GRP, side='north', storeys=20, width=1.2)
else:
    SKIPPED.append('second_escape')
    print(
        'SKIP second_escape: add_fire_escape'
        + str(inspect.signature(A.TOOL_FN['add_fire_escape'])).replace("d: 'Drawing', a, ", '')
        + ' has no group/side yet — the how-line cannot be run without putting the '
        'escape stair inside the plan'
    )

# roof access + the lift overrun.  add_stair(0..20) reaches 54.0 m; the DECK is
# 54.3 m (the roof slab is 0.3 m thick) and there is no head house and no
# overrun in any tool yet, so the evidence is placed directly — with a note.
deck = BP._top_deck(dp)
check('the deck is the top of the roof slab, not the top of the walls', abs(deck - 54.3) < 0.01, deck)
r_ra = {r['key']: r for r in BP.status(dp, prog)}['roof_access']
# 2026-09-11: add_stair's top flight now climbs deck - floor (3.0 m), so the
# tools alone satisfy roof access; the "0.3 m short" case is made by hand.
check('a core drawn by add_stair(0..20) reaches the deck and passes roof access', r_ra['ok'], r_ra['detail'])
_tops = [o for o in dp.objs if o.get('kind') == 'stair_u' and abs(o['y'] - 19 * 2.7) < 0.05]
_keep = [(o, dict(o['p'])) for o in _tops]
for o, _ in _keep:
    o['p']['steps'], o['p']['rise'] = 15, 0.18  # 51.3 + 2.7 = 54.0: 0.3 m short
r_short = {r['key']: r for r in BP.status(dp, prog)}['roof_access']
check('a core that stops 0.3 m under the deck does not pass roof access', not r_short['ok'], r_short['detail'])
check(
    'the failure names how far short the stair stops',
    'stair stops at' in r_short['detail'] and 'short of' in r_short['detail'],
    r_short['detail'],
)
for o, pp in _keep:
    o['p'] = pp
r_pl = {r['key']: r for r in BP.status(dp, prog)}['plant']
check(
    'plant with a lift overrun passes (add_elevator writes p.overrun since 2026-09-10)',
    r_pl['ok'] and 'overrun' in r_pl['detail'],
    r_pl['detail'],
)
if not accepts('add_stair', 'head_house'):
    SKIPPED.append('roof_access (head house) + plant (overrun)')
    print(
        'SKIP roof_access/plant tools: no tool builds a head house or a lift overrun yet — '
        'placing the records directly, as the evidence the finished tools must produce'
    )
HX, HZ = A.cell_centre(*A.parse_cell('FH96'))
dp.new(
    'stair_u',
    {'steps': 17, 'rise': round(3.0 / 17, 6), 'run': 0.28, 'w': 1.2},
    HX,
    HZ,
    51.3,
    0.0,
    'mat_concrete',
    name='head house stair st19-deck',
    grp='stair FH96',
)
for i, (dx, dz) in enumerate(((-2, 0), (2, 0), (0, -2), (0, 2))):
    dp.new(
        'wall',
        {'w': 4.0, 'h': 2.6, 't': 0.2},
        HX + dx,
        HZ + dz,
        54.3,
        0.0,
        'mat_concrete',
        name=f'tower head house wall {i + 1}',
        grp='tower head house',
    )
dp.new(
    'elevator_shaft',
    {'w': 1.8, 'd': 2.0, 'h': 3.0, 't': 0.2, 'overrun': 1.5},
    HX + 4,
    HZ,
    54.3,
    0.0,
    'mat_concrete',
    name='lift overrun motor room',
    grp='lift FF96',
)

rows = {r['key']: r for r in BP.status(dp, BP.get_program(dp))}
for k in req:
    if k in SKIPPED or any(k in s for s in SKIPPED):
        continue
    check(f'the how-line satisfies its own item: {k}', rows[k]['ok'], rows[k]['detail'])
check(
    'the stair detail names the storeys the stack starts on',
    rows['stair']['detail'].startswith('stairs start on storeys 0..'),
    rows['stair']['detail'],
)
check(
    'the lift detail reports the storeys its doors serve',
    'doors on' in rows['elevator']['detail'] and 'no doors (legacy)' not in rows['elevator']['detail'],
    rows['elevator']['detail'],
)
check(
    'roof access passes once the deck is reached and covered', rows['roof_access']['ok'], rows['roof_access']['detail']
)
check('plant passes once the overrun is there', rows['plant']['ok'], rows['plant']['detail'])
gate = [f for f in DR.run_checks(dp) if f['code'] == 'program' and f['sev'] == 'error']
check(
    'with every runnable how-line built, only the skipped items hold the gate',
    len(gate) <= len(SKIPPED),
    [f['text'][:70] for f in gate],
)


# ── the new evidence, each half on its own ───────────────────────────────────
# a stair built one record per storey (what task 8 makes) is the shape that passes
ds = A.Drawing({'objects': []})
ds.ext['building_program'] = BP.resolve('office', 6, 'K20', 'X34')
for s in range(5):  # roof 'flat' at 6 storeys -> the core serves storey 5
    ds.new(
        'stair_u',
        {'steps': 16, 'rise': 0.16875, 'run': 0.28, 'w': 1.2},
        0.0,
        0.0,
        s * ds.storey_h,
        0.0,
        'mat_concrete',
        name=f'stair st{s}',
        grp='stair K21',
    )
st = {r['key']: r for r in BP.status(ds, BP.get_program(ds))}['stair']
check(
    'a per-storey stack of stair records passes without the legacy note',
    st['ok'] and 'legacy' not in st['detail'],
    st['detail'],
)
check('the detail names the storeys it starts on', st['detail'] == 'stairs start on storeys 0..4 of 0..4', st['detail'])
ds.objs = [o for o in ds.objs if o['y'] < 5]  # knock the stack down to two storeys
st = {r['key']: r for r in BP.status(ds, BP.get_program(ds))}['stair']
check('a stack that stops short fails, and says how far it got', not st['ok'], st['detail'])

# a shaft with doors serves the storeys its doors are on
dl = A.Drawing({'objects': []})
dl.ext['building_program'] = BP.resolve('office', 6, 'K20', 'X34')
nl = [i for i in dl.ext['building_program']['items'] if i['key'] == 'elevator'][0]['n']
for i in range(nl):
    dl.new(
        'elevator_shaft',
        {'w': 1.8, 'd': 2.0, 'h': 16.2, 't': 0.2, 'doors': [0, 1, 2]},
        float(i),
        0.0,
        0.0,
        0.0,
        'mat_concrete',
        name=f'lift shaft {i}',
        grp=f'lift {i}',
    )
lf = {r['key']: r for r in BP.status(dl, BP.get_program(dl))}['elevator']
check('a tall shaft with doors on 3 of 6 storeys does not pass', not lf['ok'], lf['detail'])
for o in dl.objs:
    o['p']['doors'] = list(range(6))
lf = {r['key']: r for r in BP.status(dl, BP.get_program(dl))}['elevator']
check('doors on every storey pass', lf['ok'], lf['detail'])


# balconies: one balcony on a 20-storey block of flats is a token.
# 2026-09-16: the item is measured in STOREYS, not in records. Counting records
# let forty balconies on one storey pass and failed the tower recipe's own south
# facade — eight balconies every second storey from 4 to 18 — because a
# one-facade design can never hold one record per two storeys on four sides.
# The rule now: carry a quarter of the storeys, spread over half of them.
def bal_of(dr):
    return {r['key']: r for r in BP.status(dr, BP.get_program(dr))}['balconies']


db = A.Drawing({'objects': []})
db.ext['building_program'] = BP.resolve('residential', 20, 'EX90', 'FQ109')
db.new('balcony', {'w': 2.4, 'd': 1.8}, 0.0, 0.0, 2.7, 0.0, 'mat_concrete', name='balcony', grp='balconies')
bl = bal_of(db)
check(
    '1 balcony on 20 storeys is not balconies',
    not bl['ok'] and 'need 10' in bl['detail'] and '1 balcony record(s) on 1 storey(s)' in bl['detail'],
    bl['detail'],
)
for i in range(9):
    db.new(
        'balcony', {'w': 2.4, 'd': 1.8}, 0.0, 0.0, (i + 2) * 2.7, 0.0, 'mat_concrete', name='balcony', grp='balconies'
    )
bl = bal_of(db)
check('half the storeys is', bl['ok'], bl['detail'])

# forty records stacked on ONE storey is the same token, forty times over
dbs = A.Drawing({'objects': []})
dbs.ext['building_program'] = BP.resolve('residential', 20, 'EX90', 'FQ109')
for i in range(40):
    dbs.new(
        'balcony', {'w': 2.4, 'd': 1.8}, float(i), 0.0, 3 * 2.7, 0.0, 'mat_concrete', name='balcony', grp='balconies'
    )
bl = bal_of(dbs)
check(
    '40 balconies all on storey 3 is not balconies',
    not bl['ok'] and '40 balcony record(s) on 1 storey(s)' in bl['detail'],
    bl['detail'],
)

# a record that only says 'balcony' in its name counts too (older drawings and
# hand edits in the tab never set the kind)
dbn = A.Drawing({'objects': []})
dbn.ext['building_program'] = BP.resolve('residential', 20, 'EX90', 'FQ109')
for i in range(6):
    dbn.new(
        'slab',
        {'w': 2.4, 'd': 1.8, 't': 0.2},
        0.0,
        0.0,
        (i * 2 + 2) * 2.7,
        0.0,
        'mat_concrete',
        name=f'balcony slab st{i * 2 + 2}',
        grp='tower',
    )
bl = bal_of(dbn)
check('balcony records named, not kinded, still count', bl['ok'], bl['detail'])

# (A/B on the real recipe) the tower recipe's own south facade passes the item
RFIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'tower_recipe_20260916.json')
drec = A.Drawing(json.load(open(RFIX)))
bl = bal_of(drec)
check(
    'the tower recipe fixture has 8 south balconies over storeys 4..18',
    sum(1 for o in drec.objs if o.get('kind') == 'balcony') == 8,
    bl['detail'],
)
check(
    '(A) and they PASS the balconies item',
    bl['ok'] and '8 balcony record(s) on 8 storey(s), spread over 15 of 20' in bl['detail'],
    bl['detail'],
)
# (B) the same drawing with all but one balcony deleted fails, naming the count
dbad = A.Drawing(json.load(open(RFIX)))
dbad.remove([o for o in dbad.objs if o.get('kind') == 'balcony'][1:])
bl = bal_of(dbad)
check(
    '(B) one balcony left on the recipe tower fails, naming the count',
    not bl['ok'] and '1 balcony record(s) on 1 storey(s)' in bl['detail'] and 'need 10' in bl['detail'],
    bl['detail'],
)

# the second escape: the old evidence said ok and 'no second escape found' at once
de = A.Drawing({'objects': []})
de.ext['building_program'] = BP.resolve('residential', 20, 'EX90', 'FQ109')
se = {r['key']: r for r in BP.status(de, BP.get_program(de))}['second_escape']
check('no escape stair is not ok', not se['ok'] and 'no second escape' in se['detail'], se['detail'])
de.new(
    'fire_stair_exterior',
    {'storeys': 20, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18},
    0.0,
    0.0,
    0.0,
    0.0,
    'mat_steel',
    name='fire escape',
    grp='fire escape',
)
se = {r['key']: r for r in BP.status(de, BP.get_program(de))}['second_escape']
check(
    'an external escape stair is, and the detail agrees with the verdict',
    se['ok'] and 'external escape stair' in se['detail'],
    se['detail'],
)
if 'envelope_rules' in A.EXT_MODULES and hasattr(A.EXT_MODULES['envelope_rules'], 'group_at'):
    check(
        'the escape stair is judged against the envelope',
        'envelope' in se['detail'] or 'inside the plan' in se['detail'],
        se['detail'],
    )
else:
    SKIPPED.append('second_escape outside-the-envelope check')
    print(
        'SKIP second_escape envelope test: no envelope_rules family with group_at() yet — '
        'the evidence falls back to "an external escape stair exists"'
    )

# ── the programme carries the REQUEST's own words (2026-09-10) ───────────────
# Job 71ac02b0's operator asked for an infinity pool, a roof entrance, a nice
# entrance, glass walls and something luxurious.  plan_building was resolved
# from `use` and `storeys` alone, so not one of those five words reached the
# checklist: the pool was never an item, "luxurious" was answered in
# mat_concrete, and design_check said "0 errors" three times.
REQUEST = (
    'build a building with footprint of 20x20 , 20 stories high . infinity pool on the roof . '
    'roof entrance . nice entrance into the building at ground floor . make ground floor glass '
    'walls , 2nd floor rough concrete wall , 3rd floor glass walls , 4th rough concrete , repeat '
    'this for all floors. center building at cell fh100  make building look luxurious'
)

dr = A.Drawing({'objects': []})
dr.request = REQUEST  # task 14 sets this server-side from the user's message
tr, dr = assistant(
    'plan_building', {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20}, drawing=dr
)
pr = BP.get_program(dr)
nr = {i['key']: i['need'] for i in pr['items']}
kr = {i['key']: i for i in pr['items']}
check(
    '"infinity pool on the roof" makes the POOL a required item', nr.get('roof_pool') == 'required', nr.get('roof_pool')
)
check('and it makes roof access required with it', nr.get('roof_access') == 'required', nr.get('roof_access'))
check('a "nice entrance" asks for a reception too', nr.get('reception') == 'required', nr.get('reception'))
check('"luxurious" sets the finish level', pr['finish_level'] == 'luxury', pr['finish_level'])
check('a luxury roof deck must be furnished', nr.get('deck_furniture') == 'required', nr.get('deck_furniture'))
check('a luxury building must be finished in library materials', nr.get('finishes') == 'required', nr.get('finishes'))
check('"glass walls" glazes the facade without being asked', pr['glass'] is True, pr['glass'])
check(
    '"nice entrance" IS a porte cochere, not a guess', kr['entrance']['pick'] == 'porte_cochere', kr['entrance']['pick']
)
check(
    'a luxury lobby is double height whatever the height', kr['lobby']['pick'] == 'double_height', kr['lobby']['pick']
)
# 2026-09-16: the roof-pool how-line is a _macro() — with roof_kit loaded it names
# build_roof_deck(), the ONE call that puts the guard up FIRST and then the pool, the
# loungers and the lights on the deck, and only falls back to the raw add_pool(...,
# storey=20) when the kit is absent.  Either wording is a call the model can make.
check(
    'the roof pool how-line is the call that works, on the deck storey',
    'build_roof_deck(' in kr['roof_pool']['how']
    or ('add_pool(' in kr['roof_pool']['how'] and 'storey=20' in kr['roof_pool']['how']),
    kr['roof_pool']['how'],
)
check('the programme prints a FROM THE REQUEST section', 'FROM THE REQUEST' in tr, tr[:120])
check(
    'it quotes the words it mapped and what each one bought',
    '"infinity pool" -> roof pool + roof access' in tr,
    [l for l in tr.splitlines() if '->' in l][:3],
)
check(
    'the finish level is stored where draw_box and set_finish read it',
    A.finish_level(dr) == 'luxury',
    A.finish_level(dr),
)
check(
    'the whole request programme survives the document round trip',
    A.Drawing(dr.to_doc()).ext['building_program']['finish_level'] == 'luxury',
)

# the gate: a plain box answers none of it
assistant('draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 20, 'roof': 'flat'}, drawing=dr)
gate_txt = ' '.join(f['text'].lower() for f in DR.run_checks(dr) if f['code'] == 'program' and f['sev'] == 'error')
check('the gate now refuses over the roof pool the user asked for', 'roof pool' in gate_txt, gate_txt[:160])
check('and over the roof access it needs', 'roof access' in gate_txt, gate_txt[:160])
fin = {r['key']: r for r in BP.status(dr, pr)}['finishes']
check(
    'the box the tools drew today is born finished — the item passes',
    fin['ok'] and 'material-library finish' in fin['detail'],
    fin['detail'],
)

# 2026-09-16: draw_box can no longer PRODUCE the grey massing model — the luxury
# programme is already on the drawing, so Drawing.new stamps a library finish on
# every record it writes. The defect still ARRIVES: job 71ac02b0's own file, an
# older drawing reopened, a hand edit in the tab. That is what the item has to
# catch, so the programme is lifted for the write and put back straight after.
GRP_DR = 'box EX90-FQ109'
_prog = dr.ext.pop('building_program')
try:
    _cx, _cz = A.cell_centre(*A.parse_cell('FH100'))
    for _i in range(20):  # one concrete storey wall each
        dr.new(
            'wall',
            {'len': 20.0, 'h': 2.7, 't': 0.24},
            _cx,
            _cz,
            _i * dr.storey_h,
            0.0,
            'mat_concrete',
            name=f'concrete wall st{_i}',
            grp=GRP_DR,
        )
finally:
    dr.ext['building_program'] = _prog
fin2 = {r['key']: r for r in BP.status(dr, pr)}['finishes']
check(
    'a "luxurious" tower in mat_concrete does not pass finishes',
    not fin2['ok'] and 'mat_concrete' in fin2['detail'],
    fin2['detail'],
)
check(
    'one apply_finishes repaints the arrived presets and the item passes',
    'records finished' in A.call_tool(dr, 'apply_finishes', {})
    and {r['key']: r for r in BP.status(dr, pr)}['finishes']['ok'],
    {r['key']: r for r in BP.status(dr, pr)}['finishes']['detail'],
)

# and the tools the how-lines name do answer it
assistant('add_pool', {'cell_from': 'FA100', 'cell_to': 'FE109', 'storey': 20, 'infinity': 'south'}, drawing=dr)
assistant('add_beach_set', {'cells': ['EZ93', 'FB93', 'FN93', 'FP93'], 'storey': 20}, drawing=dr)
assistant(
    'set_finish',
    {
        'group': 'box EX90-FQ109',
        'floor_material': 'acg_Marble006',
        'wall_material': 'acg_Marble006',
        'roof_material': 'pht_wood_floor_deck',
    },
    drawing=dr,
)
rr = {r['key']: r for r in BP.status(dr, BP.get_program(dr))}
check('add_pool on the deck storey satisfies the roof pool', rr['roof_pool']['ok'], rr['roof_pool']['detail'])
check(
    'add_beach_set on the deck satisfies the deck furniture', rr['deck_furniture']['ok'], rr['deck_furniture']['detail']
)
check('set_finish with library ids satisfies the finishes item', rr['finishes']['ok'], rr['finishes']['detail'])

# a luxury lobby is measured, not named
assistant('add_room', {'cell_from': 'EY91', 'cell_to': 'FC95', 'storey': 0, 'name': 'Lobby'}, drawing=dr)
lb = {r['key']: r for r in BP.status(dr, BP.get_program(dr))}['lobby']
check(
    'a 5 m room called Lobby is not a luxury lobby',
    not lb['ok'] and '8 m across' in lb['detail'] and '6 m deep' in lb['detail'],
    lb['detail'],
)
assistant('add_room', {'cell_from': 'FF102', 'cell_to': 'FP109', 'storey': 0, 'name': 'Lobby'}, drawing=dr)
lb = {r['key']: r for r in BP.status(dr, BP.get_program(dr))}['lobby']
check(
    'a room 8 m across but empty is still not one (job 94f5813b built exactly that)',
    not lb['ok'] and 'EMPTY' in lb['detail'] and 'furnish_lobby' in lb['detail'],
    lb['detail'],
)
assistant(
    'furnish_lobby', {'cell_from': 'FF102', 'cell_to': 'FP109', 'storey': 0, 'entrance_side': 'south'}, drawing=dr
)
lb = {r['key']: r for r in BP.status(dr, BP.get_program(dr))}['lobby']
check('a room 8 m across, furnished, is', lb['ok'] and 'furnished' in lb['detail'], lb['detail'])
# 2026-09-16: likewise a _macro() — entrance_kit's build_entrance() draws the room, the
# door and the fit-out in one call; furnish_lobby(...) is the fallback wording.
_lhow = {i['key']: i for i in BP.get_program(dr)['items']}['lobby']['how']
check(
    'and the how-line names the tool that furnished it', 'build_entrance(' in _lhow or 'furnish_lobby(' in _lhow, _lhow
)

# ── a request that asks for none of it ───────────────────────────────────────
dw = A.Drawing({'objects': []})
dw.request = 'a warehouse with a loading yard'
tw, dw = assistant(
    'plan_building', {'use': 'warehouse', 'storeys': 1, 'cell_from': 'K20', 'cell_to': 'X34'}, drawing=dw
)
pw = BP.get_program(dw)
nw = {i['key']: i['need'] for i in pw['items']}
check('a plain warehouse request is not luxury', pw['finish_level'] == 'standard', pw['finish_level'])
check('and buys no luxury items', {'finishes', 'deck_furniture', 'roof_pool'}.isdisjoint(nw), sorted(nw))
check('the loading bay a warehouse always needs is still required', nw.get('loading') == 'required', nw.get('loading'))
check('a request that mapped nothing prints no request section', 'FROM THE REQUEST' not in tw, tw[:120])

# ── a word with no rule is said out loud, not dropped ────────────────────────
dh = A.Drawing({'objects': []})
dh.request = 'a house with a helipad'
th, dh = assistant('plan_building', {'use': 'house', 'storeys': 2, 'cell_from': 'K20', 'cell_to': 'N24'}, drawing=dh)
check(
    'a building noun that fired no rule lands in unmapped',
    'helipad' in (BP.get_program(dh).get('unmapped') or []),
    BP.get_program(dh).get('unmapped'),
)
check(
    'and the model is told to decide it or say so',
    'REQUEST WORDS NOT MAPPED' in th,
    [l for l in th.splitlines() if 'NOT MAPPED' in l],
)
check(
    'a word a rule DID map is not also reported unmapped', 'pool' not in (pr.get('unmapped') or []), pr.get('unmapped')
)

# ── no request, no change ────────────────────────────────────────────────────
tn, dn = assistant('plan_building', {'use': 'residential', 'storeys': 20, 'centre': 'FH100', 'width': 20, 'depth': 20})
pn = BP.get_program(dn)
check('an empty request prints no request section', 'FROM THE REQUEST' not in tn, tn[:120])
check(
    'and adds no items of its own',
    {'roof_pool', 'finishes', 'deck_furniture'}.isdisjoint({i['key'] for i in pn['items']}),
    [i['key'] for i in pn['items']],
)
check('an unasked-for building is standard finish', pn['finish_level'] == 'standard', pn['finish_level'])

# ── amenities: one item per word the user named ──────────────────────────────
da = A.Drawing({'objects': []})
da.request = 'a 6 storey hotel with a gym, a spa and a rooftop bar, and underground parking'
ta, da = assistant('plan_building', {'use': 'hotel', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'}, drawing=da)
pa = BP.get_program(da)
na = {i['key']: i['need'] for i in pa['items']}
check(
    'every amenity the user named is its own required item',
    all(na.get('amenity:' + w) == 'required' for w in ('gym', 'spa', 'bar')),
    sorted(na),
)
check(
    '"parking" in the request makes parking required, not recommended',
    na.get('parking') == 'required',
    na.get('parking'),
)
check(
    '"rooftop" makes roof access required on a 6-storey hotel',
    na.get('roof_access') == 'required',
    na.get('roof_access'),
)
ra = {r['key']: r for r in BP.status(da, pa)}
check('an amenity nobody built is not ok', not ra['amenity:gym']['ok'], ra['amenity:gym']['detail'])
assistant('add_room', {'cell_from': 'L21', 'cell_to': 'O24', 'storey': 0, 'name': 'Gym'}, drawing=da)
ra = {r['key']: r for r in BP.status(da, BP.get_program(da))}
check('a room named Gym satisfies the gym', ra['amenity:gym']['ok'], ra['amenity:gym']['detail'])
tsk, _ = assistant('program_status', {'skip': ['amenity:spa']}, drawing=da)
check(
    'an amenity the USER named is required and cannot be waived by the model (2026-09-16)',
    str(tsk).startswith('refused:')
    and 'REQUIRED' in str(tsk)
    and {i['key']: i['need'] for i in BP.get_program(da)['items']}.get('amenity:spa') == 'required',
    str(tsk)[:160],
)
check(
    'but an amenity nobody asked for is still refused',
    assistant('program_status', {'skip': ['amenity:helipad']}, drawing=da)[0].startswith('refused:'),
)

# ── the request argument overrides what the job carried ──────────────────────
do = A.Drawing({'objects': []})
do.request = 'a plain office block'
to, do = assistant(
    'plan_building',
    {
        'use': 'office',
        'storeys': 6,
        'cell_from': 'K20',
        'cell_to': 'X34',
        'request': 'an exclusive office with balconies',
    },
    drawing=do,
)
po = BP.get_program(do)
check(
    'an explicit request= wins over the job request',
    po['finish_level'] == 'luxury' and {i['key']: i['need'] for i in po['items']}.get('balconies') == 'required',
    po['finish_level'],
)

# ── read_request is pure, and _top_deck is not fooled by a head house ────────
check('the same words map the same way twice', BP.read_request(REQUEST) == BP.read_request(REQUEST))
dd = A.Drawing({'objects': []})
dd.new('roof_flat', {'w': 20, 'd': 20, 't': 0.3}, 0.0, 0.0, 54.0, 0.0, 'mat_concrete', name='flat roof', grp='box')
check('the deck is the roof slab top', abs(BP._top_deck(dd) - 54.3) < 0.01, BP._top_deck(dd))
dd.new(
    'roof_flat',
    {'w': 3, 'd': 3, 't': 0.2},
    0.0,
    0.0,
    57.0,
    0.0,
    'mat_concrete',
    name='head house roof',
    grp='box head house',
)
check('a head house roof 2.7 m above it is not the deck', abs(BP._top_deck(dd) - 54.3) < 0.01, BP._top_deck(dd))

# ── a plan on every typical floor (2026-09-11) ───────────────────────────────
# Live job 94f5813b: a 20-storey tower whose storeys 1-19 held zero interior
# records — only storey 0 had rooms — and the programme gate passed, because no
# item ever asked what was ON the upper floors.
ntf = {i['key']: i['need'] for i in BP.resolve('residential', 20, 'EX90', 'FQ109')['items']}
check(
    'a 20-storey block of flats REQUIRES a plan on its typical floors',
    ntf.get('typical_floors') == 'required',
    ntf.get('typical_floors'),
)
check(
    'a single-storey building is not asked for one',
    'typical_floors' not in {i['key'] for i in BP.resolve('warehouse', 1, 'K20', 'X34')['items']},
)

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'fixtures', 'live_tower_20260911.json')
dlive = A.Drawing(json.load(open(FIX)))
check('the live tower fixture loads', len(dlive.objs) == 336, len(dlive.objs))
_pl = BP.get_program(dlive)
check(
    'its programme has no typical-floors item — that is the hole this closes',
    'typical_floors' not in {i['key'] for i in _pl['items']},
)
# a replan resolves the checklist the job should have had
dlive.ext['building_program'] = BP.resolve(
    _pl['use'], _pl['storeys'], _pl['cell_from'], _pl['cell_to'], request=_pl.get('request') or ''
)
tf = {r['key']: r for r in BP.status(dlive, BP.get_program(dlive))}['typical_floors']
check('the tower that passed the last gate does not pass this item', not tf['ok'], tf['detail'])
check(
    'and the failure names the empty storeys, first and last',
    'EMPTY storeys' in tf['detail'] and re.search(r'\b1\b', tf['detail']) and re.search(r'\b19\b', tf['detail']),
    tf['detail'],
)
dlive.ext['floor_layouts'] = {str(s): {'ids': []} for s in range(1, 20)}
tf2 = {r['key']: r for r in BP.status(dlive, BP.get_program(dlive))}['typical_floors']
check('a plan registered on every upper storey satisfies it', tf2['ok'], tf2['detail'])
check('and the detail says which storeys are laid out', tf2['detail'] == 'storeys 1-19 laid out', tf2['detail'])
check(
    'a placed floor plan carries the corridor with it',
    {r['key']: r for r in BP.status(dlive, BP.get_program(dlive))}['corridor']['ok'],
    {r['key']: r for r in BP.status(dlive, BP.get_program(dlive))}['corridor']['detail'],
)
check(
    'the build order names the real-plan route',
    'place_plan' in tn and 'align="core"' in tn,
    [l for l in tn.splitlines() if 'Order:' in l][:1],
)
check(
    'the lamp how-line says where the lamps go',
    '0.5 m outside the carriageway' in {i['key']: i for i in pn['items']}['approach']['how'],
    {i['key']: i for i in pn['items']}['approach']['how'],
)

print('\nSKIPPED (not faked): ' + ('; '.join(SKIPPED) if SKIPPED else 'nothing'))
# ── program_status(skip=) cannot waive a REQUIRED item (job 71e9d42e559f, 2026-09-16) ──
d_sk = A.Drawing(None)
d_sk.request = 'luxurious 20 storey tower with infinity pool'
A.call_tool(
    d_sk, 'plan_building', dict(use='residential', storeys=20, centre='FH100', width=20, depth=20, request=d_sk.request)
)
r_sk = A.call_tool(d_sk, 'program_status', dict(skip=['corridor', 'typical_floors', 'wc']))
check(
    'skipping corridor / typical_floors / wc on a 20-storey residential is REFUSED and says why',
    str(r_sk).startswith('refused:') and 'REQUIRED' in str(r_sk) and 'typical_floors' in str(r_sk),
    str(r_sk)[:200],
)
_BPm = A.EXT_MODULES['building_program']
_rows = _BPm.get_program(d_sk)['items']
check(
    '... and nothing was waived',
    all(r['need'] != 'waived' for r in _rows),
    [(r['key'], r['need']) for r in _rows if r['need'] == 'waived'],
)
r_ok = A.call_tool(d_sk, 'program_status', dict(skip=['parking']))
check(
    'skipping a RECOMMENDED item (parking) is still allowed',
    not str(r_ok).startswith('refused:')
    and any(r['key'] == 'parking' and r['need'] == 'waived' for r in _BPm.get_program(d_sk)['items']),
    str(r_ok)[:120],
)

finish()
