# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The spawner section head: its paths and its live-state tables.

Moved verbatim from session_tree_server.py lines 758-783.
"""

from ._base import BASE, os, threading


# ───────────────────────────── spawner ───────────────────────────────────────
# The board launches its own executors: one `claude -p --model <executor_model>`
# session per READY task (todo, dependencies finished, slot + resources free),
# capped at max_executors live sessions. Each spawn is told its task and the
# task is RESERVED for that session id, so thirty executors never race for the
# lowest id. Identity still comes from the transcript: a print session writes
# ~/.claude/projects/<cwd-slug>/<sid>.jsonl like any other, and its Bash tool
# carries CLAUDE_CODE_SESSION_ID=<sid>, so the role gate is untouched. Fable
# never spawns anything (a subagent would inherit Fable's id) — the service does.

SPAWN_LOGS = os.path.join(BASE, 'spawn_logs')  # outside data/: agents may read their own log
os.makedirs(SPAWN_LOGS, exist_ok=True)
SPAWNED = {}  # sid -> {pid, popen, tree, task, weight, started_at, log, exit, exited_at}
SPAWN_HISTORY = []  # last exits, for the UI
_spawn_evt = threading.Event()
_spawn_stats = {
    'noclaim_streak': 0,
    'brake_until': 0,
    'total': 0,
    'last_error': '',
    'auth_broken_since': 0,
    'auth_last_try': 0,
    'auth_msg': '',
    'auth_last_audit': 0,
}
