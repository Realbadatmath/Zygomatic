# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 2 — plausibility.

Moved verbatim out of the old single-file gates.py (lines 4059-4772).
"""

from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.policy import (
    ANSUR_AGE_MAX_Y,
    ANSUR_AGE_MIN_Y,
    ANSUR_COVERAGE_NOTE,
    FAIL,
    HOUSE,
    MISSING,
    NOT_APPLICABLE,
    PASS,
    REPORT,
    STATURE_ANCHOR_SIGMA,
    UNMEASURABLE,
    WARN,
)
from zyg_workflows.geom.anthro.gates.bands import (
    AGE_CHANNEL,
    AGE_CHANNEL_SOURCE,
    ANCESTRY_LEG_MEANS_MALE,
    ANCESTRY_LEG_SPREAD,
    BREADTH_RATIOS,
    CDC_Z_FAIL,
    CDC_Z_WARN,
    CHILD_CORMIC,
    CHILD_CORMIC_SOURCE,
    CHILD_DIRECTION_SOURCE,
    CHILD_PROPORTION_ASSERTIONS,
    GIRTH_RATIOS,
    GateConfigError,
    SKELETAL_AGE_DRIFT_CEILING,
    TIGHT_HEIGHT_PAIRS,
    VHI_UNITS,
)
from zyg_workflows.geom.anthro.gates.gate import _result
from zyg_workflows.geom.anthro.gates.subject import (
    _band_check,
    _note,
    _roll_up,
    _roll_up_summary,
    _skip_phrase,
    _sub,
    adult_reference,
)


# ---------------------------------------------------------------------------------
# TIER 2 — plausibility
# ---------------------------------------------------------------------------------
def _input_provenance(sub, ratio_keys):
    """Where each ratio the gate is about to use actually came from.

    measure.py's put() copies convention, landmark, iso_class and survey_comparable onto a
    ratio record but NOT provenance, so a ratio that is a HOUSE substitution rather than a
    measurement is indistinguishable from a measured one at the ratio level. This walks
    back to the source measurement and recovers it. Any gate that publishes a joint verdict
    over several ratios has to say which of them were measured, because "four measured
    heights" and "three measured heights and a substitution" are different claims.

    Returns (per_key_records, house_keys).
    """
    meas = sub.measurements['measurements']
    out, house = {}, []
    for k in ratio_keys:
        src = next(
            (name for name, mr in meas.items() if mr.get('ansur_ratio') == k and mr.get('value_mm') is not None), None
        )
        if src is None:
            out[k] = {
                'measurement': None,
                'provenance': None,
                'note': 'no measure.py record publishes this ratio on this mesh',
            }
            continue
        mr = meas[src]
        rec = {
            'measurement': src,
            'provenance': mr.get('provenance'),
            'landmark': mr.get('landmark'),
            'convention': mr.get('convention'),
        }
        if mr.get('provenance') == HOUSE:
            house.append(k)
            rec['substitution_note'] = mr.get('note') or mr.get('reason')
            for extra in ('offset_frac_stature', 'offset_sd_mm'):
                if mr.get(extra) is not None:
                    rec[extra] = mr[extra]
        out[k] = rec
    return out, house


def t2_mahalanobis(sub):
    """THE PRIMARY PLAUSIBILITY GATE: joint Mahalanobis on the ratio vector.

    Thresholds are the pack's EMPIRICAL percentiles of D^2 in the real sample, never
    chi-square — on this data the chi-square 95% value passes a different fraction of real
    people than 0.95, and the pack reports that discrepancy itself.

    Only four of the ten vector components survive a standing mesh of this cage
    (iliocristale and sitting height do not exist on it; biacromial, bicristal,
    acromion-radiale and radiale-stylion have no honest landmark), so what runs is the
    EXACT MARGINAL over those four, with its own empirical thresholds. Four heights is a
    real but narrow view of a body and the result says so.

    AND ONE OF THE FOUR IS NOT A MEASUREMENT. This cage has no vertebra prominens, so
    measure.py emits cervicale_height as UNMEASURABLE and substitutes suprasternale plus a
    per-sex ANSUR mean offset, publishing it under the ANSUR name with provenance HOUSE.
    That substitution travels into this gate's first coordinate, and it is not benign: in
    ANSUR the two heights correlate at only r=0.545 (male) / 0.480 (female), so the model's
    covariance was estimated on a materially different quantity. Every result of this gate
    therefore carries the input provenance beside the verdict, the same way
    t2_heights_tight does per row — and the severity calibration measures the vector AS
    SUBSTITUTED, which is what takes this gate's licence to block away.
    """
    ref = reference()
    order = ref.doc['mahalanobis']['order']
    have = {}
    absent = {}
    for k in order:
        x = sub.ratio(k)
        if x is None:
            m = sub.measurements['measurements']
            why = next((mr.get('reason') for mr in m.values() if mr.get('ansur_ratio') == k and mr.get('reason')), None)
            absent[k] = why or 'not produced by measure.py for this mesh'
        else:
            have[k] = x
    if not have:
        return _result(UNMEASURABLE, 'none of the ten vector components is measurable', detail=absent)
    r = ref.mahalanobis(have, sub.sex)
    prov, house = _input_provenance(sub, r['used'])
    caveat = None
    if house:
        caveat = (
            '%d of the %d components is a HOUSE SUBSTITUTION, not a measurement: %s. '
            'This is a joint verdict over %d measured heights and %d substituted '
            "one(s), and the substituted coordinate is not the quantity the model's "
            'covariance was estimated on (cervicale vs suprasternale correlate at '
            'r=0.545 male / 0.480 female in ANSUR).'
            % (
                len(house),
                len(r['used']),
                '; '.join(
                    '%s <- %s (%s)' % (k, prov[k].get('measurement'), prov[k].get('landmark') or 'substitution')
                    for k in house
                ),
                len(r['used']) - len(house),
                len(house),
            )
        )
    common = dict(
        used=r['used'],
        used_provenance=prov,
        substituted_components=house,
        input_provenance_caveat=caveat,
        missing_components=absent,
        k=r['k'],
        thresholds=r['thresholds'],
        reference_n=r['reference_n'],
        chi2_reference=r['chi2_reference'],
        note=r['note'],
    )
    tail = '' if not caveat else ' — %s' % caveat
    if not sub.is_ansur_age:
        return _result(
            NOT_APPLICABLE,
            'D^2 = %.3f over %d components, but subject age %s y is outside '
            'ANSUR coverage — the joint model is built from 17-58 y adults and '
            'is not a child model%s' % (r['d2'], r['k'], sub.age_years, tail),
            observed=r['d2'],
            band=[0.0, r['thresholds']['p99']],
            source=r['source'],
            coverage=ANSUR_COVERAGE_NOTE,
            **common,
        )
    if not r['pass_']:
        st, msg = (
            FAIL,
            (
                'D^2 = %.3f exceeds the empirical p99 threshold %.3f — this '
                'combination of proportions is more extreme than 99%% of the '
                'reference sample' % (r['d2'], r['thresholds']['p99'])
            ),
        )
    elif r['warn']:
        st, msg = (
            WARN,
            (
                'D^2 = %.3f sits between the empirical p95 (%.3f) and p99 '
                '(%.3f): unusual but real. Surface it, do not reject it.'
                % (r['d2'], r['thresholds']['p95'], r['thresholds']['p99'])
            ),
        )
    else:
        st, msg = PASS, ('D^2 = %.3f, inside the empirical p95 threshold %.3f' % (r['d2'], r['thresholds']['p95']))
    return _result(st, msg + tail, observed=r['d2'], band=[0.0, r['thresholds']['p99']], source=r['source'], **common)


def t2_heights_tight(sub):
    """Heights, gated TIGHT against a stature-anchored point.

    Permitted only because reference.predictability() says so: stature explains 68-97%% of
    the variance of these dimensions. The predicted value uses the pack's per-sex
    regression (slope and intercept from doc['diagnostics'], which is where they live —
    predictability() exposes only the worse-sex summary), and the half-width is the
    MEASURED residual rmse times a HOUSE factor of %g.
    """ % STATURE_ANCHOR_SIGMA
    ref = reference()
    diag = ref.doc['diagnostics'][sub.sex]
    pairs = TIGHT_HEIGHT_PAIRS
    st = sub.stature_mm
    rows = []
    for mesh_key, dim in pairs:
        p = ref.predictability(dim)
        if p['policy'] != 'tight':
            rows.append(
                _sub(
                    dim,
                    NOT_APPLICABLE,
                    'predictability policy is %r (r=%.3f), so this dimension may '
                    'not be gated against a stature-derived point at all' % (p['policy'], p['r']),
                )
            )
            continue
        x = sub.mm(mesh_key)
        if x is None:
            rows.append(_sub(dim, UNMEASURABLE, 'not measurable on this cage'))
            continue
        d = diag[dim]
        pred = d['slope_mm_per_mm_stature'] * st + d['intercept_mm']
        half = STATURE_ANCHOR_SIGMA * d['rmse_mm']
        dev = x - pred
        if not sub.is_ansur_age:
            rows.append(
                _sub(
                    dim,
                    NOT_APPLICABLE,
                    '%.1f mm vs adult-regression prediction %.1f mm (%+.1f mm, '
                    'band +/-%.1f); subject is %s y, outside ANSUR coverage' % (x, pred, dev, half, sub.age_years),
                    observed_mm=x,
                    predicted_mm=round(pred, 1),
                    deviation_mm=round(dev, 1),
                    halfwidth_mm=round(half, 1),
                    r=d['r'],
                    rmse_mm=d['rmse_mm'],
                )
            )
            continue
        ok = abs(dev) <= half
        prov = sub.measurements['measurements'][mesh_key].get('provenance')
        rows.append(
            _sub(
                dim,
                PASS if ok else FAIL,
                '%.1f mm vs stature-predicted %.1f mm (%+.1f mm, tight band '
                '+/-%.1f = %gx rmse, r=%.3f)' % (x, pred, dev, half, STATURE_ANCHOR_SIGMA, d['r']),
                observed_mm=x,
                predicted_mm=round(pred, 1),
                deviation_mm=round(dev, 1),
                halfwidth_mm=round(half, 1),
                r=d['r'],
                rmse_mm=d['rmse_mm'],
                n=d['n'],
                measurement_provenance=prov,
                caveat=(
                    'this mesh value is a HOUSE substitution, not a measurement — see measure.py cervicale_height_house'
                    if prov == HOUSE
                    else None
                ),
            )
        )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d tight height gates: %d fail, %d pass, %d not applicable%s'
        % (
            len(rows),
            sum(1 for r in rows if r['status'] == FAIL),
            sum(1 for r in rows if r['status'] == PASS),
            sum(1 for r in rows if r['status'] == NOT_APPLICABLE),
            _skip_phrase(rows),
        ),
        source='ANSUR II per-sex stature regressions from the reference pack '
        'diagnostics block; the %gx multiplier is HOUSE' % STATURE_ANCHOR_SIGMA,
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def _wide_gate(sub, ratios, label):
    rows = []
    ref = reference()
    for ratio_key, dim in ratios:
        if dim is not None:
            p = ref.predictability(dim)
            if p['policy'] != 'wide':
                # A NOTE about the PACK, not a check on this body: the gate is not
                # entitled to band this ratio at all. If every ratio were excluded this
                # way the roll-up would be NOT_APPLICABLE, which is the honest answer —
                # not a REPORT that classifies 'ok'.
                rows.append(
                    _note(
                        ratio_key,
                        REPORT,
                        'pack policy for %s is %r, not wide, so this gate may not band it' % (dim, p['policy']),
                    )
                )
                continue
        r = _band_check(sub, ratio_key)
        rows.append(
            _sub(
                ratio_key,
                r['status'],
                r['explain'],
                observed=r['observed'],
                band=r['band'],
                **{
                    k: v
                    for k, v in (r.get('detail') or {}).items()
                    if k in ('percentile', 'mean', 'sd', 'ancestry_declared', 'not_comparable_because')
                },
            )
        )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d %s gates: %d fail, %d warn, %d report-only%s'
        % (
            len(rows),
            label,
            sum(1 for r in rows if r['status'] == FAIL),
            sum(1 for r in rows if r['status'] == WARN),
            sum(1 for r in rows if r['status'] == REPORT),
            _skip_phrase(rows),
        ),
        source='population percentile bands for the declared group; WIDE '
        'because reference.predictability() says stature does not '
        'predict these',
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def t2_breadths_wide(sub):
    """Breadths, gated WIDE against the population band and NEVER against a stature point.

    Stature predicts biacromial breadth at r=0.53 (rmse 16.2 mm) and bideltoid at r=0.31
    (rmse 30.9 mm). A breadth pinned to a stature-derived value is a fabricated
    constraint, so these are compared to the group's own p1-p99 band.
    """
    return _wide_gate(sub, BREADTH_RATIOS, 'breadth')


def t2_girths_wide(sub):
    """Circumferences, same wide treatment (waist circumference vs stature is r=0.21)."""
    return _wide_gate(sub, GIRTH_RATIOS, 'circumference')


def t2_ancestry_leg(sub):
    """Leg proportion against an ANCESTRY-PARAMETERISED band, warning when none is declared.

    Crotch-height/stature is the largest proportion effect in the whole pack: male means
    run %s (per-subject group means, which is the statistic every band in the pack is
    built on — the ratio of the two column means differs in the 4th decimal and is used
    nowhere). That %.3f spread is 44 mm of leg on a 1.85 m man — eleven times the ISO
    20685-1 height tolerance. A single-population leg gate is therefore not a tolerance, it
    is a bias, and this gate refuses to pretend otherwise when ancestry is absent.
    """ % (', '.join('%s %.4f' % (g, m) for g, m in ANCESTRY_LEG_MEANS_MALE), ANCESTRY_LEG_SPREAD)
    ref = reference()
    key = 'crotch_height_over_stature'
    x = sub.ratio(key)
    if x is None:
        return _result(UNMEASURABLE, 'crotch height not resolved on this mesh')
    groups = {}
    for g in ref.groups(sub.sex):
        b = ref.band(key, sub.sex, g)
        groups[g] = {
            'mean': b['mean'],
            'p5': b['lo'],
            'p95': b['hi'],
            'n': b['n'],
            'percentile_of_this_subject': round(ref.percentile(key, x, sub.sex, g), 2),
        }
    spread = max(g['mean'] for g in groups.values()) - min(g['mean'] for g in groups.values())
    mm_spread = spread * sub.stature_mm
    base = _band_check(sub, key)
    if sub.ancestry is None:
        return _result(
            WARN,
            'crotch/stature = %.5f but NO ANCESTRY IS DECLARED. Gated against '
            'the pooled US Army mixture, which is a bias and not a tolerance: '
            'the group means span %.4f (%.0f mm of leg at this stature) and '
            'this subject sits at p%.1f in one group and p%.1f in another.'
            % (
                x,
                spread,
                mm_spread,
                min(g['percentile_of_this_subject'] for g in groups.values()),
                max(g['percentile_of_this_subject'] for g in groups.values()),
            ),
            observed=x,
            band=base['band'],
            source=base.get('source'),
            per_group=groups,
            group_mean_spread=round(spread, 5),
            group_mean_spread_mm_at_this_stature=round(mm_spread, 1),
            pooled_result=base['status'],
        )
    return _result(
        base['status'],
        'ancestry %r declared; %s' % (sub.ancestry, base['explain']),
        observed=x,
        band=base['band'],
        source=base.get('source'),
        per_group=groups,
        group_mean_spread=round(spread, 5),
    )


def t2_ancestry_cormic(sub):
    """Cormic index against an ancestry-parameterised band — and why it cannot run here.

    Sitting height is not obtainable from a standing mesh. Deriving it would require
    assuming the cormic index, which is the quantity the gate exists to test, so no proxy
    is offered. This is the single component whose absence most weakens the joint
    plausibility check, and it is a real limitation of a standing-only pipeline.
    """
    ref = reference()
    key = 'sitting_height_over_stature'
    x = sub.ratio(key)
    m = sub.measurements['measurements'].get('sitting_height', {})
    groups = {g: ref.band(key, sub.sex, g)['mean'] for g in ref.groups(sub.sex)}
    spread = max(groups.values()) - min(groups.values())
    if x is None:
        return _result(
            UNMEASURABLE,
            'cormic index is not computable: %s' % (m.get('reason') or 'sitting height unmeasurable'),
            source='geom.anthro.measure UNMEASURABLE table',
            per_group_mean=groups,
            group_mean_spread=round(spread, 5),
            ancestry_declared=sub.ancestry is not None,
            ancestry_note='when this becomes measurable the same ancestry rule '
            'as the leg gate applies: the group means span %.4f' % spread,
        )
    return _band_check(sub, key)


def t2_child_growth(sub):
    """A declared child's SIZE against CDC 2000 stature-for-age and BMI-for-age.

    Size only. These curves constrain how big a 12-year-old is, not how a 12-year-old is
    proportioned; the proportion half of the child question is a separate gate, because
    passing stature-for-age is exactly what a scaled-down adult does.
    """
    ref = reference()
    age = sub.age_years
    if age is None:
        return _result(MISSING, 'no age declared, so no growth curve can be selected')
    if age >= 20.0:
        return _result(NOT_APPLICABLE, 'subject is %.1f y; CDC growth charts stop at 240 months' % age)
    months = age * 12.0
    rows = []
    try:
        z = ref.stature_z(sub.stature_mm / 10.0, months, sub.sex)
    except ValueError as e:
        return _result(NOT_APPLICABLE, str(e))
    st = FAIL if abs(z['z']) > CDC_Z_FAIL else WARN if abs(z['z']) > CDC_Z_WARN else PASS
    rows.append(
        _sub(
            'stature_for_age',
            st,
            'stature %.1f cm at %.1f y is z=%+.3f (p%.1f)' % (sub.stature_mm / 10.0, age, z['z'], z['percentile']),
            z=z['z'],
            percentile=z['percentile'],
            source=z['source'],
        )
    )
    bmi = sub.ratio('bmi')
    if bmi is None:
        rows.append(_sub('bmi_for_age', UNMEASURABLE, 'no BMI available'))
    else:
        b = ref.bmi_percentile(bmi, months, sub.sex)
        bst = WARN if abs(b['z']) > CDC_Z_WARN else PASS
        rows.append(
            _sub(
                'bmi_for_age',
                bst,
                'BMI %.2f at %.1f y is z=%+.3f (p%.1f)' % (bmi, age, b['z'], b['percentile']),
                z=b['z'],
                percentile=b['percentile'],
                caveat='this BMI is DERIVED from mesh volume times an ASSUMED '
                'uniform density; the CDC curves come from weighed '
                'children. The comparison is indicative and this '
                'sub-check may only warn.',
                cdc_caveat=b.get('caveat'),
            )
        )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '; '.join(r['explain'] for r in rows) + _skip_phrase(rows),
        source='CDC 2000 growth charts (NCHS), 24-240 months, public domain',
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def t2_child_proportions(sub):
    """The gate that catches an adult mesh scaled down.

    Stature-for-age cannot catch it — a scaled adult passes stature-for-age perfectly.
    What separates a child is the PROPORTION set: legs proportionally longer (12-year-old
    cormic .5057 measured vs adult .5218), a head near adult size on a smaller body, and
    distal-to-proximal growth leaving hands and feet proportionally large.

    Every comparison is against the CONVENTION-MATCHED adult — the stock anny body
    measured through this identical pipeline — not against a survey mean, because half the
    apparent difference between a bald mesh ratio and an over-hair survey ratio is the
    convention.
    """
    age = sub.age_years
    if age is None:
        return _result(MISSING, 'no age declared')
    if age >= ANSUR_AGE_MIN_Y:
        return _result(NOT_APPLICABLE, 'subject is %.1f y, not a child' % age)
    aref = adult_reference(sub.sex)
    aratios = aref['measurement']['ratios']
    rows = []
    for key, direction, why in CHILD_PROPORTION_ASSERTIONS:
        x, a = sub.ratio(key), (aratios.get(key) or {}).get('value')
        if x is None or a is None:
            rows.append(_sub(key, UNMEASURABLE, 'not measurable on child or reference'))
            continue
        rel = (x / a - 1.0) * 100.0
        ok = (x > a) if direction == 'above' else (x >= a)
        rows.append(
            _sub(
                key,
                PASS if ok else FAIL,
                'child %.5f vs convention-matched adult %.5f (%+.2f%%); required %s. %s' % (x, a, rel, direction, why),
                child=x,
                adult=a,
                relative_pct=round(rel, 3),
                required=direction,
            )
        )
    cor = CHILD_CORMIC.get(sub.sex)
    rows.append(
        _sub(
            'cormic_below_adult',
            UNMEASURABLE,
            'cormic index needs sitting height, which a standing mesh cannot '
            'give; measure.py refuses to infer it because inferring it assumes '
            'the answer. Reference for when it becomes measurable: 12 y %.4f '
            '(sd %.4f, n=%d) vs adult 25-45 y %.4f (n=%d).'
            % (cor['child_12y_mean'], cor['child_12y_sd'], cor['child_n'], cor['adult_25_45_mean'], cor['adult_n']),
            reference=cor,
            source=CHILD_CORMIC_SOURCE,
        )
    )
    rows.append(
        _sub(
            'shoulder_hip_is_not_a_child_test',
            REPORT,
            'biacromial/bicristal does NOT separate a 12-year-old boy (1.4285) '
            'from an adult man (1.4325), and neither breadth is measurable on '
            'this cage anyway, so no shoulder:hip assertion is made',
        )
    )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d child proportion assertions, %d failed%s'
        % (len(rows), sum(1 for r in rows if r['status'] == FAIL), _skip_phrase(rows)),
        source=CHILD_DIRECTION_SOURCE,
        adult_reference=aref['source'],
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def t2_adult_age_channel(sub):
    """Adult ageing is a GIRTH delta on an unchanged skeleton — checked in both directions.

    MEASURED on ANSUR: waist/stature rises with age at r=+0.40 (+8.7% from 25 to 43) while
    crotch/stature moves -0.47% and cormic -0.34% over the same span, against a population
    sd of 2.9%. So the girth ratios get an age-conditional expectation, and the skeletal
    ratios are deliberately gated against the AGE-POOLED band — conditioning them on age
    would import a signal the data says is not there.
    """
    age = sub.age_years
    if age is None:
        return _result(MISSING, 'no age declared')
    if not sub.is_ansur_age:
        return _result(
            NOT_APPLICABLE,
            'subject is %.1f y, outside the %g-%g y window the age model was '
            'fitted on' % (age, ANSUR_AGE_MIN_Y, ANSUR_AGE_MAX_Y),
        )
    rows = []
    for key, per_sex in AGE_CHANNEL['girth'].items():
        m = per_sex[sub.sex]
        x = sub.ratio(key)
        if x is None:
            rows.append(_sub(key, UNMEASURABLE, 'not measurable'))
            continue
        pred = m['intercept'] + m['slope_per_year'] * age
        half = 2.0 * m['resid_sd']
        dev = x - pred
        rows.append(
            _sub(
                key,
                PASS if abs(dev) <= half else WARN,
                '%.5f vs age-%.0f expectation %.5f (%+.5f, band +/-%.5f). Age '
                'explains little here (r=%.3f) so the band is wide by '
                'construction.' % (x, age, pred, dev, half, m['r']),
                observed=x,
                predicted=round(pred, 5),
                halfwidth=round(half, 5),
                r=m['r'],
                n=m['n'],
                channel='girth',
            )
        )
    for key, per_sex in AGE_CHANNEL['skeletal'].items():
        m = per_sex[sub.sex]
        x = sub.ratio(key)
        drift_18y = abs(m['slope_per_year']) * 18.0
        rel = drift_18y / m['pop_sd']
        pooled = _band_check(sub, key)
        rows.append(
            _sub(
                key,
                pooled['status'],
                'skeletal channel: the whole 25->43 age effect is %.5f = %.2f '
                'population SD (%.2f%% of the ratio), so this is gated against '
                'the AGE-POOLED band and not conditioned on age. %s'
                % (drift_18y, rel, 100.0 * drift_18y / max(abs(x or 1.0), 1e-9), pooled['explain']),
                observed=x,
                band=pooled['band'],
                age_effect_over_18y=round(drift_18y, 6),
                age_effect_in_population_sd=round(rel, 4),
                within_house_ceiling=bool(drift_18y / max(x or 1.0, 1e-9) <= SKELETAL_AGE_DRIFT_CEILING),
                channel='skeletal',
            )
        )
    pair = sub.spec.get('age_pair')
    # A NOTE about what the CALLER declared, not a check on this body: the pairwise test
    # needs a second mesh that does not exist, so it is not evidence either way and does
    # not drag the roll-up to 'not run'. It is still counted and printed.
    rows.append(
        _note(
            'age_pair_invariance',
            NOT_APPLICABLE if not pair else REPORT,
            'no age-pair sibling declared, so the direct test — same skeleton, '
            'two ages, skeletal ratios must move < %.1f%% while girth moves — '
            'cannot run on a single mesh. Declaring spec["age_pair"] enables it.' % (100 * SKELETAL_AGE_DRIFT_CEILING)
            if not pair
            else 'age pair %r declared' % pair,
            ceiling=SKELETAL_AGE_DRIFT_CEILING,
        )
    )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '%d age-channel checks%s' % (len(rows), _skip_phrase(rows)),
        source=AGE_CHANNEL_SOURCE,
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )


def t2_vhi_bmi(sub):
    """Volume-height index and BMI, each against a DECLARED band, with a logged override.

    VHI is the honest shape statistic here because no density assumption enters it — but
    for the same reason no survey publishes it, so no band for it can be derived from
    anything on disk and the caller must declare one. BMI can be compared to the pack, but
    the mesh BMI comes from volume times an assumed uniform density while the pack BMI
    comes from weighed subjects, so it may only warn.
    """
    rows = []
    vhi = sub.measurements['measurements'].get('volume_height_index', {}).get('value')
    band = sub.spec.get('vhi_band')
    override = sub.spec.get('vhi_override')
    if vhi is None:
        rows.append(_sub('vhi', UNMEASURABLE, 'no volume computed'))
    elif band is None:
        rows.append(
            _sub(
                'vhi',
                MISSING,
                'VHI = %.2f %s but no band is declared. No survey on disk '
                'publishes volume/stature^2, so this gate will not invent one — '
                'declare spec["vhi_band"] for the character type.' % (vhi, VHI_UNITS),
                observed=vhi,
            )
        )
    else:
        lo, hi = float(band[0]), float(band[1])
        inside = lo <= vhi <= hi
        if inside:
            rows.append(
                _sub(
                    'vhi',
                    PASS,
                    'VHI %.2f inside declared %.2f-%.2f %s' % (vhi, lo, hi, VHI_UNITS),
                    observed=vhi,
                    band=[lo, hi],
                )
            )
        elif override is not None:
            # `is not None`, not truthiness: an empty override dict is a caller trying to
            # wave the band away with nothing recorded, and that must raise, not fall
            # through to a plain failure that hides the attempt.
            if not override.get('reason'):
                raise GateConfigError(
                    'spec["vhi_override"] must carry a "reason"; an unexplained override '
                    'is indistinguishable from a silently widened band'
                )
            rows.append(
                _sub(
                    'vhi',
                    REPORT,
                    'VHI %.2f is OUTSIDE the declared %.2f-%.2f %s and was '
                    'OVERRIDDEN: %s' % (vhi, lo, hi, VHI_UNITS, override['reason']),
                    observed=vhi,
                    band=[lo, hi],
                    override=override,
                )
            )
        else:
            rows.append(
                _sub(
                    'vhi',
                    FAIL,
                    'VHI %.2f outside declared %.2f-%.2f %s' % (vhi, lo, hi, VHI_UNITS),
                    observed=vhi,
                    band=[lo, hi],
                )
            )
    r = _band_check(sub, 'bmi')
    rows.append(
        _sub(
            'bmi',
            WARN if r['status'] == FAIL else r['status'],
            r['explain'] + ' [downgraded: mesh BMI is derived from an assumed '
            'uniform density, the pack BMI is from weighed subjects]',
            observed=r['observed'],
            band=r['band'],
            **{k: v for k, v in (r.get('detail') or {}).items() if k in ('percentile', 'mean', 'sd')},
        )
    )
    status, rows = _roll_up(rows)
    return _result(
        status,
        '; '.join(r['explain'] for r in rows)[:400] + _skip_phrase(rows),
        source='VHI band is CALLER-DECLARED; BMI band is ANSUR II',
        checks=rows,
        roll_up=_roll_up_summary(rows),
    )
