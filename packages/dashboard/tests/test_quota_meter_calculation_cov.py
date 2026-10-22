# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Coverage for zyg_dashboard.quota_meter.calculation.

Everything runs offline: the credentials file, the sample ledger and the status file are
redirected to tmp_path, `urllib.request.urlopen` and the module's own `fetch_usage` /
`scan_transcripts` seams are monkeypatched, and the arithmetic (parse_usage_payload,
compute, _lane_split, _implied_rates, report) is exercised with canned payloads.
"""

from __future__ import annotations

import io
import json
import os
import urllib.error
from datetime import datetime, timezone

import pytest

from zyg_dashboard.quota_meter import calculation as M
from zyg_dashboard.quota_meter.pricing import QuotaError

WEEK = M.WEEK
DAY = M.DAY
NOW = 1766000000.0  # a fixed instant; every ISO literal below is derived from it
M1, M2, M3 = 'claude-opus-4-6', 'claude-haiku-4-5', 'claude-sonnet-5'  # $5 / $1 / $2 per MTok in
MX = 'gpt-nope'  # no price row
# billing by 7 days at 100 makes the weekly price exactly 100 and one point exactly 1
CFG = {
    'subscription_price': 100.0,
    'currency': 'EUR',
    'billing': 'days',
    'billing_days': 7,
    'eur_per_usd': 0.5,
    'plan_label': 'Claude Max 20x',
    'sample_max_age_s': 900,
    'lanes': None,
}


def _iso(t):  # a tz-aware ISO string that _ts_iso round-trips exactly
    return datetime.fromtimestamp(t, timezone.utc).isoformat()


def _boom(*_a, **_kw):
    raise AssertionError('this seam must not be reached')


def _raiser(exc):
    def _go(*_a, **_kw):
        raise exc

    return _go


def _file(t, model=M1, messages=2, cwd='/home/x'):  # one parse_transcript result
    vec = [1_000_000, 0, 0, 0, 0, 0, messages]
    return {
        'models': {model: {str(int(t // 300)): vec}},
        'first': t,
        'last': t,
        'messages': messages,
        'cwd': cwd,
        'entrypoint': 'cli',
        'tree': None,
        'task': None,
    }


def _lane(models, side='production', lane='production', label='Documentary', tree=None, sessions=1):
    return {(lane, side, label): {'models': models, 'usage': {'messages': 4}, 'sessions': sessions, 'tree': tree}}


def _roll(usd, eur, share, pct, sub):  # the five keys every _lane_split roll-up carries
    return {'api_usd': usd, 'api_eur': eur, 'share': share, 'pct': pct, 'subscription_eur': sub}


def _status(ok, samples, tier, err=None, err_ts=None):  # report()'s status block
    return {'last_ok': ok, 'last_error': err, 'last_error_ts': err_ts, 'samples': samples, 'tier': tier}


def _sample_row(util=40.0, ws=NOW - WEEK / 2, reset=NOW + WEEK / 2, surfaces=None, five=None):
    return {
        'ts': NOW,
        'seven_day': {'pct': util, 'resets_at': reset, 'window_started_at': ws},
        'five_hour': {'pct': 7.5, 'resets_at': NOW + 3600} if five is None else five,
        'surfaces': {'claude_code': 50.0} if surfaces is None else surfaces,
    }


class _Resp:  # the context manager urlopen hands back
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def read(self):
        return self._body


class _BadFp(io.BytesIO):  # an HTTPError whose body cannot be read
    def read(self, *_a, **_kw):
        raise OSError('socket gone')


@pytest.fixture
def meter_paths(tmp_path, monkeypatch):
    cred = tmp_path / 'cred.json'
    cred.write_text(
        json.dumps({'claudeAiOauth': {'accessToken': 'tok-xyz', 'rateLimitTier': 'max_20x'}}), encoding='utf-8'
    )
    monkeypatch.setattr(M, 'CRED_PATH', str(cred))
    monkeypatch.setattr(M, 'SAMPLES_PATH', str(tmp_path / 'rt' / 'quota_samples.jsonl'))
    monkeypatch.setattr(M, 'STATUS_PATH', str(tmp_path / 'rt' / 'quota_meter_status.json'))
    monkeypatch.setattr(M, 'USAGE_URL', 'https://usage.example.org/api/oauth/usage')
    return tmp_path


# ── the login ────────────────────────────────────────────────────────────────


def test_credentials_accepts_a_live_token(meter_paths):
    (meter_paths / 'cred.json').write_text(
        json.dumps({'claudeAiOauth': {'accessToken': 'tok-xyz', 'expiresAt': 4_000_000_000_000}}), encoding='utf-8'
    )
    assert M._credentials()['accessToken'] == 'tok-xyz'


def test_credentials_rejects_every_broken_login(meter_paths):
    cred = meter_paths / 'cred.json'
    cases = [(None, 'no Claude login credentials')]
    cases += [('{ not json', 'no Claude login credentials'), ('null', 'no OAuth access token')]
    cases += [('{}', 'no OAuth access token'), ('{"claudeAiOauth": {"accessToken": ""}}', 'no OAuth access token')]
    cases += [('{"claudeAiOauth": {"accessToken": "t", "expiresAt": 1000000000000}}', 'the OAuth token expired at')]
    for text, want in cases:
        if text is None:
            cred.unlink()
        else:
            cred.write_text(text, encoding='utf-8')
        with pytest.raises(QuotaError, match=want):
            M._credentials()


# ── fetch_usage ──────────────────────────────────────────────────────────────


def test_fetch_usage_sends_the_bearer_token_and_parses_the_payload(meter_paths, monkeypatch):
    seen = []
    monkeypatch.setattr(
        M.urllib.request,
        'urlopen',
        lambda req, timeout=None: seen.append((req, timeout)) or _Resp(b'{"five_hour": {"utilization": 12}}'),
    )
    assert M.fetch_usage(timeout=3.0) == {'five_hour': {'utilization': 12}}
    req, timeout = seen[0]
    assert timeout == 3.0
    assert req.full_url == M.USAGE_URL
    assert req.get_header('Authorization') == 'Bearer tok-xyz'
    assert req.get_header('Anthropic-beta') == M.OAUTH_BETA
    assert req.get_header('User-agent') == 'zygomatic-quota-meter/1'


def test_fetch_usage_refuses_to_leak_the_token_to_a_non_http_url(meter_paths, monkeypatch):
    monkeypatch.setattr(M.urllib.request, 'urlopen', _boom)
    for url, want in (('file:///etc/passwd', 'to a file URL'), ('usage.example.org/u', 'to a scheme-less URL')):
        monkeypatch.setattr(M, 'USAGE_URL', url)
        with pytest.raises(QuotaError, match=want):
            M.fetch_usage()


def test_fetch_usage_maps_an_http_error_with_a_body(meter_paths, monkeypatch):
    err = urllib.error.HTTPError(M.USAGE_URL, 429, 'Too Many Requests', {}, io.BytesIO(b'slow down'))
    monkeypatch.setattr(M.urllib.request, 'urlopen', _raiser(err))
    with pytest.raises(QuotaError, match='answered HTTP 429: slow down'):
        M.fetch_usage()


def test_fetch_usage_falls_back_to_the_reason_when_the_body_is_unreadable(meter_paths, monkeypatch):
    err = urllib.error.HTTPError(M.USAGE_URL, 503, 'Service Unavailable', {}, _BadFp(b''))
    monkeypatch.setattr(M.urllib.request, 'urlopen', _raiser(err))
    with pytest.raises(QuotaError, match='answered HTTP 503: Service Unavailable'):
        M.fetch_usage()


def test_fetch_usage_maps_an_unreachable_endpoint_and_a_junk_payload(meter_paths, monkeypatch):
    monkeypatch.setattr(M.urllib.request, 'urlopen', _raiser(urllib.error.URLError('no route')))
    with pytest.raises(QuotaError, match='usage endpoint unreachable: URLError'):
        M.fetch_usage()
    monkeypatch.setattr(M.urllib.request, 'urlopen', lambda req, timeout=None: _Resp(b'<html>nope</html>'))
    with pytest.raises(QuotaError, match='usage endpoint unreachable: JSONDecodeError'):
        M.fetch_usage()


# ── parse_usage_payload ──────────────────────────────────────────────────────


def test_parse_usage_payload_on_an_empty_payload():
    assert M.parse_usage_payload({}, now=NOW) == {
        'ts': NOW,
        'five_hour': {'pct': None, 'resets_at': None},
        'seven_day': {'pct': None, 'resets_at': None, 'window_started_at': None},
        'scoped': [],
        'surfaces': {},
        'extra_usage_enabled': False,
        'tier': None,
        'raw_keys': [],
    }


def test_parse_usage_payload_defaults_now_to_the_clock(monkeypatch):
    monkeypatch.setattr(M.time, 'time', lambda: 1234.5)
    assert M.parse_usage_payload({})['ts'] == 1234.5


def test_parse_usage_payload_derives_the_window_start_from_the_reset():
    reset = NOW + DAY
    row = M.parse_usage_payload({'seven_day': {'utilization': 50, 'resets_at': _iso(reset)}}, now=NOW)
    assert row['seven_day'] == {'pct': 50.0, 'resets_at': reset, 'window_started_at': reset - WEEK}
    assert row['raw_keys'] == ['seven_day']


def test_parse_usage_payload_keeps_every_scoped_limit_that_is_not_a_roll_up():
    reset = NOW + 2 * DAY
    limits = ['not-a-dict', {'kind': 'session'}, {'kind': 'weekly_all'}]
    limits += [
        {
            'kind': 'opus_weekly',
            'scope': {'model': {'display_name': 'Opus 4.6', 'id': M1}},
            'percent': 42,
            'resets_at': _iso(reset),
            'severity': 'warn',
        },
        {'kind': 'by_id', 'scope': {'model': {'id': M1}}, 'percent': 'oops'},
        {'kind': 'by_surface', 'scope': {'surface': 'cowork'}},
        {'kind': 'bare', 'scope': 'not-a-dict'},
    ]
    payload = {
        'five_hour': {'utilization': 12.5, 'resets_at': _iso(NOW + 3600)},
        'seven_day': {'utilization': 100, 'resets_at': _iso(reset)},
        'seven_day_breakdown': {
            'window_started_at': _iso(NOW - DAY),
            'rows': ['junk', {'nokey': 1}, {'key': 'claude_code', 'percent': 80}, {'key': 'claude_ai'}],
        },
        'limits': limits,
        'extra_usage': {'is_enabled': True},
        'dropped': None,
    }
    row = M.parse_usage_payload(payload, now=NOW, tier='max_20x')
    assert row['five_hour'] == {'pct': 12.5, 'resets_at': NOW + 3600}
    assert row['seven_day'] == {'pct': 100.0, 'resets_at': reset, 'window_started_at': NOW - DAY}
    assert row['surfaces'] == {'claude_code': 80.0, 'claude_ai': 0.0}
    assert row['extra_usage_enabled'] is True and row['tier'] == 'max_20x'
    assert row['raw_keys'] == ['extra_usage', 'five_hour', 'limits', 'seven_day', 'seven_day_breakdown']
    assert row['scoped'] == [
        {'kind': 'opus_weekly', 'name': 'Opus 4.6', 'pct': 42.0, 'resets_at': reset, 'severity': 'warn'},
        {'kind': 'by_id', 'name': M1, 'pct': None, 'resets_at': None, 'severity': None},
        {'kind': 'by_surface', 'name': 'cowork', 'pct': None, 'resets_at': None, 'severity': None},
        {'kind': 'bare', 'name': 'bare', 'pct': None, 'resets_at': None, 'severity': None},
    ]


# ── the ledger and the status file ───────────────────────────────────────────


def test_sample_ledger_round_trips_and_skips_junk_lines(meter_paths):
    M._append_sample({'ts': NOW, 'v': 1})
    M._append_sample({'ts': NOW + 60, 'v': 2})
    with open(M.SAMPLES_PATH, 'a', encoding='utf-8') as fh:
        fh.write('not json at all\n[1, 2]\n')
    M._append_sample({'ts': NOW + 120, 'v': 3})
    assert [r['v'] for r in M.read_samples()] == [1, 2, 3]
    assert [r['v'] for r in M.read_samples(since=NOW + 60)] == [2, 3]
    assert [r['v'] for r in M.read_samples(limit=1)] == [3]


def test_read_samples_and_read_status_without_any_files(meter_paths):
    assert M.read_samples() == []
    assert M.read_status() == {}


def test_write_status_merges_fields_and_survives_an_unreadable_file(meter_paths):
    M._write_status(a=1)
    M._write_status(b=2)
    assert M.read_status() == {'a': 1, 'b': 2}
    with open(M.STATUS_PATH, 'w', encoding='utf-8') as fh:
        fh.write('{ oops')
    M._write_status(c=3)
    assert M.read_status() == {'c': 3}


def test_write_status_keeps_the_old_values_when_the_file_cannot_be_written(meter_paths, monkeypatch):
    blocked = meter_paths / 'blocked' / 'status.json'
    os.makedirs(blocked, exist_ok=True)  # a directory where the JSON belongs
    monkeypatch.setattr(M, 'STATUS_PATH', str(blocked))
    M._write_status(a=1)  # read fails, then os.replace onto a directory fails
    assert M.read_status() == {}


# ── sample() ─────────────────────────────────────────────────────────────────


def test_sample_appends_a_row_and_records_the_status(meter_paths, monkeypatch):
    payload = {
        'five_hour': {'utilization': 10},
        'seven_day': {'utilization': 20, 'resets_at': _iso(NOW + DAY)},
    }
    monkeypatch.setattr(M, 'fetch_usage', lambda: payload)
    row = M.sample(NOW)
    assert row['tier'] == 'max_20x' and row['ts'] == NOW
    assert M.read_samples() == [row]
    assert M.read_status() == {
        'last_ok_ts': NOW,
        'last_error': None,
        'last_error_ts': None,
        'tier': 'max_20x',
        'seven_day_pct': 20.0,
        'five_hour_pct': 10.0,
    }


def test_sample_falls_back_to_the_subscription_type_and_the_clock(meter_paths, monkeypatch):
    (meter_paths / 'cred.json').write_text(
        json.dumps({'claudeAiOauth': {'accessToken': 't', 'subscriptionType': 'max'}}), encoding='utf-8'
    )
    monkeypatch.setattr(M, 'fetch_usage', dict)
    monkeypatch.setattr(M.time, 'time', lambda: 999.0)
    assert M.sample()['tier'] == 'max'
    assert M.read_status()['last_ok_ts'] == 999.0


def test_sample_records_the_error_and_re_raises_it(meter_paths):
    (meter_paths / 'cred.json').unlink()
    with pytest.raises(QuotaError, match='no Claude login credentials'):
        M.sample(NOW)
    status = M.read_status()
    assert 'no Claude login credentials' in status['last_error'] and status['last_error_ts'] == NOW
    assert M.read_samples() == []


# ── compute() and the lane split ─────────────────────────────────────────────


def test_compute_prices_the_week_against_the_subscription():
    week = {M1: {'input': 1_000_000}, M2: {'input': 1_000_000}, MX: {'input': 5}}
    lanes = _lane({M1: {'input': 1_000_000}})
    lanes.update(_lane({M2: {'input': 1_000_000}}, side='infrastructure', lane='interactive', label='/home/x'))
    out = M.compute(CFG, _sample_row(), week, {M3: {'input': 1_000_000}, MX: {'input': 1}}, NOW, lanes)
    assert (out['weekly_price'], out['price_per_pct']) == (100.0, 1.0)
    assert out['utilization_pct'] == 40.0
    assert out['window_started_at'] == NOW - WEEK / 2 and out['resets_at'] == NOW + WEEK / 2
    assert (out['consumed'], out['consumed_claude_code']) == (40.0, 20.0)
    assert (out['consumed_other_surfaces'], out['remaining']) == (20.0, 60.0)
    assert out['claude_code_share'] == 0.5 and out['elapsed_fraction'] == 0.5
    assert (out['projected_utilization_pct'], out['projected_api_usd']) == (80.0, 12.0)
    assert (out['api_usd'], out['api_eur']) == (6.0, 3.0)
    assert out['pct_per_api_usd'] == round(40 / 6, 4)
    assert out['eur_per_api_usd'] == round(20 / 6, 4)
    assert out['subscription_cheaper'] is False
    assert out['unpriced_models'] == [MX]
    cols = ('model', 'api_usd', 'share', 'api_eur', 'subscription_eur')
    assert set(out['models'][0]) == {*cols, 'usage'} and set(out['models'][1]) == {*cols, 'usage'}
    assert [tuple(r[c] for c in cols) for r in out['models']] == [
        (M1, 5.0, 0.8333, 2.5, 16.6667),
        (M2, 1.0, 0.1667, 0.5, 3.3333),
    ]
    assert [r['usage'] for r in out['models']] == [{'input': 1_000_000}] * 2
    assert out['session'] == {
        'utilization_pct': 7.5,
        'resets_at': NOW + 3600,
        'api_usd': 2.0,
        'models': [{'model': M3, 'usage': {'input': 1_000_000}, 'api_usd': 2.0}],
    }
    lanes_out = out['lanes']
    assert (lanes_out['api_usd'], lanes_out['production_pct'], lanes_out['unclassified_api_usd']) == (6.0, 83.3, 0.0)
    assert [r['label'] for r in lanes_out['rows']] == ['Documentary', '/home/x']
    assert lanes_out['rows'][0] == {
        'lane': 'production',
        'side': 'production',
        'label': 'Documentary',
        'tree': None,
        'sessions': 1,
        'usage': {'messages': 4},
        'api_usd': 5.0,
        'share': 0.8333,
        'api_eur': 2.5,
        'subscription_eur': 16.6667,
    }
    assert lanes_out['sides']['infrastructure'] == _roll(1.0, 0.5, 0.1667, 16.7, 3.3333)
    assert lanes_out['by_lane']['session_tree'] == _roll(0.0, 0.0, 0.0, 0.0, 0.0)


def test_compute_without_a_sample_or_any_priced_usage():
    out = M.compute(CFG, None, {MX: {'input': 10}}, {MX: {'input': 10}}, NOW, None)
    empty = (
        'utilization_pct window_started_at resets_at elapsed_fraction consumed consumed_claude_code '
        'consumed_other_surfaces remaining projected_utilization_pct projected_api_usd pct_per_api_usd '
        'eur_per_api_usd subscription_cheaper'
    ).split()
    assert [k for k in empty if out[k] is not None] == []
    assert (out['api_usd'], out['api_eur'], out['claude_code_share']) == (0.0, 0.0, 1.0)
    assert out['unpriced_models'] == [MX] and out['models'] == []
    assert out['session'] == {'utilization_pct': None, 'resets_at': None, 'api_usd': 0.0, 'models': []}
    assert out['lanes']['rows'] == [] and out['lanes']['production_pct'] is None
    assert out['lanes']['unclassified_api_usd'] == 0.0


def test_compute_clamps_the_elapsed_fraction_at_both_ends():
    old = M.compute(CFG, _sample_row(ws=NOW - 3 * WEEK), {}, {}, NOW)
    assert old['elapsed_fraction'] == 1.0 and old['projected_utilization_pct'] == 40.0
    future = M.compute(CFG, _sample_row(ws=NOW + WEEK), {}, {}, NOW)
    assert future['elapsed_fraction'] == 0.0  # 1e-6 rounded to four places
    assert future['projected_utilization_pct'] == 40000000.0


def test_compute_reads_the_claude_code_surface_share():
    cases = [({}, 1.0), ({'claude_ai': 100.0}, 1.0), ({'claude_code': None}, 1.0)]
    cases += [({'claude_code': 25.0}, 0.25), ({'claude_code': 100}, 1.0)]
    for surfaces, want in cases:
        out = M.compute(CFG, _sample_row(surfaces=surfaces), {}, {}, NOW)
        assert out['claude_code_share'] == want, surfaces
        assert out['consumed_claude_code'] == round(40.0 * want, 4), surfaces


def test_compute_says_the_subscription_is_cheaper_when_it_is():
    # 1 % of a 100 EUR week against $40 of API-equivalent work
    out = M.compute(CFG, _sample_row(util=1.0, surfaces={}), {M1: {'input': 8_000_000}}, {}, NOW)
    assert out['api_usd'] == 40.0
    assert out['eur_per_api_usd'] == 0.025 and out['subscription_cheaper'] is True


def test_lane_split_falls_back_to_the_lane_total_when_the_week_is_unpriced():
    out = M._lane_split(_lane({M1: {'input': 1_000_000}}, tree='kids-music-intro'), 0.0, 10.0, 0.5)
    assert out['api_usd'] == 5.0 and out['production_pct'] == 100.0
    assert out['rows'][0]['share'] == 1.0 and out['rows'][0]['subscription_eur'] == 10.0
    assert out['rows'][0]['tree'] == 'kids-music-intro'
    assert out['unclassified_api_usd'] == 0.0


def test_lane_split_without_a_consumed_value_and_with_an_unknown_side():
    lanes = _lane({M1: {'input': 1_000_000}})
    lanes.update(_lane({M2: {'input': 1_000_000}}, side='mystery', lane='other', label='Hm'))
    out = M._lane_split(lanes, 10.0, None, 1.0)
    assert [r['subscription_eur'] for r in out['rows']] == [None, None]
    assert out['sides']['mystery'] == _roll(1.0, 1.0, 0.1, 10.0, None)
    assert out['by_lane']['other']['api_usd'] == 1.0
    assert out['unclassified_api_usd'] == 4.0


def test_lane_split_of_nothing_at_all():
    out = M._lane_split(None, 0.0, None, 0.5)
    assert out['rows'] == [] and out['api_usd'] == 0.0
    assert out['sides']['production'] == _roll(0.0, 0.0, None, None, None)


# ── history and implied rates ────────────────────────────────────────────────


def test_history_lists_one_point_per_sample():
    rows = [{'ts': NOW, 'seven_day': {'pct': 10.0}, 'five_hour': {'pct': 1.0}}]
    rows += [{'ts': NOW + 600, 'seven_day': None, 'five_hour': {}}]
    hist = M._history(rows)
    assert hist['ts'] == [NOW, NOW + 600]
    assert hist['seven_day_pct'] == [10.0, None] and hist['five_hour_pct'] == [1.0, None]
    assert len(hist['labels']) == 2 and all('T' in label for label in hist['labels'])


def test_implied_rates_pairs_consecutive_samples_inside_one_window():
    ws = NOW - WEEK / 2
    files = {'/p/a.jsonl': _file(NOW + 300)}
    rows = [{'ts': NOW - 1800, 'seven_day': {'pct': 5.0}}]  # no window start
    rows += [{'ts': NOW - 1200, 'seven_day': {}}]  # no percentage
    rows += [{'ts': NOW - 600, 'seven_day': {'pct': 8.0, 'window_started_at': ws}}]  # nothing before it
    rows += [{'ts': NOW, 'seven_day': {'pct': 10.0, 'window_started_at': ws}}]  # no transcripts in between
    rows += [{'ts': NOW + 600, 'seven_day': {'pct': 20.0, 'window_started_at': ws}}]  # the one real pair
    rows += [{'ts': NOW + 1200, 'seven_day': {'pct': 30.0, 'window_started_at': ws + 1}}]  # a new window
    rows += [{'ts': NOW + 1800, 'seven_day': {'pct': 30.0, 'window_started_at': ws + 1}}]  # no delta
    assert M._implied_rates(rows, files) == [
        {'from': NOW, 'to': NOW + 600, 'delta_pct': 10.0, 'api_usd': 5.0, 'pct_per_usd': 2.0}
    ]


# ── report() ─────────────────────────────────────────────────────────────────


@pytest.fixture
def scan(meter_paths, monkeypatch):
    out = {'files': {}, 'parsed_now': 1, 'skipped': 0, 'errors': ['a.jsonl: ValueError: nope']}
    monkeypatch.setattr(M, 'load_config', lambda: dict(CFG))
    monkeypatch.setattr(M, 'scan_transcripts', lambda since, projects_dir=None: out)
    return out


def test_report_uses_the_latest_sample_when_it_is_fresh(scan, monkeypatch):
    row = M.parse_usage_payload(
        {
            'seven_day': {'utilization': 40, 'resets_at': _iso(NOW + WEEK / 2)},
            'five_hour': {'utilization': 5, 'resets_at': _iso(NOW + 3600)},
            'seven_day_breakdown': {'rows': [{'key': 'claude_code', 'percent': 100}]},
        },
        NOW - 60,
        tier='max_20x',
    )
    M._append_sample(row)
    M._write_status(last_ok_ts=NOW - 60, tier='max_20x', last_error=None, last_error_ts=None)
    monkeypatch.setattr(M, 'fetch_usage', _boom)  # a fresh sample must not trigger a fetch
    scan['files'] = {'/p/a.jsonl': _file(NOW - 3600), '/p/b.jsonl': _file(NOW - 3600, model=MX)}
    out = M.report(days=7, now=NOW)
    assert out['sample'] == row and out['sample_age_s'] == 60
    assert out['status'] == _status(NOW - 60, 1, 'max_20x')
    cfg_keys = 'subscription_price currency billing billing_days eur_per_usd plan_label'.split()
    assert out['config'] == {k: CFG[k] for k in cfg_keys}
    assert out['week']['utilization_pct'] == 40.0 and out['week']['claude_code_share'] == 1.0
    assert out['week']['api_usd'] == 5.0
    assert out['week']['lanes']['by_lane']['interactive']['api_usd'] == 5.0
    assert (out['range']['days'], out['range']['requested_days']) == (7, 7)
    assert [r['model'] for r in out['range']['models']] == [M1, MX]
    first, second = out['range']['models']
    assert set(first) == {'model', 'usage', 'api_usd', 'api_eur'}
    assert (first['model'], first['api_usd'], first['api_eur']) == (M1, 5.0, 2.5)
    assert second['api_usd'] is None and second['api_eur'] is None
    assert out['range']['api_usd'] == 5.0 and len(out['range']['daily']['keys']) == 8
    assert out['history']['ts'] == [NOW - 60] and out['implied_rates'] == []
    sc = out['scan']
    assert (sc['files'], sc['parsed_now'], sc['from_cache'], sc['messages']) == (2, 1, 0, 4)
    assert sc['errors'] == ['a.jsonl: ValueError: nope'] and sc['projects_dir'] == M.PROJECTS_DIR
    assert out['pricing'][0]['model_prefix'] == M.PRICING[0][0]
    assert out['pricing'][0]['cache_read'] == M.PRICING[0][5]
    assert out['legacy_cli']['unknown_model_rates'] == M.LEGACY_CLI_UNKNOWN_MODEL
    assert len(out['notes']) == 7
    assert out['notes'][3] == (
        'Subscription: Claude Max 20x at 100 EUR per 7 days = 100.00 EUR per Claude week; '
        'one utilization point = 1.000 EUR.'
    )


def test_report_notes_a_failed_fetch_and_an_empty_ledger(scan, monkeypatch):
    monkeypatch.setattr(M, 'fetch_usage', _raiser(QuotaError('usage endpoint unreachable: boom')))
    out = M.report(days=0, now=NOW)
    assert out['sample'] is None and out['sample_age_s'] is None
    assert (out['range']['days'], out['range']['requested_days']) == (M.SCAN_CAP_DAYS, 0)
    assert out['status'] == _status(None, 0, None)
    assert out['notes'][0].startswith("No sample of Claude's meter yet")
    assert out['notes'][1] == 'Live fetch failed: usage endpoint unreachable: boom. Showing the last sample.'
    assert len(out['notes']) == 9
    assert out['week']['utilization_pct'] is None
    assert out['history']['ts'] == [] and out['range']['models'] == []
    # the error did reach the status file, it is just read before the fetch is attempted
    assert M.read_status()['last_error'] == 'usage endpoint unreachable: boom'


def test_report_fetches_when_the_sample_is_stale(scan, monkeypatch):
    M._append_sample(M.parse_usage_payload({}, NOW - 5000))
    payload = {
        'seven_day': {'utilization': 60, 'resets_at': _iso(NOW + 100)},
        'five_hour': {'utilization': 9, 'resets_at': _iso(NOW + 7200)},
    }
    monkeypatch.setattr(M, 'fetch_usage', lambda: payload)
    scan['files'] = {'/p/a.jsonl': _file(NOW - 600)}
    out = M.report(days=1000, now=NOW)
    assert out['range']['days'] == M.SCAN_CAP_DAYS
    assert out['week']['utilization_pct'] == 60.0 and out['week']['api_usd'] == 5.0
    assert out['week']['session']['api_usd'] == 5.0  # the 5-hour window ends at resets_at - 5 h
    assert out['status']['last_ok'] == NOW and out['status']['samples'] == 2
    assert out['sample_age_s'] == 0
    assert out['notes'][0].startswith('Utilization percentages are')


def test_report_prints_the_calendar_month_note_and_the_default_windows(scan, monkeypatch):
    monkeypatch.setattr(M, 'load_config', lambda: dict(CFG, billing='month'))
    monkeypatch.setattr(M, 'fetch_usage', dict)
    out = M.report(days=7, now=NOW, fresh=True, projects_dir='/p/elsewhere')
    assert 'per calendar month = ' in out['notes'][3]
    assert out['scan']['projects_dir'] == '/p/elsewhere'
    assert out['week']['weekly_price'] == pytest.approx(8400 / 365.25, abs=5e-5)
    assert out['week']['utilization_pct'] is None and out['sample_age_s'] == 0
