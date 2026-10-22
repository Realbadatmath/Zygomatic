# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command line of `zyg_workflows.pipeline_dsl_adapter`, moved out of the library
module so that library code never prints; `python -m zyg_workflows.pipeline_dsl_adapter`
still reaches it.
"""

import sys

from zyg_workflows.pipeline_dsl_adapter import (
    _CAVEMAN_AVAILABLE,
    _DSL_AVAILABLE,
    _allowed_pipelines,
    _master_dsl_on,
    status_summary,
)


def main() -> int:
    print('pipeline_dsl_adapter — status')
    print(f'  CAVEMAN module loaded:   {_CAVEMAN_AVAILABLE}')
    print(f'  DSL modules loaded:      {_DSL_AVAILABLE}')
    print(f'  Master switch:           {_master_dsl_on()}')
    print(f'  Allowed pipelines:       {_allowed_pipelines() or "all"}')
    for p in ('documentary', 'video', 'storyteller', 'character'):
        print(f'  {p:<14} → {status_summary(p)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
