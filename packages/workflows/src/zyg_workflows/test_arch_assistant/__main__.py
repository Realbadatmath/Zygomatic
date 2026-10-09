# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Command-line entry point — `python -m zyg_workflows.test_arch_assistant`."""

from zyg_workflows import arch_assistant as A
import sys
from zyg_workflows.test_arch_assistant.drawer import FAILS, test_drawer
from zyg_workflows.test_arch_assistant.tab import test_tab
from zyg_workflows.test_arch_assistant.cli import test_cli, test_cli_events
from zyg_workflows.test_arch_assistant.ledger import test_assets_materials, test_ledger, test_partials
from zyg_workflows.test_arch_assistant.thinkless import test_live, test_thinkless

if __name__ == '__main__':
    canned = None
    d = A.Drawing({'objects': []})
    A.call_tool(d, 'draw_box', {'cell_from': 'C4', 'cell_to': 'L13', 'storeys': 20, 'roof': 'flat'})
    A.call_tool(d, 'add_windows', {'walls': 'new', 'every_n_storeys': 2, 'material': 'mat_glass'})
    canned = d.to_doc()
    test_drawer()
    test_tab(canned)
    test_cli()
    test_cli_events()
    test_ledger()
    test_partials()
    test_assets_materials()
    test_thinkless()
    if '--live' in sys.argv:
        test_live()
    print(('\nALL GREEN' if not FAILS else f'\n{len(FAILS)} FAILED: ' + ', '.join(FAILS)))
    sys.exit(1 if FAILS else 0)
