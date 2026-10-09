# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 4 — metadata, and the one bucket/count/name list.

Moved verbatim out of the old single-file gates.py (lines 5149-5543).
"""

from zyg_workflows.geom.anthro import measure as ME
from zyg_workflows.geom.anthro.reference import reference

from zyg_workflows.geom.anthro.gates.policy import (
    BUILD_TARGET_STATURE_TOL_MM,
    CANON,
    CANON_DEFINITION,
    CANON_VS_MEASURED_CONFLICT,
    DIURNAL_STATURE_RANGE_MM,
    FAIL,
    MEASURED,
    MEASURED_COVERAGE_SOURCE,
    MEASURED_EVIDENCE_CLASSES,
    MEASURED_NOT_COVERED_NOTE,
    MIN_ANTHROPOMETRIC_STATURE_TOL_MM,
    MISSING,
    PASS,
    PROVENANCE_RANK,
    REPORT,
    UNMEASURABLE,
    VALID_PROVENANCE,
    WITHDRAWN_EVIDENCE_CLASSES,
    _zyg_log,
    measured_covered,
    verify_measured_evidence,
)
from zyg_workflows.geom.anthro.gates.bands import (
    CANON_HEADS_TALL,
    CANON_SOURCE,
    STYLIZATION_AXIS,
    STYLIZATION_AXIS_NOTE,
)
from zyg_workflows.geom.anthro.gates.gate import RECEIPT_KEY, _result


# ---------------------------------------------------------------------------------
# TIER 4 — metadata
# ---------------------------------------------------------------------------------
REQUIRED_MEASUREMENT_FIELDS = ('kind', 'landmark', 'convention', 'provenance')
REQUIRED_META_FIELDS = (
    'pose',
    'axis_convention',
    'units',
    'girth_convention',
    'iso_caveat',
    'vertex_scope',
    'coco_source',
)


def t4_measurement_provenance(sub):
    """Every measurement must carry landmark + convention + provenance, and every absent
    value must carry a reason. A measurement that cannot state all four cannot legitimately
    be compared to a survey band, so an incomplete manifest is a blocking defect in the
    report itself rather than a cosmetic one."""
    M = sub.measurements['measurements']
    meta = sub.measurements['meta']
    missing_fields, missing_reason = [], []
    for k, r in sorted(M.items()):
        for f in REQUIRED_MEASUREMENT_FIELDS:
            if r.get(f) in (None, ''):
                missing_fields.append('%s.%s' % (k, f))
        if r.get('value_mm') is None and r.get('value') is None and not r.get('reason'):
            missing_reason.append(k)
    missing_meta = [f for f in REQUIRED_META_FIELDS if not meta.get(f)]
    bad = missing_fields + missing_reason + missing_meta
    prov = {}
    for r in M.values():
        prov[r.get('provenance')] = prov.get(r.get('provenance'), 0) + 1
    return _result(
        PASS if not bad else FAIL,
        '%d measurements: %s. %d missing a required field, %d None without a '
        'reason, %d meta fields absent'
        % (
            len(M),
            ', '.join('%s=%d' % kv for kv in sorted(prov.items())),
            len(missing_fields),
            len(missing_reason),
            len(missing_meta),
        ),
        observed=prov,
        source='geom.anthro.measure record contract',
        missing_fields=missing_fields[:20],
        none_without_reason=missing_reason,
        missing_meta=missing_meta,
    )


# ---------------------------------------------------------------------------------
# ONE BUCKET, ONE COUNT, ONE NAME LIST (re-review NEW-3).
#
# The MEASURED census sentence used to compute each clause's count from its own
# expression and then append ONE name list — `measured_bad + measured_unresolved` — to the
# LAST clause, whichever bucket the names actually belonged to. Shipped text, all five
# bodies:
#
#     ... 0 UNRESOLVED for other reasons, 0 NAMING A SURVEY THE PACK DOES NOT CONTAIN OR
#     DOES NOT ANSWER: t1_landmark_ordering_hard, t1_landmark_ordering_soft,
#     t1_girth_chain, t3_cast_diversity
#
# A count of 0 followed by four names, and those four belong to the COVERAGE-NOT-VERIFIED
# bucket two clauses earlier. The JSON key was right; the sentence a human reads was
# self-contradictory — failure shape (b), evidence computed and then surfaced under the
# wrong heading, which is worse than not surfacing it because it reads as a denial.
#
# The fix is structural, not careful. A bucket is (names, text); the count is len(names)
# rendered at the same moment as the names, so there is no second expression for it to
# disagree with. Buckets join with '; ' because names inside a bucket join with ', '.
CENSUS_BUCKET_RULE = (
    'each MEASURED census bucket renders as "<len(names)> <text>: <names>" from ONE list, '
    'so the count and the name list cannot disagree; buckets are separated by "; " and '
    'names within a bucket by ", ". The buckets (MEASURED_CENSUS_BUCKETS) partition the '
    'MEASURED gates and the sentence says so out loud if they do not sum (re-review '
    'NEW-3). No count in this file is written out as a word: that is what put "the five '
    'gates" next to a list of four.'
)

# The ONE place a bucket's key and its printed wording are paired. The census renders from
# this table and `_selftest_census_buckets` rebuilds from the same table, so re-wording a
# clause cannot make the self-test disagree with the sentence for a cosmetic reason — only
# for the real one, a name printed under a count that does not own it.
MEASURED_CENSUS_BUCKETS = (
    ('resolved_and_answered', 'resolved against the pack on disk AND answered by it'),
    ('externally_sourced', 'externally sourced and censused as such'),
    (
        'coverage_not_verified',
        'whose source key resolves but whose COVERAGE IS NOT VERIFIED (the gate names no '
        'quantity, so nothing here can say the pack answers it — this is not a pass)',
    ),
    ('unresolved_other', 'UNRESOLVED for other reasons'),
    ('survey_absent_or_silent', 'NAMING A SURVEY THE PACK DOES NOT CONTAIN OR DOES NOT ANSWER'),
)


def _census_bucket(names, text):
    """'<n> <text>[: a, b, c]', with n == len(names) by construction."""
    names = list(names)
    return '%d %s%s' % (len(names), text, (': ' + ', '.join(names)) if names else '')


def t4_threshold_provenance(sub, gates=None):
    """A census of the thresholds this run is about to apply.

    The refusal itself happens in validate_registry() before any geometry is touched; this
    gate is the visible receipt of it.

    TWO censuses, not one. CANON rows are checked against the coverage list (a book may
    not gate what a survey answers); MEASURED rows are checked against THEIR OWN EVIDENCE
    (a gate may not claim a survey it cannot produce). The second census was added
    2026-08-06 because the first one was bypassable by typing the word MEASURED — see
    MEASURED_EVIDENCE_CLASSES. A pack-backed evidence record that does not resolve is a
    FAIL; a pack that cannot be read at all makes this gate UNMEASURABLE, never a pass.
    """
    # Deferred: the registry is built FROM this gate, so the edge to it cannot be a
    # module-level import.
    from zyg_workflows.geom.anthro.gates.registry import GATES

    gates = gates if gates is not None else GATES
    census = {}
    untagged = []
    canon_rows = []
    for g in gates:
        tag = g.provenance or 'no_threshold_shipped'
        census[tag] = census.get(tag, 0) + 1
        if g.threshold is not None and g.provenance not in VALID_PROVENANCE:
            untagged.append(g.id)

    # -- THE MEASURED CENSUS -------------------------------------------------------
    # Three outcomes, not two, since 2026-08-06 (re-review R2, hole b). A pack-backed
    # record can now fail in a way the previous version could not see: the source key
    # resolves and the pack does not answer the question. And it can be UNVERIFIABLE — the
    # key resolves, the gate declares no quantities, so nothing here can say whether the
    # survey speaks to it. That third bucket used to be counted as "resolved".
    measured_rows, measured_bad = [], []
    measured_unresolved, measured_coverage_unverified = [], []
    for g in gates:
        if g.provenance != MEASURED:
            continue
        ok, rec = verify_measured_evidence(g, live=True)
        measured_rows.append(rec)
        if ok is False:
            measured_bad.append(rec)
        elif ok is None:
            measured_unresolved.append(rec)
            if rec.get('unresolved_because') == 'coverage_not_verifiable':
                measured_coverage_unverified.append(rec)

    # THE CANON CROSS-CHECK. validate_registry() refuses a CANON block against the STATIC
    # snapshot of surveyed quantities; this is where the snapshot is checked against the
    # pack as it exists on disk today. If the pack has grown a quantity the snapshot does
    # not know about and a CANON gate is gating that quantity at anything above 'report',
    # the refusal did not fire and this gate FAILS — a drift in the pack must not quietly
    # hand a drawing convention authority over a survey.
    covered, how = measured_covered()
    drift = []
    for g in gates:
        if g.provenance != CANON:
            continue
        qs = list(g.quantities or ())
        clash = sorted(q for q in qs if q in covered)
        row = {'gate': g.id, 'severity_declared': g.severity, 'quantities': qs, 'measured_source_exists_for': clash}
        canon_rows.append(row)
        if clash and g.severity in ('block', 'warn'):
            drift.append(row)

    external_rows = [r for r in measured_rows if not r['pack_backed']]
    other_unresolved = [r for r in measured_unresolved if r.get('unresolved_because') != 'coverage_not_verifiable']
    _accounted = set(id(r) for r in external_rows + measured_unresolved + measured_bad)
    resolved_rows = [r for r in measured_rows if id(r) not in _accounted]
    # A gate whose evidence could not be resolved has not been verified. Under rule 4 that
    # is UNMEASURABLE with the evidence attached — not a pass, and not a FAIL either,
    # because "the pack would not open" is not the same finding as "the named survey is
    # not there". THE COVERAGE BUCKET LANDS HERE TOO, and it is meant to: a census that
    # has verified the existence of a survey but not that the survey answers the question
    # has not verified the claim it prints, and this file's own rule 4 says such a gate
    # says so instead of passing. It costs this gate its PASS on every body until the
    # gates named in `measured_evidence_coverage_unverified` declare `quantities`; that is
    # the correct direction of pressure and the fix is one tuple per gate. (The count is
    # deliberately not written out here: this comment said "the five gates" while the list
    # held four, which was half of re-review NEW-3.)
    if measured_bad:
        st = FAIL
    elif measured_unresolved:
        st = UNMEASURABLE
    elif untagged or drift:
        st = FAIL
    else:
        st = PASS
    # ONE list per bucket, and the count printed in front of it is len() of THAT list —
    # so a count and a name list cannot disagree, which is what NEW-3 was. Buckets are
    # joined with '; ' because the names inside a bucket are joined with ', '.
    bucket_names = {
        'resolved_and_answered': [r['gate'] for r in resolved_rows],
        'externally_sourced': [r['gate'] for r in external_rows],
        'coverage_not_verified': [r['gate'] for r in measured_coverage_unverified],
        'unresolved_other': [r['gate'] for r in other_unresolved],
        'survey_absent_or_silent': [r['gate'] for r in measured_bad],
    }
    measured_sentence = '; '.join(_census_bucket(bucket_names[k], t) for k, t in MEASURED_CENSUS_BUCKETS)
    n_bucketed = sum(len(v) for v in bucket_names.values())
    if n_bucketed != len(measured_rows):
        # Arithmetic that does not close is reported, never rounded away.
        measured_sentence += (
            '; BUCKET ARITHMETIC DOES NOT CLOSE: the %d buckets above '
            'account for %d rows against %d MEASURED gates'
            % (len(MEASURED_CENSUS_BUCKETS), n_bucketed, len(measured_rows))
        )
    return _result(
        st,
        'gates by threshold provenance: %s; %d contested or untagged; %d CANON '
        'gate(s), %d of them on a quantity a survey already answers%s. %d '
        'MEASURED gate(s) — %s'
        % (
            ', '.join('%s=%d' % kv for kv in sorted(census.items())),
            len(untagged),
            len(canon_rows),
            len([r for r in canon_rows if r['measured_source_exists_for']]),
            ''
            if not drift
            else ' — AND %d of those gate it above "report": %s' % (len(drift), ', '.join(r['gate'] for r in drift)),
            len(measured_rows),
            measured_sentence,
        ),
        observed=census,
        source='geom.anthro.gates.validate_registry',
        untagged=untagged,
        measured_census_buckets=bucket_names,
        measured_census_rule=CENSUS_BUCKET_RULE,
        **{
            RECEIPT_KEY: 'this row IS the census. It prints in the text report '
            'whatever its status, because a provenance receipt that '
            'is only readable when the refusal machinery failed is '
            'not a receipt (re-review N3).'
        },
        provenance_rank=dict(PROVENANCE_RANK),
        canon_definition=CANON_DEFINITION,
        canon_vs_measured_conflict=CANON_VS_MEASURED_CONFLICT,
        canon_gates=canon_rows,
        canon_policy_violations=drift,
        measured_gates=measured_rows,
        measured_evidence_unverified=measured_bad,
        measured_evidence_unresolved=measured_unresolved,
        measured_evidence_coverage_unverified=[r['gate'] for r in measured_coverage_unverified],
        measured_evidence_classes={k: v['what'] for k, v in sorted(MEASURED_EVIDENCE_CLASSES.items())},
        withdrawn_evidence_classes=dict(WITHDRAWN_EVIDENCE_CLASSES),
        measured_coverage=how,
        measured_coverage_source=MEASURED_COVERAGE_SOURCE,
        measured_not_covered_note=MEASURED_NOT_COVERED_NOTE,
        n_measured_covered_quantities=len(covered),
        refusal='validate_registry() raises GateConfigError on any CONTESTED '
        'or untagged threshold; on any CANON threshold that claims '
        'block severity over a quantity ANSUR/CDC/NHANES answers; on '
        'any MEASURED threshold that CITES A CANON BOOK (page marker or '
        'not — the page-only test was bypassable by deleting "p.") or '
        'which names no evidence class at all; and on any MEASURED '
        'threshold at block severity whose pack evidence answers none '
        'of the quantities it names — all before a mesh is loaded',
    )


def t4_stylization_axis(sub):
    """Is the stylization axis a RECORDED DECISION or a default nobody chose?

    The target is plausible-plus-a-recorded-delta, and the delta has a name: anny's
    BodyProportions macro. What the pipeline stores today is the resulting slider value
    with no record of intent, so a character sitting at 0.5 is indistinguishable from a
    character whose builder never thought about it. MISSING is the correct answer to that,
    and it is the useful one.
    """
    phen = sub.spec.get('phenotype') or {}
    value = phen.get(STYLIZATION_AXIS)
    declared = sub.spec.get('stylization')
    if declared is None:
        return _result(
            MISSING,
            'BodyProportions is at %s but no stylization record exists, so '
            'there is no way to tell a chosen value from a default. Record '
            'spec["stylization"] = {"axis": %r, "value": <v>, "intent": ..., '
            '"declared_by": ..., "date": ...} at build time.' % (value, STYLIZATION_AXIS),
            observed=value,
            source='registry params.json phenotype',
            note=STYLIZATION_AXIS_NOTE,
            looks_defaulted=bool(value is not None and abs(value - 0.5) < 1e-9),
        )
    dv = declared.get('value')
    if dv is None or value is None or abs(float(dv) - float(value)) > 1e-9:
        return _result(
            FAIL,
            'the stylization record declares %r = %r but the built phenotype '
            'carries %r' % (STYLIZATION_AXIS, dv, value),
            observed=value,
            band=[dv, dv],
            source='spec["stylization"]',
        )
    return _result(
        PASS,
        'stylization axis %r recorded as %.4f (%s)'
        % (STYLIZATION_AXIS, float(value), declared.get('intent', 'no intent text')),
        observed=value,
        source='spec["stylization"]',
        record=declared,
    )


def t4_canon_and_percentiles(sub):
    """Non-blocking REPORTING: where this body sits in the distribution, and how far it is
    from the 8-head drawing canon.

    Neither number is a target. The canon is an art convention with no survey source and
    is emitted only so that stylization is a number an operator can read instead of a
    feeling. The percentiles come with the reminder that stacking them is meaningless: a
    p95-stature man averages p62 waist and p53 head breadth, so there is no nth-percentile
    person to aim at.
    """
    ref = reference()
    hh = sub.mm('head_height_vertex_menton')
    heads = None if not hh else sub.stature_mm / hh
    pcts = {}
    for k in sorted(sub.measurements['ratios']):
        x = sub.ratio(k)
        if x is None or k not in ref.doc['ratios']:
            continue
        try:
            pcts[k] = round(ref.percentile(k, x, sub.sex, sub.ancestry), 2)
        except KeyError as _exc:
            _zyg_log.debug('ratio %s has no percentile reference: %s', k, _exc)
            continue
    extremes = sorted(pcts.items(), key=lambda kv: min(kv[1], 100.0 - kv[1]))[:6]
    return _result(
        REPORT,
        'heads tall = %s (canon %.1f, delta %s); %d ratios placed, most '
        'extreme: %s'
        % (
            '%.3f' % heads if heads else 'n/a',
            CANON_HEADS_TALL,
            '%+.3f' % (heads - CANON_HEADS_TALL) if heads else 'n/a',
            len(pcts),
            ', '.join('%s p%.1f' % (k, v) for k, v in extremes),
        ),
        observed={
            'heads_tall': None if heads is None else round(heads, 4),
            'canon_delta_heads': None if heads is None else round(heads - CANON_HEADS_TALL, 4),
        },
        source=CANON_SOURCE,
        percentiles=pcts,
        percentile_caveat='these are MARGINAL positions. Do not stack them: a '
        'p95-stature man averages about p62 waist and p53 '
        'head breadth, so the nth-percentile person does not '
        'exist.',
        ancestry_declared=sub.ancestry is not None,
    )


def t4_tolerance_sanity(sub):
    """Refuse a per-mesh stature tolerance that is smaller than the subject's own daily
    variation, when the claim being made is anthropometric.

    A real person's stature changes %.1f-%.1f mm between morning and night. A per-mesh
    "anthropometric accuracy of 4 mm" is therefore a claim about nothing. The same 4 mm
    checked against a DECLARED BUILD TARGET is a perfectly good claim about a solver, so
    the gate keys off what is being claimed rather than off the number.
    """ % DIURNAL_STATURE_RANGE_MM
    tol = float(sub.spec.get('stature_tolerance_mm', BUILD_TARGET_STATURE_TOL_MM))
    claim = sub.spec.get('stature_claim', 'build_target')
    iso = reference().doc['iso_20685_1_table4_mm']
    common = dict(
        claim=claim,
        tolerance_mm=tol,
        diurnal_stature_range_mm=list(DIURNAL_STATURE_RANGE_MM),
        iso_20685_1_table4_mm=iso,
        iso_caveat=ME.ISO_CAVEAT,
    )
    if claim == 'anthropometric':
        ok = tol >= MIN_ANTHROPOMETRIC_STATURE_TOL_MM
        return _result(
            PASS if ok else FAIL,
            'stature tolerance %.1f mm is claimed as ANTHROPOMETRIC; the floor '
            'is %.1f mm because a real person varies %.1f-%.1f mm over one day'
            % ((tol, MIN_ANTHROPOMETRIC_STATURE_TOL_MM) + DIURNAL_STATURE_RANGE_MM),
            observed=tol,
            band=[MIN_ANTHROPOMETRIC_STATURE_TOL_MM, None],
            source='HOUSE floor derived from the MEASURED diurnal range',
            **common,
        )
    return _result(
        PASS,
        'stature tolerance %.1f mm is claimed as a BUILD-TARGET check, which '
        'is a claim about the height solver and not about anthropometric '
        'accuracy, so the %.1f mm diurnal floor does not apply' % (tol, MIN_ANTHROPOMETRIC_STATURE_TOL_MM),
        observed=tol,
        band=[0.0, None],
        source='HOUSE policy: build-target and anthropometric claims are different claims and carry different floors',
        **common,
    )
