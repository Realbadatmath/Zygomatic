# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the alarm block of build().

Moved out of the old single-file report.py (lines 1964-2254).

`_build_alarms` was itself a 311-line def, over the 300-line function ceiling, so on
2026-10-09 each alarm it raises became a small helper below it: the helper decides
whether its alarm fires and writes its text, `_build_alarms` only appends what comes
back, in the order it always did. No text, no condition and no order changed.
"""

from zyg_workflows.geom.anthro.report.constants import CRASHED, GATE_ERROR, RAN, _COUNT_KEYS
from zyg_workflows.geom.anthro.report.gatedata import _severity_class


def _stray_bucket_alarm(counts, gates):
    """Alarm on a status bucket that was counted but has no column, or None when all render.

    A bucket with no column: counts.get() would otherwise let a status invented by a
    future gates.py accumulate into a key nothing prints and nothing sums.
    """
    stray = sorted(k for k in counts if k not in _COUNT_KEYS)
    if not stray:
        return None
    return {
        'kind': 'unrendered_status_bucket',
        'gates': [g['id'] for g in gates if g['effective_status'] in stray],
        'text': 'status bucket(s) %s have no column in the banner, the summary line or '
        'the gate table. They are counted here and alarmed on rather than '
        'silently absorbed, but this renderer must be taught to render them.' % ', '.join(repr(s) for s in stray),
    }


def _crashed_alarm(gates, crashed):
    """The alarm for gates that RAISED: nothing they were to check has been checked."""
    blocked = [g['id'] for g in gates if g['crash_state'] == CRASHED and g['is_blocking_failure']]
    return {
        'kind': 'gate_crashed',
        'gates': crashed,
        'text': 'gate(s) %s RAISED — they did not run, so nothing they were supposed '
        'to check has been checked on this body. A crash is not a band '
        'rejection and is never softened by a rejection rate. %s'
        % (
            ', '.join(crashed),
            ('blocking severity on %d of them, so the verdict is FAIL: %s.' % (len(blocked), ', '.join(blocked)))
            if blocked
            else 'none of them carries a blocking severity, so they count as '
            'warnings — but the checks still did not happen.',
        ),
    }


def _verdict_refused_alarm(gates, errored_no_crash):
    """The alarm for gates recorded ERROR that did not raise: the engine refused their verdict."""
    eblocked = [
        g['id']
        for g in gates
        if g['crash_state'] == RAN and g['effective_status'] == GATE_ERROR and g['is_blocking_failure']
    ]
    return {
        'kind': 'gate_verdict_refused',
        'gates': errored_no_crash,
        'text': 'gate(s) %s are recorded ERROR and DID NOT RAISE. The engine declares '
        'they ran, measured their subject and produced a finding, and then '
        'refused or replaced the verdict — on our own provenance rule, not on '
        'anything about this body. They are NOT a crash and they did check '
        'this body: the finding each of them produced is in its row and in '
        'gates[].evidence under '
        'status_the_gate_would_have_returned. They keep the error bucket, '
        'because a refused verdict is still not a verdict and must not buy a '
        'softer outcome than the one it replaced. %s'
        % (
            ', '.join(errored_no_crash),
            ('Blocking severity on %d of them, so the verdict is FAIL: %s.' % (len(eblocked), ', '.join(eblocked)))
            if eblocked
            else 'None of them carries a blocking severity, so they count as warnings.',
        ),
    }


def _crash_flag_alarm(error_crash_undeclared):
    """The alarm for error-class rows that will not say whether they raised."""
    return {
        'kind': 'crash_flag_not_declared',
        'gates': error_crash_undeclared,
        'text': 'gate(s) %s carry an error-class status and did NOT declare whether '
        'they raised. This renderer will not infer it from the status: '
        '"error" means both "the gate raised" and "the engine refused the '
        'verdict the gate produced", and deriving one from the other is how '
        'this report came to print "GATES THAT CRASHED (checked nothing)" '
        'about two gates that had checked their subject and found it wanting. '
        'The rows are counted, bucketed and blocked exactly as before; what is '
        'unknown is only whether they ran, and it is printed as unknown. The '
        'producer must set the boolean gate row field "crashed".' % ', '.join(error_crash_undeclared),
    }


def _unrecognised_status_alarm(gates, unrecognised_status):
    """The alarm for status spellings this renderer does not know — a renderer defect."""
    spellings = sorted({repr(g['status_raw']) for g in gates if not g['status_recognised']})
    return {
        'kind': 'unrecognised_status',
        'gates': unrecognised_status,
        'text': 'gate(s) %s carry a status spelling this renderer does not know (%s). '
        'They are rendered as ERRORS — never as a pass and never as anything '
        'softer — because an engine that has grown a status faster than this '
        'renderer has learned it must lose that argument. This is a renderer '
        'defect to fix in _STATUS_ALIASES, not a fact about the body.'
        % (', '.join(unrecognised_status), ', '.join(spellings)),
    }


def _unrun_blocking_alarm(unrun_blocking, unrun_blocking_by_declared):
    """The alarm for blocking gates that produced no verdict at all."""
    return {
        'kind': 'blocking_gate_did_not_run',
        'gates': unrun_blocking,
        'text': 'gate(s) %s carry a blocking severity and produced NO VERDICT '
        '(skipped, reported-but-never-gated, missing a declaration, or '
        'unreadable). They cannot be '
        'scored, so they do not make this body fail — but the body has not '
        'passed them either, and any summary that reports "0 blocking" '
        'without naming them is claiming a check that never happened.%s'
        % (
            ', '.join(unrun_blocking),
            (
                ''
                if not unrun_blocking_by_declared
                else ' %d of them (%s) carry a blocking severity that the reference '
                'rejection rate had downgraded to a warning. A calibration '
                'measures how often a BAND would reject a real body; it is a '
                'statement about a verdict, and this gate produced none. The '
                'severity the registry DECLARED is what makes an absent check '
                'count here.' % (len(unrun_blocking_by_declared), ', '.join(unrun_blocking_by_declared))
            ),
        ),
    }


def _canon_threshold_alarms(gates):
    """The two CANON alarms, in order: a blocking book threshold, and a mute one.

    A CANON threshold that reached this report at BLOCKING severity over a quantity a
    survey already answers means the engine's own refusal did not fire — a registry
    drift, or a report produced by an engine that predates the rule. The rule is about
    RANK, not about banning books: a CANON threshold on genuinely silent ground (an
    angle, a sign, a joint range) is entitled to block and is not alarmed on. A CANON
    row that will not say WHAT it measures is alarmed on either way, because the rule
    cannot be checked against it and silence is not evidence of innocence.
    """
    canon_blocking, canon_mute = [], []
    for g in gates:
        if g['provenance_class'] != 'CANON' or g['malformed']:
            continue
        if g['severity_class'] not in ('high', 'unrecognised'):
            continue
        qs = g.get('threshold_quantities')
        clash = g.get('threshold_measured_conflict')
        if qs is None and clash is None:
            canon_mute.append(g['id'])
        elif clash:
            canon_blocking.append(g['id'])
    out = []
    if canon_blocking:
        out.append(
            {
                'kind': 'canon_threshold_blocking',
                'gates': sorted(canon_blocking),
                'text': 'gate(s) %s carry a CANON threshold at BLOCKING severity over a '
                'quantity a survey on disk ALREADY ANSWERS. CANON is a number printed '
                'in an artist or anatomy reference: it has no sample, no n and no '
                'sampling frame, and it ranks below MEASURED. It may set a threshold '
                'only where ANSUR II / CDC / NHANES is silent. '
                'geom.anthro.gates.validate_registry refuses this combination before '
                'any mesh is loaded, so a row like this means the report was produced '
                'by an engine without the rule, or the registry has drifted.' % ', '.join(sorted(canon_blocking)),
            }
        )
    if canon_mute:
        out.append(
            {
                'kind': 'canon_threshold_without_quantity',
                'gates': sorted(canon_mute),
                'text': 'gate(s) %s carry a CANON threshold at blocking severity and do not '
                'declare WHICH QUANTITY it is a threshold on, so the rule "a book may '
                'not outrank a survey" cannot be checked against them.' % ', '.join(sorted(canon_mute)),
            }
        )
    return out


def _measured_threshold_alarm(gates):
    """The MEASURED mirror of the two CANON alarms, or None when every row carries evidence.

    It exists for the same reason: the CANON rule is only worth what the word MEASURED is
    worth, and that word was measured to be free — the identical blocking gate over crotch
    height that validate_registry refuses as CANON was accepted with one field changed to
    MEASURED. A MEASURED row with no structured evidence behind it is a threshold claiming
    a survey it has not produced, and this renderer says so off the row rather than
    re-deriving it.
    """
    measured_mute = []
    for g in gates:
        if g['provenance_class'] != 'MEASURED' or g['malformed']:
            continue
        if not g.get('has_threshold'):
            continue
        ev = g.get('threshold_evidence')
        if not isinstance(ev, dict) or not ev.get('class') or not ev.get('n'):
            measured_mute.append(g['id'])
    if not measured_mute:
        return None
    return {
        'kind': 'measured_threshold_without_evidence',
        'gates': sorted(measured_mute),
        'text': 'gate(s) %s ship a MEASURED threshold with NO structured evidence '
        'record — no evidence class, or no sample size. MEASURED means a '
        'survey or a published series answered this question; without a named '
        'class, a population and an n, the tag is a self-assessment and the '
        'rule "a book may not outrank a survey" can be bypassed by typing a '
        'different word (measured 2026-08-06: it was). '
        'geom.anthro.gates.validate_registry refuses this before any mesh '
        'loads, so a row like this means the report was produced by an engine '
        'without the rule, or the registry has drifted.' % ', '.join(sorted(measured_mute)),
    }


def _registry_defect_alarms(gates):
    """The four registry-hygiene alarms, in order: contested, undeclared, severity, malformed."""
    out = []
    contested = [g['id'] for g in gates if g['provenance_class'] == 'CONTESTED']
    if contested:
        out.append(
            {
                'kind': 'contested_threshold_shipped',
                'gates': contested,
                'text': 'gate(s) %s declare CONTESTED provenance. A contested number '
                '(golden ratio, WHR 0.7, "Adonis" 1.618, symmetry-as-beauty, '
                'Drillis & Contini) must not gate anything. This is a defect in the '
                'gate registry, not a property of the body.' % ', '.join(contested),
            }
        )
    # The rule is that every THRESHOLD carries provenance. A report-only gate that
    # declares no threshold and no band has no number to attribute, so demanding one of it
    # would be a false alarm; those are counted and named in the footer instead.
    undeclared = [
        g['id'] for g in gates if g['provenance_class'] == 'UNDECLARED' and not g['malformed'] and g['has_threshold']
    ]
    if undeclared:
        out.append(
            {
                'kind': 'undeclared_provenance',
                'gates': undeclared,
                'text': 'gate(s) %s ship a threshold with no declared provenance class. '
                'Every threshold must be MEASURED (with source, population and n) or '
                'HOUSE (with a rationale).' % ', '.join(undeclared),
            }
        )
    unrec = [g['id'] for g in gates if g['severity_class'] == 'unrecognised' and not g['malformed']]
    if unrec:
        out.append(
            {
                'kind': 'unrecognised_severity',
                'gates': unrec,
                'text': 'gate(s) %s carry a severity this renderer does not recognise. They '
                'were treated as HIGH (a failure was not downgraded), which is the '
                'safe direction, but the severity should be corrected.' % ', '.join(unrec),
            }
        )
    malformed = [g['id'] for g in gates if g['malformed']]
    if malformed:
        out.append(
            {
                'kind': 'malformed_gate',
                'gates': malformed,
                'text': '%d gate entr(y/ies) could not be read as a mapping and '
                'were counted as unknown, never as pass.' % len(malformed),
            }
        )
    return out


def _calibration_alarms(gates, severity_calibration):
    """The two severity-calibration alarms: a blocking gate with no rejection rate, and drift.

    These only fire when the engine actually shipped a calibration block; a gate report
    that makes no such claim is not accused of breaking a promise it never made, so the
    caller passes None/{} through and gets nothing back.
    """
    out = []
    crows = {str(r.get('id')): r for r in (severity_calibration.get('rows') or [])}
    uncal = sorted(r['id'] for r in crows.values() if r.get('kind') == 'undeclared' and r.get('effective') == 'block')
    if uncal:
        out.append(
            {
                'kind': 'uncalibrated_blocking_gate',
                'gates': uncal,
                'text': 'gate(s) %s block without any statement of how much of the real '
                'reference sample they would reject. A blocking claim that cannot '
                'be checked against the population is the defect this pack exists '
                'to prevent.' % ', '.join(uncal),
            }
        )
    # Drift is compared on the severity CLASS, not the spelling. A gate engine is
    # allowed its own vocabulary ('critical' and 'block' are both high), and alarming
    # on a synonym would make this check noise that gets ignored — which is exactly
    # how a real high-vs-low disagreement would then get missed.
    drift = sorted(
        g['id']
        for g in gates
        if g['id'] in crows
        and crows[g['id']].get('effective') is not None
        and g['severity_class'] != 'unrecognised'
        and _severity_class(crows[g['id']]['effective'])[0] != g['severity_class']
    )
    if drift:
        out.append(
            {
                'kind': 'severity_calibration_disagreement',
                'gates': drift,
                'text': 'gate(s) %s carry a severity whose CLASS disagrees with the '
                "engine's own calibration table (one says blocking, the other "
                'says advisory). One of the two is stale; the rows above were '
                'rendered on the severity attached to the gate result, which is '
                'the one that governed the verdict.' % ', '.join(drift),
            }
        )
    return out


def _build_alarms(
    counts,
    gates,
    gr,
    crashed,
    errored_no_crash,
    error_crash_undeclared,
    unrecognised_status,
    unrun_blocking,
    unrun_blocking_by_declared,
):
    """The alarm list of build(), lifted whole out of it.

    It receives the nine locals the block read as parameters and returns the two it
    leaves behind: the ordered alarm list and the engine's severity-calibration block
    (None when it shipped none). build() was 822 lines in one def, over the 800-line
    ceiling a module may have, and this block is the one self-contained unit inside it.

    Each alarm is written by its own helper above; this function only decides which ones
    are asked for and keeps their order, which the renderer prints as it stands.
    """
    alarms = []
    stray = _stray_bucket_alarm(counts, gates)
    if stray:
        alarms.append(stray)
    if crashed:
        alarms.append(_crashed_alarm(gates, crashed))
    if errored_no_crash:
        alarms.append(_verdict_refused_alarm(gates, errored_no_crash))
    if error_crash_undeclared:
        alarms.append(_crash_flag_alarm(error_crash_undeclared))
    if unrecognised_status:
        alarms.append(_unrecognised_status_alarm(gates, unrecognised_status))
    if unrun_blocking:
        alarms.append(_unrun_blocking_alarm(unrun_blocking, unrun_blocking_by_declared))
    alarms.extend(_canon_threshold_alarms(gates))
    measured = _measured_threshold_alarm(gates)
    if measured:
        alarms.append(measured)
    alarms.extend(_registry_defect_alarms(gates))

    severity_calibration = gr.get('severity_calibration') if isinstance(gr.get('severity_calibration'), dict) else None
    if severity_calibration:
        alarms.extend(_calibration_alarms(gates, severity_calibration))
    return alarms, severity_calibration
