# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The remaining rejection measures and the calibration/severity table engine.

Moved verbatim out of the old single-file gates.py (lines 3056-3362).
"""

from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.bands import (
    ANSUR_REFERENCE_POPULATION,
    BAND_WIDTH_BLOCK,
    CAL_DECLARED_BAND,
    CAL_EMPIRICAL_PERCENTILE,
    CAL_LMS_Z,
    CAL_PRINTED_BAND,
    CAL_RATIO_BANDS,
    CAL_STATURE_ANCHORED,
    CAL_STRUCTURAL,
    CAL_UNDECLARED,
    CAL_VIOLATION_RATE,
    HEIGHT_CHAIN_SOURCE,
    SEVERITY_POLICY,
    SEVERITY_POLICY_PROVENANCE,
    SEVERITY_POLICY_SOURCE,
    SEVERITY_REJECTION_CEILING,
    _gateable_bands,
)
from zyg_workflows.geom.anthro.gates.severity_reject import (
    _norm_sf2,
    _reject_empirical_percentile,
    _reject_ratio_bands,
    _reject_stature_anchored,
    _sample_unavailable_reason,
    ansur_sample,
)
from zyg_workflows.geom.anthro.gates.registry import GATES


def _reject_lms_z(spec):
    """A |z| cut on a CDC LMS curve. The LMS transform is standard-normal by construction,
    so the rejected fraction of the reference children is the normal tail exactly."""
    z = float(spec['z_fail'])
    rate = _norm_sf2(z)
    return {
        'kind': CAL_LMS_Z,
        'rate': rate,
        'basis': 'by_construction',
        'z_fail': z,
        'per_band_by_construction': rate,
        'cells': [],
        'reference_population': 'the CDC 2000 reference children (NCHS, US, 24-240 '
        'months) — NOT ANSUR, which has no children',
        'reference_n': None,
        'explain': (
            'blocks at |z| > %g. The CDC 2000 LMS transform is standard '
            'normal by construction, so this rejects %.3f%% of the reference '
            'children — the reference here is CDC, not ANSUR, because ANSUR '
            'has no children at all. %s' % (z, 100.0 * rate, spec.get('why') or '')
        ),
        'source': spec.get('source') or 'CDC 2000 growth charts (NCHS), LMS z',
    }


def _reject_violation_rate(spec):
    """A gate whose threshold record already carries a MEASURED per-subject violation rate.

    The rate must be the rate of THE WORST STEP THE GATE CAN FAIL ON, and this function
    derives it from the step table rather than accepting a number beside it, because
    accepting a number beside it is exactly how t1_girth_chain came to certify a blocking
    claim over an elbow step with the violation rate of a forearm step. A step that may
    only warn is reported here and excluded from the governing rate; a step that may block
    but carries no rate makes the whole rate None, which takes the block away.
    """
    steps = spec.get('steps')
    if steps:
        blocking = [s for s in steps if s.get('blocking', True)]
        warning = [s for s in steps if not s.get('blocking', True)]
        unevidenced = [s for s in blocking if s.get('violation_male') is None or s.get('violation_female') is None]
        if not blocking:
            rate = None
            why_rate = (
                'no step of this gate may block (every step lacks a survey '
                'analogue), so there is no rejection rate to report'
            )
        elif unevidenced:
            rate = None
            why_rate = (
                '%d blocking step(s) carry no measured violation rate (%s), so '
                'this gate cannot say how many real people it rejects'
                % (len(unevidenced), ', '.join(s['id'] for s in unevidenced))
            )
        else:
            rate = max(max(float(s['violation_male']), float(s['violation_female'])) for s in blocking)
            why_rate = (
                'MEASURED violation rate of the worst step this gate can FAIL on '
                '(%d fail-capable step(s): %s): %.4f%% of real subjects'
                % (len(blocking), ', '.join(s['id'] for s in blocking), 100.0 * rate)
            )
        warn_note = ''
        if warning:
            warn_note = '. %d step(s) may only WARN and are excluded from this rate: %s' % (
                len(warning),
                '; '.join(
                    '%s (no survey analogue; nearest analogue %s is '
                    'violated by %.4f%%/%.4f%%)'
                    % (
                        s['id'],
                        s.get('nearest_survey_pair') or 'none',
                        100.0 * (s.get('violation_male') or 0.0),
                        100.0 * (s.get('violation_female') or 0.0),
                    )
                    for s in warning
                ),
            )
        return {
            'kind': CAL_VIOLATION_RATE,
            'rate': rate,
            'basis': 'measured' if rate is not None else 'not_measured',
            'per_band_by_construction': None,
            'cells': [],
            'reference_population': ANSUR_REFERENCE_POPULATION,
            'reference_n': spec.get('n'),
            'steps_fail_capable': [s['id'] for s in blocking],
            'steps_warn_only': [s['id'] for s in warning],
            'explain': '%s. %s%s' % (why_rate, spec.get('why') or '', warn_note),
            'source': spec.get('source') or HEIGHT_CHAIN_SOURCE,
        }
    rate = float(spec['rate'])
    return {
        'kind': CAL_VIOLATION_RATE,
        'rate': rate,
        'basis': 'measured',
        'per_band_by_construction': None,
        'cells': [],
        'reference_population': ANSUR_REFERENCE_POPULATION,
        'reference_n': spec.get('n'),
        'steps_fail_capable': None,
        'steps_warn_only': None,
        'explain': (
            'MEASURED violation rate of the worst step this gate can fail on: '
            '%.4f%% of real subjects. %s' % (100.0 * rate, spec.get('why') or '')
        ),
        'source': spec.get('source') or HEIGHT_CHAIN_SOURCE,
    }


def calibrate_gate(gate):
    """The measured severity record for one gate: what it would reject, and therefore what
    severity it is allowed to carry."""
    spec = dict(gate.calibration or {'kind': CAL_UNDECLARED})
    kind = spec.get('kind')
    try:
        if kind == CAL_RATIO_BANDS:
            # Filter to the bands the gate can actually FAIL on before measuring, so the
            # printed "as configured this gate rejects X%" describes the gate as
            # configured and not a wider gate that does not exist.
            declared = spec.get('pairs') or spec['ratios']
            keys, excluded = _gateable_bands(declared, spec.get('policy'))
            rec = dict(_reject_ratio_bands(keys, spec.get('width', BAND_WIDTH_BLOCK)))
            rec['ratios_declared'] = [r[0] if isinstance(r, (tuple, list)) else r for r in declared]
            rec['ratios_excluded'] = excluded
            if excluded:
                rec['explain'] = rec[
                    'explain'
                ] + ' %d of the %d declared band(s) cannot FAIL and are excluded from this rate: %s.' % (
                    len(excluded),
                    len(rec['ratios_declared']),
                    '; '.join('%s (%s)' % (e['ratio'], e['why']) for e in excluded),
                )
        elif kind == CAL_STATURE_ANCHORED:
            rec = _reject_stature_anchored(spec['pairs'], spec['sigma'])
        elif kind == CAL_EMPIRICAL_PERCENTILE:
            rec = _reject_empirical_percentile(spec)
        elif kind == CAL_LMS_Z:
            rec = _reject_lms_z(spec)
        elif kind == CAL_VIOLATION_RATE:
            rec = _reject_violation_rate(spec)
        elif kind in (CAL_STRUCTURAL, CAL_DECLARED_BAND):
            rec = {
                'kind': kind,
                'rate': None,
                'basis': 'not_applicable',
                'cells': [],
                'per_band_by_construction': spec.get('per_band_by_construction'),
                'reference_n': spec.get('n'),
                'explain': spec.get('why'),
                'source': spec.get('source') or 'n/a — not a population claim',
            }
        elif kind == CAL_PRINTED_BAND:
            # A CANON number has no sample behind it, so there is NO rate to compute and
            # the policy below will take any blocking claim away. That downgrade is the
            # point of the kind: it is the machinery, not a reviewer, that stops a printed
            # drawing convention from failing a body.
            rec = {
                'kind': kind,
                'rate': None,
                'basis': 'no_population_behind_a_printed_number',
                'cells': [],
                'per_band_by_construction': None,
                'reference_n': None,
                'explain': spec.get('why'),
                'source': spec.get('source') or 'a printed anatomy reference',
            }
        else:
            rec = {
                'kind': CAL_UNDECLARED,
                'rate': None,
                'basis': 'not_measured',
                'cells': [],
                'per_band_by_construction': None,
                'reference_n': None,
                'explain': 'this gate declares no calibration, so no statement about '
                'how many real people it rejects exists',
                'source': None,
            }
    except Exception as e:  # noqa: BLE001
        # A calibration that cannot be computed must not become a silent pass to blocking.
        rec = {
            'kind': kind,
            'rate': None,
            'basis': 'error',
            'cells': [],
            'per_band_by_construction': None,
            'reference_n': None,
            'explain': 'calibration raised %s: %s' % (type(e).__name__, e),
            'source': None,
        }
    rec['gate'] = gate.id
    rec['severity_declared'] = gate.severity
    rec['policy'] = SEVERITY_POLICY
    rec['ceiling'] = SEVERITY_REJECTION_CEILING
    rec['spec'] = spec
    rec.setdefault('reference_population', None)
    rec.setdefault('cells', [])
    rec.setdefault('per_band_by_construction', None)
    # The granularity allowance: an empirical percentile on n subjects moves in steps of
    # 1/n, so a threshold defined AS a percentile lands within 1/n of its nominal rate.
    n = rec.get('reference_n')
    rec['granularity'] = (1.0 / n) if n else 0.0
    rec['ceiling_effective'] = SEVERITY_REJECTION_CEILING + rec['granularity']

    if rec['kind'] in (CAL_STRUCTURAL, CAL_DECLARED_BAND):
        rec['severity_effective'] = gate.severity
        rec['governs_severity'] = False
        rec['reason'] = (
            'kind=%s: not a statistical statement about a population, so the '
            'measured-rejection policy does not apply. %s' % (rec['kind'], spec.get('why') or '')
        )
    else:
        pop = rec.get('reference_population') or ANSUR_REFERENCE_POPULATION
        if gate.severity != 'block':
            rec['severity_effective'] = gate.severity
            rec['governs_severity'] = False
            rec['reason'] = (
                'declared %r, which the policy never raises — the policy only '
                'takes blocking claims away. Rate is reported for audit: %s'
                % (
                    gate.severity,
                    'not measured' if rec['rate'] is None else '%.3f%% of %s' % (100.0 * rec['rate'], pop),
                )
            )
        elif rec['rate'] is None:
            rec['severity_effective'] = 'warn'
            rec['governs_severity'] = True
            rec['reason'] = (
                'declared block, but no rejection rate against the reference '
                'sample could be produced (%s). A gate that cannot say how '
                'many real people it rejects may not block.' % rec['basis']
            )
        elif rec['rate'] <= rec['ceiling_effective']:
            rec['severity_effective'] = 'block'
            rec['governs_severity'] = True
            rec['reason'] = 'rejects %.3f%% of %s, within the %.1f%% ceiling%s, so it may block.' % (
                100.0 * rec['rate'],
                pop,
                100.0 * SEVERITY_REJECTION_CEILING,
                ''
                if not rec['granularity']
                else ' (+%.3f%% for the 1/n granularity of an empirical '
                'percentile on n=%d)' % (100.0 * rec['granularity'], n),
            )
        else:
            rec['severity_effective'] = 'warn'
            rec['governs_severity'] = True
            rec['reason'] = (
                'DOWNGRADED block -> warn: rejects %.2f%% of %s, %.1fx the '
                '%.1f%% ceiling (bar as applied, including the 1/n '
                'granularity of the governing cell: %.3f%%). A gate stricter '
                'than the population is a gate that rejects people who exist.'
                % (
                    100.0 * rec['rate'],
                    pop,
                    rec['rate'] / SEVERITY_REJECTION_CEILING,
                    100.0 * SEVERITY_REJECTION_CEILING,
                    100.0 * rec['ceiling_effective'],
                )
            )
    return rec


def calibrate(gates=None):
    """{gate_id: calibration record} for a registry. Cheap after the first call."""
    gates = tuple(GATES if gates is None else gates)
    return {g.id: calibrate_gate(g) for g in gates}


def severity_table(gates=None):
    """The auditable severity table: one row per gate, declared vs effective vs measured
    rejection rate. This is the artefact that makes rule 6 checkable by a human."""
    cal = calibrate(gates)
    rows = []
    for g in tuple(GATES if gates is None else gates):
        c = cal[g.id]
        rows.append(
            {
                'id': g.id,
                'tier': g.tier,
                'declared': c['severity_declared'],
                'effective': c['severity_effective'],
                'rejection_rate': c['rate'],
                'basis': c['basis'],
                'kind': c['kind'],
                'reference_population': c.get('reference_population'),
                'per_band_by_construction': c.get('per_band_by_construction'),
                'downgraded': c['severity_declared'] != c['severity_effective'],
                'reason': c['reason'],
                'explain': c.get('explain'),
            }
        )
    return {
        'policy': SEVERITY_POLICY,
        'policy_provenance': SEVERITY_POLICY_PROVENANCE,
        'policy_source': SEVERITY_POLICY_SOURCE,
        'ceiling': SEVERITY_REJECTION_CEILING,
        'reference': (ansur_sample() or {}).get('source')
        or ('microdata unavailable (%s); rates are by-construction bounds' % _sample_unavailable_reason()),
        'independent_bands_admission': {
            sex: reference().doc['mahalanobis']['sexes'][sex]['independent_bands_check'] for sex in ('male', 'female')
        },
        'rows': rows,
        'downgraded': [r['id'] for r in rows if r['downgraded']],
        'blocking': [r['id'] for r in rows if r['effective'] == 'block'],
        'gates': cal,
    }
