# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.geom.body_metrics`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.geom.body_metrics` still reaches it.
"""

from __future__ import annotations

import argparse
import json
import sys

from zyg_workflows.geom.body_metrics import measure


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog='python -m zyg_workflows.geom.body_metrics')
    ap.add_argument('char_id')
    ap.add_argument('--image', help='measure this cell instead of auto-selecting one')
    ap.add_argument('--out', help='write the json here instead of body_metrics.json')
    a = ap.parse_args(argv)
    try:
        res = measure(a.char_id, image=a.image)
    except (FileNotFoundError, ValueError) as e:
        print('body_metrics: %s' % e, file=sys.stderr)
        return 2
    if a.out:
        with open(a.out, 'w', encoding='utf-8') as fh:
            json.dump({k: v for k, v in res.items() if k != 'path'}, fh, indent=2)
            fh.write('\n')
        res['path'] = a.out
    print(json.dumps(res, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
