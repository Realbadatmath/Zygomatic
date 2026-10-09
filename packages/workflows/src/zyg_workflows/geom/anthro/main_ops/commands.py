# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — the check, measure, reference and build-pack commands.

Moved verbatim from geom/anthro/__main__.py (lines 878-1124) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.
"""

import json
import sys
import traceback
from zyg_workflows.geom.anthro import report as RPT

from zyg_workflows.geom.anthro.main_ops.constants import EXIT_ERROR, EXIT_OK, GatesAbsent, GatesUnusable
from zyg_workflows.geom.anthro.main_ops.characters import (
    _age_years,
    _characters,
    _measure,
    _resolve,
    _validate_ancestry,
)
from zyg_workflows.geom.anthro.main_ops.gates_adapter import call_gates
from zyg_workflows.geom.anthro.main_ops.roster import (
    GATED,
    GATED_UNWRITTEN,
    OutSpecError,
    SKIPPED,
    _render_roster,
    _resolve_out_paths,
    _roster_exit_code,
    _supersede_stale_summary,
    _unwritten_notes,
)

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ---------------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------------
def cmd_check(a):
    chars = _characters()
    if a.character == 'all':
        names = sorted(chars)
    else:
        _resolve(a.character)
        names = [a.character]

    if not names:
        sys.stderr.write(
            'INTERNAL ERROR: nothing to check — the roster is empty, so this run establishes nothing about any body\n'
        )
        return EXIT_ERROR

    # N4: resolved HERE, before the first mesh is built. An --out that cannot be honoured
    # is a usage error and costs nothing to detect; discovering it after five gate runs
    # have printed is a waste and, worse, arrives as an exception that looks like a body
    # that could not be measured.
    try:
        out_paths = _resolve_out_paths(a.out, names)
    except OutSpecError as e:
        sys.stderr.write('INTERNAL ERROR: %s\n' % e)
        sys.stderr.write(
            '*** NOTHING WAS GATED. No body was measured and this run says NOTHING about any of them. ***\n'
        )
        return EXIT_ERROR

    roster = []
    stub_used = False
    for name in names:
        rec = chars[name]
        fixture = False
        try:
            ancestry = a.ancestry if a.ancestry is not None else rec.get('ancestry')
            _validate_ancestry(rec['sex'], ancestry)
            try:
                gate_report, entry, subject = call_gates(rec, ancestry=ancestry)
                measurement = getattr(subject, 'measurements', None)
                if measurement is None:
                    measurement, _v, _f = _measure(rec)
            except GatesAbsent as e:
                stub_used = fixture = True
                measurement, _v, _f = _measure(rec)
                gate_report = RPT.contract_fixture(character=name, sex=rec['sex'])
                entry = 'CONTRACT FIXTURE (geom.anthro.gates absent: %s)' % e
                sys.stderr.write(
                    '*** geom.anthro.gates is ABSENT. The gate rows below are the '
                    'documented CONTRACT FIXTURE, not a measurement of %s. The percentile '
                    'strip and the measurement block ARE real. ***\n' % name
                )
            doc = RPT.build(
                gate_report,
                measurement,
                name=name,
                sex=rec['sex'],
                ancestry=ancestry,
                band_width=a.width,
                age_years=_age_years(rec),
                extra={'gates_entrypoint': entry, 'section': rec['section']},
            )
            if not a.quiet:
                # The one-line summary is printed below with the artifact path appended, so
                # the long form omits its own copy rather than repeating it.
                _zyg_log.info(
                    RPT.render_text(doc, width=a.columns, show_passing_gates=not a.only_problems, include_summary=False)
                )
                _zyg_log.info('')
            # THE WRITE IS ITS OWN FAILURE CLASS. Everything above this line is "can this
            # body be gated"; this line is "can the answer be stored". Sharing one
            # `except` made the second look like the first and print `never gated` about a
            # body whose sixty gate rows had just been printed. The verdict is already
            # computed and already on screen — what is lost is the artifact, and only that
            # is claimed.
            try:
                written = RPT.write_json(doc, out_paths[name])
            except Exception as e:  # noqa: BLE001
                reason = '%s: %s' % (type(e).__name__, e)
                notes = _unwritten_notes(name, doc, out_paths[name], reason)
                _zyg_log.info(RPT.render_summary(doc) + ' json=NOT WRITTEN (%s)' % reason)
                sys.stderr.write(
                    '*** %s WAS GATED — verdict %s, exit %d — but its report could NOT '
                    'be written to %s: %s ***\n'
                    % (name, doc.get('verdict'), RPT.exit_code(doc), out_paths[name], reason)
                )
                for nt in notes:
                    sys.stderr.write('    !! %s\n' % nt)
                roster.append(
                    {
                        'name': name,
                        'section': rec['section'],
                        'outcome': GATED_UNWRITTEN,
                        'verdict': doc.get('verdict'),
                        # Fail-closed: an artifact that was supposed to exist and
                        # does not is an internal error, whatever the verdict was.
                        # A FAIL verdict is not softened either — max() keeps the
                        # worse of the two.
                        'exit_code': max(EXIT_ERROR, RPT.exit_code(doc)),
                        'fixture': fixture,
                        'json': None,
                        'reason': reason,
                        'notes': notes,
                        'gate_exit_code': RPT.exit_code(doc),
                    }
                )
                continue
            _zyg_log.info(RPT.render_summary(doc) + ' json=%s' % written)
            roster.append(
                {
                    'name': name,
                    'section': rec['section'],
                    'outcome': GATED,
                    'verdict': doc.get('verdict'),
                    'exit_code': RPT.exit_code(doc),
                    'fixture': fixture,
                    'json': written,
                }
            )
        # A body this run could not gate must not end the run: the characters after it are
        # entitled to be measured, and — worse — an abort names neither them nor the body
        # that caused it. KeyboardInterrupt is BaseException and is deliberately NOT in
        # this tuple; the operator's Ctrl-C still stops everything.
        except (GatesUnusable, SystemExit, Exception) as e:  # noqa: BLE001
            if isinstance(e, SystemExit):
                reason = str(e.code) if e.code is not None else 'SystemExit'
            else:
                reason = '%s: %s' % (type(e).__name__, e)
            if isinstance(e, GatesUnusable):
                # Same wording main() used before this loop caught it, so anything grepping
                # for the old line still finds it.
                sys.stderr.write('INTERNAL ERROR: %s\n' % e)
            elif isinstance(e, SystemExit):
                sys.stderr.write('INTERNAL ERROR: %s\n' % reason)
            else:
                # An unexpected exception is a bug, not a finding: print the traceback
                # exactly as main() would have, then carry on with the rest of the roster.
                sys.stderr.write('INTERNAL ERROR while checking %s:\n' % name)
                traceback.print_exc()
            sys.stderr.write('*** %s WAS NOT GATED. This run says NOTHING about it. ***\n' % name)
            inval = _supersede_stale_summary(
                name, reason, report_path=out_paths[name], enabled=not getattr(a, 'keep_stale_summary', False)
            )
            for act in inval['actions']:
                sys.stderr.write('    %s\n' % act)
            for err in inval['errors']:
                sys.stderr.write(
                    '    !! %s — a summary that could not be invalidated is still being presented as current\n' % err
                )
            roster.append(
                {
                    'name': name,
                    'section': rec['section'],
                    'outcome': SKIPPED,
                    'verdict': None,
                    'exit_code': EXIT_ERROR,
                    'reason': reason,
                    'invalidation': inval,
                }
            )
    skipped = [r for r in roster if r['outcome'] == SKIPPED]
    unwritten = [r for r in roster if r['outcome'] == GATED_UNWRITTEN]
    if len(names) > 1 or skipped or unwritten:
        _zyg_log.info('')
        _zyg_log.info(_render_roster(roster, width=a.columns))
    if stub_used:
        sys.stderr.write('*** VALIDATED AGAINST A CONTRACT FIXTURE, NOT AGAINST gates.py ***\n')
    if skipped:
        sys.stderr.write(
            '*** %d of %d character(s) COULD NOT BE GATED: %s ***\n'
            % (len(skipped), len(roster), ', '.join(r['name'] for r in skipped))
        )
    if unwritten:
        sys.stderr.write(
            '*** %d of %d character(s) WERE GATED but their report could not '
            'be written: %s. The verdicts are in the output above and '
            'NOWHERE ELSE. ***\n'
            % (len(unwritten), len(roster), ', '.join('%s=%s' % (r['name'], r.get('verdict')) for r in unwritten))
        )
    return _roster_exit_code(roster)


def cmd_measure(a):
    rec = _resolve(a.character)
    _validate_ancestry(rec['sex'], a.ancestry if a.ancestry is not None else rec.get('ancestry'))
    measurement, _v, _f = _measure(rec)
    if a.json:
        _zyg_log.info(json.dumps(measurement, indent=1, sort_keys=True, default=RPT._jsonable))
        return EXIT_OK
    _zyg_log.info(RPT.render_measurements(measurement, width=a.columns))
    doc = RPT.build(
        None,
        measurement,
        name=rec['name'],
        sex=rec['sex'],
        ancestry=a.ancestry if a.ancestry is not None else rec.get('ancestry'),
        band_width=a.width,
        age_years=_age_years(rec),
    )
    if doc.get('ratios'):
        _zyg_log.info('')
        _zyg_log.info(RPT.render_percentile_strip(doc['ratios'], width=a.columns))
    alarms = RPT.render_alarms(doc, width=a.columns)
    if alarms:
        _zyg_log.info('')
        _zyg_log.info(alarms)
    _zyg_log.info('')
    _zyg_log.info(RPT.render_summary(doc))
    return EXIT_OK


def cmd_reference(a):
    from zyg_workflows.geom.anthro.reference import reference

    ref = reference()
    if a.ratio in ('list', 'all'):
        _zyg_log.info('ratios in the pack (%d):' % len(ref.ratios()))
        for r in ref.ratios():
            _zyg_log.info('  %s' % r)
        _zyg_log.info(
            '\ngroups: male %s ; female %s' % (', '.join(ref.groups('male')), ', '.join(ref.groups('female')))
        )
        return EXIT_OK
    _zyg_log.info(RPT.render_reference(a.ratio, a.sex, a.ancestry, width_label=a.width, ref=ref, width=a.columns))
    return EXIT_OK


def cmd_build_pack(a):
    from zyg_workflows.geom.anthro import build_reference
    from zyg_workflows.geom.anthro.reference import AnthroReference

    root = a.out or build_reference.ROOT
    out = build_reference.build(out_root=root)
    if isinstance(out, dict):
        _zyg_log.info(
            'reference pack rebuilt at %s: %s'
            % (root, json.dumps({k: out[k] for k in list(out)[:8]}, default=str)[:400])
        )
    else:
        _zyg_log.info('reference pack rebuilt at %s: %s' % (root, out))
    # Reading it back through the runtime reader is the only proof that what was written
    # is what this package can actually consume.
    ref = AnthroReference(root)
    _zyg_log.info(
        'verified by reading it back: %d ratios, %d dimensions, male groups %s'
        % (len(ref.ratios()), len(ref.dimensions()), ', '.join(ref.groups('male')))
    )
    return EXIT_OK
