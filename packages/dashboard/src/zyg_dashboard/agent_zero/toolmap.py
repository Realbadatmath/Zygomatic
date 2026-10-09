# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The tool map: the short route to every program and function, inside a token budget.

Agent Zero v2 is given exactly three tools -- ``zero_index``, ``zero_find`` and
``zero_call`` -- and never a list of two hundred endpoints. This module is the map
those three meta-tools read:

* ``toolmap.json`` is the curated half: a hand-written, grouped index of the
  dashboard routes, sibling services and read-only code/doc lookups that are worth a
  model's attention, each with a title, a one-line description, its parameters and a
  risk class (read / act / danger).
* the live application's ``url_map`` is the automatic half: every ``/api/`` rule the
  curated map does not mention becomes an ``auto.<endpoint>`` tool. Auto tools are
  reachable through :func:`find` and :func:`get` but never appear in the index -- they
  are the long tail, found on demand, not advertised.

The automatic half is merged **only when the host module is already imported in this
process**. Importing the dashboard starts its watcher threads, and a CLI or a test
that merely asks for the index must never pay that price (or race the live server), so
``sys.modules`` is consulted instead of calling into the importer.

Budgets are the point of this module: :func:`index_text` renders the whole program in
~1200 estimated tokens, :func:`group_text` opens one group in ~800, and anything else
is a search away.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
import threading

from typing import Any

from . import _host
from .contracts import estimate_tokens

_log = logging.getLogger(__name__)

#: The curated map lives next to this module and is reloaded when its mtime changes.
MAP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'toolmap.json')

#: The route inventory ``apitests/routes.json``, which says which rules are dangerous and
#: which gate gets each one. It sits beside the dashboard's ``tests/``, i.e. four
#: ``dirname`` hops up from this module here
#: (``packages/dashboard/src/zyg_dashboard/agent_zero/`` -> ``packages/dashboard``); the
#: flatter pre-monorepo tree reached the same directory in two. A missing file is not an
#: error -- both readers degrade to "nothing flagged" -- which is exactly why the path is
#: named once here instead of being rebuilt at each call site: a wrong anchor would fail
#: silently and quietly downgrade every dangerous route to ``act``.
ROUTES_JSON = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    'apitests',
    'routes.json',
)

#: Host modules whose presence in ``sys.modules`` means the Flask app is already loaded.
_HOST_MODULES = ('crewai_web_gui', 'zyg_dashboard.crewai_web_gui')

#: Methods that carry no request body (and therefore cannot change state by themselves).
_READ_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

_RISKS = ('read', 'act', 'danger')

_lock = threading.Lock()
_cache: dict = {'mtime': 0.0, 'map': None, 'auto': None, 'auto_rules': 0}

_WORD_RE = re.compile(r'[a-z0-9_]+')
_PLACEHOLDER_RE = re.compile(r'\{([a-zA-Z_][a-zA-Z_0-9]*)\}')
_CONVERTER_RE = re.compile(r'<[^>]+>')


# ── the curated map ──────────────────────────────────────────────────────────


def _load_curated() -> dict:
    """Parse ``toolmap.json``, caching it until the file's mtime changes."""
    with _lock:
        try:
            mtime = os.path.getmtime(MAP_PATH)
        except OSError:
            mtime = 0.0
        if _cache['map'] is not None and mtime == _cache['mtime']:
            return _cache['map']
        with open(MAP_PATH, encoding='utf-8') as fh:
            raw = json.load(fh)
        groups = []
        for group in raw.get('groups', []):
            tools = [_normalise(tool, group['id']) for tool in group.get('tools', [])]
            groups.append({'id': group['id'], 'label': group.get('label', group['id']), 'tools': tools})
        parsed = {
            'version': raw.get('version', 0),
            'groups': groups,
            'by_id': {tool['id']: tool for group in groups for tool in group['tools']},
        }
        _cache.update(mtime=mtime, map=parsed, auto=None, auto_rules=0)
        return parsed


def _normalise(tool: dict, group_id: str) -> dict:
    """Fill the fields every consumer may rely on, and mark path params required."""
    out = dict(tool)
    out['group'] = group_id
    out.setdefault('kind', 'http')
    out.setdefault('risk', 'read')
    out.setdefault('desc', '')
    out.setdefault('title', out['id'])
    params = {}
    for name, spec in (out.get('params') or {}).items():
        spec_d: dict[str, Any] = dict(spec) if isinstance(spec, dict) else {'desc': str(spec)}
        spec_d.setdefault('required', False)
        spec_d.setdefault('desc', '')
        params[name] = spec_d
    for name in _PLACEHOLDER_RE.findall(out.get('path') or out.get('url') or ''):
        params.setdefault(name, {'required': True, 'desc': 'path parameter'})
        params[name]['required'] = True
    out['params'] = params
    out['curated'] = True
    if out['risk'] not in _RISKS:
        _log.warning('toolmap: tool %s has unknown risk %r, treating as danger', out['id'], out['risk'])
        out['risk'] = 'danger'
    return out


# ── the automatic half: the live url_map ─────────────────────────────────────


def _host_app_loaded():
    """The Flask app, but only if the host module is already in ``sys.modules``.

    Never triggers the import: see the module docstring.
    """
    if not any(name in sys.modules for name in _HOST_MODULES):
        return None
    try:
        return _host.app()
    except Exception as exc:  # noqa: BLE001 - a broken host is a missing host here
        _log.warning('toolmap: host app unavailable (%s)', exc)
        return None


def _inventory_danger() -> set:
    """``(normalised rule, method)`` pairs the route inventory flags as dangerous."""
    path = ROUTES_JSON
    try:
        with open(path, encoding='utf-8') as fh:
            raw = json.load(fh)
    except (OSError, ValueError):
        return set()
    out = set()
    for rows in (raw.get('apps') or {}).values():
        for row in rows:
            if row.get('danger'):
                for method in row.get('methods') or []:
                    out.add((normalise_path(row.get('rule', '')), method))
    return out


def _auto_tools() -> list:
    """Every ``/api/`` rule of the live url_map that the curated map does not cover."""
    curated = _load_curated()
    app = _host_app_loaded()
    if app is None:
        return []
    with _lock:
        rules = list(app.url_map.iter_rules())
        if _cache['auto'] is not None and _cache['auto_rules'] == len(rules):
            return _cache['auto']
        covered = {
            (normalise_path(tool['path']), method)
            for tool in curated['by_id'].values()
            if tool['kind'] == 'http'
            for method in (tool.get('method', 'GET'),)
        }
        danger = _inventory_danger()
        out, seen = [], set()
        for rule in rules:
            path = str(rule.rule)
            if not path.startswith('/api/'):
                continue
            methods = sorted(m for m in (rule.methods or ()) if m not in ('HEAD', 'OPTIONS'))
            for method in methods:
                key = (normalise_path(path), method)
                if key in covered:
                    continue
                suffix = '' if len(methods) == 1 else '.' + method.lower()
                tool_id = f'auto.{rule.endpoint}{suffix}'
                if tool_id in seen or tool_id in curated['by_id']:
                    continue
                seen.add(tool_id)
                if key in danger:
                    risk = 'danger'
                elif method in _READ_METHODS:
                    risk = 'read'
                else:
                    risk = 'act'
                out.append(
                    {
                        'id': tool_id,
                        'title': rule.endpoint,
                        'kind': 'http',
                        'method': method,
                        'path': _flask_to_braces(path),
                        'risk': risk,
                        'gate': _gate_of(path, method),
                        'params': {name: {'required': True, 'desc': 'path parameter'} for name in rule.arguments or ()},
                        'desc': f'uncurated dashboard route ({rule.endpoint})',
                        'group': 'auto',
                        'curated': False,
                    }
                )
        _cache.update(auto=out, auto_rules=len(rules))
        return out


_GATES: dict = {'rows': None}


def _gate_of(path: str, method: str) -> str:
    """The gate the route inventory recorded for a rule (``login`` / ``localhost`` / ...)."""
    if _GATES['rows'] is None:
        inv = ROUTES_JSON
        rows = {}
        try:
            with open(inv, encoding='utf-8') as fh:
                raw = json.load(fh)
            for row in (raw.get('apps') or {}).get('dashboard', []):
                for mth in row.get('methods') or []:
                    rows[(normalise_path(row.get('rule', '')), mth)] = row.get('gate') or ''
        except (OSError, ValueError):
            rows = {}
        _GATES['rows'] = rows
    return _GATES['rows'].get((normalise_path(path), method), '')


def normalise_path(path: str) -> str:
    """A converter-agnostic form of a route path, so the two inventories compare.

    ``/api/agents/config/<path:agent_name>`` and ``/api/agents/config/{agent_name}``
    both become ``/api/agents/config/<>``.
    """
    return _PLACEHOLDER_RE.sub('<>', _CONVERTER_RE.sub('<>', path or ''))


def _flask_to_braces(path: str) -> str:
    """``/api/x/<int:pid>`` -> ``/api/x/{pid}`` (the form the tool map uses)."""
    return re.sub(r'<(?:[^:<>]+:)?([^<>]+)>', r'{\1}', path or '')


# ── public API ───────────────────────────────────────────────────────────────


def groups() -> list:
    """The curated groups, each ``{id, label, tools}``."""
    return _load_curated()['groups']


def catalog() -> list:
    """Every tool: the curated ones first, then the automatic url_map tail."""
    curated = _load_curated()
    return [tool for group in curated['groups'] for tool in group['tools']] + _auto_tools()


def get(tool_id: str):
    """One tool by id (curated or automatic), or ``None``."""
    tool = _load_curated()['by_id'].get(tool_id)
    if tool is not None:
        return tool
    for auto in _auto_tools():
        if auto['id'] == tool_id:
            return auto
    return None


def display_names(group: dict) -> list:
    """The index names of a group's tools.

    A group whose tools all share one namespace (``system.*``) is listed without it;
    a mixed group (``code.*`` + ``docs.*`` + ``data.*``) keeps the full ids, because
    ``read`` twice in one line tells a model nothing.
    """
    heads = {tool['id'].split('.', 1)[0] for tool in group['tools']}
    if len(heads) == 1:
        return [tool['id'].split('.', 1)[1] if '.' in tool['id'] else tool['id'] for tool in group['tools']]
    return [tool['id'] for tool in group['tools']]


def usage_line() -> str:
    """The sentence that teaches a model how to use the three meta-tools."""
    total = len(catalog())
    return (
        f"Call zero_index(group) for a group's tools with params, zero_find(query) to search "
        f'everything ({total} tools), zero_call(tool, args) to run one. '
        f'Risk: danger tools ask the user first.'
    )


def index_text(max_tokens: int = 1200) -> str:
    """A compact text block naming every group and as many tool names as fit.

    One line per group -- ``system (20): health, telemetry, vram, ...`` -- truncated
    per group with ``+N more`` until the whole block, including the usage line, fits
    inside ``max_tokens`` estimated tokens.
    """
    index_groups = groups()
    tail = usage_line()
    for cap in range(max(len(g['tools']) for g in index_groups), 0, -1):
        lines = [_group_line(group, cap) for group in index_groups]
        text = '\n'.join(lines + ['', tail])
        if estimate_tokens(text) <= max_tokens:
            return text
    # Even one name per group does not fit: keep the group names and the usage line.
    lines = [f'{g["id"]} ({len(g["tools"])})' for g in index_groups]
    return '\n'.join(lines + ['', tail])


def _group_line(group: dict, cap: int) -> str:
    names = display_names(group)
    shown = names[:cap]
    rest = len(names) - len(shown)
    body = ', '.join(shown) + (f', +{rest} more' if rest > 0 else '')
    return f'{group["id"]} ({len(names)}): {body}'


def group_text(group_id: str, max_tokens: int = 800) -> str:
    """Every tool of one group with its call signature, inside ``max_tokens``.

    Each line is ``id -- desc [METHOD path] params: a, b? (risk)``; optional params
    carry a ``?``. Tools that do not fit are counted in a final line.
    """
    group = next((g for g in groups() if g['id'] == group_id), None)
    if group is None:
        known = ', '.join(g['id'] for g in groups())
        return f'unknown group {group_id!r}. Groups: {known}'
    head = f'{group["id"]} - {group["label"]} ({len(group["tools"])} tools)'
    lines: list = []
    for tool in group['tools']:
        candidate = lines + [tool_line(tool)]
        rest = len(group['tools']) - len(candidate)
        tail = [f'+{rest} more, use zero_find'] if rest > 0 else []
        if estimate_tokens('\n'.join([head] + candidate + tail)) > max_tokens:
            rest = len(group['tools']) - len(lines)
            lines.append(f'+{rest} more, use zero_find')
            break
        lines = candidate
    return '\n'.join([head] + lines)


def tool_line(tool: dict) -> str:
    """One tool rendered as a single call signature line."""
    params = []
    for name, spec in (tool.get('params') or {}).items():
        params.append(name if spec.get('required') else f'{name}?')
    where = target(tool)
    out = f'{tool["id"]} - {tool["desc"]} [{where}]'
    if params:
        out += ' params: ' + ', '.join(params)
    return f'{out} ({tool["risk"]})'


def target(tool: dict) -> str:
    """What a tool actually hits: ``GET /api/health``, a service URL, or its argv."""
    kind = tool.get('kind', 'http')
    if kind == 'http':
        return f'{tool.get("method", "GET")} {tool.get("path", "")}'
    if kind == 'service':
        return f'{tool.get("method", "GET")} {tool.get("url", "")}'
    if kind == 'shell':
        return 'shell ' + ' '.join(tool.get('argv') or [])
    return kind


def find(query: str, limit: int = 10) -> list:
    """Search every tool -- curated first -- and return the best matches.

    Scores the query's words against the tool id, title, description and path.
    """
    words = _WORD_RE.findall((query or '').lower())
    if not words:
        return []
    scored = []
    for tool in catalog():
        score = _score(tool, words)
        if score > 0:
            scored.append((score, tool))
    scored.sort(key=lambda row: (-row[0], row[1]['id']))
    return [tool for _, tool in scored[:limit]]


def _score(tool: dict, words: list) -> int:
    tool_id = tool['id'].lower()
    last = tool_id.split('.')[-1]
    title = (tool.get('title') or '').lower()
    desc = (tool.get('desc') or '').lower()
    target = (tool.get('path') or tool.get('url') or ' '.join(tool.get('argv') or [])).lower()
    score = 0
    for word in words:
        hit = 0
        if word == tool_id or word == last:
            hit += 100
        elif word in last:
            hit += 60
        elif word in tool_id:
            hit += 40
        if word in title:
            hit += 30
        if word in target:
            hit += 15
        if word in desc:
            hit += 10
        score += hit
    if score and tool.get('curated'):
        score += 5
    return score


def tool_specs() -> list:
    """The three meta-tool specs handed to a model with native tool calling."""
    index_groups = ', '.join(g['id'] for g in groups())
    return [
        {
            'name': 'zero_index',
            'description': (
                'List the tools of one group, with their parameters and risk class. '
                f'Groups: {index_groups}. Call this before zero_call when you know the area.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'group': {'type': 'string', 'description': f'group id, one of: {index_groups}'},
                },
                'required': ['group'],
            },
        },
        {
            'name': 'zero_find',
            'description': (
                'Search every tool -- including uncurated dashboard routes -- by words from its '
                'name, purpose or URL path. Use it when no group obviously holds what you need.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {
                        'type': 'string',
                        'description': 'words to search for, e.g. "vram" or "storyteller episodes"',
                    },
                },
                'required': ['query'],
            },
        },
        {
            'name': 'zero_call',
            'description': (
                'Run one tool by id with its arguments. Read tools run immediately, act tools are '
                'logged, and danger tools answer needs_confirmation until the user has agreed: pass '
                'confirm=true only after they said yes in this conversation.'
            ),
            'input_schema': {
                'type': 'object',
                'properties': {
                    'tool': {'type': 'string', 'description': 'tool id, e.g. system.telemetry'},
                    'args': {'type': 'object', 'description': "the tool's parameters as an object"},
                    'confirm': {
                        'type': 'boolean',
                        'description': 'true to execute a danger tool the user has approved',
                    },
                },
                'required': ['tool'],
            },
        },
    ]
