# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""quota_meter — the subscription quota meter and the two costs behind it.

Pinned here (2026-09-17):
  * the price table reproduces Anthropic list price for three real sessions, and the
    legacy table reproduces what claude 2.1.74 printed for the same sessions (to the
    cent) — so the 2.2x Sonnet 5 overstatement on the old panels is explained, not guessed;
  * transcript parsing de-duplicates a multi-block message (one line per block, same
    usage) and prices 1-hour cache writes at 2x;
  * the weekly price of a monthly plan is price x 12 / 52.18, not price / 4;
  * per-model subscription cost sums back to the consumed weekly value and follows the
    API-equivalent share; other surfaces are never attributed to a model.
"""

import json
import os
import sys
import time

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

from zyg_dashboard import quota_meter as qm  # noqa: E402

# Three sessions measured on 2026-09-17 from their transcripts (input, output, cache write 5 m,
# cache write 1 h, cache read) and the total_cost_usd the installed CLI (2.1.74) reported.
CALIBRATION = [
    ('claude-sonnet-5', (1814, 50476, 1533, 193362, 6711008), 5.8446, 2.628),
    ('claude-opus-5', (74, 20897, 0, 159042, 4920158), 3.9769, 4.573),
    ('claude-haiku-4-5-20251001', (266, 19959, 0, 55551, 3725909), 0.5473, 0.584),
]


def _vec(t):
    return {'input': t[0], 'output': t[1], 'cache_5m': t[2], 'cache_1h': t[3], 'cache_read': t[4], 'web_search': 0}


@pytest.mark.parametrize('model,tokens,cli_said,list_usd', CALIBRATION)
def test_list_price_matches_reference(model, tokens, cli_said, list_usd):
    assert qm.price_usage(model, _vec(tokens)) == pytest.approx(list_usd, abs=0.005)


@pytest.mark.parametrize('model,tokens,cli_said,list_usd', CALIBRATION[:2])
def test_legacy_cli_table_explains_old_numbers(model, tokens, cli_said, list_usd):
    """claude 2.1.74 prices any model newer than Opus/Sonnet 4.6 at Opus rates with a flat
    1.25x cache write. With that table the CLI's own figure comes back to the cent."""
    r = qm.LEGACY_CLI_UNKNOWN_MODEL
    legacy = {
        'input': tokens[0],
        'output': tokens[1],
        'cache_5m': tokens[2] + tokens[3],
        'cache_1h': 0,
        'cache_read': tokens[4],
    }
    assert qm.price_usage(model, legacy, rates=r) == pytest.approx(cli_said, abs=0.002)


def test_haiku_is_known_to_the_old_cli_too():
    """Haiku 4.5 IS in the 2.1.74 table (1/5/1.25/0.1): the old figure only misses the
    1-hour cache premium, so it sits between the flat-1.25x and the list number."""
    model, tokens, cli_said, list_usd = CALIBRATION[2]
    flat = {
        'input': tokens[0],
        'output': tokens[1],
        'cache_5m': tokens[2] + tokens[3],
        'cache_1h': 0,
        'cache_read': tokens[4],
    }
    assert qm.price_usage(model, flat) == pytest.approx(cli_said, abs=0.01)
    assert list_usd > cli_said


def test_model_key_and_unknown_models():
    assert qm.model_key('claude-haiku-4-5-20251001') == 'claude-haiku-4-5'
    assert qm.model_key('Claude-Opus-5[1m]') == 'claude-opus-5'
    assert qm.price_row('claude-fable-5-1')[4] == 0.25  # the one model with a $0.25 cache read
    assert qm.price_row('claude-fable-5')[4] == 1.0
    assert qm.price_row('gpt-4o') is None
    assert qm.price_usage('gpt-4o', _vec((1, 1, 0, 0, 0))) is None


def test_weekly_price_monthly_vs_28_days():
    month = qm.weekly_price({'subscription_price': 180, 'billing': 'month'})
    days28 = qm.weekly_price({'subscription_price': 180, 'billing': 'days', 'billing_days': 28})
    assert month == pytest.approx(180 * 12 / 52.1775, rel=1e-4)  # 41.40
    assert days28 == pytest.approx(45.0)
    assert month < days28  # 12 payments a year, not 13


def _write_transcript(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        for row in lines:
            fh.write(json.dumps(row) + '\n')


def _assistant(mid, model, ts_iso, usage, block=0):
    return {
        'type': 'assistant',
        'timestamp': ts_iso,
        'apiBlockIndex': block,
        'requestId': 'req_' + mid,
        'message': {
            'id': mid,
            'model': model,
            'role': 'assistant',
            'usage': usage,
            'content': [{'type': 'text', 'text': 'x'}],
        },
    }


def _usage(inp, out, w1h=0, w5m=0, read=0):
    return {
        'input_tokens': inp,
        'output_tokens': out,
        'cache_read_input_tokens': read,
        'cache_creation_input_tokens': w1h + w5m,
        'cache_creation': {'ephemeral_1h_input_tokens': w1h, 'ephemeral_5m_input_tokens': w5m},
    }


@pytest.fixture
def corpus(tmp_path):
    proj = tmp_path / 'projects' / '-home-x'
    # one message written as three block lines (identical usage) + a second message
    main = [
        _assistant('m1', 'claude-sonnet-5', '2026-09-17T10:00:00.000Z', _usage(100, 1000, w1h=50000, read=200000), 0),
        _assistant('m1', 'claude-sonnet-5', '2026-09-17T10:00:00.500Z', _usage(100, 1000, w1h=50000, read=200000), 1),
        _assistant('m1', 'claude-sonnet-5', '2026-09-17T10:00:01.000Z', _usage(100, 1000, w1h=50000, read=200000), 2),
        _assistant('m2', 'claude-opus-5', '2026-09-17T11:00:00.000Z', _usage(10, 2000, w5m=1000, read=100000)),
        {'type': 'user', 'timestamp': '2026-09-17T11:00:01.000Z', 'message': {'role': 'user', 'content': 'hi'}},
        {
            'type': 'assistant',
            'timestamp': '2026-09-17T11:00:02.000Z',
            'message': {'id': 'm3', 'model': '<synthetic>', 'usage': _usage(1, 1)},
        },
    ]
    _write_transcript(str(proj / 'sess.jsonl'), main)
    _write_transcript(
        str(proj / 'sess' / 'subagents' / 'agent-1.jsonl'),
        [_assistant('s1', 'claude-haiku-4-5-20251001', '2026-09-17T11:30:00.000Z', _usage(5, 300, read=50000))],
    )
    # an old session outside every window
    old = str(proj / 'old.jsonl')
    _write_transcript(old, [_assistant('o1', 'claude-opus-5', '2026-08-01T10:00:00.000Z', _usage(1, 1))])
    t_old = time.mktime((2026, 8, 1, 12, 0, 0, 0, 0, -1))
    os.utime(old, (t_old, t_old))
    return str(tmp_path / 'projects'), str(tmp_path / 'cache.json')


def test_parse_dedupes_blocks_and_prices_1h_cache(corpus):
    projects, cache = corpus
    res = qm.scan_transcripts(qm._ts_iso('2026-09-10T00:00:00Z'), projects_dir=projects, cache_path=cache)
    assert res['parsed_now'] == 2 and res['error_count'] == 0  # main + subagent; old file skipped by mtime
    files = res['files']
    assert sum(d['messages'] for d in files.values()) == 3  # m1 once, m2, s1; synthetic dropped
    start, end = qm._ts_iso('2026-09-17T00:00:00Z'), qm._ts_iso('2026-09-18T00:00:00Z')
    agg = qm.aggregate(files, start, end)
    assert agg['claude-sonnet-5']['input'] == 100 and agg['claude-sonnet-5']['cache_1h'] == 50000
    assert agg['claude-opus-5']['cache_5m'] == 1000
    assert agg['claude-haiku-4-5']['cache_read'] == 50000
    # Sonnet 5: 100*2 + 1000*10 + 50000*4 (1 h) + 200000*0.2 per MTok
    assert qm.price_usage('claude-sonnet-5', agg['claude-sonnet-5']) == pytest.approx(
        (200 + 10000 + 200000 + 40000) / 1e6
    )
    # second scan: everything from cache, nothing re-parsed
    res2 = qm.scan_transcripts(qm._ts_iso('2026-09-10T00:00:00Z'), projects_dir=projects, cache_path=cache)
    assert res2['parsed_now'] == 0 and res2['skipped'] == 2
    # a window that excludes 11:00 UTC onwards only sees m1
    part = qm.aggregate(files, start, qm._ts_iso('2026-09-17T10:30:00Z'))
    assert list(part) == ['claude-sonnet-5']


REAL_PAYLOAD = {
    'five_hour': {'utilization': 18.0, 'resets_at': '2026-09-17T15:30:00.259397+00:00'},
    'seven_day': {'utilization': 8.0, 'resets_at': '2026-09-23T19:00:00.259419+00:00'},
    'seven_day_opus': None,
    'seven_day_sonnet': None,
    'limits': [
        {
            'kind': 'session',
            'group': 'session',
            'percent': 18,
            'severity': 'normal',
            'resets_at': '2026-09-17T15:30:00+00:00',
        },
        {
            'kind': 'weekly_all',
            'group': 'weekly',
            'percent': 8,
            'severity': 'normal',
            'resets_at': '2026-09-23T19:00:00+00:00',
        },
        {
            'kind': 'weekly_scoped',
            'group': 'weekly',
            'percent': 10,
            'severity': 'normal',
            'resets_at': '2026-09-23T19:00:00+00:00',
            'scope': {'model': {'id': None, 'display_name': 'Fable'}, 'surface': None},
        },
    ],
    'extra_usage': {'is_enabled': False},
    'seven_day_breakdown': {
        'as_of': '2026-09-17T13:38:48+00:00',
        'window_started_at': '2026-09-16T19:00:00.259419+00:00',
        'rows': [
            {'key': 'claude_code', 'display_name': 'Claude Code', 'percent': 100},
            {'key': 'chat', 'display_name': 'Chats', 'percent': 0},
        ],
    },
}


def test_parse_usage_payload_real_shape():
    s = qm.parse_usage_payload(REAL_PAYLOAD, now=1000.0, tier='default_claude_max_20x')
    assert s['seven_day']['pct'] == 8.0 and s['five_hour']['pct'] == 18.0
    assert s['seven_day']['resets_at'] - s['seven_day']['window_started_at'] == pytest.approx(7 * 86400, abs=1)
    assert s['scoped'] == [
        {
            'kind': 'weekly_scoped',
            'name': 'Fable',
            'pct': 10.0,
            'resets_at': qm._ts_iso('2026-09-23T19:00:00+00:00'),
            'severity': 'normal',
        }
    ]
    assert s['surfaces'] == {'claude_code': 100.0, 'chat': 0.0}
    assert s['tier'] == 'default_claude_max_20x' and s['ts'] == 1000.0
    # no breakdown -> the week start is derived from the reset
    s2 = qm.parse_usage_payload({'seven_day': {'utilization': 1, 'resets_at': '2026-09-23T19:00:00+00:00'}}, now=1.0)
    assert s2['seven_day']['window_started_at'] == qm._ts_iso('2026-09-16T19:00:00+00:00')


def test_compute_splits_consumed_value_by_api_share():
    cfg = dict(qm.DEFAULT_CONFIG, subscription_price=180, billing='days', billing_days=28, eur_per_usd=0.9)
    sample = qm.parse_usage_payload(REAL_PAYLOAD, now=qm._ts_iso('2026-09-17T13:00:00+00:00'))
    sample['seven_day']['pct'] = 20.0
    week = {
        'claude-opus-5': _vec((0, 1_000_000, 0, 0, 0)),  # $25
        'claude-sonnet-5': _vec((0, 500_000, 0, 0, 0)),
    }  # $5
    c = qm.compute(cfg, sample, week, {}, now=sample['ts'])
    assert c['weekly_price'] == 45.0 and c['price_per_pct'] == 0.45
    assert c['consumed'] == pytest.approx(9.0) and c['remaining'] == pytest.approx(36.0)
    assert c['api_usd'] == pytest.approx(30.0) and c['api_eur'] == pytest.approx(27.0)
    by = {r['model']: r for r in c['models']}
    assert by['claude-opus-5']['share'] == pytest.approx(25 / 30, abs=1e-4)
    assert by['claude-opus-5']['subscription_eur'] + by['claude-sonnet-5']['subscription_eur'] == pytest.approx(
        9.0, abs=1e-3
    )
    assert c['eur_per_api_usd'] == pytest.approx(0.3) and c['subscription_cheaper'] is True
    assert c['pct_per_api_usd'] == pytest.approx(20 / 30, abs=1e-4)
    # 18 h into a 168 h week at 20 % -> straight-line projection
    assert c['projected_utilization_pct'] == pytest.approx(20 / (18 / 168), abs=0.2)


def test_compute_keeps_other_surfaces_off_the_models():
    cfg = dict(qm.DEFAULT_CONFIG, billing='days', billing_days=28)
    sample = qm.parse_usage_payload(REAL_PAYLOAD, now=qm._ts_iso('2026-09-17T13:00:00+00:00'))
    sample['seven_day']['pct'] = 10.0
    sample['surfaces'] = {'claude_code': 60.0, 'chat': 40.0}
    c = qm.compute(cfg, sample, {'claude-opus-5': _vec((0, 1_000_000, 0, 0, 0))}, {}, now=sample['ts'])
    assert c['consumed'] == pytest.approx(4.5)
    assert c['consumed_claude_code'] == pytest.approx(2.7) and c['consumed_other_surfaces'] == pytest.approx(1.8)
    assert c['models'][0]['subscription_eur'] == pytest.approx(2.7)


def test_compute_without_a_sample_prices_api_only():
    c = qm.compute(qm.DEFAULT_CONFIG, {}, {'claude-opus-5': _vec((0, 1_000_000, 0, 0, 0))}, {}, now=time.time())
    assert c['utilization_pct'] is None and c['consumed'] is None and c['subscription_cheaper'] is None
    assert c['api_usd'] == 25.0 and c['models'][0]['subscription_eur'] is None


def test_credentials_expired_is_reported_not_refreshed(tmp_path, monkeypatch):
    cred = tmp_path / 'cred.json'
    cred.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'x', 'expiresAt': 1000}}))
    monkeypatch.setattr(qm, 'CRED_PATH', str(cred))
    with pytest.raises(qm.QuotaError, match='expired'):
        qm.fetch_usage()


# ── lanes: production workflows vs building infrastructure (2026-09-30) ──────
# The operator's question of this meter is not only "what did the week cost" but "how much
# of it produced content and how much of it built the stack". Claude reports no such split,
# so it is made here from the transcripts and pinned below.

TREE_PROMPT = (
    'You are a Session Tree executor. The board spawned this session for exactly '
    'ONE task: second-ledger-intro-take-4-hands-quill-b-c8f3ff#1.\nDo these steps'
)


def _tree_head(sid, prompt=TREE_PROMPT):
    return {
        'type': 'queue-operation',
        'operation': 'enqueue',
        'timestamp': '2026-09-24T06:00:00.000Z',
        'sessionId': sid,
        'content': prompt,
    }


def _rowed(row, cwd, entrypoint=None):
    row = dict(row)
    row['cwd'] = cwd
    if entrypoint:
        row['entrypoint'] = entrypoint
    return row


def test_classify_reads_the_lane_off_a_transcript(tmp_path):
    proj = tmp_path / 'projects' / '-p'
    cache = str(tmp_path / 'c.json')
    ts = '2026-09-24T06:05:00.000Z'
    scholarly = '/home/x/agents/crews/data/runtime/scholarly-llm-cli'
    _write_transcript(
        str(proj / 'tree.jsonl'),
        [
            _tree_head('t1'),
            _rowed(_assistant('a', 'claude-opus-5', ts, _usage(10, 10)), '/home/x/zygomatics-zero/ledger_intro'),
        ],
    )
    _write_transcript(
        str(proj / 'flow.jsonl'), [_rowed(_assistant('b', 'claude-opus-5', ts, _usage(10, 10)), scholarly, 'sdk-cli')]
    )
    _write_transcript(
        str(proj / 'me.jsonl'),
        [_rowed(_assistant('c', 'claude-opus-5', ts, _usage(10, 10)), '/home/x/zygomatics-zero', 'claude-vscode')],
    )
    files = qm.scan_transcripts(
        qm._ts_iso('2026-09-20T00:00:00Z'), projects_dir=str(tmp_path / 'projects'), cache_path=cache
    )['files']
    got = {os.path.basename(p): qm.classify(d) for p, d in files.items()}
    assert got['tree.jsonl']['lane'] == 'session_tree'
    assert got['tree.jsonl']['tree'] == 'second-ledger-intro-take-4-hands-quill-b-c8f3ff'
    assert got['tree.jsonl']['side'] == 'production'  # "ledger" is a content keyword
    assert got['flow.jsonl'] == {
        'lane': 'production',
        'side': 'production',
        'label': 'Documentary (scholarly)',
        'tree': None,
    }
    assert got['me.jsonl']['lane'] == 'interactive' and got['me.jsonl']['side'] == 'infrastructure'


def test_a_session_that_merely_quotes_the_board_is_not_an_executor(tmp_path):
    """This very repo's agents read and write about the board, so the spawn prompt is quoted
    in ordinary sessions. Only an OPENING row that starts with it makes an executor."""
    proj = tmp_path / 'projects' / '-p'
    rows = [
        {
            'type': 'user',
            'timestamp': '2026-09-24T06:00:00.000Z',
            'message': {'role': 'user', 'content': 'the board sends "' + TREE_PROMPT + '" to each one'},
        }
    ]
    rows += [
        _rowed(
            _assistant('a', 'claude-opus-5', '2026-09-24T06:05:00.000Z', _usage(1, 1)),
            '/home/x/zygomatics-zero',
            'claude-vscode',
        )
    ]
    _write_transcript(str(proj / 's.jsonl'), rows)
    files = qm.scan_transcripts(
        qm._ts_iso('2026-09-20T00:00:00Z'), projects_dir=str(tmp_path / 'projects'), cache_path=str(tmp_path / 'c.json')
    )['files']
    who = qm.classify(list(files.values())[0])
    assert who['lane'] == 'interactive' and who['tree'] is None


def test_tree_side_follows_the_slug_and_the_config(tmp_path):
    content = {'models': {}, 'tree': 'second-ledger-intro-take-5-plate-ring-re-40eb3c', 'cwd': '', 'entrypoint': None}
    infra = {'models': {}, 'tree': 'capabilities-default-tests-for-the-45-re-a6efef', 'cwd': '', 'entrypoint': None}
    eagle = {'models': {}, 'tree': 'zygomatic-ai-intro-v4-take-7-at-the-torn-81d1ca', 'cwd': '', 'entrypoint': None}
    unknown = {'models': {}, 'tree': 'some-tree-about-nothing-abc123', 'cwd': '', 'entrypoint': None}
    assert qm.classify(content)['side'] == 'production'
    assert qm.classify(infra)['side'] == 'infrastructure'
    assert qm.classify(eagle)['side'] == 'production'  # "-intro-" matches across the dashes
    assert qm.classify(unknown)['side'] == 'infrastructure'  # tree_default
    # the operator's own keyword wins, and only the key they set is overridden
    lanes = dict(qm.DEFAULT_LANES, tree_content=['nothing'])
    assert qm.classify(unknown, lanes)['side'] == 'production'
    assert qm.classify(content, lanes)['side'] == 'infrastructure'


def test_headless_only_keeps_an_editor_out_of_a_workflow_directory(tmp_path):
    """Vicky's cwd IS Medusa's own folder: an editor opened there must not read as her."""
    vicky = {'models': {}, 'tree': None, 'cwd': '/home/x/Zygomatic/medusa', 'entrypoint': 'sdk-cli'}
    me = {'models': {}, 'tree': None, 'cwd': '/home/x/Zygomatic/medusa', 'entrypoint': 'claude-vscode'}
    assert qm.classify(vicky)['label'] == 'Vicky (Medusa)'
    assert qm.classify(me)['lane'] == 'interactive'


def test_lane_costs_sum_back_to_the_model_total(corpus):
    """The lane split and the model split cut the same messages, so they must price the
    same; and the subscription value attributed to lanes must not exceed Claude Code's."""
    projects, cache = corpus
    files = qm.scan_transcripts(qm._ts_iso('2026-09-10T00:00:00Z'), projects_dir=projects, cache_path=cache)['files']
    start, end = qm._ts_iso('2026-09-17T00:00:00Z'), qm._ts_iso('2026-09-18T00:00:00Z')
    week = qm.aggregate(files, start, end)
    lanes = qm.aggregate_lanes(files, start, end)
    cfg = qm.load_config()
    sample = {
        'seven_day': {'pct': 10.0, 'window_started_at': start, 'resets_at': end},
        'five_hour': {'pct': 1.0},
        'surfaces': {'claude_code': 100},
    }
    calc = qm.compute(cfg, sample, week, {}, end, lanes)
    L = calc['lanes']
    assert L['api_usd'] == pytest.approx(calc['api_usd'], rel=1e-6)
    assert L['unclassified_api_usd'] == 0
    assert sum(r['api_usd'] for r in L['rows']) == pytest.approx(calc['api_usd'], rel=1e-6)
    sides = L['sides']
    assert sides['production']['share'] + sides['infrastructure']['share'] == pytest.approx(1.0, abs=1e-4)
    assert sides['production']['subscription_eur'] + sides['infrastructure']['subscription_eur'] == pytest.approx(
        calc['consumed_claude_code'], abs=0.01
    )
    assert L['production_pct'] == sides['production']['pct']


def test_cache_from_an_older_build_is_not_reused(tmp_path):
    """The cache is keyed on mtime+size alone, so an entry parsed before lanes existed would
    be reused forever and classify as unknown. A version bump must discard it."""
    cache = tmp_path / 'c.json'
    cache.write_text(
        json.dumps({'version': qm.CACHE_VERSION - 1, 'entries': {'/x.jsonl': {'sig': [1, 2], 'data': {'models': {}}}}})
    )
    assert qm._read_cache_at(str(cache)) == {}
    cache.write_text(
        json.dumps({'version': qm.CACHE_VERSION, 'entries': {'/x.jsonl': {'sig': [1, 2], 'data': {'models': {}}}}})
    )
    assert list(qm._read_cache_at(str(cache))) == ['/x.jsonl']
