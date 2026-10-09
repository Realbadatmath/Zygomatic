# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""deck_rules — the roof deck read as ONE room, not as a list of records (2026-09-16)

water_leisure.check_infinity_pools asks whether the pool is a pool: deep enough,
wide enough, a weir on one side, steps on the other, a guard along the water. It
never looks up. So a pool can pass every one of those checks while standing
0.6 m off a lift shaft, with no way round it, its trough hanging past the facade,
an air-handling unit parked in the view, a head house with no door and a stair
that arrives over a void.

Those are all the same kind of fault: a relation between the pool and the REST of
the top deck. This family owns no kinds and no tools; it measures nine of them.

  pool core       the pool keeps 1.5 m clear of every core that reaches the deck.
  walkway         every non-weir side has 1.2 m of deck to walk on.
  weir edge       the weir is ON the edge (<= 0.6 m) and the trough is inside it.
  tank clash      the plant zone under the pool misses the cores; the basin
                  hanging into the storey below misses the corridor (warn).
  loungers        furniture is off the water, out of the weir strip, and faces
                  the view (warn).
  plant           rooftop plant stands on the side away from the view.
  guarding        every envelope edge of the top deck is guarded over 95% of its
                  length — measured by analyse_geometry.coverage, the same metre
                  rule finish_rules.check_deck_guarding uses, and SILENT on any
                  side that check has already named.
  head house      a head house on the deck has a door in it.
  stair arrival   the top stair's approach has deck floor under it.

Plan axes as everywhere in the studio: column letters along +X, rows along +Z,
north = -Z. The deck of a group is env['top_deck']; a record is ON it when its
base y is within 0.35 m of that (a deck-level pool is sunk, so its basin hangs
below while its record sits on the deck).
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num

KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
PROMPT = ''

DECK_TOL = 0.35  # m of slop when a record is matched to the deck level
IN_MARGIN = 1.0  # m outward a record may sit and still belong to the deck
CORE_CLEAR = 1.5  # m of deck between the pool and any core
WALK_MIN = 1.2  # m of walkway on every side that is not the weir
WEIR_INSET = 0.6  # m the weir coping may sit back from the deck edge
PLANT_CLEAR = 2.0  # m between rooftop plant and the water
LOUNGER_CLEAR = 0.5  # m between a lounger and the water
FACE_TOL = math.radians(30)
GUARD_COVER = 0.95  # the brief's "95% of its length"
GUARD_H = 1.1  # m — finish_rules.DECK_GUARD_H, read at run time
EDGE_TOL = 0.6  # m a deck edge may sit off the envelope line
BASIN_TOL = 0.05  # m of basin below the deck before it is "hanging"
MAX_FINDINGS = 8

SHAFT_KIND = 'elevator_shaft'
STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')
WALL_KINDS = ('wall', 'curtain_wall')
DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'sliding_door', 'door_glass', 'doorway')
PLANT_KINDS = frozenset({'hvac_unit', 'water_tank', 'antenna', 'satellite_dish', 'solar_panel', 'chimney'})
LOUNGE_KINDS = frozenset({'sun_lounger', 'umbrella', 'parasol', 'deck_chair', 'daybed'})
# a parasol has no front: only the seats are asked to face the view
FACE_KINDS = LOUNGE_KINDS - {'umbrella', 'parasol'}
POOL_KINDS = ('pool',)
HEAD_HOUSE = ' head house'

WORD = {'n': 'north', 's': 'south', 'e': 'east', 'w': 'west'}
OPP = {'n': 's', 's': 'n', 'e': 'w', 'w': 'e'}
SEV_RANK = {'error': 0, 'warn': 1, 'info': 2}


# ── modules, fetched lazily: load_extensions runs alphabetically ────────────
def _m(name):
    return A.EXT_MODULES.get(name)


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _bbox(o):
    return _m('envelope_rules').bbox_of(o)


def _centre(bb):
    return (bb[0] + bb[2]) / 2.0, (bb[1] + bb[3]) / 2.0


def _gap(a, b) -> float:
    """Plan distance between two axis-aligned rectangles; 0 when they overlap."""
    dx = max(b[0] - a[2], a[0] - b[2], 0.0)
    dz = max(b[1] - a[3], a[1] - b[3], 0.0)
    return math.hypot(dx, dz)


def _overlap(a, b, tol=0.0) -> bool:
    return (min(a[2], b[2]) - max(a[0], b[0]) > tol) and (min(a[3], b[3]) - max(a[1], b[1]) > tol)


def _towards(frm, to) -> str:
    """The compass word for the way from rectangle `frm` to rectangle `to`."""
    fx, fz = _centre(frm)
    tx, tz = _centre(to)
    dx, dz = tx - fx, tz - fz
    if abs(dx) >= abs(dz):
        return WORD['e'] if dx > 0 else WORD['w']
    return WORD['s'] if dz > 0 else WORD['n']


def _edge_val(env, s) -> float:
    return {'n': env['zmin'], 's': env['zmax'], 'w': env['xmin'], 'e': env['xmax']}[s]


def _side_clear(env, bb, s, pad=0.0) -> float:
    """m of deck between the padded rectangle and the envelope edge on side `s`.
    Negative when the rectangle pokes past the edge."""
    if s == 'n':
        return (bb[1] - pad) - env['zmin']
    if s == 's':
        return env['zmax'] - (bb[3] + pad)
    if s == 'w':
        return (bb[0] - pad) - env['xmin']
    return env['xmax'] - (bb[2] + pad)


def _weir_side(o) -> str:
    """The side the water falls away towards, as a single letter."""
    p = o.get('p') or {}
    raw = str(p.get('inf') or p.get('infinity') or '').strip().lower()
    W = _m('water_leisure')
    table = getattr(W, '_INF', None) if W is not None else None
    s = table.get(raw, raw) if isinstance(table, dict) else raw
    return s if s in WORD else ''


def _face_ry(s):
    """The ry that looks out over side `s` — water_leisure._FACE_X is the map
    (the brief calls it _INF; _INF is the string normaliser, _FACE_X is the
    side -> ry table at water_leisure.py:197)."""
    W = _m('water_leisure')
    table = getattr(W, '_FACE_X', None) if W is not None else None
    if isinstance(table, dict) and s in table:
        return _num(table[s], 0.0)
    return {'n': math.pi / 2, 's': -math.pi / 2, 'e': 0.0, 'w': math.pi}.get(s)


def _angle_off(a, b) -> float:
    """Smallest absolute angle between two headings, in radians."""
    return abs((a - b + math.pi) % (2 * math.pi) - math.pi)


def _storey_of(env, y, storey_h) -> int:
    if storey_h <= 0:
        return 0
    return int(round((y - _num(env.get('y0'), 0.0)) / storey_h))


# ── the deck itself ─────────────────────────────────────────────────────────
def _decks(d: Drawing) -> list:
    """[(env, recs)] — one entry per building group that has a top deck. A head
    house's own lid is 2.7 m above the deck and is not a deck."""
    E = _m('envelope_rules')
    out = []
    for g, env in (E.envelopes(d) or {}).items():
        if str(g).endswith(HEAD_HOUSE):
            continue
        top = env.get('top_deck')
        if top is None:
            continue
        recs = []
        for o in d.objs:
            if o.get('hidden'):
                continue
            if abs(_num(o.get('y'), 0.0) - _num(top, 0.0)) > DECK_TOL:
                continue
            cx, cz = _centre(_bbox(o))
            if E.inside(env, cx, cz, IN_MARGIN):
                recs.append(o)
        out.append((env, recs))
    return out


def _pools(recs) -> list:
    return [o for o in recs if str(o.get('kind') or '') in POOL_KINDS]


def _cores(d: Drawing, env, top: float, storey_h: float) -> list:
    """Every core that reaches the deck, one entry per core group:
    {'what', 'bb', 'id'}. A stair that stops at storey 3 is not in the way of a
    pool on storey 20, so a core counts only when some record of it stands
    within one storey of the deck."""
    E = _m('envelope_rules')
    groups = {}
    for o in d.objs:
        if o.get('hidden'):
            continue
        k = str(o.get('kind') or '')
        grp = str(o.get('grp') or '')
        if k == SHAFT_KIND:
            what = 'lift shaft'
        elif k in STAIR_KINDS:
            what = 'stair'
        elif grp.endswith(HEAD_HOUSE) and k in WALL_KINDS:
            what = 'head house wall'
        else:
            continue
        bb = _bbox(o)
        cx, cz = _centre(bb)
        if not E.inside(env, cx, cz, IN_MARGIN):
            continue
        rec = groups.get(grp or o['id'])
        if rec is None:
            rec = {'what': what, 'bb': list(bb), 'top': -1e9, 'id': o['id']}
            groups[grp or o['id']] = rec
        rec['bb'] = [
            min(rec['bb'][0], bb[0]),
            min(rec['bb'][1], bb[1]),
            max(rec['bb'][2], bb[2]),
            max(rec['bb'][3], bb[3]),
        ]
        y = _num(o.get('y'), 0.0)
        if y > rec['top']:
            rec['top'], rec['id'], rec['what'] = y, o['id'], what
    reach = top - max(storey_h, 0.1) - DECK_TOL
    return [v for v in groups.values() if v['top'] >= reach]


# ── 1. the pool keeps clear of the cores ────────────────────────────────────
def _check_pool_core(d, env, recs, storey_h) -> list:
    out = []
    pools = _pools(recs)
    if not pools:
        return out
    cores = _cores(d, env, _num(env['top_deck'], 0.0), storey_h)
    for o in pools:
        bb = _bbox(o)
        for c in cores:
            g = _gap(bb, c['bb'])
            if g >= CORE_CLEAR - 1e-9:
                continue
            way = _towards(c['bb'], bb)
            out.append(
                {
                    'sev': 'error',
                    'code': 'deck_pool_core',
                    'text': (
                        f'pool {o["id"]} is {g:.2f} m from {c["what"]} {c["id"]} — {CORE_CLEAR:g} m '
                        f'clear is needed to walk round the core: '
                        f'add_infinity_pool(cell_from, cell_to) further {way}'
                    ),
                }
            )
            break  # one finding per object
    return out


# ── 2. a walkway on every side but the weir ─────────────────────────────────
def _check_walkway(d, env, recs) -> list:
    out = []
    for o in _pools(recs):
        weir = _weir_side(o)
        if not weir:
            continue
        bb = _bbox(o)
        cop = _p(o, 'coping', 0.0)
        worst = None
        for s in ('n', 's', 'e', 'w'):
            if s == weir:
                continue
            clear = _side_clear(env, bb, s, cop)
            if clear >= WALK_MIN - 1e-9:
                continue
            if worst is None or clear < worst[1]:
                worst = (s, clear)
        if worst is None:
            continue
        s, clear = worst
        out.append(
            {
                'sev': 'error',
                'code': 'deck_walkway',
                'text': (
                    f'pool {o["id"]} leaves {clear:.2f} m between its coping and the {WORD[s]} deck '
                    f'edge — a walkway is {WALK_MIN:g} m: move the water off that edge with '
                    f'add_infinity_pool(cell_from, cell_to) or give the pool fewer cells'
                ),
            }
        )
    return out


# ── 3. the weir is ON the edge, and the trough is inside it ─────────────────
def _check_weir_edge(d, env, recs) -> list:
    E = _m('envelope_rules')
    out = []
    for o in _pools(recs):
        weir = _weir_side(o)
        if not weir:
            continue
        bb = _bbox(o)
        cop = _p(o, 'coping', 0.0)
        # the trough must not cross the facade line
        corners = ((bb[0], bb[1]), (bb[2], bb[1]), (bb[2], bb[3]), (bb[0], bb[3]))
        if not all(E.inside(env, x, z, 0.05) for x, z in corners):
            over = -min(_side_clear(env, bb, s) for s in ('n', 's', 'e', 'w'))
            out.append(
                {
                    'sev': 'error',
                    'code': 'deck_weir_edge',
                    'text': (
                        f'pool {o["id"]} hangs {over:.2f} m past the {WORD[weir]} facade of '
                        f'{env["group"]} — an infinity trough is carried by the deck, not by the air: '
                        f'add_infinity_pool(cell_from, cell_to) inside the plate'
                    ),
                }
            )
            continue
        back = _side_clear(env, bb, weir, cop)
        if abs(back) <= WEIR_INSET + 1e-9:
            continue
        out.append(
            {
                'sev': 'error',
                'code': 'deck_weir_edge',
                'text': (
                    f'pool {o["id"]} has its infinity edge {back:.2f} m back from the {WORD[weir]} '
                    f'deck edge — the water must read as falling off the building '
                    f'(<= {WEIR_INSET:g} m): add_infinity_pool(cell_from, cell_to) reaching the '
                    f'{WORD[weir]} edge'
                ),
            }
        )
    return out


# ── 4. the tank zone below, and the basin hanging into it ───────────────────
def _check_tank_clash(d, env, recs, storey_h) -> list:
    out = []
    pools = _pools(recs)
    if not pools:
        return out
    E = _m('envelope_rules')
    top = _num(env['top_deck'], 0.0)
    below_lo, below_hi = top - storey_h - DECK_TOL, top - DECK_TOL
    zones = []
    for o in d.objs:
        if o.get('hidden') or str(o.get('kind') or '') != 'zone':
            continue
        y = _num(o.get('y'), 0.0)
        if not (below_lo <= y <= below_hi):
            continue
        cx, cz = _centre(_bbox(o))
        if E.inside(env, cx, cz, IN_MARGIN):
            zones.append(o)
    if not zones:
        return out
    cores = _cores(d, env, top, storey_h)
    for pool in pools:
        pbb = _bbox(pool)
        for z in zones:
            nm = str(z.get('name') or '').lower()
            zbb = _bbox(z)
            if 'tank' in nm and _overlap(zbb, pbb, 0.05):
                for c in cores:
                    if not _overlap(zbb, c['bb'], 0.05):
                        continue
                    out.append(
                        {
                            'sev': 'error',
                            'code': 'deck_tank_clash',
                            'text': (
                                f'plant zone {z["id"]} under pool {pool["id"]} stands in the plan of '
                                f'{c["what"]} {c["id"]} — the tank and the core cannot share the '
                                f'storey: move("{z["id"]}", dx_cells=..., dz_cells=...)'
                            ),
                        }
                    )
                    break
                continue
            hang = _p(pool, 'depth', 0.0) - _p(pool, 'raised', 0.0)
            if hang <= BASIN_TOL or 'corridor' not in nm:
                continue
            if _overlap(zbb, pbb, 0.05):
                out.append(
                    {
                        'sev': 'warn',
                        'code': 'deck_tank_clash',
                        'text': (
                            f'the basin of pool {pool["id"]} hangs {hang:.2f} m into the storey below '
                            f'and cuts corridor zone {z["id"]} — raise the pool '
                            f'(add_infinity_pool(..., level="raised")) or move the corridor'
                        ),
                    }
                )
    return out


# ── 5. furniture: off the water, out of the weir strip, facing the view ─────
def _check_loungers(d, env, recs) -> list:
    out = []
    pools = _pools(recs)
    if not pools:
        return out
    pool = max(pools, key=lambda o: (_bbox(o)[2] - _bbox(o)[0]) * (_bbox(o)[3] - _bbox(o)[1]))
    weir = _weir_side(pool)
    pbb = _bbox(pool)
    want = _face_ry(weir) if weir else None
    # the strip between the weir and the deck edge, as wide as the pool itself
    strip = {
        's': (pbb[0], pbb[3], pbb[2], env['zmax']),
        'n': (pbb[0], env['zmin'], pbb[2], pbb[1]),
        'e': (pbb[2], pbb[1], env['xmax'], pbb[3]),
        'w': (env['xmin'], pbb[1], pbb[0], pbb[3]),
    }.get(weir)
    turned = []
    for o in recs:
        if str(o.get('kind') or '') not in LOUNGE_KINDS:
            continue
        bb = _bbox(o)
        g = _gap(bb, pbb)
        if g < LOUNGER_CLEAR - 1e-9:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'deck_lounger_placement',
                    'text': (
                        f'{o["kind"]} {o["id"]} stands {g:.2f} m from the water of {pool["id"]} — '
                        f'{LOUNGER_CLEAR:g} m of wet deck is the minimum: '
                        f'move("{o["id"]}", dx_cells=..., dz_cells=...)'
                    ),
                }
            )
            continue
        if strip is not None and _overlap(bb, strip, 0.05):
            out.append(
                {
                    'sev': 'warn',
                    'code': 'deck_lounger_placement',
                    'text': (
                        f'{o["kind"]} {o["id"]} stands in the {WORD[weir]} weir strip between the pool '
                        f'and the deck edge — that strip is the view, not a terrace: '
                        f'move("{o["id"]}", dz_cells=...) behind the pool'
                    ),
                }
            )
            continue
        if want is None or str(o.get('kind') or '') not in FACE_KINDS:
            continue
        off = _angle_off(_num(o.get('ry'), 0.0), want)
        if off > FACE_TOL:
            turned.append(o['id'])
    if turned:
        ids = ', '.join(turned[:4]) + (f' and {len(turned) - 4} more' if len(turned) > 4 else '')
        out.append(
            {
                'sev': 'warn',
                'code': 'deck_lounger_placement',
                'text': (
                    f'{len(turned)} deck seats ({ids}) face away from the {WORD[weir]} view — '
                    f'a lounger by an infinity pool looks over the weir (ry {want:.4f}): '
                    f'rotate("{turned[0]}", ...) to face {WORD[weir]}'
                ),
            }
        )
    return out


# ── 6. rooftop plant belongs on the side away from the view ─────────────────
def _check_plant_side(d, env, recs) -> list:
    out = []
    pools = _pools(recs)
    if not pools:
        return out
    pool = pools[0]
    weir = _weir_side(pool)
    if not weir:
        return out
    away = OPP[weir]
    pbb = _bbox(pool)
    for o in recs:
        if str(o.get('kind') or '') not in PLANT_KINDS:
            continue
        bb = _bbox(o)
        cx, cz = _centre(bb)
        behind = {'n': cz < pbb[1], 's': cz > pbb[3], 'w': cx < pbb[0], 'e': cx > pbb[2]}[away]
        g = _gap(bb, pbb)
        if behind and g >= PLANT_CLEAR - 1e-9:
            continue
        why = f'stands {g:.2f} m from the water' if behind else f'stands on the {WORD[weir]} view side of the pool'
        out.append(
            {
                'sev': 'error',
                'code': 'deck_plant_side',
                'text': (
                    f'{o["kind"]} {o["id"]} {why} — rooftop plant belongs {WORD[away]} of the pool and '
                    f'{PLANT_CLEAR:g} m clear of it: move("{o["id"]}", dx_cells=..., dz_cells=...), or '
                    f'delete("{o["id"]}") and add_rooftop_plant(group="{env["group"]}", '
                    f'kinds=["{o["kind"]}"]) — add_rooftop_plant takes no side argument '
                    f'(mep_services.py:329)'
                ),
            }
        )
    return out


# ── 7. every edge of the top deck is guarded ────────────────────────────────
def _on_edge(env, p0, p1) -> str:
    for s, axis in (('n', 1), ('s', 1), ('w', 0), ('e', 0)):
        val = _edge_val(env, s)
        if abs(p0[axis] - val) <= EDGE_TOL and abs(p1[axis] - val) <= EDGE_TOL:
            return s
    return ''


def _finish_sides(d) -> set:
    """The sides finish_rules.check_deck_guarding has already reported — this
    check must not say the same thing twice."""
    FR = _m('finish_rules')
    out = set()
    if FR is None:
        return out
    for f in FR.check_deck_guarding(d) or []:
        text = str(f.get('text') or '')
        for s, w in WORD.items():
            if f'its {w} edge' in text:
                out.add(s)
    return out


def _check_guard_all(d, env, done) -> list:
    G = _m('analyse_geometry')
    FR = _m('finish_rules')
    if G is None:
        return []
    min_h = _num(getattr(FR, 'DECK_GUARD_H', GUARD_H), GUARD_H) if FR is not None else GUARD_H
    top = _num(env['top_deck'], 0.0)
    solids = G.solids(d)
    guards = [o for o in solids if G.is_guard_kind(o)]
    acc = {s: [0.0, 0.0] for s in WORD}
    for o in solids:
        if o.get('kind') not in G.DECK:
            continue
        if abs(G.deck_top(o) - top) > DECK_TOL:
            continue
        rect = G.corners(o)
        for k in range(4):
            p0, p1 = rect[k], rect[(k + 1) % 4]
            L = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
            if L < 0.2:
                continue
            s = _on_edge(env, p0, p1)
            if not s:
                continue
            frac = _num(G.coverage(p0, p1, guards, top, min_h)[0], 0.0)
            acc[s][0] += L
            acc[s][1] += L * frac
    out = []
    for s in ('n', 'e', 's', 'w'):
        total, cov = acc[s]
        if total < 0.2 or s in done:
            continue
        frac = cov / total
        if frac >= GUARD_COVER - 1e-9:
            continue
        out.append(
            {
                'sev': 'error',
                'code': 'deck_guard_all',
                'text': (
                    f'the {WORD[s]} edge of the {env["group"]} deck is {total:.2f} m long and guarded '
                    f'over {round(frac * 100)}% of it — every side of an occupied deck needs '
                    f'{round(GUARD_COVER * 100)}% at {min_h:g} m: '
                    f'add_parapet("{env["group"]}", height={min_h:g})'
                ),
            }
        )
    return out


# ── 8. a head house you can get out of ──────────────────────────────────────
def _check_headhouse_door(d, env, recs, storey_h) -> list:
    E = _m('envelope_rules')
    top = _num(env['top_deck'], 0.0)
    houses = {}
    for o in d.objs:
        if o.get('hidden'):
            continue
        grp = str(o.get('grp') or '')
        if not grp.endswith(HEAD_HOUSE):
            continue
        cx, cz = _centre(_bbox(o))
        if not E.inside(env, cx, cz, IN_MARGIN):
            continue
        h = houses.setdefault(grp, {'doors': 0, 'bb': None, 'ids': [], 'walls': []})
        if str(o.get('kind') or '') in DOOR_KINDS:
            h['doors'] += 1
        if str(o.get('kind') or '') in WALL_KINDS:
            h['walls'].append(o)
        bb = _bbox(o)
        h['bb'] = (
            list(bb)
            if h['bb'] is None
            else [min(h['bb'][0], bb[0]), min(h['bb'][1], bb[1]), max(h['bb'][2], bb[2]), max(h['bb'][3], bb[3])]
        )
        h['ids'].append(o['id'])
    pools = _pools(recs)
    out = []
    for grp, h in houses.items():
        if h['doors'] or h['bb'] is None:
            continue
        # add_opening resolves the storey with arch_assistant.storey_index, which
        # counts from the record's OWN base — a head house sitting on the 54.3 m
        # deck is storey 0 OF THE HEAD HOUSE, not storey 20 of the tower, and
        # naming the deck storey here gets the model refused (arch_assistant:801).
        storey = min((A.storey_index(d, w) for w in h['walls']), default=_storey_of(env, top, storey_h))
        side = _towards(h['bb'], _bbox(pools[0])) if pools else WORD['s']
        out.append(
            {
                'sev': 'error',
                'code': 'deck_headhouse_door',
                'text': (
                    f'head house "{grp}" ({len(h["ids"])} records, {h["ids"][0]}...) has no door — '
                    f'the stair arrives inside a sealed box: '
                    f'add_opening(group="{grp}", side="{side}", storey={storey}, kind="door")'
                ),
            }
        )
    return out


# ── 9. the top stair arrives on floor ───────────────────────────────────────
def _check_stair_arrival(d, env, storey_h) -> list:
    SV = _m('stairs_vertical')
    E = _m('envelope_rules')
    if SV is None:
        return []
    stairs = []
    for o in d.objs:
        if o.get('hidden') or str(o.get('kind') or '') not in STAIR_KINDS:
            continue
        cx, cz = _centre(_bbox(o))
        if E.inside(env, cx, cz, IN_MARGIN):
            stairs.append(o)
    if not stairs:
        return []
    top = max(stairs, key=lambda o: _num(o.get('y'), 0.0))
    steps, rise = _p(top, 'steps', 0.0), _p(top, 'rise', 0.0)
    arrive = _num(top.get('y'), 0.0) + (steps * rise if steps and rise else storey_h)
    boxes = SV.approach_bboxes(top) or []
    if not boxes:
        return []
    best = None
    for b in boxes:
        cx, cz = _centre(b)
        for t, r in A.deck_tops(d, cx, cz):
            if abs(t - arrive) <= DECK_TOL:
                return []
            if best is None or abs(t - arrive) < abs(best[0] - arrive):
                best = (t, r, cx, cz)
    if best is None:
        found = 'nothing at all'
    else:
        found = f'{best[1]["id"]} at {best[0]:.2f} m'
    cx, cz = _centre(boxes[0])
    return [
        {
            'sev': 'error',
            'code': 'deck_stair_arrival',
            'text': (
                f'stair {top["id"]} arrives at {arrive:.2f} m but its landing at x {cx:.2f} z {cz:.2f} '
                f'(cell {A.cell_of(cx, cz)}) has no deck under it — {found}: give the arrival a floor '
                f'with add_slab / add_roof over that cell, or land the stair on the deck with '
                f'add_stair(cell, 0, {_storey_of(env, _num(env["top_deck"], 0.0), storey_h)})'
            ),
        }
    ]


# ── the family's one design check ───────────────────────────────────────────
def _cap(out: list) -> list:
    out.sort(key=lambda f: SEV_RANK.get(f.get('sev'), 3))
    if len(out) <= MAX_FINDINGS:
        return out
    rest = len(out) - MAX_FINDINGS
    return out[:MAX_FINDINGS] + [
        {'sev': 'info', 'code': 'deck_more', 'text': f'... and {rest} more deck finding{"s" if rest > 1 else ""}'}
    ]


def check_roof_deck(d: Drawing) -> list:
    """The top deck of every group, read as one room. Never raises: a check that
    blows up on an odd drawing must not stop design_check."""
    out = []
    try:
        if _m('envelope_rules') is None:
            return []
        storey_h = _num(getattr(d, 'storey_h', 2.7), 2.7) or 2.7
        done = _finish_sides(d)
        for env, recs in _decks(d):
            for fn, args in (
                (_check_pool_core, (d, env, recs, storey_h)),
                (_check_walkway, (d, env, recs)),
                (_check_weir_edge, (d, env, recs)),
                (_check_tank_clash, (d, env, recs, storey_h)),
                (_check_loungers, (d, env, recs)),
                (_check_plant_side, (d, env, recs)),
                (_check_guard_all, (d, env, done)),
                (_check_headhouse_door, (d, env, recs, storey_h)),
                (_check_stair_arrival, (d, env, storey_h)),
            ):
                try:
                    out.extend(fn(*args) or [])
                except Exception as exc:  # noqa: BLE001 — a check never blocks the drawing
                    out.append(
                        {
                            'sev': 'info',
                            'code': 'deck_check_failed',
                            'text': f'{fn.__name__} could not read this drawing ({exc!r}) — the deck was not checked',
                        }
                    )
    except Exception as exc:  # noqa: BLE001
        return [{'sev': 'info', 'code': 'deck_check_failed', 'text': f'the roof deck could not be read ({exc!r})'}]
    return _cap(out)


DESIGN_CHECKS = [check_roof_deck]

EXAMPLES = [
    {
        'ask': 'is the roof pool actually usable — can you walk round it, is the plant out of the view?',
        'calls': [{'tool': 'design_check', 'args': {}}],
    },
]
