# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""facade_rules — did the facade the operator ASKED for actually get built?

Job 94f5813b (2026-09-11) was asked for "ground floor glass walls, 2nd floor
rough concrete wall, 3d floor glass walls, 4th rough concrete, repeat this for
all floors ... make building look luxurious". Twenty storeys, four sides, a
parapet, a porte-cochere: 336 records, and NOTHING in the studio ever looked at
them together. Every tool answered for the records it had just made
(add_curtain_wall: "replaced 39 walls"), so a storey glazed on three sides and
left concrete on the fourth, a parapet with one side missing, a balcony hung
where no wall stands behind it, and a single 21.6 m wall standing in for eight
storeys all read as success.

This family is check-only: no kinds, no tools, no prompt. It owns the relation
between the REQUEST and the built facade, and between the facade elements
themselves:

  fac_pattern        the alternating glass/solid rhythm the request asked for,
                     measured per storey per side by glazed LENGTH
  fac_bands          a glazed storey on a luxury job with no floor line on it
  fac_parapet_gap    the parapet does not run all the way round the top deck
  fac_wall_height    two exterior walls of one storey are not the same height
                     (one wall spanning storeys hides the floors between)
  fac_balcony_place  a balcony under the entrance canopy, on the ground, with
                     no wall behind it, or cut through by a facade band
  fac_balcony_align  balconies that wander sideways from storey to storey
  fac_overhang       a canopy or balcony that projects more than 5 m

WHAT IT DELIBERATELY DOES NOT SAY. Two silences are chosen, not missing:
  · A balcony that merely sits in the canopy's PLAN rectangle is not a clash —
    add_balconies + add_canopy put ten south balconies over a 5 m porte-cochere
    on every correct tower. The clash is measured in ELEVATION: the balcony's
    own band (slab to rail top) has to meet the canopy plate's band.
  · A facade band at a balcony's own FLOOR line is the normal detail (the
    string course runs behind the slab edge). Only a band crossing the balcony
    OPENING, more than 0.1 m above its floor, is reported.
Records outside the plate are envelope_rules.check_envelope's business and are
not repeated here.

Axes as everywhere in the studio: X right, Z toward the viewer, north = -Z
(zmin), south = +Z (zmax), west = xmin, east = xmax.
"""

from __future__ import annotations

import re

from zyg_workflows.arch_assistant import Drawing, EXT_MODULES, _num

KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
PROMPT = ''  # check-only family: it costs the system prompt nothing

WALL_KINDS = ('wall', 'curtain_wall', 'wall_arc')
BAND_KINDS = ('string_course', 'cornice')
RAIL_KINDS = ('balustrade', 'railing', 'parapet_cap')

STOREY_TOL = 0.35  # metres a wall's y may miss its storey line by
EDGE_TOL = 0.6  # metres from the envelope edge that still counts as ON it
MIN_PANEL = 4.0  # shorter wall records are entrance strips, not the facade
GLASS_MIN = 0.90  # a glass storey must be at least this glazed, by length
SOLID_MAX = 0.10  # a solid storey may be at most this glazed
PARAPET_H = (0.9, 1.6)  # a wall this tall on the top deck is a parapet
PARAPET_COVER = 0.95  # of each top-deck edge
DECK_TOL = 0.8  # metres a parapet's base may sit off the top deck
BAND_TOL = 0.4  # metres a band may sit off a floor line
MIN_BAND_STOREYS = 3  # below this a group is an outbuilding, not an elevation
HEIGHT_TOL = 0.05  # metres two walls of one storey may differ by
ALIGN_TOL = 0.3  # metres a balcony may shift from the one below
OVERHANG_M = 5.0  # metres of projection that stops being a canopy
BAND_CROSS = 0.1  # metres of band inside a balcony opening that is a clash
BEHIND_TOL = 0.4  # metres of slack looking for the wall behind a balcony
MAX_FINDINGS = 8

GLASS_MATS = ('mat_glass',)

SIDE_AXIS = {'north': 'x', 'south': 'x', 'east': 'z', 'west': 'z'}


# ── small helpers ────────────────────────────────────────────────────────────
def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _env_mod():
    """envelope_rules, fetched lazily — extensions load alphabetically."""
    return EXT_MODULES.get('envelope_rules')


def _is_glass(o) -> bool:
    return o.get('kind') == 'curtain_wall' or str(o.get('mat') or '') in GLASS_MATS


def _is_parapet(o) -> bool:
    """A low guarding element, not a storey wall. Height is the test the
    drawing can be trusted on: add_parapet writes a plain `wall` record 1.1 m
    high, and a hand-drawn balustrade is the same thing by another name."""
    if o.get('kind') in RAIL_KINDS:
        return True
    nm = (str(o.get('name') or '') + ' ' + str(o.get('grp') or '')).lower()
    if 'parapet' in nm or 'balustrade' in nm or 'railing' in nm:
        return True
    h = _p(o, 'h', 0.0)
    return o.get('kind') in WALL_KINDS and PARAPET_H[0] <= h <= PARAPET_H[1]


def _is_balcony(o) -> bool:
    if o.get('kind') == 'balcony':
        return True
    nm = (str(o.get('name') or '') + ' ' + str(o.get('grp') or '')).lower()
    return 'balcony' in nm and o.get('kind') not in ('annotation', 'zone')


def _storey(d: Drawing, o, env) -> int:
    h = d.storey_h or 2.7
    return int(round((_num(o.get('y'), 0.0) - env['y0']) / h))


def _side_span(o, side) -> tuple:
    """(lo, hi) of a record's footprint along the axis its facade runs on."""
    E = _env_mod()
    bb = E.bbox_of(o)
    return (bb[0], bb[2]) if SIDE_AXIS[side] == 'x' else (bb[1], bb[3])


def _perp_span(o, side) -> tuple:
    E = _env_mod()
    bb = E.bbox_of(o)
    return (bb[1], bb[3]) if SIDE_AXIS[side] == 'x' else (bb[0], bb[2])


def _edge_span(env, side) -> tuple:
    return (env['xmin'], env['xmax']) if SIDE_AXIS[side] == 'x' else (env['zmin'], env['zmax'])


def _edge_coord(env, side) -> float:
    return {'north': env['zmin'], 'south': env['zmax'], 'west': env['xmin'], 'east': env['xmax']}[side]


def _merge(spans, lo, hi) -> float:
    """Total length of `spans` clipped to [lo, hi], overlaps counted once."""
    clipped = sorted((max(lo, a), min(hi, b)) for a, b in spans if min(hi, b) > max(lo, a))
    out, cur_a, cur_b = 0.0, None, None
    for a, b in clipped:
        if cur_a is None:
            cur_a, cur_b = a, b
        elif a <= cur_b:
            cur_b = max(cur_b, b)
        else:
            out += cur_b - cur_a
            cur_a, cur_b = a, b
    if cur_a is not None:
        out += cur_b - cur_a
    return out


def _overlap(a0, a1, b0, b1) -> float:
    return min(a1, b1) - max(a0, b0)


def _ids(recs, n=4) -> str:
    out = [o['id'] for o in recs[:n]]
    return ' '.join(out) + (f' +{len(recs) - n} more' if len(recs) > n else '')


# ── what the request asked for ───────────────────────────────────────────────
_ORDINALS = {
    'ground': 0,
    'first': 1,
    'second': 2,
    'third': 3,
    'fourth': 4,
    'fifth': 5,
    'sixth': 6,
    'seventh': 7,
    'eighth': 8,
    'ninth': 9,
    'tenth': 10,
}
_PATTERN_WORDS = re.compile(r'alternat|every other|every second|repeat this', re.I)
_EXPLICIT_LIST = re.compile(r'floors?\s+\d{1,2}\s*,\s*\d{1,2}', re.I)
_FLOOR_RE = re.compile(
    r'\b(ground|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth'
    r'|\d{1,2}\s*(?:st|nd|rd|th|d))\s+(?:floor|storey|story|level)s?\b',
    re.I,
)
_GLASS_RE = re.compile(r'glass|glazed|glazing|curtain wall', re.I)


def request_text(d: Drawing) -> str:
    """The operator's words. d.request is the live one; a drawing reloaded from
    disk has lost it, but plan_building copied it into the building programme."""
    txt = str(getattr(d, 'request', '') or '')
    if txt.strip():
        return txt
    bp = (getattr(d, 'ext', None) or {}).get('building_program') or {}
    return str(bp.get('request') or '')


def _floor_number(word: str):
    w = str(word or '').strip().lower()
    if w in _ORDINALS:
        return _ORDINALS[w]
    m = re.match(r'(\d{1,2})', w)
    return int(m.group(1)) if m else None


def glass_parity(d: Drawing):
    """0 or 1 — the parity of the storeys the request wants glazed, or None.

    'ground floor glass ... repeat this for all floors' -> 0 (storeys 0, 2, 4…).
    'first floor glass, alternating' -> 1. An explicit list of floor numbers is
    out of scope: that is not a rhythm, it is a schedule, and it is skipped.
    """
    txt = request_text(d)
    if not txt or not _PATTERN_WORDS.search(txt) or not _GLASS_RE.search(txt):
        return None
    if _EXPLICIT_LIST.search(txt):
        return None
    for m in _FLOOR_RE.finditer(txt):
        n = _floor_number(m.group(1))
        if n is None:
            continue
        tail = txt[m.end() : m.end() + 48]
        if _GLASS_RE.search(tail):
            return n % 2
    return None


def is_luxury(d: Drawing) -> bool:
    bp = (getattr(d, 'ext', None) or {}).get('building_program') or {}
    if str(bp.get('finish_level') or '').lower() in ('luxury', 'premium'):
        return True
    return bool(re.search(r'luxur|premium|high.end', request_text(d), re.I))


# ── the facade, storey by storey, side by side ───────────────────────────────
def facade_walls(d: Drawing, grp: str, env: dict) -> dict:
    """{(storey, side): [wall records]} — the exterior walls of one group that
    lie ON an envelope edge. Parapets are left out: they belong to the deck."""
    E = _env_mod()
    out: dict = {}
    for o in d.objs:
        if o.get('hidden') or o.get('grp') != grp or o.get('kind') not in WALL_KINDS:
            continue
        if _is_parapet(o):
            continue
        h = d.storey_h or 2.7
        st_f = (_num(o.get('y'), 0.0) - env['y0']) / h
        if abs(st_f - round(st_f)) * h > STOREY_TOL:
            continue
        side = E.touches_facade(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), EDGE_TOL)
        if side is None:
            continue
        out.setdefault((int(round(st_f)), side), []).append(o)
    return out


def _glass_fraction(recs) -> tuple:
    """(glazed length / total length, the solid records, the glazed records),
    counting only panels at least MIN_PANEL long — a 2.8 m entrance strip beside
    a 20 m wall is a door, not a change of material."""
    panels = [o for o in recs if _p(o, 'len', 0.0) >= MIN_PANEL]
    if not panels:
        return None, [], []
    total = sum(_p(o, 'len', 0.0) for o in panels)
    glass = [o for o in panels if _is_glass(o)]
    solid = [o for o in panels if not _is_glass(o)]
    if total <= 0:
        return None, solid, glass
    return sum(_p(o, 'len', 0.0) for o in glass) / total, solid, glass


def check_pattern(d: Drawing, grp: str, env: dict, walls: dict) -> list:
    parity = glass_parity(d)
    if parity is None:
        return []
    # 2026-09-16 (job 71e9d42e559f): the pattern was demanded of EVERY envelope,
    # so the one-storey stair head house on the roof read 'storey 0 of "tower
    # head house" should be glass'; the model glazed it, add_curtain_wall then
    # dropped the head house's base level and check_floors refused done on a
    # phantom 'storey 0 without a slab' for 12 minutes. A group under
    # MIN_BAND_STOREYS is an outbuilding — check_bands already says so.
    if int(env.get('storeys') or 0) < MIN_BAND_STOREYS:
        return []
    out = []
    for st in range(0, max(1, int(env.get('storeys') or 0))):
        recs = [o for side in ('north', 'south', 'east', 'west') for o in walls.get((st, side), [])]
        if not recs:
            continue
        frac, solid, glass = _glass_fraction(recs)
        if frac is None:
            continue
        want_glass = (st % 2) == parity
        if want_glass and frac < GLASS_MIN:
            bad = {id(o) for o in solid}
            sides = sorted(
                {s for s in ('north', 'south', 'east', 'west') for o in walls.get((st, s), []) if id(o) in bad}
            )
            out.append(
                {
                    'sev': 'error',
                    'code': 'fac_pattern',
                    'text': f'storey {st} of "{grp}" should be glass — only {frac * 100:.0f} % is, the '
                    f'{" + ".join(sides) or "facade"} side is solid ({_ids(solid)}): '
                    f'add_curtain_wall(walls="{grp}", storeys=[{st}])',
                }
            )
        elif (not want_glass) and frac > SOLID_MAX:
            bad = {id(o) for o in glass}
            sides = sorted(
                {s for s in ('north', 'south', 'east', 'west') for o in walls.get((st, s), []) if id(o) in bad}
            )
            out.append(
                {
                    'sev': 'error',
                    'code': 'fac_pattern',
                    'text': f'storey {st} of "{grp}" should be concrete — {frac * 100:.0f} % of it is glass '
                    f'on the {" + ".join(sides) or "facade"} side ({_ids(glass)}): '
                    f'replace_kind(which=[{", ".join(chr(34) + o["id"] + chr(34) for o in glass[:4])}], '
                    f'kind="wall") and repaint it pht_rough_concrete',
                }
            )
    return out


def check_bands(d: Drawing, grp: str, env: dict, walls: dict) -> list:
    """A glazed storey on a luxury job with no floor line drawn on it.

    A 20-storey sheet of glass with nothing horizontal in it has no scale: the
    string course at each floor is what makes it read as a building. Only asked
    for when the job is a luxury one or the request set a facade rhythm.
    """
    if not (is_luxury(d) or glass_parity(d) is not None):
        return []
    if int(env.get('storeys') or 0) < MIN_BAND_STOREYS:
        return []  # a one-storey head house has no rhythm to lose
    h = d.storey_h or 2.7
    bands = [o for o in d.objs if not o.get('hidden') and o.get('kind') in BAND_KINDS and o.get('grp') == grp]
    if not bands:
        band_y: list = []
    else:
        band_y = sorted({round(_num(o.get('y'), 0.0), 3) for o in bands})
    per_storey: dict = {}
    for (st, _side), recs in walls.items():
        per_storey.setdefault(st, []).extend(recs)
    glazed = sorted(st for st, recs in per_storey.items() if (_glass_fraction(recs)[0] or 0.0) >= GLASS_MIN)
    missing = []
    for st in glazed:
        floor_y = env['y0'] + st * h
        head_y = floor_y + h
        if any(abs(by - floor_y) <= BAND_TOL or abs(by - head_y) <= BAND_TOL for by in band_y):
            continue
        missing.append(st)
    if not missing:
        return []
    shown = ', '.join(str(s) for s in missing[:6]) + (' …' if len(missing) > 6 else '')
    return [
        {
            'sev': 'warn',
            'code': 'fac_bands',
            'text': f'"{grp}" has {len(missing)} glazed storey(s) with no floor line on the facade '
            f'(storeys {shown}) — a luxury elevation needs the horizontal: '
            f'add_facade_bands(group="{grp}", kind="string_course", every_n_storeys=1)',
        }
    ]


def check_parapet(d: Drawing, grp: str, env: dict, guarded: set) -> list:
    """The parapet has to run all the way round the top deck, or the deck ends
    in mid air on the side it is missing from. Silent when the group has no
    parapet at all — a roof with no guard is deck_rules' finding, not this one.
    """
    E = _env_mod()
    top = env.get('top_deck')
    if top is None:
        return []
    by_side: dict = {}
    for o in d.objs:
        if o.get('hidden') or o.get('grp') != grp:
            continue
        if o.get('kind') not in WALL_KINDS and o.get('kind') not in RAIL_KINDS:
            continue
        if not _is_parapet(o) or o.get('kind') == 'parapet_cap':
            continue
        if abs(_num(o.get('y'), 0.0) - top) > DECK_TOL:
            continue
        side = E.touches_facade(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), EDGE_TOL)
        if side:
            by_side.setdefault(side, []).append(o)
    if not by_side:
        return []
    out = []
    for side in ('north', 'south', 'east', 'west'):
        lo, hi = _edge_span(env, side)
        span = hi - lo
        if span <= 0:
            continue
        if any(grp.lower() in g and side in g for g in guarded):
            continue
        covered = _merge([_side_span(o, side) for o in by_side.get(side, [])], lo, hi)
        if covered >= span * PARAPET_COVER:
            continue
        out.append(
            {
                'sev': 'error',
                'code': 'fac_parapet_gap',
                'text': f'the parapet of "{grp}" leaves {span - covered:.1f} m of the {side} edge of the '
                f'{top:.1f} m deck open ({covered:.1f} of {span:.1f} m guarded) — '
                f'add_parapet(group="{grp}", height=1.1, cap=True) runs it round all four sides',
            }
        )
    return out


def check_wall_height(d: Drawing, grp: str, env: dict, walls: dict) -> list:
    """One storey, one wall height. A single tall wall standing in for eight
    storeys is how job 94f5813b lost its floor lines: draw_box writes ONE wall
    per storey per side, so a 21.6 m record is a hand edit or a set_height that
    swallowed the storeys above it."""
    by_storey: dict = {}
    for (st, _side), recs in walls.items():
        by_storey.setdefault(st, []).extend(recs)
    out = []
    for st in sorted(by_storey):
        recs = [o for o in by_storey[st] if _p(o, 'h', 0.0) > 0]
        if len(recs) < 2:
            continue
        tall = max(recs, key=lambda o: _p(o, 'h', 0.0))
        short = min(recs, key=lambda o: _p(o, 'h', 0.0))
        gap = _p(tall, 'h', 0.0) - _p(short, 'h', 0.0)
        if gap <= HEIGHT_TOL:
            continue
        spans = _p(tall, 'h', 0.0) / (d.storey_h or 2.7)
        out.append(
            {
                'sev': 'error',
                'code': 'fac_wall_height',
                'text': f'{tall["id"]} {_p(tall, "h", 0.0):.1f} m vs {short["id"]} {_p(short, "h", 0.0):.1f} m '
                f'on storey {st} of "{grp}": a wall spanning {spans:.0f} storeys hides the floors '
                f'behind it (draw_box draws one wall per storey) — '
                f'set_height(which=["{tall["id"]}"], metres={_p(short, "h", 0.0):.2f}) and draw the '
                f'storeys above it',
            }
        )
    return out


# ── balconies ────────────────────────────────────────────────────────────────
def _balcony_side(d: Drawing, o, envs: dict):
    """(group, side) of the facade a balcony hangs on — it stands just OUTSIDE
    the envelope, so the nearest edge within a balcony's own depth wins."""
    E = _env_mod()
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    best = (None, None, 1e18)
    for g, env in envs.items():
        side = E.touches_facade(env, x, z, 1.5)
        if side is None:
            continue
        gap = abs(
            {'north': z - env['zmin'], 'south': z - env['zmax'], 'west': x - env['xmin'], 'east': x - env['xmax']}[side]
        )
        if gap < best[2]:
            best = (g, side, gap)
    return best[0], best[1]


def check_balconies(d: Drawing, envs: dict, walls_by_grp: dict) -> list:
    E = _env_mod()
    balconies = [o for o in d.objs if not o.get('hidden') and _is_balcony(o)]
    if not balconies:
        return []
    canopies = [o for o in d.objs if not o.get('hidden') and o.get('kind') in ('canopy', 'awning')]
    bands = [o for o in d.objs if not o.get('hidden') and o.get('kind') in BAND_KINDS]
    out: list = []
    by_side: dict = {}

    for o in balconies:
        grp, side = _balcony_side(d, o, envs)
        if grp is None:
            continue  # envelope_rules owns a balcony that touches nothing
        env = envs[grp]
        st = _storey(d, o, env)
        by_side.setdefault((grp, side), {}).setdefault(st, []).append(o)
        bb = E.bbox_of(o)
        floor = _num(o.get('y'), 0.0)
        top = floor + _p(o, 'rail_h', 1.0)

        why = None
        if st <= 0:
            why = (
                f'stands on the ground (storey 0) — a balcony needs a storey under it: '
                f'add_balconies(walls="{grp}", storey_offset=1)'
            )
        if why is None:
            for c in canopies:
                cb = E.bbox_of(c)
                if _overlap(bb[0], bb[2], cb[0], cb[2]) <= 0 or _overlap(bb[1], bb[3], cb[1], cb[3]) <= 0:
                    continue
                c0 = _num(c.get('y'), 0.0)
                c1 = c0 + _p(c, 't', 0.12)
                if _overlap(floor - _p(o, 't', 0.18), top, c0 - 0.3, c1 + 0.3) > 0:
                    why = (
                        f'cuts through the {c["kind"]} {c["id"]} at {c0:.1f} m — move it to another side '
                        f'or delete it: add_balconies(walls="{grp}", sides=["north","east","west"])'
                    )
                    break
        if why is None and side:
            hosts = walls_by_grp.get(grp, {}).get((st, side), [])
            lo, hi = _side_span(o, side)
            plo, phi = _perp_span(o, side)
            edge = _edge_coord(env, side)
            behind = [
                w
                for w in hosts
                if _overlap(lo, hi, *_side_span(w, side)) > 0 and plo - BEHIND_TOL <= edge <= phi + BEHIND_TOL
            ]
            if not behind:
                why = (
                    f'hangs on the {side} face of "{grp}" at storey {st} with no wall behind it — '
                    f'draw the storey wall first, or hang it where one stands: '
                    f'add_balconies(walls="{grp}", sides=["{side}"], storey_offset=1)'
                )
        if why is None:
            for b in bands:
                bbb = E.bbox_of(b)
                if _overlap(bb[0], bb[2], bbb[0], bbb[2]) <= 0 or _overlap(bb[1], bb[3], bbb[1], bbb[3]) <= 0:
                    continue
                b0 = _num(b.get('y'), 0.0)
                b1 = b0 + _p(b, 'h', 0.12)
                cut = _overlap(b0, b1, floor + BAND_CROSS, top)
                if cut > BAND_CROSS:
                    why = (
                        f'is cut across by the {b["kind"]} {b["id"]}, {cut:.2f} m of band inside the balcony '
                        f'opening — run the bands at the floor lines: '
                        f'add_facade_bands(group="{grp}", kind="string_course", every_n_storeys=1)'
                    )
                    break
        if why:
            out.append({'sev': 'error', 'code': 'fac_balcony_place', 'text': f'balcony {o["id"]} ' + why})

    out.extend(_check_align(by_side))
    return out


def _check_align(by_side: dict) -> list:
    """Balconies that wander sideways from one storey to the next. A stagger on
    EVERY storey is a pattern; a stagger on one is a slip."""
    out = []
    for (grp, side), per_storey in sorted(by_side.items()):
        if side is None:
            continue
        storeys = sorted(per_storey)
        if len(storeys) < 2:
            continue
        pairs, offset = [], []
        for a, b in zip(storeys, storeys[1:]):
            ca = sorted((_side_span(o, side)[0] + _side_span(o, side)[1]) / 2 for o in per_storey[a])
            cb = sorted((_side_span(o, side)[0] + _side_span(o, side)[1]) / 2 for o in per_storey[b])
            if len(ca) != len(cb):
                continue
            worst = max((abs(p - q) for p, q in zip(ca, cb)), default=0.0)
            pairs.append((a, b, worst))
            if worst > ALIGN_TOL:
                offset.append((a, b, worst))
        if not offset or len(offset) == len(pairs):
            continue  # nothing wrong, or a deliberate stagger
        a, b, worst = offset[0]
        rest = f' (and {len(offset) - 1} more)' if len(offset) > 1 else ''
        out.append(
            {
                'sev': 'warn',
                'code': 'fac_balcony_align',
                'text': f'the {side} balconies of "{grp}" step {worst:.2f} m sideways between storey {a} '
                f'and storey {b}{rest} while the other storeys line up — redraw them in one call: '
                f'add_balconies(walls="{grp}", sides=["{side}"], every_n_storeys=1)',
            }
        )
    return out


def check_overhang(d: Drawing) -> list:
    out = []
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in ('canopy', 'awning', 'balcony'):
            continue
        dep = _p(o, 'd', 0.0)
        if dep > OVERHANG_M:
            out.append(
                {
                    'sev': 'warn',
                    'code': 'fac_overhang',
                    'text': f'{o["id"]} {o.get("name") or o["kind"]} projects {dep:.1f} m from the facade — '
                    f'nothing carries it that far out: set_param(which=["{o["id"]}"], key="d", '
                    f'value={OVERHANG_M:g}) or put columns under it',
                }
            )
    return out


# ── the one DESIGN_CHECK ─────────────────────────────────────────────────────
def _deck_guarded(d: Drawing) -> set:
    """The edges deck_rules already reports as unguarded, lower-cased, so the
    same missing parapet is never named twice by two families."""
    mod = EXT_MODULES.get('deck_rules')
    if mod is None:
        return set()
    out = set()
    try:
        for fn in getattr(mod, 'DESIGN_CHECKS', None) or []:
            for f in fn(d) or []:
                if str(f.get('code') or '').startswith('deck_guard'):
                    out.add(str(f.get('text') or '').lower())
    except Exception:
        return set()
    return out


def check_facade(d: Drawing) -> list:
    """Every facade rule of this family, in one pass over the drawing."""
    try:
        E = _env_mod()
        if E is None:
            return []
        envs = E.envelopes(d)
        if not envs:
            return []
        guarded = _deck_guarded(d)
        out: list = []
        walls_by_grp: dict = {}
        for grp, env in envs.items():
            walls = facade_walls(d, grp, env)
            walls_by_grp[grp] = walls
            out.extend(check_pattern(d, grp, env, walls))
            out.extend(check_wall_height(d, grp, env, walls))
            out.extend(check_parapet(d, grp, env, guarded))
            out.extend(check_bands(d, grp, env, walls))
        out.extend(check_balconies(d, envs, walls_by_grp))
        out.extend(check_overhang(d))
    except Exception as exc:  # a check must never raise
        return [
            {
                'sev': 'info',
                'code': 'fac_check_failed',
                'text': f'facade_rules could not read this drawing ({type(exc).__name__}: {exc}) — '
                f'the facade pattern, the parapet and the balconies were not checked',
            }
        ]
    if len(out) > MAX_FINDINGS:
        rest = len(out) - MAX_FINDINGS
        out = out[:MAX_FINDINGS] + [
            {'sev': 'info', 'code': 'fac_more', 'text': f'... and {rest} more facade finding{"s" if rest > 1 else ""}'}
        ]
    return out


DESIGN_CHECKS = [check_facade]
