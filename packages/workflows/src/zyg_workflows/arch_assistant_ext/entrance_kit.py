# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""entrance_kit — "a nice entrance with a lobby" as ONE call (2026-09-16).

The 09-12 live run spent 9 draw calls on an entrance and got all four pieces
wrong: the door was hung with no canopy over it (an orphan), the lobby was
drawn with a partition ON the facade line (env_facade_partition o528), the WC
ended up in front of the lift doors and the lamp posts stood under the canopy
soffit. Every one of those is a rule some family already owns — the model just
never called the tools in an order that satisfied them all at once.

build_entrance does the order once:

    door -> canopy over it -> lobby behind it -> fit-out -> drive -> lamps -> trees

and every step goes through A.call_tool, so add_opening still refuses a curtain
wall, add_room still strips a facade-line partition, site_landscape still
refuses a lamp inside a canopy footprint and clamps it under the soffit, and
furnish_lobby still refuses a room under 6 m. On the FIRST 'refused:' the
drawing is put back the way it was and the refusal is returned unchanged, so a
half-built arrival never survives.

Two pieces of arithmetic are not obvious and are done here:

* THE LOBBY DOOR IS WIDE. add_room's default 0.9 m door plus furnish_lobby's
  sofa cluster seals the route from the entrance to the core — walk_rules
  reports walk_entrance_core on the resulting drawing (measured on both a
  20 x 20 and a 40 x 40 plate, so it is not a near-core effect). A LOBBY_DOOR_W
  opening through the back partition clears it.
* THE LOBBY IS DEEPER THAN IT LOOKS. building_program measures a room from the
  bbox of its record CENTRES, and the fit-out sits 1.75 m in from the entrance
  edge and 0.85 m in from the desk wall, so a lobby has to be about 2.6 m
  deeper than the programme's LOBBY_DEEP_M before the row reads ok. On a
  luxury finish the depth is raised to LUX_LOBBY_D for that reason.

This family owns NO kinds and NO checks: every record is made by an existing
tool and the existing families already measure them.
"""

from __future__ import annotations

import copy
import math

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, _num
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
DESIGN_CHECKS: list = []

SIDES = ('north', 'east', 'south', 'west')
OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}
STYLES = ('luxury', 'standard')

DOOR_REUSE_M = 6.0  # an exterior door this close to the axis is re-used, not doubled
LOBBY_DOOR_W = 3.6  # m — the opening through the lobby's back partition (see docstring)
LUX_LOBBY_D = 9.0  # m — depth that makes building_program's lobby row read ok
MIN_LOBBY_M = 6.0  # lobby_fitout.MIN_SIDE: below this furnish_lobby refuses
PLATE_MARGIN_M = 2.0  # the lobby may not come closer than 1 m to either side facade
CORE_CLEAR_M = 1.8  # m of floor between a lobby partition and the lift landing
OPEN_GAP_M = 3.0  # a core this close to the back edge: no back partition, the lobby flows into it
LAMP_MIN_H, LAMP_MAX_H = 3.0, 4.0  # site_landscape.FURNITURE_RANGE['lamp_post'] floor, and our cap
LAMP_SOFFIT_GAP = 0.5  # site_landscape.SOFFIT_GAP
DRIVE_W = 8.0  # m of carriageway
DRIVE_NEAR_M = 6.0  # the drive starts this far out from the facade
DRIVE_FAR_M = 30.0
TREE_OFF_MIN = 7.0  # m off the axis — the brief's clearance
TREE_NEAR_M, TREE_FAR_M = 15.0, 29.0
ENTRANCE_CODES = ('ent_', 'open_', 'walk_entrance_core', 'sight')

# ── the presence of the arrival itself (2026-09-16) ─────────────────────────
# The live acceptance run's entrance was GEOMETRICALLY right and read as
# nothing: a plain oak leaf in a glass shopfront under an unlit white slab.
# Four pieces fix that, and every one of them is an existing kind.
DOOR_H = 3.0  # m — a door for a tower, clamped by add_opening to the wall height
GLASS_MAT = 'mat_glass'  # a door in a glazed ground floor is a glass door
SOLID_DOOR_MAT = 'pht_black_oak_veneer'  # ... in a solid wall it is dark timber
SPOTS = 6  # soffit downlights under the porte-cochere
SPOT_ROWS = 2
SPOT_DROP = 0.05  # m below the soffit plate
SPOT_W = 60.0  # W each — a downlight, not a desk lamp
SPOT_COL = '#ffe9c4'  # the warm lamp colour light_lamps_env already uses
SPOT_NEAR, SPOT_FAR = 0.32, 0.68  # rows at these fractions of the canopy depth:
# add_canopy stands its columns at depth - 0.35
PLANTER = 'polyhaven_arch|potted_plant_02_2k'  # a real life-size PBR plant, 0.70 x 0.84 m
PLANTER_CLEAR = 1.2  # m clear of the door leaf, either side
PLANTER_OUT = 1.2  # m outside the facade, under the canopy
AXIS_HALF = 2.0  # entrance_rules AXIS_CLEAR_HALF/design_rules AXIS_HALF_W: nothing
# of ours may stand inside the 4 m strip in front of the door
MAT_W, MAT_D = 2.4, 1.2  # m — the threshold mat
MAT_OUT = 1.3  # m outside the facade (its far edge is clear of the door swing)
MAT_MAT = 'acg_Carpet003'
ARRIVAL_KEY = 'entrance_arrival'  # meta mark, so a second call re-uses the three of them


# ── the sibling families, fetched at CALL time (alphabetical load order) ─────
def _mod(name):
    return A.EXT_MODULES.get(name)


def _envelope():
    return _mod('envelope_rules')


# ── geometry of a facade ────────────────────────────────────────────────────
def _centres(env) -> tuple:
    return ((env['xmin'] + env['xmax']) / 2.0, (env['zmin'] + env['zmax']) / 2.0)


def _pt(env, side, out: float, off: float = 0.0) -> tuple:
    """(x, z) `out` metres outside the `side` facade and `off` metres along it."""
    cx, cz = _centres(env)
    if side == 'south':
        return cx + off, env['zmax'] + out
    if side == 'north':
        return cx + off, env['zmin'] - out
    if side == 'east':
        return env['xmax'] + out, cz + off
    return env['xmin'] - out, cz + off


def _dirs(side) -> tuple:
    """((out_x, out_z), (along_x, along_z)) unit vectors of a facade in plan."""
    if side == 'south':
        return (0.0, 1.0), (1.0, 0.0)
    if side == 'north':
        return (0.0, -1.0), (1.0, 0.0)
    if side == 'east':
        return (1.0, 0.0), (0.0, 1.0)
    return (-1.0, 0.0), (0.0, 1.0)


def _glass_host(wall) -> bool:
    """Is the entrance wall a glazed ground floor? add_curtain_wall KEEPS the wall
    that holds a door and turns it mat_glass, so a glass wall and a curtain_wall
    record mean the same thing to the door hung in it."""
    return (wall or {}).get('kind') == 'curtain_wall' or str((wall or {}).get('mat') or '') == GLASS_MAT


def _snap(env, side, out: float, off: float, axis_off: float = 0.0, min_across: float = 0.0) -> tuple:
    """(cell, x, z) of the 1 m grid cell nearest `out` metres outside the facade
    and `off` along it. The grid is 1 m, so the point can slide up to 0.5 m: when
    it has to stay OUTSIDE the entrance axis strip (a planter) it is pushed a cell
    further along until it does. The cell CENTRE comes back, so the caller
    measures the place the record is actually drawn."""
    _, (ax, az) = _dirs(side)
    bx, bz = _pt(env, side, out, axis_off)
    step = 1.0 if off >= axis_off else -1.0
    cell = cx = cz = None
    for _ in range(6):
        x, z = _pt(env, side, out, off)
        cell = A.cell_of(x, z)
        cx, cz = A.cell_centre(*A.parse_cell(cell))
        if abs((cx - bx) * ax + (cz - bz) * az) >= min_across - 1e-6:
            break
        off += step
    return cell, cx, cz


def _spans(env, side) -> tuple:
    """(across_lo, across_hi, across_centre, depth_room) of the plate for `side`."""
    cx, cz = _centres(env)
    if side in ('north', 'south'):
        return env['xmin'], env['xmax'], cx, env['zmax'] - env['zmin']
    return env['zmin'], env['zmax'], cz, env['xmax'] - env['xmin']


def _rect(env, side, across_c: float, w: float, dd: float) -> tuple:
    """(xmin, zmin, xmax, zmax) of a lobby `w` across by `dd` deep behind `side`."""
    a0, a1 = across_c - w / 2.0, across_c + w / 2.0
    if side == 'south':
        return (a0, env['zmax'] - dd, a1, env['zmax'])
    if side == 'north':
        return (a0, env['zmin'], a1, env['zmin'] + dd)
    if side == 'east':
        return (env['xmax'] - dd, a0, env['xmax'], a1)
    return (env['xmin'], a0, env['xmin'] + dd, a1)


def _proj(rect, side) -> tuple:
    """(across_lo, across_hi, depth_from_facade_lo, depth_hi) of a world rect."""
    xa, za, xb, zb = rect
    if side in ('north', 'south'):
        across = (xa, xb)
        deep = (za, zb)
    else:
        across = (za, zb)
        deep = (xa, xb)
    return across, deep


def _depth_of(env, side, rect) -> tuple:
    """(near, far) distance of a rect from the `side` facade, measured inward."""
    _, deep = _proj(rect, side)
    if side == 'south':
        vals = (env['zmax'] - deep[1], env['zmax'] - deep[0])
    elif side == 'north':
        vals = (deep[0] - env['zmin'], deep[1] - env['zmin'])
    elif side == 'east':
        vals = (env['xmax'] - deep[1], env['xmax'] - deep[0])
    else:
        vals = (deep[0] - env['xmin'], deep[1] - env['xmin'])
    return (min(vals), max(vals))


def _at_on(wall, tx: float, tz: float) -> float:
    """`at` (metres from a wall's -X end) of the world point (tx, tz) on it."""
    L = _num(wall['p'].get('len'), 4.0)
    ry = _num(wall.get('ry'), 0.0)
    lx = (tx - wall['x']) * math.cos(ry) + (wall['z'] - tz) * math.sin(ry)
    return max(0.3, min(max(0.3, L - 0.3), lx + L / 2.0))


def _free_bands(lo: float, hi: float, blocked) -> list:
    bands = [(lo, hi)]
    for b0, b1 in blocked:
        nxt = []
        for s0, s1 in bands:
            if b1 <= s0 or b0 >= s1:
                nxt.append((s0, s1))
                continue
            if b0 > s0:
                nxt.append((s0, b0))
            if b1 < s1:
                nxt.append((b1, s1))
        bands = nxt
    return [b for b in bands if b[1] - b[0] > 0.1]


def _plan_lobby(env, side, cores, want_w: float, want_d: float) -> tuple:
    """(width, depth, across_centre) of the deepest lobby that clears every core,
    as close to the facade centre as it can be, or None if nothing fits."""
    a_lo, a_hi, a_c, _plate = _spans(env, side)
    lo, hi = a_lo + PLATE_MARGIN_M / 2.0, a_hi - PLATE_MARGIN_M / 2.0
    fallback = None
    # the full 1.8 m of landing first; then, rather than refuse, a lobby that only
    # keeps off the core itself — its back is open onto the landing anyway
    for clear in (CORE_CLEAR_M, 0.3):
        dd = want_d
        while dd >= MIN_LOBBY_M - 1e-6:
            blocked = []
            for cr in cores:
                c_across, _ = _proj(cr, side)
                near, far = _depth_of(env, side, cr)
                if far < 0 or near > dd:  # this core is not behind the lobby
                    continue
                blocked.append((c_across[0] - clear, c_across[1] + clear))
            bands = _free_bands(lo, hi, blocked)
            fits = [b for b in bands if b[1] - b[0] >= want_w - 1e-6]
            if fits:
                centres = [max(b[0] + want_w / 2.0, min(b[1] - want_w / 2.0, a_c)) for b in fits]
                return want_w, dd, min(centres, key=lambda v: abs(v - a_c))
            if fallback is None and bands:
                wide = max(bands, key=lambda b: b[1] - b[0])
                if wide[1] - wide[0] >= MIN_LOBBY_M:
                    fallback = (min(want_w, wide[1] - wide[0]), dd, (wide[0] + wide[1]) / 2.0)
            dd -= 1.0
        if fallback is not None:
            return fallback
    return fallback


def _core_gap(rect, wall_side: str, cores) -> float:
    """Metres of floor between the lobby's `wall_side` edge and the nearest core
    rect beyond it (inf when no core lies that way)."""
    xa, za, xb, zb = rect
    best = float('inf')
    for c0, c1, c2, c3 in cores:
        if wall_side in ('north', 'south'):
            if c2 <= xa or c0 >= xb:  # not in line with the lobby
                continue
            gap = (za - c3) if wall_side == 'north' else (c1 - zb)
        else:
            if c3 <= za or c1 >= zb:
                continue
            gap = (xa - c2) if wall_side == 'west' else (c0 - xb)
        if gap < -0.5:  # the core lies the OTHER way, not beyond this edge
            continue
        best = min(best, gap)
    return best


def _cells(rect) -> tuple:
    """The inclusive cell block that spans exactly this rect."""
    xa, za, xb, zb = rect
    return A.cell_of(xa + 0.5, za + 0.5), A.cell_of(xb - 0.5, zb - 0.5)


def _storey_of(d, o) -> int:
    try:
        return int(round((_num(o.get('y'), 0.0)) / (getattr(d, 'storey_h', 3.0) or 3.0)))
    except Exception:  # noqa: BLE001 — never block a build
        return 0


# ── what is already there ───────────────────────────────────────────────────
def _core_rects(d: Drawing, group: str, env) -> list:
    """Every plan rect on storey 0 the lobby must stay clear of."""
    ER = _envelope()
    out = []
    core = ((getattr(d, 'ext', {}) or {}).get('core') or {}).get(group) or {}
    land = core.get('landing')
    if isinstance(land, (list, tuple)) and len(land) == 4:
        out.append(tuple(float(_num(v, 0.0)) for v in land))
    for key in ('lifts', 'stair'):
        for oid in core.get(key) or []:
            o = d.find(str(oid))
            if o is not None and ER is not None:
                out.append(tuple(ER.bbox_of(o)))
    if out:
        return out
    CR = _mod('circulation_rules')
    kinds = tuple(getattr(CR, 'CORE_KINDS', ()) or ('stair_straight', 'stair_u', 'elevator_shaft'))
    for o in d.objs:
        if o.get('kind') not in kinds or o.get('hidden'):
            continue
        if ER is None:
            continue
        b = tuple(ER.bbox_of(o))
        if (
            b[0] >= env['xmin'] - 1.0
            and b[2] <= env['xmax'] + 1.0
            and b[1] >= env['zmin'] - 1.0
            and b[3] <= env['zmax'] + 1.0
        ):
            out.append(b)
    return out


def _entrance_door(d: Drawing, group: str, side: str, ax) -> tuple:
    """(record, why) of an exterior storey-0 door already on `side` near the axis."""
    DR = _mod('design_rules')
    door_kinds = tuple(getattr(DR, 'DOOR_KINDS', ()) or ('door', 'double_door'))
    wall, err = A.wall_on_side(d, group, side, 0, ('wall', 'partition', 'curtain_wall'))
    wid = wall['id'] if wall is not None and not err else ''
    for o in d.objs:
        if o.get('kind') not in door_kinds or o.get('hidden'):
            continue
        if _storey_of(d, o) != 0:
            continue
        host = str(((o.get('meta') or {}).get('host')) or '')
        if wid and host and host != wid:
            continue
        if not wid and o.get('grp') != group:
            continue
        off = abs(o['x'] - ax[0]) if side in ('north', 'south') else abs(o['z'] - ax[1])
        if off <= DOOR_REUSE_M:
            return o, (f're-used the existing {o.get("kind")} {o["id"]} on the {side} face ({off:.1f} m off the axis)')
    return None, ''


def _canopy_over(d: Drawing, ax) -> str:
    """The id of a canopy already standing over this entrance axis, or ''."""
    ER = _envelope()
    if ER is None:
        return ''
    for o in d.objs:
        if o.get('kind') != 'canopy' or o.get('hidden'):
            continue
        b = ER.bbox_of(o)
        if b[0] - 0.5 <= ax[0] <= b[2] + 0.5 and b[1] - 0.5 <= ax[1] <= b[3] + 0.5:
            return o['id']
    return ''


def _wall_material(d: Drawing, group: str) -> str:
    for o in d.select(group):
        if o.get('kind') == 'wall' and o.get('mat'):
            return str(o['mat'])
    return 'mat_concrete'


def _foreign_group(d: Drawing, group: str, pts) -> bool:
    """True if any of `pts` falls inside another group's envelope."""
    ER = _envelope()
    if ER is None:
        return False
    try:
        envs = ER.envelopes(d)
    except Exception:  # noqa: BLE001 — never block a build
        return False
    for g, e in (envs or {}).items():
        if g == group:
            continue
        for x, z in pts:
            if e['xmin'] - 1.0 <= x <= e['xmax'] + 1.0 and e['zmin'] - 1.0 <= z <= e['zmax'] + 1.0:
                return True
    return False


def _outdoors(d: Drawing, x: float, z: float) -> bool:
    """True if (x, z) falls inside NO envelope — exactly the test envelope_rules
    uses to call an interior record an orphan."""
    ER = _envelope()
    if ER is None:
        return False
    try:
        return ER.group_at(d, x, z, ER.envelopes(d)) is None
    except Exception:  # noqa: BLE001 — never block a build
        return False


# ── the presence of the arrival ─────────────────────────────────────────────
def _presence(d: Drawing, group, env, side, shifted: float, can, door_w: float) -> str:
    """Soffit downlights, flanking planters and a threshold mat under the canopy.

    Each piece is SKIPPED, never refused: the lamp budget is 32 for a whole
    drawing and the asset packs can be missing, and an entrance is not worth
    losing over a downlight. Everything stays outside the 4 m axis strip in front
    of the door, so entrance_rules keeps its silence."""
    if can is None:
        return 'no canopy to hang them from'
    cw = _num((can.get('p') or {}).get('w'), 12.0)
    cd = _num((can.get('p') or {}).get('d'), 5.0)
    soffit = _num(can.get('y'), 4.2)
    notes, skipped = [], []

    # (a) downlights — two rows, inside the plate, clear of the columns
    # add_canopy stands its columns at depth - 0.35, so SPOT_FAR keeps off them.
    # WHOLE-METRE offsets: place_light works on the 1 m cell grid, so a fractional
    # spacing snaps unevenly (9.5 / 13.5 / 16.5 under a 12 m plate). A whole-metre
    # step keeps the row even whichever way the axis falls in its cell.
    per = max(1, SPOTS // max(1, SPOT_ROWS))
    step = max(1.0, round(max(2.0, cw - 4.0) / max(1, per - 1)))
    across = [(i - (per - 1) / 2.0) * step for i in range(per)]
    rows = [SPOT_NEAR * cd, SPOT_FAR * cd]
    lit = []
    for out in rows[:SPOT_ROWS]:
        for u in across:
            cell, _cx, _cz = _snap(env, side, out, shifted + u, shifted)
            r = A.call_tool(
                d,
                'place_light',
                dict(
                    kind='spot', cell=cell, storey=0, watts=SPOT_W, colour=SPOT_COL, height=round(soffit - SPOT_DROP, 3)
                ),
            )
            if str(r).startswith('refused'):
                skipped.append('downlights (' + str(r)[9:60].strip() + ')')
                break
            lit.append(r.split()[2] if len(r.split()) > 2 else '')
        else:
            continue
        break
    if lit:
        notes.append(
            f'{len(lit)} spot downlights {SPOT_W:g} W at {soffit - SPOT_DROP:.2f} m, {SPOT_ROWS} rows under the soffit'
        )

    # (b) the flanking planters — clear of the door leaf AND of the axis strip
    pots = []
    for u in (-(door_w / 2.0 + PLANTER_CLEAR), door_w / 2.0 + PLANTER_CLEAR):
        cell, _cx, _cz = _snap(env, side, PLANTER_OUT, shifted + u, shifted, min_across=AXIS_HALF + 0.2)
        r = A.call_tool(d, 'place_asset', dict(query_or_id=PLANTER, cell=cell, storey=0, name='entrance planter'))
        if str(r).startswith('refused'):
            skipped.append('planters (' + str(r)[9:60].strip() + ')')
            break
        pots.append(cell)
    if pots:
        notes.append(
            f'{len(pots)} potted plants either side of the door ({"/".join(pots)}), '
            f'outside the {2 * AXIS_HALF:g} m axis strip'
        )

    # (c) the threshold mat — a rug on the axis, its far edge clear of the door
    out = MAT_OUT
    for _ in range(3):
        cell, cx, cz = _snap(env, side, out, shifted, shifted)
        bx, bz = _pt(env, side, 0.0, shifted)
        (ox, oz), _al = _dirs(side)
        if (cx - bx) * ox + (cz - bz) * oz >= MAT_D / 2.0 + 0.35:
            break
        out += 1.0
    if _outdoors(d, cx, cz):
        # A rug is an INTERIOR kind to envelope_rules: any interior record whose
        # centre falls outside every envelope is an orphan and reads as a room
        # standing outside the building (envelope_outside, sev error) whatever
        # group it carries. The mat can only go outdoors once some kind is
        # exterior-legal, and this family adds no kinds — so it is skipped, not
        # smuggled in as an error the operator has to clear.
        skipped.append('threshold mat (a rug outside the facade is envelope_outside)')
    else:
        n_before = len(d.objs)
        r = A.call_tool(
            d,
            'add_object',
            dict(
                kind='rug',
                cell=cell,
                storey=0,
                params={'w': MAT_W, 'd': MAT_D},
                rotation_deg=0 if side in ('north', 'south') else 90,
                material=MAT_MAT,
                name='threshold mat',
            ),
        )
        if str(r).startswith('refused'):
            skipped.append('threshold mat (' + str(r)[9:60].strip() + ')')
        else:
            # add_object makes the NAME the group, and a one-fixture group of its
            # own is read as a room; the mat belongs to the building.
            for o in d.objs[n_before:]:
                o['grp'] = group
            notes.append(f'a {MAT_W:g} x {MAT_D:g} m threshold mat in {MAT_MAT} on {cell}')
    return ('; '.join(notes) or 'nothing could be placed') + (f' — skipped: {", ".join(skipped)}' if skipped else '')


# ── undo ────────────────────────────────────────────────────────────────────
def _snapshot(d: Drawing) -> tuple:
    return (copy.deepcopy(d.objs), copy.deepcopy(getattr(d, 'ext', {}) or {}), list(getattr(d, 'selected', []) or []))


def _restore(d: Drawing, snap: tuple) -> None:
    objs, ext, sel = snap
    d.objs[:] = copy.deepcopy(objs)
    try:
        d.ext.clear()
        d.ext.update(copy.deepcopy(ext))
    except AttributeError as _exc:  # noqa: BLE001 — never block an undo
        _zyg_log.debug('drawing has no ext dict to restore: %s', _exc)
    d.selected = list(sel)


# ── the tool ────────────────────────────────────────────────────────────────
def t_build_entrance(
    d: Drawing,
    a,
    group='',
    side='south',
    style='luxury',
    door_width=2.8,
    canopy_width=12.0,
    canopy_depth=5.0,
    canopy_height=4.2,
    lobby_w=10.0,
    lobby_d=7.0,
    drive=True,
    trees=True,
    name='',
):
    ER = _envelope()
    if ER is None:
        return 'refused: envelope_rules is not loaded — build_entrance needs it to find the facade'
    group = str(group or '').strip()
    if not group:
        return 'refused: pass group — the building name draw_box printed'
    side = str(side or 'south').strip().lower()
    if side not in SIDES:
        return f'refused: side must be one of {", ".join(SIDES)}'
    style = str(style or 'luxury').strip().lower()
    if style not in STYLES:
        style = 'luxury'
    try:
        env = ER.group_envelope(d, group)
    except Exception:  # noqa: BLE001 — a bad group must refuse, not raise
        env = None
    if not env:
        groups = sorted({str(o.get('grp')) for o in d.objs if o.get('grp')})
        return f'refused: no building called "{group}" — pass the group draw_box returned' + (
            f' ({", ".join(groups[:6])})' if groups else ''
        )

    door_w = max(1.2, min(6.0, _num(door_width, 2.8)))
    can_w = max(3.0, _num(canopy_width, 12.0))
    can_d = max(1.5, _num(canopy_depth, 5.0))
    can_h = max(2.6, min(12.0, _num(canopy_height, 4.2)))
    lob_name = str(name or 'Lobby').strip() or 'Lobby'

    # the lobby plan: centred on the door axis, clamped to the plate, shifted off the core
    a_lo, a_hi, a_c, plate_d = _spans(env, side)
    max_w = max(MIN_LOBBY_M, (a_hi - a_lo) - PLATE_MARGIN_M)
    lob_w = max(MIN_LOBBY_M, min(_num(lobby_w, 10.0), max_w))
    want_d = _num(lobby_d, 7.0)
    if style == 'luxury':
        want_d = max(want_d, LUX_LOBBY_D)
    lob_d = max(MIN_LOBBY_M, min(want_d, plate_d - 1.0))

    cores = _core_rects(d, group, env)
    plan = _plan_lobby(env, side, cores, lob_w, lob_d)
    if plan is None:
        return (
            f'refused: the core leaves no strip {MIN_LOBBY_M:g} m wide and {MIN_LOBBY_M:g} m deep behind the '
            f'{side} face of "{group}" for a lobby — put the entrance on another side, or move the core '
            f'(add_core(group, position=...)) off this one'
        )
    lob_w, lob_d, axis_c = plan
    shifted = axis_c - a_c
    rect = _rect(env, side, axis_c, lob_w, lob_d)
    axis = _pt(env, side, 0.0, shifted)

    # a partition with the core right behind it seals the lift landing off from the
    # entrance (walk_entrance_core). Any interior side with a core within OPEN_GAP_M
    # is left OPEN so the lobby flows into the landing.
    # Only ONE side ever opens: the lobby rect that entrance_rules and
    # building_program measure is the bbox of the partitions, and two of the three
    # are the least that still spans it.
    interior = [s for s in SIDES if s != side]
    nearest = min(interior, key=lambda s: _core_gap(rect, s, cores))
    opened = [nearest] if _core_gap(rect, nearest, cores) < OPEN_GAP_M else []
    sides = [s for s in interior if s not in opened]

    snap = _snapshot(d)

    def step(tool, args):
        r = A.call_tool(d, tool, args)
        return r if str(r).startswith('refused') else ''

    # everything on the arrival stands on the LOBBY's axis, not the facade midpoint
    wall, werr = A.wall_on_side(d, group, side, 0, ('wall', 'partition', 'curtain_wall'))
    if werr:
        return werr
    at = _at_on(wall, *axis)

    # (1) the door — re-use one that is already there. A LUXURY door is named: glass
    # in a glazed ground floor (the leaf disappears into the shopfront the way a real
    # one does), dark oak in a solid wall. A standard entrance keeps the studio's own
    # default, so nothing about a plain front door changes.
    door_mat = ''
    if style == 'luxury':
        door_mat = GLASS_MAT if _glass_host(wall) else SOLID_DOOR_MAT
    have, reuse = _entrance_door(d, group, side, axis)
    if have is not None:
        door_id, door_note = have['id'], reuse
    else:
        err = step(
            'add_opening',
            dict(
                group=group,
                side=side,
                storey=0,
                kind='double_door',
                at=at,
                width=door_w,
                height=DOOR_H,
                material=door_mat,
            ),
        )
        if err:
            _restore(d, snap)
            return err
        doors, _ = _entrance_door(d, group, side, axis)
        door_id = doors['id'] if doors is not None else ''
        door_h = _num(((doors or {}).get('p') or {}).get('h'), DOOR_H)
        door_note = (
            f'double door {door_id} ({door_w:g} x {door_h:g} m) in the {side} wall'
            + (f', {door_mat}' if door_mat else '')
            + (' (the wall is glazed)' if door_mat == GLASS_MAT else '')
        )

    # (2) the canopy
    can_id = _canopy_over(d, axis)
    if can_id:
        can_note = f're-used the canopy {can_id} already over the axis'
    else:
        err = step(
            'add_canopy',
            dict(
                group=group,
                side=side,
                storey=0,
                at=at,
                width=can_w,
                depth=can_d,
                height=can_h,
                columns=4,
                material='mat_glass',
                column_material=_wall_material(d, group),
            ),
        )
        if err:
            _restore(d, snap)
            return err
        can_id = _canopy_over(d, axis)
        can_note = (
            f'glass porte-cochère {can_id or "(canopy)"} {can_w:g} x {can_d:g} m, soffit {can_h:g} m, on 4 columns'
        )

    # (2b) what makes it read as THE entrance: light under the soffit, something
    # green either side of the door, a mat to step onto. Luxury only — a plain
    # front door stays a plain front door — and a second call never doubles them.
    if style != 'luxury':
        arr_note = 'standard entrance: no downlights, planters or mat'
    elif any((o.get('meta') or {}).get(ARRIVAL_KEY) == group for o in d.objs):
        arr_note = 're-used the downlights, planters and mat already at this door'
    else:
        first = len(d.objs)
        arr_note = _presence(d, group, env, side, shifted, d.find(can_id) if can_id else None, door_w)
        # marked in meta, NOT regrouped: a group of its own is read as a room
        # standing outside the building (envelope_outside).
        for o in d.objs[first:]:
            o.setdefault('meta', {})[ARRIVAL_KEY] = group

    # (3) the lobby — a second call on the same side must not build it twice
    cf, ct = _cells(rect)
    if any(o.get('grp') == lob_name for o in d.objs):
        lob_note = (
            f're-used "{lob_name}", already behind this door '
            f'({"partitions " + "/".join(sides) if sides else "open plan"})'
        )
    else:
        room = dict(cell_from=cf, cell_to=ct, storey=0, name=lob_name, door_width=LOBBY_DOOR_W)
        if sides:
            room['sides'] = sides
        else:
            room['partitions'] = False  # the core is on every side: one open hall
        err = step('add_room', room)
        if err:
            _restore(d, snap)
            return err
        lob_note = (
            f'"{lob_name}" {lob_w:g} x {lob_d:g} m, cells {cf}..{ct} '
            f'({"partitions " + "/".join(sides) if sides else "open plan"}'
            + (f', {LOBBY_DOOR_W:g} m opening' if sides else '')
            + ')'
            + (f', shifted {abs(shifted):.1f} m off the core' if abs(shifted) > 0.05 else '')
            + (f'; {"/".join(opened)} side left OPEN so it flows into the lift landing' if opened else '')
        )

    # (4) the fit-out
    if any(o.get('grp') == f'{lob_name} fit-out' for o in d.objs):
        fit_note = 'already fitted out'
    else:
        err = step(
            'furnish_lobby', dict(cell_from=cf, cell_to=ct, storey=0, entrance_side=side, style=style, name=lob_name)
        )
        if err:
            _restore(d, snap)
            return err
        fit_note = f'{style} reception and seating, entrance side {side}'

    # (5) the drive and the lamps
    drive_note = 'no drive asked for'
    if drive and any(o.get('grp') == 'Approach Drive' for o in d.objs):
        drive_note = 're-used the Approach Drive and its lamp posts'
    elif drive:
        p0 = _pt(env, side, DRIVE_NEAR_M, shifted)
        p1 = _pt(env, side, DRIVE_FAR_M, shifted)
        err = step('add_road', dict(cells=[A.cell_of(*p0), A.cell_of(*p1)], width=DRIVE_W, name='Approach Drive'))
        if err:
            _restore(d, snap)
            return err
        lamp_off = max(6.0, can_w / 2.0 + 1.5, DRIVE_W / 2.0 + 1.5)
        lamp_out = max(can_d + 3.0, 8.0)
        lamp_h = max(LAMP_MIN_H, min(LAMP_MAX_H, can_h - LAMP_SOFFIT_GAP))
        lamp_pts = [_pt(env, side, o, shifted + u) for o in (lamp_out, lamp_out + 8.0) for u in (-lamp_off, lamp_off)]
        err = step(
            'add_street_furniture', dict(cells=[A.cell_of(*p) for p in lamp_pts], kind='lamp_post', height=lamp_h)
        )
        if err:
            _restore(d, snap)
            return err
        drive_note = (
            f'{DRIVE_W:g} m Approach Drive on the axis {DRIVE_NEAR_M:g}-{DRIVE_FAR_M:g} m out, '
            f'4 lamp posts {lamp_h:g} m tall at ±{lamp_off:g} m off the axis '
            f'({lamp_out:g} and {lamp_out + 8.0:g} m out, clear of the canopy)'
        )

    # (6) the trees
    tree_note = 'no trees asked for'
    if trees and any(str(o.get('grp') or '').startswith('tree line') for o in d.objs):
        tree_note = 're-used the tree lines already on the approach'
    elif trees:
        tree_off = max(TREE_OFF_MIN, max(6.0, can_w / 2.0 + 1.5, DRIVE_W / 2.0 + 1.5) + 3.0)
        lines, skipped = [], 0
        for u in (-tree_off, tree_off):
            pts = [_pt(env, side, TREE_NEAR_M, shifted + u), _pt(env, side, TREE_FAR_M, shifted + u)]
            if _foreign_group(d, group, pts):
                skipped += 1
                continue
            r = A.call_tool(
                d,
                'plant_tree_line',
                dict(cells=[A.cell_of(*p) for p in pts], spacing=8.0, kind='deciduous', height=10.0),
            )
            if str(r).startswith('refused'):
                skipped += 1  # a tree is never worth losing the entrance for
                continue
            lines.append(r)
        tree_note = (
            f'{len(lines)} deciduous tree line(s) at ±{tree_off:g} m off the axis, '
            f'{TREE_NEAR_M:g}-{TREE_FAR_M:g} m out'
            + (f'; {skipped} skipped (another building or a refusal there)' if skipped else '')
        )

    ext = getattr(d, 'ext', None)
    if isinstance(ext, dict):
        ext.setdefault('entrance', {})[group] = {
            'side': side,
            'door': door_id,
            'canopy': can_id,
            'lobby': [round(v, 3) for v in rect],
            'arrival': [o['id'] for o in d.objs if (o.get('meta') or {}).get(ARRIVAL_KEY) == group],
        }

    lines_out = [
        f'Entrance on the {side} face of "{group}":',
        f'  door    {door_note}',
        f'  canopy  {can_note}',
        f'  arrival {arr_note}',
        f'  lobby   {lob_note}',
        f'  fit-out {fit_note}',
        f'  drive   {drive_note}',
        f'  trees   {tree_note}',
    ]

    DR = _mod('design_rules')
    if DR is not None:
        try:
            found = DR.run_checks(d)
        except Exception as exc:  # noqa: BLE001 — a check must never sink the build
            found = []
            lines_out.append(f'entrance check: could not run ({exc.__class__.__name__})')
        else:
            ent = [
                f
                for f in found
                if any(str(f.get('code') or '').startswith(p) for p in ENTRANCE_CODES) and f.get('sev') == 'error'
            ]
            lines_out.append(
                f'entrance check: {len(ent)} errors'
                + ('' if not ent else ' — ' + '; '.join(f'{f["code"]}: {f["text"]}' for f in ent[:6]))
            )
    return '\n'.join(lines_out)


TOOLS = [
    (
        {
            'name': 'build_entrance',
            'description': (
                'The whole arrival of a building in ONE call: a double door in the named facade (glass '
                'in a glazed wall, oak in a solid one) under six soffit downlights, a planter either '
                'side and a threshold mat, a glass '
                'porte-cochère on four columns over it, a lobby behind it with a reception desk and '
                'seating, an approach drive on the axis, lamp posts clear of the canopy soffit and tree '
                'lines well off the axis. It re-uses a door that is already on that face instead of '
                'hanging a second one, keeps the lobby off the lift core (or leaves its back side open so '
                'the two flow together), never puts a partition on the facade line, and makes the lobby '
                'deep enough for the building programme. Use this for any "nice entrance", "grand '
                'entrance" or "entrance with a lobby" ask instead of add_opening + add_canopy + add_room '
                '+ furnish_lobby. If any step refuses, nothing is left behind.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'the building group draw_box printed'},
                    'side': {'type': 'string', 'enum': list(SIDES)},
                    'style': {'type': 'string', 'enum': list(STYLES)},
                    'door_width': {'type': 'number'},
                    'canopy_width': {'type': 'number'},
                    'canopy_depth': {'type': 'number'},
                    'canopy_height': {'type': 'number'},
                    'lobby_w': {'type': 'number'},
                    'lobby_d': {'type': 'number'},
                    'drive': {'type': 'boolean'},
                    'trees': {'type': 'boolean'},
                    'name': {'type': 'string', 'description': 'the lobby name (default "Lobby")'},
                },
                'required': ['group'],
            },
        },
        t_build_entrance,
    ),
]

# The brief budgets 220 chars, but the tower system prompt is the binding limit:
# with the sibling gate families loaded it already stands at 44 850 of its 45 000
# ceiling, so this paragraph has to pay for itself. It keeps the trigger words.
PROMPT = (
    'ENTRANCE: for any "nice entrance" ask call build_entrance(group, side) — door, canopy, lobby, drive, lamps, trees.'
)
if len(PROMPT) > 120:
    raise RuntimeError(f'entrance_kit PROMPT is {len(PROMPT)} chars — the budget is 120')

EXAMPLES = [
    {
        'ask': 'give the tower a nice entrance with a lobby on the south side',
        'calls': [{'tool': 'build_entrance', 'args': {'group': 'tower', 'side': 'south'}}],
    },
    # not 'core': system_prompt() lists the core examples first and cuts at 40,
    # so this one teaches help() and costs the tower prompt nothing.
    {
        'ask': 'a plain front door on the east of the warehouse, no canopy fuss and no drive',
        'calls': [
            {
                'tool': 'build_entrance',
                'args': {'group': 'warehouse', 'side': 'east', 'style': 'standard', 'drive': False, 'trees': False},
            }
        ],
    },
]
