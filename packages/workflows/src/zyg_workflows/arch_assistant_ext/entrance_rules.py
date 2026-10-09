# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""entrance_rules — is the way IN actually a way in? (2026-09-16)

Why this family exists: "a nice entrance into the building with a lobby" is one
of the operator's three acceptance items, and until today nothing in the studio
read the RELATIONS that make one. building_program asks whether an entrance,
a lobby, a reception and an approach EXIST; sightline_rules asks whether the
door can be SEEN from the drive. Neither asks whether the door is wide enough
for the tower behind it, whether the canopy is over the door or beside it,
whether its soffit clears the door head, whether a column or a lamp post stands
in the opening, whether a second door was drawn 0.8 m away — and, on the inside,
whether the door opens into the LOBBY at all or into a corridor, a WC or thin
air, whether that lobby holds a desk and a seat, and whether anything is parked
on the axis between the door and the room.

Job 94f5813b is the case: its "lobby" was four bare partitions boxing a
10.1 x 3.1 m strip whose near side, o512, stood 1.0 m INSIDE the entrance without
meeting it — so the visitor stepped out of the double door into the tower's raw
storey-0 volume and had to find a 0.9 m door in that partition to get in. Not one
desk or seat was ever placed there. Every existing gate passed it.

Check-only. NO NEW KINDS, no tools, PROMPT = '' (the explanation lives in the
finding texts, which is what the model reads). DESIGN_CHECKS = [check_entrance_quality];
design_rules.run_checks() picks it up and the `done` gate enforces the errors.

ENTRANCE, here: a door kind at storey 0 (within 0.5 m of the ground under it)
whose host is an EXTERIOR wall or curtain_wall — the same definition
blender_power._entrance_door and sightline_rules (lines 149-170) use, widened to
accept a curtain wall as a host because add_curtain_wall replaces the door's
wall on a glazed storey. A door on a `partition` is a room door, not an entrance.
"""

from __future__ import annotations

import math

from zyg_workflows.arch_assistant import Drawing, EXT_MODULES, _num, ground_height, is_opening, world_to_local
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
TOOLS: list = []
PROMPT = ''

# ── the numbers ──────────────────────────────────────────────────────────────
EXT_WALL_KINDS = ('wall', 'curtain_wall', 'wall_arc')
DOOR_FALLBACK = ('door', 'double_door', 'door_sliding', 'door_french')
CANOPY_KINDS = ('canopy', 'awning')
TALL_STOREYS = 5  # from this many storeys up, a 0.9 m leaf is not the front door
MIN_DOOR_W = 1.8  # ... it needs this much clear width
OUT_M = 0.5  # how far outward the door point is moved to ask "is it under the canopy?"
HEAD_M = 0.3  # headroom a soffit keeps over the door head
CANOPY_MARGIN = 2.0  # a canopy should be this much wider than the door
AXIS_CLEAR_HALF = 1.0  # HALF the clear passage a door needs: 2 m, kept for 12 m out.
# design_rules.AXIS_HALF_W = 2.0 is the TREE strip on the approach;
# a porte-cochere's own columns legitimately stand beside the drive,
# so what is measured here is the clear passage they leave, not the
# width of the strip they may not enter.
AXIS_OUT = 12.0  # how far out the approach is kept clear
AXIS_IN = 6.0  # and how far INTO the lobby the axis is kept clear
AXIS_IN_HALF = 1.0  # the inward strip is 2 m wide
AXIS_DOOR_PLANE = 0.5  # ... and starts clear of the entrance wall's own thickness
LOBBY_FREE = 1.5  # a record of the lobby's OWN group is in the way only this near the
# door: furnish_lobby keeps 1.2 m clear off the entrance wall and puts
# its desk at the FAR end, which is where a reception desk belongs.
LAMP_NEAR = 0.6  # a lamp with LESS plan clearance than this to the canopy plate is
# touching it, and then it must stay under the soffit. The brief asked
# for 2 m; light_lamps_env's OWN default street lamps land 1.06 m
# outside job 94f5813b's canopy edge, so 2 m would put an error on
# every job that never touched a lamp. This rule is for HAND placement.
LAMP_MIN_H = 2.0  # ... and a name-matched asset is a lamp POST only from this height up
INSIDE_M = 1.0  # the point inside the door that must land in the lobby
LOBBY_TOL = 0.5  # how far outside the lobby rect that point may still count as in it
DOOR_GAP = 0.6  # the lobby's entrance side sits ON the facade, so the door is on its
# rect (gap 0). More than this and the visitor crosses something else
# first, whatever the 1 m point happens to land on.
LOBBY_ACROSS_M = 8.0  # a luxury lobby is a room, not a corridor...
LOBBY_DEEP_M = 6.0  # ... 8 m across AND 6 m deep
CLUTTER_M = 1.5  # a second door this near the entrance is a duplicate
MAX_FINDINGS = 8  # per code, as the contract requires

ROOM_EDGE_KINDS = ('partition', 'wall', 'curtain_wall', 'wall_arc', 'glass_partition')

LOBBY_WORDS = ('lobby', 'foyer', 'entrance hall', 'reception')
SEAT_KINDS = ('sofa', 'armchair', 'bench', 'chair')
DESK_KINDS = ('desk', 'reception_desk', 'counter')
LAMP_KINDS = ('lamp_post', 'lamp_floor', 'street_lamp', 'bollard_light')

# Not solids for the "what stands on the lobby axis" test: surfacing, paper,
# decks, finishes and anything hanging overhead.
AXIS_SKIP = frozenset(
    {
        'ground',
        'terrain',
        'pad',
        'zone',
        'road',
        'road_curved',
        'path',
        'sidewalk',
        'kerb',
        'parking_bay',
        'lawn',
        'grass',
        'site_boundary',
        'gridline',
        'annotation',
        'dimension',
        'dim_linear',
        'dim_angle',
        'label_text',
        'markup_note',
        'guide_arc',
        'guide_path',
        'guide_poly',
        'component',
        'link',
        'slab',
        'slab_poly',
        'roof_flat',
        'roof_pitched',
        'floor_finish',
        'skirting',
        'raised_floor',
        'ceiling',
        'suspended_ceiling',
        'rug',
        'canopy',
        'awning',
        'beam',
        'beam_i',
        'string_course',
        'cornice',
        'parapet_cap',
        'pilaster',
        'camera',
        'sun',
        'water_plane',
    }
)


# ── small helpers ────────────────────────────────────────────────────────────
def _ext(name):
    """A sibling family, fetched at CALL time: extensions load alphabetically."""
    return EXT_MODULES.get(name)


def _p(o, k, dflt=0.0) -> float:
    return _num((o.get('p') or {}).get(k), dflt)


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


def _door_kinds() -> tuple:
    DR = _ext('design_rules')
    return tuple(getattr(DR, 'DOOR_KINDS', None) or DOOR_FALLBACK)


def _column_kinds() -> tuple:
    DR = _ext('design_rules')
    return tuple(getattr(DR, 'COLUMN_KINDS', None) or ('column_round', 'column_rect', 'column_h'))


def _bbox(o) -> tuple:
    """Plan bbox of any record, rotation handled (envelope_rules owns it)."""
    ER = _ext('envelope_rules')
    if ER is not None:
        try:
            return ER.bbox_of(o)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('envelope bbox unavailable, using the plan stub: %s', _exc)
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    r = max(_p(o, 'w', 0.0), _p(o, 'd', 0.0), _p(o, 'len', 0.0), 2 * _p(o, 'r', 0.0), 0.3) / 2
    return x - r, z - r, x + r, z + r


def _height(o) -> float:
    """How tall the record stands above its own y."""
    h = _p(o, 'h', 0.0)
    if h <= 0:
        h = _p(o, 'bh', 0.0) * (_num(o.get('s'), 1.0) or 1.0)
    if h <= 0:
        sm = (o.get('p') or {}).get('size_m')
        if isinstance(sm, (list, tuple)) and len(sm) > 1:
            h = _num(sm[1], 0.0) * (_num(o.get('s'), 1.0) or 1.0)
    return h


def _is_lamp(o) -> bool:
    k = str(o.get('kind') or '')
    if k in LAMP_KINDS:
        return True
    nm = (str(o.get('name') or '') + ' ' + str((o.get('p') or {}).get('item') or '')).lower()
    # An asset only counts by its NAME, and a name is weak evidence: job 71ac02b0's
    # o756 is called "reception desk" and is 0.89 m tall, but the mesh it points at
    # is polyhaven's desk_lamp_arm_01_2k, so the word alone put a desk under the
    # porte-cochere. A lamp is only in anybody's way if it stands like a post.
    return k == 'asset' and 'lamp' in nm and _height(o) >= LAMP_MIN_H


def _covers(o, x, z, loose=True) -> bool:
    """Does the record's plan rect cover (x, z)? design_rules._covers knows that a
    canopy plate hangs OUTWARD from its wall and accepts either frame (loose)."""
    DR = _ext('design_rules')
    if DR is not None and hasattr(DR, '_covers'):
        try:
            return bool(DR._covers(o, x, z, loose=loose))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('design_rules._covers failed, using the plain rect test: %s', _exc)
    bb = _bbox(o)
    return bb[0] - 1e-6 <= x <= bb[2] + 1e-6 and bb[1] - 1e-6 <= z <= bb[3] + 1e-6


def _canopy_rect(c, nx, nz) -> tuple:
    """The plan rect a canopy plate really occupies, given the OUTWARD normal of
    the wall it hangs on. balconies_facade.t_add_canopy puts the record ON THE
    WALL'S OUTER FACE (`x, z = _face(...)`) and hangs the plate outward from
    there — it raises its columns at out*(d - 0.35) — so envelope_rules.bbox_of,
    which centres a w x d box on the record, puts half the plate inside the
    building and stops d/2 short outside. Point tests go through _covers(loose=
    True), which accepts either frame; only the gap arithmetic needs the real
    rect, and taking the union of both frames instead pushed it d metres INTO the
    building, where the fixture's own drive lamps then read as 1.1 m from an edge
    that is not there."""
    w, dd = _p(c, 'w', 0.0), _p(c, 'd', 0.0)
    if w <= 0 or dd <= 0:
        return _bbox(c)
    ry = _num(c.get('ry'), 0.0)
    ax, az = math.cos(ry), -math.sin(ry)
    cx, cz = _num(c.get('x'), 0.0), _num(c.get('z'), 0.0)
    xs, zs = [], []
    for f in (-0.5, 0.5):
        for g in (0.0, 1.0):
            xs.append(cx + ax * f * w + nx * g * dd)
            zs.append(cz + az * f * w + nz * g * dd)
    return (min(xs), min(zs), max(xs), max(zs))


def _soffit(o) -> float:
    """The underside of a canopy. balconies_facade.t_add_canopy line 300 sets
    y = wall base + the `height` argument and gives the plate p.t = 0.12, which
    rises ABOVE y — so the record's own y IS the soffit. A plate written with a
    p.h and no p.t is a box hung from y, whose underside is y + p.h."""
    p = o.get('p') or {}
    if _num(p.get('t'), 0.0) <= 0 and _num(p.get('h'), 0.0) > 0:
        return _num(o.get('y'), 0.0) + _num(p.get('h'), 0.0)
    return _num(o.get('y'), 0.0)


def _hit_words(o, words) -> bool:
    raw = ' '.join(
        str(x or '')
        for x in (o.get('name'), o.get('grp'), (o.get('p') or {}).get('name'), (o.get('p') or {}).get('use'))
    ).lower()
    return any(w in raw for w in words)


# ── the entrance itself ──────────────────────────────────────────────────────
def _host_wall(d: Drawing, door: dict):
    """The EXTERIOR wall a door sits in. design_rules._host_wall looks at
    ('wall', 'partition') only; a door on a glazed storey is hosted by the
    curtain_wall add_curtain_wall put in the wall's place, so that kind is
    accepted here and `partition` (an interior wall) is not.

    meta['host'] WINS when the record carries one. floor_plans writes it, and it
    is the only way to tell an interior door apart from an exterior one when the
    two stand back to back: replay B's o31 declares host o5, a partition (it is
    the hall door), but geometrically it also lies in the plane of the south
    facade 0.8 m from the real front door, so guessing made it a second
    entrance."""
    hid = (door.get('meta') or {}).get('host')
    if hid:
        w = d.find(hid) if hasattr(d, 'find') else None
        if w is None or w.get('kind') not in EXT_WALL_KINDS or w.get('hidden'):
            return None
        return w
    best = None
    for w in d.objs:
        if w.get('kind') not in EXT_WALL_KINDS or w.get('hidden'):
            continue
        if abs(_num(w.get('y'), 0.0) - _num(door.get('y'), 0.0)) > 0.5:
            continue
        L = _p(w, 'len', 4.0)
        lx, lz = world_to_local(w, door['x'], door['z'])
        if abs(lz) <= 0.35 and abs(lx) <= L / 2 + 0.3:
            score = (0 if w.get('grp') == door.get('grp') else 1, abs(lz))
            if best is None or score < best[0]:
                best = (score, w)
    return best[1] if best else None


def _axis(d: Drawing, door: dict, host: dict):
    """(x, z, nx, nz): the door centre and its OUTWARD normal, taken from the
    host wall's rotation and pointed away from the group's own centroid —
    design_rules._door_axis' arithmetic, over the wider host kinds."""
    ry = _num(host.get('ry'), 0.0)
    n1, n2 = (-math.sin(ry), -math.cos(ry)), (math.sin(ry), math.cos(ry))
    grp = [o for o in d.objs if o.get('grp') == host.get('grp') and o.get('kind') in EXT_WALL_KINDS]
    if grp:
        cx = sum(_num(o.get('x'), 0.0) for o in grp) / len(grp)
        cz = sum(_num(o.get('z'), 0.0) for o in grp) / len(grp)
    else:
        cx, cz = _num(host.get('x'), 0.0), _num(host.get('z'), 0.0)
    vx, vz = _num(host.get('x'), 0.0) - cx, _num(host.get('z'), 0.0) - cz
    n = n1 if (n1[0] * vx + n1[1] * vz) >= 0 else n2
    return _num(door.get('x'), 0.0), _num(door.get('z'), 0.0), n[0], n[1]


def entrances(d: Drawing) -> list:
    """[{door, host, x, z, nx, nz, grp}] — the exterior storey-0 doors."""
    kinds = _door_kinds()
    out = []
    for o in d.objs:
        if o.get('kind') not in kinds or o.get('hidden'):
            continue
        try:
            if _num(o.get('y'), 0.0) - ground_height(d, o['x'], o['z']) > 0.5:
                continue
        except Exception:  # noqa: BLE001
            if _num(o.get('y'), 0.0) > 0.5:
                continue
        host = _host_wall(d, o)
        if host is None:
            continue
        x, z, nx, nz = _axis(d, o, host)
        out.append(
            {'door': o, 'host': host, 'x': x, 'z': z, 'nx': nx, 'nz': nz, 'grp': host.get('grp') or o.get('grp') or ''}
        )
    return out


def _band(o, x0, z0, nx, nz) -> tuple:
    """(along_lo, along_hi, across_lo, across_hi) of a record's plan bbox in the
    door's own frame: +along is OUTWARD, across is sideways."""
    bb = _bbox(o)
    al, ac = [], []
    for cx in (bb[0], bb[2]):
        for cz in (bb[1], bb[3]):
            dx, dz = cx - x0, cz - z0
            al.append(dx * nx + dz * nz)
            ac.append(dx * -nz + dz * nx)
    return min(al), max(al), min(ac), max(ac)


# ── the lobby ────────────────────────────────────────────────────────────────
def _lobby_groups(d: Drawing) -> set:
    BP = _ext('building_program')
    words = tuple(getattr(BP, 'LOBBY_WORDS', None) or LOBBY_WORDS) if BP else LOBBY_WORDS
    if BP is not None and hasattr(BP, '_groups'):
        try:
            return set(BP._groups(d, words))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('building_program group scan failed, using the local word match: %s', _exc)
    return {o.get('grp') for o in d.objs if o.get('grp') and _hit_words(o, words)}


def _rect_of_groups(d: Drawing, grps, H: float) -> tuple:
    """The plan rectangle a set of room groups draws on storey 0, or None.
    building_program._room_rect takes the bbox of the record CENTRES, which is
    right for its 'how big is this room' question but wrong for this one: a room
    side lying on the facade gets NO partition (interior_rooms.t_add_room,
    FACADE_LINE_TOL), so the centres of the two side walls stop half a room short
    of the entrance wall and the door would read as outside its own lobby. The
    EXTENTS are taken instead, and only records on this storey.

    Only the ENCLOSING records count — the walls and partitions. A door record in
    one of those partitions has no depth, so _bbox gives it a square w x w plan
    footprint that sticks half a metre out through its own wall; the fixture's
    lobby grew 0.45 m past its south partition that way. Furniture would drag the
    rect about the same. A room is what its walls enclose."""
    box = None
    for o in d.objs:
        if o.get('hidden') or (o.get('grp') or '') not in grps:
            continue
        if str(o.get('kind') or '') not in ROOM_EDGE_KINDS:
            continue
        y = _num(o.get('y'), 0.0)
        if y > H * 1.6 or y < -1.0:
            continue
        bb = _bbox(o)
        box = bb if box is None else (min(box[0], bb[0]), min(box[1], bb[1]), max(box[2], bb[2]), max(box[3], bb[3]))
    return box


def _in_rect(rect, x, z, tol=0.0) -> bool:
    return rect is not None and rect[0] - tol <= x <= rect[2] + tol and rect[1] - tol <= z <= rect[3] + tol


def _storeys(envs, grp) -> int:
    """How many storeys stand behind this door, per envelope_rules.envelopes()."""
    try:
        return int(_num((envs.get(grp) or {}).get('storeys'), 0))
    except Exception:  # noqa: BLE001
        return 0


def _rect_gap(rect, x, z) -> float:
    """Distance from a plan point to a rectangle (0 when it is inside it)."""
    if rect is None:
        return 1e9
    return math.hypot(max(rect[0] - x, 0.0, x - rect[2]), max(rect[1] - z, 0.0, z - rect[3]))


def _what_is_there(d: Drawing, x, z, H: float, skip) -> str:
    """The name of whatever room group the point falls in, for the finding text."""
    best, area = '', 1e18
    for g in {o.get('grp') for o in d.objs if o.get('grp')} - set(skip):
        r = _rect_of_groups(d, {g}, H)
        if r is None or not _in_rect(r, x, z, 0.3):
            continue
        a = (r[2] - r[0]) * (r[3] - r[1])
        if a < area:
            best, area = g, a
    return f'it opens into "{best}"' if best else 'there is nothing behind it'


def _luxury(d: Drawing) -> bool:
    FR = _ext('finish_rules')
    if FR is not None:
        try:
            if FR.finish_level(d) == 'luxury':
                return True
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('finish level lookup failed: %s', _exc)
    req = str(getattr(d, 'request', '') or '').lower()
    if 'porte' in req:
        return True
    return any(f'{w} entrance' in req for w in ('nice', 'grand', 'impressive'))


def _cap(out: list, code: str, text: str, sev='error') -> None:
    """One finding per object, at most MAX_FINDINGS per code; the rest fold into
    a single '... and N more' line the model can still act on."""
    n = sum(1 for f in out if f['code'] == code)
    if n < MAX_FINDINGS:
        out.append({'sev': sev, 'code': code, 'text': text})
    elif n == MAX_FINDINGS:
        out.append({'sev': sev, 'code': code, 'text': '… and 1 more of the same'})
    else:
        for f in out:
            if f['code'] == code and f['text'].startswith('… and '):
                f['text'] = f'… and {int(f["text"].split()[2]) + 1} more of the same'
                break


# ── the check ────────────────────────────────────────────────────────────────
def check_entrance_quality(d: Drawing) -> list:
    out: list = []
    try:
        H = d.storey_h or 2.7
        ents = entrances(d)
        if not ents:
            return []
        lux = _luxury(d)
        ER, FR, BP = _ext('envelope_rules'), _ext('finish_rules'), _ext('building_program')
        envs = {}
        if ER is not None:
            try:
                envs = ER.envelopes(d)
            except Exception:  # noqa: BLE001
                envs = {}
        canopies = [o for o in d.objs if o.get('kind') in CANOPY_KINDS and not o.get('hidden')]
        columns = [o for o in d.objs if o.get('kind') in _column_kinds() and not o.get('hidden')]
        lamps = [o for o in d.objs if not o.get('hidden') and _is_lamp(o)]
        doors_all = [
            o
            for o in d.objs
            if o.get('kind') in _door_kinds() and not o.get('hidden') and abs(_num(o.get('y'), 0.0)) <= H * 0.6
        ]
        ent_ids = {e['door']['id'] for e in ents}
        lob_grps = _lobby_groups(d)
        lobby = _rect_of_groups(d, lob_grps, H) if lob_grps else None

        for e in ents:
            door, host, x0, z0, nx, nz = e['door'], e['host'], e['x'], e['z'], e['nx'], e['nz']
            grp = e['grp']
            dw = _p(door, 'w', 0.9)
            head = _num(door.get('y'), 0.0) + _p(door, 'sill', 0.0) + _p(door, 'h', 2.1)

            # (1) a tower's front door is not a 0.9 m leaf
            storeys = int((envs.get(grp) or {}).get('storeys') or 0) if envs else 0
            if storeys >= TALL_STOREYS and dw < MIN_DOOR_W:
                _cap(
                    out,
                    'ent_door_width',
                    f'the entrance {_lbl(door)} of the {storeys}-storey "{grp}" is only {dw:g} m wide — '
                    f'a front door serving {storeys} storeys needs {MIN_DOOR_W:g} m clear: delete '
                    f'which="{door["id"]}", then add_opening(group="{grp}", side=<the entrance side>, '
                    f'storey=0, kind="double_door", width=2.8)',
                )

            # (2)-(4) the canopy over the door, on a luxury / porte-cochere job
            px, pz = x0 + nx * OUT_M, z0 + nz * OUT_M
            over = [c for c in canopies if _covers(c, px, pz, loose=True)]
            if lux and not over:
                _cap(
                    out,
                    'ent_canopy_missing',
                    f'{_lbl(door)} has no canopy over it — a luxury entrance is covered where people arrive: '
                    f'add_canopy(group="{grp}", side=<the entrance side>, storey=0, width=12, depth=5, '
                    f'height=4.2, columns=4, material="mat_glass")',
                )
            for c in over:
                s = _soffit(c)
                if s < head + HEAD_M - 1e-6:
                    _cap(
                        out,
                        'ent_canopy_low',
                        f'{_lbl(c)}: its soffit at {s:.2f} m is under the head of {_lbl(door)} at '
                        f'{head:.2f} m + {HEAD_M:g} m headroom = {head + HEAD_M:.2f} m — delete '
                        f'which="{c["id"]}" and add_canopy(group="{grp}", side=<the entrance side>, '
                        f'storey=0, width={max(dw + CANOPY_MARGIN, 12):g}, depth=5, '
                        f'height={max(4.2, head + HEAD_M + 0.5):.1f}, columns=4)',
                    )
                cw = _p(c, 'w', 0.0)
                if 0 < cw < dw + CANOPY_MARGIN:
                    _cap(
                        out,
                        'ent_canopy_narrow',
                        f'{_lbl(c)} is {cw:g} m wide over a {dw:g} m door — a canopy covers the door and the '
                        f'step out of the car: {dw + CANOPY_MARGIN:g} m at least (add_canopy(width=12))',
                        sev='warn',
                    )

            # (5) a column standing in the opening
            for c in columns:
                lo, hi, alo, ahi = _band(c, x0, z0, nx, nz)
                if hi < -0.1 or lo > AXIS_OUT:
                    continue
                if alo > AXIS_CLEAR_HALF or ahi < -AXIS_CLEAR_HALF:
                    continue
                _cap(
                    out,
                    'ent_column_axis',
                    f'{_lbl(c)} stands {max(lo, 0.0):.1f} m out from {_lbl(door)} and inside the '
                    f'{2 * AXIS_CLEAR_HALF:g} m of clear passage the door needs — columns on the axis block '
                    f'the door: delete which="{c["id"]}" (add_canopy(columns=4) carries the plate from its '
                    f'corners, off the axis)',
                )

            # (6) a lamp under, or through, the canopy
            for c in over:
                s = _soffit(c)
                for lp in lamps:
                    if _covers(c, _num(lp.get('x'), 0.0), _num(lp.get('z'), 0.0), loose=True):
                        _cap(
                            out,
                            'ent_lamp_canopy',
                            f'{_lbl(lp)} stands UNDER {_lbl(c)} at the entrance — a lamp post belongs on the '
                            f'drive, not in the porte-cochere: delete which="{lp["id"]}" and '
                            f'add_street_furniture(cells=[<two cells 6 m either side of the axis>], '
                            f'kind="lamp_post")',
                        )
                        continue
                    top = _num(lp.get('y'), 0.0) + _height(lp)
                    if top <= s:
                        continue
                    bb, cb = _bbox(lp), _canopy_rect(c, nx, nz)
                    gap = math.hypot(max(cb[0] - bb[2], 0.0, bb[0] - cb[2]), max(cb[1] - bb[3], 0.0, bb[1] - cb[3]))
                    if gap <= LAMP_NEAR:
                        _cap(
                            out,
                            'ent_lamp_canopy',
                            f'{_lbl(lp)} is {top:.2f} m tall, {gap:.1f} m from {_lbl(c)} whose soffit is at '
                            f'{s:.2f} m — it runs through the canopy edge: delete which="{lp["id"]}" or move '
                            f'it at least {LAMP_NEAR:g} m clear',
                        )

            # (7) the door must open INTO the lobby — but only a building that WANTS
            # a lobby is asked for one. A family house's front door opens into a hall
            # 1.2 m wide with the stair in it, and telling it to add_room("Lobby") and
            # keep 6 m clear would be nonsense: job replay B is a 12 x 9 m house and
            # these two rules alone put 12 errors on it.
            wants = lux or _storeys(envs, grp) >= TALL_STOREYS
            ix, iz = x0 - nx * INSIDE_M, z0 - nz * INSIDE_M
            if not wants:
                pass
            elif lobby is None:
                _cap(
                    out,
                    'ent_lobby_behind',
                    f'the entrance {_lbl(door)} does not open into a lobby — there is no room named '
                    f'lobby/foyer/reception in the drawing: add_room(cell_from, cell_to, storey=0, '
                    f'name="Lobby") on the door axis (door_side omitted), at least 8 x 6 cells',
                )
            else:
                # Two ways to fail. The point 1 m inside the door may land outside the
                # lobby altogether (the room is elsewhere), OR the door may sit clear of
                # the lobby rect entirely — a lobby floated away from the facade, so the
                # visitor walks through whatever is in between first. The second test is
                # the door-to-rect gap: a lobby that really is behind the door has its
                # entrance side ON the facade (interior_rooms.t_add_room draws no
                # partition there), so the gap is 0.
                gap = _rect_gap(lobby, x0, z0)
                if not _in_rect(lobby, ix, iz, LOBBY_TOL) or gap > DOOR_GAP:
                    where = _what_is_there(d, ix, iz, H, lob_grps)
                    _cap(
                        out,
                        'ent_lobby_behind',
                        f'the entrance {_lbl(door)} does not open into the lobby — 1 m inside the door '
                        f'{where}, and the {lobby[2] - lobby[0]:.1f} x {lobby[3] - lobby[1]:.1f} m lobby '
                        f'rect starts {gap:.1f} m further in — add_room(cell_from, cell_to, storey=0, '
                        f'name="Lobby") on the door axis with its entrance side ON the facade '
                        f'(door_side omitted)',
                    )
                if lux:
                    # (8) size. building_program's own lobby item already measures this
                    # (_ev_lobby, LOBBY_ACROSS_M / LOBBY_DEEP_M) whenever plan_building
                    # has been called, so raise it here ONLY when that programme is not
                    # loaded — two errors for one defect cost the model two of its 28 calls.
                    have_prog = bool(BP is not None and FR is not None and FR.has_programme(d))
                    across = max(lobby[2] - lobby[0], lobby[3] - lobby[1])
                    deep = min(lobby[2] - lobby[0], lobby[3] - lobby[1])
                    if not have_prog and (across < LOBBY_ACROSS_M - 1e-6 or deep < LOBBY_DEEP_M - 1e-6):
                        _cap(
                            out,
                            'ent_lobby_size',
                            f'the lobby behind {_lbl(door)} is {across:.1f} x {deep:.1f} m and a luxury lobby is at '
                            f'least {LOBBY_ACROSS_M:g} m across AND {LOBBY_DEEP_M:g} m deep — a 10 x 3 m room is a '
                            f'corridor with a desk: add_room over a block at least 8 x 6 cells',
                        )
                    # (9) fit-out
                    desks = seats = 0
                    for o in d.objs:
                        if o.get('hidden') or not _in_rect(lobby, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0), 0.3):
                            continue
                        k = str(o.get('kind') or '')
                        if k in DESK_KINDS:
                            desks += 1
                        elif k in SEAT_KINDS or (
                            k == 'asset'
                            and any(
                                w in str(o.get('name') or '').lower() for w in ('sofa', 'armchair', 'settee', 'couch')
                            )
                        ):
                            seats += 1  # luxury seats are pack models (2026-09-16)
                    if desks == 0 and seats == 0:
                        _cap(
                            out,
                            'ent_lobby_fitout',
                            f'the lobby behind {_lbl(door)} is EMPTY — no reception desk and no seating in its '
                            f'{lobby[2] - lobby[0]:.1f} x {lobby[3] - lobby[1]:.1f} m: furnish_lobby(cell_from, '
                            f'cell_to, storey=0, entrance_side=<the entrance side>)',
                        )
                    # (10) floor
                    flat = []
                    for o in d.objs:
                        if o.get('hidden') or o.get('kind') not in ('slab', 'slab_poly'):
                            continue
                        if abs(_num(o.get('y'), 0.0)) > H * 0.6:
                            continue
                        if not _covers(o, (lobby[0] + lobby[2]) / 2, (lobby[1] + lobby[3]) / 2, loose=False):
                            continue
                        if FR is not None and FR.is_preset(o.get('mat')):
                            flat.append(o)
                    for o in flat[:1]:
                        _cap(
                            out,
                            'ent_lobby_floor',
                            f'the lobby floor is {_lbl(o)} in {o.get("mat")}, a flat preset — the floor of a luxury '
                            f'entrance is the first thing a visitor looks at: '
                            f'set_finish(group="{o.get("grp") or grp}", floor_material="acg_Marble021")',
                            sev='warn',
                        )

            # (11) a second door beside the entrance
            for o in doors_all:
                if o is door:
                    continue
                # ... in the SAME wall, or itself an entrance. A door 0.8 m behind the
                # front door in an interior partition is a draught lobby or a hall
                # door, not a duplicate: replay B's house has exactly that pair.
                if o['id'] not in ent_ids and (_host_wall(d, o) or {}).get('id') != host['id']:
                    continue
                dist = math.hypot(_num(o.get('x'), 0.0) - x0, _num(o.get('z'), 0.0) - z0)
                if dist <= CLUTTER_M:
                    _cap(
                        out,
                        'ent_door_clutter',
                        f'{_lbl(o)} stands {dist:.2f} m from the entrance {_lbl(door)} — two doors in one '
                        f'opening: delete which="{o["id"]}"',
                    )

            # (12) the lobby axis, from the door 6 m inward. Same scope as (7): it is
            # the LOBBY axis, so a building with no lobby to reach is not measured.
            skip_ids = {door['id'], host['id']}
            for o in d.objs if wants else ():
                if o.get('hidden') or o['id'] in skip_ids:
                    continue
                k = str(o.get('kind') or '')
                if k in AXIS_SKIP or is_opening(k) or k.startswith(('light_', 'guide_', 'mass_', 'sculpt_')):
                    continue
                if abs(_num(o.get('y'), 0.0) - _num(door.get('y'), 0.0)) > H * 0.6:
                    continue
                lo, hi, alo, ahi = _band(o, x0, z0, nx, nz)
                # AXIS_DOOR_PLANE: anything still in the thickness of the entrance wall
                # is the opening's own reveal, jamb or the partition butted to the facade
                # beside it — it is not standing IN the way in.
                if hi < -AXIS_IN or lo > -AXIS_DOOR_PLANE:
                    continue
                if alo > AXIS_IN_HALF or ahi < -AXIS_IN_HALF:
                    continue
                inward = -min(hi, -AXIS_DOOR_PLANE)
                if (o.get('grp') or '') in lob_grps:
                    # the lobby's OWN walls and fit-out. Its enclosing partitions are the
                    # room itself — whether the door reaches them is ent_lobby_behind's
                    # question, not this one — and its desk belongs at the far end. Only
                    # something of the lobby's own parked right AT the door is in the way.
                    if inward > LOBBY_FREE or _on_edge(lobby, o):
                        continue
                _cap(
                    out,
                    'ent_axis_blocked',
                    f'{_lbl(o)} stands {inward:.1f} m inside the entrance {_lbl(door)}, across the '
                    f'{2 * AXIS_IN_HALF:g} m lobby axis — the way in must be clear for {AXIS_IN:g} m: '
                    f'delete which="{o["id"]}" or move which="{o["id"]}" off the axis',
                )
    except Exception as e:  # noqa: BLE001 — a check never blocks the drawing
        return [{'sev': 'info', 'code': 'ent_check_error', 'text': f'check_entrance_quality failed: {e!r}'}]
    return out


def _on_edge(rect, o) -> bool:
    """Is this record one of the four partitions that DRAW the lobby rect?"""
    if rect is None:
        return False
    x, z = _num(o.get('x'), 0.0), _num(o.get('z'), 0.0)
    return min(abs(x - rect[0]), abs(x - rect[2])) <= 0.35 or min(abs(z - rect[1]), abs(z - rect[3])) <= 0.35


DESIGN_CHECKS = [check_entrance_quality]
