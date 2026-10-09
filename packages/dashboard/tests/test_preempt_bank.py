# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Pre-Emptive generation bank (preempt_bank.py + the subscription_llm hooks). 2026-09-20.

Pinned: a record run writes every text turn to the entry's ledger and image turns are
never recorded; a replay run answers from the ledger — exact hash first, then the same
stage + prompt header once each — without spawning the CLI; a miss with policy 'never'
raises SubscriptionLimitError (the call site's local fallback), with 'always' it goes live;
entries move building → ready → claimed → consumed, a failed render returns the brain to
ready once; the song bank takes briefs oldest first; settings validate and persist.
"""

import importlib
import json
import os
import stat
import sys
import textwrap
import time

import pytest

FAKE_CLI = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    line = sys.stdin.readline()
    user = json.loads(line) if line.strip() else {}
    txt = ' '.join(b.get('text', '') for b in user.get('message', {}).get('content', []) if b.get('type') == 'text')
    n_img = sum(1 for b in user.get('message', {}).get('content', []) if b.get('type') == 'image')
    if os.environ.get('FAKE_CLI_MODE') == 'limit':
        print(json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'seven_day'}}))
        print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': "You've hit your weekly limit",
                          'session_id': 'sid-limit', 'usage': {}, 'num_turns': 0}))
        sys.exit(0)
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': 'LIVE:' + txt[:40] + ('|img' if n_img else ''),
                      'session_id': 'sid-1', 'num_turns': 1, 'duration_ms': 5, 'total_cost_usd': 0.0,
                      'usage': {'input_tokens': 3, 'output_tokens': 2}}))
    """)


@pytest.fixture
def env(tmp_path, monkeypatch):
    cli = tmp_path / 'claude'
    cli.write_text(FAKE_CLI)
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    cred = tmp_path / 'creds.json'
    cred.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'x'}}))
    monkeypatch.setenv('ZYG_SUBSCRIPTION_LLM_CLI', str(cli))
    monkeypatch.setenv('ZYG_CLAUDE_CREDENTIALS', str(cred))
    monkeypatch.setenv('ZYG_SUBSCRIPTION_LLM_DIR', str(tmp_path / 'cli'))
    monkeypatch.setenv('ZYG_PREEMPT_DIR', str(tmp_path / 'preempt'))
    monkeypatch.setenv('ZYG_APPROVAL_QUEUE_SETTINGS', str(tmp_path / 'aq.json'))
    monkeypatch.setenv('ZYG_METRICS_RUNTIME_DIR', str(tmp_path / 'runtime'))
    monkeypatch.delenv('FAKE_CLI_MODE', raising=False)
    # The modules read these env vars at import time, so they have to be dropped by their
    # real dotted names — popping the bare names left the already-imported copies in place
    # and every assertion below measured the previous run's directory.
    for m in (
        'zyg_workflows.subscription_llm',
        'zyg_workflows.llm_audit',
        'zyg_dashboard.preempt_bank',
        'zyg_dashboard.approval_queue_settings',
    ):
        sys.modules.pop(m, None)
    # Re-imported through importlib, not `from zyg_dashboard import ...`: the parent package
    # still carries the previous run's module as an attribute, and a from-import hands that
    # back without re-executing anything, so every test after the first measured the first
    # test's tmp_path. import_module re-executes the module and rebinds the attribute.
    preempt_bank = importlib.import_module('zyg_dashboard.preempt_bank')
    subscription_llm = importlib.import_module('zyg_workflows.subscription_llm')
    approval_queue_settings = importlib.import_module('zyg_dashboard.approval_queue_settings')
    runtime = importlib.import_module('zyg_workflows.runtime')

    # subscription_llm reaches the bank through `runtime.preempt_bank`, which only
    # crewai_web_gui registers (at its bottom import block). This process never boots the
    # GUI, so without this the hook stays None, every record/replay/limit path is a no-op
    # and the assertions below measure a bank that was never written to.
    _prev_bank = runtime.preempt_bank
    runtime.register(preempt_bank=preempt_bank)

    # quota never consulted by these tests: pin the snapshot
    preempt_bank._QUOTA_CACHE.update(ts=1e12, row={'five_hour_pct': 10.0, 'seven_day_pct': 20.0})
    yield {'pb': preempt_bank, 'sl': subscription_llm, 'aqs': approval_queue_settings, 'cli': cli, 'tmp': tmp_path}
    preempt_bank.clear_context()
    runtime.register(preempt_bank=_prev_bank)


def _msg(text, image=False):
    content = [{'type': 'text', 'text': text}]
    if image:
        content.append({'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': 'AAAA'}})
    return [{'role': 'user', 'content': content}]


def test_record_then_replay_without_cli(env):
    pb, sl = env['pb'], env['sl']
    e = pb.new_entry('Roman concrete', 'historic_inventions')
    assert e['status'] == 'building'
    tok = pb.set_context('record', e['id'])
    r1 = sl.run_turn(_msg('Write the script about Roman concrete'), system='S', stage='Stage 3')
    fc_head = (
        'You are a documentary fact-checker. Read the narration script and identify any specific claims '
        '(exact dates, statistics, named quotes, causality assertions, numeric figures) that are NOT supported '
        'by or directly contradicted by the source block below. Return JSON only.\n\nSOURCE: '
    )
    r2 = sl.run_turn(_msg(fc_head + 'wiki extract v1 ...'), system='S', stage='Stage 3')
    r3 = sl.run_turn(_msg('Judge this frame for text'), system='S', stage='Stage 3.5')  # text-only, recorded
    r4 = sl.run_turn(
        _msg('Judge this frame for text', image=True), system='S', stage='Stage 3.5'
    )  # image: never recorded
    pb.clear_context(tok)
    assert r1.content[0].text.startswith('LIVE:') and r4.content[0].text.endswith('|img')
    assert pb.turn_count(e['id']) == 3
    pb.snapshot(e['id'], {'essay_text': 'x' * 400, 'research_meta': {'sources_used': ['u']}})
    e = pb.finish_entry(e['id'], True)
    assert e['status'] == 'ready' and e['turns'] == 3

    # replay: the CLI is gone, the answers are not
    os.remove(env['cli'])
    tok = pb.set_context('replay', e['id'])
    a = sl.run_turn(_msg('Write the script about Roman concrete'), system='S', stage='Stage 3')
    assert a.content[0].text == r1.content[0].text and a.session_id.startswith('preempt-replay')
    # header the same, body drifted (a re-fetched wiki block): same stage + header → next unused record
    b = sl.run_turn(
        _msg(fc_head + 'wiki extract v2, re-fetched today, different text ...'), system='S', stage='Stage 3'
    )
    assert b.content[0].text == r2.content[0].text
    # a short prompt whose tail drifted inside the header window: same stage + opening line
    c = sl.run_turn(_msg('Judge this frame for text — slot 7 of 44'), system='S', stage='Stage 3.5')
    assert c.content[0].text == r3.content[0].text
    ctx = pb.current()
    assert ctx['hits'] == 3 and ctx['misses'] == 0
    # a record is used once: the same script prompt again is a miss → policy never → limit error
    env['aqs'].update('preempt', {'live_when_exhausted': 'never'})
    with pytest.raises(sl.SubscriptionLimitError):
        sl.run_turn(_msg('Write the script about Roman concrete'), system='S', stage='Stage 3')
    assert pb.current()['refused'] == 1
    # an image call never replays; with policy never it is refused too (the site falls back locally)
    with pytest.raises(sl.SubscriptionLimitError):
        sl.run_turn(_msg('Judge this frame for text', image=True), system='S', stage='Stage 3.5')
    pb.clear_context(tok)


def test_replay_miss_goes_live_when_policy_always(env):
    pb, sl = env['pb'], env['sl']
    e = pb.new_entry('Cod fisheries')
    tok = pb.set_context('record', e['id'])
    sl.run_turn(_msg('one'), system='S', stage='Stage 2')
    pb.clear_context(tok)
    env['aqs'].update('preempt', {'live_when_exhausted': 'always'})
    tok = pb.set_context('replay', e['id'])
    r = sl.run_turn(_msg('something new'), system='S', stage='Stage 4')
    assert r.content[0].text.startswith('LIVE:') and pb.current()['live'] == 1
    pb.clear_context(tok)


def test_limit_refusal_sets_hold(env, monkeypatch):
    pb, sl = env['pb'], env['sl']
    monkeypatch.setenv('FAKE_CLI_MODE', 'limit')
    pb._QUOTA_CACHE.update(
        ts=1e12, row={'five_hour_pct': 100.0, 'seven_day_pct': 20.0, 'five_hour_resets_at': '2999-01-01T00:00:00+00:00'}
    )
    with pytest.raises(sl.SubscriptionLimitError):
        sl.run_turn(_msg('x'), system='S', stage='Stage 2')
    holding, until, why = pb.limit_hold()
    assert holding and until.startswith('2999')
    ok, reason = pb.live_allowed(policy='auto')
    assert not ok and 'hold' in reason


def test_entry_lifecycle_and_songs(env):
    pb = env['pb']
    a = pb.new_entry('A')
    b = pb.new_entry('B')
    for e in (a, b):
        pb.record_turn(
            {'mode': 'record', 'dir': os.path.join(pb.DOC_DIR, e['id']), 'recorded': 0},
            model='m',
            stage='Stage 3',
            system='S',
            blocks=[{'type': 'text', 'text': 'p'}],
            text='t',
        )
        pb.snapshot(e['id'], {'essay_text': 'e' * 400})
        pb.finish_entry(e['id'], True)
    assert pb.counts()['ready'] == 2
    taken = pb.take_ready(1)
    assert [t['id'] for t in taken] == [a['id']] and pb.load_entry(a['id'])['status'] == 'claimed'
    pb.attach(a['id'], 'pid-1')
    pb.settle(a['id'], 'failed')  # first render failure → back to ready
    assert pb.load_entry(a['id'])['status'] == 'ready' and pb.load_entry(a['id'])['render_attempts'] == 1
    pb.take_ready(1)
    pb.settle(a['id'], 'failed')  # second → failed
    assert pb.load_entry(a['id'])['status'] == 'failed'
    pb.take_ready(1)
    pb.settle(b['id'], 'done')
    assert pb.load_entry(b['id'])['status'] == 'consumed'
    assert pb.counts()['built'] == 1 and 'a' not in pb.banked_topics()
    # a failed entry is never a "no turns" failure by accident
    c = pb.new_entry('C')
    pb.finish_entry(c['id'], True)
    assert pb.load_entry(c['id'])['status'] == 'failed' and 'no turns' in pb.load_entry(c['id'])['error']
    assert pb.delete_entry(c['id']) and pb.load_entry(c['id']) is None

    assert (
        pb.songs_add(
            [
                {'theme': 'a frog', 'mood': 'playful', 'age_band': 'toddler'},
                {'theme': 'A frog!', 'mood': 'happy'},  # duplicate, normalised
                {'theme': 'the moon', 'mood': 'lullaby', 'age_band': 'preschool'},
            ]
        )
        == 2
    )
    t = pb.songs_take(1)
    assert t[0]['theme'] == 'a frog' and pb.songs_counts()['claimed'] == 1
    pb.songs_settle(t[0]['id'], 'done', 'pid-9')
    assert pb.songs_counts()['consumed'] == 1 and pb.songs_counts()['ready'] == 1
    assert pb.songs_banked_themes() == {'a frog', 'the moon'}


def test_settings_validate_and_persist(env):
    aqs = env['aqs']
    assert aqs.get('documentary', 'topics_per_batch') == 6
    assert aqs.update('documentary', {'topics_per_batch': '9', 'use_bank_first': 'false'})['topics_per_batch'] == 9
    assert aqs.get('documentary', 'use_bank_first') is False
    with pytest.raises(ValueError):
        aqs.update('documentary', {'topics_per_batch': 40})
    with pytest.raises(ValueError):
        aqs.update('preempt', {'live_when_exhausted': 'maybe'})
    with pytest.raises(ValueError):
        aqs.update('melody', {'nope': 1})
    f = {x['key']: x for x in aqs.fields('documentary')}
    assert f['topics_per_batch']['value'] == 9 and f['topics_per_batch']['max'] == 12
    assert json.load(open(aqs.PATH))['documentary']['topics_per_batch'] == 9


def test_pipeline_options_pass_preempt_only_when_well_formed(env):
    sys.modules.pop('zyg_workflows.pipeline_common', None)
    try:
        from zyg_workflows.pipeline_common import _normalize_pipeline_options as norm
    except Exception as exc:  # noqa: BLE001 — pipeline_common drags the GUI in on some boxes
        pytest.skip(f'pipeline_common not importable standalone: {exc!r}')
    assert norm({'preempt': {'mode': 'replay', 'entry': 'd-1'}})['preempt'] == {
        'mode': 'replay',
        'entry': 'd-1',
        'dry_run': False,
    }
    assert 'preempt' not in norm({'preempt': {'mode': 'record'}})
    assert 'preempt' not in norm({'preempt': 'yes'})


def test_interrupted_record_resumes_instead_of_rebuying(env):
    """A recording cut off mid-run costs only the turns it never reached.

    2026-09-23: another session restarted the GUI during a 30-wide wave; 18 recordings that
    were 7-13 turns deep were settled as failures and 418k output tokens were bought again
    from scratch. An interrupted entry now keeps its turns and is re-run against them.
    """
    pb, sl = env['pb'], env['sl']
    e = pb.new_entry('Great Fire of London', 'historic_events')
    tok = pb.set_context('record', e['id'])
    first = sl.run_turn(_msg('Write the script about the Great Fire'), system='S', stage='Stage 3')
    second = sl.run_turn(_msg('List the scenes'), system='S', stage='Stage 4')
    pb.clear_context(tok)
    assert pb.turn_count(e['id']) == 2

    # the GUI is restarted under it: the run vanishes with no snapshot
    e = pb.finish_entry(e['id'], False, error='run vanished (GUI restarted?)')
    assert e['status'] == 'interrupted', 'work in hand must not be thrown away'
    assert pb.counts()['interrupted'] == 1

    # the builder picks it up again, same entry, turns still on disk
    again = pb.take_interrupted()
    assert again['id'] == e['id'] and again['status'] == 'building' and again['resume_count'] == 1
    assert pb.take_interrupted() is None, 'an entry is only claimed once'

    # re-run: the CLI is gone, so anything NOT already recorded would fail loudly
    os.remove(env['cli'])
    tok = pb.set_context('record', again['id'])
    a = sl.run_turn(_msg('Write the script about the Great Fire'), system='S', stage='Stage 3')
    b = sl.run_turn(_msg('List the scenes'), system='S', stage='Stage 4')
    assert a.content[0].text == first.content[0].text
    assert b.content[0].text == second.content[0].text
    assert a.session_id.startswith('preempt-resume')
    assert pb.current()['resumed'] == 2
    # a call the interrupted run never reached has nothing to reuse → it goes live (no CLI here)
    with pytest.raises((sl.SubscriptionLLMError, sl.SubscriptionLimitError)):
        sl.run_turn(_msg('A call the first attempt never made'), system='S', stage='Stage 3.5')
    pb.clear_context(tok)
    # reused turns are not written twice
    assert pb.turn_count(again['id']) == 2


def test_stale_building_entry_is_reaped(env):
    """A ghost `building` entry must not count against the target for ever.

    2026-09-23: 12 entries whose runs died instantly stayed `building`, so built+building hit
    100 and the builder stopped at 88 of 100 believing it was done.
    """
    pb = env['pb']
    e = pb.new_entry('Ghost topic', 'pool')
    assert pb.counts()['building'] == 1
    assert pb.reap_stale_building(max_age_s=10_000) == 0, 'a fresh entry is not stale'
    old = time.time() - 3600
    os.utime(os.path.join(pb.DOC_DIR, e['id'], 'entry.json'), (old, old))
    assert pb.reap_stale_building(max_age_s=900) == 1
    assert pb.load_entry(e['id'])['status'] == 'failed'
    assert pb.counts()['building'] == 0
