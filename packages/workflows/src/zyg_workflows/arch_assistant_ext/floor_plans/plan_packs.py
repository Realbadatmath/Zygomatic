# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""floor_plans.plan_packs — the packs on disk, the mirror/rotate/scale transform
and everything that READS a Drawing (slabs, plates, cores, approaches, landings,
facades, wall claims). Moved verbatim out of floor_plans.py (2026-10-06)."""

from __future__ import annotations

import json
import math
import os

from zyg_workflows import arch_assistant as A
from zyg_workflows import paths
from zyg_workflows.arch_assistant import (
    Drawing,
    MATERIALS,
    _num,
)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.arch_assistant_ext.floor_plans')


KINDS: dict = {}
OPENINGS: list = []

DEFAULT_DIR = paths.ZYG_PLANS_DIR
EXT_KEY = 'floor_layouts'  # the store repeat_floor reads
ATTR_KEY = 'attributions'

SCALE_MIN, SCALE_MAX = 0.88, 1.12
SIDES_CW = ('north', 'east', 'south', 'west')
KINDS_OK = ('unit', 'floor', 'house')
# schema fixture kind -> the studio kind that draws it
FIXTURE_KIND = {
    'toilet': 'toilet',
    'washbasin': 'washbasin',
    'bathtub': 'bathtub',
    'shower': 'shower',
    'kitchen': 'kitchen_counter',
    'sink': 'sink',
}
CORE_KINDS = ('stair', 'lift', 'elevator')


# ── the packs on disk ────────────────────────────────────────────────────────
_CACHE: dict = {'dir': None, 'packs': None, 'plans': {}}


def plans_dir() -> str:
    """Where the packs live: $ZYG_PLANS_DIR (the tests point it at fixtures)."""
    return os.environ.get('ZYG_PLANS_DIR') or DEFAULT_DIR


def packs(force=False) -> dict:
    """pack name -> {'manifest', 'rows', 'dir'}. Read once per directory; the
    per-plan JSON is NOT read here (the big pack's index is already a few MB)."""
    root = plans_dir()
    if _CACHE['packs'] is not None and _CACHE['dir'] == root and not force:
        return _CACHE['packs']
    out: dict = {}
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    for n in names:
        pd = os.path.join(root, n)
        man_f, idx_f = os.path.join(pd, 'pack.json'), os.path.join(pd, 'index.json')
        if not (os.path.isfile(man_f) and os.path.isfile(idx_f)):
            continue
        try:
            with open(man_f, encoding='utf-8') as fh:
                man = json.load(fh)
            with open(idx_f, encoding='utf-8') as fh:
                idx = json.load(fh)
        except (OSError, ValueError) as _exc:
            _zyg_log.warning('plan pack %s unreadable, skipped: %s', n, _exc)
            continue
        if not str(man.get('licence') or '').strip():
            continue  # no licence named -> not a pack we draw from
        rows = [r for r in (idx.get('rows') or []) if isinstance(r, dict) and r.get('id')]
        out[str(man.get('pack') or n)] = {'manifest': man, 'rows': rows, 'dir': pd}
    _CACHE.update({'dir': root, 'packs': out, 'plans': {}})
    return out


def row_of(plan_id: str) -> tuple:
    """(index row, pack name) for a plan id, or (None, '')."""
    for name, pk in packs().items():
        for r in pk['rows']:
            if r['id'] == plan_id:
                return r, name
    return None, ''


def load_plan(plan_id: str) -> dict | None:
    """The full plan JSON, read on demand and kept for the length of the call."""
    pid = str(plan_id or '').strip()
    if pid in _CACHE['plans']:
        return _CACHE['plans'][pid]
    row, name = row_of(pid)
    if not row:
        return None
    f = os.path.join(packs()[name]['dir'], 'plans', pid + '.json')
    try:
        with open(f, encoding='utf-8') as fh:
            plan = json.load(fh)
    except (OSError, ValueError):
        return None
    plan.setdefault('pack', name)
    _CACHE['plans'][pid] = plan
    return plan


def attribution_of(pack_name: str) -> str:
    pk = packs().get(pack_name) or {}
    man = pk.get('manifest') or {}
    return str(man.get('attribution') or man.get('title') or pack_name)


# ── the transform ────────────────────────────────────────────────────────────
def _mirror_side(side: str) -> str:
    return {'east': 'west', 'west': 'east'}.get(side, side)


def _rot_side(side: str, deg: int) -> str:
    """Rotating the plan `deg` clockwise in plan view moves its sides round."""
    if side not in SIDES_CW:
        return side
    return SIDES_CW[(SIDES_CW.index(side) + (int(deg) % 360) // 90) % 4]


class _T:
    """mirror (about the plan's own x centre) -> rotate 0/90/180/270 -> scale.
    Points stay in a frame whose bbox min is (0, 0); `ox`/`oz` translate it."""

    def __init__(self, w, d, mirror=False, rot=0, scale=1.0):
        self.w, self.d = float(w), float(d)
        self.mirror = bool(mirror)
        self.a = int(rot) % 360
        self.s = float(scale)
        self.ox = self.oz = 0.0

    @property
    def size(self) -> tuple:
        return (self.d * self.s, self.w * self.s) if self.a in (90, 270) else (self.w * self.s, self.d * self.s)

    def pt(self, x, z) -> tuple:
        x, z = float(x), float(z)
        if self.mirror:
            x = self.w - x
        if self.a == 90:
            x, z = self.d - z, x
        elif self.a == 180:
            x, z = self.w - x, self.d - z
        elif self.a == 270:
            x, z = z, self.w - x
        return self.ox + x * self.s, self.oz + z * self.s

    def ang(self, ry) -> float:
        r = math.pi - float(ry) if self.mirror else float(ry)
        return r - math.radians(self.a)

    def side(self, side: str) -> str:
        return _rot_side(_mirror_side(side) if self.mirror else side, self.a)


def _snap(v, s):
    s = _num(s, 0.0)
    return round(v / s) * s if s > 0 else v


def _clamp(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _fit_scale(W, D, w, d) -> float:
    if w <= 0 or d <= 0:
        return 0.0
    return min(W / w, D / d)


def _best_rot(W, D, w, d) -> tuple:
    """(rotation, plan w, plan d) — the orientation whose proportions are closer."""
    best = None
    for rot, (pw, pd) in ((0, (w, d)), (90, (d, w))):
        err = abs(pw - W) / max(W, 1e-6) + abs(pd - D) / max(D, 1e-6)
        if best is None or err < best[0]:
            best = (err, rot, pw, pd)
    return best[1], best[2], best[3]


# ── reading the drawing ──────────────────────────────────────────────────────
def _group_slab(d: Drawing, group: str, storey: int) -> tuple:
    """(slab record, error) — the group's floor slab at that storey."""
    recs = [o for o in d.select(group) if not o.get('hidden')]
    if not recs:
        return None, f'refused: no group "{group}" in the drawing — pass the name draw_box returned'
    slabs = [o for o in recs if o['kind'] == 'slab']
    if not slabs:
        return None, (
            f'refused: "{group}" has no slab — place the plan on cells instead '
            f'(place_plan(cell_from=…, cell_to=…, shell=true))'
        )
    at = [o for o in slabs if A.storey_index(d, o) == int(storey)]
    if not at:
        have = sorted({A.storey_index(d, o) for o in slabs})
        return None, (f'refused: "{group}" has no slab on storey {int(storey)} (it has storeys {have[0]}..{have[-1]})')
    return at[0], ''


def _slab_rect(slab: dict) -> tuple:
    w = abs(_num((slab['p'] or {}).get('w'), 0.0))
    dd = abs(_num((slab['p'] or {}).get('d'), 0.0))
    return (slab['x'] - w / 2, slab['z'] - dd / 2, slab['x'] + w / 2, slab['z'] + dd / 2)


def _group_plate(d: Drawing, group: str, storey: int) -> tuple:
    """(rect, y, error) — the WHOLE plate at that storey: a stair cuts the slab
    into pieces (cut_slab_void), so the bay is the union of them, not the first."""
    slab, err = _group_slab(d, group, storey)
    if err:
        return None, 0.0, err
    rects = [
        _slab_rect(o)
        for o in d.select(group)
        if o['kind'] == 'slab' and not o.get('hidden') and A.storey_index(d, o) == int(storey)
    ]
    rect = (min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects))
    return rect, slab['y'] + _num((slab['p'] or {}).get('t'), 0.22), ''


def _group_wall_mat(d: Drawing, group: str) -> str:
    for o in d.select(group) if group else []:
        if o['kind'] == 'wall' and o.get('mat') in MATERIALS:
            return o['mat']
    return 'mat_concrete'


def _rec_bbox(o: dict) -> tuple:
    """(x0, z0, x1, z1) of a record's plan footprint, turned by its own ry.
    envelope_rules knows the stair kinds properly; _p_footprint is the fallback."""
    ER = A.EXT_MODULES.get('envelope_rules')
    if ER is not None and hasattr(ER, 'bbox_of'):
        try:
            return tuple(ER.bbox_of(o))
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('envelope bbox unavailable, using the footprint fallback: %s', _exc)
    try:
        fw, fd = A._p_footprint(o['p'] or {})
    except Exception:  # noqa: BLE001
        fw = fd = 0.0
    fw, fd = max(fw, 0.6), max(fd, 0.6)
    return (o['x'] - fw / 2, o['z'] - fd / 2, o['x'] + fw / 2, o['z'] + fd / 2)


def _core_rects(d: Drawing, group: str, storey: int, rect=None, want=CORE_KINDS) -> list:
    """Footprint rectangles of the stair / lift records standing on that storey of
    the group. `rect` (the plate) also catches a core drawn in its OWN group —
    add_stair names its group after the cell, not after the box it stands in.
    `want` narrows it to some of CORE_KINDS ( ('stair',) = the stairs only )."""
    out = []
    pool = list(d.select(group)) if group else []
    if rect is not None:
        have = {o['id'] for o in pool}
        pool += [o for o in d.objs if o['id'] not in have]
    H = d.storey_h or 2.7
    lvl = int(storey) * H
    for o in pool:
        k = str(o.get('kind') or '')
        if o.get('hidden') or not any(k.startswith(c) or c in k for c in want):
            continue
        # 2026-09-11: a lift shaft is ONE record at storey 0 spanning the tower, and a
        # legacy stair one tall record — "starts on this storey" missed both, and ten
        # toilets landed inside the lift. On the storey = its vertical SPAN covers it.
        p = o.get('p') or {}
        h = _num(p.get('h'), 0.0)
        if h <= 0 and p.get('steps'):
            h = _num(p.get('steps'), 0.0) * _num(p.get('rise'), 0.0)
        y0 = _num(o.get('y'), 0.0)
        on_storey = (A.storey_index(d, o) == int(storey)) or (h > 0 and y0 - 0.3 <= lvl <= y0 + h - 0.3)
        if not on_storey:
            continue
        bb = _rec_bbox(o)
        fw, fd = max(bb[2] - bb[0], 0.6), max(bb[3] - bb[1], 0.6)
        cx, cz = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
        if rect is not None and not (rect[0] <= cx <= rect[2] and rect[1] <= cz <= rect[3]):
            continue
        out.append((cx - fw / 2, cz - fd / 2, cx + fw / 2, cz + fd / 2))
    return out


def _approach_rects(d: Drawing, group: str, storey: int, rect=None) -> list:
    """The floor a person needs at the foot of every stair on that storey, as
    keep-out rectangles — stairs_vertical.approach_bboxes owns the geometry
    (APPROACH_M = 1.2 m beyond the flight's local -X edge for a u stair).
    2026-09-14: place_plan(align="core") dropped a real Swiss floor whose own
    partitions walled the stair's foot shut — 8 circ_stair_approach errors on
    a plan the placer had trimmed against the stair WELL only."""
    S = A.EXT_MODULES.get('stairs_vertical')
    zones_of = getattr(S, 'approach_bboxes', None) if S is not None else None
    if not callable(zones_of):
        return []
    pool = list(d.select(group)) if group else []
    if rect is not None:
        have = {o['id'] for o in pool}
        pool += [o for o in d.objs if o['id'] not in have]
    H = d.storey_h or 2.7
    lvl = int(storey) * H
    out = []
    for o in pool:
        k = str(o.get('kind') or '')
        if o.get('hidden') or not k.startswith('stair'):
            continue
        p = o.get('p') or {}
        h = _num(p.get('h'), 0.0)
        if h <= 0 and p.get('steps'):
            h = _num(p.get('steps'), 0.0) * _num(p.get('rise'), 0.0)
        y0 = _num(o.get('y'), 0.0)
        if not ((A.storey_index(d, o) == int(storey)) or (h > 0 and y0 - 0.3 <= lvl <= y0 + h - 0.3)):
            continue
        if rect is not None and not (
            rect[0] <= _num(o.get('x'), 0.0) <= rect[2] and rect[1] <= _num(o.get('z'), 0.0) <= rect[3]
        ):
            continue
        for z in zones_of(o) or []:
            out.append((float(z[0]), float(z[1]), float(z[2]), float(z[3])))
    return out


def _landing_rects(d: Drawing, group: str, storey: int, rect=None) -> list:
    """The lobby in front of every lift door on that storey, as keep-out rects.

    2026-09-16: the tiler kept units out of the shaft WELL and nothing else, so
    a unit's own partition stood 0.4 m in front of the lift doors on every
    storey of a replayed tower (circ_lift_landing, and it was right — you cannot
    walk out of a lift into a wall). circulation_rules owns the geometry
    (LIFT_LANDING_M = 1.8 m over the whole shaft width, on p.door_side); it is
    fetched lazily because the extensions load alphabetically and a drawing may
    run without that family at all."""
    C = A.EXT_MODULES.get('circulation_rules')
    E = A.EXT_MODULES.get('envelope_rules')
    rect_of = getattr(C, '_landing_rect', None) if C is not None else None
    if not callable(rect_of) or E is None:
        return []
    pool = list(d.select(group)) if group else []
    if rect is not None:
        have = {o['id'] for o in pool}
        pool += [o for o in d.objs if o['id'] not in have]
    H = d.storey_h or 2.7
    lvl = int(storey) * H
    out = []
    for o in pool:
        if o.get('hidden') or str(o.get('kind') or '') != 'elevator_shaft':
            continue
        p = o.get('p') or {}
        h = _num(p.get('h'), 0.0)
        y0 = _num(o.get('y'), 0.0)
        if not ((A.storey_index(d, o) == int(storey)) or (h > 0 and y0 - 0.3 <= lvl <= y0 + h - 0.3)):
            continue
        if rect is not None and not (
            rect[0] <= _num(o.get('x'), 0.0) <= rect[2] and rect[1] <= _num(o.get('z'), 0.0) <= rect[3]
        ):
            continue
        face = str(p.get('door_side') or 'south').strip().lower()
        try:
            r = rect_of(E.bbox_of(o), face)
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.debug('door rect unavailable, record skipped: %s', _exc)
            continue
        out.append((float(r[0]), float(r[1]), float(r[2]), float(r[3])))
    return out


def _core_centre(d: Drawing, group: str, storey: int, rect=None) -> tuple:
    """Where align="core" drops the plan's stair. The STAIRS decide it when there
    are any — a plan's stair polygon belongs on the drawn stair, not on the mean
    of a stair and three lifts. `rect` catches a core in its own group."""
    rects = _core_rects(d, group, storey, rect, ('stair',)) or _core_rects(d, group, storey, rect)
    pts = [((r[0] + r[2]) / 2, (r[1] + r[3]) / 2) for r in rects]
    if not pts:
        return None
    return sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)


def _in_rects(x, z, rects) -> bool:
    return any(r[0] - 0.05 <= x <= r[2] + 0.05 and r[1] - 0.05 <= z <= r[3] + 0.05 for r in rects)


def _clip_segment(ax, az, bx, bz, rects, pad=0.05, min_len=0.3) -> list:
    """The parts of segment a-b that lie OUTSIDE every rect (each grown by pad):
    a partition running through the stair well becomes the two stubs either
    side of it (Liang-Barsky per rect). [] when nothing usable is left.
    2026-09-11: the centre-point test kept every wall whose midpoint fell
    outside the core — 120 partitions crossed the stair of the replayed tower."""
    pieces = [(ax, az, bx, bz)]
    for r in rects:
        x0, z0, x1, z1 = r[0] - pad, r[1] - pad, r[2] + pad, r[3] + pad
        nxt = []
        for pax, paz, pbx, pbz in pieces:
            dx, dz = pbx - pax, pbz - paz
            t0, t1, inside = 0.0, 1.0, True
            for p_, q_ in ((-dx, pax - x0), (dx, x1 - pax), (-dz, paz - z0), (dz, z1 - paz)):
                if abs(p_) < 1e-12:
                    if q_ < 0:
                        inside = False
                        break
                    continue
                tt = q_ / p_
                if p_ < 0:
                    t0 = max(t0, tt)
                else:
                    t1 = min(t1, tt)
            if not inside or t0 >= t1:
                nxt.append((pax, paz, pbx, pbz))  # misses this rect
                continue
            if t0 > 0:
                nxt.append((pax, paz, pax + dx * t0, paz + dz * t0))
            if t1 < 1:
                nxt.append((pax + dx * t1, paz + dz * t1, pbx, pbz))
        pieces = nxt
    return [p for p in pieces if math.hypot(p[2] - p[0], p[3] - p[1]) >= min_len]


def _poly_centre(pts) -> tuple:
    xs = [p[0] for p in pts]
    zs = [p[1] for p in pts]
    return (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2


def _facade(d: Drawing, group: str, side: str, storey: int) -> tuple:
    """(wall record, error) — the group's facade wall on that side, glazed or not."""
    if not group:
        return None, 'no group'
    return A.wall_on_side(d, group, side, storey, ('wall', 'partition', 'curtain_wall'))


# 2026-09-16: an opening is placed by its CENTRE but it is cut at its JAMBS.
# The old clamp held the centre 0.3 m off each wall end, which says nothing
# about where the leaf lands: a 0.95 m plan door centred 0.3 m from the end of
# a 2.75 m party wall hangs 0.175 m out over thin air, and opening_rules was
# right to say so. Half a leaf plus one JAMB_M of wall each side puts the
# opening inside its host by construction.
JAMB_M = 0.10  # m of wall that must remain beside an opening
HEAD_LINTEL = 0.10  # m of wall that must remain over an opening's head
MIN_GLASS = 0.30  # m of glass under which a window is not worth drawing
OVERLAP_M = 0.10  # m two openings may share of one wall (opening_rules.OVERLAP_TOL)


def _on_wall(w: dict, x, z, width: float = 0.0) -> tuple:
    """The point on wall `w` nearest (x, z), as t_add_opening would place it —
    held back by half of `width` plus JAMB_M so the whole leaf is on the wall.

    (None, None) when the wall is too short to carry that leaf at all: the
    caller drops the opening rather than cut a hole wider than its host."""
    L = _num((w['p'] or {}).get('len'), 4.0)
    half = max(0.0, _num(width, 0.0)) / 2.0
    lo, hi = half + JAMB_M, L - half - JAMB_M
    if hi < lo:
        return None, None
    lx, _lz = A.world_to_local(w, x, z)
    return A._wall_world(w, _clamp(lx + L / 2, lo, hi))


def _claim(placed: dict, host: dict, x, z, width) -> bool:
    """True when an opening `width` wide may be cut in `host` at (x, z): it
    shares under OVERLAP_M of the wall with every opening already cut in it.

    2026-09-16: a surveyed plan lists the door between two rooms ONCE PER ROOM,
    so the placer cut the same hole twice — "o485 plan door overlaps o500 plan
    door by 0.98 m in o454", four such pairs on one replayed tower, plus two
    pairs of windows on one facade and an entrance with a window over the top of
    it. The wall keeps the FIRST hole. Doors are placed before the entrance and
    the entrance before the windows, so a door never loses its opening to a
    window. Vertical spans are not consulted: this is a plan replay, there are
    no transom lights in it, and two holes on the same 0.1 m of wall are worth
    refusing whatever their heights."""
    lx, _lz = A.world_to_local(host, x, z)
    half = max(0.0, _num(width, 0.0)) / 2.0
    lo, hi = lx - half, lx + half
    seen = placed.setdefault(host['id'], [])
    for a, b in seen:
        if min(hi, b) - max(lo, a) > OVERLAP_M:
            return False
    seen.append((lo, hi))
    return True
