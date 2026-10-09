#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The buildability compiler.

Takes any voxel model and either emits a build the bot is *proven* able to
complete, or explains exactly which blocks it cannot and why.

Why this exists: the bot has canDig=false, so it can never undo a mistake.
Every other Minecraft builder (Baritone, Litematica printers, prismarine-builder)
solves reachability at run time by placing throwaway scaffolding and breaking it
afterwards.  We cannot.  Reachability therefore has to be proven *offline*,
before a single block is placed — which is what this module does.

    compiled, report = compile_schematic(blocks)

Stages
  1  LINT      — material exists, is giveable, fits the inventory budget, sits in
                 the kit's cleared zone.  Catches the silent-corruption footgun
                 where bot.js _material falls back to MAT_PRIORITY and builds the
                 whole structure out of the wrong block while reporting success.
  2  SIMULATE  — replay bot.js's actual place loop against schem_model's exact
                 support/reach/movement rules, tracking the bot's real position.
                 Emits a proven build ORDER.  Self-trapping falls out of this for
                 free: wall yourself in and the reachable set collapses.
  3  SCAFFOLD  — for blocks the bot cannot reach, synthesise the cheapest
                 staircase that fixes it (0-1 BFS over standing cells, cost =
                 blocks added), then re-simulate to confirm.
  4  REPORT    — per-block verdicts, materials, and a certification flag.

The compiler is pure and dependency-free; it is also the only thing standing
between a user's design and a 40-minute stalled build.
"""

import time
from collections import deque

import schem_model as M


class Verdict:
    OK = 'ok'
    NOSUPPORT = 'nosupport'  # nothing solid to place against, ever
    UNREACHABLE = 'unreachable'  # supported, but the bot cannot get within reach
    BAD_MATERIAL = 'bad_material'
    OUT_OF_ZONE = 'out_of_zone'
    DUPLICATE = 'duplicate'
    BELOW_GROUND = 'below_ground'


def _key(b):
    return (b['x'], b['y'], b['z'])


def _norm(b):
    """Accept both the hub's block dicts and looser user input."""
    out = {
        'x': int(b['x']),
        'y': int(b['y']),
        'z': int(b['z']),
        'mat': str(b.get('mat') or b.get('name') or b.get('block') or ''),
        'kind': b.get('kind') or 'block',
    }
    state = b.get('state')
    if isinstance(state, dict) and state:
        out['state'] = {str(k): str(v) for k, v in state.items()}
    return out


# ── Stage 1: lint ───────────────────────────────────────────────────────
def lint(blocks):
    """Cheap, exact checks that need no simulation."""
    errors = []
    seen = {}
    for b in blocks:
        k = _key(b)
        mat = b['mat']
        if not M.is_known(mat):
            errors.append(
                {'pos': k, 'mat': mat, 'verdict': Verdict.BAD_MATERIAL, 'detail': f"'{mat}' is not a block in 1.20.4"}
            )
            continue
        if not M.is_giveable(mat):
            errors.append(
                {
                    'pos': k,
                    'mat': mat,
                    'verdict': Verdict.BAD_MATERIAL,
                    'detail': f"'{mat}' has no item form — /give cannot deliver it and "
                    f'bot.js _material would silently build this in stone_bricks',
                }
            )
        if b['y'] <= M.GROUND_Y:
            errors.append(
                {
                    'pos': k,
                    'mat': mat,
                    'verdict': Verdict.BELOW_GROUND,
                    'detail': f'y={b["y"]} is at or below the grass plane (y={M.GROUND_Y}); '
                    f'builds start at y={M.BASE_Y}',
                }
            )
        if k in seen:
            errors.append(
                {
                    'pos': k,
                    'mat': mat,
                    'verdict': Verdict.DUPLICATE,
                    'detail': f"duplicate cell — also defined as '{seen[k]}'",
                }
            )
        else:
            seen[k] = mat
    return errors


def material_budget(blocks):
    """Materials the kit must deliver, and whether they fit the bot's 36 slots.

    schematic_builder.js learned this the hard way: keepInventory=true means
    materials pile up run after run, fill the inventory, and the LAST /give calls
    are silently dropped — after which every block of that material fails to
    place.  kit.py clears first, but the budget still has to fit.
    """
    mats = {}
    for b in blocks:
        mats[b['mat']] = mats.get(b['mat'], 0) + 1
    slots = 0
    for mat, count in mats.items():
        give = min(1728, int(count * 1.4) + 16)
        stack = M.stack_size(mat) or 64
        slots += -(-give // stack)  # ceil
    return mats, slots


# ── Stage 2: simulate ───────────────────────────────────────────────────
def _reach_candidates(target, reachable):
    """Standing cells near enough to possibly reach `target`.

    Filtering by a cheap bounding box before the exact distance test keeps the
    simulation fast without changing its result: the reach envelope is capped at
    5 above / 6 below the target and ~4 horizontally.
    """
    tx, ty, tz = target
    out = []
    for c in reachable:
        if abs(c[0] - tx) <= 5 and abs(c[2] - tz) <= 5 and -7 <= c[1] - ty <= 4:
            out.append(c)
    # Prefer standing close and low — mirrors how the bot actually approaches and
    # keeps the recorded camera calm instead of teleporting around the build.
    out.sort(key=lambda c: (abs(c[1] - ty), abs(c[0] - tx) + abs(c[2] - tz)))
    return out


def simulate(blocks, world=None, bounds=None, start=None, order_hint=None):
    """Replay bot.js's place loop exactly.

    Returns (placed_order, unbuilt, world, bot_pos, passes).

    The bot's position is tracked for real — it ends up standing where it last
    placed from, which is what makes self-trapping observable.
    """
    if bounds is None:
        bounds = M.analysis_bounds(blocks)
    if world is None:
        world = M.ground_world(bounds)
    else:
        world = dict(world)

    bot = start or M.BOT_SPAWN
    remaining = list(order_hint if order_hint is not None else blocks)
    placed = []
    passes = 0

    reachable = M.reachable_cells(bot, world, bounds)
    progress = True
    while progress and remaining:
        progress = False
        passes += 1
        still = []
        for b in remaining:
            t = _key(b)
            if t in world:  # already solid (shouldn't happen, but bot.js tolerates it)
                placed.append(b)
                progress = True
                continue
            ref = M.find_ref(t, world)
            if ref is None:
                still.append(b)  # no support yet — a later block may provide it
                continue
            ref_pos, face, ref_name = ref
            stand = None
            for c in _reach_candidates(t, reachable):
                if M.can_place_from(c, t, ref_pos, face, ref_name):
                    stand = c
                    break
            if stand is None:
                still.append(b)
                continue

            world[t] = b['mat']
            placed.append(b)
            bot = stand
            progress = True
            # The world changed: new footing may have appeared, and the block just
            # placed may have severed a path. Recompute from where the bot stands.
            reachable = M.reachable_cells(bot, world, bounds)
        remaining = still

    return placed, remaining, world, bot, passes


def classify_unbuilt(unbuilt, world):
    """Separate 'nothing to place against' from 'cannot get there'."""
    out = []
    for b in unbuilt:
        t = _key(b)
        ref = M.find_ref(t, world)
        v = Verdict.UNREACHABLE if ref else Verdict.NOSUPPORT
        detail = (
            'supported, but no standing cell is both reachable and within 4.0 of the reference face'
            if ref
            else 'no solid neighbour to place against (below/±x/±z), even after every other block was placed'
        )
        out.append({'pos': t, 'mat': b['mat'], 'verdict': v, 'detail': detail})
    return out


# ── Stage 3: scaffold synthesis ─────────────────────────────────────────
def _scaffold_material(mats_in_use):
    for m in M.SCAFFOLD_MATERIALS:
        if M.is_giveable(m) and M.supports_placement(m):
            return m
    return 'cobblestone'


def synthesize_scaffold(target_block, world, bounds, bot, budget=48):
    """Cheapest set of added blocks that lets the bot place `target_block`.

    0-1 BFS over standing cells. Stepping to an already-walkable cell costs 0;
    creating footing costs 1 — and is only allowed if that footing is itself
    supported AND within reach of the cell the bot is standing on at that moment,
    i.e. the bot could really have placed it. That constraint is what makes the
    synthesised staircase honest rather than a wish: it is built the same way the
    bot would build it, one reachable step at a time.

    Returns a list of {x,y,z,mat,kind:'scaffold'} or None.
    """
    t = _key(target_block)
    ref = M.find_ref(t, world)
    if ref is None:
        return None  # support does not exist yet; a later pass may create it
    ref_pos, face, ref_name = ref
    mat = _scaffold_material(None)

    start = bot if M.is_standable(bot, world) else None
    if start is None:
        for k in range(0, M.MAX_DROP_DOWN + 2):
            c = (bot[0], bot[1] - k, bot[2])
            if M.is_standable(c, world):
                start = c
                break
    if start is None:
        return None

    def get(p, addset):
        # Avoid copying the (large) world dict per node — overlay the additions.
        return mat if p in addset else world.get(p)

    best = {start: 0}
    dq = deque([(0, start, ())])
    x0, x1, y0, y1, z0, z1 = bounds

    while dq:
        cost, cell, added = dq.popleft()
        if cost > best.get(cell, 1 << 30):
            continue
        if cost > budget:
            continue

        if M.can_place_from(cell, t, ref_pos, face, ref_name):
            return [{'x': a[0], 'y': a[1], 'z': a[2], 'mat': mat, 'kind': 'scaffold'} for a in added]

        addset = set(added)
        x, y, z = cell
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            for dy in (1, 0, -1, -2, -3, -4):
                nb = (x + dx, y + dy, z + dz)
                if not (x0 <= nb[0] <= x1 and y0 <= nb[1] <= y1 and z0 <= nb[2] <= z1):
                    continue
                if not M.is_passable(get(nb, addset)):
                    continue
                if not M.is_passable(get((nb[0], nb[1] + 1, nb[2]), addset)):
                    continue
                if dy == 1 and not M.is_passable(get((x, y + 2, z), addset)):
                    continue  # no headroom to jump

                foot = (nb[0], nb[1] - 1, nb[2])
                fname = get(foot, addset)
                if fname and M.supports_placement(fname):
                    ncost, nadded = cost, added  # already walkable
                else:
                    if not M.is_passable(fname):
                        continue
                    # Would the bot actually be able to place this step from here?
                    fref = None
                    for (rdx, rdy, rdz), rface in M.SUPPORT_CANDIDATES:
                        rp = (foot[0] + rdx, foot[1] + rdy, foot[2] + rdz)
                        rn = get(rp, addset)
                        if rn and M.supports_placement(rn):
                            fref = (rp, rface, rn)
                            break
                    if fref is None:
                        continue
                    if not M.can_place_from(cell, foot, *fref):
                        continue
                    ncost, nadded = cost + 1, added + (foot,)

                if ncost < best.get(nb, 1 << 30):
                    best[nb] = ncost
                    if ncost == cost:
                        dq.appendleft((ncost, nb, nadded))
                    else:
                        dq.append((ncost, nb, nadded))
    return None


def repair(unbuilt, world, bounds, bot, max_scaffold=120):
    """Rescue unreachable blocks with synthesised scaffolding — one round.

    Blocks whose support does not exist yet are skipped, not failed: the caller
    re-simulates and comes back, so a tall structure grows its scaffold as the
    structure itself rises.
    """
    scaffold = []
    added = set()
    for b in list(unbuilt):
        if len(scaffold) >= max_scaffold:
            break
        w = world if not added else {**world, **{a: _scaffold_material(None) for a in added}}
        add = synthesize_scaffold(b, w, bounds, bot)
        if not add:
            continue
        for a in add:
            k = _key(a)
            if k in added:
                continue
            added.add(k)
            scaffold.append(a)
    return scaffold


# ── Stage 4: compile ────────────────────────────────────────────────────
def compile_schematic(raw_blocks, auto_scaffold=True, want_report=True):
    """Compile a voxel model into a proven-buildable, ordered block list.

    Returns (compiled, report).  `compiled` is the {x,y,z,mat,kind} list in build
    order — exactly the shape schematic_current.json already carries — or None if
    the design cannot be certified.
    """
    t0 = time.time()
    blocks = [_norm(b) for b in raw_blocks]
    report = {
        'certified': False,
        'block_count': len(blocks),
        'errors': [],
        'warnings': [],
        'unbuilt': [],
        'scaffold': [],
        'passes': 0,
        'ms': 0,
        'materials': {},
        'slots': 0,
        'stats': {},
    }
    if not blocks:
        report['errors'].append({'verdict': 'empty', 'detail': 'schematic has no blocks'})
        return None, report

    # 1 — lint
    errors = lint(blocks)
    fatal = [e for e in errors if e['verdict'] in (Verdict.BAD_MATERIAL, Verdict.BELOW_GROUND, Verdict.DUPLICATE)]
    report['errors'] = errors
    if fatal:
        report['ms'] = round((time.time() - t0) * 1000)
        return None, report

    # zone check is a warning: kit.py grows its clear zone to fit
    zx0, zx1, zz0, zz1, zytop = M.kit_zone(blocks)
    if (zx1 - zx0) > 48 or (zz1 - zz0) > 48:
        report['warnings'].append(
            {
                'verdict': Verdict.OUT_OF_ZONE,
                'detail': f'footprint {zx1 - zx0}x{zz1 - zz0} is very large — the kit clears '
                f'and re-grasses this whole area each run',
            }
        )

    bounds = M.analysis_bounds(blocks)

    # 2 — simulate
    placed, unbuilt, world, bot, passes = simulate(blocks, bounds=bounds)
    report['passes'] = passes

    # 3 — scaffold, iteratively.
    # One round is not enough: a block 3 storeys up has no support until the block
    # below it is placed, so its scaffold cannot be planned yet. Each round the
    # structure rises, exposing the next round's supports — so we alternate
    # repair and re-simulation until it stops helping.
    scaffold = []
    if unbuilt and auto_scaffold:
        for _ in range(24):
            new = repair(unbuilt, world, bounds, bot)
            if not new:
                break
            scaffold.extend(new)
            # Re-simulate from scratch so the emitted order is proven as a whole
            # rather than patched together.
            placed, unbuilt, world, bot, passes = simulate(blocks + scaffold, bounds=bounds)
            report['passes'] = passes
            if not unbuilt:
                break
        report['scaffold'] = scaffold

    report['unbuilt'] = classify_unbuilt(unbuilt, world)

    all_blocks = blocks + scaffold
    mats, slots = material_budget([b for b in all_blocks])
    report['materials'] = mats
    report['slots'] = slots
    if slots > 36:
        report['warnings'].append(
            {
                'verdict': 'inventory',
                'detail': f'{slots} inventory slots needed but the bot has 36 — the last '
                f'/give calls will be silently dropped and those blocks will '
                f'never be placed',
            }
        )

    report['stats'] = {
        'placed': len(placed),
        'unbuilt': len(unbuilt),
        'scaffold': len(scaffold),
        'coverage': round(100.0 * len(placed) / max(1, len(all_blocks)), 1),
    }
    report['certified'] = not unbuilt and not fatal
    report['ms'] = round((time.time() - t0) * 1000)

    if not report['certified']:
        return None, report
    return placed, report
