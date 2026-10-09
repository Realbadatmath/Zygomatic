# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_tab_blender_parity.py — the two engines must agree on
how big a kind is.

The operator's screenshot of the live 20-storey tower (job 94f5813b) showed the
exterior fire escape as full-width zig-zag flights, roughly 16 m across, while
arch_ext/stairs_vertical.js (AR_EXT.geom.fire_stair_exterior) draws 6.60 m for
storeys 20 / w 1.2 / run 0.28 / rise 0.18. Either the page ran a stale bundle or
the tab and Blender disagree. This test settles it on every sweep: for each kind
the live tower actually uses, it builds the SAME `p` in both engines and compares
the world bound box axis by axis.

  · the tab    — arch_ext_harness.browser_kinds: headless Chrome, geometry built
                 through arGeom exactly as the studio builds it.
  · Blender    — arch_ext_harness.blender_kinds: a real headless build through
                 arch_blender_build.py, bound box reported in the STUDIO frame
                 (blender x, y, z = studio x, -z, y).

Every `p` is lifted verbatim from tests_arch_ext/fixtures/live_tower_20260911.json
so the test fails the day either engine stops agreeing with what the assistant
writes. A kind only one engine builds is a MISSING failure, not a skip.

    /usr/bin/python3 tests_arch_ext/test_tab_blender_parity.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, browser_kinds, blender_kinds  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, 'fixtures', 'live_tower_20260911.json')
TOL = 0.05  # metres, per axis

print('fixture')
doc = json.load(open(FIXTURE, encoding='utf-8'))
objs = doc['objects']
check('live tower fixture has 336 records', len(objs) == 336, len(objs))
by_id = {o['id']: o for o in objs}


def p_of(oid, kind):
    """The `p` of one live record, proving its kind on the way through."""
    o = by_id.get(oid)
    if not o or o['kind'] != kind:
        raise SystemExit('fixture record %s is not a %s (%s)' % (oid, kind, o and o['kind']))
    return o['p']


def first_p(kind):
    """The `p` of the first record of `kind` in the live tower."""
    for o in objs:
        if o['kind'] == kind:
            return o['id'], o['p']
    raise SystemExit('fixture has no %s record' % kind)


sc_id, sc_p = first_p('string_course')
cw_id, cw_p = first_p('curtain_wall')

# The fire escape is given by its measured parameters rather than by id so the
# numbers the brief quotes are visible here; o498 carries exactly these.
FSE_P = {'storeys': 20, 'h': 2.7, 'w': 1.2, 'run': 0.28, 'rise': 0.18}
check('fire escape params match live record o498', by_id['o498']['p'] == FSE_P, by_id['o498']['p'])

CASES = [
    {'kind': 'fire_stair_exterior', 'src': 'o498 (measured)', 'p': FSE_P},
    {'kind': 'stair_u', 'src': 'o228', 'p': p_of('o228', 'stair_u')},
    {'kind': 'elevator_shaft', 'src': 'o334', 'p': p_of('o334', 'elevator_shaft')},
    {'kind': 'pool', 'src': 'o507', 'p': p_of('o507', 'pool')},
    {'kind': 'umbrella', 'src': 'o573', 'p': p_of('o573', 'umbrella')},
    {'kind': 'sun_lounger', 'src': 'o572', 'p': p_of('o572', 'sun_lounger')},
    {'kind': 'canopy', 'src': 'o103', 'p': p_of('o103', 'canopy')},
    {'kind': 'double_door', 'src': 'o102', 'p': p_of('o102', 'double_door')},
    {'kind': 'string_course', 'src': sc_id, 'p': sc_p},
    {'kind': 'curtain_wall', 'src': cw_id, 'p': cw_p},
    {'kind': 'column_round', 'src': 'o104', 'p': p_of('o104', 'column_round')},
    {'kind': 'wall', 'src': 'o499', 'p': p_of('o499', 'wall')},
]
KINDS = [c['kind'] for c in CASES]
check('every case kind is distinct', len(set(KINDS)) == len(KINDS), KINDS)

# ── build both engines ────────────────────────────────────────────────────────
print('tab')
tab = {r['kind']: r for r in browser_kinds([{'kind': c['kind'], 'p': c['p']} for c in CASES])}
print('blender')
bl = blender_kinds([{'kind': c['kind'], 'p': c['p']} for c in CASES])


def sizes(kind):
    t = tab.get(kind) or {}
    b = bl.get(kind) or {}
    ts = t.get('size') if t.get('ok') and t.get('size') else None
    bs = b.get('size') if (b.get('polys') or 0) > 0 and b.get('size') else None
    return ts, bs, t, b


# ── the table ─────────────────────────────────────────────────────────────────
fmt = lambda s: ('%7.3f %7.3f %7.3f' % tuple(s)) if s else '      -       -       -'  # noqa: E731
print('\n%-20s %-8s %-23s %-23s %s' % ('kind', 'src', 'tab  x   y(up)   z', 'blender  x   y(up)  z', 'delta x/y/z'))
print('-' * 104)
for c in CASES:
    ts, bs, t, b = sizes(c['kind'])
    if ts and bs:
        d = '  '.join('%.3f' % abs(ts[i] - bs[i]) for i in range(3))
    else:
        d = 'MISSING in ' + ('tab' if not ts else 'blender')
    print('%-20s %-8s %-23s %-23s %s' % (c['kind'], c['src'], fmt(ts), fmt(bs), d))
print('-' * 104 + '\n')

# ── the checks ────────────────────────────────────────────────────────────────
for c in CASES:
    kind = c['kind']
    ts, bs, t, b = sizes(kind)
    if not ts or not bs:
        check(
            '%s: both engines build it' % kind,
            False,
            'MISSING in %s (tab=%s err=%r, blender polys=%s)'
            % ('tab' if not ts else 'blender', ts, t.get('err', ''), b.get('polys')),
        )
        continue
    d = [abs(ts[i] - bs[i]) for i in range(3)]
    check(
        '%s: tab and blender agree within %.2f m (x %.3f, y %.3f, z %.3f)' % (kind, TOL, d[0], d[1], d[2]),
        max(d) <= TOL,
        {'tab': ts, 'blender': bs, 'delta': [round(v, 4) for v in d], 'p': c['p']},
    )

# The number the operator's screenshot contradicted. 20 flights of 4.2 m run
# with a 1.2 m landing hanging off each end = 6.60 m of x, NOT the ~16 m the
# stale page showed. Pinned here so a future geometry change is caught in both
# engines at once.
fse_tab = (tab.get('fire_stair_exterior') or {}).get('size') or [0, 0, 0]
fse_bl = (bl.get('fire_stair_exterior') or {}).get('size') or [0, 0, 0]
check('fire escape tab x extent is 6.60 m (not the ~16 m of the screenshot)', abs(fse_tab[0] - 6.60) <= 0.05, fse_tab)
check('fire escape blender x extent is 6.60 m', abs(fse_bl[0] - 6.60) <= 0.05, fse_bl)
check(
    'fire escape climbs 20 x 2.7 = 54.00 m in both engines',
    abs(fse_tab[1] - 54.00) <= 0.05 and abs(fse_bl[1] - 54.00) <= 0.05,
    (fse_tab, fse_bl),
)

finish()
