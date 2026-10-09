# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""geom.anthro CLI — the selftest command and the list command.

Moved verbatim from geom/anthro/__main__.py (lines 1127-1633) when that 1,757-line
file became the __main__ shim over this package. No logic was changed.

``cmd_selftest`` kept the step banners, the ``check`` reporter and the gate-absent
fallback; its eight numbered steps live in :mod:`.selftest_steps`. All printing stays
here: ``scripts/ratchet.py`` exempts ``**/selftest.py`` from ``print_calls`` by file
name, so the steps take ``check`` as an argument instead of printing themselves.
"""

import functools

from zyg_workflows.geom.anthro import report as RPT

from zyg_workflows.geom.anthro.main_ops.constants import EXIT_FAIL, EXIT_OK, EXIT_WARN, GatesAbsent
from zyg_workflows.geom.anthro.main_ops.characters import _age_years, _characters
from zyg_workflows.geom.anthro.main_ops.gates_adapter import call_gates
from zyg_workflows.geom.anthro.main_ops import selftest_steps as ST


def _check(fails, label, cond, detail=''):
    """Print one labelled selftest result; record the label in ``fails`` when it failed.

    This is the ``check`` every step is handed, bound to the run's failure list.
    """
    print('  %-58s %s%s' % (label, 'ok' if cond else 'FAIL', ('  ' + detail) if detail else ''))
    if not cond:
        fails.append(label)


def cmd_selftest(a):
    """Exercise the whole stack on one character and assert the pieces fit together.

    Deliberately not pytest: this package has to be runnable from the pipeline host, which
    has no test runner in its venv.
    """
    fails = []
    check = functools.partial(_check, fails)

    print('geom.anthro selftest')
    print(' [1] renderer arithmetic (no mesh, no pack)')
    print('  %s' % RPT._selftest())

    print(' [2] reference pack')
    ref = ST.reference_pack(check)

    name = a.character
    print(' [3] measure %s' % name)
    rec, measurement, v, f, meta = ST.measure_character(check, name)

    print(' [4] percentile strip')
    ST.percentile_strip(check, measurement, rec, meta, ref)

    print(' [5] gates')
    stub = False
    try:
        gate_report, entry, subject = call_gates(rec, measurement, v, f)
        check('gates.py called', True, 'entry point %s()' % entry)
        check(
            'gate report is a mapping with rows',
            isinstance(gate_report, (dict, list)) and len(list(RPT._iter_gates(gate_report))) > 0,
            '%d rows' % len(list(RPT._iter_gates(gate_report))),
        )
    except GatesAbsent as e:
        stub = True
        gate_report = RPT.contract_fixture(character=name, sex=rec['sex'])
        entry = 'CONTRACT FIXTURE'
        print('  gates.py ABSENT (%s) — using the documented contract fixture' % e)

    print(' [6] report assembly')
    age = _age_years(rec)
    doc = ST.report_assembly(check, gate_report, measurement, name, rec, age)
    if not stub:
        ST.tier5_canon_policy(check, doc, gate_report, measurement, name, rec, age)
    txt = RPT.render_text(doc)
    for section in ('VERDICT:', 'GATES', 'PERCENTILE STRIP', 'STYLIZATION DELTA', 'PROVENANCE'):
        check('text report contains %r' % section, section in txt)
    line = RPT.render_summary(doc)
    check('summary is one line', '\n' not in line and len(line) > 20, line[:70] + '...')

    print(' [7] artifact')
    ST.artifact_roundtrip(check, a.out, name, doc, gate_report, measurement, rec, age)

    # -- [8] failure reporting: the roster, and the supersession of a stale summary ----
    print(' [8] failure reporting (F7 + the stale summary)')
    ST.failure_roster(check)
    ST.out_spec_and_supersession(check, a.out, name)

    print('')
    if stub:
        print(
            'NOTE: geom.anthro.gates was ABSENT — steps 5 and 6 ran against the '
            'documented CONTRACT FIXTURE, not against real gates.'
        )
    if fails:
        print('SELFTEST FAILED: %d check(s): %s' % (len(fails), '; '.join(fails)))
        return EXIT_FAIL
    print('SELFTEST OK%s' % (' (gates stubbed)' if stub else ''))
    return EXIT_WARN if stub else EXIT_OK


def cmd_list(a):
    chars = _characters()
    print('%-24s %-10s %-8s %-10s %s' % ('character', 'section', 'sex', 'ancestry', 'age_frac'))
    for k in sorted(chars):
        c = chars[k]
        print(
            '%-24s %-10s %-8s %-10s %s'
            % (k, c['section'], c['sex'], c.get('ancestry') or 'undeclared', c.get('age_frac'))
        )
    return EXIT_OK
