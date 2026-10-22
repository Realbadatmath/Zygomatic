# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.capabilities_tests`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.capabilities_tests` still reaches it.
"""

import json
import sys


def _main(argv):
    """The verb dispatcher that used to live in capabilities_tests._main."""
    # The library module does not import on a bare checkout (it is on tests/import_smoke_skip.txt),
    # so the CLI imports it only when it actually runs — the smoke test imports this module clean.
    from zyg_dashboard import capabilities_tests as _mod
    from zyg_dashboard.capabilities_tests import (
        CT,
        columns_of,
        dispositions,
        load_test,
        row_view,
        summary,
        validate,
        validate_shared,
    )

    verb = argv[0] if argv else 'list'
    if verb == 'list':
        from zyg_dashboard.capabilities_hub import STEPS

        for s in STEPS:
            v = summary(s['id'])
            if not v.get('present'):
                print(f'{s["id"]:<16} —')
                continue
            print(
                f'{s["id"]:<16} {"OK " if v["ok"] else "BAD"} {v.get("columns", 0):>4} cols '
                f'{v.get("probes", 0):>3} probes  hash {v.get("hash", "-")}  '
                f'{len(v.get("errors", []))} errors {len(v.get("warnings", []))} warnings'
            )
        return 0
    step = argv[1] if len(argv) > 1 else None
    if verb == 'check':
        steps = list(CT.STEPS_WITH_TESTS) if step in (None, 'all') else [step]
        bad = 0
        for s in steps:
            v = validate(s)
            print(f'\n== {s}  {"OK" if v["ok"] else "FAIL"}  version {v.get("version")}  hash {v.get("hash")}')
            if v.get('present'):
                print(
                    f'   {v["columns"]} columns · {v["probes"]} probes · {v["operator_checks"]} operator checks · '
                    f'dispositions {v["dispositions"]} · rows {v["rows"]}'
                )
            b = v.get('budget') or {}
            if b.get('total'):
                tt = b['total']
                print(
                    f'   budget per row: {b.get("calls")} calls · {b.get("tokens_in")} in / {b.get("tokens_out")} out tokens · '
                    f'{b.get("minutes")} min ({b.get("gpu_minutes")} GPU) · operator {b.get("operator_minutes")} min · '
                    f'all {b.get("rows")} rows: {int(tt["tokens_in"])} in / {int(tt["tokens_out"])} out · {round(tt["minutes"])} min · operator {round(tt["operator_minutes"])} min'
                )
            for e in v['errors']:
                print('   ERROR  ', e)
            for w in v['warnings']:
                print('   warn   ', w)
            bad += 0 if v['ok'] else 1
        return 1 if bad else 0
    if verb == 'questions':
        # every column the sheet asks, grouped, WITHOUT needing a test module — what a new
        # test has to give a disposition to. Works for every step in capabilities_hub.STEPS.
        by_group = {}
        for c in columns_of(step):
            by_group.setdefault(c.get('group') or '—', []).append(c)
        for g, cs in by_group.items():
            print(f'\n[{g}]  ({len(cs)})')
            for c in cs:
                hint = (c.get('hint') or '').replace('\n', ' ')
                print(f'  {c["id"]:<26} {c["label"]}' + (f'  — {hint}' if hint else ''))
        print(f'\n{len(columns_of(step))} columns')
        return 0
    if verb == 'shared':
        v = validate_shared(step, strict='--strict' in argv)
        print(f'== shared {step}  {"OK" if v["ok"] else "FAIL"}  version {v.get("version")}  probes {v.get("probes")}')
        for e in v['errors']:
            print('   ERROR  ', e)
        for w in v['warnings']:
            print('   warn   ', w)
        for st, cols in (v.get('uncovered') or {}).items():
            print(
                f'   {st:<16} covers {v["covered"][st]} of {v["asked"][st]} asked columns; NOT covered by the bank: {", ".join(cols) if cols else "—"}'
            )
        return 0 if v['ok'] else 1
    if verb == 'columns':
        t = load_test(step)
        d, _ = dispositions(t, step)
        by_group = {}
        for c in columns_of(step):
            by_group.setdefault(c.get('group') or '—', []).append(c)
        for g, cs in by_group.items():
            print(f'\n[{g}]')
            for c in cs:
                v = d[c['id']]
                how = ', '.join(f'{k}:{r}' for k, r in v) or 'MISSING'
                print(f'  {c["id"]:<24} {how:<40} {c["label"]}')
        return 0
    if verb == 'show':
        print(json.dumps(load_test(step), indent=1, ensure_ascii=False, default=str))
        return 0
    if verb == 'row':
        rid = argv[2]
        for c, (k, ref, why) in row_view(step, rid).items():
            print(f'  {c:<24} {k:<8} {ref:<28} {why}')
        return 0
    # The usage text is the LIBRARY module's docstring, as it was when this lived there.
    print(_mod.__doc__)
    return 2


if __name__ == '__main__':
    sys.exit(_main(sys.argv[1:]))
