# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""assets_search — the assistant's door to the mesh-pack catalogue.

NO new kinds. A pack asset is the studio's EXISTING kind 'asset':
`{kind: 'asset', p: {pack, item, bw, bh, bd}}` — never a path, never geometry.
The tab draws a placeholder crate of bw x bh x bd while the GLB loads
(`case 'asset'` in arGeom), so a drawing that names a pack this machine does
not have still opens.

Tools: search_assets (find the id — the model cannot guess 'kenney/castle-kit|
tree-large'), place_asset (one on a cell), place_assets_along (a row along a
polyline of cells), list_asset_packs (what is on disk at all).

The catalogue is ~7,300 items across ~70 packs and costs a few MB plus a
directory walk to assemble, so the flattened search index is built ONCE per
process into _IDX and reused — architecture_assets.catalogue() has its own
30 s cache, but re-flattening it per keystroke would not.
"""

from __future__ import annotations

import math

from zyg_workflows import architecture_assets as AA
from zyg_workflows.arch_assistant import (
    Drawing,
    parse_cell,
    cell_centre,
    cell_name,
    MATERIALS,
    _num,
    MAX_OBJECTS,
    place_height,
)

KINDS: dict = {}  # no new kinds — 'asset' is a built-in
OPENINGS: list = []

PROMPT = (
    'Pack assets (~7,300 CC0/CC-BY models stored as the kind "asset"): search_assets(query, limit) returns '
    '"pack|item" ids — ALWAYS search before you place, the ids are not guessable. place_asset(query_or_id, cell, '
    'storey, rotation_deg, scale, name) drops ONE; place_assets_along(cells, query, spacing) repeats one along a '
    'polyline; list_asset_packs() names the packs. Results are tagged [real, life-size PBR] or [toy kit]; a '
    'presentation gets REAL models only. A line ending "— 3.9 M tris — heavy" is a photoscan: over 400k '
    'triangles it is placed as its lighter _lod1 twin, or refused if none exists. explain("assets") has the detail.'
)

_IDX: dict | None = None

# ── quality tiers (2026-09-08, design rules) ─────────────────────────────────
# The catalogue mixes photoscanned life-size models with stylised game kits
# whose "tree" is 0.8 m tall. Ranked by name-hit alone, the toy kits' short
# names ("Tree", "Column") won every search and the assistant furnished a
# luxury tower's forecourt with 1 m marble-kit trees. A row now carries a
# tier, real models rank first at equal relevance, and the line says which.
REAL_PACKS = (
    'polyhaven_arch',
    'lynxsdesign/house_41',
    'blender_studio/sprite_fright_env',
    'human_bases/mpfb_scale_figures',
)
SCAN_PREFIX = 'smithsonian/'
TOY_PREFIX = ('kenney/', 'quaternius/')
TIER_RANK = {'real': 0, 'scan': 1, 'other': 2, 'toy': 3}
TIER_TAG = {
    'real': '[real, life-size PBR]',
    'scan': '[museum scan]',
    'other': '',
    'toy': '[toy kit: stylised low-poly, not for presentations]',
}


def pack_tier(pack: str) -> str:
    pk = str(pack or '')
    if pk in REAL_PACKS:
        return 'real'
    if pk.startswith(SCAN_PREFIX):
        return 'scan'
    if pk.startswith(TOY_PREFIX):
        return 'toy'
    return 'other'


def _dims(it: dict) -> tuple:
    """Bounding size of a catalogue item. The catalogue carries no dimensions
    today (p is {pack, item}); if a pack ever ships them, they are read here."""
    p = it.get('p') or {}
    for trio in (('bw', 'bh', 'bd'), ('w', 'h', 'd'), ('sx', 'sy', 'sz')):
        if all(k in p for k in trio):
            v = [round(float(_num(p[k], 1.0)) or 1.0, 3) for k in trio]
            if all(x > 0 for x in v):
                return tuple(v)
    return (1.0, 1.0, 1.0)


# ── the triangle budget (2026-09-11, live job 94f5813b) ─────────────────────
# That job's scene was 15.66 M triangles, and 15.5 M of it was four copies of
# one photoscanned jacaranda — 3,863,832 triangles each. Nothing could see
# that coming: the catalogue reported a name, a pack and a size, and a 3.9 M
# model looks exactly like a 12 k one in a search result. DIMENSIONS.json now
# carries 'tris', every result line says so, heavy models rank last, and
# nothing over the budget is PLACED while a decimated stand-in exists.
TRI_BUDGET = AA.TRI_BUDGET  # 400,000 per placement
HEAVY_TRIS = 500_000  # ...and this is where a line says so


def _tris(it: dict) -> int:
    n = (it.get('p') or {}).get('tris')
    return int(n) if isinstance(n, (int, float)) and n > 0 else 0


def _tri_tag(n: int) -> str:
    if not n or n < HEAVY_TRIS:
        return ''
    return f' — {n / 1e6:.1f} M tris — heavy' if n >= 1e6 else f' — {n // 1000} k tris — heavy'


def lod_row(r: dict) -> dict | None:
    """The catalogue row of `r`'s decimated stand-in, if one has been built."""
    return _index()['by_id'].get(f'{r["pack"]}|{AA.lod_stem(r["item"])}')


def within_budget(r: dict) -> tuple:
    """(row_to_place, refusal). The row is `r` itself when it is light enough,
    its _lod1 when it is not, and None when it is heavy and has no stand-in."""
    if r is None or r.get('tris', 0) <= TRI_BUDGET:
        return r, ''
    lod = lod_row(r)
    if lod is not None and lod.get('tris', 0) <= TRI_BUDGET:
        return lod, ''
    return None, (
        f'refused: {r["id"]} is {r.get("tris", 0):,} tris (budget {TRI_BUDGET // 1000}k) — '
        'no LOD exists; run arch_asset_lod.py'
    )


def _index() -> dict:
    global _IDX
    if _IDX is None:
        cat = AA.catalogue()
        rows, packs = [], []
        for g in cat.get('groups') or []:
            label = str(g.get('g') or g.get('pack') or '')
            items = g.get('items') or []
            packs.append(
                {
                    'id': str(g.get('pack') or label),
                    'label': label,
                    'n': len(items),
                    'licence': str(g.get('licence') or ''),
                    'attrib': bool(g.get('attrib')),
                }
            )
            for it in items:
                p = it.get('p') or {}
                name = str(it.get('n') or '')
                pk = str(p.get('pack') or g.get('pack') or '')
                rows.append(
                    {
                        'id': str(it.get('id') or ''),
                        'n': name,
                        'label': label,
                        'pack': pk,
                        'tier': pack_tier(pk),
                        'item': str(p.get('item') or ''),
                        'size': _dims(it),
                        'tris': _tris(it),
                        'hay': f'{name} {label} {it.get("note") or ""}'.lower(),
                    }
                )
        packs.sort(key=lambda q: -q['n'])
        _IDX = {'rows': rows, 'packs': packs, 'by_id': {r['id']: r for r in rows if r['id']}}
    return _IDX


def _search(query: str, limit: int = 12) -> list:
    idx = _index()
    words = [w for w in str(query or '').lower().replace('_', ' ').replace('-', ' ').split() if w]
    if not words:
        return []
    scored = []
    for r in idx['rows']:
        # a whole-word hit in the NAME outranks a substring hit in the note:
        # "tree" must not surface "street rat" or a trash bag tagged 'tree'
        name_words = r['n'].lower().replace('_', ' ').replace('-', ' ').split()
        name_hit = sum(1 for w in words if w in name_words)
        sub_hit = sum(1 for w in words if w in r['hay'])
        if not sub_hit:
            continue
        score = name_hit * 3 + sub_hit
        # at equal relevance and tier the lighter model wins: a stand-in that
        # can actually be placed must outrank the 3.9 M-triangle original
        heavy = 1 if r.get('tris', 0) > TRI_BUDGET else 0
        scored.append((-score, TIER_RANK.get(r.get('tier'), 2), heavy, len(r['n']), r['n'].lower(), r))
    scored.sort(key=lambda t: t[:5])
    return [t[5] for t in scored[: max(1, min(60, int(limit or 12)))]]


def real_only(rows: list) -> list:
    return [r for r in rows if r.get('tier') == 'real']


def find_real(query: str, min_h: float = 0.0, max_h: float = 1e9, limit: int = 12) -> list:
    """Life-size models matching `query` whose height lies in [min_h, max_h]."""
    return [r for r in real_only(_search(query, 60)) if min_h <= r['size'][1] <= max_h][:limit]


def _resolve(query_or_id: str) -> dict | None:
    q = str(query_or_id or '').strip()
    if not q:
        return None
    row = _index()['by_id'].get(q)
    if row:
        return row
    hits = _search(q, 1)
    return hits[0] if hits else None


def _line(r: dict) -> str:
    w, h, dd = r['size']
    tag = TIER_TAG.get(r.get('tier') or 'other', '')
    return (
        f'{r["id"]} — {r["n"]} ({r["label"]}) {w:g}x{h:g}x{dd:g} m'
        + (' ' + tag if tag else '')
        + _tri_tag(r.get('tris', 0))
    )


def _params(r: dict) -> dict:
    w, h, dd = r['size']
    p = {'pack': r['pack'], 'item': r['item'], 'bw': w, 'bh': h, 'bd': dd}
    if r.get('tris'):
        p['tris'] = int(r['tris'])
    return p


def _mat(m, default='mat_concrete'):
    return m if m in MATERIALS else default


# ── tools ───────────────────────────────────────────────────────────────────
def t_search_assets(d: Drawing, a, query, limit=12):
    hits = _search(query, limit)
    if not hits:
        return (
            f'nothing matches "{query}" among the {len(_index()["rows"])} pack assets — '
            'try one plain word (chair, tree, car, door)'
        )
    head = f'{len(hits)} match "{query}", as "pack|item, name (pack), size":'
    return head + '\n' + '\n'.join(_line(r) for r in hits)


def t_place_asset(d: Drawing, a, query_or_id, cell, storey=0, rotation_deg=0, scale=1.0, name=None, material=''):
    r = _resolve(query_or_id)
    if r is None:
        return f'refused: nothing in the packs matches "{query_or_id}" — call search_assets first'
    r, why = within_budget(r)
    if r is None:
        return why
    cx, cz = cell_centre(*parse_cell(cell))
    s = _num(scale, 1.0) or 1.0
    if s <= 0 or s > 100:
        return 'refused: scale must be between 0 and 100'
    if len(d.objs) >= MAX_OBJECTS:
        return f'refused: the drawing is at the {MAX_OBJECTS} object ceiling'
    st = int(_num(storey, 0))
    # storey 0 stands on the ground under the cell; an upper storey on the deck
    # there (place_height lifts a base that lies inside a slab or a flat roof)
    y = place_height(d, cx, cz, None if st == 0 else st * d.storey_h)
    rec = d.new(
        'asset',
        _params(r),
        cx,
        cz,
        y,
        math.radians(_num(rotation_deg, 0.0)),
        _mat(material),
        name=name or r['n'],
        grp='assets',
    )
    rec['s'] = round(float(s), 4)
    return (
        f'placed {rec["id"]} "{r["n"]}" ({r["id"]}) on {cell_name(*parse_cell(cell))} storey {st}'
        + (f', turned {_num(rotation_deg, 0.0):g}°' if _num(rotation_deg, 0.0) else '')
        + (f', scale {s:g}' if abs(s - 1.0) > 1e-6 else '')
    )


def t_place_assets_along(
    d: Drawing, a, cells, query, spacing=3, storey=0, scale=1.0, rotation_deg=None, name=None, material=''
):
    if not isinstance(cells, list) or len(cells) < 2:
        return 'refused: cells must be a list of at least two cells, like ["C4", "C14", "M14"]'
    r = _resolve(query)
    if r is None:
        return f'refused: nothing in the packs matches "{query}" — call search_assets first'
    # a row repeats one model tens of times: the budget matters MORE here
    r, why = within_budget(r)
    if r is None:
        return why
    pts = [cell_centre(*parse_cell(c)) for c in cells]
    segs = [
        (pts[i], pts[i + 1], math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]))
        for i in range(len(pts) - 1)
    ]
    total = sum(s[2] for s in segs)
    if total < 0.5:
        return 'refused: those cells are all the same place — give a polyline at least 0.5 m long'
    sp = _num(spacing, 3.0)
    if sp < 0.25 or sp > 100:
        return 'refused: spacing must be between 0.25 and 100 m'
    n = min(400, int(total / sp) + 1)
    if len(d.objs) + n > MAX_OBJECTS:
        return f'refused: that is {n} objects past the {MAX_OBJECTS} ceiling'
    s = _num(scale, 1.0) or 1.0
    st = int(_num(storey, 0))
    grp = str(name or f'{r["n"]} row')
    ids = []
    for k in range(n):
        u = k * sp
        for i, ((ax, az), (bx, bz), L) in enumerate(segs):
            if u <= L or i == len(segs) - 1:
                f = min(1.0, (u / L) if L > 1e-9 else 0.0)
                x, z = ax + (bx - ax) * f, az + (bz - az) * f
                ry = (
                    math.radians(_num(rotation_deg, 0.0))
                    if rotation_deg is not None
                    else math.atan2(-(bz - az), bx - ax)
                )
                break
            u -= L
        rec = d.new('asset', _params(r), x, z, st * d.storey_h, ry, _mat(material), name=f'{r["n"]} {k + 1}', grp=grp)
        rec['s'] = round(float(s), 4)
        ids.append(rec['id'])
    return (
        f'placed {n} x "{r["n"]}" ({r["id"]}) {ids[0]}..{ids[-1]} along {" -> ".join(str(c) for c in cells)} '
        f'every {sp:g} m ({total:.1f} m of polyline), group "{grp}"'
    )


def t_list_asset_packs(d: Drawing, a, limit=30):
    packs = _index()['packs']
    lim = max(1, min(200, int(_num(limit, 30))))
    out = [f'{p["label"]} — {p["n"]} items ({p["id"]}, {p["licence"] or "CC0"})' for p in packs[:lim]]
    tail = f'\n... and {len(packs) - lim} more packs' if len(packs) > lim else ''
    return (
        f'{len(packs)} asset packs, {len(_index()["rows"])} items in total — '
        'search_assets(word) finds items across all of them:\n' + '\n'.join(out) + tail
    )


TOOLS = [
    (
        {
            'name': 'search_assets',
            'description': 'Find pack models by words (name, pack, note) and get their "pack|item" ids with real sizes; real life-size models rank first and every line is tagged [real, life-size PBR] or [toy kit]. ALWAYS search before place_asset. Say "tree", "lamp", "sofa", "car", "man" — one plain word works best.',
            'input_schema': {
                'type': 'object',
                'properties': {'query': {'type': 'string'}, 'limit': {'type': 'integer'}},
                'required': ['query'],
            },
        },
        t_search_assets,
    ),
    (
        {
            'name': 'place_asset',
            'description': 'Place ONE pack asset on a cell: an exact id from search_assets, or words (the best match is used). storey 0 is the ground floor, rotation_deg turns it on the plan, scale multiplies it. Use for a single chair, tree, car, statue.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query_or_id': {'type': 'string'},
                    'cell': {'type': 'string'},
                    'storey': {'type': 'integer'},
                    'rotation_deg': {'type': 'number'},
                    'scale': {'type': 'number'},
                    'name': {'type': 'string'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['query_or_id', 'cell'],
            },
        },
        t_place_asset,
    ),
    (
        {
            'name': 'place_assets_along',
            'description': 'Repeat one pack asset every `spacing` metres along the polyline through a list of cells. Use for street trees, bollards, parked cars, lamp posts, fence posts. Each copy faces along the line unless rotation_deg is given.',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'cells': {'type': 'array', 'items': {'type': 'string'}},
                    'query': {'type': 'string'},
                    'spacing': {'type': 'number'},
                    'storey': {'type': 'integer'},
                    'scale': {'type': 'number'},
                    'rotation_deg': {'type': 'number'},
                    'name': {'type': 'string'},
                    'material': {'type': 'string', 'enum': MATERIALS},
                },
                'required': ['cells', 'query'],
            },
        },
        t_place_assets_along,
    ),
    (
        {
            'name': 'list_asset_packs',
            'description': 'The mesh packs available on this machine, largest first, with the item count and licence of each. Use when the user asks what models exist rather than for a particular thing.',
            'input_schema': {'type': 'object', 'properties': {'limit': {'type': 'integer'}}, 'required': []},
        },
        t_list_asset_packs,
    ),
]

EXAMPLES = [
    {
        'ask': 'put a dining table and four chairs in the living room around F12',
        'calls': [
            {'tool': 'search_assets', 'args': {'query': 'table chair', 'limit': 10}},
            {'tool': 'place_asset', 'args': {'query_or_id': 'dining table', 'cell': 'F12'}},
            {'tool': 'place_asset', 'args': {'query_or_id': 'chair', 'cell': 'E12', 'rotation_deg': 90}},
        ],
    },
    {
        'ask': 'street trees along the kerb from C4 to C24, one every 8 metres',
        'calls': [{'tool': 'place_assets_along', 'args': {'cells': ['C4', 'C24'], 'query': 'tree', 'spacing': 8}}],
    },
    {
        'ask': 'park a car in front of the house on H30',
        'calls': [{'tool': 'place_asset', 'args': {'query_or_id': 'car', 'cell': 'H30', 'rotation_deg': 90}}],
    },
    {'ask': 'what asset packs do you have?', 'calls': [{'tool': 'list_asset_packs', 'args': {}}]},
    {
        'ask': 'bollards every 1.5 m along the quay from D40 through P40 to P52',
        'calls': [
            {'tool': 'place_assets_along', 'args': {'cells': ['D40', 'P40', 'P52'], 'query': 'bollard', 'spacing': 1.5}}
        ],
    },
]
