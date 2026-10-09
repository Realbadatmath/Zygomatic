# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""`python -m zyg_workflows.update_agent_model_mapping` — the entry point the old
update_agent_model_mapping.py carried as its `if __name__ == '__main__'` block
(lines 1063-1064).
"""

from zyg_workflows.update_agent_model_mapping.mapping import update_agent_mapping


if __name__ == '__main__':
    update_agent_mapping()
