# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.tools_arch_screenshot`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.tools_arch_screenshot` still reaches it.
"""

import argparse
import json
import sys

from zyg_workflows.tools_arch_screenshot import __doc__ as _LIB_DOC
from zyg_workflows.tools_arch_screenshot import (
    URL,
    VIEWS,
    shoot,
)


def main(argv=None):
    ap = argparse.ArgumentParser(description=_LIB_DOC.splitlines()[0])
    ap.add_argument('--project', default='', help='saved drawing id, e.g. heath-landscape-demo')
    ap.add_argument('--doc', default='', help='path to a document JSON to inject instead')
    ap.add_argument('--view', default='eye', choices=list(VIEWS))
    ap.add_argument('--out', required=True, help='PNG to write')
    ap.add_argument('--width', type=int, default=1600)
    ap.add_argument('--height', type=int, default=1000)
    ap.add_argument('--url', default=URL)
    ap.add_argument('--timeout', type=int, default=180)
    a = ap.parse_args(argv)
    doc = None
    if a.doc:
        with open(a.doc, 'r', encoding='utf-8') as fh:
            doc = json.load(fh)
        doc = doc.get('doc') if isinstance(doc, dict) and 'doc' in doc else doc
    try:
        info = shoot(
            a.out,
            project=a.project,
            doc=doc,
            view=a.view,
            width=a.width,
            height=a.height,
            url=a.url,
            timeout_s=a.timeout,
        )
    except Exception as e:
        print('ARCH_SHOT_FAIL %s: %s' % (type(e).__name__, e))
        return 1
    return 0 if info.get('bytes', 0) > 0 else 1


if __name__ == '__main__':
    sys.exit(main())
