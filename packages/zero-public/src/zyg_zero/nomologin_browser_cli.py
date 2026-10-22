# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_browser`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_browser` still reaches it.
"""

import json
import os
import sys

from zyg_zero.nomologin_browser import (
    BrowserError,
    act,
    nl,
    run,
    status,
)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description='drive a Nomologin persona browser')
    ap.add_argument('persona')
    ap.add_argument(
        'action',
        nargs='?',
        default='status',
        help='status | tabs | navigate | state | text | shot | click | type | '
        'press | scroll | wait | back, or - to read a JSON batch on stdin',
    )
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--tab', default=None)
    ap.add_argument('--index', type=int, default=None)
    ap.add_argument('--selector', default=None)
    ap.add_argument('--expect', default=None)
    a = ap.parse_args(argv)

    try:
        if a.action == 'status':
            out = status(a.persona)
        elif a.action == '-':
            out = run(a.persona, json.loads(sys.stdin.read()))
        else:
            kw: dict = {'tab': a.tab, 'index': a.index, 'selector': a.selector, 'expect': a.expect}
            joined = ' '.join(a.rest)
            if a.action == 'navigate':
                kw['url'] = joined
            elif a.action == 'type':
                kw['text'] = joined
            elif a.action == 'press':
                kw['key'] = joined
            elif a.action == 'wait':
                kw['selector'] = joined or a.selector
            elif a.action == 'shot':
                kw['path'] = joined or os.path.join(nl.ROOT, 'shots', f'{a.persona}.png')
                os.makedirs(os.path.dirname(kw['path']), exist_ok=True)
            out = act(a.persona, a.action, **kw)
    except (BrowserError, KeyError, ValueError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False)[:20000])
    return 0


def cli_main() -> int:
    """The argv hand-off that used to be the `if __name__` body of nomologin_browser."""
    return main(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(cli_main())
