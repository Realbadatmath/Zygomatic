# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_openings_special.py — the openings_special family's proof.

"${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_openings_special.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import (
    check,
    finish,
    assistant,
    kinds_of,
    browser_kinds,
    blender_kinds,  # noqa: E402
    rail_has,
    tool_names,
    URL,
)  # noqa: F401

KINDS = [
    'window_arch',
    'window_round',
    'window_bay',
    'window_strip',
    'door_garage',
    'door_sliding',
    'door_french',
    'curtain_wall',
]

# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check('tools registered', all(t in names for t in ('add_special_openings', 'add_curtain_wall', 'add_garage')), names)

# a 6 x 6 m box, 4 storeys -> 16 walls of 6 m; arched windows every 2 storeys
txt, d = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'H9', 'storeys': 4, 'roof': 'none'})
check('box drew 16 walls', kinds_of(d).get('wall') == 16, kinds_of(d))
txt, d = assistant(
    'add_special_openings', {'walls': 'new', 'kind': 'window_arch', 'every_n_storeys': 2, 'per_wall': 1}, drawing=d
)
check('one arched window per wall on storeys 0 and 2', kinds_of(d).get('window_arch') == 8, (txt, kinds_of(d)))
st = sorted({round(o['y'] / 2.7) for o in d.objs if o['kind'] == 'window_arch'})
check('...and on those storeys only', st == [0, 2], st)
arch = [o for o in d.objs if o['kind'] == 'window_arch'][0]
check('arch rise defaults to w/2', abs(arch['p']['arch'] - arch['p']['w'] / 2) < 1e-6, arch['p'])

walls = [o for o in d.objs if o['kind'] == 'wall']
off = 0
for w in [o for o in d.objs if o['kind'] == 'window_arch']:
    hit = False
    for wl in walls:
        if abs(wl['y'] - w['y']) > 1e-6:
            continue
        L = wl['p']['len']
        c, s = math.cos(-wl['ry']), math.sin(-wl['ry'])
        dx, dz = w['x'] - wl['x'], w['z'] - wl['z']
        lx, lz = dx * c - dz * s, dx * s + dz * c
        if abs(lx) <= L / 2 and abs(lz) < 1e-6:
            hit = True
            break
    off += not hit
check('arched windows on their walls', off == 0, off)

txt, d = assistant('add_special_openings', {'walls': 'all', 'kind': 'window_oval'}, drawing=d)
check('unknown opening kind refused', txt.startswith('refused'), txt)
txt, d = assistant('add_special_openings', {'walls': 'roof_flat', 'kind': 'window_round'}, drawing=d)
check('no matching walls refused', txt.startswith('refused'), txt)

# window_round carries the square hole next to r
txt, d2 = assistant('draw_wall', {'cell_from': 'C4', 'cell_to': 'K4'})
wid = d2.objs[-1]['id']
txt, d2 = assistant(
    'add_special_openings', {'walls': [wid], 'kind': 'window_round', 'width': 0.8, 'sill': 2.0}, drawing=d2
)
rnd = d2.objs[-1]
check(
    'round window: r = width/2 and w = h = 2r',
    rnd['kind'] == 'window_round' and rnd['p']['r'] == 0.4 and rnd['p']['w'] == 0.8 and rnd['p']['h'] == 0.8,
    rnd['p'],
)

# add_garage
txt, d2 = assistant('add_garage', {'wall_id': wid, 'width': 2.5}, drawing=d2)
gar = d2.objs[-1]
check('garage door in the wall', gar['kind'] == 'door_garage' and gar['p']['w'] == 2.5 and gar['p']['panels'] == 4, txt)
check(
    'garage door on the wall line',
    abs(gar['z'] - d2.find(wid)['z']) < 1e-6 and abs(gar['ry'] - d2.find(wid)['ry']) < 1e-9,
    (gar, txt),
)
txt, d2 = assistant('add_garage', {'wall_id': rnd['id']}, drawing=d2)
check('garage refused on a non-wall', txt.startswith('refused'), txt)

# add_curtain_wall replaces the walls and takes their openings with them
txt, d3 = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'H9', 'storeys': 1, 'roof': 'none'})
w0 = [o for o in d3.objs if o['kind'] == 'wall']
txt, d3 = assistant('add_special_openings', {'walls': 'new', 'kind': 'window_arch'}, drawing=d3)
for o in d3.objs:  # the tab sets p.host; do it here so the sweep has something to find
    if o['kind'] == 'window_arch':
        o['p']['host'] = w0[0]['id']
txt, d3 = assistant('add_curtain_wall', {'walls': [w['id'] for w in w0], 'mullion': 1.5, 'transom': 1.2}, drawing=d3)
k3 = kinds_of(d3)
check('4 walls became 4 curtain walls', k3.get('curtain_wall') == 4 and 'wall' not in k3, (txt, k3))
check('hosted openings went with them', k3.get('window_arch') is None, k3)
cw = [o for o in d3.objs if o['kind'] == 'curtain_wall']
check(
    'curtain wall keeps len/h/x/z/ry of its wall',
    all(
        abs(c['p']['len'] - w['p']['len']) < 1e-6
        and abs(c['p']['h'] - w['p']['h']) < 1e-6
        and abs(c['x'] - w['x']) < 1e-6
        and abs(c['z'] - w['z']) < 1e-6
        and abs(c['ry'] - w['ry']) < 1e-9
        for c, w in zip(cw, w0)
    ),
    [(c['p'], c['x'], c['z']) for c in cw],
)
check('curtain walls are glass', all(c['mat'] == 'mat_glass' for c in cw), [c['mat'] for c in cw])
txt, d3 = assistant('add_curtain_wall', {'walls': 'curtain_wall'}, drawing=d3)
check('nothing to glaze refused', txt.startswith('refused'), txt)

txt, d3 = assistant('add_object', {'kind': 'curtain_wall', 'cell': 'A1', 'params': {'len': 9}}, drawing=d3)
check('add_object knows curtain_wall', d3.objs[-1]['kind'] == 'curtain_wall' and d3.objs[-1]['p']['len'] == 9, txt)
missing = rail_has(KINDS)
check('rail lists every new kind', missing == [], missing)

# ── the entrance replay (job 71ac02b0) ────────────────────────────────────────
# The screenshot showed the entrance as a small tan panel BEHIND the glass. The
# door must survive add_curtain_wall, stay in its host wall's plane, and nothing
# glazed may stand in front of it.
print('the entrance replay (job 71ac02b0)')


def covers(w, x, z, tol=0.6):
    """Does w's plan segment pass within tol of (x, z)?"""
    cs, sn = math.cos(-w['ry']), math.sin(-w['ry'])
    dx, dz = x - w['x'], z - w['z']
    lx, lz = dx * cs - dz * sn, dx * sn + dz * cs
    return abs(lz) <= tol and abs(lx) <= w['p'].get('len', 4) / 2 + 0.05


txt, e = assistant(
    'draw_box',
    {
        'centre': 'FH100',
        'width': 20,
        'depth': 20,
        'storeys': 20,
        'roof': 'flat',
        'material': 'pht_rough_concrete',
        'name': 'tower',
    },
)
txt, e = assistant(
    'add_opening',
    {'group': 'tower', 'side': 'south', 'storey': 0, 'kind': 'double_door', 'width': 2.4, 'height': 3},
    drawing=e,
)
host0 = [o for o in e.objs if o['kind'] == 'wall' and o['name'] == 'south wall st0'][0]
txt, e = assistant(
    'add_canopy', {'group': 'tower', 'side': 'south', 'storey': 0, 'width': 12, 'depth': 5, 'height': 4.2}, drawing=e
)
glz, e = assistant(
    'add_curtain_wall',
    {
        'walls': 'tower',
        'storeys': [0, 2, 4, 6, 8, 10, 12, 14, 16, 18],
        'mullion': 1.5,
        'transom': 1.35,
        'name': 'tower_glazing',
    },
    drawing=e,
)
doors = [o for o in e.objs if o['kind'] == 'double_door']
check('after the replay there is still exactly one door record', len(doors) == 1, (glz, len(doors)))
door = doors[0]
host = e.find(host0['id'])
check('its host wall survived add_curtain_wall as a wall', host is not None and host['kind'] == 'wall', host)
check('...turned mat_glass, not left in concrete', host['mat'] == 'mat_glass', host['mat'])
check(
    'the door is in the host wall plane (within 0.15 m)',
    ((door['x'] - host['x']) ** 2 + (door['z'] - host['z']) ** 2) ** 0.5 <= 0.15
    and abs(door['ry'] - host['ry']) < 1e-9,
    (door['x'], door['z'], host['x'], host['z']),
)
front = [
    o
    for o in e.objs
    if o['kind'] in ('curtain_wall', 'panel') and covers(o, door['x'], door['z']) and abs(o['y'] - door['y']) < 2.69
]
check('no curtain wall or panel stands in front of the door', front == [], [(o['id'], o['x'], o['z']) for o in front])
check(
    "the kept wall carries NO mullion/transom keys (the tab's wall builder cannot draw them)",
    'mullion' not in host['p'] and 'transom' not in host['p'],
    host['p'],
)
check('...and the reply says so instead of pretending it is glazed', 'mullion grid' in glz and host['id'] in glz, glz)
check('the other 39 walls did become curtain walls', kinds_of(e).get('curtain_wall') == 39, kinds_of(e))

# a second wall standing in the same face at the same storey must not be glazed
# over the door either — that is exactly a pane in front of the entrance.
liner = e.new(
    'wall',
    {'len': 20.0, 'h': 2.7, 't': 0.1},
    host['x'],
    host['z'] + 0.2,
    host['y'],
    host['ry'],
    'mat_plaster',
    name='south liner st0',
    grp='tower',
)
gl2, e = assistant('add_curtain_wall', {'walls': [liner['id'], host['id']], 'mullion': 1.5, 'transom': 1.35}, drawing=e)
check(
    'a coincident wall at the door is kept too, never glazed over the entrance',
    e.find(liner['id']) is not None and e.find(liner['id'])['kind'] == 'wall' and kinds_of(e).get('curtain_wall') == 39,
    (gl2, kinds_of(e)),
)

# keep_doors=False is still the explicit opt-out
txt, f = assistant('draw_box', {'cell_from': 'C4', 'cell_to': 'H9', 'storeys': 1, 'roof': 'none'})
fw = [o for o in f.objs if o['kind'] == 'wall'][0]['id']
txt, f = assistant('add_opening', {'wall_id': fw, 'kind': 'door'}, drawing=f)
f.objs[-1]['p']['host'] = fw  # the tab sets p.host; the sweep needs it
txt, f = assistant('add_curtain_wall', {'walls': 'all', 'keep_doors': False}, drawing=f)
check(
    'keep_doors=false glazes the door wall as before',
    kinds_of(f).get('curtain_wall') == 4 and 'wall' not in kinds_of(f) and 'door' not in kinds_of(f),
    (txt, kinds_of(f)),
)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'window_arch', 'p': {'w': 1.2, 'h': 1.4, 'sill': 0.9, 'arch': 0.6}},
    {'kind': 'window_round', 'p': {'r': 0.6, 'sill': 1.2, 'w': 1.2, 'h': 1.2}},
    {'kind': 'window_bay', 'p': {'w': 2.4, 'h': 1.4, 'sill': 0.9, 'depth': 0.8}},
    {'kind': 'window_strip', 'p': {'w': 8, 'h': 1.0, 'sill': 1.1}},
    {'kind': 'door_garage', 'p': {'w': 2.5, 'h': 2.2, 'panels': 4}},
    {'kind': 'door_sliding', 'p': {'w': 2.4, 'h': 2.1}},
    {'kind': 'door_french', 'p': {'w': 1.6, 'h': 2.1}},
    {'kind': 'curtain_wall', 'p': {'len': 6, 'h': 2.7, 'mullion': 1.5, 'transom': 1.2, 't': 0.15}},
]
WANT = {
    'window_arch': (1.32, 2.12, 0.16),
    'window_round': (1.32, 1.32, 0.16),
    'window_bay': (2.46, 1.40, 0.86),
    'window_strip': (8.12, 1.12, 0.16),
    'door_garage': (2.62, 2.26, 0.16),
    'door_sliding': (2.52, 2.16, 0.16),
    'door_french': (1.72, 2.16, 0.16),
    'curtain_wall': (6.00, 2.70, 0.15),
}
b = browser_kinds(cases)
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
for r in b:
    want = WANT[r['kind']]
    ok = r['ok'] and r['registered'] and all(abs(r['size'][i] - want[i]) < 0.03 for i in range(3))
    check(f'{r["kind"]} builds, sized {want[0]:g} x {want[1]:g} x {want[2]:g}', ok, r)
cwr = [r for r in b if r['kind'] == 'curtain_wall'][0]
check('curtain wall is a grid (parts >= 1)', cwr['parts'] >= 1, cwr['parts'])
check(
    'labels',
    [r['label'] for r in b]
    == [
        'Arched window',
        'Round window',
        'Bay window',
        'Strip window',
        'Garage door',
        'Sliding door',
        'French doors',
        'Curtain wall',
    ],
    [r['label'] for r in b],
)

# the openings really cut their host wall (the studio's own arSyncHoles)
HOLE_SCRIPT = r"""
() => {
  const wall = arNewObj('wall', {len: 6, h: 2.7, t: 0.24}, 0, 0, 0);
  const win  = arNewObj('window_arch', {w: 1.2, h: 1.4, sill: 0.9}, 0, 0, 0);
  arSyncHoles();
  return {holes: (wall.p.holes || []).length, host: win.p.host, wall: wall.id,
          is_opening: arIsOpening('window_arch'), curtain_is_opening: arIsOpening('curtain_wall')};
}
"""


def hole_probe(timeout_s=120):
    from playwright.sync_api import sync_playwright

    errs = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(channel='chrome', args=['--enable-unsafe-swiftshader', '--disable-gpu-sandbox'])
        page = browser.new_page(viewport={'width': 1400, 'height': 900})
        page.on('pageerror', lambda e: errs.append(str(e)))
        page.on('dialog', lambda d: d.accept())
        page.goto(URL, wait_until='domcontentloaded', timeout=timeout_s * 1000)
        page.wait_for_function('typeof goToView === "function"', timeout=timeout_s * 1000)
        page.evaluate('goToView("architecture")')
        page.wait_for_function('typeof AR !== "undefined" && AR.built', timeout=timeout_s * 1000)
        page.evaluate('AR.shadows=false; AR.renderer.shadowMap.enabled=false; AR.sun.castShadow=false;')
        out = page.evaluate(HOLE_SCRIPT)
        browser.close()
    out['page_errors'] = errs[:3]
    return out


hp = hole_probe()
check('arSyncHoles cuts exactly one hole for a window_arch', hp['holes'] == 1, hp)
check('...hosted by that wall', hp['host'] == hp['wall'], hp)
check('the openings are openings, the curtain wall is not', hp['is_opening'] and not hp['curtain_is_opening'], hp)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
bl = blender_kinds(cases)
for k in KINDS:
    check(f'blender builds {k}', bl.get(k, {}).get('polys', 0) > 0, bl.get(k))
# ── add_curtain_wall keeps a wall's base level (head house on a deck, 2026-09-16) ──
from zyg_workflows import arch_assistant as A  # noqa: E402

if not A.EXT_MODULES:
    A.load_extensions()
d_b = A.Drawing(None)
w_b = d_b.new(
    'wall',
    {'len': 4.6, 'h': 2.7, 't': 0.24, 'base': 54.3},
    0.0,
    0.0,
    54.3,
    0.0,
    'mat_concrete',
    name='south wall head house',
    grp='tower head house',
)
r_b = A.call_tool(d_b, 'add_curtain_wall', dict(walls=[w_b['id']]))
cw_b = [o for o in d_b.objs if o['kind'] == 'curtain_wall']
check(
    'add_curtain_wall on a wall with a base level makes a curtain wall with the SAME base',
    len(cw_b) == 1 and cw_b[0]['p'].get('base') == 54.3 and cw_b[0]['grp'] == 'tower head house',
    (r_b[:80], [o['p'] for o in cw_b]),
)
w_c = d_b.new('wall', {'len': 4.6, 'h': 2.7, 't': 0.24}, 10.0, 0.0, 0.0, 0.0, 'mat_concrete', grp='x')
A.call_tool(d_b, 'add_curtain_wall', dict(walls=[w_c['id']]))
check(
    '... and a wall without one stays without one',
    all('base' not in o['p'] for o in d_b.objs if o['grp'] == 'x'),
    [o['p'] for o in d_b.objs if o['grp'] == 'x'],
)

finish()
