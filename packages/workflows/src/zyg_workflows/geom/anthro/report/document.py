# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro.report — building the canonical document.

Moved out of the old single-file report.py (lines 1776-1962, 2255-2695).
"""

from zyg_workflows.geom.anthro.report.constants import (
    EXIT_CODES,
    SCHEMA,
    UNKNOWN,
    _zyg_log,
)
from zyg_workflows.geom.anthro.report.textfmt import _num
from zyg_workflows.geom.anthro.report.gatedata import _iter_gates
from zyg_workflows.geom.anthro.report.evidence import _read_gate
from zyg_workflows.geom.anthro.report.digest import _measurement_meta
from zyg_workflows.geom.anthro.report.document_parts import (
    build_alarms,
    classify_gates,
    coverage_block,
    finalise_digest,
    initial_verdict,
    policy_block,
    provenance_map,
    ratio_summary,
    reconcile_declared_verdict,
    resolve_identity,
    resolve_reference,
    strip_block,
    volatile_block,
)


# ---------------------------------------------------------------------------------
# building the canonical document
# ---------------------------------------------------------------------------------
def _age_alarm(age_years, ref):
    """The single most consequential misuse this package can commit.

    ANSUR II is soldiers aged 17-58. A 12-year-old scored against it is not "unusual", he
    is a different growth stage: cormic index ~.507 against an adult's ~.523 (legs
    proportionally LONGER, not shorter), head ~96% of adult length at ~85% of adult
    stature, and hands and feet proportionally large because growth is distal-to-proximal.
    Every one of those reads as a failure against an adult band, and every one of them is
    correct anatomy. Refusing to say so would make the percentile column a lie.
    """
    if age_years is None or ref is None:
        return None
    try:
        lo, hi = ref.doc['coverage']['ansur_age_years']
    except Exception:  # noqa: BLE001
        return None
    if lo <= age_years <= hi:
        return None
    return {
        'kind': 'age_outside_reference_population',
        'gates': [],
        'text': 'this subject is %.1f years old; the reference population is ANSUR II '
        'soldiers aged %d-%d. Every percentile and band below compares a body at '
        'one growth stage against another, and is NOT a plausibility statement. '
        "A 12-year-old's cormic index (sitting height / stature ~.507) is LOWER "
        "than an adult's (~.523), so his legs are proportionally LONGER; his "
        'head is ~96%% of adult length at ~85%% of adult stature; and growth is '
        'distal-to-proximal, so hands and feet are proportionally LARGE. Those '
        'read as failures against an adult band and are correct anatomy. Use the '
        'CDC 2000 stature-for-age and BMI-for-age LMS curves in the pack for a '
        'child, not these bands.' % (age_years, lo, hi),
    }


def _declared_roster(gate_report):
    """(declared gate ids, where it came from, whether a roster was CLAIMED) — the coverage
    denominator (W4-3).

    Preferred source is the ARTEFACT's own severity-calibration table, which gates.py
    builds from the whole registry before the first gate runs and which therefore names
    every gate the engine declared for this run — including the ones it then failed to
    emit. Restricted to `tiers_run` when the report declares which tiers it ran, because a
    deliberate tier subset is a smaller declared suite, not an incomplete one.

    Second source is the live registry, and it is consulted ONLY for a document that
    presents itself as an engine report (it carries a schema or names the tiers it ran).
    A hand-built two-gate document is not a truncated suite, and measuring it against 60
    registered gates would be this renderer inventing a claim the document never made — a
    different way of getting the denominator wrong from the one W4-3 is about. Such a
    document is measured against itself and SAYS SO, in coverage['roster_source'] and in
    the printed rule, which is generated per document from that string.
    """
    gr = gate_report if isinstance(gate_report, dict) else {}
    tiers_run = gr.get('tiers_run')
    tiers_run = {str(t) for t in tiers_run} if isinstance(tiers_run, (list, tuple, set)) and tiers_run else None
    claims_engine_report = bool(gr.get('schema') or tiers_run or gr.get('severity_calibration'))

    def keep(tier):
        return tiers_run is None or tier is None or str(tier) in tiers_run

    sc = gr.get('severity_calibration')
    rows = sc.get('rows') if isinstance(sc, dict) else None
    if isinstance(rows, (list, tuple)):
        ids = {
            str(r.get('id')) for r in rows if isinstance(r, dict) and r.get('id') is not None and keep(r.get('tier'))
        }
        if ids:
            return (
                ids,
                (
                    "the gate report's own severity-calibration roster"
                    + ('' if tiers_run is None else ', restricted to tiers %s' % ', '.join(sorted(tiers_run)))
                ),
                True,
            )
    if claims_engine_report:
        try:
            from zyg_workflows.geom.anthro.gates.registry import GATES as _gates_GATES

            ids = {str(g.id) for g in _gates_GATES if keep(getattr(g, 'tier', None))}
            if ids:
                return ids, 'geom.anthro.gates.GATES (the live registry)', True
        except Exception as _exc:  # noqa: BLE001
            _zyg_log.warning('live gate registry unavailable, the roster stays undeclared: %s', _exc)
        return set(), ('NO DECLARED ROSTER WAS AVAILABLE, and this document presents itself as an engine report'), True
    return (
        set(),
        (
            'the gates present in this document — it declares no roster and no '
            'engine schema, so there is nothing to have been omitted from'
        ),
        False,
    )


def build(
    gate_report=None,
    measurement=None,
    *,
    name=None,
    sex=None,
    ancestry=None,
    band_width='p5p95',
    ref=None,
    stature_m=None,
    age_years=None,
    extra=None,
):
    """Assemble the one document that the text, JSON and log renderers all read.

    Either argument may be None: a gate report with no measurement still renders its
    gates, and a measurement with no gate report still renders its strip. That matters
    because the strip is the part that shows stylization, and it must not depend on
    anything having gone wrong.
    """
    who = resolve_identity(gate_report, measurement, name=name, sex=sex, ancestry=ancestry, stature_m=stature_m)
    meta, gr = who.meta, who.gr
    name, sex, ancestry, stature_m = who.name, who.sex, who.ancestry, who.stature_m

    gates = [_read_gate(t, g) for t, g in _iter_gates(gate_report)]
    buckets = classify_gates(gates)
    alarms, severity_calibration = build_alarms(buckets, gates, gr)

    ref = resolve_reference(ref)
    aa = _age_alarm(_num(age_years), ref)
    if aa:
        alarms.append(aa)

    # THE DENOMINATOR IS THE DECLARED ROSTER, NOT THE ROWS IN FRONT OF US (W4-3).
    cov = coverage_block(gates, *_declared_roster(gate_report))
    alarms.extend(cov.alarms)
    # The old body rebound the `extra` PARAMETER here, to the gate ids present in the
    # document but absent from the declared roster, and doc['extra'] has carried that list
    # ever since. Kept deliberately and spelled out: dropping the rebind would silently
    # change what every consumer reads out of doc['extra'].
    extra = cov.gates_present_but_not_declared

    # A blocking failure is a FAIL whether the gate rejected the body or crashed trying.
    v = initial_verdict(buckets, alarms, cov.meets_floor)
    v, disagreement = reconcile_declared_verdict(v, gr)
    if disagreement:
        alarms.append(disagreement)

    rows, strip_alarms, v = strip_block(
        measurement, gates, v, sex=sex, ancestry=ancestry, band_width=band_width, stature_m=stature_m, ref=ref
    )
    alarms.extend(strip_alarms)

    doc = {
        'schema': SCHEMA,
        'character': name if name else UNKNOWN,
        'sex': sex if sex else UNKNOWN,
        'ancestry': ancestry if ancestry else None,
        'ancestry_declared': ancestry is not None,
        'band_width': band_width,
        'stature_m': stature_m,
        'age_years': _num(age_years),
        'age_outside_reference_population': bool(aa),
        'verdict': v,
        'exit_code': EXIT_CODES[v],
        'counts': buckets.counts,
        'n_gates': len(gates),
        # The three lists every summary surface needs, derived here ONCE so that no
        # consumer has to re-implement the policy and drop a case. `blocking` includes
        # gates that CRASHED at a blocking severity: they are why the verdict is FAIL, and
        # a caller filtering on effective_status == 'fail' would report zero of them.
        'blocking': buckets.blocking,
        # ONLY the gates the producer says RAISED (W4-1). The other two error-class
        # populations are named separately and are not crashes.
        'crashed': buckets.crashed,
        'errored_without_crashing': buckets.errored_no_crash,
        'error_crash_undeclared': buckets.error_crash_undeclared,
        'unrecognised_status': buckets.unrecognised_status,
        'unrun_blocking': buckets.unrun_blocking,
        'unrun_blocking_by_declared_severity': buckets.unrun_blocking_by_declared,
        # Whether this document is entitled to the word PASS at all; see the floor above.
        'coverage': cov.coverage,
        'gates': gates,
        # Passed through, not recomputed. The rejection rates are the gate engine's own
        # measurement against its own reference pack; a renderer that recomputed them
        # would be a second source of truth for the numbers it is supposed to be auditing.
        'severity_calibration': severity_calibration,
        'tiers': sorted({g['tier'] for g in gates}),
        'ratios': rows,
        'ratio_summary': ratio_summary(rows),
        'policy_alarms': alarms,
        'provenance': provenance_map(gates, rows, UNKNOWN),
        'policy': policy_block(cov.coverage['roster_source'], cov.n_declared, len(gates)),
        'measurement_meta': _measurement_meta(meta),
        'synthetic': bool(isinstance(gate_report, dict) and gate_report.get('synthetic')),
    }
    if extra:
        doc['extra'] = extra
    doc['volatile'] = volatile_block(gate_report, meta)
    finalise_digest(doc, alarms)
    return doc
