# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""core_kit — the vertical core as ONE call (2026-09-16).

Every tower the assistant drew placed the stair and the lifts cell by cell and
guessed wrong. Live run 038ca075c052: add_stair(FH93, u, 1.2) made a
3.44 x 2.60 m plan and add_elevator then sank shafts at FF93 and FJ93, 0.62 m
inside BOTH of them; its foot opened onto shaft wall. stairs_vertical refuses
that now — but a refusal costs the model a turn and it guesses again.

add_core does the arithmetic once: a core strip along one facade, set back
SETBACK_M from it so the 0.2 m shaft wall never touches the curtain wall,
laid out as

    [lift 1][gap][lift 2][APPROACH_M][stair plan]

with the stair turned so its local -X — where a u stair's foot AND head both
land — faces the lifts, and the lift doors facing the lobby, so ONE landing of
LANDING_M in front of the doors serves the whole core. The sizes are not
invented here: the stair plan is computed exactly the way t_add_stair computes
it (stairs_vertical L334-353 + envelope_rules._plan_size), and the placing is
done by add_elevator / add_stair themselves, so every refusal those tools own
still applies. If one of them refuses, the drawing is put back the way it was.

This family owns NO kinds and NO checks: the records are the ones the two
existing tools make, and circulation_rules already measures them.
"""

from __future__ import annotations

import copy
import math
import re

from zyg_workflows import arch_assistant as A
from zyg_workflows.arch_assistant import Drawing, MATERIALS, _num  # noqa: F401  (MATERIALS: schema enum)
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


KINDS: dict = {}
OPENINGS: list = []
DESIGN_CHECKS: list = []

POSITIONS = ('north', 'south', 'east', 'west', 'centre')
SETBACK_M = 1.0  # m from the named facade to the nearest core face
SIDE_CLEAR_M = 0.6  # m from the strip's ends to the side facades
LIFT_GAP_M = 0.3  # m between two shafts
LANDING_M = 1.8  # m of floor in front of the lift doors (object_specs' lift spec)
APPROACH_M = 1.2  # m of floor at a stair's foot — stairs_vertical.APPROACH_M
MAX_LIFTS = 4
RETRIES = 4  # how often the layout may be widened by a cell before it gives up

# the facade a core faces is the one OPPOSITE the side it stands on: that is
# where the lobby is, so that is where the doors and the landing go.
OPPOSITE = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east', 'centre': 'south'}


# ── the sibling families, fetched at CALL time (alphabetical load order) ─────
def _stairs():
    return A.EXT_MODULES.get('stairs_vertical')


def _envelope():
    return A.EXT_MODULES.get('envelope_rules')


# ── cells <-> metres ─────────────────────────────────────────────────────────
# A.cell_of is the exact inverse of A.parse_cell + A.cell_centre at the
# drawing's current cell size (arch_assistant L345-356: centre = origin +
# (i + 0.5) * m, index = floor((v - origin) / m)). It is re-exported here so a
# core is never placed by hand arithmetic on column letters.
def cell_of(x: float, z: float) -> str:
    """The cell whose square contains the plan point (x, z)."""
    return A.cell_of(x, z)


def _idx(v: float) -> int:
    """The cell index of one coordinate. Columns and rows share one origin and
    one size, so the same number answers for x and for z."""
    return A.parse_cell(A.cell_of(v, v))[0]


def _centre(i: int) -> float:
    """The world coordinate of the centre of cell index `i` on either axis."""
    return A.cell_centre(i, i)[0]


# ── the stair plan, the way add_stair computes it ────────────────────────────
def stair_plan(d: Drawing, env: dict, kind: str, width: float, s1: int, x: float, z: float) -> tuple:
    """(rec_kind, p, L, W) of the LARGEST record add_stair will draw at (x, z).

    The flight that climbs onto a roof deck is taller than a typical storey
    (3.0 m against 2.7 on the 20-storey tower), so it has more steps and a
    longer plan — 3.44 x 2.60 m for a 1.2 m u stair, which is exactly the plan
    the lifts have to keep clear of."""
    S, E = _stairs(), _envelope()
    H = d.storey_h
    steps, rise = S._rise_for(H)
    rec_kind, p = S._stack_params(kind, steps, rise, width)
    storeys = int(env.get('storeys') or 0)
    base = _num(env.get('y0'), 0.0)
    p_top = dict(p)
    if s1 >= storeys:
        deck_y = A.surface_top(d, x, z)
        last_h = deck_y - (base + (s1 - 1) * H)
        if last_h > H + 0.02:
            ln, lr = S._rise_for(last_h)
            if lr <= S.RISE_LIMIT:
                p_top['steps'], p_top['rise'] = ln, round(lr, 9)
    p_big = p_top if _num(p_top.get('steps'), 0) > _num(p.get('steps'), 0) else p
    L, W = E._plan_size(S._probe(rec_kind, p_big, x, z, 0.0))
    return rec_kind, p_big, L, W


def _ceil_cells(m: float) -> int:
    return max(1, int(math.ceil(m - 1e-9)))


def _snapshot(d: Drawing) -> tuple:
    """Everything an inner tool may change. cut_slab_void REPLACES a slab with
    its pieces, so an undo that only drops new ids would leave the floor cut
    open — the whole record list and the ext registry are kept instead."""
    return copy.deepcopy(d.objs), copy.deepcopy(getattr(d, 'ext', {}) or {}), list(getattr(d, 'selected', []) or [])


def _restore(d: Drawing, snap: tuple) -> None:
    objs, ext, sel = snap
    d.objs[:] = copy.deepcopy(objs)
    try:
        d.ext.clear()
        d.ext.update(copy.deepcopy(ext))
    except AttributeError as _exc:  # noqa: BLE001 — never block an undo
        _zyg_log.debug('drawing has no ext dict to restore: %s', _exc)
    d.selected = list(sel)


def _new_ids(d: Drawing, before: set, kinds=None) -> list:
    return [o['id'] for o in d.objs if o['id'] not in before and (kinds is None or o.get('kind') in kinds)]


def _errors_for(d: Drawing, ids) -> tuple:
    """(count, families) — design-check ERRORS naming one of the core records,
    from circulation_rules and (when it exists) clash_rules."""
    pat = re.compile(r'\b(' + '|'.join(re.escape(i) for i in ids) + r')\b') if ids else None
    n, fams = 0, []
    for fam in ('circulation_rules', 'clash_rules'):
        mod = A.EXT_MODULES.get(fam)
        if mod is None:
            continue
        fams.append(fam)
        for fn in getattr(mod, 'DESIGN_CHECKS', []) or []:
            try:
                found = fn(d) or []
            except Exception as _exc:  # noqa: BLE001 — a check must never block a draw
                _zyg_log.debug('design check in %s failed: %s', fam, _exc)
                continue
            for f in found:
                if f.get('sev') == 'error' and pat and pat.search(str(f.get('text') or '')):
                    n += 1
    return n, fams


# ── the tool ─────────────────────────────────────────────────────────────────
def t_add_core(
    d: Drawing,
    a,
    group='',
    position='north',
    lifts=2,
    stair='u',
    stair_width=1.2,
    lift_w=1.8,
    lift_d=2.0,
    lobby_side='auto',
    name='core',
) -> str:
    S, E = _stairs(), _envelope()
    if S is None or E is None:
        return 'refused: add_core needs the stairs_vertical and envelope_rules families'
    g = str(group or '').strip()
    if not g:
        envs = E.envelopes(d)
        if len(envs) != 1:
            return (
                'refused: name the building the core belongs to (group=...) — draw_box prints it; '
                'this drawing has ' + (', '.join(f'"{k}"' for k in envs) if envs else 'none')
            )
        g = next(iter(envs))
    env = E.group_envelope(d, g)
    if env is None:
        return (
            f'refused: no building called "{g}" — draw the shell first '
            f'(draw_box(centre=..., width=..., depth=..., storeys=...)) and use the group name it prints'
        )
    pos = str(position or 'north').strip().lower()
    pos = {'centre': 'centre', 'center': 'centre', 'middle': 'centre'}.get(pos) or A.SIDE_WORDS.get(pos) or ''
    if pos not in POSITIONS:
        return 'refused: position must be ' + ', '.join(POSITIONS)
    n_lift = int(_num(lifts, 2))
    if not (1 <= n_lift <= MAX_LIFTS):
        return f'refused: lifts must be 1..{MAX_LIFTS}'
    k = str(stair or 'u').strip().lower()
    if k not in S.STAIR_KINDS:
        return 'refused: stair must be ' + ', '.join(S.STAIR_KINDS)
    sw = _num(stair_width, 1.2)
    lw, ld = _num(lift_w, 1.8), _num(lift_d, 2.0)
    storeys = int(env.get('storeys') or 0)
    if storeys < 2:
        return (
            f'refused: "{g}" is {storeys} storey — a core climbs between floors; draw_box(..., storeys=N) '
            f'with N >= 2 first'
        )
    side = str(lobby_side or 'auto').strip().lower()
    door_side = OPPOSITE[pos] if side in ('', 'auto') else (A.SIDE_WORDS.get(side) or '')
    if door_side not in ('north', 'south', 'east', 'west'):
        return 'refused: lobby_side must be auto, north, south, east or west'

    # ── the two axes of the strip ────────────────────────────────────────────
    # u runs ALONG the facade the core stands on, v across the plate. A shaft is
    # never turned (add_elevator draws it at ry = 0), so its extent along u is
    # its w on an east-west strip and its depth on a north-south one.
    if pos in ('north', 'south', 'centre'):
        u_is_x = True
        umin, umax, vmin, vmax = env['xmin'], env['xmax'], env['zmin'], env['zmax']
        lift_along, lift_across = lw, ld
        deg = 0.0  # stair local +X = world +X: its foot faces west
    else:
        u_is_x = False
        umin, umax, vmin, vmax = env['zmin'], env['zmax'], env['xmin'], env['xmax']
        lift_along, lift_across = ld, lw
        deg = 270.0  # stair local +X = world +Z: its foot faces north
    umid, vmid = (umin + umax) / 2, (vmin + vmax) / 2
    inward = 1.0 if pos in ('north', 'west') else -1.0  # from the named facade into the plate
    facade = vmin if inward > 0 else vmax

    def pt(u, v):
        return (u, v) if u_is_x else (v, u)

    # ── the layout, solved on CELL CENTRES (the tools only take cells) ───────
    L, W = 3.44, 2.60
    lay = None
    extra = 0
    for _ in range(RETRIES):
        px, pz = pt(umid, vmid)
        _rk, _p, L, W = stair_plan(d, env, k, sw, storeys, px, pz)
        across = max(lift_across, W)
        # v: set back from the facade so the shaft wall never touches the glass
        vi = _idx(vmid if pos == 'centre' else facade + inward * (SETBACK_M + across / 2))
        if pos != 'centre':
            for _ in range(4):
                if inward * ((_centre(vi) - inward * across / 2) - facade) >= SETBACK_M - 1e-6:
                    break
                vi += int(inward)
        vc = _centre(vi)
        # u: [lift 1][gap][lift 2][approach][stair], whole cells, gaps rounded UP
        step = _ceil_cells(lift_along + LIFT_GAP_M)
        off = _ceil_cells(lift_along / 2 + APPROACH_M + L / 2) + extra
        span = (n_lift - 1) * step + off
        total = lift_along / 2 + span + L / 2
        ui = _idx(umid - total / 2 + lift_along / 2)
        lift_u = [_centre(ui + i * step) for i in range(n_lift)]
        stair_u = _centre(ui + span)
        # does the whole thing stand on the plate?
        need_u = total + 2 * SIDE_CLEAR_M
        need_v = SETBACK_M + across + LANDING_M
        if (
            lift_u[0] - lift_along / 2 < umin + SIDE_CLEAR_M - 1e-6
            or stair_u + L / 2 > umax - SIDE_CLEAR_M + 1e-6
            or (umax - umin) + 1e-6 < need_u
            or (vmax - vmin) + 1e-6 < need_v
        ):
            plate = f'{need_u:.1f} x {need_v:.1f} m' if u_is_x else f'{need_v:.1f} x {need_u:.1f} m'
            have = f'{env["xmax"] - env["xmin"]:.1f} x {env["zmax"] - env["zmin"]:.1f} m'
            return (
                f'refused: a {k} core with {n_lift} lift(s) on the {pos} side needs a plate of at least '
                f'{plate} (the strip is {total:.2f} m long: {n_lift} x {lift_along:g} m of shaft, '
                f'{APPROACH_M:g} m of approach and a {L:.2f} x {W:.2f} m stair plan, {SIDE_CLEAR_M:g} m '
                f'clear of the side facades); "{g}" is {have} — make the building bigger, '
                f'or place add_stair + add_elevator by hand'
            )
        # nothing may stand in anything else's plan or at the stair's foot
        sx, sz = pt(stair_u, vc)
        probe = S._probe(_rk, _p, sx, sz, math.radians(deg))
        sbb = E.bbox_of(probe)
        zones = S.approach_bboxes(probe)
        shafts = []
        for u in lift_u:
            lx, lz = pt(u, vc)
            shafts.append(
                (
                    lx,
                    lz,
                    E.bbox_of(
                        S._probe(
                            'elevator_shaft', {'w': round(lw, 3), 'd': round(ld, 3), 'h': 1.0, 't': 0.2}, lx, lz, 0.0
                        )
                    ),
                )
            )
        bad = any(S.plan_clash(sbb, b) or any(S.plan_clash(zb, b) for zb in zones) for _x, _z, b in shafts)
        bad = bad or any(
            S.plan_clash(shafts[i][2], shafts[j][2]) for i in range(len(shafts)) for j in range(i + 1, len(shafts))
        )
        if not bad:
            lay = (sx, sz, shafts, vc, stair_u, lift_u, across, L, W)
            break
        extra += 1
    if lay is None:
        return (
            f'refused: a {L:.2f} x {W:.2f} m {k} stair and {n_lift} x {lw:g} x {ld:g} m shafts could not be '
            f'laid out clash-free on the {pos} side of "{g}" — try lifts=1, a narrower stair_width, '
            f'or position="centre"'
        )
    sx, sz, shafts, vc, stair_u, lift_u, across, L, W = lay

    # ── place them: the two tools own every other refusal there is ───────────
    snap = _snapshot(d)
    tried = [cell_of(x, z) for x, z, _b in shafts] + [cell_of(sx, sz)]
    lift_ids, lift_cells = [], []
    for i, (lx, lz, _b) in enumerate(shafts):
        cell = cell_of(lx, lz)
        was = {o['id'] for o in d.objs}
        r = str(
            A.call_tool(
                d,
                'add_elevator',
                dict(
                    cell=cell,
                    from_storey=0,
                    to_storey=storeys,
                    w=lw,
                    depth=ld,
                    door_side=door_side,
                    name=f'{name} lift {i + 1}',
                ),
            )
        )
        if r.startswith('refused:'):
            _restore(d, snap)
            return (
                f'refused: lift {i + 1} of the core could not be placed at {cell} (cells tried: '
                f'{", ".join(tried)}) — {r[len("refused:") :].strip()}'
            )
        got = _new_ids(d, was, ('elevator_shaft',))
        lift_ids += got
        lift_cells.append(cell)
    stair_cell = cell_of(sx, sz)
    was = {o['id'] for o in d.objs}
    r = str(
        A.call_tool(
            d,
            'add_stair',
            dict(
                cell=stair_cell,
                from_storey=0,
                to_storey=storeys,
                kind=k,
                width=sw,
                direction_deg=deg,
                name=f'{name} stair',
            ),
        )
    )
    if r.startswith('refused:'):
        _restore(d, snap)
        return (
            f'refused: the stair of the core could not be placed at {stair_cell} (cells tried: '
            f'{", ".join(tried)}) — {r[len("refused:") :].strip()}'
        )
    stair_ids = _new_ids(d, was, tuple(S.CORE_STAIR_KINDS))

    # ── the landing both of them share ───────────────────────────────────────
    u0, u1 = lift_u[0] - lift_along / 2, stair_u - L / 2
    v0, v1 = (
        min(vc - across / 2, vc + inward * (across / 2 + LANDING_M)),
        max(vc - across / 2, vc + inward * (across / 2 + LANDING_M)),
    )
    c0, c1 = pt(u0, v0), pt(u1, v1)
    rect = [
        round(min(c0[0], c1[0]), 4),
        round(min(c0[1], c1[1]), 4),
        round(max(c0[0], c1[0]), 4),
        round(max(c0[1], c1[1]), 4),
    ]
    land = f'{cell_of(rect[0] + 0.01, rect[1] + 0.01)}..{cell_of(rect[2] - 0.01, rect[3] - 0.01)}'

    cores = d.ext.setdefault('core', {})
    cores[g] = {
        'lifts': lift_ids,
        'stair': stair_ids,
        'landing': rect,
        'position': pos,
        'lobby_side': door_side,
        'name': str(name or 'core'),
        'storeys': storeys,
        'stair_cell': stair_cell,
        'lift_cells': lift_cells,
        'plan': [round(L, 3), round(W, 3)],
    }
    d.selected = lift_ids + stair_ids

    n_err, fams = _errors_for(d, lift_ids + stair_ids)
    lift_txt = ' and '.join(f'{i} ({c}, doors {door_side})' for i, c in zip(lift_ids, lift_cells))
    stair_txt = f'{stair_ids[0]}..{stair_ids[-1]}' if len(stair_ids) > 1 else (stair_ids[0] if stair_ids else '?')
    where = 'in the centre of' if pos == 'centre' else f'on the {pos} side of'
    return (
        f'core "{name}" {where} "{g}": lifts {lift_txt}, {k.upper()}-stair {stair_txt} at '
        f'{stair_cell} ({L:.2f} x {W:.2f} m, turned {deg:g}°) with its foot on the shared landing '
        f'{land} ({LANDING_M:g} m), head house on the deck; storeys 0-{storeys}. '
        f'Lobby side: {door_side}. design_check: {n_err} error(s) on the core records '
        f'({", ".join(fams) if fams else "no circulation family loaded"})'
    )


TOOLS = [
    (
        {
            'name': 'add_core',
            'description': (
                'The whole vertical core of a building in ONE call: the lifts, the stair and the landing '
                'they share, from storey 0 to the roof deck, clash-free. It sets the core strip back 1 m '
                'from the facade named by `position` (north/south/east/west/centre), lays the shafts out '
                'along it with a 0.3 m gap, leaves the 1.2 m a stair needs at its foot, turns the stair '
                'so that foot faces the lifts, and points the lift doors at the lobby (the opposite side) '
                'with 1.8 m of landing in front of them. add_stair and add_elevator do the drawing, so the '
                'head house, the shaft overrun, the doors on every storey and the floor openings all come '
                'with it. Use this instead of add_stair + add_elevator on any building of 3 storeys or '
                'more; if the plate is too small it refuses with the smallest plate that fits, and if an '
                'inner call refuses nothing is left behind.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': 'the building group draw_box printed'},
                    'position': {'type': 'string', 'enum': list(POSITIONS)},
                    'lifts': {'type': 'integer'},
                    'stair': {'type': 'string', 'enum': ['u', 'straight', 'winder', 'spiral']},
                    'stair_width': {'type': 'number'},
                    'lift_w': {'type': 'number'},
                    'lift_d': {'type': 'number'},
                    'lobby_side': {'type': 'string', 'enum': ['auto', 'north', 'south', 'east', 'west']},
                    'name': {'type': 'string'},
                },
                'required': ['group'],
            },
        },
        t_add_core,
    ),
]

PROMPT = (
    'CORE: add_core(group, position) places the U-stair, the lifts and their landing clash-free in one '
    'call, storey 0 to the roof deck with head house and overrun. Use it, not add_stair + '
    'add_elevator, on 3+ storeys.'
)
if len(PROMPT) > 220:
    raise RuntimeError(f'core_kit PROMPT is {len(PROMPT)} chars — the budget is 220')

EXAMPLES = [
    {
        'ask': 'put the stair and two lifts of the 20-storey tower on the north side',
        'calls': [{'tool': 'add_core', 'args': {'group': 'tower', 'position': 'north', 'lifts': 2}}],
    },
    # not 'core': system_prompt() lists the core examples first and cuts at 40,
    # so this one teaches help() and costs the tower prompt nothing.
    {
        'ask': 'the office block needs a stair and a lift in the middle of the plan',
        'calls': [{'tool': 'add_core', 'args': {'group': 'office', 'position': 'centre', 'lifts': 1, 'stair': 'u'}}],
    },
]
