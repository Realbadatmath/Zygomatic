# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""design_rules — the drawing's DESIGN CHECK (2026-09-08).

Why this family exists: on 2026-09-07 the assistant built a 20-storey tower
whose rooftop "infinity pool" had its water 0.4 m INSIDE the roof slab (base
54, deck 54.3), whose porte-cochère columns (3.5 m) pierced its own canopy
(soffit 2.4 m), whose six 8 m trees stood 1.5-3 m apart in two 3 x 4 m blocks
(one green blob each, straddling the entrance axis), and whose forecourt was
furnished with sphere-on-a-cylinder placeholders — and then judged its own
render "looks really nice". None of that is visible in a tool's own reply;
each is a RELATION between records. This check reads the records and names
the relations, and `done` refuses (twice) while errors remain.

No new kinds. One read-only tool: design_check(which). run_checks(d) is the
callable the done gate uses; it returns [{'sev': 'error'|'warn'|'info',
'code': str, 'text': str}].
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import (
    Drawing,
    _num,
    deck_tops,
    world_to_local,
    DECK_KINDS,
    EXT_MODULES,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []

TREE_KINDS = ('tree_deciduous', 'tree', 'tree_conifer', 'tree_palm')
PLACEHOLDER_KINDS = ('tree_deciduous', 'tree', 'tree_conifer', 'lamp_post', 'tree_line', 'forest', 'orchard')
COLUMN_KINDS = ('column_round', 'column_rect', 'column_h')
WATER_KINDS = ('pool', 'pond', 'fountain', 'canal', 'lake', 'water_plane', 'water_body')
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'door_french')
WALL_KINDS = ('wall', 'curtain_wall', 'wall_arc')
SLAB_KINDS = ('slab', 'slab_poly')
COVER_KINDS = {'canopy': 'soffit', 'awning': 'soffit', 'slab': 'slab', 'roof_flat': 'roof', 'beam_i': 'beam'}
SKIP_BURIED = set(DECK_KINDS) | {
    'pad',
    'ground',
    'terrain',
    'road',
    'path',
    'sidewalk',
    'kerb',
    'parking_bay',
    'road_curved',
    'gridline',
    'annotation',
    'dimension',
    'dim_linear',
    'dim_angle',
    'label_text',
    'markup_note',
    'site_boundary',
    'zone',
    'pilaster',
    'string_course',
    'cornice',
    'parapet_cap',
    'guide_arc',
    'guide_path',
    'guide_poly',
    'opening',
    'floor_finish',
    'skirting',
    'raised_floor',
    'ceiling',
    'suspended_ceiling',
}
PARAPET_H = 1.6  # a wall shorter than this is guarding, never a storey
AXIS_HALF_W = 2.0  # the entrance approach is a 4 m strip...
AXIS_LEN = 12.0  # ...12 m out from the door
CROWD = 0.6  # trunks closer than this x (r1 + r2) read as one crown
TREE_WORDS = ('tree', 'oak', 'pine', 'fir', 'jacaranda', 'palm', 'birch')


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _storey_of(o, H):
    base = _p(o, 'base', 0.0)
    return int(round((o['y'] - base) / H)) if H else 0


def _crown(o) -> float:
    """Crown radius of a tree record (parametric or a pack tree), else 0."""
    k = o.get('kind')
    if k in ('tree_deciduous', 'tree'):
        return _p(o, 'r_can', 3.0)
    if k == 'tree_conifer':
        return _p(o, 'r', 2.0)
    if k == 'tree_palm':
        return _p(o, 'h', 8.0) * 0.34
    if k == 'asset':
        nm = (o.get('name') or '').lower() + ' ' + str((o.get('p') or {}).get('item') or '').lower()
        if any(w in nm for w in TREE_WORDS) and 'stump' not in nm and 'root' not in nm:
            s = o.get('s') or 1.0
            return min(max(_p(o, 'bw', 2.0), _p(o, 'bd', 2.0)) * s / 2, _p(o, 'bh', 6.0) * s * 0.3)
    return 0.0


def _covers(o, x, z, loose=False) -> bool:
    p = o.get('p') or {}
    w, dd = _num(p.get('w'), 0.0), _num(p.get('d'), 0.0)
    if w <= 0 or dd <= 0:
        return False
    sc = o.get('s') or 1.0
    lx, lz = world_to_local(o, x, z)
    if loose:  # a canopy plate hangs OUTWARD from its wall: accept either frame
        return abs(lx) <= w * sc / 2 + 1e-6 and (
            abs(lz) <= dd * sc / 2 + 1e-6 or -1e-6 <= lz <= dd * sc + 1e-6 or -dd * sc - 1e-6 <= lz <= 1e-6
        )
    return abs(lx) <= w * sc / 2 + 1e-6 and abs(lz) <= dd * sc / 2 + 1e-6


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


# ── the checks ───────────────────────────────────────────────────────────────
def check_floors(d: Drawing) -> list:
    """Every storey that has walls in a group has a floor slab in that group."""
    H = d.storey_h or 2.7
    walls, slabs = {}, {}
    # 2026-09-16: a group's storey index is counted from ONE base. add_core's
    # head house carries p.base = the deck level on every record, but a tool
    # that rebuilt one of them without it (add_curtain_wall, job 71e9d42e559f)
    # put the same storey at index 0 AND 20 in the same group — a phantom
    # 'storey 0 without a slab'. Records without a base take their group's.
    gbase: dict = {}
    for o in d.objs:
        g = o.get('grp') or ''
        b = (o.get('p') or {}).get('base')
        if g and b is not None:
            try:
                gbase[g] = min(gbase.get(g, float(b)), float(b))
            except (TypeError, ValueError) as _exc:
                _zyg_log.debug('non-numeric base %r on group %s ignored: %s', b, g, _exc)

    def _st(o):
        g = o.get('grp') or ''
        if (o.get('p') or {}).get('base') is None and g in gbase and H:
            return int(round((o['y'] - gbase[g]) / H))
        return _storey_of(o, H)

    for o in d.objs:
        if o.get('hidden'):
            continue
        g = o.get('grp') or ''
        if o.get('kind') in WALL_KINDS and g:
            # 2026-09-08: add_parapet writes plain `wall` records 1.1 m tall in
            # the BUILDING's own group, one storey above the top slab — which
            # read here as "a storey with walls and no floor" and refused the
            # done gate on every building that correctly had a parapet. A wall
            # under PARAPET_H cannot enclose a habitable storey, so it is
            # guarding, not a storey. Balustrades and upstands are the same case.
            if _p(o, 'h', H) < PARAPET_H:
                continue
            walls.setdefault(g, set()).add(_st(o))
        elif o.get('kind') in SLAB_KINDS and g:
            slabs.setdefault(g, set()).add(_st(o))
        elif o.get('kind') == 'roof_flat' and g:
            # 2026-09-10: the flat roof IS the floor of the storey above it — a
            # pool basin, a roof house or a plant screen standing on the deck
            # read as "storey 20 has walls but no floor slab" on every rooftop
            # pool, and two runs spent three design_check rounds each deleting
            # the roof and adding a slab to clear a false error.
            slabs.setdefault(g, set()).add(_st(o))
    # a storey whose base sits on ANOTHER group's slab or flat roof is floored by
    # it: the stair head house stands on the tower's roof deck (2026-09-16)
    levels = []
    for o in d.objs:
        if o.get('hidden') or not (o.get('grp') or ''):
            continue
        if o.get('kind') in SLAB_KINDS:
            levels.append(_num(o.get('y'), 0.0) + _p(o, 't', 0.22))
            levels.append(_num(o.get('y'), 0.0))
        elif o.get('kind') == 'roof_flat':
            levels.append(_num(o.get('y'), 0.0))
            levels.append(_num(o.get('y'), 0.0) + _p(o, 't', 0.2))

    def _floored_by_other(g, st) -> bool:
        lvl = gbase.get(g, 0.0) + st * H
        return any(abs(lv - lvl) <= 0.35 for lv in levels)

    out = []
    for g, st in walls.items():
        if len(st) < 2:
            continue
        missing = sorted(s for s in st - slabs.get(g, set()) if not _floored_by_other(g, s))
        if missing:
            out.append(
                {
                    'sev': 'error',
                    'code': 'floors',
                    'text': f'group "{g}": storey{"s" if len(missing) > 1 else ""} '
                    f'{", ".join(str(m) for m in missing[:8])}{"…" if len(missing) > 8 else ""} '
                    f'have walls but no floor slab — add_slab per storey (draw_box makes them by default; '
                    f'never slabs=false on a habitable building)',
                }
            )
    return out


def check_buried(d: Drawing) -> list:
    """Nothing stands inside a deck: a flat roof buries anything at its base y, a
    slab anything strictly above its base and under its top."""
    groups = {}  # deck id -> {'deck', 'top', 'error': [...], 'warn': [...]}
    for o in d.objs:
        k = o.get('kind')
        if o.get('hidden') or k in SKIP_BURIED or str(k).startswith(('sculpt_', 'guide_', 'mass_')):
            continue
        y = o['y']
        for top, deck in deck_tops(d, o['x'], o['z']):
            if deck is o:
                continue
            base = deck['y']
            inside = (base <= y < top - 1e-6) if deck['kind'] == 'roof_flat' else (base + 1e-6 < y < top - 1e-6)
            if not inside:
                continue
            sev = 'error' if k in WATER_KINDS or k in ('asset', 'sun_lounger', 'umbrella') else 'warn'
            g = groups.setdefault(deck['id'], {'deck': deck, 'top': top, 'error': [], 'warn': []})
            g[sev].append((o, top - y))
            break
    out = []
    for g in groups.values():
        for sev in ('error', 'warn'):
            items = g[sev]
            if not items:
                continue
            ids = ', '.join(f'{_lbl(o)} ({dy:.2f} m in)' for o, dy in items[:4]) + (', …' if len(items) > 4 else '')
            out.append(
                {
                    'sev': sev,
                    'code': 'buried',
                    'text': f'{len(items)} object{"s" if len(items) > 1 else ""} stand{"" if len(items) > 1 else "s"} '
                    f'INSIDE {_lbl(g["deck"])} whose deck top is {g["top"]:g} m: {ids} — move them up '
                    f'(move which=<ids>, dy_storeys is in storeys; or delete and redraw without '
                    f'base_height: tools now land on the deck)',
                }
            )
    return out


def check_pools(d: Drawing) -> list:
    out = []
    for o in d.objs:
        if o.get('kind') != 'pool' or o.get('hidden'):
            continue
        raised, depth = _p(o, 'raised', 0.0), _p(o, 'depth', 1.5)
        water = o['y'] + raised - 0.1
        tops = [t for t, dk in deck_tops(d, o['x'], o['z']) if t <= o['y'] + max(0.5, raised + 0.05)]
        if not tops:
            continue  # a garden pool: the ground is its deck
        deck = max(tops)
        if water < deck - 1e-6:
            out.append(
                {
                    'sev': 'error',
                    'code': 'pool_water',
                    'text': f'{_lbl(o)}: water surface at {water:.2f} m is BELOW the deck at {deck:g} m — '
                    f'invisible. On a roof a pool is raised (add_pool(raised=depth) or leave raised '
                    f'out: auto) or sunk into a plant storey (sunk=true)',
                }
            )
        elif raised + 1e-6 < depth and not (o.get('p') or {}).get('sunk'):
            out.append(
                {
                    'sev': 'warn',
                    'code': 'pool_basin',
                    'text': f'{_lbl(o)}: the basin hangs {depth - raised:.2f} m into the storey below the deck '
                    f'— fine only in a plant storey (sunk=true); otherwise raised={depth:g}',
                }
            )
    return out


def check_columns(d: Drawing) -> list:
    """A column that runs through a canopy, slab or beam it does not carry."""
    out = []
    covers = [o for o in d.objs if o.get('kind') in COVER_KINDS and not o.get('hidden')]
    for c in d.objs:
        if c.get('kind') not in COLUMN_KINDS or c.get('hidden'):
            continue
        top = c['y'] + _p(c, 'h', 3.0)
        for cv in covers:
            if not _covers(cv, c['x'], c['z'], loose=cv['kind'] in ('canopy', 'awning')):
                continue
            cy = cv['y']
            if c['y'] + 0.3 < cy < top - 0.05:
                out.append(
                    {
                        'sev': 'error',
                        'code': 'pierce',
                        'text': f'{_lbl(c)} ({_p(c, "h", 3):g} m tall from {c["y"]:g} m) pierces '
                        f'{_lbl(cv)} whose {COVER_KINDS[cv["kind"]]} is at {cy:g} m — a column carries '
                        f'what it meets: make it {cy - c["y"]:.2f} m tall, or build the porte-cochère '
                        f'with add_canopy(columns=N, height=…) which sizes them',
                    }
                )
                break
    return out


def check_trees(d: Drawing) -> list:
    trees = [(o, _crown(o)) for o in d.objs if not o.get('hidden') and _crown(o) > 0]
    out = []
    pairs = []
    for i in range(len(trees)):
        oi, ri = trees[i]
        for j in range(i + 1, len(trees)):
            oj, rj = trees[j]
            dist = math.hypot(oi['x'] - oj['x'], oi['z'] - oj['z'])
            if dist < CROWD * (ri + rj):
                pairs.append((oi['id'], oj['id'], dist, ri + rj))
    if pairs:
        eg = '; '.join(f'{a}/{b} {dd:.1f} m apart with {rr:.1f} m of crown' for a, b, dd, rr in pairs[:3])
        out.append(
            {
                'sev': 'warn',
                'code': 'crowding',
                'text': f'{len(pairs)} tree pair{"s" if len(pairs) > 1 else ""} merge into one blob ({eg}'
                f'{"; …" if len(pairs) > 3 else ""}) — space trees at least a crown apart '
                f'(plant_trees refuses a block too small for its count)',
            }
        )
    n_ph = sum(1 for o in d.objs if o.get('kind') in PLACEHOLDER_KINDS and not o.get('hidden'))
    if n_ph:
        out.append(
            {
                'sev': 'warn',
                'code': 'placeholder',
                'text': f'{n_ph} parametric placeholder{"s" if n_ph > 1 else ""} (sphere-on-a-trunk trees / '
                f'plain lamp poles) — for anything a person sees use real models: '
                f'plant_trees(model="real"), add_street_furniture(model="real"), place_asset',
            }
        )
    return out


def _host_wall(d: Drawing, door: dict):
    """The wall a door sits in: an opening record carries no host id — it is
    re-hosted on injection — so take the wall of the same group and storey
    whose line runs through the door's centre."""
    best = None
    for w in d.objs:
        if w.get('kind') not in ('wall', 'partition') or w.get('hidden'):
            continue
        if abs(w['y'] - door['y']) > 0.5:
            continue
        L = _p(w, 'len', 4.0)
        lx, lz = world_to_local(w, door['x'], door['z'])
        if abs(lz) <= 0.3 and abs(lx) <= L / 2 + 0.3:
            score = (0 if w.get('grp') == door.get('grp') else 1, abs(lz))
            if best is None or score < best[0]:
                best = (score, w)
    return best[1] if best else None


def _door_axis(d: Drawing, door: dict):
    """(x, z, nx, nz) of a door and its OUTWARD normal, from its host wall."""
    host = _host_wall(d, door)
    if not host:
        return None
    ry = host.get('ry') or 0.0
    n1 = (-math.sin(ry), -math.cos(ry))
    n2 = (math.sin(ry), math.cos(ry))
    grp = [o for o in d.objs if o.get('grp') == host.get('grp') and o.get('kind') in WALL_KINDS]
    if grp:
        cx = sum(o['x'] for o in grp) / len(grp)
        cz = sum(o['z'] for o in grp) / len(grp)
    else:
        cx, cz = host['x'], host['z']
    vx, vz = host['x'] - cx, host['z'] - cz
    n = n1 if (n1[0] * vx + n1[1] * vz) >= 0 else n2
    return door['x'], door['z'], n[0], n[1]


def check_entrance(d: Drawing) -> list:
    out = []
    doors = [
        o for o in d.objs if o.get('kind') in DOOR_KINDS and not o.get('hidden') and o['y'] < 0.5 + _p(o, 'base', 0)
    ]

    # 2026-09-16 (job ead3aacacf55): the stair head house door on the roof deck
    # carries base = the deck level, so it passed as an 'entrance' and a roof
    # palm 7.5 m out on the deck was 'on the entrance axis'. A door that stands
    # on ANOTHER group's deck (roof or slab under it) is a roof-house door.
    def _on_deck(o) -> bool:
        try:
            for top, dk in deck_tops(d, o['x'], o['z']):
                if abs(top - o['y']) <= 0.35 and (dk.get('grp') or '') != (o.get('grp') or ''):
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False

    doors = [o for o in doors if o['y'] < 0.5 or not _on_deck(o)]
    trees = [(o, _crown(o)) for o in d.objs if not o.get('hidden') and _crown(o) > 0]
    for door in doors:
        ax = _door_axis(d, door)
        if not ax:
            continue
        x0, z0, nx, nz = ax
        for t, r in trees:
            dx, dz = t['x'] - x0, t['z'] - z0
            along = dx * nx + dz * nz
            across = abs(dx * -nz + dz * nx)
            if 0 <= along <= AXIS_LEN and across - r < AXIS_HALF_W:
                out.append(
                    {
                        'sev': 'warn',
                        'code': 'axis',
                        'text': f'{_lbl(t)} stands on the entrance axis {along:.1f} m out from {_lbl(door)} '
                        f'(crown {2 * r:.1f} m) — keep the approach clear for {AXIS_LEN:g} m and flank '
                        f'it at least 6 m off the axis',
                    }
                )
    return out


def check_scale(d: Drawing) -> list:
    """Toy-kit assets in a drawing that also holds real ones or a building."""
    AS = EXT_MODULES.get('assets_search')
    if AS is None:
        return []
    toys = []
    for o in d.objs:
        if o.get('kind') != 'asset' or o.get('hidden'):
            continue
        if AS.pack_tier(str((o.get('p') or {}).get('pack') or '')) == 'toy':
            toys.append(o)
    if not toys:
        return []
    return [
        {
            'sev': 'warn',
            'code': 'toy',
            'text': f'{len(toys)} toy-kit model{"s" if len(toys) > 1 else ""} ({", ".join(_lbl(o) for o in toys[:3])}'
            f'{", …" if len(toys) > 3 else ""}) — stylised low-poly game pieces; for a presentation use the '
            f'[real, life-size PBR] results of search_assets',
        }
    ]


OUTDOOR_KINDS = (
    'sun_lounger',
    'umbrella',
    'pool',
    'pond',
    'fountain',
    'lamp_post',
    'tree_deciduous',
    'tree',
    'tree_conifer',
    'tree_palm',
    'bench',
    'bin',
    'car',
    'van',
    'truck',
    'bus',
    'boat',
)


def check_indoors(d: Drawing) -> list:
    """Outdoor things (loungers, parasols, pools, trees, lamps, cars) standing on
    the ground INSIDE a building's footprint with storeys above them — the
    rooftop set that was placed without base_height and landed on storey 0."""
    hits = []
    for o in d.objs:
        k = o.get('kind')
        outdoor = (
            k in OUTDOOR_KINDS
            or (k == 'asset' and _crown(o) > 0)
            or (k == 'asset' and 'lamp' in (o.get('name') or '').lower())
        )
        if not outdoor or o.get('hidden'):
            continue
        above = [dk for top, dk in deck_tops(d, o['x'], o['z']) if dk['y'] > o['y'] + 0.5]
        if len(above) >= 2:  # a slab and a roof (or two storeys) over its head
            hits.append((o, len(above)))
    if not hits:
        return []
    eg = ', '.join(f'{_lbl(o)} ({n} decks above)' for o, n in hits[:4]) + (', …' if len(hits) > 4 else '')
    return [
        {
            'sev': 'error',
            'code': 'indoors',
            'text': f'{len(hits)} outdoor object{"s" if len(hits) > 1 else ""} stand{"" if len(hits) > 1 else "s"} '
            f'INSIDE a building on storey 0: {eg} — for the roof deck pass storey=N or base_height, '
            f'or move them out of the footprint',
        }
    ]


CHECKS = [
    check_floors,
    check_buried,
    check_indoors,
    check_pools,
    check_columns,
    check_trees,
    check_entrance,
    check_scale,
]


def contributed() -> list:
    """Checks other families register (2026-09-08). A family that knows a rule
    the drawing must satisfy exposes `DESIGN_CHECKS = [fn(d) -> findings]`, and
    the done gate enforces it without this file knowing the family exists —
    building_program's checklist and object_specs' clearances arrive this way."""
    out = []
    for name, mod in sorted(EXT_MODULES.items()):
        if name == 'design_rules':
            continue
        for fn in getattr(mod, 'DESIGN_CHECKS', None) or []:
            if callable(fn):
                out.append(fn)
    return out


def run_checks(d: Drawing) -> list:
    out = []
    for fn in CHECKS + contributed():
        try:
            out.extend(fn(d))
        except Exception as e:  # noqa: BLE001 — a check must never block the drawing
            out.append({'sev': 'info', 'code': 'check_error', 'text': f'{fn.__name__} failed: {e!r}'})
    order = {'error': 0, 'warn': 1, 'info': 2}
    out.sort(key=lambda f: order.get(f['sev'], 3))
    return out


def format_findings(findings: list) -> str:
    if not findings:
        return (
            'design check: no findings — floors present, nothing buried in a deck, pool water above its deck, '
            'no column pierces a plate, trees clear of each other and of the entrance axis'
        )
    ne = sum(1 for f in findings if f['sev'] == 'error')
    nw = sum(1 for f in findings if f['sev'] == 'warn')
    head = f'design check: {ne} error{"s" if ne != 1 else ""}, {nw} warning{"s" if nw != 1 else ""}'
    return head + '\n' + '\n'.join(f'- [{f["sev"].upper()}] {f["text"]}' for f in findings[:24])


def t_design_check(d: Drawing, a, which='all'):
    return format_findings(run_checks(d))


PROMPT = (
    'DESIGN CHECK: design_check() reads the whole drawing and reports relations no single tool can see — '
    "programme items that were required and never built, objects inside another one's clearance or under "
    "their spec's minimum size, "
    'storeys without a floor slab, anything standing INSIDE a slab or flat roof (a roof record at 54 m with '
    '0.3 m thickness has its deck at 54.3), pool water below its deck, columns piercing a canopy/slab, trees '
    'whose crowns merge or block the entrance axis, placeholder and toy-kit models. Call it before done; '
    'done itself refuses while errors remain (fix them; there is no force flag — an error still open when the gate gives up marks the job UNFINISHED).'
)

EXAMPLES = [
    {'ask': 'why does the rooftop pool not show up?', 'core': True, 'calls': [{'tool': 'design_check', 'args': {}}]},
    {
        'ask': 'check the drawing before handing it over',
        'core': True,
        'calls': [{'tool': 'design_check', 'args': {}}, {'tool': 'done', 'args': {'summary': '…'}}],
    },
    {
        'ask': 'a porte-cochère on the south wall o2: 10 m wide, 4 m deep, 4 m soffit, four columns, then trees flanking the drive',
        'core': True,
        'calls': [
            {
                'tool': 'add_canopy',
                'args': {
                    'wall_id': 'o2',
                    'width': 10,
                    'depth': 4,
                    'height': 4,
                    'columns': 4,
                    'material': 'mat_glass',
                    'column_material': 'pht_rough_concrete',
                },
            },
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'EW162', 'cell_to': 'FC176', 'count': 3, 'kind': 'tree_deciduous', 'height': 8},
            },
            {
                'tool': 'plant_trees',
                'args': {'cell_from': 'FK162', 'cell_to': 'FQ176', 'count': 3, 'kind': 'tree_deciduous', 'height': 8},
            },
            {
                'tool': 'add_street_furniture',
                'args': {'cells': ['FD164', 'FJ164', 'FD172', 'FJ172'], 'kind': 'lamp_post', 'height': 5},
            },
        ],
    },
]

TOOLS = [
    (
        {
            'name': 'design_check',
            'description': "Read-only check of the WHOLE drawing for design defects no single tool can see: missing items from the building programme set by plan_building; objects standing inside another object's required clearance, or under their spec's minimum size; storeys with walls but no floor slab; objects standing inside a slab or flat roof (a roof at 54 m, 0.3 thick, has its deck at 54.3); pool water below its deck (invisible) or a basin hanging into the storey below; columns that pierce a canopy, slab or beam; trees whose crowns merge into one blob or stand on the entrance axis; placeholder and toy-kit models in a presentation. Call it before done — done refuses while errors remain.",
            'input_schema': {'type': 'object', 'properties': {'which': {'type': 'string'}}, 'required': []},
        },
        t_design_check,
    ),
]
