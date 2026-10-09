# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — the roster, the supersession of a stale summary, and --out resolution.

Moved verbatim from geom/anthro/__main__.py (lines 363-875) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""

import os
import time
from zyg_workflows.geom.anthro import report as RPT

from zyg_workflows.geom.anthro.main_ops.constants import EXIT_ERROR, EXIT_FAIL, EXIT_OK, EXIT_WARN

# ---------------------------------------------------------------------------------
# the roster, and the supersession of a summary that is no longer about this body
# ---------------------------------------------------------------------------------
GATED = 'gated'
SKIPPED = 'skipped'
# N4. The third outcome, and the reason it has to exist: "gated, then the artifact could
# not be written" is NOT "never gated". The gates ran, the verdict is known and was
# printed, and only the file is missing. Folding it into SKIPPED made the roster print
# `0 gated, 1 SKIPPED (never gated)` about a run that had just gated a body and printed
# sixty rows about it — a false statement in the one line an operator reads to find out
# what the run covered. The exit code is unchanged (3, fail-closed): an artifact that was
# supposed to be written and is not is an internal error, whatever the verdict was.
GATED_UNWRITTEN = 'gated_unwritten'

_STALE_SCHEMA = 'geom.anthro/superseded-summary/1'

# The status word the registry's EXISTING consumers already draw red and never as a pass:
# inspection.html's anthroState() tests `status === 'gate-error'` first, before it looks at
# the verdict word, and anthroHtml() prints the reason in an alarm box. Inventing a new
# word here would have meant every shipped surface falling through to its unknown-value
# branch, which is precisely how a stale pass keeps getting displayed. The meaning matches:
# in both cases the gate engine did not produce a verdict for this body.
_STALE_STATUS = 'gate-error'

_STALE_NOTE = (
    'This body could not be gated, so the summary stored here describes a mesh that is no '
    'longer what this recipe rebuilds. It has been demoted to superseded_summary and is '
    'NOT a current verdict. Nothing was deleted.'
)


def _stale_summary(prev, *, name, reason, by, now, stale_artifacts=(), repair=None):
    """The record that REPLACES a stored anthro summary for a body that cannot be gated.

    Three properties, each of which is asserted in the selftest rather than left to review:

    1. It carries NO `verdict` key. Not 'ERROR', not 'NOT GATED' — absent. Every consumer
       of this dict reaches for `verdict` and colours by it, and the only honest answer to
       "what is this body's verdict" is that there is not one.
    2. `superseded_summary` holds the previous record VERBATIM. Demote, never delete: the
       old numbers are still the evidence for what changed, and an operator who cannot see
       what was superseded cannot tell a first refusal from a long-standing one.
    3. Superseding a supersession does not nest. The ORIGINAL measured summary stays at
       `superseded_summary` and only the timestamps move, so a nightly `check all` cannot
       bury the last real verdict under N layers of wrapper.
    """
    prev = prev or {}
    was_stale = bool(prev.get('stale'))
    original = (prev.get('superseded_summary') or None) if was_stale else (prev or None)
    rec = {
        'status': _STALE_STATUS,
        'stale': True,
        'schema': _STALE_SCHEMA,
        # `error` because that is the key the shipped GUI reads for the reason line, and a
        # refusal to gate IS the error for the operator's purposes.
        'error': reason,
        'stale_reason': reason,
        'note': _STALE_NOTE,
        'invalidated_by': by,
        'invalidated_at': now,
        'first_invalidated_at': (prev.get('first_invalidated_at') or prev.get('invalidated_at') or now)
        if was_stale
        else now,
        'generated': now,
        'summary_line': (
            'anthro char=%s verdict=NONE (SUPERSEDED, body not gateable) '
            'exit=%d was=%s generated=%s reason=%s'
            % (
                name,
                EXIT_ERROR,
                (original or {}).get('verdict') or 'none',
                (original or {}).get('generated') or 'unknown',
                reason,
            )
        ),
        'superseded_summary': original,
        'superseded_verdict': (original or {}).get('verdict'),
        'superseded_generated': (original or {}).get('generated'),
        'superseded_report': (original or {}).get('report'),
        'stale_artifacts': list(stale_artifacts),
        'repair': repair,
    }
    return rec


def _stale_report_doc(prev_doc, *, name, reason, by, now):
    """The same supersession for the CLI's own artifact store.

    Kept at report.py's schema on purpose, so `report.read_json` still parses it and
    `report.exit_code` still answers — and answers 3, because `verdict` is ERROR. A stub
    with a foreign schema would have made every reader raise, which is loud but tells a
    caller nothing about WHY the file it wanted is not a report.
    """
    prev_doc = prev_doc if isinstance(prev_doc, dict) else {}
    was_stale = bool(prev_doc.get('stale'))
    original = (prev_doc.get('superseded') or {}) if was_stale else prev_doc
    prev_vol = original.get('volatile') or {}
    # The superseded record is carried forward verbatim on a re-supersession, so by then
    # `summary_line` already exists and the sparse shape below is never re-rendered. The
    # coercion is here because render_summary formats %d over fields a first-generation
    # record may legitimately not carry, and losing the line to a TypeError would delete
    # the most readable evidence of what was demoted.
    prev_line = original.get('summary_line')
    if not prev_line and original:
        safe = dict(original)
        for _k, _d in (('counts', {}), ('ratio_summary', {}), ('n_gates', 0)):
            if safe.get(_k) is None:
                safe[_k] = _d
        prev_line = RPT.render_summary(safe)
    doc = {
        'schema': RPT.SCHEMA,
        'character': name,
        'verdict': RPT.ERROR,
        'exit_code': RPT.EXIT_CODES[RPT.ERROR],
        'n_gates': 0,
        'gates': [],
        'counts': {},
        'blocking': [],
        'unrun_blocking': [],
        'stale': True,
        'stale_reason': reason,
        'note': _STALE_NOTE,
        'invalidated_by': by,
        # Clock in `volatile` per this schema's own rule, so re-invalidating the same body
        # for the same reason does not churn the digest. `first_invalidated_at` is content:
        # when this body BECAME ungateable is a fact about the body, not about the clock.
        'first_invalidated_at': (prev_doc.get('first_invalidated_at') or now) if was_stale else now,
        'volatile': {'generated': now, 'invalidated_at': now},
        'policy_alarms': [
            {
                'kind': 'summary_superseded_body_not_gateable',
                'text': 'The gates could not be run on %s (%s). The report previously at this '
                'path described a mesh this recipe no longer rebuilds; it has been '
                'superseded, not deleted. This document is NOT a measurement.' % (name, reason),
            }
        ],
        'superseded': {
            'verdict': original.get('verdict'),
            'exit_code': original.get('exit_code'),
            'generated': prev_vol.get('generated') or original.get('generated'),
            'volatile': prev_vol or None,
            'stable_sha256': original.get('stable_sha256'),
            'n_gates': original.get('n_gates'),
            'counts': original.get('counts'),
            'summary_line': prev_line,
        },
    }
    doc['stable_sha256'] = RPT.stable_sha(doc)
    return doc


def _supersede_stale_summary(name, reason, *, report_path=None, enabled=True):
    """Mark every stored summary for `name` as superseded. Never raises.

    Returns a receipt: {'actions': [...], 'errors': [...]}. The caller prints it and keeps
    the exit code it already had — a failure to invalidate must not become a second, softer
    verdict, and it must not mask the refusal that caused it.

    WHAT IS AND IS NOT WRITTEN. registry.json is written (both `rec['anthro']` and the
    `rec['params']['anthro']` copy it embeds), and so is this CLI's own
    data/assets/anthro_reports/<name>.json. The two files BESIDE THE MESH — params.json and
    anthro_report.json — are deliberately left alone and NAMED instead, in
    `stale_artifacts`, with the repair command. For an ORIGINAL those files are 444 inside
    a 555 directory and are covered by `rec['aux_sha256']`: rewriting one from here would
    either trip the immutability alarm or force this CLI to re-record an aux hash set it
    did not regenerate, which is the exact defect `_aux_assert_unrewritten_intact` exists
    to close. Naming a stale file is honest; silently re-recording over it is not.
    """
    now = time.strftime('%Y-%m-%dT%H:%M:%S')
    by = 'python -m zyg_workflows.geom.anthro check %s' % name
    out = {'name': name, 'when': now, 'actions': [], 'errors': [], 'superseded': False}

    def note(msg):
        out['actions'].append(msg)

    if not enabled:
        note(
            'NOT superseded (--keep-stale-summary): any stored summary for %r is left in '
            'place and is now KNOWN-STALE' % name
        )
        return out

    # -- registry.json -------------------------------------------------------------
    try:
        from zyg_workflows.geom import mesh_skeletons as MS

        reg = MS._registry()
        sec = rec = None
        for s in ('originals', 'derived'):
            if name in (reg.get(s) or {}):
                sec, rec = s, reg[s][name]
                break
        if rec is None:
            note(
                'not in the registry (this is a control or an unregistered body) — no '
                'stored registry summary to supersede'
            )
        else:
            prev = rec.get('anthro')
            params = rec.get('params') if isinstance(rec.get('params'), dict) else {}
            prev_params = params.get('anthro')
            if not prev and not prev_params:
                note('registry entry %s/%s carries no stored summary — nothing to supersede' % (sec, name))
            else:
                arts = []
                d = rec.get('dir') or ''
                for fn in ('params.json', 'anthro_report.json'):
                    rel = os.path.join(d, fn)
                    if os.path.exists(os.path.join(MS.ROOT, rel)):
                        arts.append(rel)
                repair = 'python3 -m zyg_workflows.geom.mesh_skeletons gate %s' % name
                stale = _stale_summary(
                    prev or prev_params, name=name, reason=reason, by=by, now=now, stale_artifacts=arts, repair=repair
                )
                had = (
                    (prev or {}).get('verdict')
                    or (prev_params or {}).get('verdict')
                    or (prev or prev_params or {}).get('status')
                    or 'unknown'
                )
                rec['anthro'] = stale
                if prev_params is not None or params:
                    params['anthro'] = stale
                if rec.get('anthro_report'):
                    # Moved, not dropped: while the summary is superseded the GUI must not
                    # fetch and render the old full report as this body's current one.
                    rec['anthro_report_superseded'] = rec.pop('anthro_report')
                MS._save_registry(reg)
                out['superseded'] = True
                note(
                    'registry entry %s/%s SUPERSEDED (was %s, generated %s); the previous '
                    'record is kept at anthro.superseded_summary'
                    % (sec, name, had, (prev or prev_params or {}).get('generated') or 'unknown')
                )
                if arts:
                    note(
                        'still on disk and now STALE, deliberately not rewritten from '
                        'here: %s — repair with `%s`' % (', '.join(arts), repair)
                    )
    except Exception as e:  # noqa: BLE001
        out['errors'].append('registry NOT superseded: %s: %s' % (type(e).__name__, e))

    # -- this CLI's own artifact store ---------------------------------------------
    try:
        if report_path and os.path.exists(report_path):
            try:
                prev_doc = RPT.read_json(report_path)
            except Exception:  # noqa: BLE001
                prev_doc = {}
            RPT.write_json(_stale_report_doc(prev_doc, name=name, reason=reason, by=by, now=now), report_path)
            out['superseded'] = True
            note(
                '%s SUPERSEDED (was verdict %s, generated %s)'
                % (
                    report_path,
                    prev_doc.get('verdict') or 'unknown',
                    (prev_doc.get('volatile') or {}).get('generated') or prev_doc.get('generated') or 'unknown',
                )
            )
    except Exception as e:  # noqa: BLE001
        out['errors'].append('%s NOT superseded: %s: %s' % (report_path, type(e).__name__, e))
    return out


def _unwritten_notes(name, doc, path, reason):
    """What is on disk after a run that gated `name` and could not store the answer.

    Deliberately NOT `_supersede_stale_summary`. Every string that function writes says
    the body COULD NOT BE GATED — `_STALE_NOTE`, `_STALE_STATUS = 'gate-error'`, the
    `verdict=NONE` summary line. Stamping that over a record because a rename failed would
    replace one false statement (a stale verdict presented as current) with another (a
    gated body presented as ungateable), and it would do it by writing to the same store
    that just refused a write. So nothing is written; the discrepancy is stated instead,
    and it is stated at its worst: if the record still on disk is MORE FAVOURABLE than the
    verdict this run produced, that is the sentence the operator gets.
    """
    notes = [
        'the stored record for %s was deliberately NOT superseded: this body WAS '
        'gated, and every word `_stale_summary` writes says it was not. Re-run to '
        'store the verdict; nothing on disk carries it now.' % name
    ]
    prev = None
    try:
        if os.path.exists(path) and not os.path.isdir(path):
            prev = RPT.read_json(path)
    except Exception as e:  # noqa: BLE001
        notes.append(
            'the file at %s could not be read either (%s: %s), so what a reader '
            'finds there is unknown' % (path, type(e).__name__, e)
        )
        return notes
    if prev is None:
        notes.append('nothing is at %s, so no reader can obtain a verdict for %s from this run at all' % (path, name))
        return notes
    now_code, prev_code = RPT.exit_code(doc), RPT.exit_code(prev)
    notes.append(
        '%s still holds the PREVIOUS report: verdict %s (exit %d, generated %s). '
        'This run says %s (exit %d).'
        % (
            path,
            prev.get('verdict'),
            prev_code,
            (prev.get('volatile') or {}).get('generated') or prev.get('generated') or 'unknown',
            doc.get('verdict'),
            now_code,
        )
    )
    if prev_code < now_code:
        notes.append(
            'THE RECORD ON DISK IS MORE FAVOURABLE THAN THIS RUN. Anything '
            'reading %s will see %s while the gates just returned %s. Treat the '
            'stored file as superseded by hand until a write succeeds.'
            % (path, prev.get('verdict'), doc.get('verdict'))
        )
    return notes


def _roster_exit_code(roster):
    """The worst outcome across the WHOLE roster. 0 pass / 1 warn / 2 fail / 3 error.

    max() is only correct because the four codes are ordered by severity by construction,
    so that ordering is asserted here rather than assumed. A roster entry with no code, and
    an empty roster, are both 3: a run that established nothing is an internal error, never
    a pass. That is the whole point of the fix — 'covered 2 of 5' must not exit like
    'covered 5'.
    """
    if not (EXIT_OK < EXIT_WARN < EXIT_FAIL < EXIT_ERROR):
        raise RuntimeError('exit-code severity order broke')
    if not roster:
        return EXIT_ERROR
    worst = EXIT_OK
    for r in roster:
        c = r.get('exit_code')
        worst = max(worst, EXIT_ERROR if c is None else int(c))
    return worst


def _render_roster(roster, width=100):
    """gated / UNWRITTEN / SKIPPED-with-reason, for every character the run was asked for.

    The three outcomes are three different claims about coverage and the header line says
    which is which. GATED: the gates ran and the verdict is on disk. UNWRITTEN: the gates
    ran, the verdict is in the text above, the file is not there. SKIPPED: the gates did
    not run and this run establishes NOTHING about that body. Only the last of the three
    may be described as 'never gated'.
    """
    gated = [r for r in roster if r['outcome'] == GATED]
    unwritten = [r for r in roster if r['outcome'] == GATED_UNWRITTEN]
    skipped = [r for r in roster if r['outcome'] == SKIPPED]
    fixt = [r for r in gated + unwritten if r.get('fixture')]
    tally = {}
    for r in gated + unwritten:
        tally[r.get('verdict') or 'UNKNOWN'] = tally.get(r.get('verdict') or 'UNKNOWN', 0) + 1
    rule = '=' * max(40, min(int(width), 100))
    L = [
        rule,
        'CHECK ROSTER — %d character(s) requested, %d gated (%d of them with NO ARTIFACT '
        'WRITTEN), %d SKIPPED (never gated)' % (len(roster), len(gated) + len(unwritten), len(unwritten), len(skipped)),
    ]
    if tally:
        L.append('  of the gated: %s' % ', '.join('%d %s' % (n, v) for v, n in sorted(tally.items())))
    if fixt:
        L.append('  %d of the gated ran against the CONTRACT FIXTURE, not against gates.py' % len(fixt))
    for r in roster:
        if r['outcome'] == GATED:
            L.append(
                '  %-9s %-16s %-20s exit %s  [%s]'
                % (
                    'FIXTURE' if r.get('fixture') else 'GATED',
                    r['name'],
                    r.get('verdict') or 'UNKNOWN',
                    r.get('exit_code'),
                    r.get('section') or 'unknown-section',
                )
            )
        elif r['outcome'] == GATED_UNWRITTEN:
            L.append(
                '  %-9s %-16s %-20s exit %s  [%s]'
                % (
                    'UNWRITTEN',
                    r['name'],
                    '%s, NOT SAVED' % (r.get('verdict') or 'UNKNOWN'),
                    r.get('exit_code'),
                    r.get('section') or 'unknown-section',
                )
            )
            L += RPT._wrap(
                'THIS BODY WAS GATED. Its verdict is %s and the gate rows are '
                'printed above; only the artifact is missing.' % (r.get('verdict') or 'UNKNOWN'),
                width,
                12,
            )
            L += RPT._wrap('the write failed: ' + (r.get('reason') or 'no reason recorded'), width, 12)
            for note in r.get('notes') or []:
                L += RPT._wrap('!! ' + note, width, 12)
        elif r['outcome'] == SKIPPED:
            L.append(
                '  %-9s %-16s %-20s exit %s  [%s]'
                % ('SKIPPED', r['name'], 'NOT GATED', r.get('exit_code'), r.get('section') or 'unknown-section')
            )
            L += RPT._wrap('why: ' + (r.get('reason') or 'no reason recorded'), width, 12)
            inval = r.get('invalidation') or {}
            for act in inval.get('actions') or []:
                L += RPT._wrap('- ' + act, width, 12)
            for err in inval.get('errors') or []:
                L += RPT._wrap('!! ' + err, width, 12)
        else:
            # An outcome word this renderer does not know. It used to fall into the
            # SKIPPED branch and be printed as 'NOT GATED', which is how a new outcome
            # would have inherited a claim nobody checked. It is named instead, and it
            # counts in neither the gated nor the skipped tally above — so the header's
            # two numbers will visibly fail to add up to the roster length.
            L.append(
                '  %-9s %-16s %-20s exit %s  [%s]'
                % (
                    '???',
                    r['name'],
                    'UNRECOGNISED OUTCOME %r' % (r['outcome'],),
                    r.get('exit_code'),
                    r.get('section') or 'unknown-section',
                )
            )
            L += RPT._wrap(
                'this renderer does not know what %r means, so it makes NO '
                'claim about whether %s was gated. Treat it as not covered.' % (r['outcome'], r['name']),
                width,
                12,
            )
    code = _roster_exit_code(roster)
    tail = ''
    if skipped:
        tail += ' — %d of %d character(s) were NOT gated and nothing in this run says anything about them' % (
            len(skipped),
            len(roster),
        )
    if unwritten:
        tail += (
            '%s%d of %d character(s) WERE gated but their report could not be '
            "written, so nothing on disk carries this run's verdict for them"
            % ('; ' if tail else ' — ', len(unwritten), len(roster))
        )
    L.append(
        'worst outcome across the roster: exit %d (%s)%s'
        % (
            code,
            {EXIT_OK: 'pass', EXIT_WARN: 'pass-with-warnings', EXIT_FAIL: 'fail', EXIT_ERROR: 'internal error'}.get(
                code, '?'
            ),
            tail,
        )
    )
    L.append(rule)
    return '\n'.join(L)


# ---------------------------------------------------------------------------------
# --out, resolved ONCE and BEFORE any gate runs
#
# N4. `--out` is documented as "output directory or file", and it was a directory for
# `selftest`, a directory for `reference`, a directory for `check all` — and a FILE, with
# no other option, for `check <one character>`. Passing the documented directory there
# ran every gate, printed the whole report, and then died inside the atomic rename with
# IsADirectoryError. That is fail-closed, which is right, but it burned a full mesh build
# and a full gate run before saying so, and the failure arrived through a generic
# `except Exception` that classified a gated body as never gated.
#
# Both halves are closed here. The directory form is SUPPORTED, as documented, for one
# character as well as for many; and the one combination that cannot be honoured —
# several characters into a single existing file — is REFUSED up front, before the anny
# model is even loaded, instead of failing N times at the last step.
# ---------------------------------------------------------------------------------
class OutSpecError(ValueError):
    """`--out` cannot be honoured for this run. Raised before any body is measured."""


def _looks_like_dir(path):
    """A directory, or something the caller has written as one.

    Existence is checked first because it is the only non-guess. A trailing separator is
    honoured for a path that does not exist yet, because that is how every shell and every
    other tool spells "this is a directory, make it".
    """
    return bool(os.path.isdir(path) or path.endswith(os.sep) or (os.altsep and path.endswith(os.altsep)))


def _resolve_out_paths(out, names):
    """{character: json path}, or raise OutSpecError. NOTHING is measured before this.

    The rule, stated once here so the help text can quote it verbatim:
      * no --out          -> the default report store, one file per character
      * --out DIR         -> DIR/<character>.json, for one character or for many
      * --out FILE        -> that exact file. ONE character only; for several it raises,
                             because N reports cannot share one path and the last one
                             would silently be the only survivor.
      * --out NEW-PATH    -> a file for one character, a directory for several. This is
                             the pre-existing behaviour and it is kept: an operator who
                             types a new path for one body means a file.
    """
    if not out:
        return {n: RPT.report_path(n, RPT.ROOT) for n in names}
    if _looks_like_dir(out):
        return {n: RPT.report_path(n, out) for n in names}
    if len(names) > 1:
        if os.path.exists(out):
            raise OutSpecError(
                '--out %s is an existing FILE and %d characters were requested (%s). '
                '%d reports cannot share one path — the run would either overwrite the '
                'same file %d times or fail at the last step, and neither is a report '
                'about %d bodies. Pass a directory, or check one character at a time.'
                % (out, len(names), ', '.join(names), len(names), len(names), len(names))
            )
        return {n: RPT.report_path(n, out) for n in names}
    return {names[0]: out}
