# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Unit tests for the helpers extracted from the Session Tree CLI's ``main``.

``st_cli.main`` was one 463-line if-ladder over twenty commands, so not one of the
argument checks, refusals or printed blocks had a test. The split moved the transport and
the shared printers to ``st_client_cli``, one handler per command to ``st_commands_cli``,
and left ``main`` as the three gates that come first plus a dictionary lookup. This file
tests the gates, the dispatch, and the four printers every command reuses.

Nothing here reaches the board: ``call`` is stubbed or the URL is pointed at a scheme the
transport refuses before it ever opens a socket. The CLI under test belongs to
``zyg_dashboard``; the file lives in the workflows suite because that is where the task
that split it was told to put it.

    cd packages/workflows && .venv/bin/python -m pytest tests/test_st_cli_helpers.py -q
"""

import json

import pytest

from zyg_dashboard.session_tree import st_cli, st_client_cli, st_commands_cli


@pytest.fixture
def session(monkeypatch):
    """A CLI that believes it is inside a Claude Code session."""
    monkeypatch.setattr(st_cli, 'SID', 'sess-0001')


# ── main: the three gates that run before any dispatch ───────────────────────


def test_main_with_no_arguments_prints_the_help(capsys):
    """An empty argv is the help, not a refusal — the identity gate comes later."""
    assert st_cli.main([]) == 0
    assert capsys.readouterr().out.startswith('st — the Session Tree CLI.')


@pytest.mark.parametrize('flag', ['-h', '--help', 'help'])
def test_main_help_flags_all_print_the_docstring(capsys, flag):
    """All three spellings of help behave the same."""
    assert st_cli.main([flag]) == 0
    assert 'st claim TREE N' in capsys.readouterr().out


def test_main_rules_reads_the_skill_file(capsys, tmp_path, monkeypatch):
    """``st rules`` prints the rulebook from the skills directory."""
    book = tmp_path / 'SKILL.md'
    book.write_text('the rulebook\n', encoding='utf-8')
    monkeypatch.setattr(st_cli.os.path, 'expanduser', lambda p: str(book))

    assert st_cli.main(['rules']) == 0
    assert capsys.readouterr().out == 'the rulebook\n\n'


def test_main_rules_says_so_when_the_skill_file_is_missing(capsys, tmp_path, monkeypatch):
    """A missing rulebook names the path it looked at instead of raising."""
    missing = tmp_path / 'absent.md'
    monkeypatch.setattr(st_cli.os.path, 'expanduser', lambda p: str(missing))

    assert st_cli.main(['rules']) == 0
    assert capsys.readouterr().out == f'rules file missing: {missing}\n'


def test_main_templates_work_without_a_session_id(capsys, monkeypatch):
    """The two templates are answered before the identity gate, so a bare shell can read them."""
    monkeypatch.setattr(st_cli, 'SID', '')

    assert st_cli.main(['report-template']) == 0
    assert json.loads(capsys.readouterr().out)['not_done'].startswith('what is NOT done')

    assert st_cli.main(['tree-template']) == 0
    assert json.loads(capsys.readouterr().out)['tasks'][0]['weight'] == 'light'


def test_main_refuses_every_other_command_without_a_session_id(capsys, monkeypatch):
    """No session id means no identity the server could check: status 2, nothing sent."""
    monkeypatch.setattr(st_cli, 'SID', '')
    monkeypatch.setattr(st_commands_cli, 'call', lambda *a, **kw: pytest.fail('must not reach the board'))

    assert st_cli.main(['whoami']) == 2
    assert 'CLAUDE_CODE_SESSION_ID is not set' in capsys.readouterr().out


def test_main_dispatches_to_the_handler_with_the_remaining_args(session, monkeypatch):
    """The command word is consumed and everything after it is handed to the handler."""
    seen = []
    monkeypatch.setitem(st_cli.COMMANDS, 'touch', lambda args: seen.append(args) or 7)

    assert st_cli.main(['touch', 'tree-x', '3', 'a', 'note']) == 7
    assert seen == [['tree-x', '3', 'a', 'note']]


def test_main_on_an_unknown_command_prints_the_help_and_fails(session, capsys):
    """An unrecognised word is status 2 with the help, after the identity gate."""
    assert st_cli.main(['frobnicate']) == 2
    out = capsys.readouterr().out
    assert out.startswith("unknown command 'frobnicate'")
    assert 'st claim TREE N' in out


# ── the transport ────────────────────────────────────────────────────────────


def test_call_refuses_a_non_http_url_before_sending_the_identity(monkeypatch):
    """A file:// or scheme-less board URL must never be handed the session id."""
    monkeypatch.setattr(st_client_cli, 'URL', 'file:///etc/passwd')

    res = st_client_cli.call('whoami')

    assert res['ok'] is False
    assert 'refusing to post to a file session tree URL' in res['error']


def test_call_names_the_missing_scheme(monkeypatch):
    """A URL with no scheme at all is refused with the same shape of error."""
    monkeypatch.setattr(st_client_cli, 'URL', '127.0.0.1:7100')

    assert 'scheme-less' in st_client_cli.call('status')['error']


# ── read_json_arg ────────────────────────────────────────────────────────────


def test_read_json_arg_returns_the_payload_and_the_rest_of_argv(tmp_path):
    """The flag and its path are removed, so the positional arguments keep their order."""
    f = tmp_path / 'report.json'
    f.write_text('{"summary": "did the thing"}', encoding='utf-8')

    payload, rest = st_client_cli.read_json_arg(['--report', str(f), 'tree-x', '4'], '--report')

    assert payload == {'summary': 'did the thing'}
    assert rest == ['tree-x', '4']


def test_read_json_arg_removes_the_flag_from_the_middle(tmp_path):
    """``st add TREE --file tasks.json`` leaves the tree id behind as rest[0]."""
    f = tmp_path / 'tasks.json'
    f.write_text('[]', encoding='utf-8')

    payload, rest = st_client_cli.read_json_arg(['tree-x', '--file', str(f), '--eta', '20'], '--file')

    assert payload == []
    assert rest == ['tree-x', '--eta', '20']


def test_read_json_arg_without_the_flag_changes_nothing():
    """An absent flag is None, distinguishable from a file that parsed to null."""
    assert st_client_cli.read_json_arg(['tree-x'], '--file') == (None, ['tree-x'])


# ── problem_report ───────────────────────────────────────────────────────────


def test_problem_report_names_every_problem_and_the_next_command():
    """The creator is told which task died, what is blocked, and the three commands to run."""
    text = st_client_cli.problem_report(
        'tree-x',
        {
            'title': 'Clean base',
            'problems': [
                {
                    'id': 4,
                    'status': 'failed',
                    'title': 'Split main',
                    'at': '12:00',
                    'event': 'verify',
                    'summary': 'ratchet went up',
                }
            ],
            'blocked': [5, 6],
            'settled': True,
            'archive_at': '12:20',
        },
    )

    assert 'TASK FAILED in tree-x "Clean base"' in text
    assert '#4 [failed] Split main  at 12:00  event: verify' in text
    assert 'ratchet went up' in text
    assert 'blocked behind it: [5, 6]' in text
    assert 'auto-archives at 12:20' in text
    assert 'st report tree-x 4' in text
    assert 'st reset tree-x 4' in text


def test_problem_report_falls_back_to_n_with_no_problem_list():
    """A stale-only exit still prints a runnable command shape rather than a crash."""
    text = st_client_cli.problem_report('tree-y', {'title': 'T'})

    assert 'st report tree-y N' in text
    assert 'blocked behind it' not in text


# ── print_failure_notify ─────────────────────────────────────────────────────


def test_print_failure_notify_gives_the_sendmessage_line_for_a_live_creator(capsys):
    """A running creator gets a ready-to-send message naming the tree, task and reason."""
    st_client_cli.print_failure_notify(
        {'alive': True, 'peer_name': 'Fable', 'how': 'verify', 'title': 'Split main', 'summary': 'ratchet went up'},
        'tree-x',
        9,
    )

    out = capsys.readouterr().out
    assert out.startswith('TASK FAILED — notify the creator NOW, then stop:')
    assert 'SendMessage to="Fable"' in out
    assert 'Session tree tree-x task #9 FAILED (verify): Split main' in out
    assert 'Reason: ratchet went up' in out


def test_print_failure_notify_says_the_creator_is_gone(capsys):
    """With no live peer the executor is told the board will carry the news instead."""
    st_client_cli.print_failure_notify({'alive': False, 'session_id': 'abcdef123456', 'model': 'fable'}, 'tree-x', 9)

    out = capsys.readouterr().out
    assert 'creator session abcdef12 (fable) is not running' in out
    assert 'SendMessage' not in out


def test_print_failure_notify_prints_nothing_without_a_notice(capsys):
    """Most failures carry no creator notice at all; that must stay silent."""
    st_client_cli.print_failure_notify(None, 'tree-x', 9)

    assert capsys.readouterr().out == ''


# ── st status' two blocks ────────────────────────────────────────────────────


def test_print_tree_lists_the_tasks_with_their_dependencies(capsys):
    """One line per task, with the needs list and the vram figure when there is one."""
    st_commands_cli.print_tree(
        {
            'id': 'tree-x',
            'title': 'Clean base',
            'n': 2,
            'counts': {'todo': 1, 'finished': 1},
            'tasks': [
                {'id': 1, 'status': 'finished', 'weight': 'light', 'title': 'First', 'depends_on': []},
                {'id': 2, 'status': 'todo', 'weight': 'heavy', 'title': 'Second', 'depends_on': [1], 'vram_gb': 12},
            ],
        }
    )

    out = capsys.readouterr().out.splitlines()
    assert out[0] == 'tree-x  "Clean base"  2 tasks  finished=1 todo=1'
    assert out[1].startswith('  #1  finished         light')
    assert 'Second needs [1]' in out[2]
    assert '12G' in out[2]


def test_print_tree_reports_a_settled_tree_and_its_eta(capsys):
    """A settled tree says why nothing is running and when it auto-archives."""
    st_commands_cli.print_tree(
        {
            'id': 'tree-x',
            'title': 'T',
            'n': 1,
            'counts': {'failed': 1},
            'eta_minutes': 45,
            'now': 3600,
            'activated_at': 0,
            'eta_overrun_at': 3000,
            'settle': {'settled': True, 'enabled': True, 'failed': [3], 'archive_at': 4200},
            'tasks': [],
        }
    )

    out = capsys.readouterr().out
    assert 'ETA 45m elapsed 60m  OVER (logged, no action)' in out
    assert 'SETTLED (failed=1 stale=0 blocked=0)' in out
    assert 'auto-archives in 10 min unless a task is reset' in out


def test_print_spawner_shows_a_usage_hold_with_its_countdown(capsys, monkeypatch):
    """A 100%-window hold prints the reset time, the time left and the reason."""
    monkeypatch.setattr(st_commands_cli.time, 'time', lambda: 1000.0)
    monkeypatch.setattr(st_commands_cli.time, 'localtime', lambda ts=None: __import__('time').gmtime(ts))

    st_commands_cli.print_spawner(
        {
            'live_total': 0,
            'max_executors': 30,
            'auto_spawn': True,
            'executor_model': 'opus',
            'usage': {'hold': True, 'hold_until': 1000.0 + 3 * 3600 + 25 * 60, 'hold_reason': 'weekly at 100%'},
        }
    )

    out = capsys.readouterr().out
    assert 'executors 0/30 live  auto-spawn on  opus  1 task per session' in out
    assert 'USAGE HOLD: auto-spawn paused until' in out
    assert '(3h25m) — weekly at 100%' in out


# ── the handlers' own argument checks ────────────────────────────────────────


def test_cmd_claim_without_a_task_number_is_a_usage_error(capsys, monkeypatch):
    """A handler must refuse before it sends anything the server would have to reject."""
    monkeypatch.setattr(st_commands_cli, 'call', lambda *a, **kw: pytest.fail('must not reach the board'))

    assert st_commands_cli.cmd_claim(['tree-x']) == 2
    assert capsys.readouterr().out == 'usage: st claim TREE N\n'


def test_cmd_claim_queued_tells_the_executor_to_await_and_do_no_work(capsys, monkeypatch):
    """A queued claim prints no brief: the task is reserved but has not started."""
    monkeypatch.setattr(
        st_commands_cli,
        'call',
        lambda cmd, **kw: {
            'ok': True,
            'queued': True,
            'tree': 'tree-x',
            'task': 2,
            'weight': 'heavy',
            'position': 1,
            'reason': 'the GPU is busy',
            'title': 'Render the sheet',
            'wait_stale_minutes': 10,
        },
    )

    assert st_commands_cli.cmd_claim(['tree-x', '2']) == 0
    out = capsys.readouterr().out
    assert out.startswith('QUEUED tree-x#2 (heavy) position 1 — the GPU is busy')
    assert 'no brief yet, do no work on it' in out
    assert 'st await tree-x 2' in out
    assert '--- BRIEF ---' not in out


def test_cmd_done_reports_a_failed_verify_with_status_three(capsys, monkeypatch, tmp_path):
    """A non-zero verify_cmd marks the task failed, and the executor must notify the creator."""
    monkeypatch.setattr(
        st_commands_cli,
        'call',
        lambda cmd, **kw: {
            'ok': False,
            'status': 'failed',
            'msg': 'verify exited 1',
            'creator_notify': {'alive': True, 'peer_name': 'Fable', 'how': 'verify', 'title': 'T', 'summary': 'exit 1'},
        },
    )
    report = tmp_path / 'report.json'
    report.write_text(json.dumps({'summary': 'x' * 40, 'changed_files': [], 'not_done': 'none'}), encoding='utf-8')

    rc = st_commands_cli.cmd_done(['tree-x', '9', '--report', str(report)])

    out = capsys.readouterr().out
    assert rc == 3
    assert 'VERIFY FAILED — task marked failed.' in out
    assert 'SendMessage to="Fable"' in out


def test_cmd_task_report_without_a_task_number_is_a_usage_error(capsys):
    """``st report`` needs both a tree and a task; the message names both."""
    assert st_commands_cli.cmd_task_report(['tree-x']) == 2
    assert capsys.readouterr().out == 'usage: st report TREE N\n'


def test_cmd_close_without_a_tree_is_a_usage_error(capsys):
    """``st close`` with nothing to close must not archive whatever is active."""
    assert st_commands_cli.cmd_close([]) == 2
    assert capsys.readouterr().out == 'usage: st close TREE [note] [--force]\n'
