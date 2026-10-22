# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.measure_style_margins`, moved out of the library module so
that library code never prints; `python -m zyg_workflows.tools.measure_style_margins` still
reaches it.
"""

import argparse
import sys

from zyg_workflows import kids_music_service as S
from zyg_workflows import kids_music_theory as T
from zyg_workflows.tools import measure_style_margins as _mod
from zyg_workflows.tools.measure_style_margins import measure


def main(argv=None):
    ap = argparse.ArgumentParser(description=_mod.__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('styles', nargs='*', help='style keys to measure (default: all of STYLES)')
    ap.add_argument(
        '--require',
        type=float,
        default=None,
        metavar='DB',
        help=f'exit 1 if any style is under DB (the service gate is {S.MIX_MARGIN_MIN_DB})',
    )
    ap.add_argument('--candidates', type=int, default=8)
    ap.add_argument('--seconds', type=float, default=30)
    args = ap.parse_args(argv)

    keys = args.styles or list(T.STYLES)
    unknown = [k for k in keys if k not in T.STYLES]
    if unknown:
        print(f'unknown style(s): {", ".join(unknown)}', file=sys.stderr)
        return 2

    bar = args.require if args.require is not None else S.MIX_MARGIN_MIN_DB
    width = max(len(k) for k in keys)
    worst, failures = None, 0
    for key in keys:
        margin, voices, err = measure(key, candidates=args.candidates, seconds=args.seconds)
        trio = '/'.join(str(voices.get(r) or '?') for r in ('lead', 'pad', 'bass'))
        if margin is None:
            failures += 1
            print(f'{key:<{width}}  {trio}  margin=UNMEASURED ({err})')
            continue
        ok = margin >= bar
        failures += not ok
        worst = margin if worst is None else min(worst, margin)
        print(f'{key:<{width}}  {trio}  margin={margin:+.2f} dB {"ok" if ok else "FAIL"}')

    print(
        f'-- {len(keys)} styles, bar {bar:+.2f} dB, '
        f'worst {("%+.2f dB" % worst) if worst is not None else "n/a"}, '
        f'{failures} under the bar'
    )
    if args.require is not None and failures:
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
