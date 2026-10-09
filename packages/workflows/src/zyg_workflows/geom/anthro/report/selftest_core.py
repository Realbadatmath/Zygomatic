# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the self-test entry point and the crash-classification self-test.

Moved out of the old single-file report.py (lines 4164-4535).
"""

from zyg_workflows.geom.anthro.report.constants import (
    CRASH_UNDECLARED,
    FAIL,
    GATE_ERROR,
    MISSING,
    PASS,
    RAN,
    SCHEMA,
    WARN,
)
from zyg_workflows.geom.anthro.report.textfmt import _fmt_rate
from zyg_workflows.geom.anthro.report.gatedata import normalize_status
from zyg_workflows.geom.anthro.report.strip import _strip
from zyg_workflows.geom.anthro.report.document import build
from zyg_workflows.geom.anthro.report.digest import exit_code
from zyg_workflows.geom.anthro.report.renderers import (
    _banner,
    render_gate_table,
    render_severity_calibration,
    render_summary,
    render_text,
)
from zyg_workflows.geom.anthro.report.fixture import contract_fixture
from zyg_workflows.geom.anthro.report.selftest_rules import _selftest_digest, _selftest_unrun_blocking_rule
from zyg_workflows.geom.anthro.report.selftest_checks import (
    _selftest_coverage_floor,
    _selftest_evidence_ranking,
    _selftest_receipt_row,
    _selftest_status_coverage,
)


def _selftest():
    """Renderer-only self-test: no mesh, no reference pack. Asserts the arithmetic that
    the rest of the package depends on being right."""
    fx = contract_fixture()
    doc = build(fx, None, name='fixture', sex='male')
    if not (doc['schema'] == SCHEMA):
        raise AssertionError
    if not (doc['verdict'] == FAIL):
        raise AssertionError(doc['verdict'])
    if not (doc['exit_code'] == 2):
        raise AssertionError
    by = {g['id']: g for g in doc['gates']}
    if by['bideltoid_breadth_over_stature']['downgraded_by_severity'] is not True:
        raise AssertionError
    if not (by['bideltoid_breadth_over_stature']['effective_status'] == 'warn'):
        raise AssertionError
    if not (by['no_self_intersection']['effective_status'] == 'fail'):
        raise AssertionError('unrecognised severity must NOT downgrade a failure')
    if not (by['watertight']['effective_status'] == 'unknown'):
        raise AssertionError('absent status must not become a pass')
    # A DECLARED 'missing' is its own row type, not '????', and still not a pass.
    vhi = by['volume_height_index']
    if not (vhi['effective_status'] == MISSING):
        raise AssertionError(vhi['effective_status'])
    if not (doc['counts'][MISSING] == 1):
        raise AssertionError(doc['counts'])
    if not (doc['verdict'] != PASS):
        raise AssertionError('a missing declaration must never render as a pass')
    if by['crotch_height_over_stature']['delta_from_band'] is None:
        raise AssertionError
    # Severity taken away by measurement: both the flag and the rate must survive.
    bd = by['bideltoid_breadth_over_stature']
    if bd['severity_calibrated'] is not True:
        raise AssertionError
    if not (bd['severity_declared'] == 'block' and bd['severity'] == 'warn'):
        raise AssertionError
    if abs(bd['reference_rejection_rate'] - 0.1197) >= 1e-9:
        raise AssertionError
    if by['stature_declared_vs_built']['severity_calibrated'] is not False:
        raise AssertionError('a gate that declared no calibration must not be reported as calibrated')
    if by['stature_declared_vs_built']['reference_rejection_rate'] is not None:
        raise AssertionError('no calibration is not a rejection rate of zero')
    if not (_fmt_rate(None) == 'not measured' and _fmt_rate(0.0).startswith('0.000%')):
        raise AssertionError
    kinds = {a['kind'] for a in doc['policy_alarms']}
    if 'contested_threshold_shipped' not in kinds:
        raise AssertionError
    if 'undeclared_provenance' not in kinds:
        raise AssertionError
    if 'unrecognised_severity' not in kinds:
        raise AssertionError
    if 'malformed_gate' not in kinds:
        raise AssertionError
    txt = render_text(doc)
    if 'VERDICT: FAIL' not in txt:
        raise AssertionError
    if 'SYNTHETIC' not in txt:
        raise AssertionError
    # '????' is now reserved for rows whose status genuinely could not be read — the
    # absent-status gate and the malformed entry. A gate that DECLARED 'missing' must not
    # be in that bucket, which is the whole of Finding 5.
    if not (txt.count('????') == doc['counts']['unknown'] == 2):
        raise AssertionError(txt.count('????'))
    if 'MISSING' not in txt:
        raise AssertionError
    if 'SEVERITY CALIBRATION' not in txt:
        raise AssertionError
    if '11.97' not in txt:
        raise AssertionError('the measured rejection rate must be visible in the text report')
    # The section is silent, not invented, when the engine shipped no calibration.
    bare = build({'gates': [dict(g) for g in contract_fixture()['tiers']['frame']]}, None, name='bare', sex='male')
    if not (render_severity_calibration(bare) == ''):
        raise AssertionError
    if bare['severity_calibration'] is not None:
        raise AssertionError
    line = render_summary(doc)
    if not ('\n' not in line and 'verdict=FAIL' in line):
        raise AssertionError
    _selftest_digest(doc, fx)
    _selftest_coverage_floor()
    if not (_strip(50.0, 5.0, 95.0).count('#') == 1):
        raise AssertionError
    if not (_strip(0.0, 5.0, 95.0)[0] == '<'):
        raise AssertionError
    if not (_strip(100.0, 5.0, 95.0)[-1] == '>'):
        raise AssertionError
    # a body on the band edge must not erase the edge from the picture
    if not ('{' in _strip(5.0, 5.0, 95.0) and '[' not in _strip(5.0, 5.0, 95.0)):
        raise AssertionError
    if '}' not in _strip(95.0, 5.0, 95.0):
        raise AssertionError
    if not (_strip(50.0, None, None).count('#') == 1):
        raise AssertionError('a ratio with no band still plots')
    _selftest_crash(doc, txt)
    _selftest_evidence_ranking()
    src = _selftest_status_coverage()
    return 'report selftest OK: %d gates, verdict %s, sha %s; engine statuses read from %s' % (
        doc['n_gates'],
        doc['verdict'],
        doc['stable_sha256'][:12],
        src,
    )


def _selftest_crash(doc, txt):
    """A CRASHED BLOCKING GATE CANNOT PRODUCE A PASSING VERDICT.

    This is the one assertion this module exists for. gates.py records a raising gate as
    ERROR and classifies it as blocking; production calls run_gates(strict=False) so that
    one broken gate does not abort a build. If this renderer softens that row, a body
    whose blocking check never executed is issued with an amber PASS-WITH-WARNINGS chip
    reading "0 blocking" — a pass-shaped verdict over a check that did not happen.
    """
    # 1. The crashed gate inside the full contract fixture.
    by = {g['id']: g for g in doc['gates']}
    crash = by['shell_containment']
    if not (crash['status'] == GATE_ERROR and crash['effective_status'] == GATE_ERROR):
        raise AssertionError('a crashed gate must keep its own bucket, not become %r' % crash['effective_status'])
    if not (crash['crashed'] is True and crash['is_blocking_failure'] is True):
        raise AssertionError
    if crash['downgraded_by_severity'] is not False:
        raise AssertionError('a crash is never downgraded')
    if 'shell_containment' not in doc['blocking']:
        raise AssertionError(doc['blocking'])
    if 'shell_containment' not in doc['crashed']:
        raise AssertionError
    if not (doc['counts'][GATE_ERROR] == 2):
        raise AssertionError(doc['counts'])
    if 'ERROR 2' not in txt:
        raise AssertionError('the crash must be a column in the verdict banner')
    if not ('BLOCKING: ' in txt and 'shell_containment' in txt):
        raise AssertionError
    if 'gate_crashed' not in {a['kind'] for a in doc['policy_alarms']}:
        raise AssertionError

    # 1b. THE OTHER ERROR: A GATE THAT RAN, PRODUCED A FINDING, AND HAD ITS VERDICT
    #     REFUSED (W4-1). Every error fixture this test used to build was a genuine crash,
    #     so a renderer that answered "did it crash?" with "is the status 'error'?" passed
    #     this file while printing, on all five live bodies:
    #         GATES THAT CRASHED (checked nothing): t5_patellar_ligament, t5_subcostal_angle
    #     plus a gate_crashed alarm reading "they did not run, so nothing they were
    #     supposed to check has been checked on this body" and a row reading "THIS GATE
    #     RAISED. It checked nothing on this body." All three were false, and the gate's
    #     real blocking finding — the ligament is not modelled — was filed as
    #     infrastructure. A self-test that cannot observe the defect it is named for is
    #     worse than none, so the fixture now carries BOTH kinds of error row with the SAME
    #     status and the OPPOSITE crashed flag, and the assertions below are about the
    #     difference between them.
    ran = by['patellar_ligament_provenance']
    if not (ran['status'] == GATE_ERROR and ran['effective_status'] == GATE_ERROR):
        raise AssertionError('a refused verdict keeps the error bucket: it is still not a verdict')
    if not (ran['crashed'] is False and ran['crash_state'] == RAN):
        raise AssertionError
    if not (ran['crash_declared_by_engine'] is True and ran['error_kind'] == 'ran'):
        raise AssertionError
    if not (crash['error_kind'] == 'crash'):
        raise AssertionError(crash['error_kind'])
    # THE BANNER: it is not in the crashed list, it is in its own, and the heading over it
    # does not say it checked nothing.
    if 'patellar_ligament_provenance' in doc['crashed']:
        raise AssertionError(doc['crashed'])
    if not (doc['errored_without_crashing'] == ['patellar_ligament_provenance']):
        raise AssertionError(doc['errored_without_crashing'])
    if not (doc['error_crash_undeclared'] == []):
        raise AssertionError(doc['error_crash_undeclared'])
    banner = _banner(doc)
    crash_line = [ln for ln in banner.splitlines() if 'RAISED (checked nothing' in ln]
    if not (crash_line):
        raise AssertionError(banner)
    if 'patellar_ligament_provenance' in ' '.join(crash_line):
        raise AssertionError('a gate that ran and produced a finding is named under a "checked nothing" heading')
    if 'GATES WHOSE VERDICT THE ENGINE REFUSED' not in banner:
        raise AssertionError
    # ...and nothing got easier: it still blocks, it is still in doc['blocking'], the body
    # still fails. The fix is to the sentence, never to the consequence.
    if ran['is_blocking_failure'] is not True:
        raise AssertionError
    if 'patellar_ligament_provenance' not in doc['blocking']:
        raise AssertionError(doc['blocking'])
    if not (doc['verdict'] == FAIL):
        raise AssertionError
    kinds = {a['kind'] for a in doc['policy_alarms']}
    if 'gate_verdict_refused' not in kinds:
        raise AssertionError(kinds)
    refused = [a for a in doc['policy_alarms'] if a['kind'] == 'gate_verdict_refused'][0]
    if 'patellar_ligament_provenance' not in refused['gates']:
        raise AssertionError
    crashed_alarm = [a for a in doc['policy_alarms'] if a['kind'] == 'gate_crashed'][0]
    if 'patellar_ligament_provenance' in crashed_alarm['gates']:
        raise AssertionError(
            'the "nothing has been checked on this body" alarm must not name a gate that checked this body'
        )
    # THE ROW ITSELF. The wave-4 mitigation was a rebuttal sentence inside the row body
    # while the heading above it stayed wrong; contradicting your own heading is not
    # surfacing evidence. The row must not carry the boilerplate at all.
    rowtxt = render_gate_table(doc)
    seg = rowtxt.split('patellar_ligament_provenance', 1)[1].split('shell_containment')[0]
    if 'THIS GATE DID NOT RAISE' not in seg:
        raise AssertionError(seg[:400])
    if 'checked nothing' in seg:
        raise AssertionError(seg[:400])
    if 'THIS GATE RAISED' in seg:
        raise AssertionError(seg[:400])
    # ...and the finding the engine replaced is ON THE PAGE, not only in the JSON.
    if 'status_the_gate_would_have_returned=fail' not in seg:
        raise AssertionError(seg[:600])
    # 1c. A ROW THAT DECLARES NOTHING IS UNKNOWN, NOT ASSUMED. Deriving "it must have
    #     raised" from the status is the defect; deriving "it must not have" would hide a
    #     real crash. Neither is done.
    mute = {
        'id': 'g_mute',
        'tier': 'frame',
        'severity': 'block',
        'status': 'error',
        'source': 'HOUSE: fixture',
        'explanation': 'no crashed flag on this row',
    }
    okrow = {
        'id': 'g_ok0',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    md = build({'tiers': {'frame': [okrow, mute]}}, None, name='mute', sex='male')
    mrow = [g for g in md['gates'] if g['id'] == 'g_mute'][0]
    if not (mrow['crashed'] is None and mrow['crash_state'] == CRASH_UNDECLARED):
        raise AssertionError
    if not (mrow['error_kind'] == 'undeclared'):
        raise AssertionError
    if not (md['crashed'] == [] and md['errored_without_crashing'] == []):
        raise AssertionError
    if not (md['error_crash_undeclared'] == ['g_mute']):
        raise AssertionError
    if 'crash_flag_not_declared' not in {a['kind'] for a in md['policy_alarms']}:
        raise AssertionError
    if not (md['verdict'] == FAIL and 'g_mute' in md['blocking']):
        raise AssertionError('an undeclared crash flag must not soften a blocking error')
    mtxt = render_text(md)
    if 'DID NOT DECLARE WHETHER THEY RAISED' not in mtxt:
        raise AssertionError
    if 'RAISED (checked nothing' in mtxt:
        raise AssertionError('an undeclared row must not be reported as a crash')
    # 1d. AN UNMAPPED STATUS IS AN ERROR, NEVER A PASS AND NEVER SOFTER (W4-1). The engine
    #     grew a status this renderer had never heard of once already; landing in 'unknown'
    #     would take the row out of the blocking list on a blocking gate.
    if not (normalize_status('a_status_this_renderer_has_never_heard_of') == GATE_ERROR):
        raise AssertionError
    if not (normalize_status(None) == 'unknown' and normalize_status('  ') == 'unknown'):
        raise AssertionError
    strange = build(
        {'tiers': {'frame': [okrow, dict(mute, id='g_new', status='policy_error', crashed=False)]}},
        None,
        name='new',
        sex='male',
    )
    srow2 = [g for g in strange['gates'] if g['id'] == 'g_new'][0]
    if not (srow2['effective_status'] == GATE_ERROR and srow2['crashed'] is False):
        raise AssertionError
    if srow2['status_recognised'] is not True:
        raise AssertionError('policy_error is a known spelling')
    if not (strange['verdict'] == FAIL and 'g_new' in strange['blocking']):
        raise AssertionError
    if not (strange['errored_without_crashing'] == ['g_new']):
        raise AssertionError
    unk = build({'tiers': {'frame': [okrow, dict(mute, id='g_zzz', status='wat')]}}, None, name='wat', sex='male')
    zrow = [g for g in unk['gates'] if g['id'] == 'g_zzz'][0]
    if not (zrow['effective_status'] == GATE_ERROR and zrow['status_recognised'] is False):
        raise AssertionError
    if not (unk['unrecognised_status'] == ['g_zzz']):
        raise AssertionError
    if 'unrecognised_status' not in {a['kind'] for a in unk['policy_alarms']}:
        raise AssertionError
    if not (unk['verdict'] == FAIL and 'g_zzz' in unk['blocking']):
        raise AssertionError('an unknown spelling on a blocking gate must not be softer than an error')
    # The unrun blocking gate: escalated, named, and NOT counted as a blocking failure.
    unrun = by['volume_plausibility']
    if not (unrun['effective_status'] == 'warn' and unrun['produced_no_verdict'] is True):
        raise AssertionError
    if unrun['escalated_unrun_blocking_gate'] is not True:
        raise AssertionError
    if unrun['is_blocking_failure'] is not False:
        raise AssertionError('a skip cannot manufacture a FAIL')
    # Every blocking-severity gate in the fixture that reached no verdict, and only those:
    # the declared-missing band gate, the gate whose status field is absent, and the
    # not-applicable one. The malformed entry is NOT here — it has no severity to claim.
    if not (
        set(doc['unrun_blocking'])
        == {
            'watertight',
            'volume_height_index',
            'volume_plausibility',
            'girths_wide_calibrated',
        }
    ):
        raise AssertionError(doc['unrun_blocking'])
    if any(x.startswith('<malformed') for x in doc['unrun_blocking']):
        raise AssertionError
    if by['watertight']['escalated_unrun_blocking_gate'] is not True:
        raise AssertionError('an absent status on a critical gate is a blocking check that did not run')
    if not (by['watertight']['effective_status'] == 'unknown'):
        raise AssertionError('escalation must not cost the unknown row its own bucket')
    if 'blocking_gate_did_not_run' not in {a['kind'] for a in doc['policy_alarms']}:
        raise AssertionError
    if 'BLOCKING GATES THAT DID NOT RUN' not in txt:
        raise AssertionError

    # 2. The isolated proof, with nothing else in the report that could fail it: one
    #    passing gate plus one blocking gate that raised.
    ok = {
        'id': 'g_ok',
        'tier': 'frame',
        'severity': 'block',
        'status': 'pass',
        'observed': 0.5,
        'band': [0.0, 1.0],
        'source': 'HOUSE: fixture',
    }
    boom = {
        'id': 'g_boom',
        'tier': 'frame',
        'severity': 'block',
        'status': 'error',
        'crashed': True,  # the producer's flag: this one really did raise
        'source': 'HOUSE: fixture',
        'explanation': 'gate raised RuntimeError',
    }
    hot = build({'verdict': 'FAIL', 'tiers': {'frame': [ok, boom]}}, None, name='crash', sex='male')
    if not (hot['verdict'] == FAIL):
        raise AssertionError(hot['verdict'])
    if not (hot['exit_code'] == 2 and exit_code(hot) == 2):
        raise AssertionError
    if not (hot['blocking'] == ['g_boom']):
        raise AssertionError(hot['blocking'])
    if not (hot['counts'][GATE_ERROR] == 1 and hot['counts']['fail'] == 0):
        raise AssertionError
    hline = render_summary(hot)
    if not ('verdict=FAIL' in hline and 'error=1' in hline and 'blocking=1' in hline):
        raise AssertionError(hline)
    htxt = render_text(hot)
    if 'VERDICT: FAIL' not in htxt:
        raise AssertionError
    if not (' ERROR   ' in htxt or htxt.count('ERROR') >= 2):
        raise AssertionError('ERROR mark must be printed')
    # Only the failures view: the crashed row must survive the filter.
    if 'g_boom' not in render_text(hot, show_passing_gates=False):
        raise AssertionError
    # 3. Control: the SAME report without the crash passes. If this ever fails, the test
    #    above is passing for the wrong reason.
    cold = build({'verdict': PASS, 'tiers': {'frame': [ok]}}, None, name='crash', sex='male')
    if not (cold['verdict'] == PASS and cold['blocking'] == []):
        raise AssertionError(cold['verdict'])
    # 4. A crash on a LOW severity keeps its bucket and is not a pass, but does not fail
    #    the body — that is gates.py's classification and this renderer must agree.
    low = build({'tiers': {'frame': [ok, dict(boom, severity='minor')]}}, None, name='crash', sex='male')
    if not (low['verdict'] == WARN and low['blocking'] == []):
        raise AssertionError(low['verdict'])
    if not (low['counts'][GATE_ERROR] == 1 and low['crashed'] == ['g_boom']):
        raise AssertionError
    # 5. The renderer never ships the softer of two disagreeing verdicts.
    soft = build({'verdict': 'FAIL', 'tiers': {'frame': [ok]}}, None, name='soft', sex='male')
    if not (soft['verdict'] == FAIL):
        raise AssertionError('engine FAIL + renderer PASS must ship FAIL')
    if 'verdict_disagreement' not in {a['kind'] for a in soft['policy_alarms']}:
        raise AssertionError
    _selftest_unrun_blocking_rule(doc)
    _selftest_receipt_row()
    return None
