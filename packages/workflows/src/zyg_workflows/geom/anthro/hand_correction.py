# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The phalanx correction: anny's finger segments are the wrong lengths, and this fixes it.

THE DEFECT, MEASURED 2026-08-08. t5_phalanx_ratio failed on all five issued bodies and on
the anny control, at the same magnitude on every one of them (index mid/prox 0.8938-0.8979
against a two-series band centre of 0.5639). A ratio cannot say WHICH segment is wrong, so
the absolute lengths were taken and expressed as a fraction of each ray's own total, which
removes size from the comparison and leaves shape:

    index ray, metacarpal head -> fingertip        rig        BK2010      shape error
      metacarpal                                  49.5%        45.4%          +8.9%
      proximal phalanx                            17.3%        26.5%         -34.8%
      middle phalanx                              15.5%        14.9%          +4.1%
      distal + fingertip soft tissue              17.7%        13.1%         +35.0%

and the same pattern, same sign, on all four fingers: proximal -24.7 to -34.8%, middle
-3.3 to +4.1%, distal +13.5 to +35.0%. The proximal phalanx — the LONGEST bone in a real
finger — is squeezed from both ends, and the mass has gone into the metacarpal and the
fingertip.

THE HAND IS THE RIGHT SIZE. metacarpal2 head to middle fingertip is 156.59 mm against
BK2010's 156.91 mm, a ratio of 0.9979. So this is not "our hand is smaller than the
survey's"; it is a hand of the right length with its joints in the wrong places.

WHAT IS AND IS NOT INDICTED. The rig is SELF-CONSISTENT: the skinning-weight crossover
between the proximal and middle bones sits at t = 0.3472 / 0.3954 / 0.3633 / 0.3900 along
MCP->tip, against bone PIP positions of 0.3401 / 0.3835 / 0.3665 / 0.3772 — agreement to
0.012. The rigger painted the bend where the bone is. So this is NOT "correct mesh, bones
misplaced inside it", and moving bone positions alone would put the bend where there is no
weight transition and tear the finger.

THE SURFACE CANNOT ARBITRATE, AND THAT IS RECORDED RATHER THAN GLOSSED. A girth profile
(perpendicular radius about the finger axis, 48 bins) was taken to find the knuckle bumps
independently of the rig. At cage resolution it resolves nothing: 3-14 vertices per bin,
radius noise of +/-0.5 mm on a monotone 11.4 -> 4.0 mm taper, and no tri-modal structure
anywhere. anny's cage fingers have NO resolvable knuckle relief. That means the surface
offers no evidence for the correction — and equally none against it, since there is no
knuckle feature that a joint move could be seen to walk away from.

TWO ALTERNATIVES, BOTH REJECTED ON MEASUREMENT, NOT ON TASTE.

  1. The rest-space morph `hand-fingers-length-incr`. It is named as though it were a
     finger-proportion control. It is not: at +1.0 it moves the index mid/prox ratio only
     0.8974 -> 0.8812 while blowing the ray from 77.33 to 120.00 mm (+55%), and it moves
     different fingers in different DIRECTIONS (middle 0.8114 -> 0.9537, ring 0.8340 ->
     0.5705). It is a length knob with proportion as a side effect, and there is no
     setting of it that fixes this defect. anny carries no finger-proportion morph at all:
     a search of all 256 local-change labels for finger/hand/digit/phalanx returns eleven
     labels, all of them whole-hand scale, diameter, spread or translation.

  2. A constant twelve-number correction table. Rejected because it is not constant: solved
     independently on all five bodies plus the control, the per-bone scales spread by up to
     4.01% (finger2-3: 0.7175 on female against 0.7470 on male). A constant would be wrong
     by that much on every body but one, so the correction is SOLVED PER BODY and the
     solution recorded in params.json.

THE INSTRUMENT. anny's rig already carries the exact mechanism: `_scale44` puts a per-bone
scale into the 3x3 block and the kinematic chain propagates it to children. Measured on
the neutral, scaling finger2-1 by 1.5 on the LOCAL Y AXIS lengthens the proximal phalanx
by exactly 1.5 (26.48 -> 39.73 mm) and leaves its girth untouched (9.94 -> 9.94 mm), while
X and Z change girth and not length. Every chain join stays at 0.000 mm. So Y is the
length axis, and a bone scale is a length edit, which is what this defect needs.

The three knobs are COUPLED — scaling a parent scales its descendants' lengths too, and
not by exactly the parent's factor (the children's local frames are rotated relative to
it: a parent scale of 1.5 gives the middle phalanx 1.481). So the scales are not derived
in closed form, they are SOLVED by fixed-point iteration, which converges to a relative
residual below 1e-14 in three to four passes on every body tried.

THE TARGET IS THE MIDPOINT OF TWO INDEPENDENT SERIES, NOT EITHER ONE. hands._ratio_band
already defines each band's centre as 0.5 * (BK2010 + HD2002) — Buryanov & Kotiuk 2010
(n=66, Ukrainian hospital radiographs) and Hamilton & Dunsmuir 2002 (n=197, joint centres
established by cadaveric dissection, which is the rig's own convention). The correction
targets those two centres. Fitting BK alone would have made the BK half of the gate
trivially true; targeting the midpoint means NEITHER series is fitted and both remain
checks. The absolute millimetre lengths in BK2010 are not used by the solver at all, which
leaves them as a genuinely held-out test (see self_test).

WHAT THIS DOES NOT CLAIM. It does not claim the corrected hand is right in any respect the
two series do not cover. The metacarpal is deliberately LEFT ALONE at +6.2 to +12.0%:
BK2010's metapodial is the metacarpal bone, while the rig's `metacarpalN` head sits at the
carpometacarpal joint on a wrist that is a single bone, so that gap is plausibly a landmark
convention difference and not a defect, and the whole-hand length is already correct to
0.2%. Correcting it on that evidence would be an invention. It is measured and reported by
geom.form.hands and gated by nothing.

ROLLBACK: ZYG_HAND_PHALANX_FIX=0 disables the correction process-wide. A body issued with
the correction records `hand_correction` in its params.json; a body issued before it has no
such key and REBUILDS UNCORRECTED, so an old body still reproduces its own recorded hash.
"""

import json
import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Bumped whenever the solved geometry would change, so a body's params.json says which
# correction built it and staleness is visible instead of silent.
HAND_CORRECTION_VERSION = 1

ENV_FLAG = 'ZYG_HAND_PHALANX_FIX'

# The four gated fingers. The THUMB IS DELIBERATELY EXCLUDED: HD2002 publishes no thumb
# figure, so BK2010 would be a single source with no second opinion, and t5_phalanx_ratio
# reports the thumb rather than gating it for exactly that reason. Correcting a digit on
# one series while claiming the two-series midpoint as the method would be a lie about
# where the number came from.
CORRECTED_DIGITS = ('index', 'middle', 'ring', 'little')

# Fixed-point solver. The residual is a RELATIVE length error, so the tolerance is
# dimensionless and the same on a 12-year-old's hand as on an adult's.
SOLVE_TOL = 1e-10
SOLVE_MAX_ITER = 32

_SOLVE_CACHE = {}


def enabled():
    """False only when ZYG_HAND_PHALANX_FIX is explicitly switched off."""
    return str(os.environ.get(ENV_FLAG, '1')).strip().lower() not in ('0', 'false', 'no', 'off')


def _hands():
    """Lazy, because geom.form.hands imports geom.mesh_skeletons which imports this."""
    from zyg_workflows.geom.form import hands as H

    return H


def targets(digit):
    """(mid/prox, dist/mid) for one finger: the CENTRE of each published band.

    hands._ratio_band computes centre = 0.5 * (BK2010 + HD2002). Reading the centre rather
    than re-deriving it means this module cannot drift away from what the gate checks
    against — there is one definition of the target and the gate owns it.
    """
    H = _hands()
    b1 = H._ratio_band(digit, 'mid_over_prox')
    b2 = H._ratio_band(digit, 'dist_over_mid')
    if b1 is None or b2 is None:
        raise RuntimeError(
            'no published band for %r, so there is no target to correct toward. Only '
            'the four fingers have one; the thumb has a single source and is reported, '
            'not gated.' % (digit,)
        )
    return float(b1['centre']), float(b2['centre'])


def _lengths(sk, digit, side):
    H = _hands()
    _base, prox, mid, dist = H.DIGIT_BONES[digit]
    return [H._blen(sk, b, side) * 1000.0 for b in (prox, mid, dist)]


def solve(phenotype, local_changes=None, side='L', bone_scales=None):
    """Solve the per-bone Y scales that put this body's four fingers on the band centres.

    The ray total (MCP -> fingertip) is HELD: the three target lengths are that body's own
    ray redistributed, never a survey's absolute millimetres. So the correction changes
    finger SHAPE and cannot change hand SIZE, which is already correct to 0.2% and is not
    this gate's subject.

    Raises rather than returning a partial solution if the iteration does not converge —
    a body built from scales that did not converge would be a body nobody asked for, and
    the failure has to reach the operator instead of being averaged away.
    """
    H = _hands()
    key = json.dumps([dict(phenotype), dict(local_changes or {}), dict(bone_scales or {}), side], sort_keys=True)
    if key in _SOLVE_CACHE:
        return _SOLVE_CACHE[key]

    scales = {}
    for d in CORRECTED_DIGITS:
        _base, prox, mid, dist = H.DIGIT_BONES[d]
        for b in (prox, mid, dist):
            scales[b] = [1.0, 1.0, 1.0]

    def _sk(sc):
        # apply_hand_correction=False: the solver must see the UNCORRECTED rig plus
        # whatever it is currently proposing, or it would be chasing its own tail.
        merged = merge(bone_scales, sc)
        return H.skeleton(phenotype, local_changes, merged or None, apply_hand_correction=False)

    sk0 = _sk(None)
    before, want = {}, {}
    for d in CORRECTED_DIGITS:
        cur = _lengths(sk0, d, side)
        r1, r2 = targets(d)
        ray = sum(cur)
        P = ray / (1.0 + r1 + r1 * r2)
        want[d] = [P, r1 * P, r1 * r2 * P]
        before[d] = {
            'proximal_mm': cur[0],
            'middle_mm': cur[1],
            'distal_mm': cur[2],
            'ray_mm': ray,
            'mid_over_prox': cur[1] / cur[0],
            'dist_over_mid': cur[2] / cur[1],
        }

    residual, iters = float('inf'), 0
    for iters in range(1, SOLVE_MAX_ITER + 1):  # noqa: B007  counter is read after the loop ('iterations' below)
        sk = _sk(scales)
        residual = 0.0
        for d in CORRECTED_DIGITS:
            _base, prox, mid, dist = H.DIGIT_BONES[d]
            cur = _lengths(sk, d, side)
            for i, bone in enumerate((prox, mid, dist)):
                if cur[i] <= 0.0:
                    raise RuntimeError(
                        'bone %r solved to a non-positive length (%.6f mm) on this body. '
                        'The correction is a redistribution of an existing ray and can '
                        'never legitimately produce one.' % (bone, cur[i])
                    )
                k = want[d][i] / cur[i]
                scales[bone][1] *= k
                residual = max(residual, abs(k - 1.0))
        if residual < SOLVE_TOL:
            break
    else:
        raise RuntimeError(
            'the phalanx correction did not converge on this body after %d passes '
            '(relative residual %.3e, tolerance %.0e). Refusing to issue a body from '
            'scales that do not solve.' % (SOLVE_MAX_ITER, residual, SOLVE_TOL)
        )

    skf = _sk(scales)
    after, ray_drift = {}, {}
    for d in CORRECTED_DIGITS:
        cur = _lengths(skf, d, side)
        after[d] = {
            'proximal_mm': cur[0],
            'middle_mm': cur[1],
            'distal_mm': cur[2],
            'ray_mm': sum(cur),
            'mid_over_prox': cur[1] / cur[0],
            'dist_over_mid': cur[2] / cur[1],
        }
        ray_drift[d] = sum(cur) - before[d]['ray_mm']

    # The ray is held by CONSTRUCTION, so a drift here is an instrument fault, not a
    # tolerance to widen. 1e-6 mm is a nanometre; anything above it means the solve and
    # the measurement disagree about what they are measuring.
    worst_ray = max(abs(x) for x in ray_drift.values())
    if worst_ray > 1e-6:
        raise RuntimeError(
            'the correction moved a finger ray by %.3e mm. The three targets are that '
            'ray redistributed, so the total cannot move; this means the solver and the '
            'skeleton reader disagree.' % worst_ray
        )

    rec = {
        'version': HAND_CORRECTION_VERSION,
        'scales': {b: [1.0, float(s[1]), 1.0] for b, s in sorted(scales.items())},
        'side_solved': side,
        'digits': list(CORRECTED_DIGITS),
        'targets': {d: dict(zip(('mid_over_prox', 'dist_over_mid'), targets(d))) for d in CORRECTED_DIGITS},
        'before': before,
        'after': after,
        'ray_length_change_mm': ray_drift,
        'iterations': iters,
        'residual': residual,
        'target_source': (
            'the CENTRE of each t5_phalanx_ratio band, which hands._ratio_band defines '
            'as 0.5 * (Buryanov & Kotiuk 2010 n=66 + Hamilton & Dunsmuir 2002 n=197). '
            'The midpoint of two independent series, so neither is fitted and both stay '
            "checks. BK2010's absolute millimetre lengths are not used by the solver."
        ),
        'method': (
            "per-bone LOCAL-Y scale through anny's own _scale44, solved by fixed-point "
            'iteration because the kinematic chain couples the three knobs. Y is the '
            'length axis (measured: prox x1.5 exactly, girth unchanged); X and Z change '
            'girth and not length.'
        ),
        'not_corrected': {
            'metacarpal': "left at +6.2 to +12.0% vs BK2010. The rig's metacarpal head "
            'is at the carpometacarpal joint of a single-bone wrist while '
            'BK2010 measures the metacarpal bone, so the gap is plausibly '
            'a landmark convention difference; whole-hand length is '
            'already correct to 0.2%.',
            'thumb': 'HD2002 publishes no thumb figure, so there is no second opinion '
            'and t5_phalanx_ratio reports rather than gates it.',
            'toes': 'no external normative table of toe phalanx lengths was located; see hands.DIGIT_UNRESOLVED.',
        },
    }
    _SOLVE_CACHE[key] = rec
    return rec


def merge(*dicts):
    """Compose bone-scale dicts MULTIPLICATIVELY, including on shared keys.

    _scale44 already multiplies when two DIFFERENT keys hit the same bone, so multiplying
    on an identical key is the same semantics and not a new one. Overwriting instead would
    silently drop either the operator's request or the house correction depending on merge
    order, and the issued body would not be the one that was asked for — the exact failure
    _scale44's own no-match rule exists to prevent.
    """
    out = {}
    for d in dicts:
        for k, s in (d or {}).items():
            v = [float(s)] * 3 if not isinstance(s, (list, tuple)) else [float(x) for x in s]
            if k in out:
                out[k] = [out[k][i] * v[i] for i in range(3)]
            else:
                out[k] = list(v)
    return out


def scales_from_params(params):
    """The correction a REGISTERED body was issued with, or None if it predates the fix.

    Read from params.json rather than re-solved, so a rebuild reproduces the issued mesh
    bit for bit and a body issued before 2026-08-08 rebuilds as its uncorrected self
    instead of silently becoming a different body.
    """
    rec = (params or {}).get('hand_correction')
    if not rec or not rec.get('applied'):
        return None
    return {b: list(s) for b, s in (rec.get('scales') or {}).items()}


def effective_scales(phenotype, local_changes=None, bone_scales=None, params=None):
    """The bone scales a build should actually use: operator request x house correction.

    THE params ARGUMENT IS A THREE-STATE SIGNAL, and getting this wrong breaks every
    already-issued body at once:

      params is None                  a fresh build with no registered body behind it.
                                      SOLVE a correction. This is the new-character path
                                      and every reference/calibration body.
      params has hand_correction      a registered body issued WITH the correction.
                                      Reuse the RECORDED scales verbatim — never re-solve,
                                      because a re-solve is only bit-identical while the
                                      solver and the library are unchanged, and the
                                      recorded cage hash has to keep reproducing.
      params without hand_correction  a registered body issued BEFORE the correction
                                      existed. Apply NOTHING. Re-solving here would
                                      silently reissue every pre-2026-08-08 body as a
                                      different hand and then fail its own cage hash with
                                      a message about library drift.
    """
    if not enabled():
        return (dict(bone_scales) if bone_scales else None), {
            'applied': False,
            'version': HAND_CORRECTION_VERSION,
            'why': '%s is switched off in this process' % ENV_FLAG,
        }
    if params is not None:
        recorded = scales_from_params(params)
        if recorded is None:
            return (dict(bone_scales) if bone_scales else None), {
                'applied': False,
                'version': None,
                'why': 'this body was issued before the phalanx correction existed and '
                'records none, so it rebuilds as the hand that shipped. Re-derive '
                'it to pick the correction up.',
            }
        return merge(bone_scales, recorded) or None, dict(params['hand_correction'])
    rec = solve(phenotype, local_changes, bone_scales=bone_scales)
    out = dict(rec)
    out['applied'] = True
    return merge(bone_scales, rec['scales']) or None, out


# =====================================================================================
# self-test
# =====================================================================================


def _hand_length_sd_mm(phenotype):
    """One ANSUR II population SD of hand length, in mm, for a body of this stature/sex.

    The reference pack stores hand length as a STATURE RATIO (hand_length_over_stature),
    which is the form that transfers across body sizes, so the SD is recovered by
    multiplying the ratio SD by this body's own stature. Returns None rather than a guess
    if the pack is unreadable — a check with no external bar should say so, not invent one.
    """
    import json
    import os as _os

    try:
        here = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
        path = _os.path.join(_os.path.dirname(here), 'data', 'assets', 'anthro_reference', 'reference.json')
        if not _os.path.exists(path):
            return None
        ref = json.load(open(path))
        sex = 'female' if float((phenotype or {}).get('gender', 0.0)) > 0.5 else 'male'
        st = (((ref.get('stats') or {}).get(sex) or {}).get('pooled') or {}).get('hand_length_over_stature')
        if not st or not st.get('sd'):
            return None
        from zyg_workflows.geom import mesh_skeletons as MS

        v, _f, _a = MS._build_mesh(phenotype, None, None)
        stature_mm = float(MS._measure(v)['height_m']) * 1000.0
        return float(st['sd']) * stature_mm
    except Exception:  # noqa: BLE001
        return None


def _anisotropy(v, sk, bone, weights, side='L'):
    """Ratio of the two principal cross-section axes of one bone's own vertices.

    1.0 is a circular cross-section. The number itself is not interesting; the CHANGE in
    it under the correction is, because that is what a shear looks like and what a mean
    radius cannot see.
    """
    import numpy as np

    nm = '%s.%s' % (bone, side)
    w = weights.get(nm)
    if w is None:
        return None
    sel = np.where(w >= 0.5)[0]
    if len(sel) < 8:
        return None
    j = sk['index'][nm]
    h, t = sk['head'][j], sk['tail'][j]
    ax = t - h
    n = np.linalg.norm(ax)
    if n <= 0:
        return None
    ax = ax / n
    P = v[sel] - h
    perp = P - np.outer(P @ ax, ax)
    # principal axes of the perpendicular scatter
    ev = np.linalg.eigvalsh(np.cov(perp.T))
    ev = np.sort(ev)[::-1][:2]
    if ev[1] <= 0:
        return None
    return float((ev[0] / ev[1]) ** 0.5)


GATE_Z_CORRECTED_MAX = 1e-9
"""How near zero a CORRECTED body's worst mid/prox z must land.

Not a tuned tolerance. The correction solves the bone scales that put each gated ratio
ON the band centre, so a body rebuilt from its own recorded scales reproduces the centre
to floating-point noise and nothing else; the observed spread over the four registered
bodies is 9.3e-15 to 5.6e-14. 1e-9 is five orders of magnitude above that noise and
eleven below the 3.5-sigma the uncorrected chain reads, so no real regression can hide
under it and no rounding change can trip it.
"""

GATE_Z_BEFORE_SIGFIGS = 12
"""Significant figures at which the UNCORRECTED reading must reproduce the record.

The `before` block of a body's hand_correction is the chain that shipped. Rebuilding it
runs the same arithmetic on the same inputs, so agreement is exact to ~1e-16; 12 figures
is a deliberate margin, not a fit.
"""


def _close_sigfigs(a, b, figs):
    """True when a and b agree to `figs` significant figures."""
    if a == b:
        return True
    scale = max(abs(a), abs(b))
    if scale == 0.0:
        return True
    return abs(a - b) / scale < 10.0 ** (-figs)


def _scales_equal(a, b, tol=1e-15):
    a, b = (a or {}), (b or {})
    if set(a) != set(b):
        return False
    return all(all(abs(float(x) - float(y)) <= tol for x, y in zip(a[k], b[k])) for k in a)


if __name__ == '__main__':  # the CLI lives in hand_correction_cli
    from zyg_workflows.geom.anthro.hand_correction_cli import main as _cli_main

    raise SystemExit(_cli_main())
