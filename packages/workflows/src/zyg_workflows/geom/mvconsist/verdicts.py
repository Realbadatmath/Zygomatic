# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""mvconsist.verdicts — stability() across repeats, verdict() against a caller's band, and the command line.

Moved verbatim from mvconsist.py (lines 896-1163) by the 2026-10 modularization split;
no logic, constant or comment was changed.
"""

from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Sequence
import json
import os
import statistics
import sys
from zyg_workflows.geom.mvconsist.constants import (
    CAMERA_GROUPINGS,
    DEFAULT_GLOB,
    DEFAULT_MAX_IMAGE_SIZE,
    QUALITY_PRESETS,
)
from zyg_workflows.geom.mvconsist.sfm import (
    measure,
)

# ---------------------------------------------------------------------------
# Stability. The resolution limit of the whole gate.
# ---------------------------------------------------------------------------


def stability(
    image_dir: str,
    n_runs: int = 3,
    *,
    seeds: Optional[Sequence[int]] = None,
    **measure_kwargs,
) -> Dict[str, Any]:
    """Run measure() n_runs times on the same set and report the spread.

    WHY THIS IS NOT OPTIONAL. Every number measure() returns is the output of a randomised
    algorithm. A difference between two sets is only real if it is larger than the wobble a
    single set shows against itself. That wobble is what this returns, and a caller building
    a band from controls must widen the band by at least this much or the band is fiction.

    By default all runs use the SAME seed (whatever measure_kwargs says, default 0), because
    the question is 'is this reproducible when I ask for the same thing twice' — which is
    what a gate re-run does. Pass `seeds` to sweep different seeds instead, which answers the
    different and larger question of how much the seed itself matters."""
    runs: List[Dict[str, Any]] = []
    for i in range(n_runs):
        kw = dict(measure_kwargs)
        if seeds is not None:
            kw['seed'] = int(seeds[i % len(seeds)])
        runs.append(measure(image_dir, **kw))

    fields = (
        'registration_rate',
        'mean_reproj_error_px',
        'mean_track_length',
        'n_registered',
        'n_points3D',
        'n_models',
        'n_verified_matches',
        'n_features_mean',
    )
    spread: Dict[str, Any] = {}
    for f in fields:
        vals = [r.get(f) for r in runs]
        if any(v is None for v in vals):
            spread[f] = {'values': vals, 'note': 'at least one run did not produce this field'}
            continue
        vals = [float(v) for v in vals]
        spread[f] = {
            'values': vals,
            'min': min(vals),
            'max': max(vals),
            'range': round(max(vals) - min(vals), 6),
            'mean': round(statistics.fmean(vals), 6),
            'stdev': round(statistics.stdev(vals), 6) if len(vals) > 1 else 0.0,
        }

    statuses = [r.get('status') for r in runs]
    identical = all(all(r.get(f) == runs[0].get(f) for f in fields) for r in runs)
    return {
        'image_dir': os.path.abspath(image_dir),
        'n_runs': n_runs,
        'seeds': list(seeds) if seeds is not None else [measure_kwargs.get('seed', 0)] * n_runs,
        'statuses': statuses,
        'bit_identical_across_runs': bool(identical),
        'spread': spread,
        'nondeterminism': runs[0].get('nondeterminism'),
        'runs': runs,
    }


# ---------------------------------------------------------------------------
# Verdict. Separate on purpose, and inert without a band.
# ---------------------------------------------------------------------------


def verdict(result: Dict[str, Any], band: Dict[str, Any]) -> Dict[str, Any]:
    """Apply a caller-supplied band to a measure() result.

    THERE IS NO DEFAULT BAND AND THERE WILL NOT BE ONE. `band` is required, and it is meant
    to be derived from CONTROL SETS — renders of one real mesh through the same contract —
    never from the sheets being judged. If you find yourself adjusting a band because a
    character failed, stop: that is the finding, and the finding is the deliverable.

    band is {field: {"min": x} | {"max": y} | {"min": x, "max": y}}. Every named field must
    be present and non-None in the result or the verdict is 'unmeasured' — a band cannot be
    applied to a number that does not exist, and guessing one would be the exact failure this
    module is built to prevent.

    A result with status no_model or degenerate fails by construction, before the band is
    consulted — see the comment in the body. Only status=error yields "unmeasured".

    Returns {"verdict": "pass"|"fail"|"unmeasured", "checks": [...], "reason": str}.
    """
    if not isinstance(band, dict) or not band:
        raise ValueError(
            'verdict() requires a non-empty band. This module measures; it does not carry '
            'thresholds. Derive the band from control sets and pass it in.'
        )

    status = result.get('status')

    # 'error' is the ONLY status that means we do not know. The measurement did not run, so
    # there is nothing to judge and we must not pretend otherwise in either direction.
    if status == 'error':
        return {
            'verdict': 'unmeasured',
            'checks': [],
            'reason': 'the measurement did not run, so there is nothing to judge: %s' % result.get('reason'),
        }

    # 'no_model' and 'degenerate' ARE measurements — successful ones, of the worst possible
    # outcome. They must fail before the band is consulted, because a band that names
    # mean_track_length would otherwise return 'unmeasured' (the field is legitimately None
    # when there is no reconstruction to take a track length from) and a caller filtering on
    # 'fail' would silently skip the total failures while catching the partial ones. That
    # inversion is the single most dangerous bug this function could have.
    if status in ('no_model', 'degenerate'):
        return {
            'verdict': 'fail',
            'checks': [],
            'reason': 'no usable reconstruction, which fails any band by construction: %s' % result.get('reason'),
        }

    checks = []
    failed, unmeasured = [], []
    for field, lim in band.items():
        val = result.get(field)
        if val is None:
            unmeasured.append(field)
            checks.append({'field': field, 'value': None, 'band': lim, 'ok': None})
            continue
        lo, hi = lim.get('min'), lim.get('max')
        ok = True
        if lo is not None and val < lo:
            ok = False
        if hi is not None and val > hi:
            ok = False
        checks.append({'field': field, 'value': val, 'band': lim, 'ok': ok})
        if not ok:
            failed.append('%s=%s outside %s' % (field, val, lim))

    if unmeasured:
        return {
            'verdict': 'unmeasured',
            'checks': checks,
            'reason': 'band names field(s) the measurement did not produce: %s (result '
            'status=%s). No verdict is possible.' % (', '.join(unmeasured), result.get('status')),
        }
    if failed:
        return {'verdict': 'fail', 'checks': checks, 'reason': '; '.join(failed)}
    return {
        'verdict': 'pass',
        'checks': checks,
        'reason': 'all %d banded field(s) within the supplied band' % len(checks),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Sequence[str]) -> int:
    import argparse

    p = argparse.ArgumentParser(
        prog='python -m zyg_workflows.geom.mvconsist',
        description='Measure multi-view consistency of a directory of .png images by '
        'running structure-from-motion over them. Measures only; no verdict.',
    )
    p.add_argument('image_dir')
    p.add_argument('--json', action='store_true', help='emit the result dict as JSON only')
    p.add_argument(
        '--glob',
        default=DEFAULT_GLOB,
        help='glob inside image_dir (default %(default)s). Contact sheets need '
        "'cell_[0-9][0-9].png' to exclude the differently-sized body cell.",
    )
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--quality', default='high', choices=list(QUALITY_PRESETS))
    p.add_argument(
        '--camera-grouping',
        default='per_resolution',
        choices=list(CAMERA_GROUPINGS),
        help='which images share intrinsics (default %(default)s). Changing this '
        'changes the answer; hold it fixed across compared sets.',
    )
    p.add_argument('--max-image-size', type=int, default=DEFAULT_MAX_IMAGE_SIZE)
    p.add_argument('--num-threads', type=int, default=-1)
    p.add_argument('--work-dir', default=None)
    p.add_argument(
        '--stability',
        type=int,
        default=0,
        metavar='N',
        help='run the set N times and report the spread instead of one result',
    )
    a = p.parse_args(argv)

    kw = dict(
        seed=a.seed,
        quality=a.quality,
        pattern=a.glob,
        camera_grouping=a.camera_grouping,
        max_image_size=a.max_image_size,
        num_threads=a.num_threads,
        work_dir=a.work_dir,
    )

    if a.stability:
        out = stability(a.image_dir, a.stability, **kw)
        if a.json:
            print(json.dumps(out, indent=2, sort_keys=True))
        else:
            print('stability over %d runs of %s' % (out['n_runs'], out['image_dir']))
            print('  statuses: %s' % out['statuses'])
            print('  bit-identical across runs: %s' % out['bit_identical_across_runs'])
            for f, s in out['spread'].items():
                if 'range' in s:
                    print('  %-24s values=%s range=%s stdev=%s' % (f, s['values'], s['range'], s['stdev']))
                else:
                    print('  %-24s %s' % (f, s))
        return 0

    r = measure(a.image_dir, **kw)
    if a.json:
        print(json.dumps(r, indent=2, sort_keys=True))
        return 0 if r['status'] != 'error' else 1

    print('multi-view consistency measurement (NOT a verdict)')
    print('  image_dir            %s' % r.get('image_dir'))
    print('  status               %s' % r.get('status'))
    print('  reason               %s' % r.get('reason'))
    if r.get('status') == 'error':
        return 1
    for k in (
        'n_images',
        'n_registered',
        'registration_rate',
        'n_points3D',
        'mean_reproj_error_px',
        'mean_track_length',
        'n_models',
        'model_sizes',
        'n_features_mean',
        'n_verified_matches',
        'n_verified_pairs',
        'n_parallax_pairs',
        'n_images_with_verified_pairs',
        'two_view_configs',
        'camera_grouping',
        'n_camera_groups',
        'n_cameras_in_db',
        'quality',
        'seed',
        'elapsed_s',
    ):
        print('  %-20s %s' % (k, r.get(k)))
    print('  not made deterministic:')
    for n in r.get('nondeterminism', []):
        print('    - %s' % n)
    for n in r.get('notes', []):
        print('  note: %s' % n)
    return 0


if __name__ == '__main__':
    raise SystemExit(_main(sys.argv[1:]))
