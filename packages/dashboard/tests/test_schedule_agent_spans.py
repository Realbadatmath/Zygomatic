# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Agent sessions on the GPU/CPU schedule + multi-day history (2026-09-05).

Two defects this file pins:
1. The schedule pages had no record of Claude Code sessions' hardware use —
   the Live Tail showed it live and forgot it.  agent_activity now writes one
   ledger line per closed activity span and schedule_service turns those into
   kind='agent' entries (orange bars).
2. A stage that crossed midnight (creature Sheet Review 18:07 → 14:53 next
   day) was indexed under its START day only, so the next day's page never
   showed it, while the first day's page drew it past the bottom of the grid.
"""

import json
import os
import sys
from collections import deque

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

from zyg_dashboard import schedule_service as ss  # noqa: E402

aa = pytest.importorskip('agent_activity')


def _fake_session(sid, vram=0.0, cpu=0.0, ram=0.0, busy_cmd='python train.py'):
    return {
        'id': sid,
        'name': f'zygomatics-zero-{sid[:2]}',
        'project': 'crews',
        'cwd': '/x',
        'entrypoint': 'claude-vscode',
        'kind': 'interactive',
        'alive': True,
        'vram_mb': vram,
        'cpu_pct': cpu,
        'ram_mb': ram,
        'events': deque(maxlen=50),
        'procs': [
            {'pid': 1, 'cmd': busy_cmd, 'kind': 'train', 'busy': True, 'vram_mb': vram, 'cpu_pct': cpu, 'rss_mb': ram}
        ],
    }


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    led = tmp_path / 'ledger.jsonl'
    opn = tmp_path / 'open.json'
    monkeypatch.setattr(aa, '_LEDGER_FILE', str(led))
    monkeypatch.setattr(aa, '_OPEN_SPANS_FILE', str(opn))
    monkeypatch.setattr(aa, '_SPAN_GRACE_S', 100.0)
    monkeypatch.setattr(aa, '_SPAN_MIN_S', 30.0)
    monkeypatch.setattr(aa, '_spans', {})
    monkeypatch.setattr(aa, '_sessions', {})
    monkeypatch.setattr(ss, '_AGENT_LEDGER', str(led))
    monkeypatch.setattr(ss, '_AGENT_OPEN', str(opn))
    monkeypatch.setattr(ss, '_agent_mem', {'sig': None, 'spans': []})
    return led, opn


def _lines(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def test_gpu_span_opens_survives_grace_gap_and_is_written_once(ledger):
    led, opn = ledger
    t0 = 1_800_000_000.0
    aa._sessions['abc12345'] = _fake_session('abc12345', vram=4096)
    with aa._lock:
        aa._track_spans(t0)
        assert ('abc12345', 'gpu') in aa._spans
        assert ('abc12345', 'cpu') not in aa._spans  # VRAM only → gpu span only
        # idle for less than the grace period: the span stays open
        aa._sessions['abc12345']['vram_mb'] = 0.0
        aa._track_spans(t0 + 50)
        assert ('abc12345', 'gpu') in aa._spans
        # busy again: same span, no second line
        aa._sessions['abc12345']['vram_mb'] = 8192
        aa._track_spans(t0 + 80)
        # then idle past the grace → closed at the LAST busy sample, not at now
        aa._sessions['abc12345']['vram_mb'] = 0.0
        aa._track_spans(t0 + 80 + 101)
    assert ('abc12345', 'gpu') not in aa._spans
    recs = _lines(str(led))
    assert len(recs) == 1
    r = recs[0]
    assert r['device'] == 'gpu'
    assert r['start_ts'] == pytest.approx(t0)
    assert r['end_ts'] == pytest.approx(t0 + 80)
    assert r['peak_vram_mb'] == 8192
    assert r['name'] == 'zygomatics-zero-ab'
    assert r['cmds'] == ['python train.py']


def test_short_blips_are_not_logged(ledger):
    led, _ = ledger
    t0 = 1_800_000_000.0
    aa._sessions['s1'] = _fake_session('s1', cpu=900)
    with aa._lock:
        aa._track_spans(t0)
        aa._sessions['s1']['cpu_pct'] = 0.0
        aa._track_spans(t0 + 10)  # busy for 10 s only
        aa._track_spans(t0 + 10 + 200)  # past grace → close
    assert _lines(str(led)) == []


def test_open_spans_are_mirrored_and_recovered_on_restart(ledger):
    led, opn = ledger
    t0 = 1_800_000_000.0
    aa._sessions['s2'] = _fake_session('s2', cpu=1200)
    with aa._lock:
        aa._track_spans(t0)
        aa._track_spans(t0 + 120)
        aa._flush_open_spans(t0 + 120, force=True)
    mirrored = json.load(open(opn))['spans']
    assert len(mirrored) == 1 and mirrored[0]['open'] and mirrored[0]['device'] == 'cpu'
    # the GUI sees the open span as a running agent entry on today's page
    day = ss.datetime.fromtimestamp(t0, tz=ss._AMS).strftime('%Y-%m-%d')
    ents = ss.agent_entries_for('cpu', [day], now=ss.datetime.fromtimestamp(t0 + 300, tz=ss._AMS))
    assert len(ents) == 1 and ents[0]['kind'] == 'agent' and ents[0]['open'] is True
    assert ents[0]['status'] == 'running'
    assert ents[0]['model'] == ss.AGENT_MODEL_SLUG
    # a server restart closes what was open instead of losing it
    aa._spans.clear()
    aa._recover_open_spans()
    recs = _lines(str(led))
    assert len(recs) == 1 and recs[0].get('recovered') is True
    assert json.load(open(opn))['spans'] == []


def test_agent_entries_carry_the_session_and_are_never_reserved(ledger):
    led, _ = ledger
    t0 = 1_800_000_000.0
    with open(led, 'w', encoding='utf-8') as fh:
        fh.write(
            json.dumps(
                {
                    'sid': 'deadbeef-1',
                    'name': 'zygomatics-zero-de',
                    'project': 'crews',
                    'entrypoint': 'claude-vscode',
                    'device': 'gpu',
                    'start_ts': t0,
                    'end_ts': t0 + 3600,
                    'peak_vram_mb': 20000,
                    'kinds': ['train'],
                    'cmds': ['/venv/bin/python train.py --lora'],
                }
            )
            + '\n'
        )
    day = ss.datetime.fromtimestamp(t0, tz=ss._AMS).strftime('%Y-%m-%d')
    e = ss.agent_entries_for('gpu', [day])[0]
    assert e['kind'] == 'agent' and e['reserved'] is False
    assert e['agent'] == 'zygomatics-zero-de' and e['session_id'] == 'deadbeef-1'
    assert 'train.py --lora' in e['label'] and '🕱' in e['label']
    assert e['device'] == 'gpu' and e['pipeline'] == 'agent'
    # the other scope does not see it
    assert ss.agent_entries_for('cpu', [day]) == []
    # a window that does not touch it does not see it
    assert ss.agent_entries_for('gpu', ['2001-01-01']) == []


def test_agent_lane_exists_on_both_pages():
    assert ss.model_pipelines('gpu').get(ss.AGENT_MODEL_SLUG) == ['agent']
    assert ss.model_pipelines('cpu').get(ss.AGENT_MODEL_SLUG) == ['agent']
    assert any(m['slug'] == ss.AGENT_MODEL_SLUG for m in ss.model_registry('gpu').values())
    assert any(m['slug'] == ss.AGENT_MODEL_SLUG for m in ss.model_registry('cpu').values())


def test_midnight_crossing_stage_is_indexed_under_both_days(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, '_RUNTIME', str(tmp_path))
    state = {
        'creature_id': 'd0e44ab002ad',
        'status': 'completed',
        'stage_timeline': [
            {
                'name': 'Sheet Review',
                'started_at': '2026-08-25T18:07:40+02:00',
                'ended_at': '2026-08-26T14:53:58+02:00',
                'status': 'completed',
            },
            {
                'name': 'LoRA Training',
                'started_at': '2026-08-26T14:53:58+02:00',
                'ended_at': '2026-08-26T15:15:58+02:00',
                'status': 'completed',
            },
        ],
    }
    (tmp_path / 'creature_gen_d0e44ab002ad.json').write_text(json.dumps(state))
    idx = ss._build_history_index()
    ids25 = {e['id'] for e in idx['2026-08-25']}
    ids26 = {e['id'] for e in idx['2026-08-26']}
    assert 'hist_creature_d0e44ab002ad_0' in ids25
    assert 'hist_creature_d0e44ab002ad_0' in ids26  # the defect: was missing
    assert 'hist_creature_d0e44ab002ad_1' not in ids25
    # the entry keeps its real start day so the page can place it relative to
    # the day being drawn
    e = next(x for x in idx['2026-08-26'] if x['id'] == 'hist_creature_d0e44ab002ad_0')
    assert e['date'] == '2026-08-25' and e['end_iso'].startswith('2026-08-26T14:53')
    assert ss._days_of(e) == ['2026-08-25', '2026-08-26']


def test_history_for_a_window_lists_a_multi_day_entry_once(monkeypatch):
    e = {
        'id': 'x',
        'device': 'gpu',
        'date': '2026-08-25',
        'start_iso': '2026-08-25T18:07:40+02:00',
        'end_iso': '2026-08-26T14:53:58+02:00',
    }
    monkeypatch.setattr(ss, '_history_index', lambda: {'2026-08-25': [e], '2026-08-26': [e]})
    monkeypatch.setattr(ss, '_archive_entries_for', lambda scope, day: [])
    out = ss.history_entries_for('gpu', ['2026-08-25', '2026-08-26'])
    assert [x['id'] for x in out] == ['x']
