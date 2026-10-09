# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""TIER 5 — pose, digit, angle, relief and canon gates.

Moved verbatim out of the old single-file gates.py (lines 5961-6547).
"""

from zyg_workflows.geom.anthro.gates.policy import (
    CANON_DEFINITION,
    CANON_VS_MEASURED_CONFLICT,
    ERROR,
    FAIL,
    NOT_APPLICABLE,
    NOT_IMPLEMENTABLE,
    PASS,
    REPORT,
)
from zyg_workflows.geom.anthro.gates.gate import RECEIPT_KEY, _result
from zyg_workflows.geom.anthro.gates.subject import (
    DECLARED_CLAIM_CONTRACT,
    UNEVALUATED_CLAIM,
    _ROLL_UP_ORDER,
    _claim_rollup,
)
from zyg_workflows.geom.anthro.gates.tier5_form import _HAND_STATUS, _t5_payload, _xlate, form_module


# -- pose limits -------------------------------------------------------------------
# AFS p.16's printed transverse-tilt floor, MIRRORED here so that building the registry
# never requires importing a tier-5 module (the same rule _bands() follows for the
# reference pack). _pose_gate compares the mirror against
# pose_limits.TRANSVERSE_TILT_STDEV_MIN_DEG on every run and returns ERROR if they have
# drifted apart, because a mirror nobody checks is how a report ends up printing a band
# that is not the band that was enforced.
PL_STIFFNESS_FLOOR_DEG = 2.0


def _pose_gate(pose_gate_id):
    """Adapt one rolled-up pose_layer() record.

    Reads ONLY keys the module's published contract guarantees (POSE_LAYER_GATE_KEYS,
    verified on every pose_layer() call). The predecessor of this function read
    `n_violating`/`violating` off a dict that returned neither, and rendered a 100 %-
    violating pose library as "ROM-violating None" (D1 / F2). Nothing here re-derives a
    number: every figure below is lifted from the record that produced it.
    """

    def fn(sub):
        payload, bail = _t5_payload(sub, 'pose_limits', pose_gate_id)
        if bail is not None:
            return bail
        PL, _ = form_module('pose_limits')
        # The registry MIRRORS the module's printed floor so the registry can be built
        # without importing a tier-5 module. A mirror that has drifted from the thing it
        # mirrors is a silently wrong band, so it is compared here rather than trusted.
        if pose_gate_id == 't5_pose_stiffness':
            got = getattr(PL, 'TRANSVERSE_TILT_STDEV_MIN_DEG', None)
            if got != PL_STIFFNESS_FLOOR_DEG:
                return _result(
                    ERROR,
                    "the registry mirrors AFS p.16's transverse-tilt floor as "
                    '%r but geom.pose_limits.TRANSVERSE_TILT_STDEV_MIN_DEG is '
                    '%r. The band in the report would not be the band that was '
                    'enforced, which is the defect this whole tier exists to '
                    'prevent.' % (PL_STIFFNESS_FLOOR_DEG, got),
                    observed=got,
                    band=[PL_STIFFNESS_FLOOR_DEG, None],
                )
        row = (payload.get('gate_index') or {}).get(pose_gate_id)
        if row is None:
            return _result(
                ERROR,
                'geom.pose_limits.pose_layer returned no gate %r; it '
                'returned %s' % (pose_gate_id, sorted(payload.get('gate_index') or {})),
            )
        st, why = _xlate(row.get('status'), PL.GATES_STATUS_MAP, 'geom.pose_limits.%s' % pose_gate_id)
        # -- WHOSE LIBRARY NUMBERS ARE THESE? (re-review R3) ------------------------
        # `payload['library']` is ONE shared block: the pose-library read, plus the ROM
        # census, which is t5_joint_rom's subject and nobody else's. This adapter used to
        # copy library_n_violating / library_violation_rate onto EVERY pose gate from that
        # shared block, so t5_joint_rom's 44/44 ROM violation rate was stamped onto four
        # gates that never measured it — two of them PASS rows, and three of them saying
        # `library_subject = "not applicable"` in the same dict. geom/pose_limits.py states
        # the rule that was being broken, verbatim: "every gate's library numbers are the
        # ones ITS OWN subject produced. Attaching the ROM violation rate to
        # t5_elbow_owner, whose subject is the rig skinning, would be a different
        # dishonesty from hiding it." And t5_pose_stiffness's registry note shipped the
        # claim that the rate "is not attached here" on a row that carried it.
        #
        # So the numbers are now taken from `row['observed']` — the per-gate dict
        # pose_limits builds for THIS gate — and never from the shared block. Only the two
        # facts about the READ itself (which asset, under which policy) come from the
        # shared block, and only for a gate that declares the library as a subject at all.
        # A gate that does not declare it carries the module's own words saying so instead
        # of a number it did not produce.
        lib = payload.get('library') or {}
        row_obs = row.get('observed') if isinstance(row.get('observed'), dict) else {}
        declares_library = 'library' in (row.get('subjects_declared') or ())
        lib_fields = {
            'library_numbers_rule': "every field below was produced by THIS gate's own subject. The "
            'ROM violation rate belongs to t5_joint_rom and appears on no other '
            'row; a gate that does not claim the pose library carries '
            'library_subject instead of a number.'
        }
        if pose_gate_id == 't5_pose_stiffness':
            # N3: the five statistics AFS asks for are this gate's deliverable, so they
            # print beside the row whatever the verdict is. A pose-diversity statistic
            # that only becomes readable when it fails is not a published statistic.
            lib_fields[RECEIPT_KEY] = (
                "the transverse-tilt statistics are this gate's deliverable, not the "
                'workings behind a verdict, so they print in the text report on a pass as '
                'well as on a failure.'
            )
        if declares_library:
            lib_fields.update(
                {
                    'library_char_asset': lib.get('char_asset'),
                    'library_policy': lib.get('policy'),
                    'library_n_poses': row_obs.get('n_poses'),
                    'library_complete': row_obs.get('library_complete'),
                }
            )
            # ROM counts, if and only if this gate's own subject produced them.
            for src_key, out_key in (
                ('n_violating', 'library_n_violating'),
                ('n_warning', 'library_n_warning'),
                ('violation_rate', 'library_violation_rate'),
                ('worst_check', 'library_worst_check'),
            ):
                if src_key in row_obs:
                    lib_fields[out_key] = row_obs[src_key]
        else:
            lib_fields['library_subject'] = (
                row_obs.get('library_subject') or 'not applicable: this gate does not claim the fitted pose library'
            )
        return _result(
            st,
            why or (row.get('explain') or 'no explanation supplied'),
            observed=row.get('observed'),
            band=row.get('band'),
            source=row.get('source'),
            module_provenance=row.get('provenance'),
            # The two-subject audit trail, per gate. `subjects_declared` vs
            # `subjects_evaluated` is the fact that made the old rest-only pass
            # look earned: a reader can now see that half of what the gate
            # claims to gate was never looked at, or that it was.
            subject_declared=row.get('subject_declared'),
            subjects_declared=row.get('subjects_declared'),
            subjects_evaluated=row.get('subjects_evaluated'),
            subject_not_evaluated=row.get('subject_not_evaluated'),
            subject_not_applicable=row.get('subject_not_applicable'),
            rest_only_status=row.get('rest_only_status'),
            library_only_status=row.get('library_only_status'),
            **lib_fields,
            rollup_rule=payload.get('rollup_rule'),
            rest_geometry=payload.get('rest_geometry'),
            # 'rest_record' is dropped and only dropped: it is the same record
            # as 'rest' with the status/band/source fields this row already
            # carries at top level, and copying it doubles the artefact. Nothing
            # in it is unique.
            detail_from_module={k: v for k, v in (row.get('detail') or {}).items() if k != 'rest_record'},
        )

    fn.__name__ = pose_gate_id
    return fn


# -- hands / digits ----------------------------------------------------------------
def _digit_gate(predicate):
    def fn(sub):
        payload, bail = _t5_payload(sub, 'hands', 't5_' + predicate)
        if bail is not None:
            return bail
        if payload.get('disabled'):
            return _result(
                NOT_APPLICABLE,
                payload.get('why') or 'module flag off',
                observed=None,
                source='geom.form.hands rollback flag',
                rollback_flag=(payload.get('rollback_flag') or {}).get('name'),
            )
        rows = {}
        for side, block in sorted((payload.get('sides') or {}).items()):
            r = (block or {}).get(predicate)
            if r is not None:
                rows[side] = r
        if not rows:
            return _result(ERROR, 'geom.form.hands.check_digits returned no %r record' % predicate)
        # D9: the roll-up used to SEED `worst` with PASS and keep the minimum under
        # _ROLL_UP_ORDER, where REPORT sorted BELOW PASS — so a hand predicate returning
        # 'report', a status _HAND_STATUS explicitly maps, would have left the gate reading
        # PASS. The seed is gone (2026-08-06, first pass) and REPORT now ranks with the
        # non-verdicts rather than above PASS (2026-08-06, re-review D9), so both halves of
        # that defect are closed: the roll-up is taken over the statuses actually produced,
        # and an unknown status ranks as ERROR rather than as better-than-everything.
        statuses, why = [], None
        for side, r in sorted(rows.items()):
            st, w = _xlate(r.get('status'), _HAND_STATUS, 'geom.form.hands.%s[%s]' % (predicate, side))
            if w:
                why = w
            statuses.append(st)
        worst = min(statuses, key=lambda s: _ROLL_UP_ORDER.get(s, _ROLL_UP_ORDER[ERROR]))
        any_row = rows[sorted(rows)[0]]
        return _result(
            worst,
            why
            or (
                '%s: %s'
                % (' / '.join('%s %s' % (s, rows[s].get('status')) for s in sorted(rows)), any_row.get('explain') or '')
            ).strip(),
            observed={s: rows[s].get('observed') for s in sorted(rows)},
            band=any_row.get('band'),
            source=any_row.get('source'),
            per_side=rows,
            module_provenance=any_row.get('provenance'),
        )

    fn.__name__ = 't5_' + predicate
    return fn


# -- angles ------------------------------------------------------------------------
def _angle_gate(angle_key):
    def fn(sub):
        payload, bail = _t5_payload(sub, 'angles', 't5_' + angle_key)
        if bail is not None:
            return bail
        AN, _ = form_module('angles')
        rec = payload.get(angle_key)
        if not isinstance(rec, dict):
            return _result(ERROR, 'geom.form.angles.measure_angles returned no %r record' % angle_key)
        spec = (AN.BANDS or {}).get(angle_key) or {}
        if not rec.get('resolved'):
            return _result(
                NOT_IMPLEMENTABLE,
                'UNRESOLVED on this rig: %s' % (rec.get('reason') or 'no reason recorded'),
                observed=None,
                band=None,
                source=spec.get('source'),
                quantity=spec.get('quantity'),
                evidence=rec,
            )
        verdict = rec.get('band_verdict')
        band = rec.get('band_applied')
        # angles.py's own verdict vocabulary, mapped by table. 'no_applicable_band' is a
        # REPORT and not a pass: the angle was measured and no printed band covers this
        # subject's sex or age, which is a statement about the book and not about the body.
        # An unmapped verdict becomes ERROR, never PASS.
        st = {
            'in_band': PASS,
            'above_band': FAIL,
            'below_band': FAIL,
            'no_applicable_band': REPORT,
            'unresolved': NOT_IMPLEMENTABLE,
        }.get(str(verdict))
        if st is None:
            return _result(
                ERROR,
                'geom.form.angles returned band_verdict %r for %s, which this '
                'file has no mapping for. Unmapped is recorded as ERROR, never '
                'as pass.' % (verdict, angle_key),
                observed=rec.get('value_deg'),
                band=band,
                source=spec.get('source'),
            )
        extra = {}
        if angle_key == 'canthal_tilt':
            st, verdict, extra = _canthal_verdict(rec)
        return _result(
            st,
            '%.4f deg, band %s (%s) -> %s. %s'
            % (rec['value_deg'], band, rec.get('band_applies'), verdict, rec.get('claim') or ''),
            observed=rec['value_deg'],
            band=band,
            source=spec.get('source'),
            quantity=spec.get('quantity'),
            operationalisation_spread_deg=rec.get('operationalisation_spread_deg'),
            evidence={k: rec[k] for k in sorted(rec) if k not in ('evidence',)},
            **extra,
        )

    fn.__name__ = 't5_' + angle_key
    return fn


# HeadNeck p.43 prints TWO claims on one line for the canthal tilt — a SIGN (the lateral
# canthus sits above the medial) and a CEILING (+10 deg) — and it prints them as ONE
# ONE-SIDED RULE: slightly positive, and not beyond +10.
#
# THE DEFECT THIS CLOSES (calibration finding 1). The adapter used to discard the module's
# own correctly-computed `band_verdict` and score the gate off `ceiling_verdict` alone,
# which angles.py computes as max(|tilt|) <= ceiling. The band that SHIPPED in the report
# was [0, +10]; the band that was ENFORCED was [-10, +10] — twice as wide, on the side the
# page rules out. Two measured consequences:
#   * the anny-neutral CONTROL reads -0.108 deg, is `below_band` by its own module, and
#     shipped as PASS with classification 'ok';
#   * a body with an unambiguous, RESOLVED -9.9 deg tilt — the exact slant the page
#     excludes — also passed. Reproduced against the shipped adapter before the fix.
# The widening was precisely what the control needed to pass, which is rule 3's cardinal
# sin.
#
# WHAT IS ENFORCED NOW. The two claims are scored separately and rolled up worst-first
# through _claim_rollup, which is _ROLL_UP_ORDER — the same arithmetic every other roll-up
# in this file uses:
#   CEILING   |tilt| > 10          -> FAIL. Two-sided by definition and always scored.
#   SIGN      resolved NEGATIVE    -> FAIL. This is the half that was being thrown away.
#             resolved POSITIVE    -> pass.
#             UNRESOLVED           -> NOT_IMPLEMENTABLE, which cannot be outranked by the
#                                    ceiling claim that did pass.
#
# THE STATUS OF THE UNRESOLVED-SIGN CASE CHANGED ON 2026-08-06 (re-review N2), FROM PASS
# TO NOT_IMPLEMENTABLE. The reasoning behind the old PASS was half right and the half that
# was right is kept: on the neutral the two point conventions straddle zero (peak -0.108
# against centroid +2.44), so "slightly positive" is a property of the convention there
# and not of the mesh, and turning that into a FAIL would be fabricating a measurement.
# What was wrong was the other half. The row text was fully honest — it named the claim it
# had not scored — and the STATUS was not: it was PASS, it counted in pass=25 on the
# CONTROL, and no summary surface anywhere carried the fact that half the gate's declared
# claim had no verdict. Meanwhile the pose layer, in the identical situation, returned
# not_implementable, escalated, and was named in unrun_blocking. One engine cannot hold two
# contracts for "a declared claim I did not evaluate"; see DECLARED_CLAIM_CONTRACT.
#
# What this costs, measured: the CONTROL's canthal row moves pass -> n/a, so its pass
# count drops by one. That is the honest count. The gate still cannot FAIL on an
# unresolved sign, which is the part that would have been fabrication.
def _canthal_verdict(rec):
    ceiling_ok = rec.get('ceiling_verdict') == 'in_band'
    sign_resolved = bool(rec.get('sign_resolved'))
    sign_positive = bool(rec.get('sign_positive'))
    # Claim 1 of 2: the ceiling. Always scored — |tilt| is defined whatever the sign does.
    ceiling_st = PASS if ceiling_ok else FAIL
    # Claim 2 of 2: the sign.
    if sign_resolved and not sign_positive:
        sign_st = FAIL
        sign_txt = (
            'RESOLVED NEGATIVE — every operationalisation puts the lateral '
            'canthus BELOW the medial, which is the slant HeadNeck p.43 rules out'
        )
    elif sign_resolved:
        sign_st, sign_txt = PASS, 'resolved positive, as printed'
    else:
        sign_st = UNEVALUATED_CLAIM
        sign_txt = (
            'UNRESOLVED, so this half of HeadNeck p.43 HAS NO VERDICT and the '
            'gate does not pass on the strength of the other half — %s'
            % (
                rec.get('sign_reason')
                or 'the point conventions straddle zero, so the sign is a property '
                'of the convention and not of this mesh'
            )
        )
    st = _claim_rollup([ceiling_st, sign_st])
    verdict = 'ceiling %s (|tilt| <= %s) -> %s; sign %s -> %s. Rolled up worst-first to %s. %s' % (
        rec.get('ceiling_verdict'),
        rec.get('ceiling_deg'),
        ceiling_st,
        sign_txt,
        sign_st,
        st,
        DECLARED_CLAIM_CONTRACT,
    )
    extra = {
        'canthal_claims_declared': 2,
        'canthal_claims_evaluated': int(ceiling_st != UNEVALUATED_CLAIM) + int(sign_st != UNEVALUATED_CLAIM),
        'canthal_claim_not_evaluated': None
        if sign_st != UNEVALUATED_CLAIM
        else 'sign (HeadNeck p.43: lateral canthus above medial)',
        'canthal_ceiling_claim': rec.get('ceiling_verdict'),
        'canthal_ceiling_status': ceiling_st,
        'canthal_sign_claim': ('fail' if sign_st == FAIL else 'pass' if sign_st == PASS else 'unresolved'),
        'canthal_sign_status': sign_st,
        'canthal_sign_resolved': sign_resolved,
        'canthal_sign_positive': sign_positive if sign_resolved else None,
        'canthal_band_declared': [0.0, rec.get('ceiling_deg')],
        'canthal_band_enforced': 'sign half: FAIL only on a RESOLVED negative, so an unresolved sign is not '
        'converted into a failure — it is a NON-VERDICT (%s) and the gate does not '
        'pass without it. Ceiling half: |tilt| <= %s, always scored. The enforced rule '
        'is NOT the two-sided band [-%s, +%s] that shipped until 2026-08-06.'
        % (UNEVALUATED_CLAIM, rec.get('ceiling_deg'), rec.get('ceiling_deg'), rec.get('ceiling_deg')),
        'declared_claim_contract': DECLARED_CLAIM_CONTRACT,
        'canthal_operationalisations': rec.get('operationalisations'),
    }
    return st, verdict, extra


# -- relief ------------------------------------------------------------------------
# WHAT COUNTS AS "RESOLVES RELIEF" IS NOT DECIDED HERE — AND THAT IS THE FIX.
#
# THE DEFECT THIS CLOSES (F1, HIGH). This adapter used to carry its own verdict list:
#     if vd in ('ridge', 'furrow', 'mixed_strip', 'point_only'):
# `point_only` is geom.form.ridge's verdict for a run SHORTER than min_run, and min_run is
# the null's measured p99 + 1 — so point_only IS the null's own support. Re-derived on the
# shipped seed: a point_only-or-better reading occurs by chance on 33.3% of landmark-free
# skin pools in ridge mode, 6.7% in point mode, 37.8% under the two-mode union that is the
# criterion actually applied. Counting it as a resolution turned abel's 0 resolved body
# landmarks into "8 of 20" — 0.40 against a chance rate of 0.378, z = +0.20, i.e. a
# headline statistically indistinguishable from pointing the instrument at blank skin. That
# is threshold-widening at the consumer so our own assets pass, which is rule 3's cardinal
# sin, and it silently retired a real pre-existing finding.
#
# The classification now lives in ridge.py (RESOLVED_VERDICTS / VERDICT_CLASS /
# resolves_relief(), which RAISES on an unknown verdict rather than defaulting), and every
# probe record carries `resolves_relief` and `resolution_class` computed there. This file
# reads those fields. It does not pattern-match a verdict string, and it must not: a
# verdict name is not a threshold.
#
# THE HONEST RESULT SHIPS. abel: 0 of 20 body probes resolved, 11 of 11 AFS p.63
# fat-invariant probes silent. So do the other four bodies' numbers.
FAT_INVARIANT_SOURCE = (
    'CANON — Anatomy For Sculptors p.63 maps the regions that keep bony relief at every '
    'BMI (facial mask, nape, clavicle-sternum, spine midline, elbows, wrists/hands, knees, '
    'ankles/feet), and p.193-194 enumerates 13 lower-limb landmarks that read through '
    'flesh on ordinary, non-athletic, non-posed subjects. The ROSTER and its denominator '
    "are geom.form.ridge.AFS_P63_REGIONS, which keeps the page's eight regions whole and "
    'REPORTS the three that have no body probe at all (facial mask, nape, spine midline) '
    'rather than dropping them and letting a partial census read as a complete one. The '
    "CUT is not from the book: it is geom.form.ridge.RIDGE_NULL_P99, the module's own "
    'measured false-positive floor (120 random skin pools x 3 sizes, seed 20260806, 1% '
    'per-station FPR), and "resolves" means ridge.resolves_relief() — outside that null — '
    'never the below-null point_only verdict. The book supplies WHICH regions must show '
    'relief; the mesh supplies what counts as showing it.'
)


def _relief_summary(probe, M, scope):
    """(summary, error_result_or_None) — the module's own four-bucket census.

    Never re-counts. If the module did not attach `_summary` the probe set predates the
    resolution contract, and that is reported as an ERROR rather than recovered by
    re-deriving the classification here, which is how the classification drifted in the
    first place.
    """
    summ = probe.get('_summary')
    if not isinstance(summ, dict) or 'n_resolved' not in summ:
        try:
            summ = M.relief_summary(probe, scope=scope)
        except Exception as e:  # noqa: BLE001
            return None, _result(
                ERROR,
                'the %s probe set carries no _summary and '
                'geom.form.ridge.relief_summary raised %s: %s. This file '
                'will not re-derive which verdicts resolve relief — that '
                'decision belongs to ridge.RESOLVED_VERDICTS and '
                'duplicating it is the defect being fixed.' % (scope, type(e).__name__, e),
            )
    return summ, None


def t5_landmark_relief(sub):
    """Do the bony landmarks AFS p.63 says are visible AT EVERY BODYFAT show relief on this
    cage, outside geom.form.ridge's own measured null?

    Scored on ridge's fat-invariant census, which keeps the page's denominator whole and
    reports the independence of the windows beside the count — the 11 body probes cover 5
    separated regions of skin, at most 6 of them pairwise disjoint (D6), so "n of 11" is
    never 11 independent observations.
    """
    payload, bail = _t5_payload(sub, 'ridge', 't5_landmark_relief')
    if bail is not None:
        return bail
    M, _ = form_module('ridge')
    body = payload['body']
    summ, err = _relief_summary(body, M, 'body')
    if err is not None:
        return err
    fi = body.get('_fat_invariant')
    if not isinstance(fi, dict) or 'n_probes_missing' not in fi:
        try:
            fi = M.fat_invariant_report(body)
        except Exception as e:  # noqa: BLE001
            return _result(ERROR, 'geom.form.ridge.fat_invariant_report raised %s: %s' % (type(e).__name__, e))
    missing = list(fi.get('missing') or [])
    ind = fi.get('independence') or {}
    st = FAIL if missing else PASS
    return _result(
        st,
        '%s %s' % (summ.get('sentence') or '', fi.get('sentence') or ''),
        observed={
            'resolved': summ.get('n_resolved'),
            'probes': summ.get('n_probes'),
            'below_null': summ.get('n_below_null'),
            'point_only': len(summ.get('point_only') or ()),
            'unmeasurable': summ.get('n_unmeasurable'),
            'never_probed': summ.get('n_never_probed'),
            'fat_invariant_probes': fi.get('n_probes'),
            'fat_invariant_resolved': fi.get('n_probes_resolved'),
            'fat_invariant_missing': fi.get('n_probes_missing'),
            'fat_invariant_separated_skin_regions': ind.get('n_disjoint_clusters'),
            'fat_invariant_max_pairwise_disjoint': ind.get('max_disjoint_windows'),
            'afs_p63_regions_with_no_body_probe': len(fi.get('unprobed_page_regions') or ()),
        },
        band=[0, 0],
        source=FAT_INVARIANT_SOURCE,
        resolution_contract=summ.get('resolution_contract'),
        resolved=summ.get('resolved'),
        point_only=summ.get('point_only'),
        flat=summ.get('flat'),
        unmeasurable=summ.get('unmeasurable'),
        never_probed=summ.get('never_probed'),
        fat_invariant_missing=missing,
        fat_invariant_resolved=fi.get('resolved'),
        afs_p63_unprobed_regions=fi.get('unprobed_page_regions'),
        afs_p63_census_incomplete=fi.get('absent_from_set'),
        window_independence=ind,
        set_independence=(body.get('_independence') or {}).get('note'),
        shared_peak_vertices=(body.get('_independence') or {}).get('shared_peak_vertices'),
        cuts=body.get('_cuts'),
    )


def t5_head_landmark_relief(sub):
    """The 12 head/neck windows, REPORT ONLY.

    Head relief is a different regime from the body and the module says so: the contrast
    floor those probes are scored against was calibrated on a BODY null, and a head feature
    is broad enough that its own collar is curved, so a broad arch can carry +15 mm of
    relief and still miss a contrast test built for a point bump on flat skin. Gating on a
    floor known to be measured on the wrong surface would be exactly the calibration error
    this package refuses; the numbers are reported and the caveat travels with them.

    F6: the prose is now ridge.relief_summary()'s own sentence, which names the windows
    that hold NO VERTEX on this cage by name every time, including when the list is empty.
    The shipped text said "4 of 12 resolve; unresolved: <5 names>" — 4 + 5 = 9 — and the
    three windows with no geometry (cervicale, external_occipital_protuberance,
    mastoid_process on abel) appeared nowhere in the artefact.
    """
    payload, bail = _t5_payload(sub, 'ridge', 't5_head_landmark_relief')
    if bail is not None:
        return bail
    M, _ = form_module('ridge')
    head = payload['head']
    summ, err = _relief_summary(head, M, 'head')
    if err is not None:
        return err
    return _result(
        REPORT,
        summ.get('sentence') or 'no summary sentence',
        observed={
            'resolved': summ.get('n_resolved'),
            'probes': summ.get('n_probes'),
            'below_null': summ.get('n_below_null'),
            'point_only': len(summ.get('point_only') or ()),
            'unmeasurable': summ.get('n_unmeasurable'),
            'never_probed': summ.get('n_never_probed'),
        },
        source=FAT_INVARIANT_SOURCE,
        resolution_contract=summ.get('resolution_contract'),
        resolved=summ.get('resolved'),
        point_only=summ.get('point_only'),
        flat=summ.get('flat'),
        unmeasurable=summ.get('unmeasurable'),
        never_probed=summ.get('never_probed'),
        window_independence=(head.get('_independence') or {}).get('note'),
        cuts=head.get('_cuts'),
        caveat='the contrast floor in force was measured on TORSO AND LIMB '
        'skin; there is no featureless head skin on this cage to build a '
        'head null from, so a head percentile is indicative, not exact. '
        'These counts are REPORT ONLY and may not be summed with the '
        'body counts in either direction.',
    )


# -- the CANON receipt -------------------------------------------------------------
AFS_HEAD_UNITS_CHART = {'ages_8_12': 6.0, 'teen': 7.0, 'adult': 7.5, 'source': 'Anatomy For Sculptors p.91-93'}


def t5_canon_head_units(sub):
    """The visible receipt of the CANON policy: AFS's head-unit chart against this body.

    REPORT ONLY, and the severity is the whole point. AFS p.91 puts ages 8-12 at 6.0 head
    units; this pipeline measures 7.06-7.13 on a 12-year-old and on three adults alike. The
    chart's derived claim about crotch height contradicts NHANES III cormic data already on
    disk. A CANON number that is contradicted by a MEASURED one does not get to fail a
    body — it gets printed next to the measurement so a reader can see the size of the
    disagreement.
    """
    hh = sub.mm('head_height_vertex_menton')
    heads = None if not hh else sub.stature_mm / hh
    age = sub.age_years
    canon = (
        AFS_HEAD_UNITS_CHART['ages_8_12']
        if (age is not None and 8.0 <= age <= 12.0)
        else AFS_HEAD_UNITS_CHART['adult']
        if (age is None or age >= 18.0)
        else AFS_HEAD_UNITS_CHART['teen']
    )
    crotch = sub.ratio('crotch_height_over_stature')
    return _result(
        REPORT,
        "head count %s vs the AFS chart's %.1f for age %s (delta %s). "
        'crotch_height_over_stature = %s, which is a MEASURED-covered quantity '
        '(ANSUR II) and therefore NOT gateable from the chart under the CANON '
        'policy.'
        % (
            '%.3f' % heads if heads else 'unmeasured',
            canon,
            'unknown' if age is None else '%.1f y' % age,
            '%+.3f' % (heads - canon) if heads else 'n/a',
            'unmeasured' if crotch is None else '%.4f' % crotch,
        ),
        observed={
            'heads_tall': None if heads is None else round(heads, 4),
            'canon_heads_for_age': canon,
            'delta_heads': (None if heads is None else round(heads - canon, 4)),
            'crotch_height_over_stature': crotch,
        },
        band=None,
        source=AFS_HEAD_UNITS_CHART['source'],
        provenance_note=CANON_DEFINITION,
        conflict=CANON_VS_MEASURED_CONFLICT,
        why_report_only='the two quantities this chart constrains, crotch '
        'height and the age trend, are both answered by surveys '
        'on disk, and the chart disagrees with both',
    )
