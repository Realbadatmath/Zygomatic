# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""THE FOUR CONTROLS, as reusable primitives instead of good intentions.

Each one here exists because its absence caused a specific, dated, measured failure in this
project. None is a general-purpose quality idea; every one is a scar. They are collected in
a module so that the next measurement gets them by importing rather than by remembering.

  1. require_bracket()   — a measurement may not emit a number without a CEILING and a
                           FLOOR. Failure it prevents: reading leakage 0.084 as the
                           filter's limit when it was the PROBE's own spectral spread.
  2. runtime_stamp()     — an artefact records what EXECUTED, not what was configured.
                           Failure it prevents: benchmarking against an analytic iteration
                           count that scan_ingest computes and does not run.
  3. assert_coverage()   — count what you touched and assert it equals what you claimed.
                           Failure it prevents: a probe measuring the umbrella filter while
                           the Butterworth one produced the output.
  4. cross_check()       — two independent instruments must agree, or the disagreement is
                           the finding. Failure it prevents: believing cProfile's 88%
                           attribution on a 20,435-call site when wall-clock said 2.3x.

THE PROPERTY THEY ALL SHARE, and it is the whole point: EACH ONE CAN FAIL LOUDLY. A control
that degrades to a warning gets read as noise; a control that returns a value on the error
path gets read as a result. These raise. If that is inconvenient at a call site, the call
site is where the argument should happen — not inside the control.

AND THEY MUST THEMSELVES BE TESTED. geom/anthro/mutation.py exists to break gates on
purpose; self_test() below does the same to these, because a control that has never been
observed to fire is indistinguishable from one that has stopped working. That is not
hypothetical: geom/sfm_capability.py's BROKEN path was originally verified by SIMULATING a
baseline diff rather than by inducing a real break.
"""

from __future__ import annotations

import os
import platform
import sys
import time

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

SCHEMA = 'geom.controls/1'


class ControlError(RuntimeError):
    """Raised when a control fires. Never caught inside this module."""


# ----------------------------------------------------------------------------------
# 1. CEILING AND FLOOR
# ----------------------------------------------------------------------------------


def require_bracket(name, value, ceiling, floor, higher_is_better=True, ceiling_means=None, floor_means=None):
    """Score `value` only if a ceiling AND a floor exist, and place it between them.

    THE FAILURE THIS PREVENTS, measured 2026-08-08. A Butterworth separator scored leakage
    0.0842 on a synthetic sinusoid probe and I read it as the filter's limitation. It was
    not: raising the order to 8 moved it to 0.0873 — WORSE — because a plane wave on a
    curved irregular surface is not a single Laplace-Beltrami eigenmode, so its energy is
    spread and even a perfect brick wall could not score 0. The 0.084 was the PROBE's own
    spectral spread. Without a ceiling there was nothing for the number to be good or bad
    against, and the natural reading was the wrong one.

    A ceiling is a case that MUST score well (a real 3D object, an uncorrupted body). A
    floor is a case that MUST score badly (six different people mixed together, a
    deliberately broken mesh). Both must be measured on the SAME instrument as `value`, or
    they bracket nothing.

    Raises rather than warning in three situations, each of which has bitten:
      * either bound missing — the caller is about to publish an unanchored number;
      * ceiling not better than floor — the instrument does not discriminate at all, and
        every value it produces is meaningless, including the flattering ones;
      * value outside the bracket — either the instrument is unstable or one of the bounds
        is wrong, and both are findings rather than results.
    """
    if ceiling is None or floor is None:
        raise ControlError(
            '%s: refusing to score. ceiling=%r floor=%r — a measurement without BOTH is '
            'unanchored, and an unanchored number gets read as though its scale were '
            'obvious. Measure a case that must score well and a case that must score '
            'badly, on this same instrument, before reporting this value.' % (name, ceiling, floor)
        )

    c, f, x = float(ceiling), float(floor), float(value)
    span = (c - f) if higher_is_better else (f - c)
    if span <= 0:
        raise ControlError(
            '%s: the instrument does not discriminate. ceiling=%.6g floor=%.6g with '
            'higher_is_better=%s, so the case that must score well does not out-score the '
            'case that must score badly. No value from this instrument means anything '
            'until that is fixed — including values that look good.%s%s'
            % (
                name,
                c,
                f,
                higher_is_better,
                ' ceiling is meant to be: %s.' % ceiling_means if ceiling_means else '',
                ' floor is meant to be: %s.' % floor_means if floor_means else '',
            )
        )

    pos = ((x - f) / span) if higher_is_better else ((f - x) / span)
    out = {
        'name': name,
        'value': x,
        'ceiling': c,
        'floor': f,
        'higher_is_better': bool(higher_is_better),
        'fraction_of_bracket': pos,
        'ceiling_means': ceiling_means,
        'floor_means': floor_means,
    }

    if pos < -0.02 or pos > 1.02:  # 2% slack for instrument noise
        raise ControlError(
            '%s: value %.6g lies OUTSIDE its own bracket [floor %.6g, ceiling %.6g] at '
            '%.1f%% of span. Either the instrument is unstable between runs or one of the '
            'bounds is wrong. Both are findings; neither is a result.' % (name, x, f, c, 100.0 * pos)
        )
    return out


# ----------------------------------------------------------------------------------
# 2. WHAT ACTUALLY RAN
# ----------------------------------------------------------------------------------


def runtime_stamp(what_ran, **detail):
    """Record the code path that EXECUTED, for embedding in an artefact.

    THE FAILURE THIS PREVENTS, measured 2026-08-08. geom/scan_ingest.py defines
    _lowpass_iters (an analytic heat-kernel estimate) and _calibrate_lowpass (which
    iterates until the response is MEASURED at 0.5). It ships the second. I benchmarked
    against the first, because that is the one the formula in the source describes, and the
    difference was not small: 60 iterations against 3,240, scoring selectivity 3.29 against
    the shipped 1.14. The comparison flattered the incumbent for a week.

    A configured value is a claim about intent. Only a stamp written by the branch that ran
    is evidence. `what_ran` should therefore be produced INSIDE the branch — not selected
    afterwards from the same config the branch read, which reproduces the bug one level up.
    """
    if not what_ran or not isinstance(what_ran, str):
        raise ControlError('runtime_stamp needs a non-empty description of what executed; got %r' % (what_ran,))
    return {
        'what_ran': what_ran,
        'stamped_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'python': sys.version.split()[0],
        'host': platform.node(),
        'pid': os.getpid(),
        'detail': dict(detail),
        'note': 'written by the branch that executed. A value copied from config describes intent, not behaviour.',
    }


# ----------------------------------------------------------------------------------
# 3. COVERAGE
# ----------------------------------------------------------------------------------


def assert_coverage(name, claimed, touched, what='items', sample=8):
    """Assert that what was processed is what was advertised.

    THE FAILURE THIS PREVENTS, caught 2026-08-08 before shipping. scan_ingest's transfer
    probe called _probe_response(A, ...) unconditionally — the UMBRELLA operator — while
    the residual it reported beside those numbers had been produced by the Butterworth
    filter. Every figure would have been real, precise, reproducible, and about code that
    did not run. Related, and shipped for a while: t5_joint_rom claiming the whole pose
    library while evaluating the rest pose only (real answer once fixed: 44/44 poses FAIL).

    Compares COUNT and, when `touched` is a collection of ids, IDENTITY — because equal
    counts over different sets is exactly the silent case.
    """
    try:
        n_touched = len(touched)
        ids = set(touched) if not isinstance(touched, int) else None
    except TypeError:
        n_touched, ids = int(touched), None

    if isinstance(claimed, int):
        n_claimed, claimed_ids = claimed, None
    else:
        n_claimed, claimed_ids = len(claimed), set(claimed)

    if n_touched != n_claimed:
        raise ControlError(
            '%s: claimed %d %s, touched %d. A gate or report that advertises a scope it '
            'does not cover produces true numbers about the wrong population.' % (name, n_claimed, what, n_touched)
        )

    if ids is not None and claimed_ids is not None and ids != claimed_ids:
        missing = sorted(claimed_ids - ids)[:sample]
        extra = sorted(ids - claimed_ids)[:sample]
        raise ControlError(
            '%s: counts match (%d) but the SETS differ — this is the silent case. '
            'claimed-not-touched: %s ; touched-not-claimed: %s' % (name, n_claimed, missing or 'none', extra or 'none')
        )
    return {'name': name, 'n': n_claimed, 'what': what, 'identity_checked': ids is not None}


# ----------------------------------------------------------------------------------
# 4. SECOND INSTRUMENT
# ----------------------------------------------------------------------------------


def cross_check(
    name, primary, secondary, rel_tol=0.25, primary_is='primary instrument', secondary_is='independent instrument'
):
    """Two instruments measuring the same quantity must agree, or that is the finding.

    THE FAILURE THIS PREVENTS, measured 2026-08-08. cProfile attributed 88% of a null pass
    to curvature._face_edges. Fixing it produced 1.6-2.3x, not the ~8x that implies —
    because the function was called through np.unique 20,435 times and per-call profiler
    overhead inflated exactly the site being investigated. Wall-clock disagreed with the
    profiler all along: the profiled run took 33.7 s where the unprofiled one takes 111 s.
    One instrument, believed, sent me to build the wrong fix on the wrong hardware.

    Reports the disagreement rather than picking a winner: which instrument is wrong is not
    something the comparison can know.
    """
    p, s = float(primary), float(secondary)
    denom = max(abs(p), abs(s), 1e-30)
    rel = abs(p - s) / denom
    out = {
        'name': name,
        'primary': p,
        'secondary': s,
        'relative_difference': rel,
        'rel_tol': float(rel_tol),
        'primary_is': primary_is,
        'secondary_is': secondary_is,
        'agree': bool(rel <= rel_tol),
    }
    if not out['agree']:
        raise ControlError(
            '%s: instruments disagree by %.1f%% (tolerance %.1f%%). %s says %.6g, %s says '
            '%.6g. Which one is wrong is not decidable from this comparison — that is the '
            'point. Do not proceed on either number until the disagreement is explained.'
            % (name, 100 * rel, 100 * rel_tol, primary_is, p, secondary_is, s)
        )
    return out


# ----------------------------------------------------------------------------------
# THE CONTROLS' OWN CONTROL
# ----------------------------------------------------------------------------------


def self_test(verbose=True):
    """Make every control FIRE, on purpose.

    A control that has never been observed to fire cannot be distinguished from one that
    has stopped working. This is the same argument geom/anthro/mutation.py makes about
    gates, applied one level up to the things that check the gates — and it is not
    hypothetical: sfm_capability's BROKEN path was first 'verified' by simulating a
    baseline diff rather than by inducing a real break.
    """
    fired, missed = [], []

    def expect_raise(label, fn):
        try:
            fn()
        except ControlError:
            fired.append(label)
            return
        except Exception as e:  # noqa: BLE001
            missed.append('%s raised the WRONG type: %s' % (label, type(e).__name__))
            return
        missed.append('%s did NOT fire' % label)

    expect_raise('bracket: missing ceiling', lambda: require_bracket('t', 0.5, None, 0.1))
    expect_raise('bracket: missing floor', lambda: require_bracket('t', 0.5, 1.0, None))
    expect_raise('bracket: ceiling not better than floor', lambda: require_bracket('t', 0.5, 0.2, 0.9))
    expect_raise('bracket: value outside bracket', lambda: require_bracket('t', 5.0, 1.0, 0.0))
    expect_raise('stamp: empty description', lambda: runtime_stamp(''))
    expect_raise('coverage: count mismatch', lambda: assert_coverage('t', 20, list(range(17))))
    expect_raise('coverage: same count, different set', lambda: assert_coverage('t', [1, 2, 3], [1, 2, 4]))
    expect_raise('cross_check: instruments disagree', lambda: cross_check('t', 8.0, 2.3, rel_tol=0.25))

    # and the happy paths must NOT fire
    ok = []
    try:
        require_bracket('t', 0.5, 1.0, 0.0)
        assert_coverage('t', [1, 2, 3], [3, 2, 1])
        cross_check('t', 1.00, 1.05, rel_tol=0.25)
        runtime_stamp('the branch that ran')
        ok.append('happy paths stayed quiet')
    except ControlError as e:
        missed.append('a happy path fired: %s' % e)

    passed = not missed
    if verbose:
        for f in fired:
            _zyg_log.info('  fired as designed: %s' % f)
        for o in ok:
            _zyg_log.info('  %s' % o)
        for m in missed:
            _zyg_log.info('  DEFECT: %s' % m)
        _zyg_log.info(
            '  controls self-test: %s (%d fired, %d defects)' % ('OK' if passed else 'FAILED', len(fired), len(missed))
        )
    return {'schema': SCHEMA, 'passed': passed, 'fired': fired, 'defects': missed}


if __name__ == '__main__':
    sys.exit(0 if self_test()['passed'] else 1)
