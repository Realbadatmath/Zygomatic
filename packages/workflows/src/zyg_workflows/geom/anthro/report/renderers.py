# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — renderers.

Moved out of the old single-file report.py (lines 2896-3594).
"""

import textwrap
from zyg_workflows.geom.anthro.report.constants import (
    CRASHED,
    ERROR,
    GATE_ERROR,
    MISSING,
    PASS,
    RAN,
    UNKNOWN,
    _COUNT_KEYS,
    _DEFAULT_WIDTH,
    _EVIDENCE_ROWS,
    _STATUS_MARK,
    _STATUS_ORDER,
)
from zyg_workflows.geom.anthro.report.textfmt import _fmt_num, _fmt_pct, _fmt_rate, _wrap
from zyg_workflows.geom.anthro.report.evidence import _flat_evidence, _rank_evidence
from zyg_workflows.geom.anthro.report.strip import render_percentile_strip
from zyg_workflows.geom.anthro.report.digest import exit_code


# ---------------------------------------------------------------------------------
# renderers
# ---------------------------------------------------------------------------------
def _banner(doc, width=_DEFAULT_WIDTH):
    c = doc.get('counts', {})
    inner = width - 4
    lines = [
        'VERDICT: %s' % doc.get('verdict', UNKNOWN),
        'character %s   sex %s   ancestry %s   stature %s'
        % (
            doc.get('character'),
            doc.get('sex'),
            doc.get('ancestry') or 'NOT DECLARED (pooled bands)',
            ('%.4f m' % doc['stature_m']) if doc.get('stature_m') else UNKNOWN,
        ),
        'gates %d   pass %d   warn %d   FAIL %d   ERROR %d   MISSING %d   unknown %d   '
        'not-run %d   note %d'
        % (
            doc.get('n_gates', 0),
            c.get(PASS, 0),
            c.get('warn', 0),
            c.get('fail', 0),
            c.get(GATE_ERROR, 0),
            c.get(MISSING, 0),
            c.get('unknown', 0),
            c.get('skip', 0),
            c.get('report', 0),
        ),
        'ratios %d   with a band %d   outside band %d   unchecked %d'
        % (
            doc.get('ratio_summary', {}).get('n', 0),
            doc.get('ratio_summary', {}).get('n_banded', 0),
            doc.get('ratio_summary', {}).get('n_outside', 0),
            doc.get('ratio_summary', {}).get('n_no_band', 0),
        ),
    ]
    # How much of the suite actually produced a verdict. Printed on EVERY report, not only
    # when it is short: "pass 17" means nothing without "37 of 60 gates reached a verdict",
    # and a reader who has to open the JSON to find that out will not.
    cov = doc.get('coverage') or {}
    if cov:
        lines.append(
            'gates that produced a verdict %d of %d declared (%s)   floor for a '
            'PASS: %d and %.0f%% (%s gate(s))   margin: %s'
            % (
                cov.get('n_produced_verdict', 0),
                cov.get('n_declared', cov.get('n_gates', 0)),
                'n/a' if cov.get('fraction') is None else '%.1f%%' % (100.0 * cov['fraction']),
                cov.get('floor_n', 0),
                100.0 * cov.get('floor_fraction', 0.0),
                'n/a' if cov.get('floor_gates') is None else '%d' % cov['floor_gates'],
                'n/a' if cov.get('margin_gates') is None else '%+d gate(s)' % cov['margin_gates'],
            )
        )
        absent = cov.get('gates_declared_but_absent') or []
        if absent:
            lines.append(
                'DECLARED GATES MISSING FROM THIS DOCUMENT (%d, counted in the '
                'denominator): %s%s'
                % (
                    len(absent),
                    ', '.join(str(x) for x in absent[:8]),
                    '' if len(absent) <= 8 else ', +%d more' % (len(absent) - 8),
                )
            )
        extra = cov.get('gates_present_but_not_declared') or []
        if extra and 'declares no roster' not in str(cov.get('roster_source')):
            lines.append(
                'GATES IN THIS DOCUMENT THAT THE ROSTER DOES NOT DECLARE (%d, '
                'also counted in the denominator): %s%s'
                % (
                    len(extra),
                    ', '.join(str(x) for x in extra[:8]),
                    '' if len(extra) <= 8 else ', +%d more' % (len(extra) - 8),
                )
            )
        if not cov.get('meets_floor', True):
            lines.append(
                'SUITE COVERAGE BELOW FLOOR: this document is not a pass, it is '
                'an unrun suite. A PASS is a claim about checks that ran.'
            )
    dg = doc.get('digest') or {}
    if dg and not dg.get('stable', True):
        lines.append(
            'DIGEST IS NOT STABLE: %d field(s) in this document move with the '
            'clock, so stable_sha256 is a per-run nonce and cannot identify this '
            'report: %s'
            % (
                len(dg.get('unstable_fields') or []),
                ', '.join(r['path'] for r in (dg.get('unstable_fields') or [])[:4]),
            )
        )
    # The counted total must close against the gate count. If it does not, a status bucket
    # is being dropped somewhere between _read_gate and here, and that is exactly the
    # class of defect this banner is supposed to make impossible to ship.
    tot = sum(c.get(k, 0) for k in _COUNT_KEYS)
    if tot != doc.get('n_gates', 0):
        lines.append(
            'COUNTS DO NOT CLOSE: %d gates, %d accounted for in the columns '
            'above. %d gate(s) are in a status bucket this banner does not print '
            '— treat every number in this report as unverified.'
            % (doc.get('n_gates', 0), tot, doc.get('n_gates', 0) - tot)
        )
    blk = doc.get('blocking') or []
    if blk:
        lines.append('BLOCKING: %s' % ', '.join(str(x) for x in blk))
    # W4-1. THREE HEADINGS, BECAUSE THERE ARE THREE FACTS. The single "GATES THAT CRASHED
    # (checked nothing)" line was printed over gates that had run and produced findings,
    # and a rebuttal five lines further down the page does not unprint a heading.
    crash = doc.get('crashed') or []
    if crash:
        lines.append('GATES THAT RAISED (checked nothing on this body): %s' % ', '.join(str(x) for x in crash))
    ran_err = doc.get('errored_without_crashing') or []
    if ran_err:
        lines.append(
            'GATES WHOSE VERDICT THE ENGINE REFUSED (they RAN and produced a '
            'finding; not a crash): %s' % ', '.join(str(x) for x in ran_err)
        )
    undecl = doc.get('error_crash_undeclared') or []
    if undecl:
        lines.append(
            'ERROR ROWS THAT DID NOT DECLARE WHETHER THEY RAISED (not assumed '
            'either way): %s' % ', '.join(str(x) for x in undecl)
        )
    unrec = doc.get('unrecognised_status') or []
    if unrec:
        lines.append(
            'GATES WITH A STATUS THIS RENDERER DOES NOT KNOW (rendered as '
            'ERRORS): %s' % ', '.join(str(x) for x in unrec)
        )
    unrun = doc.get('unrun_blocking') or []
    if unrun:
        lines.append('BLOCKING GATES THAT DID NOT RUN (no verdict, NOT a pass): %s' % ', '.join(str(x) for x in unrun))
    if doc.get('synthetic'):
        lines.insert(1, 'SYNTHETIC CONTRACT FIXTURE — these gate rows are a shape test, NOT a measurement of a body')
    bar = '+' + '=' * (width - 2) + '+'
    out = [bar]
    for ln in lines:
        for part in textwrap.wrap(ln, inner) or ['']:
            out.append('| %-*s |' % (inner, part))
    out.append(bar)
    return '\n'.join(out)


def render_gate_table(doc, width=_DEFAULT_WIDTH, only=None):
    """The gate table, grouped by tier and ordered worst-first inside each tier."""
    gates = doc.get('gates') or []
    if not gates:
        return 'GATES — none. No gate report was supplied, or it contained no gates.'
    if only:
        gates = [g for g in gates if g['effective_status'] in only]
    out = ['GATES']
    order = {s: i for i, s in enumerate(_STATUS_ORDER)}
    # Columns are sized from the data rather than fixed, because a truncated gate id or a
    # truncated band is exactly the information the reader came for.
    id_w = min(46, max([len(g['id']) for g in gates] + [4]))
    sev_w = min(14, max([len(g['severity'] or UNKNOWN) for g in gates] + [8]))
    obs_w = min(18, max([len(g['observed_text']) for g in gates] + [8]))
    band_w = max(12, width - (2 + 7 + 1 + id_w + 1 + sev_w + 1 + obs_w + 1))
    fmt = '  %%-7s %%-%ds %%-%ds %%%ds %%-%ds' % (id_w, sev_w, obs_w, band_w)
    for tier in sorted({g['tier'] for g in gates}):
        block = sorted(
            [g for g in gates if g['tier'] == tier], key=lambda g: (order.get(g['effective_status'], 9), g['id'])
        )
        if not block:
            continue
        out.append('')
        out.append('  tier: %s   (%d gates)' % (tier, len(block)))
        out.append((fmt % ('status', 'gate', 'severity', 'observed', 'band')).rstrip())
        for g in block:
            st = g['effective_status']
            # A bucket with no mark of its own is printed as a shout, not as its own name:
            # an unrendered status word in this column reads like a verdict and is not one.
            mark = _STATUS_MARK.get(st, '!%s!' % str(st).upper()[:10])
            out.append(
                (
                    fmt
                    % (
                        mark,
                        g['id'][:id_w],
                        (g['severity'] or UNKNOWN)[:sev_w],
                        g['observed_text'][:obs_w],
                        g['band_text'][:band_w],
                    )
                ).rstrip()
            )
            detail = []
            if g.get('severity_calibrated'):
                detail.append(
                    'severity %s -> %s BY MEASUREMENT (%s): %s'
                    % (
                        g.get('severity_declared'),
                        g['severity'],
                        _fmt_rate(g.get('reference_rejection_rate')),
                        g.get('severity_reason') or 'no reason recorded',
                    )
                )
            elif st != PASS and g.get('reference_rejection_rate') is not None:
                # The rate belongs next to the finding, not only in the table at the
                # bottom: a reader deciding what to do about THIS row needs to know how
                # many real people the same rule would have thrown out. Named with its
                # own population, because not every gate is measured against the same one
                # — a child-growth gate is calibrated on CDC children, not on ANSUR.
                detail.append(
                    'as configured this gate rejects %.3f%% of %s'
                    % (100.0 * g['reference_rejection_rate'], g.get('calibration_population') or 'the reference sample')
                )
            if g['downgraded_by_severity']:
                detail.append('DOWNGRADED from fail to warn on declared severity %r' % g['severity'])
            # W4-1. The sentence follows the ENGINE'S OWN FLAG, not the bucket. "THIS GATE
            # RAISED. It checked nothing on this body." was printed over
            # t5_patellar_ligament, whose finding is that the patellar ligament is not
            # modelled at all — a measured, blocking, anatomical failure filed as an
            # infrastructure crash on every body.
            consequence = (
                ' — and this gate is entitled to block, so the verdict is FAIL'
                if g.get('is_blocking_failure')
                else ' — its severity is not blocking, so it counts as a warning'
            )
            if g.get('crash_state') == CRASHED:
                detail.append(
                    'THIS GATE RAISED. It checked nothing on this body. A crash '
                    'is not a band rejection, so the severity calibration does '
                    'not apply to it%s%s'
                    % (consequence, '' if g.get('is_blocking_failure') else '; the check still did not happen')
                )
            elif st == GATE_ERROR and g.get('crash_state') == RAN:
                detail.append(
                    'THIS GATE DID NOT RAISE. The engine declares it RAN, '
                    'measured its subject and produced a finding, and then '
                    'refused or replaced the verdict — status %r. This is not an '
                    'infrastructure failure: the finding the gate produced is '
                    'printed below and travels in gates[].evidence under '
                    'status_the_gate_would_have_returned%s.' % (g['status_raw'], consequence)
                )
            elif st == GATE_ERROR:
                detail.append(
                    'THIS ROW IS AN ERROR AND DID NOT DECLARE WHETHER THE GATE '
                    'RAISED. This renderer reads a boolean the engine sets and '
                    'never infers one from the status, because "error" covers '
                    'both a crash and a refused verdict. Whether the check ran '
                    'is UNKNOWN%s.' % consequence
                )
            elif g['escalated_unrun_blocking_gate']:
                # Which severity made it blocking has to be in the sentence. On a row the
                # calibration downgraded, "status 'skipped' on a 'warn'-severity gate — a
                # blocking check that produced no verdict" reads as a contradiction unless
                # it says that the DECLARED severity is the one doing the work.
                detail.append(
                    'ESCALATED: status %r on a %s gate — a blocking check that '
                    'produced no verdict has not passed%s'
                    % (
                        g['status_raw'],
                        ('%r-severity' % g['severity'])
                        if g['blocking_severity_by'] != 'declared'
                        else 'gate the registry DECLARED %r (the reference rejection '
                        'rate had downgraded it to %r, which softens a verdict '
                        'and cannot soften the absence of one)' % (g['severity_declared'], g['severity']),
                        ', so this row counts as a warning'
                        if g['effective_status'] == 'warn'
                        else ' and is named in the report header',
                    )
                )
            off_band = g['delta_from_band'] not in (None, 0.0)
            if off_band:
                d = g['delta_from_band']
                txt = 'distance past the band edge: %+.5g' % d
                if doc.get('stature_m') and 'over_stature' in g['id']:
                    txt += ' (= %+.1f mm at this stature)' % (d * doc['stature_m'] * 1000)
                detail.append(txt)
            # THE RECEIPT ROWS (N3). Two of this wave's own headline numbers — the
            # threshold-provenance census and the pose-stiffness tilt statistics — were
            # reachable only by opening the JSON, because the rule below prints evidence for
            # non-pass and off-band rows and both of them PASS. That is F4's blind spot
            # pointing the other way: a gate whose deliverable IS the numbers publishes
            # nothing on the page precisely when it has nothing to complain about.
            # gates.py marks such a row with RECEIPT_KEY in its detail (see
            # geom.anthro.gates.RECEIPT_KEY); the flag is a statement about the gate, never
            # about the verdict, so it is read here and never conditioned on status.
            receipt = bool(g.get('evidence_is_the_finding'))
            # A PASS whose observed value sits OUTSIDE its declared band is the one
            # combination whose explanation may never be suppressed: printing the distance
            # past the band edge and withholding the reason it was not a failure is how
            # t5_canthal_tilt shipped '-0.108 below its own band, classification ok' with
            # nothing on the page to say why. Whenever the row is off its band, the
            # explanation prints regardless of status.
            if (st != PASS or off_band or receipt) and g['explanation'] and g['explanation'] != UNKNOWN:
                detail.append(str(g['explanation']))
            if st != PASS and g['population'] and g['population'] != UNKNOWN:
                detail.append('population: %s' % g['population'])
            # THE EVIDENCE (F4). Printed for every row that is not a clean pass, for a
            # pass that sits off its band, and for a receipt row. A number the engine
            # computed as the reason for a verdict has to be readable next to the verdict.
            if st != PASS or off_band or receipt:
                fields = _flat_evidence(g.get('observed_fields'))
                fields += _flat_evidence(g.get('evidence'))
                # W4-5: DECISIVE EVIDENCE FIRST. The cap is a screen-space limit, and
                # taking the first fourteen ALPHABETICALLY meant t5_pose_stiffness printed
                # elbow_locked_fraction_* and erect_fraction_* while the two numbers its
                # verdict is computed from — tilt_n_same_sign against
                # tilt_opposition_required_fraction — were named only as part of "+56
                # further field(s)". Nothing is dropped or added here; the fields the row's
                # own band, threshold or explanation names are moved to the front.
                decisive = g.get('evidence_decisive') or []
                fields = _rank_evidence(fields, decisive)
                if fields:
                    detail.append('evidence: ' + ' | '.join(fields[:_EVIDENCE_ROWS]))
                    if len(fields) > _EVIDENCE_ROWS:
                        shown = {f.split('=', 1)[0] for f in fields[:_EVIDENCE_ROWS]}
                        held = [d for d in decisive if d not in shown]
                        detail.append(
                            'evidence: +%d further field(s) in the JSON artefact '
                            'under gates[].evidence%s. The %d field(s) this '
                            "gate's band, threshold or explanation names as "
                            'deciding it are printed FIRST above%s'
                            % (
                                len(fields) - _EVIDENCE_ROWS,
                                '' if not decisive else ' (ranked: decisive first, then alphabetical)',
                                len(decisive),
                                ''
                                if not held
                                else ' — except %d that did not fit: %s' % (len(held), ', '.join(held[:6])),
                            )
                        )
                if g.get('evidence_dropped'):
                    detail.append('evidence NOT fully carried: %s' % '; '.join(g['evidence_dropped'][:4]))
            for d in detail:
                out.extend(_wrap(d, width, 10))
    return '\n'.join(out)


def render_provenance(doc, width=_DEFAULT_WIDTH):
    """Every distinct source behind every number above, plus the claim-class census. A
    report whose thresholds cannot be traced is not a report."""
    out = ['PROVENANCE — where every threshold in this report came from']
    prov = doc.get('provenance') or {}
    classes = {}
    for g in doc.get('gates') or []:
        classes[g['provenance_class']] = classes.get(g['provenance_class'], 0) + 1
    out.append('')
    out.append(
        '  claim classes across %d gates: %s'
        % (doc.get('n_gates', 0), ', '.join('%s %d' % (k, classes[k]) for k in sorted(classes)) or 'none')
    )
    exempt = [
        g['id']
        for g in doc.get('gates') or []
        if g['provenance_class'] == 'UNDECLARED' and not g.get('has_threshold') and not g['malformed']
    ]
    if exempt:
        out.extend(
            _wrap(
                '%d gate(s) declare no threshold and no band at all, so there is '
                'no number to attribute and no provenance is demanded of them: '
                '%s. They are report-only rows; if one of them ever grows a '
                'threshold it must grow a provenance with it.' % (len(exempt), ', '.join(sorted(exempt))),
                width,
                2,
            )
        )
    out.extend(
        _wrap(
            'CLAIM CLASSES, best evidence first. '
            'MEASURED = a number read off a named dataset, carrying source, '
            'population and n. '
            'CANON = a number printed in an artist or anatomy reference: a '
            'drawing convention or a clinical rule of thumb, with no sample, no n '
            'and no sampling frame. It ranks BELOW MEASURED and may set a '
            'threshold only where ANSUR II / CDC / NHANES is silent — the angle, '
            'sign, curvature, relief and joint-range material — and may never '
            'block a quantity a survey already answers. '
            'HOUSE = our own policy, carrying a rationale, never presented as a '
            'measurement. CONTESTED = a number the literature does not support; '
            'these must not ship.',
            width,
            2,
        )
    )
    canon = sorted(g['id'] for g in doc.get('gates') or [] if g['provenance_class'] == 'CANON')
    if canon:
        out.append('')
        out.extend(
            _wrap(
                '%d gate(s) carry a CANON threshold: %s. Check the severity '
                'table above: a printed number has no population behind it, so '
                'the measured-severity policy takes any blocking claim away from '
                "it automatically unless the gate's subject is our own rig or "
                'registry rather than a person.' % (len(canon), ', '.join(canon)),
                width,
                2,
            )
        )
    if not prov:
        out.append('')
        out.append('  no source strings were attached to any threshold in this report.')
    for i, src in enumerate(sorted(prov), 1):
        out.append('')
        cls = prov[src].get('class', 'UNDECLARED')
        users = prov[src].get('gates') or []
        out.append('  [%d] %s' % (i, cls))
        out.extend(_wrap(src, width, 6))
        out.extend(
            _wrap(
                'used by: %s' % ', '.join(sorted(set(users))[:12])
                + (' (+%d more)' % (len(set(users)) - 12) if len(set(users)) > 12 else ''),
                width,
                6,
            )
        )
    pol = doc.get('policy') or {}
    out.append('')
    out.append("  [policy] HOUSE — this renderer's own arithmetic")
    # EVERY rule in the policy block is printed, in a preferred order and then whatever is
    # left. This used to be a hand-typed list of five names, which is the same shape as the
    # hand-typed unrun_blocking_rule that drifted from the tuple it described: a rule added
    # to the document and not to this tuple would be enforced on every body and readable
    # only by opening the JSON. The self-test asserts the two cannot diverge.
    preferred = (
        'verdict_rule',
        'missing_field_rule',
        'crash_rule',
        'unrun_blocking_rule',
        'coverage_floor_rule',
        'severity_rule',
        'digest_rule',
    )
    rules = [k for k in preferred if pol.get(k)]
    rules += sorted(k for k in pol if k.endswith('_rule') and k not in preferred and pol.get(k))
    for k in rules:
        out.extend(_wrap('%s: %s' % (k, pol[k]), width, 6))
    mm = doc.get('measurement_meta') or {}
    if mm:
        out.append('')
        out.append('  [measurement conventions in force]')
        for k in ('girth_convention', 'limb_girth_convention', 'coco_source', 'iso_caveat', 'arm_exclusion'):
            if mm.get(k):
                out.extend(_wrap('%s: %s' % (k, mm[k]), width, 6))
    return '\n'.join(out)


def render_severity_calibration(doc, width=_DEFAULT_WIDTH):
    """Why each gate is allowed to block, as a number.

    A severity is a claim about how bad a violation is, and left as a declaration it is
    unfalsifiable. When the gate engine ships a calibration — the fraction of the real
    reference sample each gate would reject as configured — this section prints it, so a
    reader can check the severity of every row above against the population instead of
    taking the registry's word for it. The section is silent when no calibration was
    shipped, rather than inventing one.
    """
    cal = doc.get('severity_calibration') or {}
    rows = cal.get('rows') or []
    if not rows:
        return ''
    out = ['SEVERITY CALIBRATION — the rejection rate that entitles each gate to block']
    out.append('')
    out.extend(_wrap('policy: %s' % cal.get('policy', UNKNOWN), width, 2))
    if cal.get('reference'):
        out.extend(_wrap('reference sample: %s' % cal['reference'], width, 2))
    ib = cal.get('independent_bands_admission') or {}
    for sex in sorted(ib):
        rec = ib[sex] or {}
        if rec.get('admitted_fraction') is not None:
            out.extend(
                _wrap(
                    "the pack's own measurement, %s: %s = %.4f. That is the reason this "
                    'section exists — a gate set that blocks on any single marginal band '
                    'rejects the majority of real people.'
                    % (sex, rec.get('method', 'independent band admission'), rec['admitted_fraction']),
                    width,
                    2,
                )
            )
    out.append('')
    idw = min(40, max([len(str(r.get('id', ''))) for r in rows] + [4]))
    fmt = '  %-*s %-9s %-10s %10s  %-16s %s'
    out.append(fmt % (idw, 'gate', 'declared', 'effective', 'rejects', 'basis', 'kind'))
    order = {'block': 0, 'warn': 1, 'report': 2}
    for r in sorted(rows, key=lambda r: (not r.get('downgraded'), order.get(r.get('effective'), 3), str(r.get('id')))):
        rate = r.get('rejection_rate')
        out.append(
            fmt
            % (
                idw,
                str(r.get('id'))[:idw],
                str(r.get('declared')),
                str(r.get('effective')) + ('*' if r.get('downgraded') else ''),
                '-' if rate is None else '%.3f%%' % (100.0 * float(rate)),
                str(r.get('basis')),
                str(r.get('kind')),
            )
        )
    down = [r for r in rows if r.get('downgraded')]
    out.append('')
    if down:
        out.extend(
            _wrap(
                '* %d gate(s) had a blocking claim TAKEN AWAY by measurement. '
                'This is not leniency: each one was measured to reject more of '
                'the real reference sample than the primary plausibility gate '
                'does, so blocking on it would have rejected people who exist.' % len(down),
                width,
                2,
            )
        )
        for r in down:
            out.append('')
            out.append('    %s' % r.get('id'))
            out.extend(_wrap(str(r.get('reason') or ''), width, 8))
            if r.get('explain'):
                out.extend(_wrap(str(r['explain']), width, 8))
    else:
        out.extend(
            _wrap('no gate was downgraded: every blocking gate in this registry measured inside the ceiling.', width, 2)
        )
    blank = [r['id'] for r in rows if r.get('kind') == 'undeclared']
    if blank:
        out.append('')
        out.extend(
            _wrap(
                'gate(s) %s declare no calibration at all, so nothing is known '
                'about how many real people they reject. They may warn; they may '
                'not block.' % ', '.join(blank),
                width,
                2,
            )
        )
    return '\n'.join(out)


def render_alarms(doc, width=_DEFAULT_WIDTH):
    alarms = doc.get('policy_alarms') or []
    if not alarms:
        return ''
    out = ['POLICY ALARMS — defects in the gate registry, not in the body']
    for a in alarms:
        out.append('')
        out.append('  ! %s' % a.get('kind'))
        out.extend(_wrap(a.get('text'), width, 6))
    return '\n'.join(out)


def render_text(doc, width=_DEFAULT_WIDTH, show_passing_gates=True, include_summary=True):
    """The whole terminal report."""
    parts = [_banner(doc, width), '']
    alarms = render_alarms(doc, width)
    if alarms:
        parts.extend([alarms, ''])
    parts.append(
        render_gate_table(
            doc, width, only=None if show_passing_gates else (GATE_ERROR, 'fail', 'warn', MISSING, 'unknown')
        )
    )
    parts.append('')
    sev = render_severity_calibration(doc, width)
    if sev:
        parts.extend([sev, ''])
    if doc.get('ratios'):
        cav = None
        if doc.get('age_outside_reference_population'):
            cav = (
                'this subject is %s years old and the bands below are ANSUR II '
                'adults — the percentile column compares two different growth '
                'stages. See the policy alarm above.'
                % (('%.1f' % doc['age_years']) if doc.get('age_years') else UNKNOWN)
            )
        parts.append(render_percentile_strip(doc['ratios'], width, caveat=cav))
        parts.append('')
        parts.append(_render_stylization(doc, width))
        parts.append('')
    parts.append(render_provenance(doc, width))
    if include_summary:
        parts.append('')
        parts.append(render_summary(doc))
    return '\n'.join(parts)


def _render_stylization(doc, width=_DEFAULT_WIDTH):
    """The stylization delta, stated as a number.

    Two separate facts, and they are not the same one: how far outside its band the worst
    ratio is, and whether the WHOLE body sits consistently to one side of the population
    median. The second is the one a marginal-band check cannot see — a body every one of
    whose ratios sits at p90 has passed every band and is still a caricature.
    """
    rows = [r for r in doc.get('ratios') or [] if r.get('percentile') is not None]
    out = ['STYLIZATION DELTA — how far this body is from the reference population']
    if not rows:
        out.append('  no ratio had a reference band, so no delta can be stated.')
        return '\n'.join(out)
    pcts = sorted(r['percentile'] for r in rows)
    n = len(pcts)
    med = pcts[n // 2] if n % 2 else 0.5 * (pcts[n // 2 - 1] + pcts[n // 2])
    extreme = sum(1 for p in pcts if p <= 5.0 or p >= 95.0)
    high = sum(1 for p in pcts if p >= 50.0)
    outside = [r for r in rows if r.get('status') == 'outside']
    out.append(
        '  %d ratios with a band; median percentile %.1f; %d of %d at or above '
        'p50; %d beyond p5/p95' % (n, med, high, n, extreme)
    )
    out.extend(
        _wrap(
            'a median percentile far from 50 is a whole-body style, not a '
            'per-ratio error: it is the number to record as the deliberate '
            'stylization delta rather than to gate away.',
            width,
            2,
        )
    )
    if outside:
        worst = sorted(outside, key=lambda r: -abs(r.get('delta') or 0.0))[:6]
        out.append('')
        out.append('  furthest outside their bands:')
        for r in worst:
            mm = r.get('delta_mm_of_stature')
            out.append(
                '    %-44s %+.5f%s  (value %s, band %s..%s, %s)'
                % (
                    r['ratio'][:44],
                    r['delta'],
                    '' if mm is None else ' = %+.1f mm' % mm,
                    _fmt_num(r['value']),
                    _fmt_num(r['band_lo']),
                    _fmt_num(r['band_hi']),
                    _fmt_pct(r['percentile']).strip(),
                )
            )
    if not doc.get('ancestry_declared'):
        out.append('')
        out.extend(
            _wrap(
                'ANCESTRY WAS NOT DECLARED, so every band above is the pooled '
                'US Army mixture. In this data crotch-height/stature runs .4952 '
                'Black / .4796 White / .4788 Hispanic / .4712 Asian in males — a '
                '.024 spread, 44 mm of leg on a 1.85 m man. A pooled band used '
                'as a universal gate encodes a bias, not a tolerance.',
                width,
                2,
            )
        )
    return '\n'.join(out)


def render_summary(doc):
    """One line, key=value, no separators that a log parser has to escape."""
    c = doc.get('counts', {})
    rs = doc.get('ratio_summary', {})
    bits = [
        'anthro',
        'char=%s' % (doc.get('character') or UNKNOWN),
        'verdict=%s' % doc.get('verdict', ERROR),
        'exit=%d' % exit_code(doc),
        'gates=%d' % doc.get('n_gates', 0),
        'pass=%d' % c.get(PASS, 0),
        'warn=%d' % c.get('warn', 0),
        'fail=%d' % c.get('fail', 0),
        'error=%d' % c.get(GATE_ERROR, 0),
        'missing=%d' % c.get(MISSING, 0),
        'unknown=%d' % c.get('unknown', 0),
        'notrun=%d' % c.get('skip', 0),
        'note=%d' % c.get('report', 0),
        # The two counts a log reader needs to know a "0 fail" line is not the whole story.
        'blocking=%d' % len(doc.get('blocking') or []),
        'unrun_blocking=%d' % len(doc.get('unrun_blocking') or []),
        # The error bucket split the way the engine splits it (W4-1): a gate that RAISED
        # and a gate whose verdict the engine refused are both errors and are not the same
        # event, and a log line that reports only 'error=' cannot tell them apart.
        'crashed=%d' % len(doc.get('crashed') or []),
        'error_ran=%d' % len(doc.get('errored_without_crashing') or []),
        # ...and the third: how much of the suite reached a verdict at all. A pass=0 line
        # with everything skipped used to be a PASS (NEW-5).
        'verdicts=%d' % (doc.get('coverage') or {}).get('n_produced_verdict', 0),
        'coverage_floor=%s' % ('ok' if (doc.get('coverage') or {}).get('meets_floor', True) else 'BELOW'),
        'ratios=%d' % rs.get('n', 0),
        'banded=%d' % rs.get('n_banded', 0),
        'outside=%d' % rs.get('n_outside', 0),
        'sex=%s' % (doc.get('sex') or UNKNOWN),
        'ancestry=%s' % (doc.get('ancestry') or 'undeclared'),
        'width=%s' % doc.get('band_width'),
    ]
    if doc.get('stature_m'):
        bits.append('stature_m=%.4f' % doc['stature_m'])
    worst = None
    # Blocking failures, not just band failures: a crashed blocking gate is the finding.
    fails = [g for g in doc.get('gates') or [] if g.get('is_blocking_failure', g.get('effective_status') == 'fail')]
    if fails:
        worst = sorted(fails, key=lambda g: -abs(g.get('delta_from_band') or 0.0))[0]
        bits.append('worst=%s' % worst['id'])
        if worst.get('delta_from_band'):
            bits.append('worst_delta=%+.5g' % worst['delta_from_band'])
    if doc.get('policy_alarms'):
        bits.append('alarms=%s' % ';'.join(a.get('kind', '?') for a in doc['policy_alarms']))
    if doc.get('synthetic'):
        bits.append('SYNTHETIC=1')
    bits.append('sha=%s' % (doc.get('stable_sha256') or '')[:12])
    if not (doc.get('digest') or {}).get('stable', True):
        bits.append('sha_stable=NO')
    return ' '.join(bits)
