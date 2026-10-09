# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for the Agent Zero v2 tool map.

No Flask application is imported here: ``agent_zero.toolmap`` is deliberately readable
without the dashboard (the curated half is a JSON file, the automatic half is merged
only when the host module already sits in ``sys.modules``). Where a test needs the
executor to attempt an HTTP tool, ``_host.app`` is monkeypatched to ``None`` -- importing
``crewai_web_gui`` for real would start its watcher threads inside the test process and
race the live server on :5000.
"""

import json
import os
import re
import sys

import pytest

from zyg_dashboard.agent_zero import _host, toolmap, toolmap_exec
from zyg_dashboard.agent_zero.contracts import estimate_tokens

# The dashboard package root: it carries src/, tests/ and the apitests/ route inventory.
CREWS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES_JSON = os.path.join(CREWS_DIR, 'apitests', 'routes.json')

#: Paths that exist on the live ``url_map`` (verified 2026-10-08 against
#: ``crewai_web_gui.app.url_map``, 438 rules) but are absent from the generated
#: ``apitests/routes.json`` inventory, which predates the affiliate blueprint. The
#: runtime map wins over the inventory, so these are curated on purpose.
KNOWN_INVENTORY_GAPS = {
    ('/api/internal/affiliate/history', 'GET'),
    ('/api/internal/affiliate/config', 'GET'),
    ('/api/internal/affiliate/auto', 'GET'),
    ('/api/internal/affiliate/start', 'POST'),
}


@pytest.fixture(autouse=True)
def _quiet_tool_log(tmp_path, monkeypatch):
    """Keep the executor's audit log out of the live ``data/runtime`` directory."""
    monkeypatch.setattr(_host, 'runtime_dir', lambda: str(tmp_path))


@pytest.fixture(scope='module')
def curated():
    with open(toolmap.MAP_PATH, encoding='utf-8') as fh:
        return json.load(fh)


@pytest.fixture(scope='module')
def inventory_keys():
    with open(ROUTES_JSON, encoding='utf-8') as fh:
        raw = json.load(fh)
    keys = set()
    for rows in (raw.get('apps') or {}).values():
        for row in rows:
            for method in row.get('methods') or []:
                keys.add((toolmap.normalise_path(row.get('rule', '')), method))
    return keys


# ── the curated map itself ───────────────────────────────────────────────────


def test_curated_map_parses_and_is_big_enough(curated):
    tools = [tool for group in curated['groups'] for tool in group['tools']]
    assert len(curated['groups']) >= 8
    assert len(tools) >= 70, f'the curated map must cover the program: only {len(tools)} tools'


def test_every_tool_is_fully_described(curated):
    missing = []
    for group in curated['groups']:
        for tool in group['tools']:
            for field in ('id', 'title', 'kind', 'risk', 'desc'):
                if not tool.get(field):
                    missing.append(f'{tool.get("id", "?")}: {field}')
            if tool.get('kind') not in ('http', 'service', 'code', 'shell'):
                missing.append(f'{tool.get("id")}: kind={tool.get("kind")!r}')
            if tool.get('risk') not in ('read', 'act', 'danger'):
                missing.append(f'{tool.get("id")}: risk={tool.get("risk")!r}')
    assert not missing, 'incomplete tools: ' + '; '.join(missing)


def test_tool_ids_are_unique(curated):
    ids = [tool['id'] for group in curated['groups'] for tool in group['tools']]
    duplicates = sorted({tool_id for tool_id in ids if ids.count(tool_id) > 1})
    assert not duplicates, f'duplicate tool ids: {duplicates}'


def test_http_tools_point_at_real_routes(curated, inventory_keys):
    misses = []
    for group in curated['groups']:
        for tool in group['tools']:
            if tool.get('kind') != 'http':
                continue
            assert tool['path'].startswith('/api/'), f'{tool["id"]} is not under /api/'
            key = (toolmap.normalise_path(tool['path']), tool.get('method', 'GET'))
            if key not in inventory_keys:
                misses.append((tool['id'], tool['path'], tool.get('method')))
    unexpected = [row for row in misses if (row[1], row[2]) not in KNOWN_INVENTORY_GAPS]
    assert not unexpected, 'routes not found in apitests/routes.json: ' + '; '.join(
        f'{tool_id} {method} {path}' for tool_id, path, method in unexpected
    )


def test_service_and_shell_tools_are_well_formed(curated):
    for group in curated['groups']:
        for tool in group['tools']:
            if tool['kind'] == 'service':
                assert re.match(r'^(http://|\{ollama_url\})', tool['url']), tool['id']
            if tool['kind'] == 'shell':
                assert tool['argv'] and tool['argv'][0] == 'st', f'{tool["id"]} is not an st command'
                assert tool['risk'] == 'read', f'{tool["id"]} must be read-only'


def test_code_tools_all_have_a_handler(curated):
    code_ids = {tool['id'] for group in curated['groups'] for tool in group['tools'] if tool['kind'] == 'code'}
    assert code_ids == set(toolmap_exec._CODE_HANDLERS), 'code tools and handlers disagree'


# ── budgets ──────────────────────────────────────────────────────────────────


def test_index_text_fits_its_budget_and_names_every_group():
    text = toolmap.index_text(1200)
    assert estimate_tokens(text) <= 1200, estimate_tokens(text)
    for group in toolmap.groups():
        assert f'{group["id"]} (' in text, f'group {group["id"]} missing from the index'
    assert 'zero_index(group)' in text and 'zero_find(query)' in text and 'zero_call(tool, args)' in text
    assert 'danger tools ask the user first' in text


def test_index_text_truncates_under_a_small_budget():
    text = toolmap.index_text(300)
    assert estimate_tokens(text) <= 300, estimate_tokens(text)
    assert 'more' in text.split('Call zero_index')[0], 'a small budget must truncate with "+N more"'
    for group in toolmap.groups():
        assert f'{group["id"]} (' in text, f'group {group["id"]} dropped under pressure'


def test_index_text_keeps_the_group_names_under_an_impossible_budget():
    text = toolmap.index_text(60)
    for group in toolmap.groups():
        assert f'{group["id"]} ({len(group["tools"])})' in text
    assert 'zero_find(query)' in text


def test_group_text_fits_its_budget():
    text = toolmap.group_text('system', 800)
    assert estimate_tokens(text) <= 800, estimate_tokens(text)
    assert 'system.health' in text
    assert '[GET /api/health]' in text
    assert 'params: section' in text, 'required params must be named without a ?'


def test_group_text_rejects_an_unknown_group():
    text = toolmap.group_text('nope')
    assert 'unknown group' in text and 'system' in text


def test_find_puts_the_obvious_tool_first():
    hits = toolmap.find('vram')
    assert hits, 'find("vram") found nothing'
    assert hits[0]['id'] == 'system.vram', [hit['id'] for hit in hits]


def test_find_is_empty_for_an_empty_query():
    assert toolmap.find('') == []


def test_tool_specs_are_the_three_meta_tools():
    specs = toolmap.tool_specs()
    assert [spec['name'] for spec in specs] == ['zero_index', 'zero_find', 'zero_call']
    for spec in specs:
        assert spec['description'] and spec['input_schema']['type'] == 'object'
    call_spec = next(spec for spec in specs if spec['name'] == 'zero_call')
    assert set(call_spec['input_schema']['properties']) == {'tool', 'args', 'confirm'}


def test_catalog_without_the_host_is_the_curated_map_only(monkeypatch):
    """The automatic half must never import the dashboard to answer a question.

    Earlier tests in the suite may already have imported the host, so it is unloaded
    for the duration of this test (monkeypatch restores sys.modules afterwards).
    """
    for name in [k for k in sys.modules if 'crewai_web_gui' in k]:
        monkeypatch.delitem(sys.modules, name)
    assert len(toolmap.catalog()) == sum(len(group['tools']) for group in toolmap.groups())
    assert not [k for k in sys.modules if 'crewai_web_gui' in k], 'catalog() imported the host'


# ── the code sandbox ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    'path',
    [
        '../.env',
        'data/runtime/zero_provider_keys.json',
        '/etc/passwd',
        os.path.expanduser('~/.claude/.credentials.json'),
    ],
)
def test_code_read_sandbox_refuses(path):
    out = toolmap_exec.call('code.read', {'path': path})
    assert out['ok'] is False, f'{path} was readable!'
    assert 'refused' in out['text'] or 'outside the sandbox' in out['text'], out['text']


def test_code_read_allows_a_file_inside_the_sandbox():
    out = toolmap_exec.call('code.read', {'path': 'src/zyg_dashboard/agent_zero/toolmap.json', 'start': 1, 'lines': 3})
    assert out['ok'] is True
    assert '1: {' in out['text']


def test_code_read_caps_the_line_count():
    out = toolmap_exec.call('code.read', {'path': 'src/zyg_dashboard/agent_zero/toolmap.py', 'start': 1, 'lines': 9999})
    assert out['ok'] is True
    assert re.search(r'lines 1-(\d+) of', out['text'])
    assert int(re.search(r'lines 1-(\d+) of', out['text']).group(1)) <= 200


def test_data_read_json_refuses_a_non_json_file():
    out = toolmap_exec.call('data.read_json', {'path': 'src/zyg_dashboard/agent_zero/toolmap.py'})
    assert out['ok'] is False and 'not a .json' in out['text']


def test_find_route_finds_the_vram_route():
    out = toolmap_exec.call('code.find_route', {'query': 'vram'})
    assert out['ok'] is True
    assert '/api/vram/free' in out['text'] and 'api_vram_free' in out['text']


def test_find_symbol_rejects_a_regex():
    out = toolmap_exec.call('code.find_symbol', {'name': 'def .*'})
    assert out['ok'] is False and 'identifier' in out['text']


# ── the risk gate ────────────────────────────────────────────────────────────


def test_danger_tool_asks_before_it_runs(monkeypatch):
    monkeypatch.setattr(_host, 'app', lambda: None)
    first = toolmap_exec.execute('zero_call', {'tool': 'zero.stop'})
    assert first['ok'] is False
    assert first['needs_confirmation'] is True
    assert first['risk'] == 'danger'
    assert first['text'].startswith('CONFIRMATION REQUIRED: Emergency stop (POST /api/zero/stop)')
    confirm_id = first['confirm_id']
    assert confirm_id and toolmap_exec.PENDING[confirm_id]['tool'] == 'zero.stop'

    # The confirmation is accepted exactly once. The host app is patched away, so the
    # tool is dispatched and fails on a missing application instead of stopping the
    # live pipelines -- what matters is that it was no longer refused as unconfirmed.
    second = toolmap_exec.execute_confirmed(confirm_id)
    assert second['needs_confirmation'] is False
    assert 'not importable' in second['text'], second['text']

    third = toolmap_exec.execute_confirmed(confirm_id)
    assert third['ok'] is False
    assert 'unknown or expired' in third['text']


def test_confirmations_expire(monkeypatch):
    out = toolmap_exec.execute('zero_call', {'tool': 'launch.market_run'})
    confirm_id = out['confirm_id']
    toolmap_exec.PENDING[confirm_id]['ts'] -= toolmap_exec.PENDING_TTL_S + 1
    assert toolmap_exec.pending_tool(confirm_id) is None
    assert 'unknown or expired' in toolmap_exec.execute_confirmed(confirm_id)['text']


def test_read_tools_need_no_confirmation(monkeypatch):
    monkeypatch.setattr(_host, 'app', lambda: None)
    out = toolmap_exec.execute('zero_call', {'tool': 'system.health'})
    assert out['needs_confirmation'] is False
    assert out['ok'] is False and 'not importable' in out['text']


def test_unknown_tool_lists_the_closest_ids():
    out = toolmap_exec.execute('zero_call', {'tool': 'system.vramm'})
    assert out['ok'] is False
    assert 'unknown tool' in out['text']
    assert 'system.vram' in out['text']
    assert len(out['text'].split('Closest ids: ')[1].split(', ')) <= 5


def test_unknown_meta_tool_is_refused():
    out = toolmap_exec.execute('zero_whatever', {})
    assert out['ok'] is False and 'zero_index' in out['text']


# ── the meta-tools ───────────────────────────────────────────────────────────


def test_zero_index_without_a_group_returns_the_index():
    out = toolmap_exec.execute('zero_index', {})
    assert out['ok'] is True and 'pipelines (' in out['text']


def test_zero_index_opens_one_group():
    out = toolmap_exec.execute('zero_index', {'group': 'code'})
    assert out['ok'] is True
    assert 'code.find_symbol' in out['text'] and 'docs.search' in out['text']


def test_zero_find_names_the_tool():
    out = toolmap_exec.execute('zero_find', {'query': 'telemetry'})
    assert out['ok'] is True and 'system.telemetry' in out['text']


def test_zero_find_says_so_when_nothing_matches():
    out = toolmap_exec.execute('zero_find', {'query': 'zzzzqqq'})
    assert out['ok'] is True and 'no tool matches' in out['text']


# ── the audit log ────────────────────────────────────────────────────────────


def test_every_execution_is_logged_without_argument_values(tmp_path):
    toolmap_exec.call('code.find_route', {'query': 'telemetry'}, actor='apitest')
    with open(toolmap_exec.log_path(), encoding='utf-8') as fh:
        rows = [json.loads(line) for line in fh]
    row = rows[-1]
    assert row['tool'] == 'code.find_route'
    assert row['actor'] == 'apitest'
    assert row['risk'] == 'read' and row['ok'] is True
    assert row['args_keys'] == ['query']
    assert 'telemetry' not in json.dumps(row), 'argument values must never be logged'
