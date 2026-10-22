# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


# ruff: noqa: E402
# E402: the section import blocks follow the original top block (and the
# `_zyg_log` line it ended with) so attribute access like the old module had it
# keeps working; this module does not import standalone (its legacy bare
# `import medusa_victor` has no top-level target), so a hoist cannot be proved.

"""medusa_vicky.py — Vicky, the chat assistant embedded in Medusa (2026-09-16).

Vicky is a plain Claude Code CLI subprocess (`claude -p --model sonnet`), spawned
fresh per turn and resumed by session id across turns — the same pattern as the
Architecture Studio's arch_assistant.py. Two things distinguish her from that
precedent and make her Medusa's own:

RULES. Her system prompt is built fresh, per request, from VICKY_RULES.md in this
same folder — nothing else is ever spliced in. `--setting-sources project` means
she only ever loads THIS folder's .claude/settings.json; she never sees the
operator's ~/.claude settings, and this session's own memory lives under a
different project's path entirely (keyed by working directory), so it is never
reachable from a process whose cwd is this folder.

ACCESS. Unlike the arch assistant — which gives its model zero built-in tools and
only a narrow drawing-only MCP server, so filesystem access is architecturally
impossible — Vicky needs to actually build Medusa out. She gets real
Read/Write/Edit/Glob/Grep/Bash. What fences her to this folder is
.claude/settings.json (permissions.allow/deny scoped to this directory tree) plus
`cwd` pinned here. Read/Write/Edit/Glob/Grep take a path argument that the
permission rules match against, so those four are genuinely directory-scoped.
Bash is NOT — Claude Code has no notion of "this shell command may only touch
this directory", only command-pattern rules — so Bash is the weak link in this
fence: it is allowed broadly because Vicky cannot do her job without running
scripts, tests and `systemctl --user restart medusa.service`. Treat that as a
known, accepted gap, not a solved one; VICKY_RULES.md is the place to narrow it
with explicit Bash allow patterns once real usage shows what she actually needs.

Because she runs on real filesystem tools (not an MCP shim like arch_assistant),
the CLI subprocess handles its whole agentic loop internally — there is no
per-tool-call HTTP round trip to broker here, unlike arch's shim_tool().

HTTP surface (mounted by medusa_server.py under /api/vicky/...): start, job,
cancel, active, info.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid

from zyg_workflows import paths

import medusa_victor
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# The sections of the original medusa_vicky.py, imported in their original order
# so module-level side effects still happen in that order, then every name the
# single-file module defined, re-exported so no importer anywhere changes.
from .constants import (
    ALLOWED_TOOLS,
    CHAT_DIR,
    CHAT_KEEP_MESSAGES,
    CHAT_TITLE_MAX,
    CLI_BIN,
    CLI_DIR,
    CLI_MAX_OUTPUT,
    CLI_MAX_TURNS,
    CLI_MODEL,
    CLI_TIMEOUT,
    CONV_DIR,
    CURRENT_FILE,
    DEFAULT_ENGINE,
    ENGINES,
    HERE,
    PARTIAL_DIR,
    PARTIAL_FLUSH_CHARS,
    PARTIAL_FLUSH_S,
    RULES_FILE,
    RUNTIME_DIR,
    UPLOAD_DIR,
    UPLOAD_MAX_AGE,
    _CLOCK,
)
from .cli import (
    EXPENSIVE,
    _UUID_RE,
    _add_thought,
    _cli_cmd,
    _cli_env,
    _cli_event,
    _cli_first_message,
    _cli_model,
    _engine,
    _is_uuid,
    _kill,
    _run_cli,
    cli_available,
    cli_login_present,
    engine_available,
    engine_info,
    system_prompt,
    vicky_rules,
)
from .ledger import (
    _close_orphans,
    _conv_end,
    _conv_path,
    _conv_start,
    _conv_write,
    _partial_clear,
    _partial_path,
    _partial_read,
    _partial_sweep,
    _partial_write,
)
from .chat_store import (
    STILLS_DIR,
    _CHAT_CACHE,
    _CHAT_ID_RE,
    _CHAT_LOCK,
    _backfill_chats_from_ledger,
    _chat_path,
    _chat_read,
    _chat_summary,
    _chat_title_from,
    _chat_write,
    _valid_chat_id,
    chat_append,
    chat_delete,
    chat_delete_all,
    chat_list,
    chat_markdown,
    chat_new,
    chat_pictures,
    chat_rename,
    chat_set_engine,
    chat_set_session,
    current_chat_id,
    open_chat,
    set_current_chat,
)
from .jobs import (
    BEACON_PATH,
    JOBS,
    PREFIX,
    _ALLOWED_IMAGE_TYPES,
    _BEACON_TICK,
    _IMAGE_B64_MAX,
    _JLOCK,
    _JOB_TTL,
    _SAFE_FNAME,
    _beacon_pulse,
    _beacon_thread,
    _beacon_write,
    _chat_record_turn,
    _gc,
    _job_view,
    _purge_old_uploads,
    _run,
    _validate_attachments,
    active_jobs,
    cancel_job,
    handle_get,
    handle_post,
    job_status,
    save_upload,
    start_job,
)

# The single-file module carried module-level annotations; restated bare (they
# bind nothing) so this package's __annotations__ matches the old module's.
_CHAT_CACHE: dict[str, tuple[float, dict]]
JOBS: dict[str, dict]

# ── re-export surface ────────────────────────────────────────────────────────
# Every name the single medusa_vicky.py defined, so attribute access on this module
# keeps resolving after the split. Declaring them is what makes the re-export
# deliberate rather than an unused import; nothing does ``import *`` from here,
# so __all__ changes no behaviour.
__all__ = [
    'json',
    'os',
    're',
    'shutil',
    'subprocess',
    'threading',
    'time',
    'uuid',
    'paths',
    'medusa_victor',
    '_zyg_logging',
    'ALLOWED_TOOLS',
    'CHAT_DIR',
    'CHAT_KEEP_MESSAGES',
    'CHAT_TITLE_MAX',
    'CLI_BIN',
    'CLI_DIR',
    'CLI_MAX_OUTPUT',
    'CLI_MAX_TURNS',
    'CLI_MODEL',
    'CLI_TIMEOUT',
    'CONV_DIR',
    'CURRENT_FILE',
    'DEFAULT_ENGINE',
    'ENGINES',
    'HERE',
    'PARTIAL_DIR',
    'PARTIAL_FLUSH_CHARS',
    'PARTIAL_FLUSH_S',
    'RULES_FILE',
    'RUNTIME_DIR',
    'UPLOAD_DIR',
    'UPLOAD_MAX_AGE',
    '_CLOCK',
    'EXPENSIVE',
    '_UUID_RE',
    '_add_thought',
    '_cli_cmd',
    '_cli_env',
    '_cli_event',
    '_cli_first_message',
    '_cli_model',
    '_engine',
    '_is_uuid',
    '_kill',
    '_run_cli',
    'cli_available',
    'cli_login_present',
    'engine_available',
    'engine_info',
    'system_prompt',
    'vicky_rules',
    '_close_orphans',
    '_conv_end',
    '_conv_path',
    '_conv_start',
    '_conv_write',
    '_partial_clear',
    '_partial_path',
    '_partial_read',
    '_partial_sweep',
    '_partial_write',
    'STILLS_DIR',
    '_CHAT_CACHE',
    '_CHAT_ID_RE',
    '_CHAT_LOCK',
    '_backfill_chats_from_ledger',
    '_chat_path',
    '_chat_read',
    '_chat_summary',
    '_chat_title_from',
    '_chat_write',
    '_valid_chat_id',
    'chat_append',
    'chat_delete',
    'chat_delete_all',
    'chat_list',
    'chat_markdown',
    'chat_new',
    'chat_pictures',
    'chat_rename',
    'chat_set_engine',
    'chat_set_session',
    'current_chat_id',
    'open_chat',
    'set_current_chat',
    'BEACON_PATH',
    'JOBS',
    'PREFIX',
    '_ALLOWED_IMAGE_TYPES',
    '_BEACON_TICK',
    '_IMAGE_B64_MAX',
    '_JLOCK',
    '_JOB_TTL',
    '_SAFE_FNAME',
    '_beacon_pulse',
    '_beacon_thread',
    '_beacon_write',
    '_chat_record_turn',
    '_gc',
    '_job_view',
    '_purge_old_uploads',
    '_run',
    '_validate_attachments',
    'active_jobs',
    'cancel_job',
    'handle_get',
    'handle_post',
    'job_status',
    'save_upload',
    'start_job',
]
