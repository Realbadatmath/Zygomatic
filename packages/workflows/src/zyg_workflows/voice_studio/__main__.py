# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""voice_studio.__main__ — the operator CLI smoke test.

Moved verbatim from voice_studio.py lines 3027-3047 (2026-10-06 split).
"""

from __future__ import annotations

import json
import time

from zyg_workflows.voice_studio.params import (
    defaults,
)
from zyg_workflows.voice_studio.synthesis import (
    render_chain,
    seed_chain,
)
from zyg_workflows.voice_studio.jobs import (
    job,
    start_render,
)


if __name__ == '__main__':  # pragma: no cover — operator smoke test
    import argparse

    ap = argparse.ArgumentParser(description='Voice Studio — CLI smoke test')
    ap.add_argument('--voice', default='abel')
    ap.add_argument('--text', default='')
    ap.add_argument('--chain-only', action='store_true', help='print the ffmpeg chains for the defaults and exit')
    a = ap.parse_args()
    d = defaults()
    if a.chain_only:
        print('seed  :', ','.join(seed_chain(d)))
        print('render:', ','.join(render_chain(d)))
        raise SystemExit(0)
    jb = start_render(a.voice, a.text, d)
    while True:
        time.sleep(2)
        jb = job(jb['id'])
        if jb.get('state') in ('done', 'error'):
            break
    print(json.dumps({k: jb[k] for k in ('state', 'wav', 'error', 'log', 'metrics')}, indent=2, default=str))
    raise SystemExit(0 if jb['state'] == 'done' else 1)
