# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
Session Tree — port 7100.

A job board for Claude agent sessions. One tree = up to 30 tasks written by a
creator session (Claude Fable). Executor sessions (Claude Opus) — spawned by this
server, one per ready task, ≤ max_executors live — claim ONE task
at a time, receive its brief only on claim, and must hand in a report that the
server checks before the task counts as finished.

Everything is stdlib so it runs under /usr/bin/python3 (no venv, no Flask).

Identity is NOT self-declared. The CLI sends CLAUDE_CODE_SESSION_ID; this server
opens that session's transcript under ~/.claude/projects/*/<sid>.jsonl and reads
the model the harness recorded. A session cannot claim to be Fable or Opus — the
transcript says what it is.

The listening address is ``$BIND_HOST`` and defaults to ``127.0.0.1``: the board is
loopback-only unless LAN exposure is asked for explicitly by setting
``BIND_HOST=0.0.0.0`` in the environment. (The constant is read from the environment
rather than from ``zyg_workflows.paths``, which spells the same variable, because this
module is stdlib-only so that it runs under /usr/bin/python3 with no venv.)

Storage: data/active/<tree>.json, data/planned/<tree>.json, data/finished/<tree>.json,
data/audit.jsonl.

One tree is active at a time. A tree created while another is active goes to
data/planned/ (status "planned", ranked by created_at). When the active tree
archives — or is deleted — the oldest planned tree is promoted to active and
executors pick its tasks up with the normal `st next`. Executors never see
planned trees; the creator sees them in `st status`, the operator in the
Planned tab (activate now / delete).
Finished trees are only served to a browser (Sec-Fetch-Site, or a same-origin
Referer from a Mozilla user agent — curl and urllib send neither) — the agent
CLI has no command that reaches them.
"""

# ruff: noqa: F401

# The submodules are imported in the original section order, so their module-level
# side effects (makedirs, config load, the server start stamp) still run in that order.
from ._base import (
    ACTIVE,
    AUDIT,
    BASE,
    BIND_HOST,
    BaseHTTPRequestHandler,
    CLAUDE_PROJECTS,
    CONFIG_PATH,
    DATA,
    DEFAULT_CONFIG,
    FINISHED,
    LOCK,
    PLANNED,
    SELF_HOST,
    STATIC,
    SUGGESTED,
    ThreadingHTTPServer,
    datetime,
    glob,
    ipaddress,
    json,
    os,
    parse_qs,
    re,
    shutil,
    subprocess,
    threading,
    time,
    urlparse,
    uuid,
    _zyg_log,
    _zyg_logging,
)
from .storage import CFG, audit, audit_tail, d, iso, list_trees, load_config, load_tree, now, save_tree, _tree_path
from .peers import (
    NOTIFY,
    activate_tree,
    archive_tree,
    live_peers,
    notice_for,
    operator_notify,
    peer_for,
    pending_notices,
    planned_trees,
    promote_planned,
    suggested_trees,
    _claude_bin,
    _peers_cache,
)
from .identity import identify, _find_transcript, _model_from_transcript
from .resources import admission, executing_tasks, queue_position, queue_state, resources, wait_queue, _res_cache
from .task_helpers import (
    claimable,
    deps_done,
    public_task_row,
    reserved_for_other,
    session_active_task,
    session_task_count,
    sweep_leases,
    validate_task,
)
from .spawner_state import SPAWNED, SPAWN_HISTORY, SPAWN_LOGS, _spawn_evt, _spawn_stats
from .usage import (
    AUTH_RE,
    CRED_PATH,
    LIMIT_RE,
    USAGE_STATE,
    USAGE_URL,
    auth_hold_active,
    fetch_claude_usage,
    parse_claude_usage,
    usage_hold_active,
    usage_poll,
    usage_state,
    usage_thread,
    _USAGE_PERSIST,
    _auth_fail_in_log,
    _hold_from_message,
    _iso_ts,
    _limit_hit_in_log,
    _usage,
    _usage_evt,
    _usage_load,
    _usage_release,
    _usage_save,
    _usage_set_hold,
)
from .spawner import (
    EXECUTOR_PROMPT,
    kick_spawner,
    reap_spawned,
    save_config,
    spawn_executor,
    spawn_reservation_live,
    spawn_sweep,
    spawner_state,
    spawner_thread,
    _executor_died_holding_task,
    _kill_spawn,
    _pid_alive,
    _spawn_env,
    _task_holder_sids,
    _task_reserved_sids,
)
from .metrics import (
    SERVER_STARTED,
    SPAWNS_LOG,
    USAGE_V,
    ZERO_USAGE,
    attribute_session_usage,
    audit_server_starts,
    eta_check,
    spawn_record,
    spawn_records,
    stamp_task_usage,
    stamp_usage_for_session,
    task_timeline,
    transcript_usage,
    tree_metrics,
    ui_metrics,
    _END_EVENTS,
    _START_EVENTS,
    _audit_scan,
    _iso_epoch,
    _sum_usage,
    _union_len,
    _usage_cache,
)
from .commands import (
    Refuse,
    cmd_await,
    cmd_claim,
    cmd_next,
    cmd_release,
    cmd_status,
    cmd_touch,
    cmd_whoami,
    need_role,
    pick_next,
    waiting_summary,
    _brief_payload,
    _grant,
    _held_task,
)
from .completion import (
    cmd_done,
    cmd_fail,
    failure_notify,
    settle_sweep,
    tree_settle,
    _check_files,
    _maybe_archive,
    _run_verify,
    _spawn_alive,
)
from .creator_commands import (
    AGENT_COMMANDS,
    cmd_add,
    cmd_close,
    cmd_create,
    cmd_report,
    cmd_reset,
    cmd_review,
    cmd_suggest,
    cmd_wait,
    _reset_task,
)
from .ui import ui_action, ui_active, ui_counts, ui_finished, ui_planned, ui_suggested
from .http_server import Handler, main
