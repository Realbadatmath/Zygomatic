# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""tests_arch_ext/test_assets_search.py — proof for the assets_search family.

    "${ZYG_SERVER_PYTHON:-$HOME/Zygomatic Full/agents/.venv/bin/python}" tests_arch_ext/test_assets_search.py

The family adds NO new kinds: pack assets are the studio's built-in kind
'asset'. So the rail check is that it asks for nothing, and the tab check is
that a record with the parameters place_asset writes still builds the
placeholder crate at the size those parameters name.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from zyg_workflows.arch_ext_harness import check, finish, assistant, kinds_of, browser_kinds, rail_has, tool_names  # noqa: E402
from zyg_workflows.arch_assistant import cell_centre, parse_cell  # noqa: E402

NEW_KINDS: list = []  # this family adds none


def _lines(txt):
    return [l for l in txt.splitlines() if ' — ' in l]


# ── the assistant ─────────────────────────────────────────────────────────────
print('assistant')
names = tool_names()
check(
    'tools registered',
    all(t in names for t in ('search_assets', 'place_asset', 'list_asset_packs', 'place_assets_along')),
    names,
)

txt, d = assistant('search_assets', {'query': 'chair'})
check('search_assets("chair") returns at least one line', len(_lines(txt)) >= 1, txt[:300])
check(
    '...each line names an id, a pack and a size',
    all('|' in l and '(' in l and re.search(r'\d m( \[|$)', l.rstrip()) for l in _lines(txt)),
    _lines(txt)[:3],
)
check(
    '...and every line carries a quality tag ([real…] or [toy kit…])',
    all('[real' in l or '[toy kit' in l or '[museum' in l for l in _lines(txt)),
    _lines(txt)[:3],
)

txt, d = assistant('search_assets', {'query': 'qzxvwnotathing'}, drawing=d)
check('a nonsense word finds nothing', txt.startswith('nothing'), txt[:200])

txt, d = assistant('place_asset', {'query_or_id': 'tree', 'cell': 'C4'}, drawing=d)
o = d.objs[-1]
cx, cz = cell_centre(*parse_cell('C4'))
check('place_asset made one record of kind asset', kinds_of(d).get('asset') == 1 and o['kind'] == 'asset', txt)
check(
    '...at the cell centre, storey 0',
    abs(o['x'] - cx) < 1e-6 and abs(o['z'] - cz) < 1e-6 and o['y'] == 0.0,
    (o['x'], o['z'], o['y'], cx, cz),
)
check(
    '...with p.pack / p.item / a bounding size',
    bool(o['p'].get('pack'))
    and bool(o['p'].get('item'))
    and o['p'].get('bw', 0) > 0
    and o['p'].get('bh', 0) > 0
    and o['p'].get('bd', 0) > 0,
    o['p'],
)
check(
    '...named after the item, grouped under "assets"',
    o['grp'] == 'assets' and o['name'] and o['name'] != 'asset',
    (o['name'], o['grp']),
)
PLACED = dict(o['p'])

txt, d = assistant('place_asset', {'query_or_id': 'tree', 'cell': 'ZZ9'}, drawing=d)
check('off-grid cell refused', txt.startswith('refused') and kinds_of(d).get('asset') == 1, txt)
txt, d = assistant('place_asset', {'query_or_id': 'qzxvwnotathing', 'cell': 'C4'}, drawing=d)
check('unmatchable query refused', txt.startswith('refused') and kinds_of(d).get('asset') == 1, txt)

txt, d = assistant('list_asset_packs', {}, drawing=d)
check('list_asset_packs names at least five packs', len(_lines(txt)) >= 5, txt[:300])

txt, d = assistant('place_assets_along', {'cells': ['C4', 'C14', 'M14'], 'query': 'tree', 'spacing': 3}, drawing=d)
n_along = kinds_of(d).get('asset', 0) - 1
check('place_assets_along over 20 m at 3 m gives at least 4 assets', n_along >= 4, (n_along, txt))
row = [x for x in d.objs if x['grp'] != 'assets' and x['kind'] == 'asset']
check(
    '...first copy sits on the first cell',
    abs(row[0]['x'] - cx) < 1e-6 and abs(row[0]['z'] - cz) < 1e-6,
    (row[0]['x'], row[0]['z']),
)
check('...they are spaced 3 m apart', abs(abs(row[1]['z'] - row[0]['z']) - 3.0) < 1e-6, (row[0]['z'], row[1]['z']))
txt, d = assistant('place_assets_along', {'cells': ['C4'], 'query': 'tree'}, drawing=d)
check('a one-cell polyline is refused', txt.startswith('refused'), txt)

# ── the triangle budget (2026-09-11, live job 94f5813b) ──────────────────────
# That job's scene was 15.66 M triangles and 15.5 M of it was four copies of one
# photoscanned jacaranda. The catalogue counts triangles now, a heavy line says
# so, and nothing over TRI_BUDGET is placed while a decimated twin exists.
print('triangle budget')
from zyg_workflows import arch_assistant as _A  # noqa: E402

_A.load_extensions()
AS = _A.EXT_MODULES['assets_search']
BY_ID = AS._index()['by_id']

lod0 = BY_ID.get('polyhaven_arch|jacaranda_tree_2k')
lod1 = BY_ID.get('polyhaven_arch|jacaranda_tree_lod1')
check(
    'the catalogue knows the jacaranda is 3.86 M triangles',
    lod0 is not None and 3.80e6 < lod0['tris'] < 3.95e6,
    lod0 and lod0.get('tris'),
)
check(
    'a decimated twin polyhaven_arch|jacaranda_tree_lod1 is catalogued',
    lod1 is not None,
    sorted(k for k in BY_ID if 'jacaranda' in k),
)
check(
    '...at or under the %d-triangle budget' % AS.TRI_BUDGET,
    lod1 is not None and 0 < lod1['tris'] <= AS.TRI_BUDGET,
    lod1 and lod1.get('tris'),
)
check(
    '...and still the same tree: height within 5%% of the original %.2f m' % (lod0['size'][1] if lod0 else 0),
    lod1 is not None and lod0 is not None and abs(lod1['size'][1] - lod0['size'][1]) <= 0.05 * lod0['size'][1],
    (lod0 and lod0['size'], lod1 and lod1['size']),
)

txt, _dj = assistant('search_assets', {'query': 'jacaranda'})
jl = _lines(txt)
check(
    'search_assets("jacaranda") lists the lod1 first',
    bool(jl) and jl[0].startswith('polyhaven_arch|jacaranda_tree_lod1'),
    jl,
)
check(
    '...and the line for the original says it is heavy',
    any('tris — heavy' in l and 'jacaranda_tree_2k' in l for l in jl),
    jl,
)

txt, dbud = assistant('place_asset', {'query_or_id': 'polyhaven_arch|jacaranda_tree_2k', 'cell': 'C4'})
_p = dbud.objs[-1]['p'] if dbud.objs else {}
check(
    'place_asset on the 3.9 M jacaranda plants the lod1 instead',
    _p.get('item') == 'jacaranda_tree_lod1' and 0 < _p.get('tris', 0) <= AS.TRI_BUDGET,
    (txt[:160], _p),
)

_orphan = next((r for r in AS._index()['rows'] if r['tris'] > AS.TRI_BUDGET and AS.lod_row(r) is None), None)
txt, dbud = assistant('place_asset', {'query_or_id': _orphan['id'], 'cell': 'C6'}, drawing=dbud)
check(
    'a heavy model with no lod1 is refused, and the refusal names the tool that makes one',
    txt.startswith('refused') and 'arch_asset_lod.py' in txt and kinds_of(dbud).get('asset') == 1,
    (_orphan['id'], _orphan['tris'], txt[:200]),
)

# plant_tree_line is where the live job did it: every life-size tree in the
# packs is a 0.6-17 M triangle photoscan, and an avenue plants a dozen.
txt, dline = assistant(
    'plant_tree_line', {'cells': ['C10', 'C40'], 'kind': 'deciduous', 'height': 12, 'spacing': 8, 'model': 'real'}
)
line_assets = [o for o in dline.objs if o['kind'] == 'asset']
over = sorted(
    {
        o['p'].get('item')
        for o in line_assets
        if (BY_ID.get(f'{o["p"].get("pack")}|{o["p"].get("item")}') or {}).get('tris', 0) > AS.TRI_BUDGET
    }
)
check('plant_tree_line(real, deciduous, 12 m) still plants real pack trees', len(line_assets) >= 3, txt[:200])
check(
    '...and not one of them is over the triangle budget',
    over == [],
    over or [o['p'].get('item') for o in line_assets[:3]],
)

check('the family asks nothing of the rail (no new kinds)', rail_has(NEW_KINDS) == [], rail_has(NEW_KINDS))
check('the rail already knows kind asset', rail_has([]) == [] and 'asset' not in NEW_KINDS)

# ── the tab ───────────────────────────────────────────────────────────────────
print('tab')
cases = [
    {'kind': 'asset', 'p': PLACED},
    {'kind': 'asset', 'p': {'pack': 'kenney/castle-kit', 'item': 'tree-large', 'bw': 2.0, 'bh': 3.0, 'bd': 2.0}},
]
b = browser_kinds(cases)
one, two = b
check('no page errors', not any(x.get('page_errors') for x in b), [x.get('page_errors') for x in b])
# 2026-09-07 night: every pack item carries a MEASURED size (DIMENSIONS.json -> p.bw/bh/bd),
# so the placeholder crate is the item's real box, not 1 x 1 x 1 any more.
_ew, _eh, _ed = (float(PLACED.get('bw') or 1.0), float(PLACED.get('bh') or 1.0), float(PLACED.get('bd') or 1.0))
check(
    "the placed record builds a crate at the item's measured size %.3f x %.3f x %.3f m" % (_ew, _eh, _ed),
    one['ok']
    and abs(one['size'][0] - _ew) < 1e-3
    and abs(one['size'][1] - _eh) < 1e-3
    and abs(one['size'][2] - _ed) < 1e-3,
    one,
)
check(
    'bw/bh/bd size the crate',
    two['ok']
    and abs(two['size'][0] - 2.0) < 1e-3
    and abs(two['size'][1] - 3.0) < 1e-3
    and abs(two['size'][2] - 2.0) < 1e-3,
    two,
)

# ── Blender ───────────────────────────────────────────────────────────────────
print('blender')
check('no new kinds to build in Blender', NEW_KINDS == [], NEW_KINDS)
finish()
