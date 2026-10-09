# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Section 1 — the harness and the drawer (no model, no browser)."""

from zyg_workflows import arch_assistant as A
import math
from zyg_workflows import paths

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

URL = paths.ZYG_KANBAN_URL + '/inspection.html#architecture'
# Not a credential: the throwaway string this self-test's own loopback server
# hands out and then checks it gets back. Named so, nothing here reads like one.
FIXTURE_TOKEN = 'tok123'  # noqa: S105  fixture string, not a credential
FAILS = []


def check(name, ok, detail=''):
    _zyg_log.info(('  ok   ' if ok else '  FAIL ') + name + (('  — ' + str(detail)) if detail and not ok else ''))
    if not ok:
        FAILS.append(name)


# ── 1. the drawer ─────────────────────────────────────────────────────────────
def test_drawer():
    _zyg_log.info('drawer')
    check(
        'cells parse',
        A.parse_cell('C4') == (2, 3) and A.parse_cell('AA12') == (26, 11) and A.parse_cell('KN300') == (299, 299),
    )
    check('cells print', A.cell_name(*A.parse_cell('AB7')) == 'AB7' and A.cell_of(*A.cell_centre(2, 3)) == 'C4')
    bad = False
    try:
        A.parse_cell('ZZ4')
    except ValueError:
        bad = True
    check('off-grid refused', bad)
    d = A.Drawing({'objects': []})
    A.call_tool(d, 'draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 100, 'roof': 'flat'})
    A.call_tool(d, 'add_windows', {'walls': 'new', 'every_n_storeys': 2, 'material': 'mat_glass'})
    kinds = {}
    for o in d.objs:
        kinds[o['kind']] = kinds.get(o['kind'], 0) + 1
    check('box counts', kinds == {'wall': 400, 'slab': 100, 'roof_flat': 1, 'window': 400}, kinds)
    walls = [o for o in d.objs if o['kind'] == 'wall']
    off = 0
    for w in [o for o in d.objs if o['kind'] == 'window']:
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
    check('windows on their walls', off == 0, off)
    st = sorted({A.storey_of(o['y'], 2.7) for o in d.objs if o['kind'] == 'window'})
    check('windows on even storeys only', st == list(range(0, 100, 2)), st[:5])
    check('glass', all(o['mat'] == 'mat_glass' for o in d.objs if o['kind'] == 'window'))
    xs = [o['x'] for o in walls]
    zs = [o['z'] for o in walls]
    check(
        'footprint C4..L13 = x -148..-138',
        (min(xs), max(xs), min(zs), max(zs)) == (-148, -138, -147, -137),
        (min(xs), max(xs), min(zs), max(zs)),
    )
    check('summary names the block', 'C4..L13' in d.summary(), d.summary())
    doc = d.to_doc()
    check('doc is the record shape', set(doc['objects'][0]) >= {'id', 'kind', 'p', 'x', 'y', 'z', 'ry', 'mat', 'grp'})
    return doc
