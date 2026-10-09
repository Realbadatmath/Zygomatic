# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for agent_zero.budget: config defaults and validation, the three kinds of
ceiling, the operator override, and the counters' day rollover.

No dashboard import: every file the module touches is redirected into tmp_path by
monkeypatching ``_host.runtime_dir``, and Claude's meter is a stub.
"""

import json
import os

import pytest

from zyg_dashboard.agent_zero import budget


def _reset_caches():
    budget._meter_cache.update(ts=0.0, snapshot=None)
    budget._share_cache.update(ts=0.0, login_week_usd=None, meter_pct=None)


class _Meter:
    """Stand-in for quota_meter with a weekly meter the test controls."""

    def __init__(self, seven=10.0, scoped=None, week_usd=100.0):
        self.seven = seven
        self.scoped = scoped or []
        self.week_usd = week_usd

    def read_status(self):
        return {'seven_day_pct': self.seven, 'five_hour_pct': 5.0}

    def report(self, days=7, **_kw):
        return {'week': {'api_usd': self.week_usd, 'utilization_pct': self.seven}}

    def price_tokens(self, model, tin=0, tout=0, cache_write=0, cache_read=0, **_kw):
        return (tin + tout) / 1_000_000.0


@pytest.fixture
def rt(tmp_path, monkeypatch):
    """Point budget's two files at tmp_path and give it no meter by default."""
    monkeypatch.setattr(budget._host, 'runtime_dir', lambda: str(tmp_path))
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: None)
    monkeypatch.setattr(budget, '_today', lambda: '2026-10-08')
    _reset_caches()
    yield tmp_path
    _reset_caches()


def test_defaults_created_on_first_load(rt):
    assert not os.path.exists(budget.config_path())
    cfg = budget.load_config()
    assert cfg == budget.DEFAULTS
    assert cfg['per_turn']['max_context_tokens'] == 14000
    assert cfg['per_turn']['max_tool_calls'] == 12
    assert cfg['per_day']['hard_tokens'] == 400000
    assert cfg['per_week']['meter_reserve_pct'] == 90
    assert cfg['policy']['allow_local_when_blocked'] is True
    with open(budget.config_path(), encoding='utf-8') as fh:
        assert json.load(fh) == budget.DEFAULTS
    # Every setting is documented for the UI.
    for section, keys in budget.DEFAULTS.items():
        for key in keys:
            assert budget.CONFIG_DOC[f'{section}.{key}']


def test_load_config_merges_new_keys(rt):
    budget._write_json(budget.config_path(), {'per_turn': {'max_tool_calls': 3}})
    cfg = budget.load_config()
    assert cfg['per_turn']['max_tool_calls'] == 3
    assert cfg['per_turn']['max_context_tokens'] == 14000
    with open(budget.config_path(), encoding='utf-8') as fh:
        assert json.load(fh)['per_session']['keep_recent_turns'] == 8


def test_save_config_validates(rt):
    with pytest.raises(TypeError, match='must be a number'):
        budget.save_config({'per_turn': {'max_tool_calls': 'twelve'}})
    with pytest.raises(ValueError, match='must be >='):
        budget.save_config({'per_turn': {'max_tool_calls': -1}})
    with pytest.raises(ValueError, match='unknown budget setting'):
        budget.save_config({'per_turn': {'nonsense': 1}})
    with pytest.raises(TypeError, match='true or false'):
        budget.save_config({'policy': {'allow_local_when_blocked': 1}})
    with pytest.raises(ValueError, match='unknown budget section'):
        budget.save_config({'nope': {}})
    # Nothing of the above was written.
    assert budget.load_config()['per_turn']['max_tool_calls'] == 12
    cfg = budget.save_config({'per_turn': {'max_tool_calls': 6}})
    assert cfg['per_turn']['max_tool_calls'] == 6
    assert budget.load_config()['per_turn']['max_tool_calls'] == 6
    assert budget.check_tool(5) is True
    assert budget.check_tool(6) is False


def test_check_turn_blocks_on_context_ceiling(rt):
    verdict = budget.check_turn('anthropic', 'claude-opus-5', 20000)
    assert verdict['allowed'] is False
    assert verdict['level'] == 'blocked'
    assert '20000' in verdict['reason']
    assert '14000' in verdict['reason']
    assert verdict['limits']['per_turn']['max_context_tokens'] == 14000
    assert budget.load_state()['last_block']['reason'] == verdict['reason']
    ok = budget.check_turn('anthropic', 'claude-opus-5', 1000)
    assert ok['allowed'] is True
    assert ok['level'] == 'ok'


def test_day_hard_cap_blocks_and_override_allows_exactly_n(rt):
    budget.record('anthropic', 'claude-opus-5', {'input_tokens': 400000, 'output_tokens': 0, 'cost_usd': 0.5})
    state = budget.load_state()
    assert state['day_tokens'] == 400000
    assert state['day_api_usd'] == 0.5

    blocked = budget.check_turn('anthropic', 'claude-opus-5', 500)
    assert blocked['allowed'] is False
    assert '400000' in blocked['reason']

    budget.grant_override(2)
    first = budget.check_turn('anthropic', 'claude-opus-5', 500)
    second = budget.check_turn('anthropic', 'claude-opus-5', 500)
    third = budget.check_turn('anthropic', 'claude-opus-5', 500)
    assert [first['allowed'], second['allowed'], third['allowed']] == [True, True, False]
    assert first['level'] == 'warn' and 'override' in first['reason']
    assert budget.load_state()['override_turns_left'] == 0
    # A local model is never blocked by a token cap, and the block message says so.
    assert budget.check_turn('ollama', 'qwen3:8b', 500)['allowed'] is True
    assert 'Ollama' in third['reason']


def test_meter_reserve_blocks_subscription_but_not_ollama(rt, monkeypatch):
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=95.0))
    _reset_caches()
    blocked = budget.check_turn('subscription', 'claude-opus-5', 1000)
    assert blocked['allowed'] is False
    assert '95' in blocked['reason'] and '90' in blocked['reason']
    assert budget.check_turn('ollama', 'qwen3:8b', 1000)['allowed'] is True
    # An API key is not the subscription meter either.
    assert budget.check_turn('anthropic', 'claude-opus-5', 1000)['allowed'] is True


def test_fable_scoped_cap_blocks_only_fable_models(rt, monkeypatch):
    # The scoped weekly limits only exist in the newest line of the sampler's ledger.
    row = {
        'ts': 1791475829.9,
        'seven_day': {'pct': 20.0, 'window_started_at': 1791399600.0},
        'scoped': [{'kind': 'weekly_scoped', 'name': 'Fable', 'pct': 61.0}],
    }
    (rt / 'quota_samples.jsonl').write_text(json.dumps(row) + '\n', encoding='utf-8')
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=20.0))
    _reset_caches()
    assert budget.meter_snapshot()['scoped'] == {'fable': 61.0}
    _reset_caches()
    blocked = budget.check_turn('subscription', 'claude-fable-5-1', 1000)
    assert blocked['allowed'] is False
    assert 'Fable' in blocked['reason'] and '50' in blocked['reason']
    assert budget.check_turn('subscription', 'claude-opus-5', 1000)['allowed'] is True


def test_warn_level_on_the_daily_soft_cap(rt):
    budget.record('anthropic', 'claude-opus-5', {'input_tokens': 150000, 'output_tokens': 0})
    warn = budget.check_turn('anthropic', 'claude-opus-5', 1000)
    assert warn['allowed'] is True and warn['level'] == 'warn'
    assert '150000' in warn['reason'] and '400000' in warn['reason']
    # A local model is not warned about Claude tokens it does not spend.
    assert budget.check_turn('ollama', 'qwen3:8b', 1000)['level'] == 'ok'


def test_warn_level_near_the_weekly_reserve(rt, monkeypatch):
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=82.0))
    _reset_caches()
    near = budget.check_turn('subscription', 'claude-opus-5', 1000)
    assert near['allowed'] is True and near['level'] == 'warn'
    assert '82' in near['reason'] and '90' in near['reason']


def test_unreadable_meter_never_blocks(rt, monkeypatch):
    class _Broken:
        def read_status(self):
            raise OSError('no status file')

        def report(self, days=7, **_kw):
            raise OSError('no transcripts')

    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Broken())
    _reset_caches()
    verdict = budget.check_turn('subscription', 'claude-opus-5', 1000)
    assert verdict['allowed'] is True and verdict['level'] == 'ok'
    assert budget.meter_snapshot()['ok'] is False
    assert budget.zero_share_pct() is None


def test_record_rolls_day_totals_and_resets_on_a_new_day(rt, monkeypatch):
    budget.record('subscription', 'claude-opus-5', {'input_tokens': 10, 'output_tokens': 5, 'cost_usd': 0.01})
    budget.record('ollama', 'qwen3:8b', {'input_tokens': 100, 'output_tokens': 20})
    state = budget.load_state()
    assert state['day'] == '2026-10-08'
    assert state['day_tokens'] == 135
    assert state['day_turns'] == 2
    assert state['week_tokens'] == 135
    assert state['week_sub_turns'] == 1
    assert state['day_api_usd'] == 0.01
    assert state['totals'] == {'turns': 2, 'tokens': 135, 'api_usd': 0.01}

    monkeypatch.setattr(budget, '_today', lambda: '2026-10-09')
    rolled = budget.load_state()
    assert rolled['day'] == '2026-10-09'
    assert rolled['day_tokens'] == 0 and rolled['day_turns'] == 0 and rolled['day_api_usd'] == 0.0
    # The week and the lifetime totals survive the day rollover.
    assert rolled['week_tokens'] == 135
    assert rolled['totals']['tokens'] == 135


def test_record_prices_an_unpriced_claude_turn(rt, monkeypatch):
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter())
    _reset_caches()
    budget.record('subscription', 'claude-opus-5', {'input_tokens': 1_000_000, 'output_tokens': 0})
    assert budget.load_state()['week_api_usd'] == 1.0
    # A local model never costs money, priced or not.
    budget.record('ollama', 'qwen3:8b', {'input_tokens': 1_000_000, 'output_tokens': 0})
    assert budget.load_state()['week_api_usd'] == 1.0


def test_zero_share_pct_and_state_payload(rt, monkeypatch):
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=40.0, week_usd=50.0))
    _reset_caches()
    budget.record('subscription', 'claude-opus-5', {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 5.0})
    # 5 $ of a 50 $ week at a 40 % meter = 4 points of the weekly allowance.
    assert budget.zero_share_pct() == pytest.approx(4.0)
    payload = budget.state()
    assert payload['zero_share_pct'] == pytest.approx(4.0)
    assert payload['meter']['seven_day_pct'] == 40.0
    assert payload['config']['per_turn']['max_tool_calls'] == 12
    assert payload['config_doc'] is budget.CONFIG_DOC


def test_zero_share_cap_blocks_subscription(rt, monkeypatch):
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=40.0, week_usd=50.0))
    _reset_caches()
    budget.record('subscription', 'claude-opus-5', {'input_tokens': 0, 'output_tokens': 0, 'cost_usd': 30.0})
    assert budget.zero_share_pct() == pytest.approx(24.0)
    blocked = budget.check_turn('subscription', 'claude-opus-5', 1000)
    assert blocked['allowed'] is False
    assert '24' in blocked['reason'] and '20' in blocked['reason']


def test_summary_line_fits_the_prompt(rt, monkeypatch):
    assert len(budget.summary_line()) <= 160
    monkeypatch.setattr(budget._host, 'quota_meter', lambda: _Meter(seven=21.0, week_usd=50.0))
    _reset_caches()
    budget.record('subscription', 'claude-opus-5', {'input_tokens': 23000, 'output_tokens': 0, 'cost_usd': 0.3})
    budget.zero_share_pct()
    budget.grant_override(10)
    line = budget.summary_line()
    assert line.startswith('Budget: ')
    assert len(line) <= 160
    assert '23k/400k tokens' in line
    assert 'week meter 21%' in line
    assert 'tools <=12/turn' in line
