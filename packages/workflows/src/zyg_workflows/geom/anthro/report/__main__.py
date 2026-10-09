# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.geom.anthro.report` — the entry point the old report.py
carried as its `if __name__ == '__main__'` block.
"""

from zyg_workflows.geom.anthro.report import build, contract_fixture, render_text, _selftest

if __name__ == '__main__':
    print(_selftest())
    print()
    print(render_text(build(contract_fixture(), None, name='fixture', sex='male')))
