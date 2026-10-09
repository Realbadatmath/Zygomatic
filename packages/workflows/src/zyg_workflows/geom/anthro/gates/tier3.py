# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 3 — profile, symmetry, cast.

Moved verbatim out of the old single-file gates.py (lines 4775-5146).
"""

import math
import numpy as np
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.policy import (
    FAIL,
    MISSING,
    NOT_APPLICABLE,
    NOT_IMPLEMENTABLE,
    PASS,
    REPORT,
    UNMEASURABLE,
    WARN,
)
from zyg_workflows.geom.anthro.gates.bands import (
    CAST_PAIR_CALIBRATION,
    CAST_PAIR_SAMPLES,
    CAST_PAIR_SEED,
    CAST_PAIR_SOURCE,
    CAST_SAME_BODY_PERCENTILE,
    CAST_SIMILAR_PERCENTILE,
    CAST_VECTOR_COMPONENTS,
    DEPTH_RATIOS,
    GateConfigError,
    REALISM_ASYMMETRY_BAND_MM,
    REALISM_ASYMMETRY_POP_MEAN_MM,
    SYM_MORPH_TOL_SOURCE,
)
from zyg_workflows.geom.anthro.gates.gate import _result
from zyg_workflows.geom.anthro.gates.subject import Subject, _roll_up, _roll_up_summary, _skip_phrase, _sub
from zyg_workflows.geom.anthro.gates.tier2 import _input_provenance, _wide_gate


# ---------------------------------------------------------------------------------
# TIER 3 — profile, symmetry, cast
# ---------------------------------------------------------------------------------
def t3_depths_wide(sub):
    """DEPTH-axis metrics, banded exactly like the widths.

    This project learned the hard way that a width-only metric set lets a solver dump its
    error into the unmeasured depth axis: the silhouette passes every gate from the front
    and the body is wrong from the side. Depths are the least stature-predicted class in
    the pack (chest depth r=0.22, buttock depth r=0.22), so like breadths they are gated
    against the population band and never against a stature-derived point.
    """
    r = _wide_gate(sub, DEPTH_RATIOS, 'depth')
    extra = []
    wd = sub.mm('waist_depth_omphalion')
    wb = sub.mm('waist_breadth_omphalion')
    if wd and wb:
        extra.append(
            _sub(
                'waist_depth_over_breadth',
                REPORT,
                'waist depth %.1f / breadth %.1f = %.4f. No ANSUR standing '
                'abdominal depth at omphalion exists in the pack (the pack '
                'carries a SEATED abdominal depth, which is not comparable), '
                'so this is reported as a torso cross-section aspect ratio '
                'only.' % (wd, wb, wd / wb),
                observed=round(wd / wb, 4),
            )
        )
    for k in ('chest_depth', 'buttock_depth'):
        d = sub.mm(k)
        b = sub.mm({'chest_depth': 'chest_breadth', 'buttock_depth': 'hip_breadth'}[k])
        if d and b:
            extra.append(
                _sub(
                    '%s_over_breadth' % k,
                    REPORT,
                    '%s %.1f / paired breadth %.1f = %.4f — the depth:width '
                    'aspect that a width-only gate set cannot see' % (k, d, b, d / b),
                    observed=round(d / b, 4),
                )
            )
    r.setdefault('detail', {}).setdefault('checks', []).extend(extra)
    return r


def t3_morph_symmetry(sub):
    """MORPH-SPACE symmetry: a CORRECTNESS check on the build, not a tolerance on realism.

    A body out of a bilaterally symmetric morph space should be symmetric by construction.
    It is not exactly: anny's own local-morph target data is not bit-mirror-symmetric, and
    the measured floor over six bodies is 0.0632 mm, rising with the number of fitted
    measure-* locals. So the band is that floor with headroom (%.2f mm), not floating-point
    noise, and the honest expected value is "the vendor floor", not zero. Anything above
    the band is our layer, and the sculpt channel is the first place to look.

    It is deliberately a different gate id, a different payload and a different band from
    t3_realism_asymmetry, and integrity.py stamps check='morph_correctness' on the record
    so the two cannot be conflated by accident.
    """ % IG.SYM_MORPH_TOL_MM
    r = sub.integrity['mirror_symmetry_morph']
    d = r['detail']
    if d.get('check') != 'morph_correctness':
        raise GateConfigError(
            'integrity.mirror_symmetry payload is not stamped morph_correctness — refusing to gate on it'
        )
    ok = bool(d['pass'])
    anat = sub.spec.get('anatomy_layer') or {}
    return _result(
        PASS if ok else FAIL,
        'max mirror deviation %.4f mm (%.4f mm about the best-fit plane) '
        "against a %.2f mm tolerance; the expected value is anny's morph-data "
        'floor (0.0632 mm on the male original), not exactly 0'
        % (d['max_mm'], d['max_mm_about_best_fit'], d['tol_mm']),
        observed=d['max_mm'],
        band=[0.0, d['tol_mm']],
        source=SYM_MORPH_TOL_SOURCE,
        tol_provenance_from_integrity=d['tol_provenance'],
        rms_mm=d['rms_mm'],
        rigid_offset_um=d['rigid_offset_um'],
        vertices_over_tol=d['vertices_over_tol'],
        check=d['check'],
        is_not=d['not'],
        sculpt_channel=anat or None,
        diagnosis=(
            'the post-morph sculpt channel %r is not mirror-equivariant; '
            'this is a build defect in our layer, not in anny' % anat
        )
        if (not ok and anat)
        else None,
    )


def t3_realism_asymmetry(sub):
    """Deliberately injected realism asymmetry, %g-%g mm, population mean %.1f mm.

    Kept API-distinct from the morph gate on purpose, and the trap it avoids was live on
    this project: until the abs_definition sculpt was made mirror-symmetric on 2026-08-05,
    two of the four issued bodies deviated 2.93 and 3.76 mm from mirror symmetry — well
    inside this 0-10 mm realism band, so an operator reading one merged "asymmetry" number
    would have concluded the bodies were pleasingly lifelike while a sculpt pass was
    broken. With that fixed the four bodies now sit at 0.0014-0.0632 mm (the vendor
    morph-data floor), which changes nothing about the argument: this gate refuses to be
    that number and runs only when the pipeline DECLARES asymmetry was injected.
    """ % (REALISM_ASYMMETRY_BAND_MM + (REALISM_ASYMMETRY_POP_MEAN_MM,))
    d = sub.integrity['mirror_symmetry_morph']['detail']
    if not sub.spec.get('realism_asymmetry_injected'):
        return _result(
            NOT_APPLICABLE,
            'no realism asymmetry was declared for this subject, so the %g-%g '
            'mm band does not apply. The measured deviation of %.4f mm belongs '
            'entirely to t3_morph_symmetry and must NOT be excused by this '
            'band.' % (REALISM_ASYMMETRY_BAND_MM + (d['max_mm'],)),
            observed=d['max_mm'],
            band=list(REALISM_ASYMMETRY_BAND_MM),
            source='research briefing: injected realism asymmetry 0-10 mm, '
            'population mean %.1f mm' % REALISM_ASYMMETRY_POP_MEAN_MM,
        )
    lo, hi = REALISM_ASYMMETRY_BAND_MM
    x = d['max_mm']
    return _result(
        PASS if lo <= x <= hi else FAIL,
        'declared realism asymmetry %.3f mm against the %g-%g mm band' % (x, lo, hi),
        observed=x,
        band=[lo, hi],
        source='research briefing population mean %.1f mm' % REALISM_ASYMMETRY_POP_MEAN_MM,
    )


def t3_spine_curvature(sub):
    """NOT IMPLEMENTABLE on this cage, and saying so is the correct output.

    A lordosis angle without declared endpoints is not a measurement: the same spine reads
    32.4 deg over L1-L5, 35-38 deg over L4-S1 and about 70 deg over L1-sacrum. Endpoints
    are therefore mandatory — and this cage cannot supply them. landmarks.py resolves no
    vertebral landmark at all: cervicale is UNRESOLVED because the posterior midline is
    monotone from 0.76 to 0.92 of stature with no vertebra prominens, tenth rib is
    UNRESOLVED because there is no costal margin, and iliocristale is UNRESOLVED because
    there is no crest bulge. With no C7, no T10, no L1, no L5 and no sacrum, any curvature
    number would be a proxy invented to fill the gate, which is exactly the failure mode
    the endpoint rule exists to prevent.
    """
    declared = sub.spec.get('spine_endpoints')
    lm = sub.landmarks
    unresolved = [k for k in ('cervicale', 'tenth_rib', 'iliocristale') if not (lm.get(k) or {}).get('point')]
    return _result(
        NOT_IMPLEMENTABLE,
        'no vertebral endpoints exist on this cage (unresolved: %s), so no '
        'lordosis or kyphosis angle can be reported. Declared endpoints: %r'
        % (', '.join(unresolved) or 'none missing', declared),
        source='geom.anthro.landmarks resolution result for this mesh',
        why='the same spine measures 32.4 deg L1-L5, 35-38 deg L4-S1 and '
        '~70 deg L1-sacrum; an angle without its endpoints is meaningless',
        would_need=['C7', 'T10 or the costal margin', 'L1', 'L5', 'S1'],
        declared_endpoints=declared,
    )


_CAST_CACHE = {}
_CAST_FAILED = {}


def registry_cast(exclude=None):
    """Every registered character, built once per process, plus the ones that would not
    rebuild.

    A cast partner that cannot be rebuilt used to abort the whole report of whatever
    character was being gated — one bad recipe took every other character's report with
    it. It is now returned as a named failure so t3_cast_diversity can report "this pair
    could not be compared" instead: the diversity claim over a cast with an unbuildable
    member is weaker than the claim over a complete one, and that has to be visible rather
    than fatal. Returns (subjects, {name: error}).
    """
    reg = MS._registry()
    names = sorted(list(reg.get('originals', {})) + list(reg.get('derived', {})))
    out, failed = [], {}
    for n in names:
        if n == exclude:
            continue
        if n in _CAST_FAILED:
            failed[n] = _CAST_FAILED[n]
            continue
        if n not in _CAST_CACHE:
            try:
                _CAST_CACHE[n] = Subject.from_registry(n)
            except Exception as e:  # noqa: BLE001
                _CAST_FAILED[n] = '%s: %s' % (type(e).__name__, e)
                failed[n] = _CAST_FAILED[n]
                continue
        out.append(_CAST_CACHE[n])
    return out, failed


def _cast_vector(sub):
    xs = [sub.ratio(k) for k in CAST_VECTOR_COMPONENTS]
    return None if any(x is None for x in xs) else np.asarray(xs, np.float64)


_CAST_NULL = {}


def _cast_null(sex, idx):
    """The null distribution the cast metric is read against: how far apart are two
    RANDOM real people of the same sex, in the same units.

    Recomputed from the pack rather than trusted from the constant table, so that a
    rebuilt reference pack cannot silently invalidate the threshold.
    """
    key = (sex, tuple(idx))
    if key not in _CAST_NULL:
        X = reference().npz['%s_vectors' % sex].astype(np.float64)[:, list(idx)]
        inv = np.linalg.inv(np.cov(X, rowvar=False))
        rng = np.random.default_rng(CAST_PAIR_SEED)
        pick = rng.integers(0, len(X), (CAST_PAIR_SAMPLES, 2))
        pick = pick[pick[:, 0] != pick[:, 1]]
        d = X[pick[:, 0]] - X[pick[:, 1]]
        dist = np.sort(np.sqrt(np.einsum('ij,jk,ik->i', d, inv, d)))
        _CAST_NULL[key] = (inv, dist)
    return _CAST_NULL[key]


def t3_cast_diversity(sub):
    """Same-body syndrome, as a calibrated distance between real bodies.

    The distance is Mahalanobis in the population's own covariance, over the four vector
    components this cage can measure, so it asks "how far apart are these two characters
    compared to how far apart two random real people are". Two random same-sex ANSUR
    subjects are separated by 2.58 (median); the 1st percentile is 0.765. A cast pair
    below that is more alike than 99% of randomly drawn pairs of real people.

    Only same-sex pairs are gated. A pair involving a subject outside ANSUR's age window
    is reported with its distance but not gated, because the covariance used to scale the
    difference is an adult covariance. If NO pair is gateable the gate says so and returns
    NOT APPLICABLE — a wall of "not gated" rows is not a diversity pass.

    The vector shares t2_mahalanobis's first coordinate, so it shares its caveat: on this
    cage cervicale is a HOUSE substitution and the separation is measured over three
    measured heights and one substituted one.
    """
    ref = reference()
    order = ref.doc['mahalanobis']['order']
    idx = [order.index(k) for k in CAST_VECTOR_COMPONENTS]
    mine = _cast_vector(sub)
    if mine is None:
        return _result(
            UNMEASURABLE, 'this subject is missing one of the %d cast vector components' % len(CAST_VECTOR_COMPONENTS)
        )
    prov, house = _input_provenance(sub, CAST_VECTOR_COMPONENTS)
    cast = sub.spec.get('cast')
    failed = {}
    if cast is None:
        cast, failed = registry_cast(exclude=sub.name)
    rows = []
    gated = []
    for name, err in sorted(failed.items()):
        rows.append(
            _sub(
                name,
                MISSING,
                'cast partner %r could not be rebuilt from its recipe, so this pair was NOT compared: %s' % (name, err),
                rebuild_error=err,
            )
        )
    for other in cast:
        if other.name == sub.name:
            continue
        theirs = _cast_vector(other)
        if theirs is None:
            rows.append(_sub(other.name, UNMEASURABLE, 'partner vector incomplete'))
            continue
        if other.sex != sub.sex:
            rows.append(
                _sub(
                    other.name,
                    REPORT,
                    'cross-sex pair (%s vs %s): not gated, the covariance is sex-specific' % (sub.sex, other.sex),
                )
            )
            continue
        inv, null = _cast_null(sub.sex, idx)
        d = mine - theirs
        dist = float(math.sqrt(d @ inv @ d))
        cut = float(np.percentile(null, CAST_SAME_BODY_PERCENTILE))
        pct = 100.0 * float(np.searchsorted(null, dist)) / len(null)
        cal = dict(
            CAST_PAIR_CALIBRATION[sub.sex],
            recomputed_p1=round(cut, 4),
            recomputed_median=round(float(np.median(null)), 4),
            pairs_sampled=int(len(null)),
        )
        if not (sub.is_ansur_age and other.is_ansur_age):
            rows.append(
                _sub(
                    other.name,
                    REPORT,
                    'distance %.3f = p%.2f of real same-sex pairs (p1 %.3f, '
                    'median %.3f) — NOT gated, one of the two is outside the '
                    'adult window the covariance came from' % (dist, pct, cut, np.median(null)),
                    distance=round(dist, 4),
                    pair_percentile=round(pct, 3),
                    calibration=cal,
                )
            )
            continue
        gated.append(dist)
        soft = float(np.percentile(null, CAST_SIMILAR_PERCENTILE))
        st = FAIL if dist < cut else (WARN if dist < soft else PASS)
        rows.append(
            _sub(
                other.name,
                st,
                'distance %.3f = p%.2f of real same-sex pairs; same-body cut is '
                'the p%.0f (%.3f), the similar-pair warn level is the p%.0f '
                '(%.3f), and the median real pair is %.3f'
                % (dist, pct, CAST_SAME_BODY_PERCENTILE, cut, CAST_SIMILAR_PERCENTILE, soft, np.median(null)),
                distance=round(dist, 4),
                pair_percentile=round(pct, 3),
                warn_cut=round(soft, 4),
                calibration=cal,
            )
        )
    # informational wide view over every shared measurable ratio, in population SD units
    wide = []
    for other in cast:
        if other.name == sub.name or other.sex != sub.sex:
            continue
        acc, used = [], []
        for k in sorted(set(sub.measurements['ratios']) & set(other.measurements['ratios']) & set(ref.ratios())):
            a, b = sub.ratio(k), other.ratio(k)
            if a is None or b is None:
                continue
            sd = ref.band(k, sub.sex)['sd']
            if sd > 0:
                acc.append(((a - b) / sd) ** 2)
                used.append(k)
        if acc:
            wide.append(
                {
                    'partner': other.name,
                    'rms_population_sd': round(float(np.sqrt(np.mean(acc))), 4),
                    'ratios': len(used),
                }
            )
    status, rows = _roll_up(rows)
    if not rows:
        status = NOT_APPLICABLE
        why = 'no cast partner to compare against'
    elif not gated:
        # Every row is a "not gated" row. Rolling that up as REPORT and classifying it
        # 'ok' would report a diversity PASS over zero comparisons.
        status = NOT_APPLICABLE if status in (PASS, REPORT) else status
        why = (
            '%d cast pair(s), NONE gateable (cross-sex or outside the adult window the '
            'covariance came from), so no same-body claim is made about this character' % len(rows)
        )
    else:
        why = '%d cast pairs, %d gateable; closest gated separation %.3f' % (len(rows), len(gated), min(gated))
    return _result(
        status,
        why + _skip_phrase(rows),
        source=CAST_PAIR_SOURCE,
        checks=rows,
        roll_up=_roll_up_summary(rows),
        vector_provenance=prov,
        substituted_components=house,
        cast_rebuild_failures=failed or None,
        wide_uncalibrated_view=wide,
        wide_note='RMS over every shared measurable ratio in population-SD '
        'units. Uncalibrated — there is no per-subject microdata for '
        'most of these ratios, so it has no null distribution and is '
        'informational only.',
    )
