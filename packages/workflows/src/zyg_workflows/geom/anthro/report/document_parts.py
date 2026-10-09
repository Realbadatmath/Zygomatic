# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — the stages document.build() is assembled from.

`build` was one 541-line function, which meant that not one of the decisions it makes
could be exercised on its own: the coverage floor, the verdict reconciliation, the
provenance map and the digest finalisation were all reachable only by rendering a whole
document. Each block is here as a named helper with explicit parameters and a return
value. The orchestrator in document.py calls them in exactly the order the old body ran
them in, and no helper decides anything the old code did not decide at the same point.
"""

import math
import time
from dataclasses import dataclass, field
from zyg_workflows.geom.anthro.report.constants import (
    CRASHED,
    CRASH_UNDECLARED,
    EXIT_CODES,
    FAIL,
    GATE_ERROR,
    PASS,
    RAN,
    WARN,
    _COUNT_KEYS,
    _DIGEST_EXCLUDED_TOP_LEVEL,
    _INSTRUMENTATION_KEYS,
    _INSTRUMENTATION_SUFFIXES,
    _LOW_SEVERITIES,
    _MIN_VERDICTS_FOR_PASS,
    _MIN_VERDICT_FRACTION_FOR_PASS,
    _NOT_A_PASS,
    _UNRUN_BLOCKING_STATUSES,
    _VERDICT_RANK,
    _VERDICT_STATUSES,
)
from zyg_workflows.geom.anthro.report.textfmt import _num
from zyg_workflows.geom.anthro.report.strip import ratio_rows
from zyg_workflows.geom.anthro.report.alarms import _build_alarms
from zyg_workflows.geom.anthro.report.digest import _digest_scan, _volatile_content, stable_sha


@dataclass
class Identity:
    """Who the document is about, after the arguments and the measurement metadata agree.

    `meta` and `gr` are the two mappings the rest of build() reads; the four identity
    fields are whatever the caller passed, falling back to the measurement's own metadata
    and then to the gate report, in that order.
    """

    meta: dict
    gr: dict
    name: object
    sex: object
    ancestry: object
    stature_m: object


@dataclass
class GateBuckets:
    """The gate rows sorted into the populations the document reports separately.

    The three error classes are kept apart deliberately (W4-1): `crashed` is only what the
    PRODUCER says raised, and a gate that ran and had its verdict refused is a different
    fact from a gate that checked nothing.
    """

    counts: dict
    blocking: list
    crashed: list
    errored_no_crash: list
    error_crash_undeclared: list
    unrecognised_status: list
    unrun_blocking: list
    unrun_blocking_by_declared: list


@dataclass
class Coverage:
    """The coverage floor's verdict on a document, plus the alarms it wants raised.

    `coverage` is the block that goes into the document verbatim; `alarms` are appended by
    the caller in the order they were produced, which is the order the old body appended
    them in.
    """

    coverage: dict
    n_verdicts: int
    n_declared: int
    cov_fraction: object
    meets_floor: bool
    gates_present_but_not_declared: list
    alarms: list = field(default_factory=list)


def resolve_identity(gate_report, measurement, *, name, sex, ancestry, stature_m):
    """Fill in name, sex, ancestry and stature from the measurement and the gate report.

    An explicitly passed argument always wins; `None` means "read it off the documents".
    Returns an :class:`Identity`, which also carries the two mappings (`meta`, `gr`) the
    rest of the build reads, normalised so neither can be None.
    """
    meta = (measurement or {}).get('meta') or {}
    gr = gate_report if isinstance(gate_report, dict) else {}
    if stature_m is None:
        stature_m = _num(meta.get('stature_m'))
    if name is None:
        name = meta.get('name') or gr.get('character') or gr.get('name')
    if sex is None:
        sex = meta.get('sex_declared') or gr.get('sex')
    if ancestry is None:
        ancestry = gr.get('ancestry')
    return Identity(meta=meta, gr=gr, name=name, sex=sex, ancestry=ancestry, stature_m=stature_m)


def classify_gates(gates):
    """Count the gate rows by effective status and sort them into the reported buckets.

    Takes the rows `_read_gate` produced and returns a :class:`GateBuckets`. Nothing is
    derived from the status spelling alone: whether a gate raised is the boolean the engine
    stamped on the row, and an unrecognised status is reported as such rather than read as
    a run that produced a verdict.
    """
    counts = {k: 0 for k in _COUNT_KEYS}
    for g in gates:
        counts[g['effective_status']] = counts.get(g['effective_status'], 0) + 1

    # Blocking failures, in one place, so that no consumer has to re-derive the policy
    # from `effective_status == 'fail'` and miss the crashed ones.
    blocking = [g['id'] for g in gates if g['is_blocking_failure']]
    # THE THREE ERROR-CLASS POPULATIONS, KEPT APART (W4-1). `crashed` is only the gates the
    # PRODUCER says raised. A gate that ran, checked its subject and produced a finding the
    # engine then refused is not in it, and neither is a row that declared nothing — each
    # gets its own list, its own banner line and its own alarm, because the one sentence
    # this report must never print is "checked nothing on this body" about a gate that
    # checked its subject and found something wrong with it.
    crashed = [g['id'] for g in gates if g['crash_state'] == CRASHED]
    # status_recognised is required here, not merely nice: gates.py stamps `crashed` on
    # EVERY row, so a status this renderer does not know arrives with crashed=False, reads
    # as RAN, and lands in this bucket — whose heading says "GATES WHOSE VERDICT THE ENGINE
    # REFUSED ... on our own provenance rule". Nothing refused it; the renderer simply did
    # not recognise it. That is the same class of falsehood as the "GATES THAT CRASHED"
    # banner this bucket was created to fix. An unrecognised status is reported by
    # `unrecognised_status` below and still renders as an error — never as a pass.
    errored_no_crash = [
        g['id']
        for g in gates
        if g['effective_status'] == GATE_ERROR and g['crash_state'] == RAN and g['status_recognised']
    ]
    error_crash_undeclared = [
        g['id'] for g in gates if g['effective_status'] == GATE_ERROR and g['crash_state'] == CRASH_UNDECLARED
    ]
    unrecognised_status = [g['id'] for g in gates if not g['status_recognised']]
    # Blocking-severity gates that reached no verdict and are NOT already counted as a
    # blocking failure: skipped, missing, or unreadable. They cannot be scored, so they do
    # not manufacture a FAIL, but they are never silent either.
    # Malformed entries are excluded and left to the malformed_gate alarm: a row that
    # could not be read as a mapping has no severity, and calling it a BLOCKING gate would
    # be a claim about it that the report cannot support. It still counts as 'unknown',
    # so it is still not a pass.
    # 'blocking_severity' is DECLARED-or-calibrated, not calibrated alone; see the block
    # above the escalation branch in _read_gate for why a rejection rate may not excuse a
    # check that produced no verdict.
    unrun_blocking = [
        g['id']
        for g in gates
        if g['produced_no_verdict'] and not g['is_blocking_failure'] and not g['malformed'] and g['blocking_severity']
    ]
    # The subset that is here ONLY because the registry declared it blocking — the
    # calibration had taken the blocking severity away. Named separately so the change of
    # rule is visible on the page rather than inferable from a count that got bigger.
    unrun_blocking_by_declared = [
        g['id']
        for g in gates
        if g['produced_no_verdict']
        and not g['is_blocking_failure']
        and not g['malformed']
        and g['blocking_severity_by'] == 'declared'
    ]
    return GateBuckets(
        counts=counts,
        blocking=blocking,
        crashed=crashed,
        errored_no_crash=errored_no_crash,
        error_crash_undeclared=error_crash_undeclared,
        unrecognised_status=unrecognised_status,
        unrun_blocking=unrun_blocking,
        unrun_blocking_by_declared=unrun_blocking_by_declared,
    )


def build_alarms(buckets, gates, gr):
    """Run the policy-alarm pass over the sorted buckets.

    A thin seam over `alarms._build_alarms` so the orchestrator hands over one bucket
    object instead of nine positional lists. Returns `(alarms, severity_calibration)`.
    """
    return _build_alarms(
        buckets.counts,
        gates,
        gr,
        buckets.crashed,
        buckets.errored_no_crash,
        buckets.error_crash_undeclared,
        buckets.unrecognised_status,
        buckets.unrun_blocking,
        buckets.unrun_blocking_by_declared,
    )


def resolve_reference(ref):
    """Return `ref`, or the default reference pack, or None if the pack cannot be loaded.

    A missing pack is not an error here: the strip simply goes unscored and says so, and
    the age alarm cannot be computed without a coverage band.
    """
    if ref is not None:
        return ref
    try:
        from zyg_workflows.geom.anthro.reference import reference as _reference

        return _reference()
    except Exception:  # noqa: BLE001
        return None


def coverage_block(gates, roster, roster_source, roster_claimed):
    """Measure the document against the DECLARED gate roster and judge the coverage floor.

    `roster`/`roster_source`/`roster_claimed` are what `document._declared_roster` returned.
    Returns a :class:`Coverage`: the block for the document, the numbers the printed rules
    interpolate, and the alarms for absent gates, an unavailable roster and a suite below
    the floor — in that order.
    """
    # THE DOCUMENT-LEVEL COVERAGE FLOOR (re-review NEW-5). Counted off the RAW status, not
    # the effective one: 'warn' can be an escalated skip, and an escalated skip is still a
    # check that produced no verdict. A malformed entry produced no verdict either.
    verdict_gates = [g for g in gates if not g['produced_no_verdict'] and not g['malformed']]
    n_verdicts = len(verdict_gates)
    present_ids = {g['id'] for g in gates}
    absent = sorted(roster - present_ids)
    extra = sorted(present_ids - roster) if roster else []
    n_declared = len(roster | present_ids) if roster else len(gates)
    cov_fraction = (float(n_verdicts) / n_declared) if n_declared else None
    coverage_ok = bool(
        n_verdicts >= _MIN_VERDICTS_FOR_PASS
        and cov_fraction is not None
        and cov_fraction >= _MIN_VERDICT_FRACTION_FOR_PASS
    )
    # The live margin, computed instead of asserted in a comment: how many gates this body
    # could lose before the floor stops being met. anny-neutral ships at +1.
    need = int(math.ceil(_MIN_VERDICT_FRACTION_FOR_PASS * n_declared)) if n_declared else 0
    coverage = {
        'n_gates': len(gates),
        # The declared roster and where it was read from. A reader must be able to tell
        # "60 gates were declared and 3 of them are in this document" from "3 gates were
        # declared"; before W4-3 the document could not express the difference.
        'n_declared': n_declared,
        'roster_source': roster_source,
        'gates_declared_but_absent': absent or None,
        'gates_present_but_not_declared': extra or None,
        'n_produced_verdict': n_verdicts,
        'n_produced_no_verdict': n_declared - n_verdicts,
        'fraction': round(cov_fraction, 6) if cov_fraction is not None else None,
        'floor_n': _MIN_VERDICTS_FOR_PASS,
        'floor_fraction': _MIN_VERDICT_FRACTION_FOR_PASS,
        'floor_gates': max(need, _MIN_VERDICTS_FOR_PASS) if n_declared else None,
        'margin_gates': (n_verdicts - max(need, _MIN_VERDICTS_FOR_PASS) if n_declared else None),
        'meets_floor': coverage_ok,
        'verdict_statuses': list(_VERDICT_STATUSES),
    }
    alarms = []
    if absent:
        alarms.append(
            {
                'kind': 'declared_gates_absent',
                'gates': absent,
                'text': '%d gate(s) the engine DECLARED for this run are not in this document '
                'at all (%s%s). They are counted in the coverage denominator, because a '
                'suite reaches the floor by omission exactly as easily as by skipping — '
                'and a document that silently shrinks its own denominator can report '
                '100%% coverage of three gates out of sixty. Roster read from %s.'
                % (
                    len(absent),
                    ', '.join(absent[:8]),
                    '' if len(absent) <= 8 else ', +%d more' % (len(absent) - 8),
                    roster_source,
                ),
            }
        )
    if roster_claimed and not roster:
        alarms.append(
            {
                'kind': 'coverage_roster_unavailable',
                'gates': [],
                'text': 'this document presents itself as an engine report and the coverage '
                'floor could not be measured against a DECLARED roster: %s. The '
                'denominator below is the gates PRESENT, which is the weaker claim — a '
                'gate that was never emitted cannot be counted as missing. Treat the '
                'coverage fraction as an upper bound.' % roster_source,
            }
        )
    if not coverage_ok:
        alarms.append(
            {
                'kind': 'suite_coverage_below_floor',
                'gates': [],
                'text': 'only %d of %d DECLARED gate(s) produced a verdict (%s); a PASS '
                'requires at least %d and at least %.0f%%. A document in which the '
                'checks did not run is not a pass, it is an unrun suite: this '
                'renderer\'s "a check '
                'that did not run is never a pass" rule was enforced on every gate and '
                'on no body, so an all-skipped suite at a non-blocking severity used '
                'to render PASS, exit 0, with "pass 0" in the counts. The verdict is '
                'held at PASS-WITH-WARNINGS or worse. It is NOT forced to FAIL: unrun '
                'checks do not manufacture a failure here, and a body that failed '
                'nothing has not failed.'
                % (
                    n_verdicts,
                    n_declared,
                    'no gates at all' if not n_declared else '%.1f%%' % (100.0 * cov_fraction),
                    _MIN_VERDICTS_FOR_PASS,
                    100.0 * _MIN_VERDICT_FRACTION_FOR_PASS,
                ),
            }
        )
    return Coverage(
        coverage=coverage,
        n_verdicts=n_verdicts,
        n_declared=n_declared,
        cov_fraction=cov_fraction,
        meets_floor=coverage_ok,
        gates_present_but_not_declared=extra,
        alarms=alarms,
    )


def initial_verdict(buckets, alarms, meets_floor):
    """Derive the document's verdict from the buckets, the alarms and the coverage floor.

    FAIL for any blocking failure; PASS-WITH-WARNINGS for any warning, error, not-a-pass
    status or policy alarm; PASS otherwise. The floor is applied as its own step and not
    left to the fact that a floor alarm happens to force WARN: below the floor, PASS is
    unreachable.
    """
    if buckets.blocking:
        v = FAIL
    elif buckets.counts['warn'] or buckets.counts[GATE_ERROR] or any(buckets.counts[k] for k in _NOT_A_PASS) or alarms:
        v = WARN
    else:
        v = PASS
    # Stated as its own step rather than left to the fact that the alarm above lands in
    # `alarms` and `alarms` happens to force WARN two lines up. That coupling is invisible,
    # and a later edit to the alarm chain would take the floor away without touching
    # anything that looks like a floor. The rule is: below the floor, PASS is unreachable.
    if not meets_floor and v == PASS:
        v = WARN
    return v


def reconcile_declared_verdict(verdict, gr):
    """Compare the engine's own declared verdict with the recomputed one; keep the stricter.

    Returns `(verdict, alarm_or_None)`. The gate engine renders its own verdict, and
    recomputing it here from the rows is the cheapest available check that the two have not
    drifted apart — a renderer that quietly disagrees with the engine is worse than one
    that crashes. Reporting the softer of the two is how a crashed blocking gate once went
    out as PASS-WITH-WARNINGS, so a disagreement is never resolved in the body's favour.
    """
    declared = gr.get('verdict')
    if not isinstance(declared, str):
        return verdict, None
    norm = declared.strip().upper().replace(' ', '-')
    if norm in ('PASS-WITH-WARNING', 'PASSWITHWARNINGS'):
        norm = WARN
    if norm not in EXIT_CODES or norm == verdict:
        return verdict, None
    harsher = max(verdict, norm, key=lambda x: _VERDICT_RANK.get(x, 0))
    return harsher, {
        'kind': 'verdict_disagreement',
        'gates': [],
        'text': 'the gate engine declared verdict %r; recomputing it from the '
        "gate rows under this renderer's HOUSE arithmetic gives %r. One "
        'of the two is wrong. The STRICTER of the two (%s) is what this '
        'report carries — a verdict this renderer cannot reproduce is '
        "never resolved in the body's favour." % (declared, verdict, harsher),
    }


def strip_block(measurement, gates, verdict, *, sex, ancestry, band_width, stature_m, ref):
    """Build the percentile strip and judge how much of it could actually be scored.

    Returns `(rows, alarms, verdict)`. A strip that cannot be built at all, and a strip in
    which half the ratios found no band, both raise an alarm and hold the verdict at
    PASS-WITH-WARNINGS: a per-ratio lookup failure is caught and rendered, which is right
    for one ratio and very wrong for all of them, because a bad ancestry or a missing pack
    would otherwise produce a clean-looking report in which nothing was checked.
    """
    # Exact match only: a fuzzy id-to-ratio association would silently attribute a gate to
    # the wrong measurement, which is worse than no association at all.
    measured_ratios = (measurement or {}).get('ratios') or {}
    gates_by_ratio = {g['id']: g['id'] for g in gates if g['id'] in measured_ratios}

    rows = []
    alarms = []
    v = verdict
    if measurement is not None and sex:
        try:
            rows = ratio_rows(
                (measurement or {}).get('ratios') or {},
                sex,
                ancestry,
                width=band_width,
                stature_m=stature_m,
                ref=ref,
                gates_by_ratio=gates_by_ratio,
            )
        except Exception as e:  # noqa: BLE001
            alarms.append(
                {'kind': 'strip_unavailable', 'gates': [], 'text': 'percentile strip could not be built: %s' % e}
            )
            if v == PASS:
                v = WARN
        # A per-ratio band lookup that fails is caught and rendered, which is right for one
        # ratio and very wrong for all of them: a bad ancestry or a missing pack would
        # otherwise produce a clean-looking report in which nothing was actually checked.
        errs = [r for r in rows if r.get('status') in ('band-error', 'no-reference')]
        if rows and len(errs) >= max(3, len(rows) // 2):
            alarms.append(
                {
                    'kind': 'reference_lookup_failing',
                    'gates': [],
                    'text': '%d of %d ratios could not be scored against the reference pack '
                    '(first reason: %s). Nothing below was checked against a real '
                    'distribution — treat this report as unvalidated.'
                    % (len(errs), len(rows), errs[0].get('note_render') or errs[0].get('status')),
                }
            )
            if v != FAIL:
                v = WARN
    return rows, alarms, v


def provenance_map(gates, rows, unknown):
    """Group the gate ids and the strip ratios by the source each was measured from.

    `unknown` is the sentinel a gate carries when it declares no source; such rows are
    left out rather than filed under a source named "unknown". Strip rows are keyed
    'strip:<ratio>' so a provenance entry always says which surface it came from.
    """
    prov = {}
    for g in gates:
        src = g['source']
        if src and src != unknown:
            prov.setdefault(str(src), {'class': g['provenance_class'], 'gates': []})
            prov[str(src)]['gates'].append(g['id'])
    for r in rows:
        if r.get('source'):
            prov.setdefault(r['source'], {'class': 'MEASURED', 'gates': []})
            prov[r['source']]['gates'].append('strip:' + r['ratio'])
    return prov


def ratio_summary(rows):
    """Count the strip rows by how well each one could be scored."""
    return {
        'n': len(rows),
        'n_banded': sum(1 for r in rows if r.get('percentile') is not None),
        'n_outside': sum(1 for r in rows if r.get('status') == 'outside'),
        'n_no_band': sum(1 for r in rows if r.get('status') in ('no-band', 'no-reference', 'band-error', 'no-value')),
    }


def policy_block(roster_source, n_declared, n_gates):
    """The HOUSE policy the document states about itself, generated from what it enforces.

    Every printed rule that names a threshold, a status vocabulary or a denominator
    interpolates the constant or the number the arithmetic above actually used, so the
    sentence cannot come to mean something the code does not do — the two used to be a
    hand-typed sentence and a separate tuple, and a whole status fell down the gap.
    """
    return {
        'class': 'HOUSE',
        'verdict_rule': 'any failing gate at a high or unrecognised severity, and any '
        'gate that CRASHED at a high or unrecognised severity, -> '
        'FAIL; otherwise any warning, error, missing, unknown status '
        'or policy alarm -> PASS-WITH-WARNINGS; otherwise PASS. When '
        "the gate engine's own verdict and this one disagree, the "
        'stricter of the two is reported.',
        'missing_field_rule': 'an absent status renders as unknown and counts towards '
        'the warning total. A gate that DECLARES status '
        '"missing" — it ran, and what is missing is a '
        'declaration the caller owes it — renders as MISSING '
        'with its own explanation and also counts towards the '
        'warning total. Neither is ever a pass.',
        'crash_rule': 'a gate that RAISED renders as ERROR in its own bucket and its '
        'own count column, is listed in doc["blocking"], and fails the '
        'body outright at a high or unrecognised severity. A crash is '
        'never a band rejection, so no rejection-rate calibration may '
        'soften it, and it is never folded into "unknown": a check that '
        'did not run is not a pass. WHETHER A GATE RAISED IS A BOOLEAN '
        'THE ENGINE SETS ON THE ROW ("crashed"), READ HERE AND NEVER '
        'DERIVED FROM THE STATUS: the error bucket also holds gates that '
        'RAN, measured their subject and produced a finding whose '
        'verdict the engine then refused on a provenance rule. Those are '
        'named in doc["errored_without_crashing"], keep the error bucket '
        'and the same blocking consequence, and are never described as '
        'having checked nothing. A row that declares no flag is reported '
        'as undeclared in doc["error_crash_undeclared"] rather than '
        'guessed at in either direction.',
        'unrecognised_status_rule': 'a status spelling this renderer does not know renders as an ERROR, never '
        'as a pass and never as anything softer, and is named in '
        'doc["unrecognised_status"]. An absent or unreadable status is a different '
        'fact and keeps the "unknown" bucket.',
        'volatile_rule': 'the "volatile" block is dropped from stable_sha256 BY NAME, '
        'so anything placed in it is invisible to the digest and to '
        'the clock-residue detector, which runs on a tree it has '
        'already been removed from. Every key in it must therefore be '
        'instrumentation — a record of when this process ran or how '
        'long it took. Content found there sets '
        'doc["digest"]["stable"] false and raises an alarm, because a '
        'digest that cannot see part of the report cannot identify '
        'it.',
        # THE PRINTED RULE IS GENERATED FROM THE ENFORCED ONE. It used to be a
        # hand-typed sentence enumerating "skip, missing or unknown" while _NO_VERDICT
        # enforced a different set; the two drifted, and a whole status ('report') fell
        # down the gap between them. Interpolating the tuple makes that particular
        # divergence impossible rather than merely fixed.
        'unrun_blocking_rule': 'a blocking-severity gate whose status is %s produced '
        'no verdict. It cannot be scored, so it does not '
        'manufacture a FAIL, but it is escalated, counted as a '
        'warning, named in doc["unrun_blocking"], alarmed on, '
        'and printed in the banner. "0 blocking" alongside an '
        'unrun blocking gate is a false statement. An '
        'ERROR-class row is not in this list — a gate that '
        'RAISED, and equally a gate that RAN and whose verdict '
        'the engine refused: both have their own bucket and '
        'crash_rule, and at blocking severity both are a '
        'FAILURE rather than an unrun check. BLOCKING-SEVERITY '
        'here '
        'means the severity the registry DECLARED or the '
        'severity that governed the run, whichever is higher: a '
        'reference rejection rate measures how often a BAND '
        'would reject a real body, which is a statement about a '
        'verdict, and a gate that produced no verdict has not '
        'earned that softening. Rows escalated on the declared '
        'severity alone are named in '
        'doc["unrun_blocking_by_declared_severity"].' % ', '.join(_UNRUN_BLOCKING_STATUSES),
        # THE PRINTED RULE NAMES THE DENOMINATOR IT WAS ACTUALLY COMPUTED AGAINST
        # (W4-3). It used to say "of the declared gates" while the arithmetic used the
        # gates PRESENT, so a suite that emitted 3 of 60 — all passing — scored 100%
        # coverage and exited 0. The roster source is interpolated per document, so
        # the sentence cannot mean something the arithmetic did not do.
        'coverage_floor_rule': 'a verdict of PASS requires that at least %d gate(s) '
        'and at least %.0f%% of the DECLARED gates actually '
        'produced a verdict (%s). Declared here means: %s — %d '
        'gate(s), of which %d are in this document. Below that '
        'floor the document '
        'is not a pass, it is an unrun suite, and the verdict is '
        'held at PASS-WITH-WARNINGS or worse. Counted on the '
        'RAW status: an escalated skip counts towards the '
        'warning total but is still not a verdict. A gate the '
        'roster declares and the document does not contain '
        'counts against the floor exactly like a gate that '
        'skipped: a suite reaches the floor by omission as '
        'easily as by silence. HOUSE.'
        % (
            _MIN_VERDICTS_FOR_PASS,
            100.0 * _MIN_VERDICT_FRACTION_FOR_PASS,
            ', '.join(_VERDICT_STATUSES),
            roster_source,
            n_declared,
            n_gates,
        ),
        'digest_rule': 'stable_sha256 is sha256 over this document with the volatile '
        'block, the digest block and the digest itself removed, and '
        'every INSTRUMENTATION key removed at every depth. '
        'Instrumentation is anything recording when this process ran or '
        'how long it took; volatile is the one block where it may live '
        'by name. Two runs of the same mesh against the same pack '
        'produce the same digest. Every key removed is named in '
        'doc["digest"]["instrumentation_excluded"], and anything that '
        'survives the strip and still looks like a per-run clock OR a '
        'per-run identity — by its NAME, or by its VALUE being a bare '
        'unix epoch, an ISO timestamp with a time of day on it, or a '
        'UUID — sets doc["digest"]["stable"] false and raises an alarm '
        'rather than letting the field go back to being a per-run '
        'nonce. The value test is what makes this a test of the class '
        'rather than of a vocabulary: the fix for a name nobody thought '
        'of can never be a slightly longer list of names. Content found '
        'inside the volatile block does the same, because that block is '
        'dropped from the hash by name and is the one place a field '
        'could change without the digest moving.',
        'severity_rule': 'a failure is downgraded to a warning only on an explicitly '
        'recognised low severity (%s). Unrecognised severities keep '
        'the failure.' % ', '.join(_LOW_SEVERITIES),
        'exit_codes': dict(EXIT_CODES),
    }


def volatile_block(gate_report, meta):
    """The instrumentation block: when this process ran, and how long the inputs took.

    This is the one block the digest is allowed not to see, so nothing but a record of
    timing may go in it — `finalise_digest` checks that and alarms if content appears here.
    """
    return {
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'gate_report_generated': (gate_report or {}).get('generated') if isinstance(gate_report, dict) else None,
        'measurement_generated': meta.get('generated'),
        'measurement_elapsed_s': meta.get('elapsed_s'),
    }


def finalise_digest(doc, alarms):
    """Audit the volatile block, take the stable digest, and stamp both onto `doc` in place.

    Mutates `doc` (its 'verdict', 'exit_code', 'digest' and 'stable_sha256') and appends to
    `alarms`, which is the same list object `doc['policy_alarms']` holds — the findings are
    content and must be inside the hash, so both the volatile-content check and the
    clock-residue scan run BEFORE the digest is taken and the inventory is then taken again
    over the document that will actually be hashed.
    """
    # W4-4: THE ONE BLOCK THE DIGEST CANNOT SEE INTO MUST CONTAIN NOTHING WORTH SEEING.
    # `volatile` is excluded from the hash by name and the residue detector runs after it
    # has been removed, so a content field placed here would be invisible to both — the
    # mirror image of the clock-in-the-content defect, and nothing checked it. Checked
    # before the digest is taken so the finding is inside the hash like every other alarm.
    volatile_content = _volatile_content(doc['volatile'])
    if volatile_content:
        alarms.append(
            {
                'kind': 'volatile_contains_content',
                'gates': [],
                'text': 'the "volatile" block carries %d field(s) that are not instrumentation '
                '(%s). That block is dropped from stable_sha256 BY NAME and the '
                'clock-residue detector runs on a tree it has already been removed '
                'from, so anything placed there is invisible to the digest twice over: '
                'the report could change and the digest could not. Instrumentation — '
                'when this process ran, how long it took — belongs here. Everything '
                'else belongs in the document, where it is hashed.'
                % (len(volatile_content), ', '.join(volatile_content[:6])),
            }
        )
    # The strip is inspected BEFORE the digest is taken, so that a clock the stripper does
    # not recognise can raise its alarm and have that alarm inside the hash — rather than
    # being appended afterwards and leaving doc['stable_sha256'] != stable_sha(doc).
    _stripped, excluded, residue = _digest_scan(doc)
    if residue:
        alarms.append(
            {
                'kind': 'digest_includes_the_clock',
                'gates': [],
                'text': 'stable_sha256 CANNOT claim to be stable: %d field(s) survived the '
                'instrumentation strip and still look like a per-run clock (%s). Two '
                'runs of the same mesh will produce different digests, and every '
                'consumer that treats this field as the identity of a report — '
                'geom.mesh_skeletons stores it as exactly that — will see change where '
                'there is none. Either the field is content and belongs under a name '
                'that is not a clock, or it is instrumentation and belongs in the '
                'volatile block or in _INSTRUMENTATION_KEYS.'
                % (len(residue), '; '.join('%s (%s)' % (r['path'], r['why']) for r in residue[:6])),
            }
        )
    if residue or volatile_content:
        if doc['verdict'] == PASS:
            doc['verdict'] = WARN
        doc['exit_code'] = EXIT_CODES[doc['verdict']]
        # The alarm is content and is inside the digest, so the inventory is taken again
        # over the document that will actually be hashed rather than over the one that was
        # inspected. Same answer unless an alarm text is itself a clock, and "same answer
        # unless" is how the field became a nonce in the first place.
        _stripped, excluded, residue = _digest_scan(doc)
    doc['digest'] = {
        'algorithm': 'sha256 of the document as JSON with sorted keys',
        'excluded_top_level': list(_DIGEST_EXCLUDED_TOP_LEVEL),
        'instrumentation_excluded': excluded,
        'n_instrumentation_excluded': len(excluded),
        'instrumentation_vocabulary': sorted(_INSTRUMENTATION_KEYS),
        'instrumentation_suffixes': list(_INSTRUMENTATION_SUFFIXES),
        # The claim the field's NAME makes, stated as a checkable fact rather than as a
        # docstring. False here means the digest moves with the clock (NEW-4) — or that
        # part of the report is hiding inside the block the digest cannot see (W4-4).
        'stable': not (residue or volatile_content),
        'unstable_fields': residue or None,
        'volatile_content_fields': volatile_content or None,
    }
    doc['stable_sha256'] = stable_sha(doc)
