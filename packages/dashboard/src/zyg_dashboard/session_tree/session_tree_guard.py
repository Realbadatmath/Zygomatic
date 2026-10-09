#!/usr/bin/python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""PreToolUse hook: agents may not open Session Tree data files directly.
Exit 2 = block the tool call and show the message to the agent."""

import json
import re
import sys

try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
ti = d.get('tool_input') or {}
blob = ' '.join(str(ti.get(k, '')) for k in ('command', 'file_path', 'path', 'pattern', 'glob', 'notebook_path'))
if re.search(r'session_tree/data(/|\b)', blob):
    sys.stderr.write(
        "BLOCKED by Session Tree rule 5: the board's data files are read only through the `st` CLI "
        '(st status / st claim). Finished trees are never read by agents.\n'
    )
    sys.exit(2)
sys.exit(0)
