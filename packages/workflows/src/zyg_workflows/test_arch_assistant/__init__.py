# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# ruff: noqa: E402,F401

"""test_arch_assistant.py — the drawing assistant, the cell labels, the ring.

    venv/bin/python test_arch_assistant.py          (needs :8899 up)

Three layers, each of which can be right while the others are wrong:

  · THE DRAWER (Python, no model): a 10x10-cell box, 100 storeys, glass every
    second storey — counts, storeys, and every window projecting INTO its wall
    by the client's own arSyncHoles rule. Cells parse and print round-trip.
  · THE TAB (headless Chrome, SwiftShader): Shift+R paints labels (the texture
    is not blank, Room did NOT arm), the three new dock icons rasterise to
    three different, non-blank pictures, the ring shows the two phase texts,
    a canned result injects as ONE undo step and Ctrl+Z takes all of it back,
    the sun's shadow frustum grew to the tower, the ghost preview keeps and
    discards.
  · THE ROUND TRIP (mocked server): the panel posts a start, polls, answers
    a `look` with a picture, and injects the done result — the whole client
    state machine without spending a token.

The live model is NOT exercised here; that costs money and is a judgement
call, not a regression. test_cli covers the Claude Code CLI backend offline
(2026-09-07). `--live` runs one small request against the real
server and prints what came back.
"""

import json
import math
import sys
import time
from zyg_workflows import paths

sys.path.insert(0, __file__.rsplit('/', 2)[0])
from zyg_workflows import arch_assistant as A

from zyg_workflows.test_arch_assistant.drawer import URL, FIXTURE_TOKEN, FAILS, check, test_drawer
from zyg_workflows.test_arch_assistant.tab import SCRIPT, test_tab
from zyg_workflows.test_arch_assistant.cli import test_cli, test_cli_events
from zyg_workflows.test_arch_assistant.ledger import test_ledger, test_partials, test_assets_materials
from zyg_workflows.test_arch_assistant.thinkless import test_thinkless, test_live
