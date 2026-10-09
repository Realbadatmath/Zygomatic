# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The engine.

Moved verbatim out of the old single-file gates.py (lines 8408-8724).
"""

import json
import os
import time

from zyg_workflows.geom.anthro.gates.policy import (
    CRASHED_CONTRACT,
    CRASHED_KEY,
    ERROR,
    ERROR_CLASS_STATUSES,
    FAIL,
    MISSING,
    PASS,
    POLICY_ERROR,
    SCHEMA,
    STATUSES,
    TIERS,
    WARN,
)
from zyg_workflows.geom.anthro.gates.bands import GateConfigError
from zyg_workflows.geom.anthro.gates.gate import _result, check_module_provenance, validate_registry
from zyg_workflows.geom.anthro.gates.subject import Subject, _NO_VERDICT_STATUSES
from zyg_workflows.geom.anthro.gates.registry import GATES
from zyg_workflows.geom.anthro.gates.severity import calibrate, severity_table


# ---------------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------------
# Which statuses count as what, per severity. A gate that could not run is never a
# failure, but it is also never invisible: the verdict block counts it separately.
# BOTH error-class statuses are here. POLICY_ERROR was added with W4-1 and it enters this
# tuple in the same breath as it is invented, because the whole risk of splitting a status
# is that the new half quietly stops blocking. It does not: a refused finding blocks
# exactly as the undifferentiated ERROR did.
_BLOCKING = (FAIL,) + ERROR_CLASS_STATUSES
_WARNING = (WARN, MISSING)


def _effective_severity(gate, cal, status):
    """The severity that governs THIS result.

    Two rules, and the second one is the important one. The calibrated severity governs a
    band failure, because that is the thing whose rejection rate was measured. It does NOT
    govern an error-class status: a gate that raised did not reject an unusual body, it
    broke, and a gate refused on provenance did not reject an unusual body either — the
    engine refused its paperwork. Letting a rejection-rate argument soften either one would
    be using the right answer to the wrong question.
    """
    if status == ERROR:
        return gate.severity, (
            'declared %r — status is ERROR, and a gate that could not '
            'complete its check is not a band rejection, so the '
            'measured-rejection policy does not apply to it' % gate.severity
        )
    if status == POLICY_ERROR:
        return gate.severity, (
            'declared %r — status is %s. The gate RAN and produced a '
            'finding; the engine refused that finding on a policy '
            'ground about the row (see provenance_disagreement). A '
            'refusal is not a band rejection, so the measured-rejection '
            'policy does not apply to it, and the declared severity '
            'governs exactly as it does for a crash.' % (gate.severity, POLICY_ERROR)
        )
    return cal['severity_effective'], cal['reason']


def _classify(severity, status):
    if status not in STATUSES:
        # AN UNMAPPED STATUS IS AN ERROR, NEVER AN 'ok'. This branch used to be absent and
        # the function fell through to `return 'ok'`, so a status this engine has never
        # heard of — a gate returning a hand-built dict, a typo, a future token from a form
        # module — was counted as a pass on a blocking gate. It is the same defect as
        # report.py rendering an unknown status as a pass, on this side of the wall, and it
        # is closed the same way _roll_up and _xlate already close it: unmapped folds to
        # ERROR's treatment. run_gates also names the status in the row (`status_unmapped`)
        # so this is visible rather than silently absorbed.
        status = ERROR
    if status in _BLOCKING:
        return 'blocking' if severity == 'block' else 'warning'
    if status in _WARNING:
        return 'warning'
    # REPORT joined the non-verdicts here on 2026-08-06 (re-review N1). It used to fall
    # through to 'ok', so a BLOCK-severity gate whose status rolled up to 'report' was
    # counted as ok, was absent from blocking_gates_not_run, and — because report.py's
    # _NO_VERDICT did not list 'report' either — was absent from doc['unrun_blocking'] and
    # from the "BLOCKING GATES THAT DID NOT RUN" banner as well. It was not a pass, not a
    # fail, not escalated and not named anywhere. Live instance: t5_pronation_isolation on
    # abel and cornelis. A printed row is not a verdict, whatever its severity.
    if status in _NO_VERDICT_STATUSES:
        return 'not_run'
    return 'ok'


def run_gates(subject, *, tiers=None, strict=True, gates=None):
    """Run the engine over one subject and return the report.

    subject : a Subject, a registered character name, or a (v, faces, spec) triple.
    tiers   : iterable of tier numbers to run; None runs all four.
    strict  : True (default) lets an exception from a gate callable propagate, because a
              gate that crashes has not passed and must not be recorded as if it had.
              False records it as status 'error', which is a blocking failure for a
              blocking gate.
    gates   : registry override, validated the same way before anything runs.

    Verdict: any blocking failure -> FAIL. Otherwise warnings -> PASS WITH WARNINGS.

    "Blocking" here means the EFFECTIVE severity, which is measured before the first gate
    runs (see rule 6 and calibrate()). Every row carries severity, severity_declared,
    severity_reason and reference_rejection_rate, and the report carries the whole
    severity table, so the reason any gate did or did not block is in the artefact rather
    than in this file's opinion.
    """
    gates = tuple(GATES if gates is None else gates)
    validate_registry(gates)
    if tiers is None:
        tiers = TIERS
    tiers = tuple(int(t) for t in tiers)
    bad = [t for t in tiers if t not in TIERS]
    if bad:
        raise GateConfigError('unknown tier(s) %r; valid: %s' % (bad, list(TIERS)))
    if isinstance(subject, str):
        subject = Subject.from_registry(subject)
    elif isinstance(subject, (tuple, list)) and len(subject) == 3:
        subject = Subject.from_mesh(subject[0], subject[1], subject[2])
    if not isinstance(subject, Subject):
        raise TypeError(
            'subject must be a Subject, a registered character name, or a '
            '(v, faces, spec) triple; got %r' % type(subject).__name__
        )

    # Measured BEFORE any gate runs, so that a severity in the report is never a severity
    # some gate result talked the engine into.
    cal_table = calibrate(gates)

    t0 = time.time()
    results = []
    counts = {'blocking': 0, 'warning': 0, 'not_run': 0, 'ok': 0}
    for g in gates:
        if g.tier not in tiers:
            continue
        started = time.time()
        # THE ONE FACT THAT DECIDES `crashed`, AND THE ONLY PLACE IT IS KNOWN. Set in the
        # except branch and nowhere else. No status, before or after, may move it.
        raised = None
        try:
            r = g.fn(subject)
        except Exception as e:  # noqa: BLE001
            if strict:
                raise
            raised = '%s: %s' % (type(e).__name__, e)
            r = _result(ERROR, 'gate raised %s' % raised)
        # R4: the module's provenance tag against the registry's, on every row, before the
        # status is classified. An unshippable module tag replaces the verdict; a
        # shippable disagreement is recorded beside it.
        prov_disagreement = check_module_provenance(g, r)
        if prov_disagreement is not None:
            if prov_disagreement['unsafe']:
                # The replaced verdict is NAMED HERE, not only stored. A gate whose real
                # finding is demoted into a detail key by a bookkeeping error is failure
                # shape (b) — evidence computed and then not surfaced — and it costs the
                # reader the actual anatomy result (t5_patellar_ligament's 10-27% drift).
                #
                # W4-1, PRODUCER HALF. This row's status is POLICY_ERROR, not ERROR, and
                # the row's `crashed` is False — an explicit boolean set below from
                # `raised`, which only the except branch can set. Wave 4 emitted plain
                # ERROR here and report.py, correctly following "error means crash", filed
                # a live blocking anatomical finding as an infrastructure crash on all five
                # bodies. The previous fix for that was a rebuttal sentence inside this
                # explain string; a rebuttal is not a fact a counter can read, so the two
                # events now have two tokens and the flag is carried rather than inferred.
                r = _result(
                    POLICY_ERROR,
                    'PROVENANCE DISAGREEMENT, UNSAFE DIRECTION. THIS GATE DID NOT '
                    'CRASH: it RAN, it checked this body, and it produced the '
                    'verdict named at the end of this line, which the engine then '
                    "refused HERE and only here. That is why this row's status is "
                    '%r and not %r, and why it carries %s=False. The registry ships '
                    'this gate as %s; the form module tags the same number %s at '
                    '%s, and that tag travels into every row of the artefact and is '
                    'printed. %s THE VERDICT THIS REFUSAL REPLACES, which stands as '
                    "the gate's own finding and is not withdrawn: %s — %s"
                    % (
                        POLICY_ERROR,
                        ERROR,
                        CRASHED_KEY,
                        g.provenance,
                        prov_disagreement['module_provenance'],
                        ', '.join(
                            sorted(p for paths in prov_disagreement['module_provenance_paths'].values() for p in paths)
                        )
                        or 'an unrecorded path',
                        prov_disagreement['why'],
                        r.get('status'),
                        (r.get('explain') or 'no explanation supplied'),
                    ),
                    gate_ran_and_produced_a_verdict=True,
                    crashed_contract=CRASHED_CONTRACT,
                    observed=r.get('observed'),
                    band=r.get('band'),
                    source=g.source,
                    module_provenance=prov_disagreement['module_provenance'],
                    provenance_disagreement=prov_disagreement,
                    status_the_gate_would_have_returned=r.get('status'),
                    explain_the_gate_would_have_returned=r.get('explain'),
                    module_detail=(r.get('detail') or {}),
                )
            else:
                r.setdefault('detail', {})['provenance_disagreement'] = prov_disagreement
        cal = cal_table[g.id]
        sev, sev_reason = _effective_severity(g, cal, r['status'])
        cls = _classify(sev, r['status'])
        counts[cls] += 1
        row = g.as_dict()
        row.update(r)
        # -- the `crashed` contract, written onto every row ---------------------------
        row[CRASHED_KEY] = raised is not None
        row['crashed_contract'] = CRASHED_CONTRACT
        if raised is not None:
            row['crash_exception'] = raised
        # An unmapped status is named as one rather than absorbed. _classify has already
        # treated it as error-class; this key is so that a reader can see WHICH token the
        # engine did not recognise instead of inferring it from a bucket.
        if r.get('status') not in STATUSES:
            row['status_unmapped'] = r.get('status')
            row['status_unmapped_note'] = (
                'this engine has no mapping for status %r; it is classified as error-class '
                '(%s), never as a pass. Valid: %s' % (r.get('status'), cls, ', '.join(STATUSES))
            )
        # `severity` is the EFFECTIVE severity — the one that governed this row and this
        # verdict. The declared one is kept beside it rather than replaced, because "the
        # registry asked for block and the reference sample said warn" is the fact a
        # reader of this report most needs, and overwriting it would erase the audit.
        row['severity'] = sev
        row['severity_declared'] = g.severity
        row['severity_reason'] = sev_reason
        row['severity_calibrated'] = bool(sev != g.severity)
        row['reference_rejection_rate'] = cal['rate']
        row['severity_calibration'] = cal
        row['classification'] = cls
        row['ms'] = round(1000.0 * (time.time() - started), 2)
        results.append(row)

    verdict = 'FAIL' if counts['blocking'] else 'PASS WITH WARNINGS' if counts['warning'] else 'PASS'
    meta = sub_meta(subject)
    # A gate that carries blocking severity and did NOT run is the one thing a reader of
    # "blocking: []" must not be allowed to miss: the list is empty because nothing
    # FAILED, which is a different sentence from "every blocking check passed". Named
    # here so no summary surface has to reconstruct it — and both of its parts are
    # separated, because 'missing' (a declared input was absent) and 'not run' (the check
    # does not apply to this body) are different admissions.
    # _NO_VERDICT_STATUSES, not _SKIPPED: a block-severity gate that rolled up to REPORT
    # reached no verdict either, and leaving it out of this list was half of N1.
    blocking_not_run = [r['id'] for r in results if r['severity'] == 'block' and r['status'] in _NO_VERDICT_STATUSES]
    blocking_missing = [r['id'] for r in results if r['severity'] == 'block' and r['status'] == MISSING]
    # W4-1. The two error-class populations, separated AT THE PRODUCER, so that no summary
    # surface has to reconstruct either one from a status — which is precisely how "GATES
    # THAT CRASHED (checked nothing)" came to name two gates that had run.
    crashed_ids = [r['id'] for r in results if r[CRASHED_KEY]]
    policy_error_ids = [r['id'] for r in results if r['status'] == POLICY_ERROR]
    unmapped_ids = [r['id'] for r in results if 'status_unmapped' in r]
    return {
        'schema': SCHEMA,
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'subject': meta,
        'tiers_run': list(tiers),
        'verdict': verdict,
        'counts': counts,
        'blocking': [r['id'] for r in results if r['classification'] == 'blocking'],
        'warnings': [r['id'] for r in results if r['classification'] == 'warning'],
        'not_run': [r['id'] for r in results if r['classification'] == 'not_run'],
        'blocking_gates_not_run': blocking_not_run,
        'blocking_gates_missing_input': blocking_missing,
        'blocking_verified': [r['id'] for r in results if r['severity'] == 'block' and r['status'] == PASS],
        # THE GATES THAT ACTUALLY RAISED. Read off row[CRASHED_KEY], which only the except
        # branch can set true — never off a status.
        'crashed': crashed_ids,
        # THE GATES THAT RAN, PRODUCED A FINDING, AND HAD IT REFUSED ON POLICY. These are
        # not crashes and the sentence written about them must not say they checked
        # nothing: each row carries status_the_gate_would_have_returned and
        # explain_the_gate_would_have_returned, and the finding is not withdrawn.
        'policy_errors': policy_error_ids,
        'crashed_contract': CRASHED_CONTRACT,
        'error_class_note': (
            '%d gate(s) raised (%s) and %d ran, produced a finding and were refused on '
            'policy (%s). Both are error-class and both block on a block-severity gate; '
            'they are counted apart because only the first checked nothing. Statuses: %s '
            'for a crash, %s for a refusal.'
            % (
                len(crashed_ids),
                ', '.join(crashed_ids) or 'none',
                len(policy_error_ids),
                ', '.join(policy_error_ids) or 'none',
                ERROR,
                POLICY_ERROR,
            )
        ),
        'status_unmapped_gates': unmapped_ids,
        'unverified_note': (
            '%d blocking-severity gate(s) did not run on this body (%s) and %d could not '
            'run for want of a declared input (%s). "blocking: []" means nothing FAILED, '
            'not that every blocking check passed.'
            % (
                len(blocking_not_run),
                ', '.join(blocking_not_run) or 'none',
                len(blocking_missing),
                ', '.join(blocking_missing) or 'none',
            )
        ),
        'severity_calibration': severity_table(gates),
        'gates': results,
        'elapsed_s': round(time.time() - t0, 3),
    }


def sub_meta(subject):
    m = subject.measurements['meta']
    return {
        'name': subject.name,
        'sex': subject.sex,
        'sex_source': subject.spec.get('sex_source'),
        'ancestry': subject.ancestry,
        'ancestry_declared': subject.ancestry is not None,
        'age_years': subject.age_years,
        'age_source': subject.spec.get('age_source'),
        'in_ansur_age_window': subject.is_ansur_age,
        'stature_mm': round(subject.stature_mm, 2),
        'build_target_stature_mm': subject.spec.get('build_target_stature_mm'),
        'vertices': int(len(subject.v)),
        'faces': int(len(subject.faces)),
        'pose': m['pose'],
        'axis_convention': m['axis_convention'],
        'girth_convention': m['girth_convention'],
        'coco_source': m['coco_source'],
        'cage_vert_sha256': subject.spec.get('cage_vert_sha256'),
    }


def _atomic_json(path, doc):
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(doc, fh, indent=1, default=str)
    os.replace(tmp, path)
