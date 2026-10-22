# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.pipeline_runtime`, moved out of the library module
so that library code never prints; `python -m zyg_workflows.pipeline_runtime` still
reaches it.
"""

import json
import sys

from zyg_workflows.pipeline_runtime import compute_runtime, format_runtime


def main() -> int:  # pragma: no cover - manual inspection helper
    for path in sys.argv[1:]:
        with open(path, encoding='utf-8') as fh:
            data = json.load(fh)
        res = compute_runtime(data)
        print(f'{path}')
        print(f'  status   : {data.get("status")}')
        print(f'  started  : {data.get("started")}')
        print(f'  as_of    : {res["runtime_as_of"]}  (running={res["runtime_running"]})')
        print(
            f'  runtime  : {format_runtime(res["runtime_seconds"])}'
            f'   [wall {format_runtime(res["runtime_wall_seconds"])}]'
        )
        for gap in res['runtime_gaps']:
            print(
                f'  ⏸ paused : {format_runtime(gap["seconds"]):>12}  '
                f'{gap["from"][11:19]} → {gap["to"][11:19]}  ({gap["reason"]})'
            )
    return 0


if __name__ == '__main__':
    sys.exit(main())
