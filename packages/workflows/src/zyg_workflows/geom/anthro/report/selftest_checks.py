# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the coverage-floor, receipt-row, evidence-ranking and status-coverage self-tests.

Moved out of the old single-file report.py (lines 5035-5513).
"""

from zyg_workflows.geom.anthro.report.constants import (
    FAIL,
    GATE_ERROR,
    PASS,
    _COUNT_KEYS,
    _ENGINE_STATUS_CONSTANTS,
    _ENGINE_STATUS_CONSTANTS_OPTIONAL,
    _RECEIPT_KEY,
    _STATUS_ALIASES,
    _STATUS_MARK,
    _STATUS_ORDER,
)
from zyg_workflows.geom.anthro.report.gatedata import engine_statuses, normalize_status
from zyg_workflows.geom.anthro.report.document import build
from zyg_workflows.geom.anthro.report.renderers import render_gate_table, render_summary, render_text


def _selftest_coverage_floor():
    """A DOCUMENT IN WHICH NOTHING RAN IS NOT A PASS (re-review NEW-5).

    Rule 4 — "a check that did not run is never a pass" — was enforced on every gate and on
    no body. A suite in which every gate skips at a NON-blocking severity produced
    verdict=PASS, exit 0, and a counts line reading "pass 0": nothing in the arithmetic
    asked whether the suite had run at all.
    """
    skip = {
        'tier': 'frame',
        'severity': 'advisory',
        'status': 'skipped',
        'source': 'HOUSE: fixture',
        'explanation': 'no judgement is possible',
    }
    ok = {
        'tier': 'frame',
        'severity': 'advisory',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    # 1. THE DEFECT, EXACTLY: six advisory gates, every one of them skipped.
    d = build({'tiers': {'frame': [dict(skip, id='s%d' % i) for i in range(6)]}}, None, name='unrun', sex='male')
    if not (d['counts'][PASS] == 0 and d['counts']['skip'] == 6):
        raise AssertionError(d['counts'])
    if not (d['blocking'] == [] and d['unrun_blocking'] == []):
        raise AssertionError('control: none of these gates is blocking, so the per-gate rule cannot save this')
    if not (d['coverage']['n_produced_verdict'] == 0):
        raise AssertionError
    if d['coverage']['meets_floor'] is not False:
        raise AssertionError
    if not (d['verdict'] != PASS):
        raise AssertionError('a suite in which nothing ran rendered as a PASS')
    if not (d['exit_code'] != 0):
        raise AssertionError('and exited 0 while doing it')
    if 'suite_coverage_below_floor' not in {a['kind'] for a in d['policy_alarms']}:
        raise AssertionError
    if 'SUITE COVERAGE BELOW FLOOR' not in render_text(d):
        raise AssertionError
    if 'coverage_floor=BELOW' not in render_summary(d):
        raise AssertionError
    if 'verdicts=0' not in render_summary(d):
        raise AssertionError
    # 2. The floor is a FRACTION as well as a count. One gate in ten is the case that an
    #    "at least one check ran" floor would happily bless.
    thin = build(
        {'tiers': {'frame': [dict(ok, id='p0')] + [dict(skip, id='s%d' % i) for i in range(9)]}},
        None,
        name='thin',
        sex='male',
    )
    if not (thin['coverage']['n_produced_verdict'] == 1):
        raise AssertionError
    if not (thin['coverage']['meets_floor'] is False and thin['verdict'] != PASS):
        raise AssertionError
    # 3. An EMPTY suite is the degenerate case and is not a pass either.
    empty = build({'tiers': {'frame': []}}, None, name='empty', sex='male')
    if not (empty['n_gates'] == 0 and empty['verdict'] != PASS):
        raise AssertionError(empty['verdict'])
    if empty['coverage']['fraction'] is not None:
        raise AssertionError
    # 4. CONTROL: a suite that DID run still passes. The floor must not invent a warning on
    #    a clean report — if it does, every PASS in the file is noise and nobody reads it.
    full = build({'tiers': {'frame': [dict(ok, id='p%d' % i) for i in range(4)]}}, None, name='full', sex='male')
    if full['coverage']['meets_floor'] is not True:
        raise AssertionError
    if not (full['verdict'] == PASS and full['exit_code'] == 0):
        raise AssertionError(full['policy_alarms'])
    # 5. AT the floor, a pass is still a pass: this is a floor, not a majority test that
    #    quietly moved a threshold. Two verdicts and two non-verdicts is exactly 0.5.
    half = build(
        {'tiers': {'frame': [dict(ok, id='p0'), dict(ok, id='p1'), dict(skip, id='s0'), dict(skip, id='s1')]}},
        None,
        name='half',
        sex='male',
    )
    if not (half['coverage']['fraction'] == 0.5):
        raise AssertionError
    if not (half['coverage']['meets_floor'] is True and half['verdict'] == PASS):
        raise AssertionError
    # 6. Coverage is counted on the RAW status. An escalated skip counts towards the
    #    warning total, and it is still not a verdict — reading it off effective_status
    #    would let escalation manufacture the coverage that excuses it.
    esc = build(
        {'tiers': {'frame': [dict(ok, id='p0'), dict(skip, id='s0', severity='block')]}}, None, name='esc', sex='male'
    )
    srow = [g for g in esc['gates'] if g['id'] == 's0'][0]
    if not (srow['effective_status'] == 'warn' and srow['produced_no_verdict'] is True):
        raise AssertionError
    if not (esc['coverage']['n_produced_verdict'] == 1):
        raise AssertionError(esc['coverage'])

    # 7. THE DENOMINATOR IS THE DECLARED ROSTER, NOT THE ROWS PRESENT (W4-3). The printed
    #    rule said "of the DECLARED gates" and the arithmetic divided by len(gates), so a
    #    suite that EMITTED 3 of its 60 declared gates, all passing, scored fraction=1.000,
    #    meets_floor=True, verdict=PASS, exit 0 — the same hole the floor was built to
    #    close, reached by omission instead of by skipping. This is that document.
    roster = {
        'policy': 'fixture',
        'rows': [
            {
                'id': 'r%02d' % i,
                'tier': 'frame',
                'declared': 'warn',
                'effective': 'warn',
                'rejection_rate': None,
                'basis': 'fixture',
                'kind': 'fixture',
                'downgraded': False,
            }
            for i in range(60)
        ],
    }
    thin3 = build(
        {
            'schema': 'geom.anthro.gates/1',
            'tiers_run': ['frame'],
            'severity_calibration': roster,
            'tiers': {'frame': [dict(ok, id='r%02d' % i) for i in range(3)]},
        },
        None,
        name='omit',
        sex='male',
    )
    cov = thin3['coverage']
    if not (cov['n_gates'] == 3 and cov['n_declared'] == 60):
        raise AssertionError(cov)
    if not (cov['n_produced_verdict'] == 3 and cov['fraction'] == 0.05):
        raise AssertionError(cov)
    if not (len(cov['gates_declared_but_absent']) == 57):
        raise AssertionError
    if not (cov['meets_floor'] is False and thin3['verdict'] != PASS):
        raise AssertionError(thin3['verdict'])
    if not (thin3['exit_code'] != 0):
        raise AssertionError
    if 'declared_gates_absent' not in {a['kind'] for a in thin3['policy_alarms']}:
        raise AssertionError
    if 'DECLARED GATES MISSING FROM THIS DOCUMENT' not in render_text(thin3):
        raise AssertionError
    # ...and the PRINTED rule names the denominator it was actually computed against, so
    # the sentence and the arithmetic cannot mean two different things again.
    if 'severity-calibration roster' not in thin3['policy']['coverage_floor_rule']:
        raise AssertionError
    if '60 gate(s), of which 3' not in thin3['policy']['coverage_floor_rule']:
        raise AssertionError(thin3['policy']['coverage_floor_rule'])
    # CONTROL 1: the same three gates with the roster naming only them is a complete suite
    # and passes. The floor is about omission, not about being small.
    small = {'policy': 'fixture', 'rows': roster['rows'][:3]}
    full3 = build(
        {
            'schema': 'geom.anthro.gates/1',
            'severity_calibration': small,
            'tiers': {'frame': [dict(ok, id='r%02d' % i) for i in range(3)]},
        },
        None,
        name='small',
        sex='male',
    )
    if not (full3['coverage']['n_declared'] == 3 and full3['coverage']['meets_floor'] is True):
        raise AssertionError
    if not (full3['verdict'] == PASS):
        raise AssertionError(full3['policy_alarms'])
    # CONTROL 2: a hand-built document that declares no roster at all is measured against
    # itself and SAYS SO. Inventing the live registry as its denominator would be a
    # different way of getting this number wrong.
    bare = build({'tiers': {'frame': [dict(ok, id='b0')]}}, None, name='bare2', sex='male')
    if not (bare['coverage']['n_declared'] == 1 and bare['verdict'] == PASS):
        raise AssertionError
    if 'declares no roster' not in bare['coverage']['roster_source']:
        raise AssertionError
    # 8. THE MARGIN IS COMPUTED, NOT QUOTED IN A COMMENT. anny-neutral clears this floor by
    #    ONE gate; the comment that claimed two was stale, and so were its five figures.
    if not (half['coverage']['floor_gates'] == 2 and half['coverage']['margin_gates'] == 0):
        raise AssertionError(half['coverage'])
    if not (thin['coverage']['margin_gates'] == 1 - 5):
        raise AssertionError(thin['coverage'])


def _selftest_receipt_row():
    """A RECEIPT ROW PRINTS ITS EVIDENCE ON A PASS (re-review N3).

    render_gate_table prints evidence for non-pass and off-band rows, which is right for a
    gate whose finding is its verdict and wrong for one whose finding is its numbers. Two
    of this wave's own headline receipts — t4_threshold_provenance's provenance census and
    t5_pose_stiffness's tilt statistics — were therefore readable only in the JSON.
    """
    base = {
        'id': 'g_ok',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
        'explanation': 'THE CENSUS SENTENCE',
        'detail': {'census_number': 12},
    }
    quiet = build({'tiers': {'frame': [base]}}, None, name='r0', sex='male')
    qtxt = render_gate_table(quiet)
    if not ('THE CENSUS SENTENCE' not in qtxt and 'census_number' not in qtxt):
        raise AssertionError('control: a plain passing row still prints no explanation and no evidence')
    loud = build(
        {'tiers': {'frame': [dict(base, detail={'census_number': 12, _RECEIPT_KEY: 'the numbers ARE the finding'})]}},
        None,
        name='r1',
        sex='male',
    )
    row = [g for g in loud['gates'] if g['id'] == 'g_ok'][0]
    if row['evidence_is_the_finding'] is not True:
        raise AssertionError
    if not (row['effective_status'] == PASS):
        raise AssertionError('the flag must not change the verdict')
    ltxt = render_gate_table(loud)
    if 'THE CENSUS SENTENCE' not in ltxt:
        raise AssertionError('a receipt row must print its explanation')
    if 'census_number=12' not in ltxt:
        raise AssertionError('a receipt row must print its evidence')
    # The key is one string shared with the engine. Two spellings would silently disable
    # every receipt in the file, which is the failure mode this whole flag exists to fix.
    try:
        from zyg_workflows.geom.anthro.gates.gate import RECEIPT_KEY as _RK
    except Exception:  # noqa: BLE001
        return
    if not (_RK == _RECEIPT_KEY):
        raise AssertionError(
            'geom.anthro.gates.RECEIPT_KEY is %r and this renderer reads %r; the receipt '
            'contract is broken and every receipt row would silently stop printing' % (_RK, _RECEIPT_KEY)
        )


def _selftest_evidence_ranking():
    """THE FIELDS THAT DECIDE A GATE ARE PRINTED, NOT ALPHABETISED OUT (W4-5).

    render_gate_table prints the first _EVIDENCE_ROWS evidence leaves and names the rest.
    They arrived in alphabetical order, so on the live t5_pose_stiffness the fourteen
    printed fields were elbow_locked_fraction_* and erect_fraction_* while
    `tilt_n_same_sign` (22) and `tilt_opposition_required_fraction` (1.0) — the two numbers
    the verdict is computed from — appeared only inside "+56 further field(s) in the JSON
    artefact". The prose rescued that particular gate because somebody wrote a good
    sentence; nothing ranked the evidence.

    The fixture below is that shape exactly: a failing gate whose decisive fields sort last
    and whose filler sorts first.
    """
    filler = {'aaa_%02d' % i: float(i) for i in range(20)}
    ev = dict(
        filler,
        tilt_n_same_sign=22,
        tilt_opposition_fraction=0.5,
        tilt_opposition_required_fraction=1.0,
        tilt_n_same_sign_allowed=0,
        zz_unrelated=1.0,
    )
    g = {
        'id': 'g_rank',
        'tier': 'frame',
        'severity': 'block',
        'status': 'fail',
        'observed': 0.5,
        'band': {'tilt_opposition_required_fraction': 1.0, 'tilt_n_same_sign_allowed': 0},
        'source': 'HOUSE: fixture',
        'explanation': 'FAILS on tilt_sign_opposition: same sign in 22 of 44',
        'detail': dict(ev, scored_check_status={'tilt_sign_opposition': 'fail'}),
    }
    d = build({'tiers': {'frame': [g]}}, None, name='rank', sex='male')
    row = d['gates'][0]
    dec = set(row['evidence_decisive'] or [])
    # The two thresholds the band declares, and the two observed numbers they bound — the
    # second pair reached only by taking the threshold qualifier off the name.
    for k in (
        'tilt_opposition_required_fraction',
        'tilt_n_same_sign_allowed',
        'tilt_n_same_sign',
        'tilt_opposition_fraction',
    ):
        if k not in dec:
            raise AssertionError((k, sorted(dec)))
    # ...and the field the gate's own explanation names, as a snake_case identifier.
    if 'scored_check_status.tilt_sign_opposition' not in dec:
        raise AssertionError(sorted(dec))
    # Nothing else was promoted: prose shares its words with field names, and a ranking
    # that promotes everything is not a ranking.
    if not ('zz_unrelated' not in dec and 'aaa_00' not in dec):
        raise AssertionError(sorted(dec))
    txt = render_gate_table(d)
    flat = ' '.join(txt.split())  # the evidence line is wrapped to the page width
    for k in (
        'tilt_n_same_sign=22',
        'tilt_opposition_required_fraction=1.0',
        'tilt_opposition_fraction=0.5',
        'tilt_n_same_sign_allowed=0',
    ):
        if k not in flat:
            raise AssertionError((k, flat[-600:]))
    # THE CAP STILL BITES AND STILL SAYS SO — nothing was dropped to make room, the order
    # changed. The filler is what falls off the end now.
    if 'further field(s)' not in flat:
        raise AssertionError(flat[-400:])
    if 'decisive first' not in flat:
        raise AssertionError
    if 'aaa_19=' in flat:
        raise AssertionError('the cap must still bite; this is a reorder, not a lift')
    # CONTROL: a gate that declares no band, no threshold and no identifier in its prose
    # ranks nothing, and its evidence is still printed in the old alphabetical order.
    plain = build(
        {
            'tiers': {
                'frame': [
                    {
                        'id': 'g_plain',
                        'tier': 'frame',
                        'severity': 'block',
                        'status': 'fail',
                        'observed': 0.5,
                        'source': 'HOUSE: fixture',
                        'explanation': 'no field names in this sentence',
                        'detail': dict(filler),
                    }
                ]
            }
        },
        None,
        name='plain',
        sex='male',
    )
    prow = plain['gates'][0]
    if prow['evidence_decisive'] is not None:
        raise AssertionError(prow['evidence_decisive'])
    ptxt = [ln for ln in render_gate_table(plain).splitlines() if 'evidence:' in ln]
    if 'aaa_00=0.0' not in ' '.join(ptxt):
        raise AssertionError(ptxt)


def _selftest_status_coverage():
    """EVERY STATUS gates.py CAN EMIT HAS AN EXPLICIT RENDERING.

    No silent fallthrough to 'unknown'. The alias table's default is 'unknown', which is
    the right behaviour for a status nobody has ever seen — but an engine status landing
    there is a renderer defect, and it is exactly what happened to 'error'. This test
    reads the engine's status constants from the engine and fails if any of them has no
    bucket, no count column, no sort order or no mark of its own.
    """
    found, src = engine_statuses()
    if src == 'geom.anthro.gates':
        required = set(_ENGINE_STATUS_CONSTANTS)
        allowed = required | set(_ENGINE_STATUS_CONSTANTS_OPTIONAL)
        if required > set(found):
            raise AssertionError(
                'geom.anthro.gates has LOST status constant(s) %s that this renderer renders '
                'explicitly.' % sorted(required - set(found))
            )
        if set(found) > allowed:
            raise AssertionError(
                'geom.anthro.gates status constants have drifted: %s. Every one of them needs '
                'an entry in _STATUS_ALIASES and a rendering here.' % sorted(set(found) - allowed)
            )
        # THE W4-1 CONTRACT, CHECKED AGAINST THE ENGINE AND NOT ASSUMED. When gates.py
        # spells the policy/provenance refusal, it must be a DIFFERENT string from a
        # genuine exception (so the two are separable downstream) and it must still land in
        # the error bucket here (so a refused verdict cannot buy a softer outcome than the
        # verdict it replaced). Both halves, or the separation is a downgrade in disguise.
        if 'POLICY_ERROR' in found:
            if not (found['POLICY_ERROR'] != found.get('ERROR')):
                raise AssertionError('the policy refusal and a genuine exception must not share a status string')
            if not (normalize_status(found['POLICY_ERROR']) == GATE_ERROR):
                raise AssertionError('a refused verdict must keep the error bucket')
            pe = {
                'id': 'g_pe',
                'tier': 'frame',
                'severity': 'block',
                'status': found['POLICY_ERROR'],
                'crashed': False,
                'source': 'HOUSE: fixture',
                'explanation': 'the engine refused it',
            }
            okp = {
                'id': 'g_okp',
                'tier': 'frame',
                'severity': 'block',
                'status': 'pass',
                'observed': 0.5,
                'band': [0.0, 1.0],
                'source': 'HOUSE: fixture',
            }
            d = build({'tiers': {'frame': [okp, pe]}}, None, name='pe', sex='male')
            if not (d['crashed'] == [] and d['errored_without_crashing'] == ['g_pe']):
                raise AssertionError
            if not (d['verdict'] == FAIL and 'g_pe' in d['blocking']):
                raise AssertionError('a refused verdict on a blocking gate must still fail the body')
            if 'RAISED (checked nothing' in render_text(d):
                raise AssertionError
    for cname in sorted(found):
        raw = found[cname]
        bucket = normalize_status(raw)
        if not (bucket != 'unknown' or raw == 'unknown'):
            raise AssertionError(
                'engine status %s=%r falls through to "unknown": a status that means the check '
                'did not run must not be rendered as an unreadable row, and must never be '
                'softer than the engine made it' % (cname, raw)
            )
        if bucket not in _COUNT_KEYS:
            raise AssertionError('%r -> %r has no count column' % (raw, bucket))
        if bucket not in _STATUS_ORDER:
            raise AssertionError('%r -> %r has no sort order' % (raw, bucket))
        if bucket not in _STATUS_MARK:
            raise AssertionError('%r -> %r has no mark in the gate table' % (raw, bucket))
    # Every bucket the alias table can produce is renderable, not just the engine's ones.
    for bucket in set(_STATUS_ALIASES.values()) | {'unknown'}:
        if not (bucket in _COUNT_KEYS and bucket in _STATUS_MARK and bucket in _STATUS_ORDER):
            raise AssertionError('bucket %r is not renderable' % bucket)
    if not (set(_COUNT_KEYS) == set(_STATUS_ORDER) == set(_STATUS_MARK)):
        raise AssertionError
    # A blocking gate cannot pass on any of the no-verdict statuses, and every status
    # actually PRINTS its own mark in the table at both severities — the second half is
    # the part that catches a bucket that exists in the arithmetic but renders as blank.
    ok = {
        'id': 'g_ok',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    seen = set()
    for cname in sorted(found):
        raw = found[cname]
        for sev in ('report', 'block'):
            d = build(
                {
                    'tiers': {
                        'frame': [
                            ok,
                            {'id': 'g_x', 'tier': 'frame', 'severity': sev, 'status': raw, 'source': 'HOUSE: fixture'},
                        ]
                    }
                },
                None,
                name='cover',
                sex='male',
            )
            if not (d['n_gates'] == sum(d['counts'].values())):
                raise AssertionError(d['counts'])
            row = [g for g in d['gates'] if g['id'] == 'g_x'][0]
            mark = _STATUS_MARK[row['effective_status']]
            seen.add(row['effective_status'])
            if '  %s ' % mark not in render_gate_table(d):
                raise AssertionError(
                    'status %s=%r at severity %r renders no %r mark in the gate table' % (cname, raw, sev, mark)
                )
            # 'report' USED TO BE EXEMPTED HERE, beside PASS, and that exemption is what
            # let N1 ship: this loop is the test that proves a blocking gate cannot come
            # out of any engine status as a pass, and it declined to ask the question for
            # the one status that then turned out to have no answer. A REPORT row on a
            # BLOCKING gate is a declared blocking claim with no verdict behind it and it
            # is held to the same standard as 'skip'. Only PASS is exempt, because PASS is
            # the thing being tested for.
            if sev != 'block' or normalize_status(raw) == PASS:
                continue
            if not (d['verdict'] != PASS):
                raise AssertionError('%s=%r on a blocking gate produced a PASS' % (cname, raw))
            if not (row['effective_status'] != PASS):
                raise AssertionError
            if not (row['id'] in (d['blocking'] + d['unrun_blocking']) or raw == 'warn'):
                raise AssertionError(
                    '%s=%r on a blocking gate is in neither the blocking nor the unrun list' % (cname, raw)
                )
    # 'unknown' is not an engine status — it is what an ABSENT status becomes — so it is
    # covered here rather than by the loop above.
    d = build({'tiers': {'frame': [dict(ok, id='g_none', status=None)]}}, None, name='cover', sex='male')
    if not (d['gates'][0]['effective_status'] == 'unknown' and d['verdict'] != PASS):
        raise AssertionError
    seen.add('unknown')
    if not (seen == set(_COUNT_KEYS)):
        raise AssertionError('buckets never exercised: %s' % sorted(set(_COUNT_KEYS) - seen))
    return src
