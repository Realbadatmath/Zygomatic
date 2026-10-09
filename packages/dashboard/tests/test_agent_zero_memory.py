# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for agent_zero.memory: the session store and its index, auto-titling, the
prompt window (last pairs + untrimmable current message), compaction and pinned facts.

No dashboard import: ``_host.runtime_dir`` is redirected into tmp_path.
"""

import json

import pytest

from zyg_dashboard.agent_zero import memory


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setattr(memory._host, 'runtime_dir', lambda: str(tmp_path))
    return tmp_path


def _index():
    with open(memory.index_path(), encoding='utf-8') as fh:
        return json.load(fh)


def _chat(pairs, tail=None):
    """A session with ``pairs`` user/assistant pairs and an optional trailing question."""
    session = memory.new_session('Ad', 'subscription', 'claude-opus-5')
    for i in range(pairs):
        memory.append_message(session['id'], {'role': 'user', 'content': f'question {i} ' + 'q' * 200})
        memory.append_message(session['id'], {'role': 'assistant', 'content': f'answer {i} ' + 'a' * 200})
    if tail:
        memory.append_message(session['id'], {'role': 'user', 'content': tail})
    return memory.get_session(session['id'])


def test_session_round_trip_with_index(rt):
    session = memory.new_session('Ad', 'subscription', 'claude-opus-5')
    sid = session['id']
    assert session['title'] == 'New chat'
    assert session['summary'] == '' and session['summary_covers'] == 0 and session['pinned'] == []

    loaded = memory.get_session(sid)
    assert loaded['id'] == sid and loaded['user'] == 'Ad' and loaded['model'] == 'claude-opus-5'

    rows = memory.list_sessions()
    assert [r['id'] for r in rows] == [sid]
    assert rows[0]['provider'] == 'subscription' and rows[0]['turns'] == 0
    assert _index()[sid]['title'] == 'New chat'

    memory.rename_session(sid, 'Budget ceilings')
    assert memory.get_session(sid)['title'] == 'Budget ceilings'
    assert _index()[sid]['title'] == 'Budget ceilings'
    assert memory.list_sessions()[0]['title'] == 'Budget ceilings'

    assert memory.delete_session(sid) is True
    assert memory.get_session(sid) is None
    assert memory.list_sessions() == []
    assert sid not in _index()
    assert memory.delete_session(sid) is False
    assert memory.get_session('nope') is None


def test_list_sessions_is_newest_first(rt):
    first = memory.new_session('Ad', 'ollama', 'qwen3:8b')
    second = memory.new_session('Ad', 'ollama', 'qwen3:8b')
    memory.rename_session(first['id'], 'touched last')
    assert memory.list_sessions()[0]['id'] == first['id']
    assert len(memory.list_sessions(limit=1)) == 1
    assert second['id'] in _index()


def test_auto_title_from_the_first_user_message(rt):
    session = memory.new_session('Ad', 'ollama', 'qwen3:8b')
    sid = session['id']
    memory.append_message(sid, {'role': 'user', 'content': 'Explain  the\nbudget ceilings please'})
    stored = memory.get_session(sid)
    assert stored['title'] == 'Explain the budget ceilings please'
    assert stored['turns'] == 1
    assert stored['messages'][0]['ts'] and stored['messages'][0]['turn_id']

    memory.append_message(sid, {'role': 'assistant', 'content': 'Sure.'})
    memory.append_message(sid, {'role': 'user', 'content': 'And now something completely different'})
    stored = memory.get_session(sid)
    assert stored['title'] == 'Explain the budget ceilings please'
    assert stored['turns'] == 2

    long_chat = memory.new_session('Ad', 'ollama', 'qwen3:8b')
    memory.append_message(long_chat['id'], {'role': 'user', 'content': 'w' * 200})
    assert memory.get_session(long_chat['id'])['title'] == 'w' * memory.TITLE_CHARS


def test_history_for_prompt_keeps_last_pairs_and_the_current_message(rt):
    session = _chat(10, tail='the current question')
    summary, msgs = memory.history_for_prompt(session, max_tokens=10000, keep_recent_turns=3)
    assert summary == ''
    assert len(msgs) == 7
    assert msgs[0]['role'] == 'user' and msgs[0]['content'].startswith('question 7')
    assert msgs[-1]['content'] == 'the current question'
    assert [m['role'] for m in msgs] == ['user', 'assistant'] * 3 + ['user']

    # A ceiling so tight that nothing fits still keeps the user's own message intact.
    summary, tiny = memory.history_for_prompt(session, max_tokens=10, keep_recent_turns=3)
    assert len(tiny) == 1
    assert tiny[0]['role'] == 'user' and tiny[0]['content'] == 'the current question'

    # The window never opens on an assistant message.
    _, mid = memory.history_for_prompt(session, max_tokens=120, keep_recent_turns=3)
    assert mid[0]['role'] == 'user'
    assert mid[-1]['content'] == 'the current question'


def test_history_for_prompt_collapses_old_tool_results(rt):
    session = memory.new_session('Ad', 'subscription', 'claude-opus-5')
    sid = session['id']
    for i in range(4):
        memory.append_message(sid, {'role': 'user', 'content': f'do job {i}'})
        memory.append_message(
            sid,
            {
                'role': 'assistant',
                'content': [{'type': 'tool_use', 'id': f'tu{i}', 'name': 'read_file', 'input': {'path': 'x'}}],
            },
        )
        memory.append_message(
            sid,
            {
                'role': 'user',
                'content': [{'type': 'tool_result', 'tool_use_id': f'tu{i}', 'content': 'L' * 4000}],
            },
        )
        memory.append_message(sid, {'role': 'assistant', 'content': f'done {i}'})
    memory.append_message(sid, {'role': 'user', 'content': 'and now?'})

    _, msgs = memory.history_for_prompt(memory.get_session(sid), max_tokens=100000, keep_recent_turns=8)
    texts = [memory._text_of(m) for m in msgs]
    blob = '\n'.join(texts)
    # The two most recent tool round-trips keep their payload; the older ones are notes.
    assert blob.count('[tool read_file ran, ok]') >= 1
    assert blob.count('L' * 4000) <= 2
    assert '[tool read_file called]' in blob
    # No collapsed turn leaves a tool_use without its tool_result.
    for msg in msgs:
        content = msg.get('content')
        if isinstance(content, list):
            uses = {b['id'] for b in content if isinstance(b, dict) and b.get('type') == 'tool_use'}
            if uses:
                nxt = msgs[msgs.index(msg) + 1]
                answered = {
                    b.get('tool_use_id')
                    for b in (nxt.get('content') or [])
                    if isinstance(b, dict) and b.get('type') == 'tool_result'
                }
                assert uses <= answered


def test_needs_compaction_and_estimate(rt):
    session = _chat(3)
    estimate = memory.estimate_history_tokens(session)
    assert estimate > 200
    assert memory.needs_compaction(session, estimate) is True
    assert memory.needs_compaction(session, estimate + 1) is False


def test_compaction_folds_old_turns_into_the_summary(rt):
    session = _chat(12)
    sid = session['id']
    before = memory.estimate_history_tokens(session)
    calls = []

    def summarize(text):
        calls.append(text)
        return 'facts: twelve questions were asked'

    memory.compact(session, summarize, keep_recent_turns=2)
    stored = memory.get_session(sid)
    assert stored['summary'] == 'facts: twelve questions were asked'
    assert stored['summary_covers'] == 20
    assert len(stored['messages']) == 24
    live = stored['messages'][stored['summary_covers'] :]
    assert [m['role'] for m in live] == ['user', 'assistant', 'user', 'assistant']
    assert live[0]['content'].startswith('question 10')
    assert memory.estimate_history_tokens(stored) < before
    assert 'question 0' in calls[0] and 'question 10' not in calls[0]

    summary, msgs = memory.history_for_prompt(stored, max_tokens=10000, keep_recent_turns=2)
    assert 'facts: twelve questions were asked' in summary
    assert len(msgs) == 4

    # Nothing left to fold: the session is returned untouched.
    assert memory.compact(stored, summarize, keep_recent_turns=12)['summary_covers'] == 20


def test_compaction_keeps_history_when_the_summarizer_fails(rt):
    session = _chat(6)
    sid = session['id']

    def boom(_text):
        raise RuntimeError('model unreachable')

    memory.compact(session, boom, keep_recent_turns=2)
    assert memory.get_session(sid)['summary_covers'] == 0
    memory.compact(session, lambda _t: '   ', keep_recent_turns=2)
    assert memory.get_session(sid)['summary_covers'] == 0
    assert len(memory.get_session(sid)['messages']) == 12


def test_pinned_facts_survive_compaction(rt):
    session = _chat(8, tail='what next?')
    sid = session['id']
    memory.pin(sid, 'the operator prefers metric units')
    memory.pin(sid, 'the operator prefers metric units')
    memory.pin(sid, 'never restart crewai-gui.service')
    assert memory.get_session(sid)['pinned'] == [
        'the operator prefers metric units',
        'never restart crewai-gui.service',
    ]

    memory.compact(memory.get_session(sid), lambda _t: 'eight earlier questions', keep_recent_turns=2)
    stored = memory.get_session(sid)
    assert stored['pinned'] == ['the operator prefers metric units', 'never restart crewai-gui.service']

    # Pinned facts go into the prompt even when the token ceiling leaves no room at all.
    summary, msgs = memory.history_for_prompt(stored, max_tokens=10, keep_recent_turns=2)
    assert 'metric units' in summary and 'never restart' in summary
    assert msgs[-1]['content'] == 'what next?'

    memory.unpin(sid, 'never restart crewai-gui.service')
    assert memory.get_session(sid)['pinned'] == ['the operator prefers metric units']


def test_bad_session_id_is_refused(rt):
    with pytest.raises(ValueError):
        memory.session_path('../escape')
    assert memory.get_session('../escape') is None
    assert memory.delete_session('') is False
