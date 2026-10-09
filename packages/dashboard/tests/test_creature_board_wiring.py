#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The creature pipeline's board wiring: cards ↔ API routes ↔ stage names ↔ model registry.

    scripts/run_tests.sh tests/test_creature_board_wiring.py

These two checks came out of ``zygomatic-workflows/tests/test_creature_sheet.py`` in the
2026-10-05 repository split. The work they guard is the GUI's: the kanban card list, the
blueprint's route table, the Live Tail's agent panel and the scheduler's model registry all
live in this package. What they guard it *against* is drift from one name that does not —
``zyg_workflows.creature_training_service.STAGES_ORDER`` — which is exactly why the test has
to sit on this side of the fence: the dashboard may import the library, and the library may
never import the dashboard, so only this repository can see both halves of the contract.
"""

import os
import re

import pytest

import zyg_dashboard
from zyg_workflows import creature_training_service as cts

_PKG = os.path.dirname(os.path.abspath(zyg_dashboard.__file__))


def _src(*parts):
    """A GUI source file in this package, read as text -- or a package directory, read as the
    concatenation of its modules (bp_pipeline_api and kanban_server became packages in the
    2026-10 modularization; every check below is a membership test, so the join is safe)."""
    p = os.path.join(_PKG, *parts)
    if os.path.isdir(p):
        names = sorted(n for n in os.listdir(p) if n.endswith('.py'))
        return '\n'.join(open(os.path.join(p, n), encoding='utf-8').read() for n in names)
    if not os.path.isfile(p):
        pytest.skip('not in this checkout: %s' % p)
    with open(p, encoding='utf-8') as fh:
        return fh.read()


def test_kanban_cards_match_api_and_stages():
    """Every card prompt on the board must be a real stage and a real route.

    The board drives the pipeline by posting the prompt string on the card, so a card whose
    prompt no longer matches ``STAGES_ORDER`` is a button that silently does nothing.
    """
    js = _src('kanban_assets', 'kanban_main.js')
    blk = js[js.index('creature_creation: {') : js.index('// end creature_creation')]
    prompts = re.findall(r"prompt:\s*'([^']+)'", blk)
    assert prompts == list(cts.STAGES_ORDER), prompts
    api = _src('bp_pipeline_api')
    for p in prompts:
        assert f"'{p}'" in api, p
    assert '/api/internal/creature/<creature_id>/approve' in api
    assert '/api/internal/creature/<creature_id>/reject' in api
    assert "creature_options=data.get('creature_options')" in api

    html = _src('kanban.html')
    # The Live Tail's agent-session panel (2026-08-30) — skull badge next to the Test
    # button, its subtab row and the per-session pane the subtabs open.
    for _id in ('lt-agents-btn', 'lt-agents-count', 'lt-agent-rail', 'lt-pane-agents'):
        assert _id in html, _id
    # The rail is docked OUTSIDE #lt-panel (which is overflow:hidden), so it has to live
    # at body level and be positioned in JS against the panel's rect.
    assert html.index('lt-agent-rail') > html.index('id="lt-panel"'), (
        'the agent rail must sit outside #lt-panel or it is clipped away'
    )
    # kanban_main.js is cache-busted with a version query so a browser reloads it after a
    # change. The number is bumped by hand with the file; what has to hold is that it is
    # there at all, not which revision this checkout happens to be at.
    assert re.search(r'kanban_main\.js\?v=\d+', html), 'kanban_main.js is loaded without a cache-busting version'

    lt = _src('kanban_assets', 'kanban_livetail.js')
    for _fn in ('pollAgents', 'ltToggleAgents', 'ltSelectAgent', 'renderAgentPane', '_ltPositionAgentRail'):
        assert f'function {_fn}(' in lt, _fn
    srv = _src('kanban_server')
    assert "'/kanban/api/agents'" in srv
    assert "'/kanban/api/agents/tail'" in srv


def test_schedule_and_registry():
    """Every model the creature stages name must exist in the registry they are picked from."""
    from zyg_dashboard import schedule_service as ss

    assert ss._PIPELINE_FALLBACK_MODEL['creature'][0] == 'qwen-image-edit-2509'
    assert not any(slug == 'flux-1-dev' for _, slug, _ in ss._STAGE_MODEL_RULES['creature'])
    # data/models.json is operator state, not packaged source — no file in this repository
    # tracks it — so a bare checkout has an empty registry and nothing to compare against.
    if not os.path.isfile(ss._MODELS_JSON):
        pytest.skip('not in this checkout: %s' % ss._MODELS_JSON)
    reg = ss.model_registry('gpu', include_deprecated=True)
    slugs = {m['slug'] for m in reg.values()}
    for _, slug, _dev in ss._STAGE_MODEL_RULES['creature']:
        assert slug in slugs, slug
