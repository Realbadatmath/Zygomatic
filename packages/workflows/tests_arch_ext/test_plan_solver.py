#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_plan_solver.py — the generated-plan solver.

12 seeds x 4 sizes are laid out and checked against the plan JSON schema (the
same `validate` the pack contract uses), against the solver's own hard
constraints (min width, aspect, a window wall for every habitable room, a door
for every room, reachability from the hall) and against the swiss_dwellings
area medians. Then the assistant tool is run for real: it must write a plan
file under ZYG_PLANS_DIR/generated and name place_plan in its reply.

Run:  ZYG_PLANS_DIR=tests_arch_ext/fixtures/plans "../.venv/bin/python" \
          tests_arch_ext/test_plan_solver.py
"""

from __future__ import annotations

import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)
sys.path.insert(0, HERE)

os.environ.setdefault('ZYG_PLANS_DIR', os.path.join(HERE, 'fixtures', 'plans'))

from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402
from test_plan_packs import validate  # noqa: E402
from zyg_workflows import arch_assistant as A  # noqa: E402
import zyg_workflows.arch_assistant_ext.plan_solver as PS  # noqa: E402

A.load_extensions()

SIZES = [(6, 9), (8, 11), (12, 9), (20, 10)]
SEEDS = list(range(12))


def rect(pts):
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    return min(xs), max(xs), min(zs), max(zs)


def edges(pts):
    """Axis-aligned polygon edges as (axis, coord, lo, hi) — works for the
    hall's T as well as for a plain rectangular room."""
    out = []
    for i, (ax, az) in enumerate(pts):
        bx, bz = pts[(i + 1) % len(pts)]
        if abs(ax - bx) < 1e-6 and abs(az - bz) > 1e-6:
            out.append(('x', ax, min(az, bz), max(az, bz)))
        elif abs(az - bz) < 1e-6 and abs(ax - bx) > 1e-6:
            out.append(('z', az, min(ax, bx), max(ax, bx)))
    return out


def shared_len(a, b):
    """The longest wall segment two room polygons have in common."""
    best = 0.0
    for axis, c, lo, hi in edges(a):
        for axis2, c2, lo2, hi2 in edges(b):
            if axis == axis2 and abs(c - c2) < 1e-3:
                best = max(best, min(hi, hi2) - max(lo, lo2))
    return best


print('plan_solver — stats + layout')
st_path = os.path.join(PS.plans_root(), 'swiss_dwellings', 'stats.json')
check('stats.json found under ZYG_PLANS_DIR', os.path.isfile(st_path), st_path)
check(
    'room medians read from the pack stats',
    abs(PS.median_area('bedroom') - 13.781) < 1e-6 and abs(PS.median_area('living') - 23.983) < 1e-6,
    (PS.median_area('bedroom'), PS.median_area('living')),
)

plans = {}
gen_err = []
for w, d in SIZES:
    for s in SEEDS:
        try:
            plans[(w, d, s)] = PS.generate_unit(w, d, seed=s)
        except Exception as exc:  # noqa: BLE001
            gen_err.append(f'{w}x{d} seed {s}: {exc}')
check(
    '12 seeds x 4 sizes all produce a plan (%d)' % len(plans),
    len(plans) == len(SIZES) * len(SEEDS) and not gen_err,
    '; '.join(gen_err[:4]),
)

bad = []
for key, p in plans.items():
    for msg in validate(p, 'generated'):
        bad.append(f'{key}: {msg}')
check('every plan validates against the plan JSON schema', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    for r in p['rooms']:
        x0, x1, z0, z1 = rect(r['pts'])
        if r['type'] == 'hall':
            continue
        if min(x1 - x0, z1 - z0) < PS.MIN_W.get(r['type'], 1.1) - 1e-6:
            bad.append(f'{key}: {r["type"]} min width {min(x1 - x0, z1 - z0):.2f}')
        if max(x1 - x0, z1 - z0) > PS.ASPECT * min(x1 - x0, z1 - z0) + 1e-6:
            bad.append(f'{key}: {r["type"]} aspect')
check('every room holds its minimum width and aspect <= 2.6', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    for r in p['rooms']:
        if r['type'] not in PS.HABITABLE:
            continue
        x0, x1, z0, z1 = rect(r['pts'])
        edge = 0.0
        if abs(z0) < 1e-6 or abs(z1 - p['d']) < 1e-6:
            edge = max(edge, x1 - x0)
        if abs(x0) < 1e-6 or abs(x1 - p['w']) < 1e-6:
            edge = max(edge, z1 - z0)
        if edge < PS.WIN_W - 1e-6:
            bad.append(f'{key}: {r["type"]} has no boundary edge')
check('every habitable room has an outside wall for a window', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    hosts = [i for i, r in enumerate(p['rooms']) if r['type'] in ('hall', 'living')]
    for i, r in enumerate(p['rooms']):
        if r['type'] == 'hall':
            continue
        if not any(j != i and shared_len(r['pts'], p['rooms'][j]['pts']) >= PS.TOUCH for j in hosts):
            bad.append(f'{key}: {r["type"]} touches neither hall nor living')
check('every room shares a door-wide edge with the hall or the living room', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    n_hall = sum(1 for r in p['rooms'] if r['type'] == 'hall')
    if len(p['doors']) < len(p['rooms']) - n_hall + 1:
        bad.append(f'{key}: {len(p["doors"])} doors for {len(p["rooms"])} rooms')
    if sum(1 for dr in p['doors'] if dr['kind'] == 'entrance') != 1:
        bad.append(f'{key}: not exactly one entrance door')
    e = p['entrance']
    on_edge = abs(e['z']) < 1e-3 or abs(e['z'] - p['d']) < 1e-3 or abs(e['x']) < 1e-3 or abs(e['x'] - p['w']) < 1e-3
    if not on_edge:
        bad.append(f'{key}: entrance {e} not on the boundary')
check('every room has a door, and the front door sits on the boundary', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    reach = {i for i, r in enumerate(p['rooms']) if r['type'] == 'hall'}
    for _ in range(len(p['rooms'])):
        for i, r in enumerate(p['rooms']):
            if i in reach:
                continue
            if any(
                shared_len(r['pts'], p['rooms'][j]['pts']) >= PS.TOUCH and p['rooms'][j]['type'] in ('hall', 'living')
                for j in reach
            ):
                reach.add(i)
    if len(reach) != len(p['rooms']):
        bad.append(f'{key}: {len(p["rooms"]) - len(reach)} rooms unreachable')
check('every room is reachable from the hall', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    ks = [r for r in p['rooms'] if r['type'] == 'kitchen']
    lv = [r for r in p['rooms'] if r['type'] == 'living']
    for k in ks:
        if lv and not any(shared_len(k['pts'], l['pts']) >= PS.TOUCH for l in lv):
            bad.append(f'{key}: kitchen not adjacent to the living room')
check('the kitchen always adjoins the living room', not bad, '; '.join(bad[:6]))

meds = {}
for (w, d, s), p in plans.items():
    prog = [r['type'] for r in p['rooms']]
    scale = (w * d) / sum(PS.median_area(t) for t in prog)
    err = [abs(r['area'] - PS.median_area(r['type']) * scale) / (PS.median_area(r['type']) * scale) for r in p['rooms']]
    meds[(w, d, s)] = statistics.median(err)
worst = max(meds.items(), key=lambda kv: kv[1])
check(
    'area error median < 25 %% of the stats medians on every plan (worst %.3f at %s)' % (worst[1], worst[0]),
    worst[1] < 0.25,
    worst,
)
check(
    'area error median over all 48 plans < 20 %% (%.3f)' % statistics.median(meds.values()),
    statistics.median(meds.values()) < 0.20,
)

bad = []
for key, p in plans.items():
    ext = [wl for wl in p['walls'] if wl['ext']]
    inn = [wl for wl in p['walls'] if not wl['ext']]
    if len(ext) != 4 or any(abs(wl['t'] - 0.24) > 1e-9 for wl in ext):
        bad.append(f'{key}: {len(ext)} boundary walls')
    if not inn or any(abs(wl['t'] - 0.1) > 1e-9 for wl in inn):
        bad.append(f'{key}: internal walls t != 0.1')
    seen = {(tuple(wl['a']), tuple(wl['b'])) for wl in inn}
    if len(seen) != len(inn):
        bad.append(f'{key}: duplicate internal walls')
check('walls: 4 boundary walls at t 0.24 plus deduped internal lines at t 0.1', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    for r in p['rooms']:
        if r['type'] not in PS.HABITABLE:
            continue
        x0, x1, z0, z1 = rect(r['pts'])
        n = sum(1 for wd in p['windows'] if x0 - 0.01 <= wd['x'] <= x1 + 0.01 and z0 - 0.01 <= wd['z'] <= z1 + 0.01)
        if n < 1:
            bad.append(f'{key}: {r["type"]} has no window')
    for wd in p['windows']:
        if abs(wd['sill'] - 0.9) > 1e-9 or abs(wd['h'] - 1.4) > 1e-9:
            bad.append(f'{key}: window sill/h {wd["sill"]}/{wd["h"]}')
check('every habitable room gets at least one 1.2 m window at sill 0.9', not bad, '; '.join(bad[:6]))

bad = []
for key, p in plans.items():
    baths = [r for r in p['rooms'] if r['type'] == 'bathroom']
    for b in baths:
        x0, x1, z0, z1 = rect(b['pts'])
        got = {
            f['kind'] for f in p['fixtures'] if x0 - 0.01 <= f['x'] <= x1 + 0.01 and z0 - 0.01 <= f['z'] <= z1 + 0.01
        }
        if not {'toilet', 'washbasin'} <= got:
            bad.append(f'{key}: bathroom fixtures {sorted(got)}')
        if b['area'] >= 4.0 and not ({'shower', 'bathtub'} & got):
            bad.append(f'{key}: bathroom {b["area"]} m2 without shower/bathtub')
    if any(r['type'] == 'kitchen' for r in p['rooms']) and not any(f['kind'] == 'kitchen' for f in p['fixtures']):
        bad.append(f'{key}: no kitchen fixture')
check('bathrooms get toilet + washbasin (+ shower/bath >= 4 m2), kitchens a run', not bad, '; '.join(bad[:6]))

again = PS.generate_unit(12, 9, seed=3)
check(
    'the same size and seed give byte-identical JSON',
    json.dumps(again, sort_keys=True) == json.dumps(plans[(12, 9, 3)], sort_keys=True),
    again['id'],
)
check(
    'a different seed gives a different layout',
    json.dumps(plans[(12, 9, 4)], sort_keys=True) != json.dumps(plans[(12, 9, 3)], sort_keys=True),
)
check(
    'the id is a stable gen_<hash>',
    again['id'] == plans[(12, 9, 3)]['id'] and again['id'].startswith('gen_') and len(again['id']) == 16,
    again['id'],
)

sides = {}
for side in ('north', 'south', 'east', 'west'):
    q = PS.generate_unit(10, 12, entrance=side, seed=5)
    sides[side] = q['entrance']['side']
    if not validate(q, 'generated'):
        pass
check(
    'all four entrance sides lay out and are recorded',
    sides == {s: s for s in ('north', 'south', 'east', 'west')},
    sides,
)

h = PS.generate_house(12, 10, seed=2)
check(
    'generate_house gives a house with 3 bedrooms, a wc and a storage',
    h['kind'] == 'house'
    and sum(1 for r in h['rooms'] if r['type'] == 'bedroom') == 3
    and {'wc', 'storage'} <= {r['type'] for r in h['rooms']},
    [r['type'] for r in h['rooms']],
)
check('the house plan validates too', not validate(h, 'generated'), validate(h, 'generated'))

print('plan_solver — the family contract')
check(
    'PROMPT is one paragraph <= 700 chars (%d)' % len(PS.PROMPT),
    len(PS.PROMPT) <= 700 and '\n' not in PS.PROMPT.strip(),
)
check(
    'EXAMPLES >= 2 and every call names a tool of this family',
    len(PS.EXAMPLES) >= 2 and all(c['tool'] in ('plan_unit', 'plan_house') for e in PS.EXAMPLES for c in e['calls']),
    len(PS.EXAMPLES),
)
check('both tools are registered with the assistant', {'plan_unit', 'plan_house'} <= {t['name'] for t in A.TOOL_DEFS})

print('plan_solver — the tool writes the generated pack')
pack = PS.pack_dir()
d0 = A.Drawing({'objects': []})
txt = A.call_tool(d0, 'plan_unit', {'width': 9, 'depth': 11, 'entrance': 'north', 'seed': 7})
check('plan_unit answers without refusing', not txt.startswith('refused:'), txt)
pid = txt.split(' ')[0]
fp = os.path.join(pack, 'plans', pid + '.json')
check('plan_unit wrote %s under ZYG_PLANS_DIR/generated' % (pid + '.json'), os.path.isfile(fp), fp)
check('the reply tells the model to place it with place_plan', 'place_plan' in txt, txt)
on_disk = json.load(open(fp))
check(
    'the written plan validates against the schema', not validate(on_disk, 'generated'), validate(on_disk, 'generated')
)

txt2 = A.call_tool(d0, 'plan_house', {'width': 12, 'depth': 10, 'entrance': 'south', 'seed': 4})
check(
    'plan_house answers without refusing and names place_plan',
    not txt2.startswith('refused:') and 'place_plan' in txt2,
    txt2,
)
hid = txt2.split(' ')[0]
check('plan_house wrote its file too', os.path.isfile(os.path.join(pack, 'plans', hid + '.json')), hid)

man = json.load(open(os.path.join(pack, 'pack.json')))
idx = json.load(open(os.path.join(pack, 'index.json')))
ids = {r['id'] for r in idx['rows']}
disk = {f[:-5] for f in os.listdir(os.path.join(pack, 'plans')) if f.endswith('.json')}
check(
    'pack.json carries pack/title/licence/attribution',
    all(man.get(k) for k in ('pack', 'title', 'licence', 'attribution')) and man['pack'] == 'generated',
    man.get('licence'),
)
check(
    'index.json rows match the files on disk',
    ids == disk,
    f'index-only {sorted(ids - disk)[:3]}, disk-only {sorted(disk - ids)[:3]}',
)
check(
    'the manifest counts match the rows',
    man['count'] == {k: sum(1 for r in idx['rows'] if r['kind'] == k) for k in ('unit', 'floor', 'house')},
    man['count'],
)
row = next(r for r in idx['rows'] if r['id'] == pid)
check(
    'the index row is the compact schema row',
    all(k in row for k in ('id', 'kind', 'w', 'd', 'area', 'n_rooms', 'types', 'entrance', 'fill'))
    and row['n_rooms'] == len(on_disk['rooms']),
    row,
)

check(
    'a bad entrance is refused with the call that works',
    A.call_tool(d0, 'plan_unit', {'width': 9, 'depth': 11, 'entrance': 'up'}).startswith('refused:'),
)
check(
    'an unknown room type is refused',
    A.call_tool(d0, 'plan_unit', {'width': 9, 'depth': 11, 'rooms': 'garage'}).startswith('refused:'),
)
check(
    'an impossible rectangle is refused, not crashed',
    A.call_tool(d0, 'plan_unit', {'width': 3, 'depth': 3}).startswith('refused:'),
)

finish()
