# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""opening_rules — a hole is a hole IN something (2026-09-16).

Why this family exists: on 2026-09-12 the assistant deleted the lobby's south
partition and its door stayed behind — a 2.8 m oak door standing in the facade
plane, overlapping the glass entrance double door by 1.8 m, hosted by nothing,
on a storey whose facade already had its entrance. Nothing reported it: every
tool's reply names only the record it just wrote, and an opening is not a solid,
so neither the envelope check nor the clearance check ever looks at it.

An opening is never a thing on its own. It is a RELATION: a hole cut in ONE
wall, inside that wall's length and under its head, not sharing its span with a
second hole, and — for a door on the ground — with something to step onto on the
far side. This module measures six of those relations and owns no kinds and no
tools:

  open_orphan          the opening has no wall of its own to sit in
  open_off_wall        it runs off the end of its wall, or over its head
  open_overlap         two openings share the same span in the same plane
  open_nowhere         a ground-floor door opens onto no walkable surface
  open_double_entrance two entrance doors on one facade of one group
  open_headroom        a door under 2.0 m clear

Plan axes as everywhere in the studio: column letters along +X, rows along +Z,
north = -Z (zmin), south = +Z (zmax), west = -X, east = +X.

HOSTING. An opening written since 2026-09-12 names its wall in meta.host, and
`delete` uses that to take the hole with the wall. When meta.host is absent (a
legacy record, a hand edit in the tab) the host is found by geometry — but only
among the wall-like records of the OPENING'S OWN GROUP. That group rule is what
catches the 09-12 defect: the abandoned lobby door kept group "Lobby" while the
only wall left in its plane was the tower facade, which is not its wall and
never held it. add_opening, add_windows, add_room and layout_floor all write the
opening into the host's group, so a matching group is an invariant of every
opening the tools make.
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

HOST_KINDS = ('wall', 'curtain_wall', 'partition', 'wall_arc')
EXTERIOR_HOST_KINDS = ('wall', 'curtain_wall')
FALLBACK_DOOR_KINDS = ('door', 'double_door', 'door_sliding', 'door_french')
EXTRA_OPENING_KINDS = ('window', 'window_strip', 'shopfront', 'skylight')

# A surface a person can step onto outside a door.
WALK_KINDS = (
    'pad',
    'path',
    'road',
    'road_curved',
    'sidewalk',
    'kerb',
    'parking_bay',
    'terrace',
    'deck',
    'plaza',
    'driveway',
)

ON_LINE = 0.12  # m from a wall's centre line an opening still sits IN it
END_TOL = 0.3  # m past a wall end an opening is still matched to it
OFF_TOL = 0.05  # m of overrun before "off the wall" is a real error
HEAD_TOL = 0.02  # m over the wall head before the lintel is a real error
PLANE_TOL = 0.3  # m between two wall lines that still read as one plane
PLANE_COS = 0.966  # ~15 deg: two openings must run the same way to share a plane
OVERLAP_TOL = 0.1  # m of shared span before two holes are one hole
STEP_OUT = 0.6  # m outside the wall a door needs something to stand on
STEP_DY = 0.35  # m the walkable surface may differ from the door's floor
ENTRANCE_NEAR = 6.0  # m between two entrance doors on one facade
DOOR_CLEAR = 2.0  # m of clear door height a person needs
MAX_PER_CODE = 8


def _p(o, k, dflt=0.0):
    return _num((o.get('p') or {}).get(k), dflt)


def _lbl(o) -> str:
    return f'{o["id"]} {o.get("name") or o.get("kind")}'


def _env_mod():
    return A.EXT_MODULES.get('envelope_rules')


def door_kinds() -> tuple:
    DR = A.EXT_MODULES.get('design_rules')
    return tuple(getattr(DR, 'DOOR_KINDS', None) or FALLBACK_DOOR_KINDS)


def opening_kinds() -> tuple:
    """The holes this family reads: the door kinds design_rules owns, plus the
    window kinds the studio actually registers (shopfront and skylight are not
    kinds today — they are listed so the check picks them up on the day they are)."""
    return door_kinds() + tuple(k for k in EXTRA_OPENING_KINDS if k in A.KINDS)


def _storey_of(d: Drawing, o: dict) -> int:
    H = d.storey_h or 2.7
    return int(round((_num(o.get('y'), 0.0) - _p(o, 'base', 0.0)) / H)) if H else 0


def _span(o: dict) -> tuple:
    """(bottom, top) of the hole in world height."""
    y = _num(o.get('y'), 0.0) + _p(o, 'sill', 0.0)
    return y, y + _p(o, 'h', 2.1)


def _wall_span(w: dict) -> tuple:
    y = _num(w.get('y'), 0.0)
    return y, y + _p(w, 'h', 2.7)


def _walls(d: Drawing) -> list:
    return [w for w in d.objs if w.get('kind') in HOST_KINDS and not w.get('hidden')]


def _on_line(w: dict, o: dict) -> tuple:
    """(along, perp) of the opening's centre in the wall's own plan frame."""
    lx, lz = A.world_to_local(w, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0))
    return lx, abs(lz)


def _find_host(d: Drawing, o: dict, walls=None):
    """The wall this opening is a hole in, or None.

    meta.host first (that is what `delete` cascades on), then geometry among the
    wall-like records of the opening's OWN group: the segment must pass within
    ON_LINE of the opening's centre, the centre must lie inside its length (plus
    END_TOL, so a hole that runs off the end is still matched to the wall it runs
    off), and the wall's vertical span must contain the opening's floor + 0.1.
    """
    hid = (o.get('meta') or {}).get('host')
    if hid:
        h = d.find(str(hid))
        if h is not None and h.get('kind') in HOST_KINDS and not h.get('hidden'):
            return h
        # 2026-09-16: a named host that is GONE is not proof of an orphan —
        # add_curtain_wall REPLACES a wall with a new curtain_wall record of the
        # same group on the same line, and every window it glazed still names the
        # wall that was consumed. Fall through to geometry; only when no wall of
        # the opening's own group stands in its plane is it really hanging in air.
        pass
    y = _num(o.get('y'), 0.0) + 0.1
    grp = o.get('grp') or ''
    best = None
    for w in walls if walls is not None else _walls(d):
        if (w.get('grp') or '') != grp:
            continue
        wy0, wy1 = _wall_span(w)
        if not (wy0 - 0.05 <= y <= wy1 + 0.05):
            continue
        along, perp = _on_line(w, o)
        if perp > ON_LINE or abs(along) > _p(w, 'len', 4.0) / 2 + END_TOL:
            continue
        score = (perp, -_p(w, 'len', 4.0))
        if best is None or score < best[0]:
            best = (score, w)
    return best[1] if best else None


def _foreign_wall(d: Drawing, o: dict, walls=None):
    """A wall-like record of ANOTHER group standing in this opening's plane — the
    facade the abandoned lobby door was left hanging in."""
    y = _num(o.get('y'), 0.0) + 0.1
    grp = o.get('grp') or ''
    for w in walls if walls is not None else _walls(d):
        if (w.get('grp') or '') == grp:
            continue
        wy0, wy1 = _wall_span(w)
        if not (wy0 - 0.05 <= y <= wy1 + 0.05):
            continue
        along, perp = _on_line(w, o)
        if perp <= ON_LINE and abs(along) <= _p(w, 'len', 4.0) / 2 + END_TOL:
            return w
    return None


def _covers_point(o: dict, x: float, z: float) -> bool:
    """Does this ground surface record cover the plan point? A road carries its
    length in p.len and its WIDTH in p.w (envelope_rules.bbox_of reads p.w as the
    thickness for a `len` record, so the rect is measured here)."""
    p = o.get('p') or {}
    if 'len' in p and 'w' in p:
        w, dd = _p(o, 'len', 0.0), _p(o, 'w', 0.0)
    elif 'w' in p and 'd' in p:
        w, dd = _p(o, 'w', 0.0), _p(o, 'd', 0.0)
    elif 'r' in p:
        w = dd = 2 * _p(o, 'r', 0.0)
    else:
        return False
    if w <= 0 or dd <= 0:
        return False
    sc = _num(o.get('s'), 1.0) or 1.0
    lx, lz = A.world_to_local(o, x, z)
    return abs(lx) <= w * sc / 2 + 0.05 and abs(lz) <= dd * sc / 2 + 0.05


def walkable_at(d: Drawing, x: float, z: float, y: float) -> bool:
    """Is there something to stand on at (x, z) within STEP_DY of height y?
    The ground itself counts (a pad levels it), so does a road/path/sidewalk
    record under the point, so does a slab or roof deck at that height."""
    try:
        if abs(A.ground_height(d, x, z) - y) <= STEP_DY:
            return True
    except Exception as _exc:  # noqa: BLE001 — never block a check
        _zyg_log.debug('ground height lookup failed: %s', _exc)
    for o in d.objs:
        if o.get('hidden') or o.get('kind') not in WALK_KINDS:
            continue
        if abs(_num(o.get('y'), 0.0) - y) <= STEP_DY + 0.15 and _covers_point(o, x, z):
            return True
    try:
        for top, _deck in A.deck_tops(d, x, z):
            if abs(top - y) <= STEP_DY:
                return True
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.debug('deck top lookup failed: %s', _exc)
    return False


_OUTWARD = {'north': (0.0, -1.0), 'south': (0.0, 1.0), 'west': (-1.0, 0.0), 'east': (1.0, 0.0)}


def _fits_width(host: dict) -> float:
    return round(max(0.6, _p(host, 'len', 4.0) - 0.6), 2)


def _cap(items: list, code: str, what: str) -> list:
    if len(items) <= MAX_PER_CODE:
        return items
    rest = len(items) - MAX_PER_CODE
    return items[:MAX_PER_CODE] + [
        {'sev': 'info', 'code': code, 'text': f'... and {rest} more {what}{"s" if rest > 1 else ""}'}
    ]


# ── the check ────────────────────────────────────────────────────────────────
def check_openings(d: Drawing) -> list:
    """Every hole sits in one wall, inside it, alone in its span, and a door on
    the ground opens onto something."""
    try:
        return _check_openings(d)
    except Exception as e:  # noqa: BLE001 — a check must never block the drawing
        return [{'sev': 'info', 'code': 'open_check_error', 'text': f'check_openings failed: {e!r}'}]


def _check_openings(d: Drawing) -> list:
    kinds = opening_kinds()
    doors = set(door_kinds())
    holes = [o for o in d.objs if o.get('kind') in kinds and not o.get('hidden')]
    if not holes:
        return []
    walls = _walls(d)
    E = _env_mod()
    envs = E.envelopes(d) if E is not None else {}

    orphan, off_wall, overlap, nowhere, double_ent, headroom = [], [], [], [], [], []
    hosts: dict = {}

    for o in holes:
        host = _find_host(d, o, walls)
        hosts[o['id']] = host
        st = _storey_of(d, o)
        w = _p(o, 'w', 1.0)
        h = _p(o, 'h', 2.1)

        # (1) no wall of its own
        if host is None:
            other = _foreign_wall(d, o, walls)
            extra = (
                (
                    f' (it stands in the plane of {other["id"]}, which belongs to group '
                    f'"{other.get("grp") or ""}", not to "{o.get("grp") or ""}")'
                )
                if other is not None
                else ''
            )
            orphan.append(
                {
                    'sev': 'error',
                    'code': 'open_orphan',
                    'text': f'{_lbl(o)} at ({o["x"]:.1f}, {o["z"]:.1f}) storey {st} has no wall to sit in — '
                    f'delete it (delete(which=["{o["id"]}"])) or draw the wall{extra}',
                }
            )
        else:
            # (2) off the end of its wall, or over its head
            L = _p(host, 'len', 4.0)
            along, _perp = _on_line(host, o)
            over = max((-L / 2) - (along - w / 2), (along + w / 2) - L / 2)
            head = (_num(o.get('y'), 0.0) - _num(host.get('y'), 0.0)) + _p(o, 'sill', 0.0) + h
            host_h = _p(host, 'h', d.storey_h or 2.7)
            why = ''
            if over > OFF_TOL:
                why = (
                    f'is {w:g} m wide {abs(along):.2f} m off the centre of {host["id"]} '
                    f'({host.get("kind")}, {L:g} m long): it runs {over:.2f} m past its end'
                )
            elif head > host_h + HEAD_TOL:
                why = (
                    f'reaches {head:.2f} m up a {host_h:g} m {host.get("kind")} {host["id"]}: '
                    f'the head is {head - host_h:.2f} m above the wall'
                )
            if why:
                off_wall.append(
                    {
                        'sev': 'error',
                        'code': 'open_off_wall',
                        'text': f'{_lbl(o)} {why} — delete it (delete(which=["{o["id"]}"])) and '
                        f'add_opening(group="{host.get("grp") or ""}", side=<side>, storey={st}, '
                        f'kind="{o.get("kind")}", width={_fits_width(host)})',
                    }
                )

        # (6) a door a person cannot walk through
        if o.get('kind') in doors and h < DOOR_CLEAR:
            headroom.append(
                {
                    'sev': 'error',
                    'code': 'open_headroom',
                    'text': f'{_lbl(o)} is only {h:g} m tall — under the {DOOR_CLEAR:g} m clear a door '
                    f'needs; delete it (delete(which=["{o["id"]}"])) and add_opening(..., '
                    f'height=2.1)',
                }
            )

    # (3) two holes in one plane sharing a span
    seen = set()
    for i, a in enumerate(holes):
        ay0, ay1 = _span(a)
        aw = _p(a, 'w', 1.0)
        for b in holes[i + 1 :]:
            if abs(math.cos(_num(a.get('ry'), 0.0) - _num(b.get('ry'), 0.0))) < PLANE_COS:
                continue
            ha, hb = hosts.get(a['id']), hosts.get(b['id'])
            lx, lz = A.world_to_local(a, _num(b.get('x'), 0.0), _num(b.get('z'), 0.0))
            same_host = ha is not None and hb is not None and ha['id'] == hb['id']
            if not same_host and abs(lz) > PLANE_TOL:
                continue
            by0, by1 = _span(b)
            if min(ay1, by1) - max(ay0, by0) <= 0:
                continue
            bw = _p(b, 'w', 1.0)
            share = min(aw / 2, lx + bw / 2) - max(-aw / 2, lx - bw / 2)
            if share <= OVERLAP_TOL:
                continue
            key = (a['id'], b['id'])
            if key in seen:
                continue
            seen.add(key)
            where = f'in {ha["id"]}' if same_host else 'in the same wall plane'
            overlap.append(
                {
                    'sev': 'error',
                    'code': 'open_overlap',
                    'text': f'{_lbl(a)} overlaps {_lbl(b)} by {share:.2f} m {where} — two holes cut the '
                    f'same piece of wall; delete one (delete(which=["{b["id"]}"]))',
                }
            )

    # (4) + (5) the doors on the ground, on a facade
    entrances: dict = {}
    for o in holes:
        if o.get('kind') not in doors or _storey_of(d, o) != 0:
            continue
        host = hosts.get(o['id'])
        if host is None or host.get('kind') not in EXTERIOR_HOST_KINDS:
            continue
        grp = host.get('grp') or ''
        env = envs.get(grp)
        if env is None or E is None:
            continue
        side = E.touches_facade(env, _num(o.get('x'), 0.0), _num(o.get('z'), 0.0))
        if side is None:
            continue
        entrances.setdefault((grp, side), []).append(o)
        nx, nz = _OUTWARD[side]
        px, pz = _num(o.get('x'), 0.0) + nx * STEP_OUT, _num(o.get('z'), 0.0) + nz * STEP_OUT
        if not walkable_at(d, px, pz, _num(o.get('y'), 0.0)):
            nowhere.append(
                {
                    'sev': 'warn',
                    'code': 'open_nowhere',
                    'text': f'{_lbl(o)} on the {side} facade of "{grp}" opens onto nothing — there is no '
                    f'ground, pad, path or road at {_num(o.get("y"), 0.0):g} m '
                    f'{STEP_OUT:g} m outside it; add_road / add_object(kind="path") under the '
                    f'approach, or move the door',
                }
            )

    for (grp, side), recs in sorted(entrances.items()):
        for i, a in enumerate(recs):
            for b in recs[i + 1 :]:
                gap = math.hypot(a['x'] - b['x'], a['z'] - b['z'])
                if gap > ENTRANCE_NEAR:
                    continue
                double_ent.append(
                    {
                        'sev': 'error',
                        'code': 'open_double_entrance',
                        'text': f'two entrance doors {a["id"]},{b["id"]} {gap:.1f} m apart on the '
                        f'{side} facade of "{grp}" — a building has ONE entrance on a face: '
                        f'keep one (delete(which=["{b["id"]}"]))',
                    }
                )

    out = []
    out += _cap(orphan, 'open_orphan', 'opening with no wall')
    out += _cap(off_wall, 'open_off_wall', 'opening off its wall')
    out += _cap(overlap, 'open_overlap', 'overlapping opening')
    out += _cap(headroom, 'open_headroom', 'door under 2 m')
    out += _cap(double_ent, 'open_double_entrance', 'doubled entrance')
    out += _cap(nowhere, 'open_nowhere', 'door onto nothing')
    return out


DESIGN_CHECKS = [check_openings]
