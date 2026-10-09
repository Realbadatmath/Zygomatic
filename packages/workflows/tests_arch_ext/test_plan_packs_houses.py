# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_plan_packs_houses.py — schema proof for the house plan
packs (resplan, procthor10k) written by tools/plans_convert_houses.py.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_plan_packs_houses.py

It validates the TEST FIXTURES (tests_arch_ext/fixtures/plans/<pack>/, 6 plans
each) plan by plan — never the 28k-plan production packs — and then checks only
the manifest and index of the real packs under data/architecture/plans/ when
they are present. ZYG_PLANS_DIR overrides the fixture root, so the same checks
can be pointed at any pack dir.

This file exists because tests_arch_ext/test_plan_packs.py (task 1, generic
validator for every pack) was not on disk when the house packs were converted.
If that generic validator lands, these checks are a superset for the two house
packs and this file can be folded into it.
"""

import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CREWS = os.path.dirname(HERE)
FIXTURES = os.environ.get('ZYG_PLANS_DIR', os.path.join(HERE, 'fixtures', 'plans'))
REAL = os.path.join(CREWS, 'data', 'architecture', 'plans')
PACKS = ('resplan', 'procthor10k')

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
OK_LICENCES = ('CC BY', 'CC0', 'Apache', 'BSD', 'MIT')
ROW_KEYS = {'id', 'kind', 'w', 'd', 'area', 'n_rooms', 'types', 'entrance', 'fill'}


def poly_area(pts):
    a = 0.0
    for i in range(len(pts)):
        x0, z0 = pts[i]
        x1, z1 = pts[(i + 1) % len(pts)]
        a += x0 * z1 - x1 * z0
    return a / 2.0


def seg_dist(a, b, p):
    ax, az = a
    bx, bz = b
    px, pz = p
    dx, dz = bx - ax, bz - az
    ln = dx * dx + dz * dz
    t = 0.0 if ln <= 0 else max(0.0, min(1.0, ((px - ax) * dx + (pz - az) * dz) / ln))
    return math.hypot(px - (ax + t * dx), pz - (az + t * dz))


def check_manifest(pack, m, where):
    ok = True
    for k in ('pack', 'title', 'source_url', 'version', 'licence', 'attribution', 'doi', 'count', 'converted', 'notes'):
        ok &= check('%s %s manifest has %s' % (pack, where, k), k in m, sorted(m))
    ok &= check('%s %s manifest pack name' % (pack, where), m.get('pack') == pack, m.get('pack'))
    lic = str(m.get('licence', ''))
    ok &= check(
        '%s %s licence is shareable' % (pack, where),
        any(lic.startswith(p) or (' ' + p) in lic for p in OK_LICENCES),
        lic,
    )
    ok &= check(
        '%s %s attribution is one line' % (pack, where),
        len(str(m.get('attribution', ''))) >= 20 and '\n' not in str(m.get('attribution', '')),
        m.get('attribution'),
    )
    ok &= check(
        '%s %s count is a kind map' % (pack, where),
        isinstance(m.get('count'), dict) and set(m['count']) == {'unit', 'floor', 'house'},
        m.get('count'),
    )
    return ok


def check_plan(pack, rec, path):
    name = '%s %s' % (pack, rec.get('id', os.path.basename(path)))
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
        'core',
        'units',
        'source',
        'mirror_ok',
    ):
        check('%s has %s' % (name, k), k in rec, sorted(rec))
    check('%s id matches file' % name, rec.get('id') == os.path.basename(path)[:-5], path)
    check('%s pack field' % name, rec.get('pack') == pack, rec.get('pack'))
    check('%s kind is house' % name, rec.get('kind') == 'house', rec.get('kind'))
    w, d = rec.get('w', 0), rec.get('d', 0)
    check('%s w/d positive and sane' % name, 0.5 < w < 120 and 0.5 < d < 120, (w, d))
    check('%s storey_h sane' % name, 2.0 <= rec.get('storey_h', 0) <= 4.0, rec.get('storey_h'))

    b = rec.get('boundary') or []
    check(
        '%s boundary is a polygon' % name, len(b) >= 3 and all(isinstance(q, list) and len(q) == 2 for q in b), len(b)
    )
    check('%s boundary is CCW' % name, poly_area(b) > 0, poly_area(b))
    xs = [q[0] for q in b]
    zs = [q[1] for q in b]
    check('%s boundary origin is (0,0)' % name, abs(min(xs)) < 1e-6 and abs(min(zs)) < 1e-6, (min(xs), min(zs)))
    check(
        '%s boundary bbox equals w/d' % name,
        abs(max(xs) - w) < 0.02 and abs(max(zs) - d) < 0.02,
        (max(xs), w, max(zs), d),
    )
    check('%s area fits the bbox' % name, 0.05 <= rec.get('area', 0) / (w * d) <= 1.002, rec.get('area') / (w * d))

    rooms = rec.get('rooms') or []
    check('%s has rooms' % name, len(rooms) >= 1, len(rooms))
    check(
        '%s room types are in the vocabulary' % name,
        all(x.get('type') in ROOM_TYPES for x in rooms),
        sorted({x.get('type') for x in rooms} - ROOM_TYPES),
    )
    check(
        '%s room polygons are closed rings of >=3 points' % name,
        all(len(x.get('pts') or []) >= 3 and x['pts'][0] != x['pts'][-1] for x in rooms),
        [len(x.get('pts') or []) for x in rooms],
    )
    check(
        '%s room areas match their polygons' % name,
        all(abs(abs(poly_area(x['pts'])) - x['area']) <= 0.05 * max(1.0, x['area']) for x in rooms),
        [(x['type'], x['area'], round(abs(poly_area(x['pts'])), 2)) for x in rooms][:4],
    )
    check(
        '%s rooms lie inside the bbox' % name,
        all(-0.05 <= q[0] <= w + 0.05 and -0.05 <= q[1] <= d + 0.05 for x in rooms for q in x['pts']),
        name,
    )

    walls = rec.get('walls') or []
    check('%s has walls' % name, len(walls) >= 3, len(walls))
    check(
        '%s walls are centreline segments' % name,
        all(
            len(x.get('a') or []) == 2
            and len(x.get('b') or []) == 2
            and 0.02 <= x.get('t', 0) <= 1.0
            and isinstance(x.get('ext'), bool)
            for x in walls
        ),
        walls[:2],
    )
    check(
        '%s walls have length' % name,
        all(math.dist(x['a'], x['b']) > 0.05 for x in walls),
        min(math.dist(x['a'], x['b']) for x in walls) if walls else 0,
    )
    check('%s some walls are external' % name, any(x['ext'] for x in walls), sum(1 for x in walls if x['ext']))

    for group, kinds, extra in (('doors', DOOR_KINDS, ()), ('windows', None, ('sill', 'h'))):
        items = rec.get(group) or []
        check(
            '%s %s index a real wall' % (name, group),
            all(isinstance(o.get('wall'), int) and 0 <= o['wall'] < len(walls) for o in items),
            [o.get('wall') for o in items][:6],
        )
        check(
            '%s %s sit on their wall' % (name, group),
            all(
                seg_dist(walls[o['wall']]['a'], walls[o['wall']]['b'], (o['x'], o['z'])) <= 0.35
                for o in items
                if isinstance(o.get('wall'), int) and 0 <= o['wall'] < len(walls)
            ),
            [round(seg_dist(walls[o['wall']]['a'], walls[o['wall']]['b'], (o['x'], o['z'])), 3) for o in items][:6],
        )
        check(
            '%s %s widths are sane' % (name, group),
            all(0.2 <= o.get('w', 0) <= 5.0 for o in items),
            [o.get('w') for o in items][:6],
        )
        if kinds:
            check(
                '%s %s kinds are in the vocabulary' % (name, group),
                all(o.get('kind') in kinds for o in items),
                [o.get('kind') for o in items][:6],
            )
        for k in extra:
            check(
                '%s %s all carry %s' % (name, group, k), all(isinstance(o.get(k), (int, float)) for o in items), group
            )

    check(
        '%s fixture kinds are in the vocabulary' % name,
        all(o.get('kind') in FIXTURE_KINDS for o in (rec.get('fixtures') or [])),
        sorted({o.get('kind') for o in (rec.get('fixtures') or [])} - FIXTURE_KINDS),
    )
    check(
        '%s fixtures carry x/z/ry' % name,
        all(all(isinstance(o.get(k), (int, float)) for k in ('x', 'z', 'ry')) for o in (rec.get('fixtures') or [])),
        rec.get('fixtures')[:2],
    )

    ent = rec.get('entrance')
    check(
        '%s entrance is null or a side + point' % name,
        ent is None
        or (
            ent.get('side') in SIDES
            and isinstance(ent.get('x'), (int, float))
            and isinstance(ent.get('z'), (int, float))
        ),
        ent,
    )
    core = rec.get('core') or {}
    check(
        '%s core has stairs/lifts lists' % name,
        isinstance(core.get('stairs'), list) and isinstance(core.get('lifts'), list),
        core,
    )
    check('%s units is a list' % name, isinstance(rec.get('units'), list), rec.get('units'))
    check('%s source is a dict' % name, isinstance(rec.get('source'), dict), rec.get('source'))
    check('%s mirror_ok is a bool' % name, isinstance(rec.get('mirror_ok'), bool), rec.get('mirror_ok'))
    check(
        '%s coordinates are rounded to 3dp' % name,
        all(round(q, 3) == q for q in xs + zs),
        [q for q in xs if round(q, 3) != q][:4],
    )


def check_index(pack, root, plans_on_disk, where):
    ix = json.load(open(os.path.join(root, 'index.json')))
    check(
        '%s %s index has pack + rows' % (pack, where),
        isinstance(ix.get('pack'), dict) and isinstance(ix.get('rows'), list),
        sorted(ix),
    )
    rows = ix.get('rows') or []
    check(
        '%s %s index row count == pack count' % (pack, where),
        len(rows) == ix['pack']['count']['house'],
        (len(rows), ix['pack']['count']),
    )
    check(
        '%s %s index rows are compact' % (pack, where),
        all(set(x) == ROW_KEYS for x in rows),
        sorted(set(rows[0]) ^ ROW_KEYS) if rows else 'no rows',
    )
    check(
        '%s %s index fill = area/(w*d)' % (pack, where),
        all(abs(x['fill'] - x['area'] / (x['w'] * x['d'])) < 0.002 for x in rows),
        [x['id'] for x in rows if abs(x['fill'] - x['area'] / (x['w'] * x['d'])) >= 0.002][:4],
    )
    check(
        '%s %s index types count matches n_rooms' % (pack, where),
        all(len(x['types'].split(',')) == x['n_rooms'] for x in rows),
        [x['id'] for x in rows if len(x['types'].split(',')) != x['n_rooms']][:4],
    )
    check(
        '%s %s index entrance sides are valid' % (pack, where),
        all(x['entrance'] is None or x['entrance'] in SIDES for x in rows),
        sorted({str(x['entrance']) for x in rows if not (x['entrance'] is None or x['entrance'] in SIDES)}),
    )
    if plans_on_disk is not None:
        check(
            '%s %s every index row has a plan file' % (pack, where),
            {x['id'] for x in rows} == plans_on_disk,
            len({x['id'] for x in rows} ^ plans_on_disk),
        )
    return rows


# ── the fixtures (full schema validation, plan by plan) ───────────────────────
for pack in PACKS:
    root = os.path.join(FIXTURES, pack)
    if not check('%s fixture dir exists' % pack, os.path.isdir(root), root):
        continue
    m = json.load(open(os.path.join(root, 'pack.json')))
    check_manifest(pack, m, 'fixture')
    files = sorted(f for f in os.listdir(os.path.join(root, 'plans')) if f.endswith('.json'))
    check('%s fixture has 6 plans' % pack, len(files) == 6, files)
    ids = set()
    for f in files:
        path = os.path.join(root, 'plans', f)
        rec = json.load(open(path))
        ids.add(rec.get('id'))
        check_plan(pack, rec, path)
    check_index(pack, root, ids, 'fixture')

# ── the real packs (manifest + index only — never 28k plan files) ─────────────
for pack in PACKS:
    root = os.path.join(REAL, pack)
    if not check('%s pack dir exists' % pack, os.path.isdir(root), root):
        continue
    m = json.load(open(os.path.join(root, 'pack.json')))
    check_manifest(pack, m, 'pack')
    rows = check_index(pack, root, None, 'pack')
    n = len(os.listdir(os.path.join(root, 'plans')))
    check('%s pack plan files == index rows' % pack, n == len(rows), (n, len(rows)))
    check('%s pack is big enough to be the real thing' % pack, len(rows) >= 1000, len(rows))
    one = json.load(open(os.path.join(root, 'plans', rows[0]['id'] + '.json')))
    check_plan(pack, one, os.path.join(root, 'plans', rows[0]['id'] + '.json'))

finish()
