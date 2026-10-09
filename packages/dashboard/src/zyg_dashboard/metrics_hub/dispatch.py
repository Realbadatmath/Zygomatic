# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The section dispatcher and the hot-reloaded sibling hubs."""

from __future__ import annotations

import json
import os
import sys
import time

from .constants import CREWS
from .helpers import _iso, _memo, _req_arg
from .llm import _quota_meter, section_llm
from .pipelines import section_pipelines
from .characters import section_characters
from .quality_section import section_quality
from .system import section_system
from .overview import section_agents, section_overview

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# ── dispatch ─────────────────────────────────────────────────────────────────

SECTIONS = (
    'overview',
    'pipelines',
    'characters',
    'llm',
    'quality',
    'system',
    'agents',
    'quota',
    'analytics',
    'test_data',
    'capabilities',
    'stack_lineage',
    'expansion',
    'zero',
)


_ANALYTICS_MOD = {'mod': None, 'mtime': 0.0}


def _analytics_mod():
    """analytics_hub, re-imported when its file changes (the same hot-reload rule as quota_meter)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _ANALYTICS_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_dashboard import analytics_hub as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _ANALYTICS_MOD['mod'] is not None and mtime != _ANALYTICS_MOD['mtime']:
            mod = maybe_reload(mod)
        _ANALYTICS_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] analytics_hub reload failed, keeping loaded module: {exc}')
    return mod


def section_analytics(days=30, now=None, fresh=False):
    """Metrics > Analytics (2026-09-18): the kanban of analytic cards, see analytics_hub.py.
    Inside a request, `?set=<json>` updates the stated assumptions before the build — the
    hot path that works without a GUI restart; POST /api/metrics/analytics/config is the
    proper route once the GUI has restarted."""
    mod = _analytics_mod()
    try:
        from flask import has_request_context, request
    except ImportError:  # CLI under /usr/bin/python3: no request, nothing to set
        has_request_context = None
    if has_request_context:
        try:
            if has_request_context() and request.args.get('set'):
                mod.save_config(json.loads(request.args.get('set')))
        except Exception as exc:  # noqa: BLE001
            _zyg_log.info(f'[METRICS-HUB] analytics config update failed: {exc}')
    return mod.section_analytics(days, now, fresh=fresh)


_TESTDATA_MOD = {'mod': None, 'mtime': 0.0}


def _testdata_mod():
    """test_data_hub, re-imported when its file changes (the same hot-reload rule as analytics_hub)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _TESTDATA_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_dashboard import test_data_hub as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _TESTDATA_MOD['mod'] is not None and mtime != _TESTDATA_MOD['mtime']:
            mod = maybe_reload(mod)
        _TESTDATA_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] test_data_hub reload failed, keeping loaded module: {exc}')
    return mod


def section_test_data(days=30, now=None, fresh=False):
    """Metrics > Test Data (2026-09-22): one kanban card per test that was performed, each
    with its own graph; see test_data_hub.py for the store and the record schema."""
    return _testdata_mod().section_test_data(days, now, fresh=fresh)


_CAPABILITIES_MOD = {'mod': None, 'mtime': 0.0}


def _capabilities_mod():
    """capabilities_hub, re-imported when its file changes (the same hot-reload rule as test_data_hub)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _CAPABILITIES_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_dashboard import capabilities_hub as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _CAPABILITIES_MOD['mod'] is not None and mtime != _CAPABILITIES_MOD['mtime']:
            mod = maybe_reload(mod)
        _CAPABILITIES_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] capabilities_hub reload failed, keeping loaded module: {exc}')
    return mod


def section_capabilities(days=30, now=None, fresh=False):
    """Metrics > Capabilities (2026-09-27): one sheet per workflow step — rows are the
    models/tools in that step, columns are what a test asked of them. `?inspect=<step>`
    and `?asset=<id>` ride this same endpoint; see capabilities_hub.py."""
    return _capabilities_mod().section_capabilities(days, now, fresh=fresh)


_LINEAGE_MOD = {'mod': None, 'mtime': 0.0}


def _lineage_mod():
    """stack_lineage_hub, re-imported when its file changes (the same hot-reload rule as capabilities_hub)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _LINEAGE_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_workflows import stack_lineage_hub as mod
    try:
        mtime = os.path.getmtime(mod.__file__)
        if _LINEAGE_MOD['mod'] is not None and mtime != _LINEAGE_MOD['mtime']:
            mod = maybe_reload(mod)
        _LINEAGE_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] stack_lineage_hub reload failed, keeping loaded module: {exc}')
    return mod


def section_stack_lineage(days=30, now=None, fresh=False):
    """Metrics > Lineage (2026-10-04): one card per model/tool — what it was for, what went
    wrong with it, what the replacement fixed, and what is still wrong. The store is
    data/stack_lineage/*.json, the dated chart is docs/stack_upgrade_history.md; see
    stack_lineage_hub.py. `days` is ignored on purpose: a lineage is not a window."""
    return _lineage_mod().section_stack_lineage(days, now, fresh=fresh)


_EXPANSION_MOD = {'mod': None, 'mtime': 0.0}


def _expansion_mod():
    """expansion_hub, re-imported when its file changes (the same hot-reload rule as stack_lineage_hub)."""
    from zyg_workflows.devreload import maybe_reload

    mod = _EXPANSION_MOD['mod']
    if mod is None:
        sys.path.insert(0, CREWS) if CREWS not in sys.path else None
        from zyg_dashboard import expansion_hub as mod
    try:
        # expansion_hub is a package: the trigger is the newest of its modules, because
        # editing a submodule leaves the __init__.py its __file__ names untouched.
        pkg_dir = os.path.dirname(mod.__file__)
        mtime = max(
            os.path.getmtime(os.path.join(pkg_dir, name)) for name in os.listdir(pkg_dir) if name.endswith('.py')
        )
        if _EXPANSION_MOD['mod'] is not None and mtime != _EXPANSION_MOD['mtime']:
            mod = maybe_reload(mod)
        _EXPANSION_MOD.update(mod=mod, mtime=mtime)
    except Exception as exc:  # noqa: BLE001
        _zyg_log.info(f'[METRICS-HUB] expansion_hub reload failed, keeping loaded module: {exc}')
    return mod


def section_expansion(days=30, now=None, fresh=False):
    """Metrics > Expansion (2026-10-04): the census of the program's own structural files —
    folders, files per kind/extension, lines and bytes per file, Python structure, the
    systemd units per component, prompt files + prompt literals in code, and the training
    data generation is conditioned on. Generated content is excluded and the exclusions
    are listed; see expansion_hub.py. `days` is ignored: a census is what is on disk now."""
    return _expansion_mod().section_expansion(days, now, fresh=fresh)


def section_quota(days=7, now=None, fresh=False):
    """The Claude subscription meter and the two costs (see quota_meter.py for the method).
    `days` is the transcript range for the daily chart; the weekly window is Claude's."""
    return _quota_meter().report(days=days, now=now, fresh=fresh)


def section_zero(days=30, now=None, fresh=False):
    """Metrics > Agent Zero (2026-10-08): every number Agent Zero v2 produces -- turns,
    tokens, API-equivalent dollars, latency, tools, budget verdicts, installs. The ledger
    is data/runtime/zero_metrics.jsonl, one line per finished turn; the payload shape is
    CONTRACT F in agent_zero/metrics.py, which owns the whole reduction."""
    from zyg_dashboard.agent_zero import metrics as _zm

    return _zm.section_zero(days=days, now=now, fresh=fresh)


def section(name, days=30, telemetry=None, fresh=False):
    if name not in SECTIONS:
        raise KeyError(name)
    t0 = time.time()

    def build():
        now = time.time()
        if name == 'overview':
            return section_overview(days, now, telemetry, fresh=fresh)
        if name == 'system':
            return section_system(days, now, telemetry)
        if name == 'quota':
            return section_quota(days, now, fresh=fresh)
        if name == 'analytics':
            return section_analytics(days, now, fresh=fresh)
        if name == 'test_data':
            return section_test_data(days, now, fresh=fresh)
        if name == 'capabilities':
            return section_capabilities(days, now, fresh=fresh)
        if name == 'stack_lineage':
            return section_stack_lineage(days, now, fresh=fresh)
        if name == 'expansion':
            return section_expansion(days, now, fresh=fresh)
        if name == 'zero':
            return section_zero(days, now, fresh=fresh)
        return {
            'pipelines': section_pipelines,
            'characters': section_characters,
            'llm': section_llm,
            'quality': section_quality,
            'agents': section_agents,
        }[name](days, now)

    # `capabilities` is never memoised: the same endpoint answers ?asset= and ?inspect=,
    # so a cached board payload would be served for an asset request.
    if name == 'capabilities' or (name == 'quality' and _req_arg('detail')):
        data = build()
    else:
        data = _memo(
            (name, days),
            8 if name in ('system', 'overview', 'analytics', 'test_data', 'zero') else 20,
            build,
            fresh=fresh,
        )
    return dict(
        data,
        section=name,
        window_days=days,
        generated_at=_iso(time.time()),
        compute_ms=round((time.time() - t0) * 1000),
    )
