# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — evidence pass-through, which evidence decided the gate, and the gate row reader.

Moved out of the old single-file report.py (lines 1066-1519).
"""

import re
from zyg_workflows.geom.anthro.report.constants import CRASHED, GATE_ERROR, RAN, UNKNOWN, _NO_VERDICT, _RECEIPT_KEY
from zyg_workflows.geom.anthro.report.textfmt import _jsonable
from zyg_workflows.geom.anthro.report.gatedata import (
    _band_of,
    _crash_state,
    _fmt_band,
    _get,
    _observed_of,
    _prov_class,
    _rejection_rate,
    _severity_class,
    normalize_status,
    status_is_recognised,
)

# ---------------------------------------------------------------------------------
# EVIDENCE PASS-THROUGH
#
# THE DEFECT THIS CLOSES (adversarial review F4). _read_gate flattens each gate row to a
# FIXED FIELD LIST and never copied g['detail'], and dict-valued `observed` collapsed to
# the string "{N fields}". Measured on the shipped artefact: rows with detail 0 of 60.
# Everything the gate engine deliberately attached as evidence was therefore computed and
# then discarded before it reached a reader — the pose library's violation rate, the
# patellar patch caveat under a BLOCKING FAIL, the relief resolution lists, the angle
# records behind every not_implementable, the elbow patch ownership. The engine's honesty
# contract ("the evidence for the refusal travels in the gate record", "the caveat travels
# with them") was written against a writer that dropped it.
#
# The whitelist is now widened DELIBERATELY rather than left as an accidental filter, with
# three rules, because an unbounded copy of `detail` would put whole mesh records and 44
# pose rows into every artefact:
#   1. SCALARS AND SHORT LISTS SURVIVE WHOLE. Those are the numbers.
#   2. A container that is too big is replaced by a DESCRIPTOR naming its size and its
#      keys — never silently omitted, so a reader can see that something was there.
#   3. What was dropped is listed by key path in `evidence_dropped`. A truncation that
#      does not say what it truncated is the same defect one level down.
# Dict-valued `observed` is surfaced the same way, as `observed_fields`, because that is
# where the pose layer publishes its per-gate numbers precisely so a whitelist cannot lose
# them.
# ---------------------------------------------------------------------------------
EVIDENCE_MAX_LIST = 12  # list entries kept whole
EVIDENCE_MAX_STR = 700  # characters of any one string
EVIDENCE_MAX_DEPTH = 3
EVIDENCE_MAX_FIELDS = 60  # leaves per gate row


def _ev_scalar(x):
    if isinstance(x, str):
        return (
            x if len(x) <= EVIDENCE_MAX_STR else (x[:EVIDENCE_MAX_STR] + ' ...[+%d ch]' % (len(x) - EVIDENCE_MAX_STR))
        )
    return x


def _evidence_of(raw, dropped, path='', depth=0, budget=None):
    """Bounded, honest copy of a gate's evidence. Every omission is recorded in `dropped`."""
    if budget is None:
        budget = [EVIDENCE_MAX_FIELDS]
    if raw is None or isinstance(raw, (bool, int, float, str)):
        return _ev_scalar(raw)
    if hasattr(raw, 'tolist'):
        try:
            raw = raw.tolist()
        except Exception:  # noqa: BLE001
            return _jsonable(raw)
    if isinstance(raw, (list, tuple)):
        if len(raw) > EVIDENCE_MAX_LIST:
            dropped.append('%s: list of %d, kept the first %d' % (path or '<root>', len(raw), EVIDENCE_MAX_LIST))
            raw = list(raw)[:EVIDENCE_MAX_LIST]
        return [_evidence_of(x, dropped, '%s[%d]' % (path, i), depth + 1, budget) for i, x in enumerate(raw)]
    if isinstance(raw, dict):
        if depth >= EVIDENCE_MAX_DEPTH:
            dropped.append(
                '%s: nested dict with %d key(s) [%s] not expanded past depth %d'
                % (path or '<root>', len(raw), ', '.join(sorted(str(k) for k in raw)[:8]), EVIDENCE_MAX_DEPTH)
            )
            return '{%d keys: %s}' % (len(raw), ', '.join(sorted(str(k) for k in raw)[:8]))
        out = {}
        for k in sorted(raw, key=str):
            if budget[0] <= 0:
                dropped.append(
                    '%s: %d further key(s) omitted at the %d-field cap [%s]'
                    % (
                        path or '<root>',
                        len(raw) - len(out),
                        EVIDENCE_MAX_FIELDS,
                        ', '.join(sorted(str(x) for x in raw if str(x) not in out)[:8]),
                    )
                )
                break
            budget[0] -= 1
            out[str(k)] = _evidence_of(raw[k], dropped, '%s.%s' % (path, k) if path else str(k), depth + 1, budget)
        return out
    return _jsonable(raw)


def _flat_evidence(ev, prefix=''):
    """Scalar leaves of an evidence tree as `key=value` strings, for the text renderer."""
    out = []
    if isinstance(ev, dict):
        for k in sorted(ev, key=str):
            out.extend(_flat_evidence(ev[k], '%s.%s' % (prefix, k) if prefix else str(k)))
    elif isinstance(ev, (list, tuple)):
        if ev and all(not isinstance(x, (dict, list, tuple)) for x in ev):
            out.append('%s=[%s]' % (prefix, ', '.join(str(x) for x in ev)))
        else:
            for i, x in enumerate(ev):
                out.extend(_flat_evidence(x, '%s[%d]' % (prefix, i)))
    elif ev is not None and ev != '':
        s = str(ev)
        out.append('%s=%s' % (prefix, s if len(s) <= 240 else s[:240] + '...'))
    return out


# ---------------------------------------------------------------------------------
# WHICH EVIDENCE DECIDED THE GATE (W4-5)
# ---------------------------------------------------------------------------------
# The text report prints the first _EVIDENCE_ROWS leaves of a gate's evidence and names the
# remainder. Those leaves arrive ALPHABETICALLY, because _evidence_of sorts the tree for a
# stable digest — so on t5_pose_stiffness the fourteen printed fields were
# elbow_locked_fraction_* and erect_fraction_*, while `tilt_n_same_sign` and
# `tilt_opposition_required_fraction` — the two numbers the verdict is actually computed
# from — fell into "+56 further field(s) in the JSON artefact". Evidence computed and then
# not surfaced is this codebase's second recurring failure shape, and an alphabetical cap
# reproduces it every time a gate's decisive field starts with a late letter.
#
# THE RULE: a field is DECISIVE if the row itself names it —
#   * it is a key of the gate's declared BAND or THRESHOLD (the thresholds the verdict is
#     taken against: `tilt_opposition_required_fraction`, `tilt_n_same_sign_allowed`);
#   * it is the OBSERVED counterpart of one of those, i.e. its name is the same name with
#     the threshold qualifier taken off (`tilt_n_same_sign_allowed` -> `tilt_n_same_sign`,
#     `tilt_opposition_required_fraction` -> `tilt_opposition_fraction`);
#   * the gate's own explanation names it as a snake_case identifier (`tilt_sign_opposition`
#     in "this set FAILS on tilt_sign_opposition"). Only identifiers with an underscore
#     count: prose shares its vocabulary with field names, and matching bare words would
#     make every field decisive and the ranking meaningless;
#   * or it is one of the few names that carry a REPLACED verdict, which on an error-class
#     row that did not crash IS the finding (W4-1).
# Nothing is dropped and nothing is added by this: the same fields are printed, the
# decisive ones first, and the count in the "+N further" line is unchanged.
_EVIDENCE_QUALIFIER_TOKENS = frozenset(
    (
        'required',
        'allowed',
        'min',
        'max',
        'floor',
        'ceiling',
        'limit',
        'threshold',
        'declared',
        'expected',
        'canon',
        'cap',
        'bound',
        'tol',
        'tolerance',
        'permitted',
    )
)
# The STRUCTURAL keys of a band dict — {'lo': .., 'hi': .., 'width': .., 'units': ..} — name
# the shape of the band rather than the quantity it is on, so they are not evidence of
# anything and promoting a field called 'units' over a measured number would be a ranking
# that ranks the furniture.
_BAND_STRUCTURAL_KEYS = frozenset(
    ('lo', 'hi', 'low', 'high', 'width', 'units', 'value', 'band', 'interval', 'kind', 'basis')
)
_DECISIVE_EVIDENCE_KEYS = frozenset(
    (
        'status_the_gate_would_have_returned',
        'explain_the_gate_would_have_returned',
        'provenance_disagreement',
        'module_provenance',
        'gate_crashed',
        'gate_ran_and_produced_a_verdict',
    )
)
_EV_TOKEN_RE = re.compile(r'[^A-Za-z0-9]+')
_EV_PATH_RE = re.compile(r'[.\[\]]+')
_EV_IDENTIFIER_RE = re.compile(r'[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+')


def _ev_tokens(name):
    return [t for t in _EV_TOKEN_RE.split(str(name).lower()) if t]


def _ev_stem(name):
    """A field name with its threshold qualifier removed, as an unordered token set, so a
    declared threshold and the number it bounds resolve to the same thing."""
    return frozenset(t for t in _ev_tokens(name) if t not in _EVIDENCE_QUALIFIER_TOKENS)


def _decisive_evidence_vocabulary(band_raw, threshold_raw, explanation):
    """(names, stems) the gate itself named as deciding it."""
    names, stems = set(), set()
    for src in (band_raw, threshold_raw):
        if isinstance(src, dict):
            for k in src:
                low = str(k).strip().lower()
                if low in _BAND_STRUCTURAL_KEYS:
                    continue
                names.add(low)
                st = _ev_stem(k)
                if st:
                    stems.add(st)
    if isinstance(explanation, str):
        for w in _EV_IDENTIFIER_RE.findall(explanation):
            names.add(w.lower())
    return names, stems


def _field_is_decisive(path, names, stems):
    for seg in _EV_PATH_RE.split(str(path)):
        if not seg:
            continue
        s = seg.strip().lower()
        if s in names:
            return True
        st = _ev_stem(seg)
        if st and st in stems:
            return True
    return False


def _rank_evidence(fields, decisive):
    """`fields` (as produced by _flat_evidence) with the decisive ones first, each half
    left in its original alphabetical order. A stable partition, not a sort: two runs of
    the same report must produce the same page."""
    if not decisive:
        return list(fields)
    dec = set(decisive)
    head = [f for f in fields if f.split('=', 1)[0] in dec]
    tail = [f for f in fields if f.split('=', 1)[0] not in dec]
    return head + tail


def _read_gate(tier, g):
    """One gate, flattened to the fields this module renders."""
    status_raw = _get(g, 'status', 'result', 'outcome', 'state', default=None)
    status = normalize_status(status_raw)
    status_ok = status_is_recognised(status_raw)
    # DID THIS GATE RAISE? Asked of the producer, before anything else reads the status, so
    # that no line below can be tempted to answer it from the bucket (W4-1).
    crash_state, crash_declared = _crash_state(g)
    # `severity` is the severity that GOVERNED the run. A gate engine that calibrates its
    # severities against the reference sample also sends the one it originally declared,
    # and the difference between the two is a fact about the gate registry that belongs in
    # the report — quietly rendering only the effective one would hide the calibration
    # that this renderer's own arithmetic then depends on.
    sev_raw = _get(g, 'severity', 'level', default=None)
    sev_class, sev_text = _severity_class(sev_raw)
    sev_declared_raw = _get(g, 'severity_declared', default=None)
    _dcls, sev_declared = _severity_class(sev_declared_raw)
    # _severity_class(None) is 'unrecognised' by design — an unreadable severity must behave
    # like a high one. That is the right answer for a severity that IS there and cannot be
    # read, and the wrong one for a gate that never declared a second severity at all, so
    # the declared class is only consulted when the engine actually sent one.
    sev_declared_class = _dcls if sev_declared_raw is not None else None
    cal = g.get('severity_calibration') if isinstance(g, dict) else None
    cal = cal if isinstance(cal, dict) else {}
    calibrated = bool(sev_declared_raw is not None and str(sev_declared_raw) != str(sev_raw))
    obs_raw = _get(g, 'observed', 'value', 'measured', default=None)
    obs_val, obs_txt, units = _observed_of(obs_raw)
    # 'the gate declared no band' and 'the field was not there' are different facts, and
    # only the second one is a gap in the report. Both used to print as 'unknown'.
    if obs_raw is None:
        obs_txt = '-' if (isinstance(g, dict) and 'observed' in g) else UNKNOWN
    band_raw = _get(g, 'band', 'interval', 'expected', 'tolerance', default=None)
    lo, hi, width, band_text = _band_of(band_raw)
    if band_raw is None and isinstance(g, dict) and 'band' in g:
        band_text = 'none declared'
    if units is None and isinstance(_get(g, 'band', default=None), dict):
        units = _get(g, 'band').get('units')

    # WHAT "BLOCKING SEVERITY" MEANS IN THE UNRUN RULE (re-review, disclosed ambiguity).
    #
    # The printed unrun_blocking_rule says "a BLOCKING-SEVERITY gate whose status is skip,
    # report, missing or unknown ... is escalated". The code tested only the CALIBRATED
    # severity — the one that governed the run — so seven live instances of a gate the
    # registry DECLARED 'block', calibrated down to 'warn', which then produced no verdict
    # (t2_mahalanobis, t2_heights_tight, t2_breadths_wide, t2_girths_wide, t3_depths_wide on
    # abel; t2_breadths_wide, t5_canthal_tilt on anny-neutral) were not escalated, not
    # counted, and not named in doc['unrun_blocking']. The sentence and the code meant
    # different things by the same two words.
    #
    # RESOLVED IN THE STRICT DIRECTION, and the argument is about what a calibration IS. A
    # severity calibration is a measurement of how much of the real reference sample a
    # BAND would reject; it downgrades 'block' to 'warn' because the gate is too
    # trigger-happy to be trusted when it REJECTS a body. That is a statement about a
    # verdict. A gate that produced no verdict rejected nothing, so the calibration has
    # nothing to say about it, while the registry's DECLARED severity — "this body must not
    # ship without this check" — still stands untouched. Letting a rejection-rate soften the
    # ABSENCE of a check would be a rate about false positives excusing a false negative.
    # So: blocking for this rule if the gate is blocking under the severity that governed
    # the run OR under the severity the registry declared, and the row records which.
    #
    # The asymmetry with the downgrade branch below is deliberate: calibration may soften a
    # verdict the band produced, and may not soften the fact that no verdict was produced.
    blocking_sev = sev_class in ('high', 'unrecognised') or sev_declared_class in ('high', 'unrecognised')
    if not blocking_sev:
        blocking_sev_by = None
    elif sev_class in ('high', 'unrecognised'):
        blocking_sev_by = 'both' if sev_declared_class in ('high', 'unrecognised') else 'calibrated'
    else:
        blocking_sev_by = 'declared'

    # A failure is downgraded ONLY on a recognised low severity, and the downgrade is
    # recorded so it appears in the output instead of happening quietly.
    effective = status
    downgraded = False
    escalated = False
    if status == 'fail' and sev_class == 'low':
        effective = 'warn'
        downgraded = True
    elif status in _NO_VERDICT and blocking_sev:
        # A blocking check that produced no verdict has not passed. 'skip' and 'report'
        # take the warning bucket because an explicitly declared non-verdict carries no
        # bucket of its own that is worse — and leaving 'report' in the note bucket on a
        # blocking gate is precisely how t5_pronation_isolation shipped as neither a pass
        # nor a warning nor a failure (N1). MISSING, 'unknown' and 'error' KEEP their own
        # buckets, because each names a different failure of the run and each already
        # counts as something other than a pass. A crash is NEVER downgraded here: gates.py
        # shields ERROR from the rejection-rate calibration for the same reason.
        # An error-class row — a crash OR an engine refusal of the verdict the gate
        # produced — is not an "unrun check": it has its own bucket, its own flag and its
        # own alarm, and at blocking severity it is a FAILURE rather than an absence.
        escalated = status != GATE_ERROR
        if status in ('skip', 'report'):
            effective = 'warn'

    # An error on a low severity is still an error — it keeps its bucket and its mark, and
    # it counts towards the warning total rather than the blocking one, which is exactly
    # how gates.py classifies it (_classify: blocking only when severity == 'block').
    blocking_failure = bool(effective == 'fail' or (effective == GATE_ERROR and sev_class in ('high', 'unrecognised')))
    no_verdict = status in _NO_VERDICT

    delta = None
    if obs_val is not None:
        if lo is not None and obs_val < lo:
            delta = obs_val - lo
        elif hi is not None and obs_val > hi:
            delta = obs_val - hi
        elif lo is not None and hi is not None:
            delta = 0.0

    # F4: the evidence the gate engine attached, bounded and with every omission named.
    ev_dropped = []
    raw_detail = g.get('detail') if isinstance(g, dict) else None
    evidence = _evidence_of(raw_detail, ev_dropped)
    # N3: read the receipt flag off the RAW detail, not off the bounded copy. The bounded
    # copy sorts keys alphabetically under a 60-field cap, so a gate with enough evidence
    # could lose the very flag that says its evidence must be printed — the truncation
    # silently switching the printing rule off is exactly the shape of defect this flag
    # exists to fix.
    receipt = bool(isinstance(raw_detail, dict) and raw_detail.get(_RECEIPT_KEY))
    observed_fields = _evidence_of(obs_raw, ev_dropped, 'observed') if isinstance(obs_raw, dict) else None

    # W4-5: which of those leaves the gate's own verdict is taken against. Resolved here,
    # once, and carried in the row, so the text renderer, the JSON artefact and any later
    # reader agree on what "decisive" meant instead of each re-deriving it.
    explanation = _get(g, 'explain', 'explanation', 'why', 'message', 'note', 'detail')
    _dec_names, _dec_stems = _decisive_evidence_vocabulary(band_raw, _get(g, 'threshold', default=None), explanation)
    # On an ERROR-class row the fields that carry the REPLACED verdict are the finding
    # (W4-1), and only there: on an ordinary row a recorded provenance disagreement is a
    # side-fact, and promoting it would push the gate's own numbers off the page — the
    # defect W4-5 is about, one level up.
    if status == GATE_ERROR:
        _dec_names |= set(_DECISIVE_EVIDENCE_KEYS)
    decisive = [
        f.split('=', 1)[0]
        for f in (_flat_evidence(observed_fields) + _flat_evidence(evidence))
        if _field_is_decisive(f.split('=', 1)[0], _dec_names, _dec_stems)
    ]

    return {
        'id': str(_get(g, 'id', 'gate', 'name', 'key')),
        'tier': str(tier),
        'severity': sev_text,
        'severity_class': sev_class,
        'severity_declared': sev_declared if sev_declared_raw is not None else None,
        'severity_declared_class': sev_declared_class,
        # Whether this gate counts as BLOCKING SEVERITY for the unrun rule, and which of
        # the two severities made it so. 'declared' means the calibration had taken the
        # blocking severity away and the registry's declaration put it back for this rule
        # only — the row that used to fall silent.
        'blocking_severity': blocking_sev,
        'blocking_severity_by': blocking_sev_by,
        'severity_calibrated': calibrated,
        'severity_reason': _get(g, 'severity_reason', default=None) or cal.get('reason'),
        'reference_rejection_rate': _rejection_rate(g),
        'calibration_kind': cal.get('kind'),
        'calibration_basis': cal.get('basis'),
        'calibration_population': cal.get('reference_population'),
        'status_raw': _get(g, 'status', 'result', 'outcome', 'state', default=None),
        'status': status,
        'effective_status': effective,
        'downgraded_by_severity': downgraded,
        'escalated_unrun_blocking_gate': escalated,
        # The two facts every summary surface needs and none of them used to have:
        # whether this row is a blocking failure (a FAIL, or an ERROR-class row on a gate
        # entitled to block — whether it raised or the engine refused its verdict), and
        # whether it reached any verdict at all.
        'is_blocking_failure': blocking_failure,
        'produced_no_verdict': no_verdict,
        'evidence_is_the_finding': receipt,
        # W4-1. True / False / None, read from the producer's explicit flag and NEVER
        # derived from the status. None means the row did not declare, and is rendered as
        # "not declared" rather than defaulted in either direction.
        'crashed': (True if crash_state == CRASHED else False if crash_state == RAN else None),
        'crash_state': crash_state,
        'crash_declared_by_engine': crash_declared,
        # Which kind of error-class row this is, for a consumer that must not re-derive the
        # policy: 'crash' (raised), 'ran' (ran, and the engine refused or replaced the
        # verdict it produced), 'undeclared', or None for a row that is not error-class.
        'error_kind': (
            None
            if status != GATE_ERROR
            else 'crash'
            if crash_state == CRASHED
            else 'ran'
            if crash_state == RAN
            else 'undeclared'
        ),
        'status_recognised': status_ok,
        'title': _get(g, 'title', default=None),
        'threshold': _get(g, 'threshold', default=None),
        # Computed from the RAW band, not from the rendered text: a gate that explicitly
        # declared band=None has no threshold, and its placeholder string must not read
        # back as one.
        'has_threshold': (_get(g, 'threshold', default=None) is not None or band_raw is not None),
        'classification': _get(g, 'classification', default=None),
        'observed': obs_val,
        'observed_text': obs_txt,
        'units': units,
        'band_lo': lo,
        'band_hi': hi,
        'band_width': width,
        'band_text': _fmt_band(lo, hi, width, band_text, units),
        'delta_from_band': delta,
        # threshold_source first: it is the registry's citation for the NUMBER, which is
        # what the provenance footer is about. `source` on a result row describes the run.
        # What the threshold is a threshold ON, and which of those quantities a survey on
        # disk already answers. Both come straight off the gate row; this renderer does not
        # own the coverage list and must not re-derive it.
        'threshold_quantities': _get(g, 'threshold_quantities', default=None),
        'threshold_measured_conflict': _get(g, 'threshold_measured_conflict', default=None),
        # The structured evidence behind a MEASURED tag, straight off the row. This
        # renderer does not decide what makes a MEASURED claim true; it prints what the
        # registry declared so a reader can check it.
        'threshold_evidence': _get(g, 'threshold_evidence', default=None),
        'source': _get(g, 'threshold_source', 'source', 'provenance_source', 'reference'),
        'run_source': _get(g, 'source', default=None) if _get(g, 'threshold_source', default=None) else None,
        'provenance_class': _prov_class(g),
        # 'detail' is last: gates.py uses it for a dict of extra numbers, not for prose.
        'explanation': explanation,
        'malformed': bool(isinstance(g, dict) and g.get('_malformed')),
        'population': _get(g, 'population', default=None),
        # THE EVIDENCE. Deliberately widened whitelist; see the block above _read_gate.
        # `evidence` is the gate's `detail`; `observed_fields` is a dict-valued `observed`,
        # which the scalar renderer can only show as "{N fields}". Both bounded, and
        # `evidence_dropped` names every omission by key path.
        'evidence': evidence,
        'observed_fields': observed_fields,
        'evidence_dropped': ev_dropped or None,
        # The evidence paths the gate's band, threshold or explanation names as deciding
        # it. Printed first (W4-5); never printed INSTEAD of anything.
        'evidence_decisive': decisive or None,
    }
