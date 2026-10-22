# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.build_all_libraries`, moved out of the library module so that
library code never prints; `python -m zyg_workflows.build_all_libraries` still reaches it.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import os
import sys

from zyg_workflows.build_all_libraries import (
    HERE,
    blend_path,
    build_one,
    newest,
)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--plan', action='store_true')
    ap.add_argument('--force', action='store_true')
    ap.add_argument('--pack', action='append', help='build only these (repeatable)')
    ap.add_argument('--jobs', type=int, default=4, help='concurrent blender processes')
    ap.add_argument('--timeout', type=int, default=3600)
    a = ap.parse_args()

    sys.path.insert(0, HERE)
    from zyg_workflows import architecture_assets as aa

    cat = aa.catalogue()
    packs = [(p['id'], p['licence'], p['count']) for p in cat['packs']]
    if a.pack:
        want = set(a.pack)
        packs = [p for p in packs if p[0] in want]

    todo, fresh = [], []
    for pid, lic, n in packs:
        out = blend_path(pid)
        src = newest(pid)
        cur = os.path.getmtime(out) if os.path.isfile(out) else 0.0
        (fresh if (cur >= src and not a.force) else todo).append((pid, lic, n))

    print(f'{len(packs)} packs: {len(todo)} to build, {len(fresh)} already current')
    for pid, _lic, n in todo:
        print(f'  build {pid} ({n} items)')
    if a.plan:
        return

    ok, bad = [], []
    with cf.ThreadPoolExecutor(max(1, a.jobs)) as ex:
        futs = {ex.submit(build_one, pid, lic, a.timeout): pid for pid, lic, _n in todo}
        for i, f in enumerate(cf.as_completed(futs), 1):
            r = f.result()
            if r.get('error'):
                bad.append(r)
                print(f'  [{i}/{len(todo)}] FAIL {r["pack"]}: {r["error"]} {r.get("tail", "")}', flush=True)
            else:
                ok.append(r)
                print(
                    f'  [{i}/{len(todo)}] {r["pack"]}: {r["assets"]} assets, '
                    f'{r["previews"]} previews, {r["skipped"]} skipped, '
                    f'{r["secs"]}s',
                    flush=True,
                )

    print(f'\nbuilt {len(ok)}, failed {len(bad)}, {sum(r["assets"] for r in ok)} assets marked')
    if bad:
        print('FAILED: ' + ', '.join(r['pack'] for r in bad))
        sys.exit(1)


if __name__ == '__main__':
    main()
