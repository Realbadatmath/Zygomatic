# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools.farmyard_stretch`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools.farmyard_stretch` still reaches it.
"""

import argparse
import sys

from zyg_workflows.tools.farmyard_stretch import __doc__ as _LIB_DOC
from zyg_workflows.tools.farmyard_stretch import build


def main(argv=None):
    ap = argparse.ArgumentParser(description=_LIB_DOC.split('\n')[0])
    ap.add_argument(
        '--measure-only', action='store_true', help='do not re-render, just re-measure and rewrite the index'
    )
    a = ap.parse_args(argv)
    index = build(measure_only=a.measure_only)
    bad = [r for r in index['takes'] if not r['ok']]
    print(
        '\n%d takes, %d bad%s'
        % (len(index['takes']), len(bad), (': ' + ', '.join(r['key'] for r in bad)) if bad else '')
    )
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
