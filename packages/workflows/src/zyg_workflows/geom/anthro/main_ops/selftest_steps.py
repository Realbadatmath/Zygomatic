# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The numbered steps of the ``geom.anthro selftest`` command, one function per step.

Extracted verbatim from ``cmd_selftest`` in :mod:`.selftest`, which keeps the step
banners, the ``check`` reporter and the gate-absent fallback and calls the steps below
in the original order with the original side effects.

Every step takes ``check(label, cond, detail='')`` as its first argument — the reporter
the command owns — and prints nothing itself: ``scripts/ratchet.py`` exempts
``**/selftest.py`` from the ``print_calls`` metric by file name but not this module, so
all output stays in the command's own file.
"""

import os

from zyg_workflows.geom.anthro import report as RPT

from zyg_workflows.geom.anthro.main_ops.constants import EXIT_ERROR, EXIT_FAIL, EXIT_OK, EXIT_WARN
from zyg_workflows.geom.anthro.main_ops.characters import _measure, _resolve
from zyg_workflows.geom.anthro.main_ops.roster import (
    GATED,
    GATED_UNWRITTEN,
    OutSpecError,
    SKIPPED,
    _STALE_STATUS,
    _render_roster,
    _resolve_out_paths,
    _roster_exit_code,
    _stale_report_doc,
    _stale_summary,
    _unwritten_notes,
)


def reference_pack(check):
    """Step 2: load the reference pack and check a band carries its provenance.

    Returns the loaded reference object for the later percentile step.
    """
    from zyg_workflows.geom.anthro.reference import reference

    ref = reference()
    check('pack loads', len(ref.ratios()) > 0, '%d ratios' % len(ref.ratios()))
    check(
        'mahalanobis vector present',
        len(ref.doc['mahalanobis']['order']) >= 2,
        '%d components' % len(ref.doc['mahalanobis']['order']),
    )
    b = ref.band('crotch_height_over_stature', 'male')
    check(
        'a band carries source+population+n',
        bool(b['source']) and bool(b['population']) and b['n'] > 0,
        'n=%d' % b['n'],
    )
    check('an undeclared ancestry is flagged', b['ancestry_declared'] is False)
    return ref


def measure_character(check, name):
    """Step 3: build and measure one character's mesh.

    Returns ``(rec, measurement, v, f, meta)`` — the roster record, the measurement
    document, its vertices and faces, and ``measurement['meta']``.
    """
    rec = _resolve(name)
    measurement, v, f = _measure(rec)
    meta = measurement['meta']
    check(
        'mesh built and measured',
        len(measurement['measurements']) > 0,
        '%d measurements, %d ratios, stature %.4f m'
        % (len(measurement['measurements']), len(measurement['ratios']), meta['stature_m']),
    )
    check(
        'measurements carry a convention',
        all(isinstance(r, dict) and 'convention' in r for r in measurement['measurements'].values()),
    )
    check(
        'measurements carry a provenance class', all(r.get('provenance') for r in measurement['measurements'].values())
    )
    return rec, measurement, v, f, meta


def percentile_strip(check, measurement, rec, meta, ref):
    """Step 4: build a percentile row per measured ratio and render the strip."""
    rows = RPT.ratio_rows(measurement['ratios'], rec['sex'], None, stature_m=meta['stature_m'], ref=ref)
    banded = [r for r in rows if r.get('percentile') is not None]
    check(
        'rows built for every measured ratio',
        len(rows) == len(measurement['ratios']),
        '%d rows, %d with a band' % (len(rows), len(banded)),
    )
    check(
        'every banded row has a value, a percentile and a band',
        all(
            r['value'] is not None
            and r['percentile'] is not None
            and r['band_lo'] is not None
            and r['band_hi'] is not None
            for r in banded
        ),
    )
    check('percentiles are inside 0..100', all(0.0 <= r['percentile'] <= 100.0 for r in banded))
    check(
        'stature-relative deltas are converted to mm',
        all(r.get('delta_mm_of_stature') is not None for r in banded if r['ratio'].endswith('_over_stature')),
    )
    strip = RPT.render_percentile_strip(rows)
    check(
        'strip renders',
        'PERCENTILE STRIP' in strip and len(strip.splitlines()) > 4,
        '%d lines' % len(strip.splitlines()),
    )


def report_assembly(check, gate_report, measurement, name, rec, age):
    """Step 6: assemble the report document and check its verdict/exit-code invariants.

    Returns the assembled document.
    """
    doc = RPT.build(gate_report, measurement, name=name, sex=rec['sex'], ancestry=None, age_years=age)
    check(
        'age recorded',
        doc['age_years'] is not None,
        '%.1f y, outside the reference population: %s' % (doc['age_years'], doc['age_outside_reference_population']),
    )
    if age is not None and not (17 <= age <= 58):
        check(
            'a subject outside the reference age range is alarmed on',
            doc['age_outside_reference_population']
            and any(x['kind'] == 'age_outside_reference_population' for x in doc['policy_alarms']),
        )
    check('verdict is one of the four', doc['verdict'] in RPT.EXIT_CODES, doc['verdict'])
    check(
        'exit code matches the verdict',
        doc['exit_code'] == RPT.EXIT_CODES[doc['verdict']] == RPT.exit_code(doc),
        'exit %d' % doc['exit_code'],
    )
    check(
        'gate count agrees with the counts block',
        doc['n_gates'] == sum(doc['counts'].values()),
        '%d gates' % doc['n_gates'],
    )
    check('measurement conventions carried into the report', bool(doc['measurement_meta'].get('girth_convention')))
    check('every gate has a provenance class', all(g['provenance_class'] in RPT._PROV_CLASSES for g in doc['gates']))
    return doc


def tier5_canon_policy(check, doc, gate_report, measurement, name, rec, age):
    """Step 6b: tier 5 and the CANON policy — only meaningful against real gates.

    Four properties, each of which has already gone wrong once somewhere in this stack:
    a registered gate that never ran, a CANON threshold outranking a survey, a crashed
    blocking gate rendering as a warning, and a tier that exists in the registry but
    never reaches the artefact.
    """
    import importlib

    G = importlib.import_module('zyg_workflows.geom.anthro.gates')
    registered = [g.id for g in G.GATES]
    rendered = {g['id'] for g in doc['gates']}
    never_ran = [gid for gid in registered if gid not in rendered]
    check('every REGISTERED gate reached the report', not never_ran, 'missing: %s' % (', '.join(never_ran) or 'none'))
    t5 = [g for g in G.GATES if g.tier == 5]
    check(
        'tier 5 is registered and rendered',
        bool(t5) and all(g.id in rendered for g in t5),
        '%d tier-5 gates' % len(t5),
    )
    cal = G.calibrate()
    canon_bad = [
        g.id
        for g in G.GATES
        if g.provenance == G.CANON and cal[g.id]['severity_effective'] == 'block' and g.measured_conflict()
    ]
    check(
        'no CANON threshold blocks a quantity a survey already answers',
        not canon_bad,
        'offenders: %s' % (', '.join(canon_bad) or 'none'),
    )
    canon_mute = [g.id for g in G.GATES if g.provenance == G.CANON and g.quantities is None]
    check(
        'every CANON gate declares what quantity it measures',
        not canon_mute,
        'silent: %s' % (', '.join(canon_mute) or 'none'),
    )
    blocking_t5 = next((g['id'] for g in doc['gates'] if str(g['tier']) == '5' and g['severity_class'] == 'high'), None)
    if not blocking_t5:
        check('a tier-5 gate carries blocking severity', False, 'none found — the crash test could not run')
        return
    _crashed_blocking_gate(check, blocking_t5, gate_report, measurement, name, rec, age)
    low_t5 = next((g['id'] for g in doc['gates'] if str(g['tier']) == '5' and g['severity_class'] == 'low'), None)
    if low_t5:
        _crashed_low_gate(check, low_t5, gate_report, measurement, name, rec, age)


def _crashed_blocking_gate(check, blocking_t5, gate_report, measurement, name, rec, age):
    """A CRASH on a tier-5 blocking gate must FAIL the body, not warn it.

    Proven by substituting an error row for a real one rather than by reading the code:
    this renderer mapped 'error' to 'unknown' once, and a crashed blocking gate shipped
    as PASS-WITH-WARNINGS.
    """
    import copy

    hurt = copy.deepcopy(gate_report)
    for row in hurt.get('gates', []):
        if row.get('id') == blocking_t5:
            row['status'] = 'error'
            # W4-1: `crashed` is an explicit boolean the ENGINE sets, and the
            # renderer reads it instead of inferring "it raised" from the status —
            # because the error bucket now also holds gates whose verdict the
            # engine refused, which RAN. A synthetic crash has to declare itself a
            # crash, exactly as run_gates does for a real one.
            row['crashed'] = True
            row['explain'] = 'synthetic crash injected by selftest'
    hdoc = RPT.build(hurt, measurement, name=name, sex=rec['sex'], ancestry=None, age_years=age)
    hrow = next(g for g in hdoc['gates'] if g['id'] == blocking_t5)
    # The verdict alone is not enough evidence here: this body may already be
    # failing for other reasons. The ROW has to be a blocking failure in its own
    # right, in its own bucket, and named in doc['blocking'].
    check(
        'a CRASHED tier-5 blocking gate fails the body (not a warning)',
        hdoc['verdict'] == RPT.FAIL
        and hdoc['exit_code'] == 2
        and hrow['status'] == 'error'
        and hrow['crashed']
        and hrow['is_blocking_failure']
        and blocking_t5 in (hdoc.get('blocking') or []),
        '%s -> status=%s blocking_failure=%s listed=%s verdict=%s exit=%d'
        % (
            blocking_t5,
            hrow['status'],
            hrow['is_blocking_failure'],
            blocking_t5 in (hdoc.get('blocking') or []),
            hdoc['verdict'],
            hdoc['exit_code'],
        ),
    )


def _crashed_low_gate(check, low_t5, gate_report, measurement, name, rec, age):
    """A crash on a report-severity tier-5 gate keeps the error bucket.

    It must not be silently swallowed either: it counts as something other than a pass.
    """
    import copy

    soft = copy.deepcopy(gate_report)
    for row in soft.get('gates', []):
        if row.get('id') == low_t5:
            row['status'] = 'error'
    sdoc = RPT.build(soft, measurement, name=name, sex=rec['sex'], ancestry=None, age_years=age)
    srow = next(g for g in sdoc['gates'] if g['id'] == low_t5)
    check(
        'a CRASHED low-severity tier-5 gate is an error, never a pass',
        srow['status'] == 'error'
        and srow['effective_status'] == 'error'
        and not srow['is_blocking_failure']
        and sdoc['counts'].get('error', 0) >= 1,
        '%s -> %s, counted in the error bucket (%d)' % (low_t5, srow['status'], sdoc['counts'].get('error', 0)),
    )


def artifact_roundtrip(check, out, name, doc, gate_report, measurement, rec, age):
    """Step 7: write the report, read it back, check the digest and the temp hygiene.

    The artefact is unlinked again before returning.
    """
    path = os.path.join(out or RPT.ROOT, '_selftest_%s.json' % name)
    written = RPT.write_json(doc, path)
    back = RPT.read_json(written)
    check('json round-trips', back['stable_sha256'] == doc['stable_sha256'], doc['stable_sha256'][:12])
    check(
        'digest excludes the clock',
        RPT.stable_sha(RPT.build(gate_report, measurement, name=name, sex=rec['sex'], ancestry=None, age_years=age))
        == doc['stable_sha256'],
    )
    check(
        'no temp file left behind',
        not any(x.startswith(os.path.basename(path) + '.tmp') for x in os.listdir(os.path.dirname(written))),
    )
    os.unlink(written)


def failure_roster(check):
    """Step 8, first half: the roster exit code and the roster rendering.

    Both halves of the 2026-08-06 fix, exercised as pure functions so they run on any
    host: the exit code must be the worst outcome over the WHOLE roster, and a body that
    could not be gated must not be left carrying a verdict.
    """
    r_pass = {'name': 'rp-a', 'outcome': GATED, 'verdict': RPT.PASS, 'exit_code': EXIT_OK}
    r_warn = {'name': 'rp-b', 'outcome': GATED, 'verdict': RPT.WARN, 'exit_code': EXIT_WARN}
    r_fail = {'name': 'rp-c', 'outcome': GATED, 'verdict': RPT.FAIL, 'exit_code': EXIT_FAIL}
    r_skip = {
        'name': 'rp-skipped',
        'section': 'derived',
        'outcome': SKIPPED,
        'verdict': None,
        'exit_code': EXIT_ERROR,
        'reason': 'cage hash mismatch',
        'invalidation': {},
    }
    check('all-pass roster exits 0', _roster_exit_code([r_pass, r_pass]) == EXIT_OK)
    check('a warn among passes exits 1', _roster_exit_code([r_pass, r_warn]) == EXIT_WARN)
    check('a fail outranks a warn', _roster_exit_code([r_pass, r_warn, r_fail]) == EXIT_FAIL)
    check(
        'ONE un-gateable body makes the whole run exit 3',
        _roster_exit_code([r_pass, r_pass, r_skip]) == EXIT_ERROR,
        'this is F7: 2 of 3 covered must not exit like 3 of 3',
    )
    check('an empty roster is an internal error, never a pass', _roster_exit_code([]) == EXIT_ERROR)
    check(
        'a roster entry with no exit code is an internal error, never a pass',
        _roster_exit_code([{'name': 'x', 'outcome': GATED}]) == EXIT_ERROR,
    )
    txt_roster = _render_roster([r_pass, r_skip], width=100)
    check(
        'the roster names every skipped character and its reason',
        'SKIPPED' in txt_roster
        and 'rp-skipped' in txt_roster
        and 'cage hash mismatch' in txt_roster
        and 'NOT GATED' in txt_roster,
    )
    _unwritten_roster(check, r_skip)


def _unwritten_roster(check, r_skip):
    """N4: --out resolution, and "gated then not written" vs "never gated"."""
    r_unw = {
        'name': 'rp-unwritten',
        'section': 'derived',
        'outcome': GATED_UNWRITTEN,
        'verdict': RPT.FAIL,
        'exit_code': EXIT_ERROR,
        'gate_exit_code': EXIT_FAIL,
        'reason': "IsADirectoryError: [Errno 21] Is a directory: '/tmp/d'",
        'notes': ['the stored record was deliberately NOT superseded'],
    }
    txt_unw = _render_roster([r_unw], width=100)
    check(
        'a body gated-then-not-written is NOT reported as never gated',
        '1 gated (1 of them with NO ARTIFACT WRITTEN), 0 SKIPPED' in txt_unw
        and 'UNWRITTEN' in txt_unw
        and 'THIS BODY WAS GATED' in txt_unw
        and 'NOT GATED' not in txt_unw,
        txt_unw.splitlines()[1],
    )
    check(
        'an unwritten report still exits 3 and keeps its verdict word',
        _roster_exit_code([r_unw]) == EXIT_ERROR and RPT.FAIL in txt_unw and 'NOT SAVED' in txt_unw,
    )
    check(
        'the skipped wording survives beside the unwritten wording',
        'never gated' in _render_roster([r_skip], width=100)
        and 'were NOT gated and nothing in this run says anything about them' in _render_roster([r_skip], width=100),
    )
    _txt_unk = _render_roster(
        [{'name': 'rp-weird', 'section': 'derived', 'outcome': 'something_new', 'exit_code': EXIT_ERROR}], width=100
    )
    check(
        'an outcome word the renderer does not know is named, not called NOT GATED',
        'UNRECOGNISED OUTCOME' in _txt_unk
        and 'NOT GATED' not in _txt_unk
        and '0 gated' in _txt_unk
        and '0 SKIPPED' in _txt_unk,
    )


def out_spec_and_supersession(check, out, name):
    """Step 8, second half: --out resolution, unwritten notes and the stale supersession.

    ``out`` is the command's ``--out`` value (None for the default store) and ``name``
    the character the scratch files are named after; every file written is unlinked.
    """
    tmpd = out or RPT.ROOT
    _out_spec_checks(check, tmpd, name)
    _unwritten_note_checks(check, tmpd, name)
    _stale_summary_checks(check)
    _stale_doc_checks(check, out, name)


def _out_spec_checks(check, tmpd, name):
    """N4: a --out directory gives one file per character; a shared FILE is refused."""
    _op = _resolve_out_paths
    check(
        '--out DIR gives one file per character, for ONE character',
        _op(tmpd, ['abel']) == {'abel': RPT.report_path('abel', tmpd)},
        'this is N4: a directory used to raise IsADirectoryError after every gate ran',
    )
    check(
        '--out DIR gives one file per character, for ALL',
        _op(tmpd, ['abel', 'male']) == {'abel': RPT.report_path('abel', tmpd), 'male': RPT.report_path('male', tmpd)},
    )
    check(
        'a path with a trailing separator is a directory even if it does not exist',
        _op(os.path.join(tmpd, '_selftest_nodir') + os.sep, ['abel'])
        == {'abel': RPT.report_path('abel', os.path.join(tmpd, '_selftest_nodir') + os.sep)},
    )
    _f = os.path.join(tmpd, '_selftest_out_%s.json' % name)
    check('--out FILE for one character is that exact file', _op(_f, ['abel']) == {'abel': _f})
    with open(_f, 'w') as _fh:
        _fh.write('{}\n')
    try:
        _refused = False
        try:
            _op(_f, ['abel', 'male'])
        except OutSpecError:
            _refused = True
        check(
            'several characters into one existing FILE is refused, not attempted',
            _refused,
            'and it is refused before any body is measured',
        )
    finally:
        os.unlink(_f)
    check('no --out is the default store', _op(None, ['abel']) == {'abel': RPT.report_path('abel', RPT.ROOT)})


def _unwritten_note_checks(check, tmpd, name):
    """An unwritten FAIL must say so, whether the record on disk says PASS or is absent."""
    _doc_fail = {'verdict': RPT.FAIL, 'exit_code': EXIT_FAIL}
    _prev = os.path.join(tmpd, '_selftest_prev_%s.json' % name)
    RPT.write_json(
        {
            'schema': RPT.SCHEMA,
            'character': 'x',
            'verdict': RPT.PASS,
            'exit_code': EXIT_OK,
            'gates': [],
            'counts': {},
            'n_gates': 0,
            'volatile': {'generated': '2026-08-05T23:12:14'},
        },
        _prev,
    )
    _notes = _unwritten_notes('x', _doc_fail, _prev, 'OSError: disk full')
    check(
        'an unwritten FAIL says so when the record on disk still says PASS',
        any('MORE FAVOURABLE' in n for n in _notes) and any('deliberately NOT superseded' in n for n in _notes),
        '; '.join(n[:60] for n in _notes),
    )
    os.unlink(_prev)
    _notes2 = _unwritten_notes('x', _doc_fail, os.path.join(tmpd, '_selftest_absent.json'), 'OSError: disk full')
    check(
        'an unwritten report with nothing on disk says no reader can get a verdict',
        any('no reader can obtain a verdict' in n for n in _notes2),
    )


def _stale_summary_checks(check):
    """A superseded run summary carries the reason and the demoted record, never a verdict."""
    was = {
        'status': 'ok',
        'verdict': RPT.WARN,
        'generated': '2026-08-05T23:12:14',
        'report': 'derived/x/anthro_report.json',
        'blocking': [],
        'warnings': ['w1'],
    }
    st = _stale_summary(
        was,
        name='x',
        reason='cage hash mismatch',
        by='selftest',
        now='2026-08-06T00:00:00',
        stale_artifacts=['derived/x/params.json'],
        repair='gate x',
    )
    check(
        'a superseded summary carries NO verdict word at all',
        'verdict' not in st and st.get('status') == _STALE_STATUS,
        'status=%r' % st.get('status'),
    )
    check(
        'the superseded summary states the reason and the timestamp',
        st['stale'] is True
        and st['stale_reason'] == 'cage hash mismatch'
        and st['invalidated_at'] == '2026-08-06T00:00:00',
    )
    check(
        'the previous record is demoted verbatim, not deleted',
        st['superseded_summary'] == was and st['superseded_verdict'] == RPT.WARN,
    )
    # The consumers all reach for a verdict. report.exit_code() is the one that answers in
    # the contract's own vocabulary, and with no verdict key it answers 3, not 0.
    check(
        'a consumer asking the superseded record for a verdict gets exit 3',
        RPT.exit_code(st) == EXIT_ERROR and RPT.verdict(st) == RPT.ERROR,
    )
    check(
        'the one-line summary announces the supersession rather than a verdict',
        'SUPERSEDED' in st['summary_line']
        and 'verdict=NONE' in st['summary_line']
        and 'was=%s' % RPT.WARN in st['summary_line'],
    )
    st2 = _stale_summary(st, name='x', reason='still mismatched', by='selftest', now='2026-08-07T00:00:00')
    check(
        'superseding a supersession does not nest or lose the original',
        st2['superseded_summary'] == was
        and st2['first_invalidated_at'] == '2026-08-06T00:00:00'
        and st2['invalidated_at'] == '2026-08-07T00:00:00',
    )


def _stale_doc_checks(check, out, name):
    """A superseded report artifact still parses, answers exit 3 and keeps its digest."""
    sd = _stale_report_doc(
        {
            'verdict': RPT.WARN,
            'exit_code': 1,
            'n_gates': 60,
            'generated': '2026-08-05T23:12:14',
            'stable_sha256': 'abc',
        },
        name='x',
        reason='cage hash mismatch',
        by='selftest',
        now='2026-08-06T00:00:00',
    )
    check(
        'the superseded artifact still parses and answers exit 3',
        RPT.exit_code(sd) == EXIT_ERROR
        and sd['verdict'] == RPT.ERROR
        and sd['stale'] is True
        and sd['superseded']['verdict'] == RPT.WARN,
    )
    sd2 = _stale_report_doc(sd, name='x', reason='cage hash mismatch', by='selftest', now='2026-08-09T00:00:00')
    check(
        're-superseding keeps the original, the first date, and the digest',
        sd2['superseded']['verdict'] == RPT.WARN
        and sd2['first_invalidated_at'] == '2026-08-06T00:00:00'
        and sd2['stable_sha256'] == sd['stable_sha256'],
        'digest %s' % sd2['stable_sha256'][:12],
    )
    spath = os.path.join(out or RPT.ROOT, '_selftest_stale_%s.json' % name)
    swritten = RPT.write_json(sd, spath)
    check('the superseded artifact round-trips through read_json', RPT.read_json(swritten)['verdict'] == RPT.ERROR)
    os.unlink(swritten)
