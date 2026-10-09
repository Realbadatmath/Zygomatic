#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""test_plan_packs.py — the plan-pack contract.

Every pack directory under ZYG_PLANS_DIR (default
data/architecture/plans) and under tests_arch_ext/fixtures/plans is checked:

  · pack.json parses and carries a licence + an attribution line
  · index.json rows match the files on disk
  · 20 random plans validate against the plan JSON schema
  · the swiss_dwellings pack holds >= 10,000 units and >= 500 floors
    (that count assertion is SKIPped with a printed line when the big pack is
    absent — the fixtures always run)

Run:  "../.venv/bin/python" tests_arch_ext/test_plan_packs.py
"""

from __future__ import annotations

import json
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
sys.path.insert(0, CREWS)
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

PACKS_DIR = os.environ.get('ZYG_PLANS_DIR', os.path.join(CREWS, 'data', 'architecture', 'plans'))
FIXTURES_DIR = os.path.join(HERE, 'fixtures', 'plans')

ROOM_TYPES = {
    'living',
    'kitchen',
    'bedroom',
    'bathroom',
    'wc',
    'hall',
    'corridor',
    'storage',
    'balcony',
    'stair',
    'lift',
    'shaft',
    'other',
}
FIXTURE_KINDS = {'toilet', 'washbasin', 'bathtub', 'shower', 'kitchen', 'sink'}
DOOR_KINDS = {'door', 'entrance', 'sliding'}
SIDES = {'north', 'south', 'east', 'west'}
KINDS = {'unit', 'floor', 'house'}
OPEN_LICENCES = ('CC BY', 'CC0', 'Apache', 'BSD', 'MIT', 'ODbL')
SAMPLE = 20


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pts_ok(pts, n=3):
    return (
        isinstance(pts, list)
        and len(pts) >= n
        and all(isinstance(p, list) and len(p) == 2 and _num(p[0]) and _num(p[1]) for p in pts)
    )


def validate(plan, pack_name):
    """Return a list of schema violations for one plan dict."""
    bad = []

    def need(cond, msg):
        if not cond:
            bad.append(msg)

    for k in (
        'id',
        'pack',
        'kind',
        'w',
        'd',
        'area',
        'storey_h',
        'boundary',
        'rooms',
        'walls',
        'doors',
        'windows',
        'fixtures',
        'entrance',
        'source',
        'mirror_ok',
    ):
        need(k in plan, 'missing key ' + k)
    if bad:
        return bad
    need(isinstance(plan['id'], str) and plan['id'], 'id not a string')
    need(plan['pack'] == pack_name, f'pack {plan["pack"]!r} != dir {pack_name!r}')
    need(plan['kind'] in KINDS, 'bad kind ' + str(plan['kind']))
    for k in ('w', 'd', 'area', 'storey_h'):
        need(_num(plan[k]) and plan[k] > 0, f'{k} not a positive number')
    need(2.0 <= plan['storey_h'] <= 5.0, 'storey_h out of range')
    need(_pts_ok(plan['boundary'], 4), 'boundary needs >= 4 [x,z] points')
    if bad:
        return bad

    xs, zs = [], []

    def note(pts):
        for x, z in pts:
            xs.append(x)
            zs.append(z)

    note(plan['boundary'])
    need(isinstance(plan['rooms'], list) and plan['rooms'], 'rooms empty')
    for i, r in enumerate(plan['rooms']):
        need(isinstance(r, dict), f'room {i} not an object')
        if not isinstance(r, dict):
            continue
        need(r.get('type') in ROOM_TYPES, f'room {i} type {r.get("type")!r}')
        need(_pts_ok(r.get('pts')), f'room {i} pts')
        need(_num(r.get('area')) and r['area'] > 0, f'room {i} area')
        if _pts_ok(r.get('pts')):
            note(r['pts'])
    for i, w in enumerate(plan['walls']):
        ok = (
            isinstance(w, dict)
            and _pts_ok([w.get('a'), w.get('b')], 2)
            and _num(w.get('t'))
            and w['t'] > 0
            and isinstance(w.get('ext'), bool)
        )
        need(ok, f'wall {i} malformed')
        if ok:
            note([w['a'], w['b']])
    nw = len(plan['walls'])
    for i, dr in enumerate(plan['doors']):
        need(
            isinstance(dr, dict) and _num(dr.get('x')) and _num(dr.get('z')) and _num(dr.get('w')) and dr['w'] > 0,
            f'door {i} malformed',
        )
        need(
            isinstance(dr.get('wall'), int) and 0 <= dr['wall'] < nw,
            f'door {i} wall index {dr.get("wall")} outside 0..{nw - 1}',
        )
        need(dr.get('kind') in DOOR_KINDS, f'door {i} kind {dr.get("kind")!r}')
        if _num(dr.get('x')):
            note([[dr['x'], dr['z']]])
    for i, wd in enumerate(plan['windows']):
        need(
            isinstance(wd, dict) and _num(wd.get('x')) and _num(wd.get('z')) and _num(wd.get('w')) and wd['w'] > 0,
            f'window {i} malformed',
        )
        need(
            isinstance(wd.get('wall'), int) and 0 <= wd['wall'] < nw,
            f'window {i} wall index {wd.get("wall")} outside 0..{nw - 1}',
        )
        need(_num(wd.get('sill')) and _num(wd.get('h')), f'window {i} sill/h')
        if _num(wd.get('x')):
            note([[wd['x'], wd['z']]])
    for i, fx in enumerate(plan['fixtures']):
        need(isinstance(fx, dict) and fx.get('kind') in FIXTURE_KINDS, f'fixture {i} kind {fx.get("kind")!r}')
        need(_num(fx.get('x')) and _num(fx.get('z')) and _num(fx.get('ry')), f'fixture {i} x/z/ry')
        if _num(fx.get('x')):
            note([[fx['x'], fx['z']]])
    e = plan['entrance']
    if e is not None:
        need(isinstance(e, dict) and e.get('side') in SIDES, f'entrance side {(e or {}).get("side")!r}')
        need(_num((e or {}).get('x')) and _num((e or {}).get('z')), 'entrance x/z')
    if plan['kind'] == 'floor':
        c = plan.get('core') or {}
        need(
            isinstance(c, dict) and isinstance(c.get('stairs'), list) and isinstance(c.get('lifts'), list),
            'floor core missing stairs/lifts',
        )
        need(isinstance(plan.get('units'), list), 'floor units not a list')
        for ring in (c.get('stairs') or []) + (c.get('lifts') or []):
            if _pts_ok(ring):
                note(ring)
    need(isinstance(plan['source'], dict), 'source not an object')
    need(isinstance(plan['mirror_ok'], bool), 'mirror_ok not a bool')

    # bbox: w/d are the max over every point of the plan, and every wall end
    # lies inside that bbox (the brief's two bbox rules)
    if xs:
        need(abs(max(xs) - plan['w']) <= 0.01, f'w {plan["w"]} != max x {max(xs):.3f}')
        need(abs(max(zs) - plan['d']) <= 0.01, f'd {plan["d"]} != max z {max(zs):.3f}')
    for i, w in enumerate(plan['walls']):
        if not _pts_ok([w.get('a'), w.get('b')], 2):
            continue
        for x, z in (w['a'], w['b']):
            need(
                -0.01 <= x <= plan['w'] + 0.01 and -0.01 <= z <= plan['d'] + 0.01,
                f'wall {i} end ({x}, {z}) outside the bbox',
            )
    return bad


def below_origin(plan):
    """How far a plan's geometry runs below the origin. Noted, not failed: the
    bbox rule the brief spells out is 'w/d = max of points' plus walls inside
    the bbox, so a pack that translates by its boundary rather than by its full
    extent is still legal — but it is worth the owning pack's attention."""
    out = 0.0
    for seq in (
        [plan.get('boundary') or []]
        + [r.get('pts') or [] for r in plan.get('rooms') or []]
        + [[w.get('a'), w.get('b')] for w in plan.get('walls') or []]
    ):
        for p in seq:
            if isinstance(p, list) and len(p) == 2 and _num(p[0]) and _num(p[1]):
                out = min(out, p[0], p[1])
    for o in (plan.get('doors') or []) + (plan.get('windows') or []) + (plan.get('fixtures') or []):
        if _num(o.get('x')) and _num(o.get('z')):
            out = min(out, o['x'], o['z'])
    return out


def check_pack(pdir, label):
    name = os.path.basename(pdir.rstrip('/'))
    tag = f'{label}:{name}'
    man_p = os.path.join(pdir, 'pack.json')
    idx_p = os.path.join(pdir, 'index.json')
    if not (os.path.isfile(man_p) or os.path.isfile(idx_p)):
        print(f'  SKIP {tag}: no pack.json/index.json yet — directory is still being written')
        return None
    if not check(f'{tag} pack.json + index.json exist', os.path.isfile(man_p) and os.path.isfile(idx_p), pdir):
        return None
    try:
        man = json.load(open(man_p))
        idx = json.load(open(idx_p))
    except Exception as exc:
        check(f'{tag} manifest/index parse', False, exc)
        return None
    check(
        f'{tag} manifest parses with pack/title/licence/attribution',
        all(man.get(k) for k in ('pack', 'title', 'licence', 'attribution')) and man['pack'] == name,
        man,
    )
    check(
        f'{tag} licence is an open one',
        any(str(man.get('licence', '')).startswith(p) for p in OPEN_LICENCES),
        man.get('licence'),
    )
    check(
        f'{tag} attribution is a printable credit line',
        isinstance(man.get('attribution'), str) and len(man['attribution']) >= 20,
        man.get('attribution'),
    )

    rows = idx.get('rows')
    check(
        f'{tag} index.json has pack + rows',
        isinstance(rows, list) and bool(rows) and isinstance(idx.get('pack'), dict),
        type(rows),
    )
    if not isinstance(rows, list):
        return None
    ids = [r.get('id') for r in rows]
    check(f'{tag} index row ids are unique', len(ids) == len(set(ids)), f'{len(ids)} rows, {len(set(ids))} unique')
    on_disk = {f[:-5] for f in os.listdir(os.path.join(pdir, 'plans')) if f.endswith('.json')}
    check(
        f'{tag} index rows match the files on disk',
        set(ids) == on_disk,
        f'index-only {len(set(ids) - on_disk)}, disk-only {len(on_disk - set(ids))}',
    )
    for k in ('kind', 'w', 'd', 'area', 'n_rooms', 'types', 'fill'):
        check(f'{tag} index rows carry {k}', all(k in r for r in rows))
    counts = {'unit': 0, 'floor': 0, 'house': 0}
    for r in rows:
        counts[r['kind']] = counts.get(r['kind'], 0) + 1
    check(
        f'{tag} manifest counts match the rows',
        {k: int(v) for k, v in (man.get('count') or {}).items()} == counts,
        f'manifest {man.get("count")} vs rows {counts}',
    )
    print(f'    {tag}: {counts["unit"]} units, {counts["floor"]} floors, {counts["house"]} houses')

    rnd = random.Random(20260910)
    pick = rnd.sample(rows, min(SAMPLE, len(rows)))
    bad = []
    neg = []
    for r in pick:
        p = os.path.join(pdir, 'plans', r['id'] + '.json')
        try:
            plan = json.load(open(p))
        except Exception as exc:
            bad.append(f'{r["id"]}: unreadable ({exc})')
            continue
        for msg in validate(plan, name):
            bad.append(f'{r["id"]}: {msg}')
        if abs(plan.get('w', -1) - r['w']) > 0.01 or abs(plan.get('d', -1) - r['d']) > 0.01:
            bad.append(f'{r["id"]}: index w/d disagrees with the plan')
        if len(plan.get('rooms', [])) != r['n_rooms']:
            bad.append(f'{r["id"]}: index n_rooms disagrees with the plan')
        m = below_origin(plan)
        if m < -0.01:
            neg.append(f'{r["id"]} {m:.3f}')
    check(f'{tag} {len(pick)} random plans validate against the schema', not bad, '; '.join(bad[:6]))
    if neg:
        print(
            f'    NOTE {tag}: {len(neg)}/{len(pick)} sampled plans have geometry '
            f'below the origin ({", ".join(neg[:4])}) — legal under the bbox rule '
            f'(w/d = max of points) but worth a look by the pack that owns it'
        )

    stats_p = os.path.join(pdir, 'stats.json')
    if os.path.isfile(stats_p):
        try:
            st = json.load(open(stats_p))
        except Exception as exc:
            st = None
            check(f'{tag} stats.json parses', False, exc)
        if st is not None:
            check(
                f'{tag} stats.json has rooms / size classes / adjacency / door widths',
                all(st.get(k) for k in ('rooms', 'unit_size_classes', 'adjacency', 'door_width_median')),
                sorted(st or {}),
            )
    return counts


def main():
    print('plan packs')
    seen = 0
    sd_counts = None
    for label, root in (('pack', PACKS_DIR), ('fixture', FIXTURES_DIR)):
        if not os.path.isdir(root):
            print(f'  SKIP {label} root absent: {root}')
            continue
        for name in sorted(os.listdir(root)):
            pdir = os.path.join(root, name)
            if not os.path.isdir(os.path.join(pdir, 'plans')):
                continue
            seen += 1
            c = check_pack(pdir, label)
            if label == 'pack' and name == 'swiss_dwellings':
                sd_counts = c
    check('at least one pack directory was checked', seen > 0, f'{PACKS_DIR} / {FIXTURES_DIR}')

    if sd_counts is None:
        print(
            '  SKIP swiss_dwellings size assertion — pack absent from ' + PACKS_DIR + ' (the fixtures above still ran)'
        )
    else:
        check('swiss_dwellings has >= 10,000 units', sd_counts['unit'] >= 10000, sd_counts['unit'])
        check('swiss_dwellings has >= 500 floors', sd_counts['floor'] >= 500, sd_counts['floor'])
    finish()


if __name__ == '__main__':
    main()
