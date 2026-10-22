# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_zero.nomologin_mail`, moved out of the library module so that
library code never prints; `python -m zyg_zero.nomologin_mail` still reaches it.
"""

import json
import sys

from zyg_zero.nomologin_mail import (
    MailError,
    check,
    codes,
    configure,
    configured,
    forget,
    message,
    recent,
)


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="read a persona's mailbox (read-only)")
    ap.add_argument('persona')
    ap.add_argument(
        'action', nargs='?', default='check', help='check | recent | codes | read <uid> | configure | forget | list'
    )
    ap.add_argument('rest', nargs='*')
    ap.add_argument('--host'), ap.add_argument('--user'), ap.add_argument('--password')
    ap.add_argument('--port', type=int, default=993)
    ap.add_argument('--minutes', type=float, default=30.0)
    ap.add_argument('-n', type=int, default=20)
    ap.add_argument('--unread', action='store_true')
    a = ap.parse_args(argv)
    try:
        if a.action == 'list':
            out = configured()
        elif a.action == 'configure':
            out = configure(a.persona, a.host, a.user, a.password, a.port)
        elif a.action == 'forget':
            out = forget(a.persona)
        elif a.action == 'check':
            out = check(a.persona)
        elif a.action == 'recent':
            out = recent(a.persona, a.n, a.unread)
        elif a.action == 'codes':
            out = codes(a.persona, a.minutes)
        elif a.action == 'read':
            out = message(a.persona, a.rest[0])
        else:
            out = {'ok': False, 'error': f'unknown action {a.action}'}
    except (MailError, IndexError, TypeError) as exc:
        print(json.dumps({'ok': False, 'error': str(exc)}, indent=2))
        return 1
    print(json.dumps(out, indent=2, ensure_ascii=False)[:20000])
    return 0


def cli_main() -> int:
    """The argv hand-off that used to be the `if __name__` body of nomologin_mail."""
    return main(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(cli_main())
