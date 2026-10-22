# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.asset_validate`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.asset_validate` still reaches it.

The `log_fn=lambda m: print(m)` sink that made the library module whole-file T201-exempt
moved with `_cli`.
"""

import sys

from zyg_workflows.asset_validate import (
    MAX_BOWL_FRAC,
    MAX_DARK_RING_FRAC,
    MIN_ELONGATION,
    _zyg_log,
    validate_prop_ref,
)


def _cli(argv):
    import argparse
    import json

    ap = argparse.ArgumentParser(description='Preflight geometry gate for prop reference assets.')
    ap.add_argument('images', nargs='+')
    ap.add_argument('--min-elong', type=float, default=MIN_ELONGATION)
    ap.add_argument('--max-bowl', type=float, default=MAX_BOWL_FRAC)
    ap.add_argument('--max-dark', type=float, default=MAX_DARK_RING_FRAC)
    ap.add_argument('--no-backdrop', action='store_true', help='skip the flat-backdrop requirement')
    ap.add_argument('--json', action='store_true')
    a = ap.parse_args(argv)

    results = []
    worst = 0
    for p in a.images:
        r = validate_prop_ref(
            p,
            min_elong=a.min_elong,
            max_bowl_frac=a.max_bowl,
            max_dark_ring=a.max_dark,
            require_flat_backdrop=not a.no_backdrop,
            log_fn=None if a.json else (lambda m: print(m)),
        )
        results.append(r)
        if not r['ok']:
            worst = 1
        if not a.json:
            m = r['metrics']
            _zyg_log.info(f'  {p}')
            _zyg_log.info(f'    elongation      {m["elongation"]}   (need >= {a.min_elong})')
            _zyg_log.info(f'    bowl_frac       {m["bowl_frac"]}   (need <= {a.max_bowl})')
            _zyg_log.info(
                f'    backdrop_flat   {m["backdrop_flat"]}  '
                f'(std {m.get("backdrop_std")}, corner range {m.get("backdrop_corner_range")})'
            )
            _zyg_log.info(f'    dark_ring_frac  {m["dark_ring_frac"]}   (need <= {a.max_dark})')
            _zyg_log.info(f'    -> {"PASS" if r["ok"] else "FAIL"}')
            for why in r['reasons']:
                _zyg_log.info(f'       - {why}')
    if a.json:
        _zyg_log.info(json.dumps(results if len(results) > 1 else results[0], indent=2))
    return worst


def main() -> int:
    """The `if __name__ == '__main__'` block asset_validate used to carry."""
    return _cli(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
