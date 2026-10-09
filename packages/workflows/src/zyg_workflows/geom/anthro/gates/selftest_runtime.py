# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Self-tests over declared claims, severity, roll-up, shells, paths and crash-vs-policy.

Moved verbatim out of the old single-file gates.py (lines 9346-9955).
"""

import numpy as np
from zyg_workflows.geom import mesh_skeletons as MS
from zyg_workflows.geom.anthro import integrity as IG
from zyg_workflows.geom.anthro import landmarks as LMK
from zyg_workflows.geom.anthro import measure as ME

from zyg_workflows.geom.anthro.gates.policy import (
    CANON,
    CRASHED_KEY,
    ERROR,
    FAIL,
    HOUSE,
    MISSING,
    NOT_APPLICABLE,
    PASS,
    POLICY_ERROR,
    REPORT,
    UNMEASURABLE,
)
from zyg_workflows.geom.anthro.gates.bands import CAL_UNDECLARED, GateConfigError, STYLIZATION_AXIS, _structural
from zyg_workflows.geom.anthro.gates.gate import Gate, _result
from zyg_workflows.geom.anthro.gates.subject import (
    Subject,
    UNEVALUATED_CLAIM,
    _SKIPPED,
    _claim_rollup,
    _note,
    _roll_up,
    _roll_up_summary,
    _sub,
)
from zyg_workflows.geom.anthro.gates.severity_reject import _reject_ratio_bands
from zyg_workflows.geom.anthro.gates.tier1 import t1_build_target_stature, t1_shell_containment
from zyg_workflows.geom.anthro.gates.tier2 import t2_vhi_bmi
from zyg_workflows.geom.anthro.gates.tier3 import t3_realism_asymmetry
from zyg_workflows.geom.anthro.gates.tier4 import t4_stylization_axis, t4_tolerance_sanity
from zyg_workflows.geom.anthro.gates.tier5_gates import _canthal_verdict
from zyg_workflows.geom.anthro.gates.registry import GATES
from zyg_workflows.geom.anthro.gates.severity import calibrate_gate, severity_table
from zyg_workflows.geom.anthro.gates.engine import _classify, _effective_severity, run_gates


def _selftest_declared_claims():
    """ONE CONTRACT FOR A DECLARED CLAIM THAT WAS NOT EVALUATED (N2)."""
    out = []
    cases = (
        (
            'ceiling in band, sign RESOLVED POSITIVE',
            {'ceiling_verdict': 'in_band', 'ceiling_deg': 10.0, 'sign_resolved': True, 'sign_positive': True},
            PASS,
        ),
        (
            'ceiling in band, sign RESOLVED NEGATIVE',
            {'ceiling_verdict': 'in_band', 'ceiling_deg': 10.0, 'sign_resolved': True, 'sign_positive': False},
            FAIL,
        ),
        (
            'ceiling OUT of band',
            {'ceiling_verdict': 'above_band', 'ceiling_deg': 10.0, 'sign_resolved': True, 'sign_positive': True},
            FAIL,
        ),
        # The CONTROL's shape, and the one that changed: one of two declared claims has
        # no verdict, so the gate has none either. It used to return PASS.
        (
            'ceiling in band, sign UNRESOLVED (the anny-neutral control)',
            {'ceiling_verdict': 'in_band', 'ceiling_deg': 10.0, 'sign_resolved': False, 'sign_positive': False},
            UNEVALUATED_CLAIM,
        ),
    )
    for label, rec, want in cases:
        st, _why, extra = _canthal_verdict(rec)
        out.append('%-52s -> %-18s (%s)' % (label, st, 'correct' if st == want else 'WRONG, expected %s' % want))
        if want == UNEVALUATED_CLAIM:
            out.append(
                '    claims declared=%d evaluated=%d not evaluated=%r'
                % (
                    extra['canthal_claims_declared'],
                    extra['canthal_claims_evaluated'],
                    extra['canthal_claim_not_evaluated'],
                )
            )
    out.append(
        'and it is the SAME arithmetic as every other roll-up: _claim_rollup uses '
        '_ROLL_UP_ORDER (%s beats pass: %s)'
        % (UNEVALUATED_CLAIM, _claim_rollup([PASS, UNEVALUATED_CLAIM]) == UNEVALUATED_CLAIM)
    )
    return out


def _selftest_severity():
    """The severity policy has to be arithmetic on measured numbers, not a claim in a
    docstring. Prove the three things a reader would want to check by hand."""
    out = []
    st = severity_table()
    # 1. The policy actually fired, and on the gates the audit said it should.
    out.append('downgraded by measurement: %s' % (', '.join(st['downgraded']) or 'NONE (suspicious)'))
    # 2. A p1-p99 band really does exclude 2% of the sample whatever the ratio, which is
    #    the argument for the policy and not an incidental detail.
    one = _reject_ratio_bands(['crotch_height_over_stature'])
    other = _reject_ratio_bands(['bmi'])
    pooled = [c for c in one['cells'] if c['sex'] == 'male' and c['group'] == 'pooled']
    pooled2 = [c for c in other['cells'] if c['sex'] == 'male' and c['group'] == 'pooled']
    out.append(
        'single p1p99 band on two unrelated ratios rejects %s and %s of male '
        'pooled — identical because a percentile band is a property of the band, '
        'not of the body'
        % ('%.4f' % pooled[0]['rejected'] if pooled else '?', '%.4f' % pooled2[0]['rejected'] if pooled2 else '?')
    )
    # 3. The primary gate is inside the ceiling and the band gates are nowhere near it.
    for gid in ('t2_mahalanobis', 't2_heights_tight', 't2_breadths_wide', 't2_girths_wide', 't3_depths_wide'):
        c = st['gates'][gid]
        out.append(
            '%-18s declared=%-5s effective=%-5s rejects=%s'
            % (
                gid,
                c['severity_declared'],
                c['severity_effective'],
                'n/a' if c['rate'] is None else '%.2f%%' % (100.0 * c['rate']),
            )
        )
    # 4. Every gate in the registry has an answer, so no severity is un-auditable.
    blank = [r['id'] for r in st['rows'] if r['kind'] == CAL_UNDECLARED]
    out.append('gates with no declared calibration: %s' % (', '.join(blank) or 'none'))
    # 5. The calibration softens a BAND REJECTION. It must not soften a CRASH: a gate that
    #    raised did not observe an unusual body, it broke. Proven on a gate the policy did
    #    downgrade, so the ERROR guard is what is being tested and not the severity.
    downgraded = next((g for g in GATES if g.id in st['downgraded']), None)
    if downgraded is not None:
        cal = calibrate_gate(downgraded)
        sev_fail, _ = _effective_severity(downgraded, cal, FAIL)
        sev_err, _ = _effective_severity(downgraded, cal, ERROR)
        out.append(
            'on the downgraded gate %s: a band FAIL classifies %r, a crash '
            'classifies %r (%s)'
            % (
                downgraded.id,
                _classify(sev_fail, FAIL),
                _classify(sev_err, ERROR),
                'correct' if _classify(sev_err, ERROR) == 'blocking' else 'WRONG',
            )
        )
    # 6. A gate that declares no calibration may warn but may never block.
    mute = Gate(
        't9_silent', 2, 'block', 'declares nothing', 1.0, HOUSE, 'HOUSE', lambda s: _result(FAIL, 'never reached')
    )
    c = calibrate_gate(mute)
    out.append(
        'a block-severity gate with no calibration resolves to %r (%s)'
        % (c['severity_effective'], 'correct' if c['severity_effective'] == 'warn' else 'WRONG')
    )
    # 7. The primary gate is calibrated on the vector AS SUBSTITUTED, not on the pack's
    #    own coordinates. Both numbers are printed because the difference IS the finding.
    c = st['gates']['t2_mahalanobis']
    out.append(
        't2_mahalanobis: model as the pack built it rejects %s, the vector as this '
        'pipeline substitutes it rejects %s -> effective %r (%s)'
        % (
            'n/a' if c.get('rate_of_model_as_built') is None else '%.3f%%' % (100.0 * c['rate_of_model_as_built']),
            'n/a' if c.get('rate_as_configured') is None else '%.3f%%' % (100.0 * c['rate_as_configured']),
            c['severity_effective'],
            'the substituted rate governs'
            if c['rate'] == c.get('rate_as_configured')
            else 'WRONG: the model rate is governing',
        )
    )
    # 8. A calibration may not count bands the gate cannot fail on.
    for gid in ('t2_breadths_wide', 't2_girths_wide'):
        c = st['gates'][gid]
        out.append(
            '%-18s calibrated on %d of %d declared bands (excluded: %s)'
            % (
                gid,
                len(c.get('ratios') or []),
                len(c.get('ratios_declared') or []),
                ', '.join(e['ratio'] for e in c.get('ratios_excluded') or []) or 'none',
            )
        )
    # 9. The girth chain's rate must come from a step it can actually fail on.
    c = st['gates']['t1_girth_chain']
    out.append(
        't1_girth_chain rate %s from fail-capable steps %s; warn-only steps %s'
        % (
            'n/a' if c['rate'] is None else '%.4f%%' % (100.0 * c['rate']),
            c.get('steps_fail_capable'),
            c.get('steps_warn_only'),
        )
    )
    return out


def _selftest_rollup():
    """The roll-up is where "the check did not run" turns into "the gate passed", so the
    conversion is tested rather than asserted."""
    out = []
    cases = (
        (
            'all real checks unmeasurable, one trivial pass',
            [_sub('a', UNMEASURABLE, ''), _sub('b', UNMEASURABLE, ''), _sub('trivial', PASS, '')],
            (UNMEASURABLE,),
            'not_run',
        ),
        (
            'report rows beside skipped rows (the abel breadths case)',
            [_sub('a', REPORT, ''), _sub('b', NOT_APPLICABLE, ''), _sub('c', NOT_APPLICABLE, '')],
            (NOT_APPLICABLE,),
            'not_run',
        ),
        ('everything passed', [_sub('a', PASS, ''), _sub('b', PASS, '')], (PASS,), 'ok'),
        (
            'passes plus an INFORMATIONAL note about a caller input',
            [_sub('a', PASS, ''), _note('declared?', NOT_APPLICABLE, '')],
            (PASS,),
            'ok',
        ),
        (
            'a real failure still dominates everything',
            [_sub('a', FAIL, ''), _sub('b', UNMEASURABLE, ''), _sub('c', PASS, '')],
            (FAIL,),
            'blocking',
        ),
        (
            'a missing input still dominates a pass',
            [_sub('a', MISSING, ''), _sub('b', PASS, '')],
            (MISSING,),
            'warning',
        ),
        # D9. This case returned PASS until 2026-08-06: REPORT ranked BELOW pass in
        # _ROLL_UP_ORDER, so a gate with one gated row that passed and one row that was
        # only printed reported a clean pass and the ungated half vanished.
        (
            'a REPORT row beside a pass may not roll up to pass (D9)',
            [_sub('a', REPORT, ''), _sub('b', PASS, '')],
            (REPORT,),
            'not_run',
        ),
        (
            'all-report still rolls up to report, unchanged',
            [_sub('a', REPORT, ''), _sub('b', REPORT, '')],
            (REPORT,),
            'not_run',
        ),
        (
            'a REPORT row does not outrank a real failure either',
            [_sub('a', REPORT, ''), _sub('b', FAIL, '')],
            (FAIL,),
            'blocking',
        ),
    )
    for label, rows, want, want_cls in cases:
        got, _ = _roll_up(rows)
        cls = _classify('block', got)
        ok = got in want and cls == want_cls
        out.append(
            '%-56s -> %-16s %-9s (%s)'
            % (label, got, cls, 'correct' if ok else 'WRONG, expected %s/%s' % ('|'.join(want), want_cls))
        )
    s = _roll_up_summary([_sub('a', PASS, ''), _sub('b', UNMEASURABLE, ''), _note('n', NOT_APPLICABLE, '')])
    out.append(
        'summary of 1 pass + 1 skipped + 1 note: evidence=%d skipped=%d '
        'informational=%d (%s)'
        % (
            s['evidence'],
            s['skipped'],
            s['informational'],
            'correct' if (s['evidence'], s['skipped'], s['informational']) == (1, 1, 1) else 'WRONG',
        )
    )
    return out


def _selftest_shells():
    """The containment engine was computed on every character and read by nothing. Prove
    the wiring end to end AND on the payload shapes no issued asset produces."""
    out = []
    phen = dict(LMK.REF_MALE)
    v, f, _ = MS._build_mesh(phen, None)
    base = dict(
        sex='male',
        age_years=ME._age_years(phen['age']),
        phenotype=phen,
        local_changes={},
        anatomy_layer={},
        topology_scope='full',
        build_target_stature_mm=None,
    )
    clean = Subject.from_mesh(np.asarray(v, np.float64), f, dict(base), 'selftest')
    r = t1_shell_containment(clean)
    out.append('pristine cage -> %s (%s)' % (r['status'], r['explain'][:90]))

    # Move the second-largest component (the tongue on this cage) two metres forward.
    try:
        tris = IG.triangulate_quads(np.asarray(f))
        ncomp, labels = IG._components(np.asarray(v, np.float64), tris)
        sizes = [(int((labels == k).sum()), k) for k in range(ncomp)]
        sizes.sort(reverse=True)
        if len(sizes) < 2:
            raise RuntimeError('this cage has only one component')
        target = sizes[1][1]
        vd = np.asarray(v, np.float64).copy()
        vd[labels == target] += np.array([0.0, -2.0, 0.0])
        moved = Subject.from_mesh(vd, f, dict(base), 'selftest-detached')
        rd = t1_shell_containment(moved)
        out.append(
            'shell %d (%d v) teleported 2 m anterior -> %s (%s)'
            % (target, sizes[1][0], rd['status'], rd['explain'][:90])
        )
        rep = run_gates(moved, tiers=[1], strict=False)
        out.append(
            '...and the tier-1 verdict is %s with blocking=%s (%s)'
            % (
                rep['verdict'],
                rep['blocking'],
                'correct' if rep['verdict'] == 'FAIL' else 'WRONG: a detached shell must not pass',
            )
        )
    except Exception as e:  # noqa: BLE001
        out.append(
            'DETACHED-SHELL FIXTURE UNAVAILABLE (%s: %s) — the end-to-end proof did NOT run' % (type(e).__name__, e)
        )

    # Payload shapes the four issued cages never produce.
    fake = dict(clean.integrity)
    sc = fake['shell_components']
    d = dict(sc['detail'])
    d['inventory'] = [dict(e) for e in d['inventory']]
    for e in d['inventory']:
        if e.get('role') != 'body':
            e['containment'] = {'state': 'not_tested', 'state_meaning': 'not analysed'}
            break
    fake['shell_components'] = {'pass': False, 'detail': d, 'ms': 0.0}
    stub = Subject.from_mesh(np.asarray(v, np.float64), f, dict(base), 'stub')
    stub._integ = fake
    out.append(
        'one shell reported not_tested -> %s (%s)'
        % (
            t1_shell_containment(stub)['status'],
            'correct'
            if t1_shell_containment(stub)['status'] in _SKIPPED
            else 'WRONG: untested containment is not a pass',
        )
    )
    fake2 = dict(fake)
    fake2.pop('shell_components')
    stub2 = Subject.from_mesh(np.asarray(v, np.float64), f, dict(base), 'stub2')
    stub2._integ = fake2
    out.append(
        'no shell payload at all -> %s (%s)'
        % (
            t1_shell_containment(stub2)['status'],
            'correct' if t1_shell_containment(stub2)['status'] == MISSING else 'WRONG',
        )
    )
    return out


def _selftest_paths():
    """Exercise the code paths that no issued asset happens to take, so that the parts of
    the engine our own four characters never reach are still known to work."""
    out = []
    phen = dict(LMK.REF_MALE)
    v, f, _ = MS._build_mesh(phen, None)
    base = dict(
        sex='male',
        age_years=ME._age_years(phen['age']),
        phenotype=phen,
        local_changes={},
        anatomy_layer={},
        topology_scope='full',
        build_target_stature_mm=None,
    )

    s = Subject.from_mesh(v, f, dict(base, stature_tolerance_mm=2.0, stature_claim='anthropometric'), 'selftest')
    r = t4_tolerance_sanity(s)
    out.append(
        'anthropometric claim at 2.0 mm -> %s (%s)' % (r['status'], 'correct' if r['status'] == FAIL else 'WRONG')
    )
    s = Subject.from_mesh(v, f, dict(base, stature_tolerance_mm=20.0, stature_claim='anthropometric'), 'selftest')
    out.append('anthropometric claim at 20.0 mm -> %s' % t4_tolerance_sanity(s)['status'])

    s = Subject.from_mesh(v, f, dict(base, build_target_stature_mm=1686.0), 'selftest')
    r = t1_build_target_stature(s)
    out.append('declared build target 1686.0 mm -> %s (%s)' % (r['status'], r['explain']))

    s = Subject.from_mesh(v, f, dict(base, vhi_band=(15.0, 30.0)), 'selftest')
    out.append('declared VHI band 15-30 -> %s' % [c['status'] for c in t2_vhi_bmi(s)['detail']['checks']][0])
    s = Subject.from_mesh(v, f, dict(base, vhi_band=(1.0, 2.0)), 'selftest')
    out.append('impossible VHI band 1-2 -> %s' % [c['status'] for c in t2_vhi_bmi(s)['detail']['checks']][0])
    s = Subject.from_mesh(
        v, f, dict(base, vhi_band=(1.0, 2.0), vhi_override={'reason': 'stylised giant, approved'}), 'selftest'
    )
    out.append(
        'impossible VHI band + logged override -> %s' % [c['status'] for c in t2_vhi_bmi(s)['detail']['checks']][0]
    )
    s = Subject.from_mesh(v, f, dict(base, vhi_band=(1.0, 2.0), vhi_override={}), 'selftest')
    try:
        t2_vhi_bmi(s)
        out.append('override without a reason -> ACCEPTED (WRONG)')
    except GateConfigError:
        out.append('override without a reason -> refused')

    s = Subject.from_mesh(
        v,
        f,
        dict(
            base,
            stylization={
                'axis': STYLIZATION_AXIS,
                'value': phen[STYLIZATION_AXIS],
                'intent': 'vendor neutral, deliberately unstylised',
                'declared_by': 'selftest',
                'date': '2026-08-05',
            },
        ),
        'selftest',
    )
    out.append('stylization recorded -> %s' % t4_stylization_axis(s)['status'])
    s = Subject.from_mesh(v, f, dict(base, stylization={'axis': STYLIZATION_AXIS, 'value': 0.9}), 'selftest')
    out.append('stylization record disagreeing with the built phenotype -> %s' % t4_stylization_axis(s)['status'])

    s = Subject.from_mesh(v, f, dict(base, realism_asymmetry_injected=True), 'selftest')
    out.append('realism asymmetry declared on a pure-morph body -> %s' % t3_realism_asymmetry(s)['status'])

    rep = run_gates(Subject.from_mesh(v, f, dict(base), 'selftest'), tiers=[1])
    out.append('tiers=[1] ran %d gates, verdict %s' % (len(rep['gates']), rep['verdict']))

    boom = Gate(
        't9_boom',
        4,
        'block',
        'always raises',
        None,
        None,
        None,
        lambda s: 1 / 0,
        calibration=_structural('a fixture that raises on purpose'),
    )
    rep = run_gates(Subject.from_mesh(v, f, dict(base), 'selftest'), tiers=[4], gates=[boom], strict=False)
    out.append('strict=False on a raising gate -> %s / %s' % (rep['gates'][0]['status'], rep['verdict']))
    try:
        run_gates(Subject.from_mesh(v, f, dict(base), 'selftest'), tiers=[4], gates=[boom], strict=True)
        out.append('strict=True on a raising gate -> SWALLOWED (WRONG)')
    except ZeroDivisionError:
        out.append('strict=True on a raising gate -> propagated')
    out.extend(_selftest_crash_vs_policy(v, f, base))
    return out


def _selftest_crash_vs_policy(v, f, base):
    """A CRASH AND A REFUSED FINDING MUST NOT SHARE A STATUS OR A FLAG (W4-1).

    THE DEFECT THIS SUITE IS NAMED FOR, AND WHY THE PREVIOUS ONE COULD NOT SEE IT. Wave 4
    gave a gate that RAN, checked its subject and produced a real finding the same status
    as a gate that raised, and the renderer — correctly following "error means crash" —
    printed "GATES THAT CRASHED (checked nothing)" over t5_patellar_ligament's live
    blocking finding on all five bodies. The self-test in place at the time built every
    error fixture by raising, so all of its rows were genuine crashes and it could not have
    distinguished the two events even in principle. That is the third recurring failure
    shape in this package: a test blind to its own subject.

    Case 2 below is the one that can see it. It is a gate that RETURNS — it never raises —
    and produces a FAIL with a module tag that outranks the registry's. If POLICY_ERROR is
    folded back into ERROR, or if `crashed` goes back to being inferred from the status,
    case 2 and case 3 print WRONG. Cases 5-7 hold the other half of the contract: the split
    must not have made anything softer.
    """
    out, wrong = [], []
    subj = Subject.from_mesh(v, f, dict(base), 'selftest')

    def verdict(label, ok, right, wrong_txt):
        out.append('%s (%s)' % (label, right if ok else 'WRONG: ' + wrong_txt))
        if not ok:
            wrong.append(label)

    def one_row(gate, **kw):
        rep = run_gates(subj, tiers=[gate.tier], gates=[gate], strict=False, **kw)
        return rep, rep['gates'][0]

    # 1. A GATE THAT REALLY RAISES. status ERROR, crashed True, and it is the only thing in
    #    doc['crashed'].
    boom = Gate(
        't9_w41_boom',
        4,
        'block',
        'always raises',
        None,
        None,
        None,
        lambda s: 1 / 0,
        calibration=_structural('a fixture that raises on purpose'),
    )
    rep1, row1 = one_row(boom)
    verdict(
        '1 a gate that RAISES: status=%r crashed=%r doc.crashed=%r'
        % (row1['status'], row1[CRASHED_KEY], rep1['crashed']),
        row1['status'] == ERROR
        and row1[CRASHED_KEY] is True
        and rep1['crashed'] == ['t9_w41_boom']
        and rep1['policy_errors'] == [],
        'correct — a crash is a crash',
        'the one row that really did crash is no longer recorded as one',
    )

    # 2. THE W4-1 ROW. It RETURNS — nothing raises anywhere in this fixture — checks the
    #    body, produces a FAIL, and emits CANON where the registry adjudicated the weaker
    #    HOUSE. This is the live t5_patellar_ligament shape, quantity and all.
    def _ran_and_found(_s):
        return _result(
            FAIL,
            'THE LIGAMENT IS NOT MODELLED: patella-to-tuberosity distance drifts -15.54% at 120 deg',
            observed=-0.1554,
            module_provenance=CANON,
        )

    liar = Gate(
        't9_w41_refused',
        4,
        'block',
        'runs, finds, and over-claims its provenance',
        {'max_drift_frac': 0.02},
        HOUSE,
        'HOUSE — selftest fixture',
        _ran_and_found,
        quantities=('patella_tibial_tuberosity_distance_drift',),
        calibration=_structural('a fixture whose module over-claims'),
    )
    rep2, row2 = one_row(liar)
    verdict(
        '2 a gate that RAN and was refused on provenance: status=%r crashed=%r '
        'doc.crashed=%r doc.policy_errors=%r'
        % (row2['status'], row2[CRASHED_KEY], rep2['crashed'], rep2['policy_errors']),
        row2['status'] == POLICY_ERROR
        and row2[CRASHED_KEY] is False
        and rep2['crashed'] == []
        and rep2['policy_errors'] == ['t9_w41_refused'],
        'correct — a refused finding is not a crash, and says so as a flag rather than as a sentence',
        'a gate that ran and produced a finding is being filed as an infrastructure crash again — the W4-1 falsehood',
    )

    # 3. THE TWO TOKENS ARE ACTUALLY DIFFERENT. A test that only asserted "both are
    #    error-class" would pass with the statuses re-merged, which is the thing being
    #    fixed.
    verdict(
        '3 crash status %r and refusal status %r are distinct tokens' % (ERROR, POLICY_ERROR),
        ERROR != POLICY_ERROR and row1['status'] != row2['status'],
        'correct — separable downstream and in the counts',
        'the two events share one token again, so no consumer can tell them apart',
    )

    # 4. THE FINDING SURVIVED THE REFUSAL. Failure shape (b) is evidence computed and then
    #    not surfaced; the anatomy result must still be in the row and still be readable.
    ev = row2.get('detail') or {}
    verdict(
        '4 the replaced verdict is carried: would_have_returned=%r, "%s" in explain=%r'
        % (
            ev.get('status_the_gate_would_have_returned'),
            'LIGAMENT IS NOT MODELLED',
            'LIGAMENT IS NOT MODELLED' in (row2.get('explain') or ''),
        ),
        ev.get('status_the_gate_would_have_returned') == FAIL
        and 'LIGAMENT IS NOT MODELLED' in (ev.get('explain_the_gate_would_have_returned') or '')
        and 'LIGAMENT IS NOT MODELLED' in (row2.get('explain') or ''),
        'correct — the anatomy finding is named in the row and in the status text',
        'the real finding has been demoted into a detail key nobody reads',
    )

    # 5. NOTHING GOT SOFTER. The refusal still blocks a block-severity gate, still makes
    #    the run FAIL, and is still named in doc["blocking"].
    verdict(
        '5 the refusal still blocks: classification=%r verdict=%r blocking=%r '
        'severity=%r (declared %r)'
        % (row2['classification'], rep2['verdict'], rep2['blocking'], row2['severity'], row2['severity_declared']),
        row2['classification'] == 'blocking'
        and rep2['verdict'] == 'FAIL'
        and rep2['blocking'] == ['t9_w41_refused']
        and row2['severity'] == 'block',
        'correct — a new name, not a lighter sentence',
        'splitting the status softened it, which is the one thing the split was not allowed to do',
    )

    # 6. THE CALIBRATION STILL CANNOT REACH IT. A measured rejection rate is an argument
    #    about band failures; a refusal is not one.
    verdict(
        '6 the measured-rejection policy does not soften a refusal: %r'
        % (_effective_severity(liar, {'severity_effective': 'warn', 'reason': 'a rate argument'}, POLICY_ERROR)[0],),
        _effective_severity(liar, {'severity_effective': 'warn', 'reason': 'a rate argument'}, POLICY_ERROR)[0]
        == 'block',
        'correct — declared severity governs, exactly as for a crash',
        'a rejection-rate argument can now downgrade a provenance refusal',
    )

    # 7. AN UNMAPPED STATUS IS ERROR-CLASS, NEVER 'ok'. _classify fell through to 'ok'
    #    before W4-1, so a token this engine has never heard of counted as a pass on a
    #    blocking gate. Asserted through _classify directly AND through a live row.
    def _weird(_s):
        return {
            'status': 'fine_probably',
            'observed': None,
            'band': None,
            'source': None,
            'explain': 'a status this engine has never heard of',
        }

    odd = Gate(
        't9_w41_unmapped',
        4,
        'block',
        'returns an unknown status',
        None,
        None,
        None,
        _weird,
        calibration=_structural('a fixture with a bad status'),
    )
    rep7, row7 = one_row(odd)
    verdict(
        '7 an unmapped status %r -> _classify=%r row.classification=%r crashed=%r '
        'verdict=%r'
        % (
            'fine_probably',
            _classify('block', 'fine_probably'),
            row7['classification'],
            row7[CRASHED_KEY],
            rep7['verdict'],
        ),
        _classify('block', 'fine_probably') == 'blocking'
        and _classify('warn', 'fine_probably') == 'warning'
        and row7['classification'] == 'blocking'
        and row7.get('status_unmapped') == 'fine_probably'
        and row7[CRASHED_KEY] is False
        and rep7['verdict'] == 'FAIL',
        'correct — unmapped is error-class and is NAMED, and it did not raise so it is not a crash',
        'a status this engine cannot read is being counted as a pass on a blocking gate',
    )

    # 8. EVERY ROW CARRIES THE FLAG, not only the interesting ones — a consumer that reads
    #    row["crashed"] must never get None and fall back to guessing from the status.
    rep8 = run_gates(subj, tiers=[1])
    missing = [r['id'] for r in rep8['gates'] if not isinstance(r.get(CRASHED_KEY), bool)]
    verdict(
        '8 all %d tier-1 rows carry an explicit boolean %r: missing=%r' % (len(rep8['gates']), CRASHED_KEY, missing),
        not missing and rep8['crashed'] == [],
        'correct — the renderer never has to re-derive it',
        'some rows have no flag, so a renderer reading it falls back to the status and W4-1 comes back through the gap',
    )

    out.append(
        'crash-vs-policy self-checks: all 8 correct'
        if not wrong
        else 'crash-vs-policy self-checks: %d of 8 WRONG -> %s' % (len(wrong), '; '.join(wrong))
    )
    return out
