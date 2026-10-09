# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""clash_rules — nothing solid passes through something else solid (2026-09-16).

The operator's words: "avoid any defects like stairs crossing through walls".

Until today the only interference the studio measured was core-vs-core:
circulation_rules.check_core_clash sees a stair inside a lift shaft and nothing
else. A partition laid straight across a stair well, a column standing in the
lobby desk, a sofa half inside a wall, a lounger floating in the pool water, a
tree trunk in a canopy post — every one of those draws, renders and passes
design_check today, because each tool only ever sees the record it just made.

Interference is a RELATION, so it is measured here, over the whole drawing, by
ROLE rather than by kind:

    core       a stair or a lift shaft — the vertical thing a building is built around
    wall       wall, curtain_wall, wall_arc, partition
    column     column_round, column_rect, column_h
    furniture  anything whose spec stands on a floor or a deck
    water      the basin of a pool (the water box, inside the coping)
    tree       a trunk (0.5 m) — a CROWN may overhang a wall, a trunk may not
    canopy     the plate a porte-cochere hangs over the entrance

and the pairs that may never interpenetrate are declared once, in PAIRS.

THE THIN-AXIS RULE. A wall is 0.1-0.3 m thick, so a flat "overlap > 0.15 m in
both plan axes" can never fire on one, and would fire on every skirting-close
sofa if it were loosened. A wall therefore clashes only when its THIN axis is
CONTAINED inside the other record's footprint (both faces at least 0.05 m in) —
which is exactly the difference between a partition crossing a stair well and a
partition running along the well's edge, the case the brief calls "touching".

No new kinds, no tools, no prompt: this family only measures.
"""

from __future__ import annotations

import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
PROMPT = ''

TOL_PLAN = 0.15  # m of plan overlap before two solids interfere
TOL_V = 0.10  # m of vertical overlap before they share a height
EDGE_IN = 0.05  # m a wall face must be inside a footprint to be "through" it

# 2026-09-16: how deep a piece of FURNITURE must reach into a wall before the
# eye reads it as a defect. The number is not a drafting tolerance, it is the
# thickness of a domestic party wall: the surveyed plan packs place a bathtub
# against a 0.10 m partition and the tub's own rim lands ON the wall line, so
# every such tub read as "passes through the party wall: 0.10 x 0.75 m" — eight
# of them on one replayed tower, all of them invisible in the render and none of
# them anything a person could act on. 0.12 m is one partition thickness plus
# 0.02 m of placement noise: it silences the tub-on-the-party-wall row and keeps
# every real one, because real furniture-in-a-wall is a whole leaf deep (a sofa
# 0.3 m into a facade, a counter 0.6 m into a stair well). Measured along the
# WALL'S THIN AXIS, so it is a penetration depth and not a plan overlap: a tub
# that runs 3 m ALONG a wall still fires on the other axis.
FURN_WALL_PEN = 0.12  # m a piece of furniture may reach into a wall
TRUNK_R = 0.25  # m — a tree trunk, the part that may not pass through a wall
MAX_PER_PAIR = 8  # findings per role pair before the rest are folded

STAIR_KINDS = ('stair_straight', 'stair_u', 'stair_l', 'stair_winder', 'stair_spiral')
SHAFT_KIND = 'elevator_shaft'
WALL_ROLE_KINDS = ('wall', 'curtain_wall', 'wall_arc', 'partition')
COLUMN_KINDS = ('column_round', 'column_rect', 'column_h')
WATER_KINDS = ('pool',)
CANOPY_KINDS = ('canopy', 'awning')
TREE_KINDS = ('tree_deciduous', 'tree', 'tree_conifer', 'tree_palm')
TREE_WORDS = ('tree', 'oak', 'pine', 'jacaranda', 'palm')

# furniture the store may not know by spec yet, but the tab draws
FURNITURE_EXTRA = (
    'sofa',
    'armchair',
    'coffee_table',
    'desk',
    'table',
    'bed',
    'sun_lounger',
    'umbrella',
    'planter',
    'reception_desk',
    'rug',
)

# things a spec calls "stands on the floor" that are NOT furniture: they are
# circulation (a lift car lives INSIDE its shaft by construction), a surface, or
# a zone marker. Reading them as furniture reports the building against itself.
NOT_FURNITURE = frozenset(
    {
        'elevator_car',
        'escalator',
        'fire_stair_exterior',
        'stair_landing',
        'zone',
        'slab',
        'slab_poly',
        'roof_flat',
        'pool',
        'wall_ring',
        'parking_bay',
    }
)

# never a party to a clash: horizontal construction (slab_voids owns a stair
# through a slab), trim, and the opening records that live in a wall's plane.
SKIP_KINDS = frozenset(
    {
        'slab',
        'slab_poly',
        'roof_flat',
        'roof_gable',
        'roof_hip',
        'roof_shed',
        'roof_pitched',
        'string_course',
        'parapet_cap',
        'cornice',
        'pilaster',
        'beam',
        'beam_i',
        'beam_rect',
        'joist',
        'purlin',
        'door',
        'double_door',
        'door_sliding',
        'door_french',
        'window',
        'window_bay',
        'window_round',
        'skylight',
        'opening',
    }
)

MOVE_HINT = 'delete + re-add, or add_room/layout_floor with core_from/core_to clear of it'


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _mod(name):
    return A.EXT_MODULES.get(name)


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


# ── roles ───────────────────────────────────────────────────────────────────
def _is_tree(o) -> bool:
    k = str(o.get('kind') or '')
    if k in TREE_KINDS:
        return True
    if k != 'asset':
        return False
    nm = (str(o.get('name') or '') + ' ' + str((o.get('p') or {}).get('item') or '')).lower()
    return any(w in nm for w in TREE_WORDS) and 'stump' not in nm and 'root' not in nm


def furniture_kinds() -> set:
    """Every kind whose object spec says it stands on a floor or a deck, plus the
    handful the tab draws that the store has no sheet for yet. Kinds that already
    own another role (a wall, a column, a core, the pool) are not furniture."""
    out = set()
    S = _mod('object_specs')
    skip = set(getattr(S, 'SOLID_SKIP', ()) or ()) if S is not None else set()
    spec_for_kind = getattr(S, 'spec_for_kind', None) if S is not None else None
    if callable(spec_for_kind):
        for k in list(getattr(A, 'KINDS', {}) or {}):
            try:
                s = spec_for_kind(k)
            except Exception:  # noqa: BLE001
                s = None
            if s and ((s.get('space') or {}).get('host') in ('floor', 'deck')):
                out.add(k)
    for k in FURNITURE_EXTRA:
        if k in (getattr(A, 'KINDS', {}) or {}):
            out.add(k)
    out -= set(STAIR_KINDS) | {SHAFT_KIND} | set(WALL_ROLE_KINDS) | set(COLUMN_KINDS)
    out -= set(WATER_KINDS) | set(CANOPY_KINDS) | set(TREE_KINDS) | NOT_FURNITURE | skip
    return out


def role_of(o, furn: set):
    k = str(o.get('kind') or '')
    if k in STAIR_KINDS or k == SHAFT_KIND:
        return 'core'
    if k in WALL_ROLE_KINDS:
        return 'wall'
    if k in COLUMN_KINDS:
        return 'column'
    if k in WATER_KINDS:
        return 'water'
    if k in CANOPY_KINDS:
        return 'canopy'
    if _is_tree(o):
        return 'tree'
    if k in furn:
        return 'furniture'
    return None


# (subject role, object role) -> the role that should move
PAIRS = {
    ('core', 'wall'): 'wall',
    ('core', 'column'): 'column',
    ('furniture', 'wall'): 'furniture',
    ('furniture', 'column'): 'furniture',
    ('furniture', 'core'): 'furniture',
    ('furniture', 'water'): 'furniture',
    ('column', 'water'): 'column',
    ('tree', 'wall'): 'tree',
    ('tree', 'column'): 'tree',
    ('tree', 'canopy'): 'tree',
    ('wall', 'water'): 'wall',
}
WORD = {
    'core': 'core',
    'wall': 'wall',
    'column': 'column',
    'furniture': 'furniture',
    'water': 'pool water',
    'tree': 'tree',
    'canopy': 'canopy',
}


def pair_of(ra, rb):
    """((subjectRole, objectRole), swapped) for a pair the matrix covers, else None."""
    if (ra, rb) in PAIRS:
        return (ra, rb), False
    if (rb, ra) in PAIRS:
        return (rb, ra), True
    return None


# ── geometry ────────────────────────────────────────────────────────────────
def _bbox(o) -> tuple:
    E = _mod('envelope_rules')
    if E is not None:
        try:
            return tuple(E.bbox_of(o))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('envelope bbox unavailable, using the point stub: %s', _exc)
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    return (x - 0.25, z - 0.25, x + 0.25, z + 0.25)


def plan_rect(o, role: str) -> tuple:
    """The footprint a clash is measured against. A tree is its TRUNK — a crown
    may lean over a wall; a pool is its WATER, the basin inside the coping."""
    if role == 'tree':
        x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
        r = TRUNK_R if str(o.get('kind') or '') != 'asset' else TRUNK_R
        return (x - r, z - r, x + r, z + r)
    bb = _bbox(o)
    if role == 'water':
        c = max(0.0, _p(o, 'coping', 0.4))
        if bb[2] - bb[0] > 2 * c + 0.4 and bb[3] - bb[1] > 2 * c + 0.4:
            return (bb[0] + c, bb[1] + c, bb[2] - c, bb[3] - c)
    return bb


def _stair_h(o) -> float:
    S = _mod('stairs_vertical')
    fn = getattr(S, 'stair_height', None) if S is not None else None
    if callable(fn):
        try:
            return _num(fn(o), 0.0)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('stairs_vertical stair height failed: %s', _exc)
    C = _mod('circulation_rules')
    fn = getattr(C, 'stair_height', None) if C is not None else None
    if callable(fn):
        try:
            return _num(fn(o), 0.0)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('circulation_rules stair height failed: %s', _exc)
    p = o.get('p') or {}
    n = _num(p.get('steps'), 0.0) or (_num(p.get('steps_a'), 0.0) + _num(p.get('steps_b'), 0.0))
    return n * _num(p.get('rise'), 0.0)


def _spec_h(kind) -> float:
    S = _mod('object_specs')
    fn = getattr(S, 'spec_for_kind', None) if S is not None else None
    if not callable(fn):
        return 0.0
    try:
        s = fn(kind)
    except Exception:  # noqa: BLE001
        return 0.0
    h = ((s or {}).get('space') or {}).get('h')
    return _num(h[0], 0.0) if isinstance(h, list) and h else 0.0


def vspan(o, role: str) -> tuple:
    """(y0, y1) the record occupies. A pool hangs DOWN from its water level."""
    y = _num(o.get('y'), 0.0)
    k = str(o.get('kind') or '')
    if role == 'water':
        # water_leisure L302-326: `y` is the surface the basin SITS ON and p.raised
        # is how far its rim stands above it, so the water box is
        # [y - depth + raised, y + raised]. On the ground (raised 0) that is the
        # sunk basin [y - depth, y]; on a deck (raised = depth) it is the rooftop
        # pool standing on the roof, which is the case the live tower has.
        dep = max(0.3, _p(o, 'depth', 1.5))
        r = max(0.0, _p(o, 'raised', 0.0))
        return y - dep + r, y + r
    if k in STAIR_KINDS:
        return y, y + max(_stair_h(o), 0.3)
    h = _p(o, 'h', 0.0)
    if h <= 0:
        h = _p(o, 'bh', 0.0) * (_num(o.get('s'), 1.0) or 1.0)
    if h <= 0:
        h = _spec_h(k)
    if h <= 0:
        h = _p(o, 't', 0.0)
    if h <= 0:
        h = 0.6
    return y, y + h


def _need(a0, a1, b0, b1) -> float:
    """Overlap this axis must exceed: the flat tolerance, but never more than
    most of the smaller of the two extents — otherwise a 0.1 m partition could
    not clash with anything at all."""
    return min(TOL_PLAN, 0.8 * max(0.02, min(a1 - a0, b1 - b0)))


def _through(wall_rect, other_rect) -> bool:
    """A wall's THIN axis lies inside the other footprint, both faces at least
    EDGE_IN in: the wall passes THROUGH it rather than running along its edge."""
    wx, wz = wall_rect[2] - wall_rect[0], wall_rect[3] - wall_rect[1]
    if wx <= wz:  # thin along X
        return wall_rect[0] >= other_rect[0] + EDGE_IN and wall_rect[2] <= other_rect[2] - EDGE_IN
    return wall_rect[1] >= other_rect[1] + EDGE_IN and wall_rect[3] <= other_rect[3] - EDGE_IN


def square_on(o) -> bool:
    """Is this record square to the grid? A rect is all this check measures, and
    `envelope_rules.bbox_of` gives the AXIS-ALIGNED box: for a record turned 30 deg
    that box is far bigger than the thing, so two such boxes can overlap while the
    records do not touch. The plan-pack kitchens prove it — a counter and the
    partition it stands against, both turned, read as a 0.80 x 0.33 m collision
    that is not there. An oblique record is left to the eye, not guessed at.

    `ry` is RADIANS here (a facade wall reads 1.570796, not 90)."""
    deg = math.degrees(_num(o.get('ry'), 0.0)) % 90.0
    return deg <= 1.0 or deg >= 89.0


def overlap(ra, a_rect, rb, b_rect) -> tuple | None:
    """(ox, oz) when the two footprints interfere, else None."""
    ox = min(a_rect[2], b_rect[2]) - max(a_rect[0], b_rect[0])
    oz = min(a_rect[3], b_rect[3]) - max(a_rect[1], b_rect[1])
    if ox <= 0 or oz <= 0:
        return None
    if ox <= _need(a_rect[0], a_rect[2], b_rect[0], b_rect[2]):
        return None
    if oz <= _need(a_rect[1], a_rect[3], b_rect[1], b_rect[3]):
        return None
    if ra == 'wall' and rb != 'wall' and not _through(a_rect, b_rect):
        return None
    if rb == 'wall' and ra != 'wall' and not _through(b_rect, a_rect):
        return None
    if {ra, rb} == {'furniture', 'wall'}:
        w_rect = a_rect if ra == 'wall' else b_rect
        thin_x = (w_rect[2] - w_rect[0]) <= (w_rect[3] - w_rect[1])
        if (ox if thin_x else oz) <= FURN_WALL_PEN:  # see FURN_WALL_PEN
            return None
    return ox, oz


def _storey(d: Drawing, o) -> int:
    H = getattr(d, 'storey_h', 0.0) or 2.7
    return int(round((_num(o.get('y'), 0.0) - _p(o, 'base', 0.0)) / H)) if H else 0


# ── what the ROOM tools ask before they draw ────────────────────────────────
def core_word(o) -> str:
    k = str(o.get('kind') or '')
    return 'lift shaft' if k == SHAFT_KIND else k.replace('_', ' ')


def cores_on_storey(d: Drawing, storey) -> list:
    """[(record, (x0, z0, x1, z1))] — every stair and lift shaft whose vertical
    span covers that storey. A shaft is ONE record for the whole tower and a
    legacy stair one tall record, so "starts on this storey" misses both: the
    test is the same span test floor_plans._core_rects uses."""
    H = getattr(d, 'storey_h', 0.0) or 2.7
    lvl = int(_num(storey, 0)) * H
    out = []
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden') or (k not in STAIR_KINDS and k != SHAFT_KIND):
            continue
        y0 = _num(o.get('y'), 0.0)
        h = _p(o, 'h', 0.0) or (_stair_h(o) if k in STAIR_KINDS else 0.0)
        on = abs(y0 - lvl) <= 0.3 or (h > 0 and y0 - 0.3 <= lvl <= y0 + h - 0.3)
        if on:
            out.append((o, tuple(_bbox(o))))
    return out


GRAZE = 0.35  # of the core's own plan area: less than this and it is a nick


def blocking_core(d: Drawing, rect, storey, tol=TOL_PLAN, graze=GRAZE):
    """(record, rect, ox, oz) of the core the plan rectangle crosses WORST on that
    storey, else None. The room tools call this BEFORE drawing: a partition
    through a stair well is far cheaper to refuse than to find in design_check
    twenty records later.

    A block that clips a CORNER of the core is not a crossing. building_program's
    own lobby how-line lays EY91..FC95 over 0.40 x 0.50 m of a 1.8 x 2.0 m shaft —
    5 % of it — and refusing the programme's own advice helps nobody. The block has
    to swallow `graze` of the core's plan before the tool says no; anything smaller
    is left to check_clashes, which measures the partitions that actually result."""
    best = None
    for o, cr in cores_on_storey(d, storey):
        ox = min(rect[2], cr[2]) - max(rect[0], cr[0])
        oz = min(rect[3], cr[3]) - max(rect[1], cr[1])
        if ox <= tol or oz <= tol:
            continue
        area = max(1e-6, (cr[2] - cr[0]) * (cr[3] - cr[1]))
        if (ox * oz) / area < graze:
            continue
        if best is None or min(ox, oz) > min(best[2], best[3]):
            best = (o, cr, ox, oz)
    return best


def core_phrase(o, cr) -> str:
    return f'{core_word(o)} {o["id"]} (x {cr[0]:.1f}..{cr[2]:.1f}, z {cr[1]:.1f}..{cr[3]:.1f})'


# ── the check ───────────────────────────────────────────────────────────────
def _candidates(d: Drawing) -> list:
    furn = furniture_kinds()
    S = _mod('object_specs')
    skip = set(getattr(S, 'SOLID_SKIP', ()) or ()) if S is not None else set()
    out = []
    for o in d.objs:
        k = str(o.get('kind') or '')
        if o.get('hidden') or k in SKIP_KINDS or k in skip:
            continue
        r = role_of(o, furn)
        if not r:
            continue
        out.append((o, r, plan_rect(o, r), vspan(o, r)))
    return out


def check_clashes(d: Drawing) -> list:
    """Nothing solid stands inside something else solid. One finding per record,
    the worst overlap it is party to; at most 8 per role pair."""
    try:
        recs = _candidates(d)
        best: dict = {}
        for i, (a, ra, arect, aspan) in enumerate(recs):
            for b, rb, brect, bspan in recs[i + 1 :]:
                if a.get('grp') and a.get('grp') == b.get('grp') and a.get('kind') == b.get('kind'):
                    continue
                if (b.get('meta') or {}).get('host') == a['id'] or (a.get('meta') or {}).get('host') == b['id']:
                    continue
                pr = pair_of(ra, rb)
                if pr is None:
                    continue
                if not (square_on(a) and square_on(b)):
                    continue  # two AABBs cannot prove an oblique clash
                (sa, sb), swapped = pr
                if min(aspan[1], bspan[1]) - max(aspan[0], bspan[0]) <= TOL_V:
                    continue
                ov = overlap(ra, arect, rb, brect)
                if ov is None:
                    continue
                subj, obj = (b, a) if swapped else (a, b)
                mover = PAIRS[(sa, sb)]
                move = subj if mover == sa else obj
                code = f'clash_{sa}_{sb}'
                score = min(ov)
                cur = best.get(subj['id'])
                if cur is not None and cur[0] >= score:
                    continue
                text = (
                    f'{_lbl(subj)} passes through {_lbl(obj)}: {ov[0]:.2f} x {ov[1]:.2f} m overlap on '
                    f'storey {_storey(d, subj)} — move the {WORD.get(mover, mover)} '
                    f'{move["id"]} ({MOVE_HINT})'
                )
                best[subj['id']] = (score, {'sev': 'error', 'code': code, 'text': text})

        out, n_by_code, folded = [], {}, {}
        for _, f in sorted(best.values(), key=lambda e: -e[0]):
            c = f['code']
            n_by_code[c] = n_by_code.get(c, 0) + 1
            if n_by_code[c] <= MAX_PER_PAIR:
                out.append(f)
            else:
                folded[c] = folded.get(c, 0) + 1
        for c in sorted(folded):
            out.append(
                {
                    'sev': 'info',
                    'code': 'clash_more',
                    'text': f'... and {folded[c]} more {c} finding{"s" if folded[c] > 1 else ""}',
                }
            )
        return out
    except Exception as e:  # noqa: BLE001 — a check never blocks a drawing
        return [
            {
                'sev': 'info',
                'code': 'clash_error',
                'text': f'the clash check could not run on this drawing ({type(e).__name__}: {e}) — '
                f'nothing is claimed about interference here',
            }
        ]


DESIGN_CHECKS = [check_clashes]
