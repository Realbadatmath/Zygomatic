# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The anthropometric gating layer: the character spec, the reference
population, the gate run and the compact summary buckets.

Moved verbatim out of the old single-file mesh_skeletons.py (lines 1961-2574).
"""

import json
import os
import sys
import time
import traceback

import numpy as np

from zyg_workflows.geom.mesh_skeletons.spec import ANTHRO_REPORT_FILE, ROOT

from zyg_workflows.geom.mesh_skeletons.rig import _build_mesh

from zyg_workflows.geom.mesh_skeletons.anatomy import _apply_anatomy

from zyg_workflows.geom.mesh_skeletons.artifacts import _vert_sha

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── anthropometric gating (2026-08-05) ───────────────────────────────────────────
# Every issued body is measured against real anthropometric distributions by
# geom/anthro/ and the verdict is stored beside it. Read the env flag at CALL time, not
# at import time: a long-lived GUI process must be able to turn the gates off without a
# restart, and a test must be able to exercise both paths in one process.
ANTHRO_SPEC_SCHEMA = 'geom.mesh_skeletons/character_spec/1'

# anny's BodyProportions macro is the STYLIZATION AXIS: 108 MakeHuman targets split
# idealproportions/uncommonproportions. It is a named parameter, so a departure from
# ordinary proportion is something a character DECLARES, not something a build drifts
# into. This constant names the axis; it does not say what value is good, because no
# such value is measurable.
STYLIZATION_AXIS = 'proportions'

# The originals' macro values are the output of geom/fit_reference.py — a chamfer fit
# against the CC0 Blender Studio realistic bodies. That is a recorded provenance for the
# proportions value, which is why the originals declare their stylization and a derived
# character that merely inherited the number does not.
ORIGINAL_STYLIZATION_INTENT = (
    'fitted, not chosen: the BodyProportions value is the output of the '
    'geom/fit_reference.py chamfer fit against the CC0 Blender Studio realistic body. '
    'No aesthetic target was applied.'
)


def _anthro_enabled():
    return os.environ.get('ZYG_ANTHRO_GATES', '1').strip().lower() not in ('0', 'false', 'no', 'off', '')


def _reference_population(ancestry):
    """What the bands this body will be scored against actually describe.

    Read out of the reference pack rather than restated here, so the recorded population
    cannot drift away from the one the gates used. A body scored against 'pooled' because
    nobody declared an ancestry is NOT scored against "the average human" — ancestry is
    the largest proportion effect in the data (crotch-height/stature spans .4712-.4952
    across the male DODRace groups, 44 mm of leg on a 1.85 m man) and that fact has to be
    on the record, not implied by a silence.
    """
    # ORDERING BUG, fixed 2026-08-05 (was: CRITICAL). This function is called from
    # _character_spec, which build_originals()/derive() run BEFORE _anthro_run() — and
    # _anthro_run() was the only caller of _ensure_repo_importable(). Under
    # `python3 geom/mesh_skeletons.py` the repo root is not on sys.path yet, so
    # `from geom.anthro.reference import ...` raised ModuleNotFoundError, the except
    # below swallowed it into a string, and the FIRST character issued in every process
    # recorded 'pack_unreadable' instead of its reference population. It is baked into
    # three of the four issued bodies (male, abel, cornelis — see the fix note in
    # _reference_population_damaged). The path fix must therefore run HERE, not later.
    _ensure_repo_importable()
    out = {
        'group': ancestry or 'pooled',
        'group_source': (
            'declared ancestry'
            if ancestry
            else 'UNDECLARED ancestry -> the pooled band. Pooled is a mixture, not a neutral population.'
        ),
    }
    try:
        # the pack's own location, NOT one derived from ROOT: ROOT is overridable (tests
        # point it at a scratch tree) and the reference pack does not move with it.
        # Imported from the submodule directly — `from geom.anthro import reference`
        # resolves to the package's lazily-exported singleton FUNCTION of that name.
        from zyg_workflows.geom.anthro.reference import ROOT as pack_root

        with open(os.path.join(pack_root, 'reference.json')) as f:
            doc = json.load(f)
        cov = doc.get('coverage') or {}
        out.update(
            {
                'pack_readable': True,
                'pack': 'data/assets/anthro_reference/reference.json',
                'pack_generated': doc.get('generated'),
                'survey': cov.get('ansur_population'),
                'age_years': cov.get('ansur_age_years'),
                'groups_available': sorted((doc.get('stats') or {}).get('male', {})),
            }
        )
    except Exception as e:  # noqa: BLE001
        # LOUD. This is provenance, not a gate: the body is still issued, but nothing
        # about that is routine and it must never scroll past unnoticed. The record says
        # in words that it is DAMAGED, so a reader of params.json cannot mistake the
        # absence of a survey name for "no ancestry was declared".
        out['pack_readable'] = False
        out['pack_unreadable'] = '%s: %s' % (type(e).__name__, e)
        out['pack_unreadable_meaning'] = (
            'DAMAGED PROVENANCE RECORD. The reference pack could not be read at spec '
            'time, so this body does NOT record which population its bands describe. '
            'The gates may still have scored it (they resolve the pack independently) — '
            'in that case the record is silent about a comparison that happened, which '
            'is exactly the failure this field exists to prevent. Re-issue the character '
            'once the pack is readable; `gate` alone does not repair it.'
        )
        _zyg_log.info(
            '  ANTHRO REFERENCE POPULATION UNREADABLE: %s: %s\n'
            '    the character spec will record DAMAGED PROVENANCE (no survey, no pack '
            'generation date, no ancestry-group inventory).\n'
            '    The body is still issued and still gated — but nothing on its record '
            'says which population it was scored against.' % (type(e).__name__, e)
        )
        traceback.print_exc()
    return out


def _reference_population_damaged(rp):
    """Is this a spec whose reference-population record was lost? (True/False/None).

    None = the record predates `pack_readable` and carries neither marker, i.e. the build
    no longer knows. Kept separate from False on purpose: 'we checked and it was fine' and
    'we cannot tell' are different facts and only one of them is reassuring.
    """
    if not isinstance(rp, dict):
        return None
    if 'pack_unreadable' in rp:
        return True
    if rp.get('pack_readable') is True:
        return False
    return None if 'survey' not in rp else False


def _stylization(phen, explicit, intent=None, declared_by=None):
    """The BodyProportions record: the value, and whether anyone CHOSE it.

    `explicit` is tri-state on purpose. True = this build set the axis. False = the value
    came in with the inherited recipe and nobody decided it. None = the character was
    issued before this record existed and the build no longer knows — which is not the
    same as "defaulted" and must not be written down as if it were.
    """
    val = (phen or {}).get(STYLIZATION_AXIS)
    return {
        'axis': STYLIZATION_AXIS,
        'value': None if val is None else float(val),
        'explicitly_set': explicit,
        'intent': intent,
        'declared_by': declared_by,
        'date': time.strftime('%Y-%m-%d'),
        'axis_note': 'anny/MakeHuman BodyProportions macro (108 targets, '
        'idealproportions/uncommonproportions). The axis is a named '
        'parameter; this record says what it was set to and by whom, never '
        'that a value is correct.',
    }


def _character_spec(
    phen,
    sex,
    *,
    sex_source=None,
    ancestry=None,
    ancestry_source=None,
    build_target_m=None,
    build_target_source=None,
    stylization_explicit=None,
    stylization_intent=None,
    declared_by=None,
):
    """Everything the Tier-4 gates ask a character to DECLARE about itself.

    Nothing here is inferred from the geometry. Every field the pipeline does not
    genuinely know is null with a source string saying so, because an invented ancestry
    or an invented build target would make the gates answer a question nobody asked.
    """
    return {
        'schema': ANTHRO_SPEC_SCHEMA,
        'sex': sex,
        'sex_source': sex_source
        or 'declared by the build recipe (ORIGINAL_SPEC gender '
        'axis; in anny gender=0.0 is MALE and 1.0 is FEMALE, '
        'measured 2026-08-05, not assumed)',
        'ancestry': ancestry,
        'ancestry_source': ancestry_source
        or (
            'UNDECLARED — this pipeline carries no ancestry for its bodies. A '
            'single-population leg gate would be a bias, so the gates score against the '
            'pooled band and say so.'
        ),
        'reference_population': _reference_population(ancestry),
        'build_target_stature_mm': (None if build_target_m is None else round(float(build_target_m) * 1000.0, 3)),
        'build_target_source': build_target_source or ('UNDECLARED — no target stature was recorded for this build.'),
        'stature_claim': 'build_target',
        'stature_tolerance_mm': 2.0,
        'stature_tolerance_note': 'HOUSE: +/-2 mm is a question about the height SOLVER. '
        'It is not an anthropometric-accuracy claim — a real '
        'person varies 14.4-19.3 mm of stature over one day.',
        'stylization': _stylization(phen, stylization_explicit, stylization_intent, declared_by),
        'declared': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }


def _apply_spec(params, spec):
    """Write the declared spec into params.json, mirroring the fields geom.anthro reads.

    geom.anthro.gates.Subject.from_registry reads params['ancestry'], params['stylization']
    and params['height_target_m'] directly. The stylization mirror is written ONLY when
    the axis was explicitly set: a record that merely restates an inherited number would
    turn the gate's honest 'nobody chose this' into a pass, which is the exact laundering
    the record exists to prevent. The full tri-state stays in params['character_spec'].
    """
    params['character_spec'] = spec
    params['ancestry'] = spec.get('ancestry')
    if spec.get('build_target_stature_mm') is not None:
        params.setdefault('height_target_m', spec['build_target_stature_mm'] / 1000.0)
    st = spec.get('stylization') or {}
    if st.get('explicitly_set') is True:
        params['stylization'] = st
    else:
        params.pop('stylization', None)
    return params


def _anthro_spec(params):
    """params.json -> the gates.Subject spec dict."""
    from zyg_workflows.geom.anthro import measure as _ME

    cs = params.get('character_spec') or {}
    phen = params.get('phenotype') or {}
    sex = cs.get('sex') or params.get('sex') or ('female' if float(phen.get('gender', 0.0)) > 0.5 else 'male')
    spec = {
        'sex': sex,
        'sex_source': cs.get('sex_source') or 'inferred from the anny gender macro',
        'ancestry': cs.get('ancestry'),
        'age_years': (_ME._age_years(phen['age']) if 'age' in phen else None),
        'age_source': 'anny age macro %r via measure._age_years' % phen.get('age'),
        'build_target_stature_mm': cs.get('build_target_stature_mm'),
        'stature_claim': cs.get('stature_claim', 'build_target'),
        'stature_tolerance_mm': cs.get('stature_tolerance_mm', 2.0),
        'phenotype': phen,
        'local_changes': params.get('local_changes') or {},
        'anatomy_layer': params.get('anatomy_layer') or {},
        'topology_scope': 'full',
        'cage_vert_sha256': params.get('cage_vert_sha256'),
    }
    st = cs.get('stylization') or {}
    if st.get('explicitly_set') is True:
        spec['stylization'] = st
    return spec


def _ensure_repo_importable():
    """Make `geom.*` importable no matter how this module was entered.

    Run as `python3 -m zyg_workflows.geom.mesh_skeletons` the repo root is already on sys.path, but run
    as `python3 geom/mesh_skeletons.py` — which is how the CLI is invoked in practice —
    sys.path[0] is geom/ and `from geom.anthro import ...` raises ModuleNotFoundError.
    The gate's fail-safe caught that and issued every character as UNGATED, which is the
    correct behaviour for a broken tool and exactly why it must not be left broken.
    """
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if root not in sys.path:
        sys.path.insert(0, root)


# Gate-row triage for the compact summary. Deliberately written against report.py's
# CLASSES rather than its exact spellings, because the status vocabulary is allowed to
# grow (report.py may split 'error' out of 'unknown'); a status this module has never seen
# must land in the not-a-pass bucket, never in silence.
_ANTHRO_PASS = 'PASS'  # noqa: S105  gate status constant (report.PASS), not a secret
_ANTHRO_WARN = 'warn'
_ANTHRO_INFORMATIONAL = ('report',)  # measured and printed, never gated
# Statuses report.py is KNOWN to emit as of 2026-08-05. 'error' = the gate itself raised;
# 'missing' = the declaration it needed was never made; 'unknown' = the status could not
# be read. All three are triaged above; this tuple exists only so that a status added to
# report.py LATER shows up in summary['unaccounted'] instead of being absorbed silently.
_ANTHRO_KNOWN_STATUSES = (_ANTHRO_PASS, 'fail', _ANTHRO_WARN, 'skip', 'report', 'missing', 'unknown', 'error')
# Severity words report.py classes as LOW, i.e. a gate that is not allowed to block. Used
# only as a fallback for reports written before 'severity_class' existed; an unrecognised
# severity is treated as blocking, exactly as report.py does.
_ANTHRO_LOW_SEVERITIES = (
    'minor',
    'advisory',
    'info',
    'informational',
    'note',
    'cosmetic',
    'low',
    'warn',
    'warning',
    'report',
)


def _anthro_row_blocks(row):
    """Is this gate allowed to block? 'unrecognised' severity counts as blocking."""
    cls = row.get('severity_class')
    if cls:
        return cls != 'low'
    sev = str(row.get('severity') or '').strip().lower()
    return sev not in _ANTHRO_LOW_SEVERITIES


def _anthro_buckets(gates):
    """Split the gate rows into the buckets the compact summary reports.

    THE DEFECT THIS CLOSES (2026-08-05): the summary collected exactly two statuses —
    effective_status=='fail' into `blocking` and =='warn' into `warnings` — so a BLOCKING
    gate that never ran was in neither, and every surface built on this dict (the CLI
    line, params.json, registry.json, the Mesh-tab chip) said '0 blocking'. cornelis
    shipped with t1_build_target_stature and t2_vhi_bmi at status 'missing', both declared
    severity 'block': the delivered stature was checked against nothing, and the card read
    'PASS +WARN — 0 blocking'.

    The rule now is the one report.py already states: a check that did not run is never a
    pass. `blocking` therefore means "blocking gates that are NOT satisfied", failed or
    unrun, so the existing renderers stop under-reporting without needing to change; the
    two are also kept apart in `blocking_failed` / `blocking_unrun` so a caller that wants
    to distinguish "measured and outside the band" from "never measured" still can.

    `unaccounted` closes the arithmetic: every row lands in exactly one bucket, and a
    status this module has never seen is reported by name rather than dropped.
    """
    out = {
        'passed': [],
        'warnings': [],
        'informational': [],
        'skipped': [],
        'blocking_failed': [],
        'blocking_unrun': [],
        'unaccounted': [],
    }
    for g in gates or []:
        gid = g.get('id')
        st = g.get('effective_status')
        blocks = _anthro_row_blocks(g)
        if g.get('escalated_unrun_blocking_gate'):
            # report.py's own name for it: a BLOCKING gate whose status was 'skip' (or
            # another non-verdict), lifted to 'warn' so it cannot read as a pass. It is
            # named in report.py's "BLOCKING GATES THAT DID NOT RUN" header, so it has to
            # be in the same bucket here or the two surfaces disagree about the same row.
            out['blocking_unrun'].append(
                {
                    'id': gid,
                    'status': g.get('status'),
                    'status_raw': g.get('status_raw'),
                    'effective_status': st,
                    'escalated': True,
                    'severity': g.get('severity'),
                    'severity_class': g.get('severity_class'),
                    'why': (g.get('explanation') or g.get('severity_reason') or '')[:300],
                }
            )
        elif st == _ANTHRO_PASS:
            out['passed'].append(gid)
        elif st == 'fail':
            # a 'fail' on a low-severity gate is already downgraded to 'warn' by
            # report.py, so anything still reading 'fail' here is a blocking failure
            (out['blocking_failed'] if blocks else out['warnings']).append(gid)
        elif st == _ANTHRO_WARN:
            out['warnings'].append(gid)
        elif st in _ANTHRO_INFORMATIONAL:
            out['informational'].append(gid)
        elif not blocks:
            # skip / missing / unknown on a gate that was never allowed to block
            out['skipped'].append(gid)
        else:
            # missing, unknown, error, skip-that-escaped-escalation, or any status added
            # to report.py after this was written: a BLOCKING check with no verdict
            out['blocking_unrun'].append(
                {
                    'id': gid,
                    'status': st,
                    'status_raw': g.get('status_raw'),
                    'effective_status': st,
                    'escalated': False,
                    'severity': g.get('severity'),
                    'severity_class': g.get('severity_class'),
                    'why': (g.get('explanation') or g.get('severity_reason') or '')[:300],
                }
            )
        if st not in _ANTHRO_KNOWN_STATUSES:
            out['unaccounted'].append({'id': gid, 'effective_status': st})
    return out


def _anthro_run(name, v, faces, params, d):
    """Run the four-tier gate engine on one body and write its report next to the mesh.

    strict=False so that one crashing gate is recorded as an ERROR row (blocking, for a
    blocking gate) instead of destroying the other 33 results. The caller still wraps
    this: a failure to gate must never stop a character being issued.
    """
    _ensure_repo_importable()
    from zyg_workflows.geom.anthro import report as ARP
    from zyg_workflows.geom.anthro.gates.engine import run_gates
    from zyg_workflows.geom.anthro.gates.subject import Subject

    spec = _anthro_spec(params)
    sub = Subject.from_mesh(np.asarray(v, np.float64), faces, spec, name)
    gr = run_gates(sub, strict=False)
    doc = ARP.build(
        gr,
        sub.measurements,
        name=name,
        sex=spec['sex'],
        ancestry=spec.get('ancestry'),
        age_years=spec.get('age_years'),
        extra={
            'gates_entrypoint': 'geom.anthro.gates.run_gates',
            'issued_by': 'geom.mesh_skeletons',
            'kind': params.get('kind'),
            'cage_vert_sha256': params.get('cage_vert_sha256'),
        },
    )
    path = os.path.join(d, ANTHRO_REPORT_FILE)
    ARP.write_json(doc, path)
    # Same status keys report.py counts with — 'PASS' is its constant, and inventing a
    # lowercase 'pass' beside it would produce a tier row whose numbers do not add up.
    tiers = {}
    for row in doc.get('gates') or []:
        t = tiers.setdefault(
            'tier%s' % row.get('tier'),
            {'PASS': 0, 'warn': 0, 'fail': 0, 'skip': 0, 'report': 0, 'missing': 0, 'unknown': 0},
        )
        k = row.get('effective_status', 'unknown')
        t[k] = t.get(k, 0) + 1
    rs = doc.get('ratio_summary') or {}
    b = _anthro_buckets(doc.get('gates'))
    unrun = b['blocking_unrun']
    rp = (params.get('character_spec') or {}).get('reference_population')
    return {
        'status': 'ok',
        'verdict': doc.get('verdict'),
        'exit_code': doc.get('exit_code'),
        'counts': doc.get('counts'),
        'tiers': tiers,
        'n_gates': doc.get('n_gates'),
        # `blocking` = blocking gates that are NOT satisfied. A gate that crashed, was
        # never declared to, or otherwise produced no verdict is not a pass, so it is
        # counted here as well as listed separately below. Fail-first ordering so the
        # measured failures stay at the front of any truncated display.
        'blocking': b['blocking_failed'] + [u['id'] for u in unrun],
        'blocking_failed': b['blocking_failed'],
        'blocking_unrun': unrun,
        'blocking_unrun_ids': [u['id'] for u in unrun],
        'warnings': b['warnings'],
        'informational': b['informational'],
        'not_run_non_blocking': b['skipped'],
        # every row lands in exactly one bucket; a non-empty list here means report.py
        # emitted a status this module does not know about, which is itself the alarm
        'unaccounted': b['unaccounted'],
        'buckets_total': (
            len(b['passed'])
            + len(b['warnings'])
            + len(b['informational'])
            + len(b['skipped'])
            + len(b['blocking_failed'])
            + len(unrun)
        ),
        'reference_population': rp,
        'reference_population_damaged': _reference_population_damaged(rp),
        'ratios': {
            'n': rs.get('n'),
            'banded': rs.get('n_banded'),
            'outside': rs.get('n_outside'),
            'no_band': rs.get('n_no_band'),
        },
        'ancestry': doc.get('ancestry'),
        'ancestry_declared': bool(doc.get('ancestry_declared')),
        'age_years': doc.get('age_years'),
        'age_outside_reference_population': doc.get('age_outside_reference_population'),
        'alarms': [a.get('kind') for a in doc.get('policy_alarms') or []],
        'engine': gr.get('schema'),
        'report_schema': doc.get('schema'),
        'stable_sha256': doc.get('stable_sha256'),
        'summary_line': ARP.render_summary(doc),
        'report': os.path.relpath(path, ROOT),
        'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'elapsed_s': gr.get('elapsed_s'),
    }, doc


def _anthro_gate(name, v, faces, params, d):
    """FAIL-SAFE wrapper. Returns the compact summary; never raises.

    A gate-engine exception is loud (full traceback to stdout) and recorded as
    status 'gate-error' — an unmeasured body is issued as UNMEASURED, never as passed.
    """
    if not _anthro_enabled():
        return {
            'status': 'disabled',
            'reason': 'ZYG_ANTHRO_GATES=%r' % os.environ.get('ZYG_ANTHRO_GATES'),
            'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }, None
    t0 = time.time()
    try:
        summary, doc = _anthro_run(name, v, faces, params, d)
    except Exception as e:  # noqa: BLE001
        _zyg_log.info(
            '  ANTHRO GATE FAILED for %s: %s: %s — the character is still issued and '
            'is recorded as UNGATED (status gate-error), not as passed' % (name, type(e).__name__, e)
        )
        traceback.print_exc()
        return {
            'status': 'gate-error',
            'error': '%s: %s' % (type(e).__name__, e),
            'traceback': traceback.format_exc()[-2000:],
            'elapsed_s': round(time.time() - t0, 3),
            'generated': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }, None
    unrun = summary.get('blocking_unrun') or []
    _zyg_log.info(
        '  anthro gate %s: %s (%d blocking%s, %d warnings, %d/%d ratios outside band, '
        '%.1fs)'
        % (
            name,
            summary['verdict'],
            len(summary['blocking']),
            (' — %d FAILED, %d NEVER RAN' % (len(summary['blocking_failed']), len(unrun)) if unrun else ''),
            len(summary['warnings']),
            summary['ratios']['outside'] or 0,
            summary['ratios']['n'] or 0,
            time.time() - t0,
        )
    )
    # A blocking gate with no verdict is the one thing an operator must not scroll past:
    # it means the body is UNCHECKED on that axis, not that it is fine.
    for u in unrun:
        _zyg_log.info(
            '    BLOCKING GATE DID NOT RUN: %s [%s, severity %s] — %s'
            % (u['id'], u['status'], u.get('severity'), u.get('why') or 'no reason given')
        )
    for u in summary.get('unaccounted') or []:
        _zyg_log.info(
            '    UNRECOGNISED GATE STATUS %r on %s — report.py emitted a status this '
            'summary does not know how to classify; it is NOT counted as a pass'
            % (u.get('effective_status'), u.get('id'))
        )
    if summary.get('reference_population_damaged'):
        _zyg_log.info(
            '    reference-population provenance is DAMAGED on this body '
            '(see character_spec.reference_population.pack_unreadable)'
        )
    return summary, doc


def _rebuild_from_params(p, name):
    """Rebuild a registered body from its recipe and refuse to gate a different one.

    Same rule as gates.Subject.from_registry: the .glb is triangulated and the gates want
    the quad cage, so the cage is rebuilt — and if the rebuild no longer hashes to what
    shipped, that is a library drift and the report would describe some other body.
    """
    v, faces, _ = _build_mesh(p['phenotype'], p.get('local_changes') or None, p.get('bone_scales') or None, params=p)
    v = _apply_anatomy(
        v,
        faces,
        p.get('anatomy_layer'),
        phenotype=p['phenotype'],
        local_changes=p.get('local_changes') or None,
        bone_scales=p.get('bone_scales') or None,
        params=p,
    )
    want = p.get('cage_vert_sha256')
    if want and _vert_sha(v) != want:
        from zyg_workflows.geom.anthro import hand_correction as HC

        rec = p.get('hand_correction') or {}
        # A hash mismatch used to mean exactly one thing — library drift. Since
        # 2026-08-08 it can also mean the body was ISSUED BEFORE the phalanx correction
        # and the process now applies one, which is a deliberate geometry change and not
        # drift. Naming both possibilities is the difference between an operator
        # re-deriving and an operator hunting a version skew that is not there.
        stale = (
            ''
            if rec.get('version') == HC.HAND_CORRECTION_VERSION
            else ' This body records hand_correction version %s and the process is at '
            'version %d, so it may simply predate the phalanx correction — '
            're-derive it to pick the correction up, or set %s=0 to reproduce the '
            'body exactly as issued.' % (rec.get('version', 'none'), HC.HAND_CORRECTION_VERSION, HC.ENV_FLAG)
        )
        raise RuntimeError(
            'rebuilt cage for %r hashes %s but the registry recorded %s — '
            'the recipe no longer reproduces the issued mesh.%s' % (name, _vert_sha(v)[:16], want[:16], stale)
        )
    return v, faces


def _backfill_spec(p, name):
    """A character_spec for a body issued before the spec existed.

    Everything unknown stays unknown. In particular stylization.explicitly_set is None,
    not False: params.json records the MERGED recipe, so there is no way to tell after
    the fact whether the proportions value was chosen for this character or inherited
    from the base, and guessing would make the Tier-4 gate answer a question it was
    never asked.
    """
    if p.get('kind') == 'ORIGINAL':
        return _character_spec(
            p.get('phenotype') or {},
            p.get('sex'),
            build_target_m=p.get('height_target_m'),
            build_target_source='TARGET_HEIGHT_M, operator-specified at issue and solved for by _calibrate_height',
            stylization_explicit=True,
            stylization_intent=ORIGINAL_STYLIZATION_INTENT,
            declared_by='geom.mesh_skeletons ORIGINAL_PHEN',
        )
    phen = p.get('phenotype') or {}
    sex = 'female' if float(phen.get('gender', 0.0)) > 0.5 else 'male'
    spec = _character_spec(
        phen,
        sex,
        sex_source='INFERRED from the anny gender macro (%.3f); params.json for a '
        'DERIVED character issued before the spec block records no sex field' % float(phen.get('gender', 0.0)),
        build_target_m=p.get('height_target_m'),
        build_target_source='UNDECLARED — %r was derived before derive() recorded a '
        'build target; params.json stores only the ACHIEVED height. '
        'The note field says "%s", which is prose, not a declaration.' % (name, (p.get('note') or '')[:60]),
        stylization_explicit=None,
        stylization_intent='NOT RECORDED — issued before the stylization record existed; '
        'the merged recipe cannot say whether this value was chosen '
        'or inherited from the base original.',
        declared_by=None,
    )
    return spec
