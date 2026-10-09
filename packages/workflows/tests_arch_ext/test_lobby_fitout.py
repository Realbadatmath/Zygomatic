# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_lobby_fitout — the lobby is furnished, and the programme checks it.

Job 94f5813b's "double-height lobby" was four plaster partitions with nothing
inside, and the build checklist passed it. This proves both halves of the fix:
furnish_lobby puts real pieces in the block, and building_program's lobby item
refuses an empty room on a luxury job.

    /usr/bin/python3 tests_arch_ext/test_lobby_fitout.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

BP = A.EXT_MODULES['building_program']
LF = A.EXT_MODULES['lobby_fitout']
GRP = 'Lobby fit-out'


def models(rows, aid):
    """The pack-model records of one asset id. place_asset always makes kind
    'asset' — the item id inside p is the only thing that says WHAT it is."""
    item = aid.split('|')[-1]
    return [o for o in rows if o['kind'] == 'asset' and (o.get('p') or {}).get('item') == item]


def hung(o):
    return bool((o.get('meta') or {}).get('hung'))


check('the tool is registered', 'furnish_lobby' in tool_names())
check('the family declares no new kinds', LF.KINDS == {}, LF.KINDS)
check('the prompt is inside the 900-char ceiling', len(LF.PROMPT) <= 900, len(LF.PROMPT))
check('at least two examples', len(LF.EXAMPLES) >= 2, len(LF.EXAMPLES))

# ── a real lobby: a box, add_room, furnish_lobby ─────────────────────────────
XMIN, ZMIN, XMAX, ZMAX = A.block_bounds('C4', 'L9')  # 10 x 6 m
d = A.Drawing({'objects': []})
assistant('draw_box', {'cell_from': 'B3', 'cell_to': 'M10', 'storeys': 2, 'roof': 'flat', 'name': 'tower'}, drawing=d)
assistant(
    'add_room', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'name': 'Lobby', 'door_side': 'south'}, drawing=d
)
before = len(d.objs)
txt, d = assistant(
    'furnish_lobby', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'entrance_side': 'south'}, drawing=d
)
fit = [o for o in d.objs if o['grp'] == GRP]
k = kinds_of(A.Drawing({'objects': fit}))
check('it is not a refusal', not txt.startswith('refused'), txt)
check(
    'everything it made is in one "<name> fit-out" group',
    len(fit) == len(d.objs) - before,
    (len(fit), len(d.objs) - before),
)
check('a reception desk of two desk records', k.get('desk') == 2, k)
# 2026-09-16: on a luxury job the seating group and the planters are PACK MODELS,
# so they are kind 'asset' and not kind 'sofa'/'armchair'/'shrub' any more. The four
# parametric armchairs that remain are the waiting chairs at the counter — they are
# what building_program's lobby item counts as seats (it cannot see an 'asset').
check(
    'two sofa models and two armchair models',
    len(models(fit, LF.ASSET_SOFA)) == 2 and len(models(fit, LF.ASSET_ARMCHAIR)) == 2,
    (len(models(fit, LF.ASSET_SOFA)), len(models(fit, LF.ASSET_ARMCHAIR)), k),
)
check(
    'no parametric box chairs beside the models (2026-09-16: the programme counts the models)',
    not k.get('armchair') and not k.get('sofa'),
    k,
)
check('one coffee table on one rug', k.get('coffee_table') == 1 and k.get('rug') == 1, k)
plants = len(models(fit, LF.ASSET_PLANT)) + sum(v for kk, v in k.items() if kk in LF.PLANT_KINDS)
check('four planters', plants == 4, (plants, k))
check('one chandelier, hung', len(models(fit, LF.ASSET_CHANDELIER)) == 1, k)
lights = [o for o in fit if o['kind'].startswith('light_')]
check('ceiling lights on a 4 m grid (3 x 2 over 10 x 6 m)', len(lights) == 6, len(lights))
check(
    'the reply counts every group', all(s in txt for s in ('2 desks', '4 seats', '4 planters', '6 ceiling lights')), txt
)
check('and it names the ids it made', f'ids {fit[0]["id"]}..{fit[-1]["id"]}' in txt, txt)

out = [(o['id'], o['kind'], o['x'], o['z']) for o in fit if not (XMIN <= o['x'] <= XMAX and ZMIN <= o['z'] <= ZMAX)]
check('every record sits inside the block', out == [], (out, (XMIN, ZMIN, XMAX, ZMAX)))
floor = [o for o in fit if not o['kind'].startswith('light_') and not hung(o)]
check(
    'every piece stands on the floor (y within 0.35 of storey 0)',
    all(abs(o['y']) <= 0.35 for o in floor),
    sorted({o['y'] for o in floor}),
)
check(
    'the lights hang at the wall height less 0.6 m (2.7 - 0.6), not on the floor',
    all(abs(o['y'] - 2.1) < 1e-6 for o in lights),
    sorted({o['y'] for o in lights}),
)

desks = sorted((o for o in fit if o['kind'] == 'desk'), key=lambda o: o['x'])
check(
    'the desk is at the far end, away from the south entrance',
    all(abs(o['z'] - ZMIN) < 1.5 for o in desks),
    [o['z'] for o in desks],
)
check(
    'it faces the entrance (ry = pi looks south)',
    all(abs(abs(o['ry']) - 3.141593) < 1e-3 for o in desks),
    [o['ry'] for o in desks],
)
check(
    'the two desks stand end to end (1.4 m apart, the width of one)',
    abs((desks[1]['x'] - desks[0]['x']) - 1.4) < 1e-6 and desks[0]['z'] == desks[1]['z'],
    [(o['x'], o['z']) for o in desks],
)
check('a luxury desk gets the marble top', all(o['mat'] == 'acg_Marble021' for o in desks), [o['mat'] for o in desks])

sofas = sorted(models(fit, LF.ASSET_SOFA), key=lambda o: o['z'])
check('the two sofa models are 2.4 m apart', abs((sofas[1]['z'] - sofas[0]['z']) - 2.4) < 1e-6, [o['z'] for o in sofas])
check('and they face each other', abs(abs(sofas[0]['ry'] - sofas[1]['ry']) - 3.141593) < 1e-3, [o['ry'] for o in sofas])
table = [o for o in fit if o['kind'] == 'coffee_table'][0]
rug = [o for o in fit if o['kind'] == 'rug'][0]
check(
    'the coffee table sits between them, on the rug',
    sofas[0]['z'] < table['z'] < sofas[1]['z'] and (table['x'], table['z']) == (rug['x'], rug['z']),
    (table['x'], table['z'], rug['x'], rug['z']),
)
check(
    '1.2 m of circulation is clear off the entrance wall',
    min(ZMAX - o['z'] for o in floor) >= 1.2 - 1e-9,
    sorted(round(ZMAX - o['z'], 2) for o in floor)[:3],
)

# ── the other three entrances are the same layout, turned ────────────────────
txt_w, dw = assistant('furnish_lobby', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'entrance_side': 'west'})
fw = [o for o in dw.objs if o['grp'] == GRP]
dkw = [o for o in fw if o['kind'] == 'desk']
check(
    'a west entrance puts the desk against the east wall', all(XMAX - o['x'] < 1.5 for o in dkw), [o['x'] for o in dkw]
)
check('facing west (ry = +pi/2)', all(abs(o['ry'] - 1.570796) < 1e-3 for o in dkw), [o['ry'] for o in dkw])
check(
    'and 1.2 m is clear off the WEST wall',
    min(o['x'] - XMIN for o in fw if not o['kind'].startswith('light_')) >= 1.2 - 1e-9,
    sorted(round(o['x'] - XMIN, 2) for o in fw)[:3],
)
# Turned west, the SAME 10 x 6 block is only 6 m across, under ASSET_MIN_ACROSS:
# a 2.73 m sofa pair with armchairs beside it does not fit, so the whole fit-out
# falls back to the parametric layout — and the reply has to say so.
kw = kinds_of(A.Drawing({'objects': fw}))
check(
    'a room under 8 m across falls back to the parametric pieces',
    not kw.get('asset') and kw.get('sofa') == 2 and kw.get('armchair') == 2,
    kw,
)
check('and the reply says why it fell back', 'stayed parametric' in txt_w, txt_w)

txt1, d1 = assistant(
    'furnish_lobby', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 1, 'name': 'Foyer', 'style': 'standard'}
)
f1 = [o for o in d1.objs if o['grp'] == 'Foyer fit-out']
check(
    'storey 1 stands everything on the 2.7 m floor',
    f1 and all(abs(o['y'] - 2.7) < 0.35 for o in f1 if not o['kind'].startswith('light_')),
    sorted({o['y'] for o in f1}),
)
check('a standard lobby gets no marble', all(o['mat'] != 'acg_Marble021' for o in f1), {o['mat'] for o in f1})
k1 = kinds_of(A.Drawing({'objects': f1}))
check(
    'a standard lobby stays parametric — no pack models at all',
    not k1.get('asset') and k1.get('sofa') == 2 and k1.get('armchair') == 2,
    k1,
)

# ── refusals ─────────────────────────────────────────────────────────────────
txt, _ = assistant('furnish_lobby', {'cell_from': 'C4', 'cell_to': 'F7'})
check('a 4 x 4 m block is refused', txt.startswith('refused') and '6 x 6' in txt, txt)
txt, _ = assistant('furnish_lobby', {'cell_from': 'C4', 'cell_to': 'L9', 'entrance_side': 'up'})
check('an unknown entrance side is refused', txt.startswith('refused'), txt)
txt, _ = assistant('furnish_lobby', {'cell_from': 'ZZ9', 'cell_to': 'L9'})
check('an off-grid cell is refused', txt.startswith('refused'), txt)

# ── the programme: an empty luxury lobby is not a lobby ──────────────────────
dp = A.Drawing({'objects': []})
dp.request = 'a luxurious 12-storey residential tower'
assistant('plan_building', {'use': 'residential', 'storeys': 12, 'cell_from': 'B3', 'cell_to': 'M10'}, drawing=dp)
check('the request is a luxury job', BP.get_program(dp)['finish_level'] == 'luxury', BP.get_program(dp)['finish_level'])
lb = {r['key']: r for r in BP.status(dp, BP.get_program(dp))}['lobby']
check('no lobby at all fails the item', not lb['ok'], lb['detail'])
assistant(
    'add_room', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'name': 'Lobby', 'door_side': 'south'}, drawing=dp
)
lb = {r['key']: r for r in BP.status(dp, BP.get_program(dp))}['lobby']
check(
    'a 10 m room with nothing in it still fails — and says so',
    not lb['ok'] and 'EMPTY' in lb['detail'] and 'furnish_lobby' in lb['detail'],
    lb['detail'],
)
assistant('furnish_lobby', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'entrance_side': 'south'}, drawing=dp)
lb = {r['key']: r for r in BP.status(dp, BP.get_program(dp))}['lobby']
check('the same room, furnished, passes', lb['ok'], lb['detail'])
check(
    'and the detail counts what it found',
    'furnished' in lb['detail'] and '2 desks' in lb['detail'] and '4 seats' in lb['detail'],
    lb['detail'],
)
how = {i['key']: i for i in BP.get_program(dp)['items']}['lobby']['how']
# 2026-09-16: the lobby item's how-line is a _macro() — when entrance_kit is loaded it
# names build_entrance(), the ONE call that draws the room, the door and this fit-out
# together, and only falls back to "add_room ... then furnish_lobby(...)" when the kit
# is absent. Either wording is the right instruction; what must never happen is a
# how-line that does not name a tool the model can actually call.
check('the how-line tells the model to call it', 'build_entrance(' in how or 'furnish_lobby(' in how, how)

# a standard-finish lobby is still satisfied by the room alone (no regression)
ds = A.Drawing({'objects': []})
assistant('plan_building', {'use': 'office', 'storeys': 4, 'cell_from': 'B3', 'cell_to': 'M10'}, drawing=ds)
assistant('add_room', {'cell_from': 'C4', 'cell_to': 'L9', 'storey': 0, 'name': 'Lobby'}, drawing=ds)
ls = {r['key']: r for r in BP.status(ds, BP.get_program(ds))}['lobby']
check('a standard lobby is not asked to be furnished', ls['ok'], ls['detail'])

# ── A/B: the whole entrance kit on a tower, and a picture of the result ──────
# The unit checks above prove the records; this proves the thing an operator
# actually sees. A luxury tower gets pack models, a standard one does not, and
# the lobby camera has to find something in the room.
import re  # noqa: E402
import shutil  # noqa: E402

DR = A.EXT_MODULES['design_rules']
EK = A.EXT_MODULES['entrance_kit']
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
os.makedirs(OUT, exist_ok=True)


def tower(style):
    """draw_box + plan_building + build_entrance, the acceptance sequence."""
    t = A.Drawing(None)
    t.request = 'a luxurious 6-storey residential tower' if style == 'luxury' else 'a plain 6-storey office block'
    A.call_tool(t, 'draw_box', dict(centre='FH100', width=20, depth=20, storeys=6, roof='flat', name='tower'))
    A.call_tool(
        t, 'plan_building', dict(use='residential', storeys=6, centre='FH100', width=20, depth=20, name='tower')
    )
    return t, A.call_tool(t, 'build_entrance', dict(group='tower', side='south', style=style))


tl, tltxt = tower('luxury')
lob = [o for o in tl.objs if str(o.get('grp') or '').endswith('fit-out')]
check('build_entrance draws a lobby fit-out on a luxury tower', len(lob) >= 12, (len(lob), str(tltxt)[:200]))
check('>= 2 sofa models in it', len(models(lob, LF.ASSET_SOFA)) >= 2, len(models(lob, LF.ASSET_SOFA)))
check('>= 2 armchair models in it', len(models(lob, LF.ASSET_ARMCHAIR)) >= 2, len(models(lob, LF.ASSET_ARMCHAIR)))
check('>= 4 potted plant models in it', len(models(lob, LF.ASSET_PLANT)) >= 4, len(models(lob, LF.ASSET_PLANT)))
ch = models(lob, LF.ASSET_CHANDELIER)
check('exactly one chandelier', len(ch) == 1, len(ch))
# the record's y is the HANG POINT, not the base: Chandelier_01_2k's geometry runs
# from -CHANDELIER_DROP to 0 in its own frame, so the bottom is y - drop * scale.
low = (ch[0]['y'] - LF.CHANDELIER_DROP * float(ch[0].get('s') or 1.0)) if ch else 0.0
check(
    'and its bottom is >= 2.2 m clear of the lobby floor',
    low >= LF.CHANDELIER_CLEAR - 1e-6,
    (round(low, 3), ch[0]['y'] if ch else None, ch[0].get('s') if ch else None),
)
parts = [o for o in tl.objs if o.get('kind') in ('partition', 'wall') and str(o.get('grp') or '').startswith('Lobby')]
check(
    'the lobby partitions are repainted acg_Plaster001',
    parts and all(o['mat'] == LF.LUX_WALL for o in parts),
    [(o['id'], o['mat']) for o in parts],
)

# design_check, scoped to the lobby as the brief asks: the rest of a 6-storey
# shell is unfinished on purpose and its programme errors are not this job's.
ids = {o['id'] for o in lob} | {o['id'] for o in parts}
find = DR.run_checks(tl)
mine = [f for f in find if any(i in f['text'] for i in ids)]
check(
    'no design error names a lobby record',
    [f for f in mine if f['sev'] == 'error'] == [],
    [f['text'][:150] for f in mine if f['sev'] == 'error'],
)
check(
    'and no clearance warning inside the lobby group',
    [f for f in mine if f['code'] == 'clearance'] == [],
    [f['text'][:150] for f in mine if f['code'] == 'clearance'],
)

ts, _tstxt = tower('standard')
slob = [o for o in ts.objs if str(o.get('grp') or '').endswith('fit-out')]
check(
    'a standard tower keeps the parametric fit-out',
    slob and not [o for o in slob if o['kind'] == 'asset'],
    sorted({o['kind'] for o in slob}),
)

# ── and the picture ──────────────────────────────────────────────────────────
BPW = A.EXT_MODULES.get('blender_power')
rep = BPW.t_present(tl, None, group='', engine='eevee', width=960, height=540)
ptxt = rep['text'] if isinstance(rep, dict) else str(rep)
m = re.search(r'^lobby: (\d+) visible', ptxt, re.M)
check('present() rendered a lobby view', m is not None, ptxt[:400])
nvis = int(m.group(1)) if m else 0
check(
    'the lobby camera sees >= 12 records (it was an empty concrete room)', nvis >= 12, (nvis, (m.group(0) if m else ''))
)
png = ''
for f in (tl.ext.get('presented') or {}).get('files') or []:
    if f.startswith('view-lobby-'):
        png = os.path.join(BPW.BLEND_DIR, f)
if png and os.path.exists(png):
    png = shutil.copy(png, os.path.join(OUT, 'lobby_luxury.png'))
check('and the frame was saved for a human to look at', bool(png) and os.path.exists(png), png)
print('    lobby render: ' + str(png))

finish()
