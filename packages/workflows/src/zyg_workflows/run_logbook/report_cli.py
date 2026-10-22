# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.run_logbook.report`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.run_logbook.report` still reaches it.
"""

import json
import sys

from zyg_workflows.run_logbook import report as _mod
from zyg_workflows.run_logbook.report import (
    compare_runs,
    format_compare,
    format_list,
    ingest_run_dir,
    load_run,
    resolve_run,
    resume_from,
)


def _main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(_mod.__doc__.strip().splitlines()[0])
        print(
            'usage: python3 run_logbook.py list | compare <A> <B> | show <run> | '
            'resume <run_dir> | ingest <run_dir> [--version vNN] [--driver PATH]'
        )
        return 1
    cmd = argv[0]
    if cmd == 'list':
        print(format_list())
        return 0
    if cmd == 'compare':
        pos = [a for a in argv[1:] if not a.startswith('--')]
        if len(pos) < 2:
            print('usage: run_logbook.py compare <runA> <runB> [--top N]')
            return 2
        top = None
        if '--top' in argv:
            try:
                top = int(argv[argv.index('--top') + 1])
            except (ValueError, IndexError):
                top = None
        cmp = compare_runs(pos[0], pos[1], log_fn=None)
        print(format_compare(cmp, limit=top))
        return 0 if cmp.get('ok') else 1
    if cmd == 'show':
        if len(argv) < 2:
            print('usage: run_logbook.py show <run>')
            return 2
        h = resolve_run(argv[1])
        if h is None:
            print(f'unknown run: {argv[1]}')
            return 1
        print(json.dumps(load_run(h), indent=1, default=str))
        return 0
    if cmd == 'resume':
        if len(argv) < 2:
            print('usage: run_logbook.py resume <run_dir>')
            return 2
        print(json.dumps(resume_from(argv[1]), indent=1, default=str))
        return 0
    if cmd == 'ingest':
        if len(argv) < 2:
            print('usage: run_logbook.py ingest <run_dir> [--version vNN] [--driver PATH]')
            return 2
        ver = argv[argv.index('--version') + 1] if '--version' in argv else None
        drv = argv[argv.index('--driver') + 1] if '--driver' in argv else None
        h = ingest_run_dir(argv[1], version=ver, driver_file=drv, log_fn=print)
        print(json.dumps({'run_key': h.get('run_key'), 'jsonl': h.get('jsonl')}, indent=1))
        return 0
    print(f'unknown command: {cmd}')
    return 2


if __name__ == '__main__':
    sys.exit(_main())
