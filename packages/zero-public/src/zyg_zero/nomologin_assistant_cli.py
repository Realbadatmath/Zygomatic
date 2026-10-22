# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_assistant`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_assistant` still reaches it.
"""

import json
import sys
import time

from zyg_zero.nomologin_assistant import (
    ask,
    available,
    view,
)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description='ask the persona assistant')
    ap.add_argument('persona')
    ap.add_argument('text', nargs='*')
    ap.add_argument('--check', action='store_true', help='report readiness and exit')
    ap.add_argument('--session', default=None)
    a = ap.parse_args(argv)
    if a.check:
        print(json.dumps(available(), indent=2))
        return 0
    if not a.text:
        print(json.dumps({'ok': False, 'error': 'nothing asked'}))
        return 2
    job = ask(a.persona, ' '.join(a.text), a.session)
    jid = job['id']
    while True:
        time.sleep(2.0)
        v = view(jid)
        if v['status'] != 'running':
            print(json.dumps(v, indent=2, ensure_ascii=False)[:20000])
            return 0 if v['status'] == 'done' else 1
        sys.stderr.write(f'\r{v["steps"]} steps, {v["seconds"]:.0f}s  ')
        sys.stderr.flush()


def cli_main() -> int:
    """The argv hand-off that used to be the `if __name__` body of nomologin_assistant."""
    return main(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(cli_main())
