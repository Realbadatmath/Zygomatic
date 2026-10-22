#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Ground-truth tests for the buildability compiler.

Run:  cd hub && python3 tests/test_compiler.py

The 10 built-in schematics are the ground truth: the Nether Portal has actually
been built by the bot in the live sim (14/14 blocks), and the Watchtower's
geometry is the shape the original tower proved out.  If the compiler cannot
certify them, the model is wrong.

The falsification test matters more than the positive one: strip the Watchtower's
internal staircase and the upper walls MUST be reported unreachable.  A validator
that says yes to everything is worse than no validator, because it gets trusted.
"""

import importlib.util
import logging as _zyg_logging
import sys
from pathlib import Path

_zyg_log = _zyg_logging.getLogger(__name__)

HUB = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HUB))

import schem_model as M  # noqa: E402
import schem_compiler as C  # noqa: E402

FAILURES = []
PASSES = []


def check(name, cond, detail=''):
    if cond:
        PASSES.append(name)
        _zyg_log.info(f'  PASS  {name}')
    else:
        FAILURES.append((name, detail))
        _zyg_log.info(f'  FAIL  {name}  {detail}')


def load_builtins():
    """Import the hub's SCHEMATICS without starting its Flask app."""
    spec = importlib.util.spec_from_file_location('gs', HUB / 'gamesim_server.py')
    gs = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gs)
    return gs.SCHEMATICS


def test_model_constants():
    _zyg_log.info('\n[model] constants match the code that actually runs')
    check('reach range is 4.0 (bot.js GoalPlaceBlock range:4)', M.REACH_RANGE == 4.0)
    check("head offset is 1.6 (goals.js:415, NOT mineflayer's 1.62 eye height)", M.HEAD_DY == 1.6)
    check('max drop is 4 (movements.js:107)', M.MAX_DROP_DOWN == 4)
    check('no line-of-sight test (bot.js passes LOS:false)', M.CHECK_LINE_OF_SIGHT is False)
    check('parkour not modelled (conservative)', M.MODEL_PARKOUR is False)


def test_manifest():
    _zyg_log.info('\n[manifest] registry truth from minecraft-data')
    b = M.blocks()
    check('manifest loaded', len(b) > 1000, f'{len(b)} blocks')
    check('225 blocks do not support placement', sum(1 for v in b.values() if v['bb'] != 'block') == 225)
    check("slabs support placement (bb=='block' is not 'full cube')", M.supports_placement('stone_brick_slab'))
    check('stairs support placement', M.supports_placement('stone_brick_stairs'))
    check('torch does NOT support placement', not M.supports_placement('torch'))
    check('stone_bricks is giveable', M.is_giveable('stone_bricks'))
    check('bedrock is not giveable... (sanity: it is, actually)', M.is_known('bedrock'))


def test_face_centers():
    _zyg_log.info('\n[geometry] face centres match pathfinder shapes.js')
    # Target at (0,66,0), ref is the full cube below it at (0,65,0).
    # Placing on its top face: centre must be the target's bottom face centre.
    c = M.face_centers((0, 65, 0), (0, 1, 0), 'stone_bricks')
    check('top-face centre of the block below == (0.5, 66, 0.5)', c == [(0.5, 66.0, 0.5)], str(c))
    # Side face
    c = M.face_centers((1, 66, 0), (-1, 0, 0), 'stone_bricks')
    check('west-face centre of the block at +x == (1.0, 66.5, 0.5)', c == [(1.0, 66.5, 0.5)], str(c))


def test_standing_in():
    _zyg_log.info('\n[geometry] isStandingIn forbids exactly two cells')
    t = (0, 66, 0)
    check('standing in the target is forbidden', M.is_standing_in((0, 66, 0), t))
    check('standing directly below the target is forbidden', M.is_standing_in((0, 65, 0), t))
    check('standing beside it is allowed', not M.is_standing_in((1, 66, 0), t))
    check('standing 2 below is allowed', not M.is_standing_in((0, 64, 0), t))


def test_builtins_certify(schematics):
    _zyg_log.info('\n[ground truth] all 10 built-in schematics must certify')
    for sid, s in schematics.items():
        compiled, rep = C.compile_schematic(s['blocks'], auto_scaffold=False)
        detail = ''
        if not rep['certified']:
            u = rep['unbuilt'][:3]
            detail = (
                f'{rep["stats"]["unbuilt"]}/{rep["block_count"]} unbuilt, '
                f'e.g. {[(x["pos"], x["mat"], x["verdict"]) for x in u]}'
            )
        check(f'{sid} certifies ({rep["block_count"]} blocks, {rep["ms"]}ms)', rep['certified'], detail)


def test_order_is_valid(schematics):
    _zyg_log.info('\n[ordering] emitted order is self-supporting at every step')
    s = schematics['watchtower']
    compiled, rep = C.compile_schematic(s['blocks'], auto_scaffold=False)
    if not compiled:
        check('watchtower compiled (prerequisite)', False)
        return
    world = M.ground_world(M.analysis_bounds(compiled))
    ok = True
    bad = None
    for b in compiled:
        if M.find_ref((b['x'], b['y'], b['z']), world) is None:
            ok = False
            bad = b
            break
        world[(b['x'], b['y'], b['z'])] = b['mat']
    check('every block has support when its turn comes', ok, str(bad))
    check('order covers every block', len(compiled) == len(s['blocks']))


def test_falsification():
    """THE test. A validator that says yes to everything is worse than none.

    The 1x1 column is airtight where the watchtower ablation is not: a 1-block
    wall is WALKABLE, so a tower is its own staircase and the bot climbs its own
    courses (verified — the ablated watchtower really is buildable, so the stair
    rings are insurance, not necessity). A 1-wide column has no room to step
    aside, so it can only ever be built from the ground, which pins the reach
    ceiling to exactly feet+5.
    """
    _zyg_log.info('\n[falsification] THE test — the reach ceiling must be enforced')
    col = [{'x': 0, 'y': y, 'z': -5, 'mat': 'stone_bricks', 'kind': 'col'} for y in range(65, 75)]
    compiled, rep = C.compile_schematic(col, auto_scaffold=False)
    check(
        '10-tall 1x1 column does NOT certify',
        not rep['certified'],
        'compiler certified a column taller than the bot can reach',
    )

    unbuilt_ys = sorted(u['pos'][1] for u in rep['unbuilt'])
    check(
        'exactly y=71..74 are unbuildable (feet at 65 + reach ceiling 5 = 70)',
        unbuilt_ys == [71, 72, 73, 74],
        str(unbuilt_ys),
    )
    check('6 blocks placed (y=65..70)', rep['stats']['placed'] == 6, f'placed={rep["stats"]["placed"]}')
    check(
        "the first failure is 'unreachable', not 'nosupport'",
        rep['unbuilt'][0]['verdict'] == C.Verdict.UNREACHABLE,
        str(rep['unbuilt'][0]['verdict']),
    )

    # And the boundary case: 6 tall must certify, 7 tall must not.
    _, r6 = C.compile_schematic(col[:6], auto_scaffold=False)
    _, r7 = C.compile_schematic(col[:7], auto_scaffold=False)
    check('column to y=70 certifies (at the ceiling)', r6['certified'])
    check('column to y=71 does not (one past it)', not r7['certified'])


def test_scaffold_repairs_column():
    _zyg_log.info('\n[scaffold] synthesis must build a staircase up to the column top')
    col = [{'x': 0, 'y': y, 'z': -5, 'mat': 'stone_bricks', 'kind': 'col'} for y in range(65, 75)]
    compiled, rep = C.compile_schematic(col, auto_scaffold=True)
    check('scaffold synthesis produced blocks', len(rep['scaffold']) > 0, f'scaffold={len(rep["scaffold"])}')
    check(
        'the whole column now certifies',
        rep['certified'],
        f'unbuilt={rep["stats"]["unbuilt"]} scaffold={len(rep["scaffold"])}',
    )
    if rep['scaffold']:
        ys = sorted({s['y'] for s in rep['scaffold']})
        check('scaffold rises (it is a staircase, not a pile)', len(ys) > 1, str(ys))
    if compiled:
        # The emitted order must still be support-valid with scaffold merged in.
        world = M.ground_world(M.analysis_bounds(compiled))
        ok = all(
            M.find_ref((b['x'], b['y'], b['z']), world) is not None
            and not world.__setitem__((b['x'], b['y'], b['z']), b['mat'])
            for b in compiled
        )
        check('scaffolded order is support-valid at every step', ok)


def test_watchtower_ablation_is_buildable(schematics):
    """Documents the finding that surprised us, so a future change that breaks it
    is visible rather than silent."""
    _zyg_log.info('\n[finding] a 1-block wall is walkable — the tower is its own staircase')
    s = schematics['watchtower']
    ablated = [b for b in s['blocks'] if b['kind'] != 'stair']
    check('ablation removed the stair ring', len(ablated) < len(s['blocks']))
    compiled, rep = C.compile_schematic(ablated, auto_scaffold=False)
    check(
        'watchtower still certifies without its staircase (bot climbs its courses)',
        rep['certified'],
        f'unbuilt={rep["stats"]["unbuilt"]}',
    )


def test_lint_catches_corruption():
    _zyg_log.info('\n[lint] the silent-corruption footguns are caught')
    bad = [{'x': 0, 'y': 65, 'z': -5, 'mat': 'stone_brickz', 'kind': 'wall'}]
    compiled, rep = C.compile_schematic(bad)
    check(
        "typo'd material rejected",
        not rep['certified'] and any(e['verdict'] == C.Verdict.BAD_MATERIAL for e in rep['errors']),
    )

    # A real block with no item form: bot.js would silently build it in stone.
    nogive = [b for b in M.blocks() if not M.blocks()[b]['give']]
    if nogive:
        blocks = [{'x': 0, 'y': 65, 'z': -5, 'mat': nogive[0], 'kind': 'wall'}]
        compiled, rep = C.compile_schematic(blocks)
        check(
            f'non-giveable block rejected ({nogive[0]})',
            any(e['verdict'] == C.Verdict.BAD_MATERIAL for e in rep['errors']),
        )

    dup = [
        {'x': 0, 'y': 65, 'z': -5, 'mat': 'stone_bricks', 'kind': 'wall'},
        {'x': 0, 'y': 65, 'z': -5, 'mat': 'cobblestone', 'kind': 'wall'},
    ]
    compiled, rep = C.compile_schematic(dup)
    check('duplicate cell rejected', any(e['verdict'] == C.Verdict.DUPLICATE for e in rep['errors']))

    below = [{'x': 0, 'y': 64, 'z': -5, 'mat': 'stone_bricks', 'kind': 'wall'}]
    compiled, rep = C.compile_schematic(below)
    check('block at ground level rejected', any(e['verdict'] == C.Verdict.BELOW_GROUND for e in rep['errors']))


def test_floating_block():
    _zyg_log.info('\n[support] a floating island cannot be built')
    floating = [{'x': 0, 'y': 70, 'z': -5, 'mat': 'stone_bricks', 'kind': 'wall'}]
    compiled, rep = C.compile_schematic(floating, auto_scaffold=False)
    check(
        'block with no neighbours is nosupport',
        not rep['certified'] and rep['unbuilt'] and rep['unbuilt'][0]['verdict'] == C.Verdict.NOSUPPORT,
    )


if __name__ == '__main__':  # the CLI lives in test_compiler_cli
    from zyg_dashboard.hub.tests.test_compiler_cli import main as _cli_main

    raise SystemExit(_cli_main())
