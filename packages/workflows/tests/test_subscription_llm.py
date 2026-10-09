# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""subscription_llm — the documentary pipeline's Claude calls as headless turns on the login.

Pinned (2026-09-17): the requested model is replaced by Opus 5 and the substitution is
audited; no ANTHROPIC_* variable reaches the CLI (it would bill the key); the system
prompt and the user blocks — image blocks included — arrive as stream-json; the response
has the SDK shape the call sites read; a rejected rate limit is its own error class and
nothing falls back to the API.
"""

import json
import os
import stat
import sys
import textwrap

import pytest

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _CREWS not in sys.path:
    sys.path.insert(0, _CREWS)

FAKE_CLI = textwrap.dedent("""\
    #!/usr/bin/env python3
    import json, os, sys
    argv = sys.argv[1:]
    line = sys.stdin.readline()
    user = json.loads(line) if line.strip() else {}
    mode = os.environ.get('FAKE_CLI_MODE', 'ok')
    echo = {'argv': argv, 'user': user, 'env_has_key': 'ANTHROPIC_API_KEY' in os.environ,
            'max_out': os.environ.get('CLAUDE_CODE_MAX_OUTPUT_TOKENS'), 'cwd': os.getcwd()}
    if mode == 'limit':
        print(json.dumps({'type': 'rate_limit_event', 'rate_limit_info': {'status': 'rejected', 'rateLimitType': 'seven_day'}}))
        print(json.dumps({'type': 'result', 'subtype': 'error_during_execution', 'is_error': True, 'result': "You've hit your weekly limit",
                          'session_id': 'sid-limit', 'usage': {}, 'num_turns': 0}))
        sys.exit(0)
    if mode == 'crash':
        sys.stderr.write('boom\\n'); sys.exit(3)
    print(json.dumps({'type': 'assistant', 'message': {'content': [{'type': 'text', 'text': 'partial'}]}}))
    print(json.dumps({'type': 'result', 'subtype': 'success', 'is_error': False, 'result': json.dumps(echo),
                      'session_id': 'sid-1', 'num_turns': 1, 'duration_ms': 12, 'total_cost_usd': 0.0123,
                      'usage': {'input_tokens': 7, 'output_tokens': 3, 'cache_read_input_tokens': 100, 'cache_creation_input_tokens': 50}}))
""")


@pytest.fixture
def shim(tmp_path, monkeypatch):
    cli = tmp_path / 'claude'
    cli.write_text(FAKE_CLI)
    cli.chmod(cli.stat().st_mode | stat.S_IEXEC)
    cred = tmp_path / 'cred.json'
    cred.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'x'}}))
    monkeypatch.setenv('ZYG_SUBSCRIPTION_LLM_CLI', str(cli))
    monkeypatch.setenv('ZYG_CLAUDE_CREDENTIALS', str(cred))
    monkeypatch.setenv('ZYG_SUBSCRIPTION_LLM_DIR', str(tmp_path / 'cli-dir'))
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-should-not-leak')
    monkeypatch.delenv('ZYG_SCHOLARLY_LLM_BACKEND', raising=False)
    monkeypatch.delenv('ZYG_SCHOLARLY_LLM_MODEL', raising=False)
    import importlib
    from zyg_workflows import llm_audit

    monkeypatch.setattr(llm_audit, '_AUDIT_DIR', str(tmp_path / 'audit'))
    from zyg_workflows import subscription_llm

    mod = importlib.reload(subscription_llm)
    return mod, tmp_path


def _echo(resp):
    return json.loads(resp.content[0].text)


def test_turn_maps_onto_the_tier_strips_key_and_passes_prompt(shim):
    """The 2026-09-23 hybrid ruling: the subscription keeps the pipeline's own tiering,
    so a haiku ask stays on haiku and only the script turn is Opus. Before it, every call
    was rewritten to Opus and a 17-token 'extract the subject' turn cost Opus rates."""
    mod, tmp = shim
    assert mod.BACKEND == 'subscription'
    assert (mod.MODEL_SMALL, mod.MODEL_LARGE, mod.MODEL_SCRIPT) == (
        'claude-haiku-4-5-20251001',
        'claude-sonnet-5',
        'claude-opus-5',
    )
    client = mod.anthropic_client('sk-ant-whatever')
    r = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=900,
        temperature=0.0,
        system='Be terse.',
        messages=[{'role': 'user', 'content': 'hello there'}],
    )
    e = _echo(r)
    argv = e['argv']
    assert argv[argv.index('--model') + 1] == 'claude-haiku-4-5-20251001'
    assert e['env_has_key'] is False
    assert e['max_out'] == '16000'  # floor (2026-09-20): 2x the ask, never under 16k — one answer, one message
    assert argv[argv.index('--tools') + 1] == '' and '--setting-sources' in argv
    sysp = argv[argv.index('--system-prompt') + 1]
    assert sysp.startswith('Be terse.') and 'documentary production pipeline' in sysp
    assert e['user']['message']['content'] == [{'type': 'text', 'text': 'hello there'}]
    assert e['cwd'] == str(tmp / 'cli-dir')
    # SDK shape
    assert r.model == 'claude-haiku-4-5-20251001' and r.stop_reason == 'end_turn'
    assert (
        r.usage.input_tokens,
        r.usage.output_tokens,
        r.usage.cache_read_input_tokens,
        r.usage.cache_creation_input_tokens,
    ) == (7, 3, 100, 50)
    assert r.total_cost_usd == 0.0123 and r.session_id == 'sid-1'
    # audit row
    rows = [json.loads(l) for f in os.listdir(tmp / 'audit') for l in open(tmp / 'audit' / f)]
    assert len(rows) == 1
    row = rows[0]
    assert (
        row['source'] == 'claude_code'
        and row['model'] == 'claude-haiku-4-5-20251001'
        and row['requested_model'] == 'claude-haiku-4-5-20251001'
    )
    assert row['input_tokens'] == 7 and row['cost_usd'] == 0.0123 and row['images'] == 0 and row['error'] is None


def test_images_pass_through_and_stream_wrapper(shim):
    mod, _ = shim
    img = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'AAAA'}}
    with mod.SubscriptionClient().messages.stream(
        model='claude-sonnet-4-6',
        max_tokens=100000,
        messages=[{'role': 'user', 'content': [img, {'type': 'text', 'text': 'judge'}]}],
    ) as s:
        r = s.get_final_message()
    e = _echo(r)
    assert e['user']['message']['content'][0] == img
    assert e['user']['message']['content'][1] == {'type': 'text', 'text': 'judge'}
    assert e['max_out'] == '64000'  # ceiling


def test_prior_turns_fold_into_one_user_message(shim):
    mod, _ = shim
    r = mod.run_turn(
        [{'role': 'user', 'content': 'q1'}, {'role': 'assistant', 'content': 'a1'}, {'role': 'user', 'content': 'q2'}]
    )
    texts = [b['text'] for b in _echo(r)['user']['message']['content']]
    assert texts == ['q1', '[Assistant earlier in this conversation]\na1', 'q2']


def test_rate_limit_is_its_own_error(shim, monkeypatch):
    mod, tmp = shim
    monkeypatch.setenv('FAKE_CLI_MODE', 'limit')
    with pytest.raises(mod.SubscriptionLimitError):
        mod.run_turn([{'role': 'user', 'content': 'x'}])
    rows = [json.loads(l) for f in os.listdir(tmp / 'audit') for l in open(tmp / 'audit' / f)]
    assert rows and rows[0]['error']


def test_crash_without_result(shim, monkeypatch):
    mod, _ = shim
    monkeypatch.setenv('FAKE_CLI_MODE', 'crash')
    with pytest.raises(mod.SubscriptionLLMError, match='boom'):
        mod.run_turn([{'role': 'user', 'content': 'x'}])


def test_gate_and_api_mode(shim, monkeypatch):
    mod, tmp = shim
    assert mod.api_key_or_login() == mod.LOGIN_SENTINEL
    monkeypatch.setenv('ZYG_CLAUDE_CREDENTIALS', str(tmp / 'missing.json'))
    import importlib

    mod = importlib.reload(mod)
    assert mod.api_key_or_login() == ''  # no login -> the call sites skip Claude
    monkeypatch.setenv('ZYG_SCHOLARLY_LLM_BACKEND', 'api')
    mod = importlib.reload(mod)
    assert mod.MODEL_SMALL == 'claude-haiku-4-5-20251001' and mod.MODEL_LARGE == 'claude-sonnet-4-6'
    assert mod.api_key_or_login() == 'sk-ant-should-not-leak'
    anthropic = pytest.importorskip('anthropic')
    assert isinstance(mod.anthropic_client('k'), anthropic.Anthropic)
