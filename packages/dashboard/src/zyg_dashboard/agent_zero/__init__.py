# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Agent Zero v2 -- the operator's single chat agent over the whole program.

Agent Zero is the one place a person talks to Zygomatic. v1 (``bp_zero.py`` plus
``static/js/dashboard_agent_zero.js``) was a chat box fronted by a row of preset
buttons: each button ran a fixed prompt against a fixed model, so the agent could
only do what somebody had already wired a button for. v2 replaces that with a real
agent: the operator picks the brain (the Claude Code subscription, any hosted API,
or a local Ollama model), Agent Zero gets tools over the dashboard itself, and the
conversation -- not a preset -- decides what happens.

The package is self-contained on purpose: the same source runs in this monorepo and in
the pre-monorepo tree it was written in, where the dashboard modules are bare top-level
names instead of packages. Everything it borrows from the host goes through
:mod:`agent_zero._host` (CONTRACT A), and the shapes its parts agree on live in
:mod:`agent_zero.contracts` (CONTRACT C).

Layout::

    _host.py        the only seam to the live dashboard
    contracts.py    TurnContext, the event protocol, the provider table
    models.py       model registry: catalogue, fit, status, Ollama installs, selection
    routes_*.py     Flask routes, registered on the ``bp`` blueprint below
    backends/       one module per provider family, all speaking the event protocol

Importing this package must stay cheap and side-effect free: it may not import the
dashboard (``crewai_web_gui``), touch the GPU, or start a thread.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging

from flask import Blueprint

_log = logging.getLogger(__name__)

__all__ = ['bp']

#: The blueprint every ``routes_*`` module hangs its routes on. The host registers it.
bp = Blueprint('zero_v2', __name__)

#: Route modules, imported in order. Each one does ``from . import bp``. All four ship
#: with the package; the ``find_spec`` guard below only keeps a partially-synced checkout
#: importable. A module that exists and raises is NOT swallowed: an import error there is
#: a bug, not a feature.
_ROUTE_MODULES = ('routes_models', 'routes_chat', 'routes_mcp', 'routes_budget')

for _name in _ROUTE_MODULES:
    if importlib.util.find_spec(f'{__name__}.{_name}') is None:
        _log.debug('agent_zero: route module %s not present yet', _name)
        continue
    importlib.import_module(f'{__name__}.{_name}')
