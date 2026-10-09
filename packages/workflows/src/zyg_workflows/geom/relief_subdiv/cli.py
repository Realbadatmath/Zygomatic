# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The self-test on hand-checkable meshes, and the command line.

Moved verbatim out of the old single-file relief_subdiv.py (lines 1769-2059).
"""

import sys

import numpy as np

from zyg_workflows.geom.relief_subdiv.subdivision import (
    _verify_fast_mirror_map,
    catmull_clark,
    mirror_map_override,
    subdiv_mirror_map,
)
from zyg_workflows.geom.relief_subdiv.nulls import _pooled_runs_at, cuts_for
from zyg_workflows.geom.relief_subdiv.measurement import determinism_check, measure
# ---------------------------------------------------------------------------------
# self-test — the primitives, on meshes small enough to check by hand
# ---------------------------------------------------------------------------------


def self_test(verbose=True):
    """Everything checkable without the anny model."""
    out = {}

    # a closed all-quad cube, mirror-symmetric in x, with quads deliberately stored from
    # DIFFERENT start corners on the two halves — the trap that broke _apply_anatomy.
    V = np.array([[x, y, z] for z in (-1.0, 1.0) for y in (-1.0, 1.0) for x in (-1.0, 1.0)], np.float64)
    F = np.array([[0, 1, 3, 2], [4, 6, 7, 5], [0, 4, 5, 1], [2, 3, 7, 6], [0, 2, 6, 4], [1, 5, 7, 3]], np.int64)
    V2, F2, rec = catmull_clark(V, F)
    # Euler: a closed quad mesh has E = 2F, so V' = V + F + 2F and F' = 4F
    out['cube_counts'] = {
        'v': int(len(V2)),
        'expect_v': len(V) + len(F) + 2 * len(F),
        'f': int(len(F2)),
        'expect_f': 4 * len(F),
        'ok': bool(len(V2) == len(V) + 3 * len(F) and len(F2) == 4 * len(F)),
    }
    out['cube_index_preserved'] = {
        'max_move': float(np.linalg.norm(V2[: len(V)] - V, axis=1).max()),
        'note': 'nonzero by construction — Catmull-Clark moves the originals',
    }
    # the limit of a cube is a sphere-ish blob: every original corner pulls in by the same
    # amount, which is a symmetry statement the implementation must satisfy exactly
    d = np.linalg.norm(V2[: len(V)] - V, axis=1)
    out['cube_corner_symmetry'] = {'spread': float(d.max() - d.min())}

    # anny's cage is closed; a mesh with a hole must be REFUSED, not silently smoothed
    try:
        catmull_clark(V, F[:-1])
        out['open_mesh_refused'] = False
    except ValueError:
        out['open_mesh_refused'] = True

    # triangles must be refused outright (the GLB route)
    try:
        catmull_clark(V, np.array([[0, 1, 2]], np.int64))
        out['triangles_refused'] = False
    except ValueError:
        out['triangles_refused'] = True

    # combinatorial mirror on the cube: x -> -x pairs vertices 0<->1, 2<->3, ...
    mate = np.array([1, 0, 3, 2, 5, 4, 7, 6], np.int64)
    cm = subdiv_mirror_map(mate, F, 1)
    Vm = V2[cm].copy()
    Vm[:, 0] *= -1.0
    out['combinatorial_mirror_cube'] = {
        'paired': int((cm >= 0).sum()),
        'of': int(len(V2)),
        'max_residual': float(np.abs(V2 - Vm).max()),
        'involution_ok': bool(np.array_equal(cm[cm], np.arange(len(V2)))),
    }

    # two levels must agree with one level applied twice
    A = subdiv_mirror_map(mate, F, 2)
    V3, F3, _ = catmull_clark(V2, F2)
    Vm3 = V3[A].copy()
    Vm3[:, 0] *= -1.0
    out['combinatorial_mirror_level2'] = {
        'paired': int((A >= 0).sum()),
        'of': int(len(V3)),
        'max_residual': float(np.abs(V3 - Vm3).max()),
    }

    # determinism: the same input twice, byte for byte
    W2, G2, _ = catmull_clark(V, F)
    out['deterministic'] = {'bytes_identical': bool(V2.tobytes() == W2.tobytes() and F2.tobytes() == G2.tobytes())}

    # the level cut may never be accepted below the refusal floor
    try:
        cuts_for(
            {
                'ridge_null': {
                    'by_mode': {
                        'ridge': {'abs_station_relief_frac': {'p99': 1e-9}, 'abs_station_contrast': {'p99': 0.1}},
                        'point': {'abs_station_relief_frac': {'p99': 1e-9}, 'abs_station_contrast': {'p99': 0.1}},
                    }
                }
            },
            'level',
        )
        out['degenerate_level_cut_refused'] = False
    except ValueError:
        out['degenerate_level_cut_refused'] = True

    # ...and a level cut whose CONTRAST null has collapsed must be refused too. Guarding
    # only the relief axis leaves half the two-axis test ungated.
    _panel = {
        'ridge_panel': {
            m: {
                'cut': {'min_frac_stature': 2.0e-3, 'min_contrast': 1e-9},
                'min_run': 4,
                'min_run_any_sign': 5,
                'n_seeds': 6,
                'n_pools_pooled': 144,
                'seeds': [1, 2, 3, 4, 5, 6],
                'station_p99_frac': {'spread_frac': 0.1},
                'null_rate_resolved_at_cut': 0.0,
                'null_rate_point_only_or_better_at_cut': 0.0,
                'rate_provenance': 'test',
            }
            for m in ('ridge', 'point')
        },
        'ridge_null': {'by_mode': {m: {} for m in ('ridge', 'point')}},
    }
    try:
        cuts_for(_panel, 'level')
        out['degenerate_contrast_cut_refused'] = False
    except ValueError:
        out['degenerate_contrast_cut_refused'] = True

    # a level cut may not be derived from a null that carries no seed panel: one draw is
    # not a measurement of this mesh (see LEVEL_NULL_SEED_PANEL).
    try:
        cuts_for(
            {
                'ridge_null': {
                    'by_mode': {
                        m: {'abs_station_relief_frac': {'p99': 2.0e-3}, 'abs_station_contrast': {'p99': 3.0}}
                        for m in ('ridge', 'point')
                    }
                }
            },
            'level',
        )
        out['level_cut_without_panel_refused'] = False
    except ValueError:
        out['level_cut_without_panel_refused'] = True

    # the pooled re-scorer must agree with ridge's own classifier station for station
    from zyg_workflows.geom.form import ridge as _RD

    _rl = np.array([0.0, 3e-3, 3e-3, 3e-3, 3e-3, 0.0], np.float64)
    _cn = np.array([0.0, 5.0, 5.0, 5.0, 5.0, 0.0], np.float64)
    _ok = np.ones(6, bool)
    _hp = np.full(6, 0.01)
    _want = _RD._score_profile(_rl, _cn, _ok, 'either', 1e-3, 2.0)
    _got = _pooled_runs_at([[(_rl, _cn, _ok, _hp)]], 'either', 1e-3, 2.0)
    out['pooled_runs_at_cut'] = {
        'run': int(_got[0][0]),
        'expect': int(_want[2]),
        'any': int(_got[1][0]),
        'expect_any': int(_want[6]),
        'ok': bool(_got[0][0] == _want[2] and _got[1][0] == _want[6]),
    }

    # relief.py's own structural guarantee still holds where this module runs
    from zyg_workflows.geom import relief as RL

    out['falloff_inside_collar'] = RL._check_falloff_inside_collar()

    # the k-d tree mirror map must reproduce the loop one exactly, on a mesh where both are
    # trivially checkable, and the override must restore the real function on every path
    out['fast_mirror_map_on_cube'] = _verify_fast_mirror_map(V2, 1e-6)
    real = RL.mirror_map
    try:
        with mirror_map_override(np.arange(len(V2)), np.zeros(len(V2)), len(V2)):
            got = RL.mirror_map(V2, 1e-6)[0]
            wrong_size = RL.mirror_map(V, 1e-6)[0]  # must fall through to the real one
            live = RL.mirror_map is not real
        out['override'] = {
            'installed': bool(live and np.array_equal(got, np.arange(len(V2)))),
            'falls_through_on_wrong_size': bool(len(wrong_size) == len(V)),
            'restored_after_block': bool(RL.mirror_map is real),
        }
    finally:
        RL.mirror_map = real

    # ---------------------------------------------------------------- THE ASSERTIONS
    # Computing a boolean and printing it is not a test. Every invariant above is
    # load-bearing — index preservation is what lets regions.json be reused at 219,368
    # vertices, and the combinatorial mirror map is what the layer mirrors through at every
    # level above 1 — so a broken primitive must make this function RAISE and the CLI exit
    # non-zero, not print a False that a CI step reads as success.
    fail = []

    def _need(cond, what):
        if not cond:
            fail.append(what)

    _need(
        out['cube_counts']['ok'],
        'catmull_clark vertex/face counts: got %(v)d/%(f)d, Euler requires '
        '%(expect_v)d/%(expect_f)d' % out['cube_counts'],
    )
    _need(
        out['cube_corner_symmetry']['spread'] < 1e-12,
        'catmull_clark is not symmetric on a symmetric cube: corner displacement spread '
        '%.3e' % out['cube_corner_symmetry']['spread'],
    )
    _need(out['open_mesh_refused'], 'catmull_clark accepted an OPEN mesh')
    _need(out['triangles_refused'], 'catmull_clark accepted TRIANGLES')
    cm = out['combinatorial_mirror_cube']
    _need(cm['paired'] == cm['of'], 'combinatorial mirror map paired %d of %d cube vertices' % (cm['paired'], cm['of']))
    _need(cm['max_residual'] < 1e-12, 'combinatorial mirror map is not a mirror: residual %.3e' % cm['max_residual'])
    _need(cm['involution_ok'], 'combinatorial mirror map is not an involution (m[m[i]] != i)')
    l2 = out['combinatorial_mirror_level2']
    _need(l2['paired'] == l2['of'], 'combinatorial mirror map paired %d of %d at level 2' % (l2['paired'], l2['of']))
    _need(
        l2['max_residual'] < 1e-12,
        'combinatorial mirror map at level 2 is not a mirror: residual %.3e' % l2['max_residual'],
    )
    _need(out['deterministic']['bytes_identical'], 'catmull_clark is not byte-deterministic on identical input')
    _need(out['degenerate_level_cut_refused'], 'cuts_for accepted a level cut below LEVEL_CUT_ABSOLUTE_FLOOR_FRAC')
    _need(
        out['degenerate_contrast_cut_refused'], 'cuts_for accepted a level cut below LEVEL_CUT_ABSOLUTE_FLOOR_CONTRAST'
    )
    _need(out['level_cut_without_panel_refused'], 'cuts_for derived a level cut from a null with no seed panel')
    # NOT `_need(out['falloff_inside_collar'], ...)`: that dict is always truthy, so the
    # check would pass for any content. Assert the inequality it reports instead.
    _fc = out['falloff_inside_collar']
    _need(
        _fc['falloff_frac'] < _fc['ridge_gap_frac'],
        'relief.FALLOFF_FRAC (%.5f) is no longer strictly inside ridge.RIDGE_GAP_FRAC '
        '(%.5f)' % (_fc['falloff_frac'], _fc['ridge_gap_frac']),
    )
    fm = out['fast_mirror_map_on_cube']
    _need(
        fm['identical'],
        'fast_mirror_map disagrees with relief.mirror_map on the cube (%d differences)' % fm['differences'],
    )
    ov = out['override']
    _need(ov['installed'], 'mirror_map_override did not install its map')
    _need(ov['falls_through_on_wrong_size'], 'mirror_map_override answered for a mesh it was not built for')
    _need(ov['restored_after_block'], 'mirror_map_override did not restore relief.mirror_map')
    _need(
        out['pooled_runs_at_cut']['ok'],
        'the pooled re-scorer disagrees with ridge._score_profile on a hand-built profile',
    )

    out['_checks_run'] = 15
    out['_failures'] = fail
    out['ok'] = not fail
    if verbose:
        for k in sorted(out):
            if not k.startswith('_'):
                print('  %-32s %s' % (k, out[k]))
        print('  %-32s %d checks, %d failure(s)' % ('ASSERTED', out['_checks_run'], len(fail)))
    if fail:
        raise AssertionError(
            'relief_subdiv self-test FAILED %d of %d checks:\n  - %s'
            % (len(fail), out['_checks_run'], '\n  - '.join(fail))
        )
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else 'selftest'
    print('=== geom/relief_subdiv.py self-test (primitives only; no anny model) ===')
    # self_test RAISES on any failed invariant; the non-zero exit is the whole point of
    # running it from a CI step, so the exception is turned into a return code here rather
    # than swallowed. A caller reading only the exit status must be told the truth by it.
    try:
        self_test()
    except AssertionError as exc:  # noqa: BLE001
        print('SELF-TEST FAILED\n%s' % exc)
        return 1
    if cmd == 'selftest':
        return 0
    if cmd == 'determinism':
        who = argv[1] if len(argv) > 1 else 'female'
        lv = int(argv[2]) if len(argv) > 2 else 2
        print('\n=== determinism: subdivide + sculpt at 1 vs 8 threads ===')
        d = determinism_check(who, lv)
        print('  %s' % d)
        if not d['identical']:
            print('DETERMINISM FAILED: %s' % d['hashes'])
            return 1
        return 0
    if cmd != 'measure':
        print(
            'usage: python -m zyg_workflows.geom.relief_subdiv [selftest | determinism BODY LEVEL | '
            'measure BODY[,BODY] LEVEL[,LEVEL] [out.json] [states] [cuts]]'
        )
        return 2
    who = tuple((argv[1] if len(argv) > 1 else 'female').split(','))
    lv = tuple(int(x) for x in (argv[2] if len(argv) > 2 else '2').split(','))
    out_path = argv[3] if len(argv) > 3 else None
    states = tuple((argv[4] if len(argv) > 4 else 'base,cage2sub,sub').split(','))
    cuts = tuple((argv[5] if len(argv) > 5 else 'level,shipped').split(','))
    measure(which=who, levels=lv, states=states, cut_kinds=cuts, out_path=out_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
