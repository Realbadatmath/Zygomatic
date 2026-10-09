# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_floor_layouts — a whole floor in one call, the typical floors in a
second, and the spec minimums enforced at the tool boundary."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, tool_names  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402

FL = A.EXT_MODULES['floor_layouts']
check('both tools are registered', {'layout_floor', 'repeat_floor'} <= set(tool_names()))

# ── one call = one floor ─────────────────────────────────────────────────────
txt, d = assistant('layout_floor', {'cell_from': 'K20', 'cell_to': 'X34', 'use': 'residential', 'storey': 1})
k = kinds_of(d)
check(
    'a corridor, units, doors and zones in ONE call',
    k.get('partition', 0) >= 4 and k.get('door', 0) >= 4 and k.get('zone', 0) >= 4,
    k,
)
# 2026-09-16: layout_floor now declares the CORRIDOR as a zone of its own, so the
# planning analyses and walk_rules read the circulation as a named space instead of
# inferring it from the gap between the partitions. That is one zone MORE than there
# are units, and it is named "corridor st<N>" with use="corridor", not "Apartment N.MM".
zones = [o for o in d.objs if o['kind'] == 'zone']
units = [o for o in zones if str(o['p'].get('use') or '') != 'corridor']
corr = [o for o in zones if str(o['p'].get('use') or '') == 'corridor']
check('every unit gets a zone the planning analyses can read', len(units) == k['door'], dict(k, unit_zones=len(units)))
check('the corridor is declared as a zone of its own', len(corr) == 1, [o['p'].get('name') for o in zones])
check('the reply says how to carry it up', 'repeat_floor' in txt, txt[:80])
check('zones carry a name and a use', all(o['p'].get('name') and o['p'].get('use') for o in zones))
check(
    'zones are named per storey',
    all(o['p']['name'].startswith('Apartment 1.') for o in units)
    and all(o['p']['name'].endswith(' st1') for o in corr),
    [o['p']['name'] for o in zones],
)
check('the corridor group is findable by the programme check', any('corridor' in (o.get('grp') or '') for o in d.objs))
rec = d.ext['floor_layouts']['1']
check('the layout is recorded on the document', rec['units'] == len(units) and rec['ids'], rec.get('units'))

# geometry means what the reply says
w = max(o['p']['len'] for o in d.objs if o['kind'] == 'partition')
check('the corridor walls run the full length of the plate', abs(w - 15.0) < 0.01, w)
check('the unit depth is the plate minus the corridor, halved', abs(rec['depth'] - (14 - 1.5) / 2) < 0.01, rec['depth'])

# ── the spec minimums are enforced HERE, not warned about later ──────────────
t, _ = assistant(
    'layout_floor', {'cell_from': 'K20', 'cell_to': 'X34', 'use': 'residential', 'storey': 2, 'corridor_w': 0.9}
)
check('a corridor under 1.2 m is REFUSED', t.startswith('refused:') and '1.2' in t, t[:90])
check('the refusal names the width to use instead', 'corridor_w=1.5' in t, t[:120])
t, _ = assistant('layout_floor', {'cell_from': 'K20', 'cell_to': 'M22', 'use': 'residential', 'storey': 2})
check('a plate too shallow for two unit bands is REFUSED', t.startswith('refused:') and 'at least' in t, t[:110])
t, _ = assistant('layout_floor', {'cell_from': 'K20', 'cell_to': 'X34', 'use': 'castle', 'storey': 2})
check('an unknown use is refused', t.startswith('refused:'), t[:60])

# a deep plate is built but the daylight problem is stated
t, dd = assistant('layout_floor', {'cell_from': 'A1', 'cell_to': 'AZ50', 'use': 'residential', 'storey': 0})
check('a plate too deep to daylight is flagged, not silently built', 'NOTE' in t and 'dark' in t, t[-140:])

# ── the typical floors ───────────────────────────────────────────────────────
before = len(d.objs)
t, _ = assistant('repeat_floor', {'from_storey': 2, 'to_storey': 5, 'source_storey': 1}, drawing=d)
per = before
check('four storeys copied in one call', len(d.objs) == before * 5, f'{before} -> {len(d.objs)}')
ys = sorted({round(o['y'], 2) for o in d.objs if o['kind'] == 'zone'})
check('each copy sits on its own storey', ys == [round(s * d.storey_h, 2) for s in range(1, 6)], ys)
check(
    'the copies are renumbered per storey',
    any(o['p'].get('name', '').startswith('Apartment 5.') for o in d.objs if o['kind'] == 'zone'),
    sorted({o['p'].get('name') for o in d.objs if o['kind'] == 'zone'})[:6],
)
check('groups are renumbered too', any('st5' in (o.get('grp') or '') for o in d.objs))

t, _ = assistant('repeat_floor', {'from_storey': 8, 'to_storey': 9, 'source_storey': 7}, drawing=d)
check('repeating a storey that was never laid out is refused', t.startswith('refused:') and 'no layout' in t, t[:90])
t, _ = assistant('repeat_floor', {'from_storey': 1, 'to_storey': 1, 'source_storey': 1}, drawing=d)
check('repeating a storey onto itself is refused', t.startswith('refused:'), t[:70])

# the object ceiling is refused with the number that DOES fit, not by silent truncation
big = A.Drawing({'objects': []})
assistant('layout_floor', {'cell_from': 'A1', 'cell_to': 'BZ60', 'use': 'hotel', 'storey': 0}, drawing=big)
t, _ = assistant('repeat_floor', {'from_storey': 1, 'to_storey': 120, 'source_storey': 0}, drawing=big)
check('the object ceiling refuses with a number that fits', t.startswith('refused:') and 'at a time' in t, t[:140])

# ── it composes with the programme ───────────────────────────────────────────
BP = A.EXT_MODULES['building_program']
_, d3 = assistant('plan_building', {'use': 'residential', 'storeys': 6, 'cell_from': 'K20', 'cell_to': 'X34'})
rows = {r['key']: r for r in BP.status(d3, BP.get_program(d3))}
check('the corridor item starts unbuilt', not rows['corridor']['ok'])
assistant('layout_floor', {'cell_from': 'K20', 'cell_to': 'X34', 'use': 'residential', 'storey': 1}, drawing=d3)
rows = {r['key']: r for r in BP.status(d3, BP.get_program(d3))}
check('layout_floor satisfies the corridor item', rows['corridor']['ok'], rows['corridor']['detail'])

# ── a copied opening is re-hosted on the wall of ITS OWN storey ──────────────
# 2026-09-16: a plan's windows are cut in the BUILDING's facade wall, and that
# wall is not one of the storey's own layout records, so the copy kept the
# storey-1 wall as its host. A storey-2 window then read as reaching 5.30 m up a
# wall that stops at 5.40 m from a floor at 2.70 m — open_off_wall, "the head is
# 2.60 m above the wall", eight of them on one replayed tower, every one of them
# an artefact of the copy.
_t, dh = assistant(
    'draw_box', {'centre': 'FH100', 'width': 20, 'depth': 20, 'storeys': 3, 'roof': 'flat', 'name': 'tower'}
)
SH = dh.storey_h
FAC = [o for o in dh.objs if o['kind'] in ('wall', 'curtain_wall')]
LOW = [o for o in FAC if abs(o['y'] - SH) < 0.05]
TWINS = [
    o
    for o in FAC
    if LOW and abs(o['y'] - 2 * SH) < 0.05 and abs(o['x'] - LOW[0]['x']) < 0.05 and abs(o['z'] - LOW[0]['z']) < 0.05
]
check(
    '(host) the box gives every storey its own facade wall on the same line',
    bool(LOW) and bool(TWINS),
    sorted({round(o['y'], 2) for o in FAC}),
)
host1, twin2 = LOW[0], TWINS[0]
win = dh.new(
    'window',
    {'w': 1.2, 'h': 1.4, 'sill': 0.9},
    host1['x'],
    host1['z'],
    host1['y'],
    host1.get('ry') or 0.0,
    'mat_plaster',
    name='plan window st1',
    grp='plan st1',
)
win.setdefault('meta', {})['host'] = host1['id']
dh.ext.setdefault('floor_layouts', {})['1'] = {'use': 'plan', 'ids': [win['id']], 'units': 0}

nb = len(dh.objs)
rt = A.call_tool(dh, 'repeat_floor', {'from_storey': 2, 'to_storey': 2, 'source_storey': 1})
check('(host) repeat_floor carries the window up', not rt.startswith('refused:'), rt[:120])
cp = dh.objs[nb:]
check(
    '(host-A) the copy stands one storey above the wall that hosted the original',
    len(cp) == 1 and abs(cp[0]['y'] - (host1['y'] + SH)) < 0.02,
    (len(cp), cp and round(cp[0]['y'], 2), round(host1['y'], 2)),
)
check(
    '(host-B) so its host is the facade wall of ITS OWN storey, not the one below',
    len(cp) == 1 and (cp[0].get('meta') or {}).get('host') == twin2['id'],
    (
        (cp[0].get('meta') or {}).get('host') if cp else None,
        f'wanted {twin2["id"]} at y={twin2["y"]}, not {host1["id"]} at y={host1["y"]}',
    ),
)

finish()
