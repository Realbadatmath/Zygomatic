# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_dashboard.expansion_hub.aggregation`, moved out of the library module so that
library code never prints; `python -m zyg_dashboard.expansion_hub.aggregation` still reaches it.
"""

import json
import os
import sys

from zyg_dashboard.expansion_hub.aggregation import _zyg_log, build
from zyg_dashboard.expansion_hub.constants import CACHE_PATH


def main() -> int:
    """The census report that used to live under `if __name__ == '__main__'` in aggregation."""
    fresh = '--fresh' in sys.argv
    if fresh:
        try:
            os.remove(CACHE_PATH)
        except OSError as _exc:
            _zyg_log.debug('no cache to remove for --fresh: %s', _exc)
    p = build(fresh=fresh)
    if '--json' in sys.argv:
        print(json.dumps(p, indent=1, default=str))
    else:
        t = p['totals']
        print(
            f'scan {p["scan"]["total_ms"]} ms (walk {p["scan"]["walk_ms"]} ms, read {p["scan"]["files_read"]}, '
            f'cache {p["scan"]["files_from_cache"]})  version {p["data_version"]}'
        )
        print(
            f'files {t["files"]}  lines {t["lines"]}  bytes {t["bytes"] / 1e6:.1f} MB  dirs {t["dirs"]}  '
            f'components {t["components"]}  services {t["services"]} ({t["services_active"]} active)'
        )
        print(
            f'py {t["py"]}  js {t["js"]}  html {t["html"]}  css {t["css"]}  json {t["json"]}  md {t["md"]}  sh {t["sh"]}  yaml {t["yaml"]}'
        )
        print(
            f'prompts: files {t["prompt_files"]} units {t["prompt_units"]}  in-code literals {t["prompt_literals"]} '
            f'({p["prompts"]["in_code_chars"]} chars in {p["prompts"]["in_code_files"]} files)'
        )
        print(
            f'training: {t["training_datasets"]} datasets, {t["training_files"]} files, {t["training_bytes"] / 1e9:.2f} GB'
        )
        print(
            f'excluded dirs {t["excluded_dirs"]}  skipped files {t["skipped_files"]} ({t["skipped_bytes"] / 1e9:.2f} GB)'
        )
        print('-- by kind')
        for k in p['by_kind']:
            print(f'  {k["kind"]:8s} files {k["files"]:6d} lines {k["lines"]:9d} bytes {k["bytes"] / 1e6:8.1f} MB')
        print('-- components')
        for c in p['components']:
            print(
                f'  {c["label"]:40s} files {c["files"]:6d} lines {c["lines"]:9d} dirs {c["dirs"]:5d} services {len(c["services"])}'
                + ('  MISSING' if c['missing'] else '')
            )
        print('-- top extensions')
        for e in p['by_ext'][:14]:
            print(
                f'  {e["ext"]:14s} files {e["files"]:6d} lines {e["lines"]:9d} median {e["median_lines"]:6d} max {e["max_lines"]:7d} {e["largest"]}'
            )
        print('-- excluded by reason')
        for e in p['excluded']:
            print(f'  {e["count"]:4d}  {e["reason"]}')
        print('-- skipped files by reason')
        for s in p['skipped']:
            print(f'  {s["files"]:7d} {s["bytes"] / 1e9:8.2f} GB  {s["reason"]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
