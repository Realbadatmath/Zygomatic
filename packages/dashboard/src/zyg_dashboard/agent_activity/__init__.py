# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""agent_activity.py — which Claude Code agent sessions are burning this box's hardware.

The Live Tail knows everything about a *pipeline* run and nothing about the
other thing that drives this GPU all day: a Claude Code session launching a
workflow, a render, or a smoke test from a terminal.  Measured 2026-08-30,
ComfyUI (55% CPU, 530 MiB VRAM) had been started by hand from session
102a6649 and `comfyui.service` sat in `failed` — the board showed an idle
pipeline and the operator had no way to see who was actually holding the card.

**Attribution is by INHERITED ENVIRONMENT, not by process tree.**  Every process
a Claude Code session spawns through its Bash tool carries

    CLAUDE_CODE_SESSION_ID=<uuid>      CLAUDE_PID=<pid of the claude process>

in ``/proc/<pid>/environ``, and — this is the point — a child *keeps* them after
``setsid``/``nohup`` detaches it from the tree.  A process-tree walk loses
exactly the processes that matter most (the long-lived detached ones); the
environment does not.  The trade-off is the mirror image: a service an agent
started weeks ago still names that agent, so `detached` is reported per process
and a session only counts as ACTIVE while its processes are measurably busy
right now — existence is not activity.

Session identity comes from Claude Code's own registry, ``~/.claude/sessions/
<pid>.json`` (pid, sessionId, cwd, name, kind, procStart).  ``procStart`` is
field 22 of ``/proc/<pid>/stat`` and is checked against it: a pid alone is
recycled by the kernel, so a stale registry file could otherwise rename a live
unrelated process into an agent session.

Nothing here talks to the network, and nothing here can steer a run — it reads
/proc, the session registry and the session transcripts, and reports.
"""

from __future__ import annotations

# ruff: noqa: E402,F401
import glob
import json
import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime, timezone

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

from zyg_dashboard.agent_activity import tunables as tunables
from zyg_dashboard.agent_activity import sampler as sampler
from zyg_dashboard.agent_activity import transcripts as transcripts
from zyg_dashboard.agent_activity import api as api

from zyg_dashboard.agent_activity.tunables import _CPU_ACTIVE_CORES as _CPU_ACTIVE_CORES
from zyg_dashboard.agent_activity.tunables import _CPU_ACTIVE_PCT as _CPU_ACTIVE_PCT
from zyg_dashboard.agent_activity.tunables import _VRAM_ACTIVE_MB as _VRAM_ACTIVE_MB
from zyg_dashboard.agent_activity.tunables import _RAM_ACTIVE_MB as _RAM_ACTIVE_MB
from zyg_dashboard.agent_activity.tunables import _NCPU as _NCPU
from zyg_dashboard.agent_activity.tunables import _SAMPLE_S as _SAMPLE_S
from zyg_dashboard.agent_activity.tunables import _NVIDIA_S as _NVIDIA_S
from zyg_dashboard.agent_activity.tunables import _EVENT_CAP as _EVENT_CAP
from zyg_dashboard.agent_activity.tunables import _SESS_EVENT_CAP as _SESS_EVENT_CAP
from zyg_dashboard.agent_activity.tunables import _TAIL_BYTES as _TAIL_BYTES
from zyg_dashboard.agent_activity.tunables import _HOME as _HOME
from zyg_dashboard.agent_activity.tunables import _SESS_DIR as _SESS_DIR
from zyg_dashboard.agent_activity.tunables import _PROJ_DIR as _PROJ_DIR
from zyg_dashboard.agent_activity.tunables import _LEDGER_DIR as _LEDGER_DIR
from zyg_dashboard.agent_activity.tunables import _LEDGER_FILE as _LEDGER_FILE
from zyg_dashboard.agent_activity.tunables import _OPEN_SPANS_FILE as _OPEN_SPANS_FILE
from zyg_dashboard.agent_activity.tunables import _SPAN_GRACE_S as _SPAN_GRACE_S
from zyg_dashboard.agent_activity.tunables import _SPAN_MIN_S as _SPAN_MIN_S
from zyg_dashboard.agent_activity.tunables import _OPEN_FLUSH_S as _OPEN_FLUSH_S
from zyg_dashboard.agent_activity.tunables import _UID as _UID
from zyg_dashboard.agent_activity.tunables import _CLOCK_TICKS as _CLOCK_TICKS
from zyg_dashboard.agent_activity.tunables import _SELF_RE as _SELF_RE
from zyg_dashboard.agent_activity.tunables import _KIND_PATTERNS as _KIND_PATTERNS
from zyg_dashboard.agent_activity.tunables import _ICONS as _ICONS
from zyg_dashboard.agent_activity.tunables import _REDACT_RE as _REDACT_RE
from zyg_dashboard.agent_activity.tunables import _EVAL_RE as _EVAL_RE
from zyg_dashboard.agent_activity.tunables import _EVAL_RE2 as _EVAL_RE2
from zyg_dashboard.agent_activity.tunables import _now_iso as _now_iso
from zyg_dashboard.agent_activity.tunables import _iso as _iso
from zyg_dashboard.agent_activity.sampler import _lock as _lock
from zyg_dashboard.agent_activity.sampler import _started as _started
from zyg_dashboard.agent_activity.sampler import _thread as _thread
from zyg_dashboard.agent_activity.sampler import _tracked as _tracked
from zyg_dashboard.agent_activity.sampler import _ignored as _ignored
from zyg_dashboard.agent_activity.sampler import _sessions as _sessions
from zyg_dashboard.agent_activity.sampler import _events as _events
from zyg_dashboard.agent_activity.sampler import _seq as _seq
from zyg_dashboard.agent_activity.sampler import _gpu as _gpu
from zyg_dashboard.agent_activity.sampler import _gpu_pids as _gpu_pids
from zyg_dashboard.agent_activity.sampler import _last_sample as _last_sample
from zyg_dashboard.agent_activity.sampler import _sampler_error as _sampler_error
from zyg_dashboard.agent_activity.sampler import _transcripts as _transcripts
from zyg_dashboard.agent_activity.sampler import _spans as _spans
from zyg_dashboard.agent_activity.sampler import _open_flushed as _open_flushed
from zyg_dashboard.agent_activity.sampler import _open_dirty as _open_dirty
from zyg_dashboard.agent_activity.sampler import _emit as _emit
from zyg_dashboard.agent_activity.sampler import _proc_start_ticks as _proc_start_ticks
from zyg_dashboard.agent_activity.sampler import _live_sessions as _live_sessions
from zyg_dashboard.agent_activity.sampler import _NVML as _NVML
from zyg_dashboard.agent_activity.sampler import _nvml as _nvml
from zyg_dashboard.agent_activity.sampler import _nvidia_refresh as _nvidia_refresh
from zyg_dashboard.agent_activity.sampler import _read_env as _read_env
from zyg_dashboard.agent_activity.sampler import _clean_cmd as _clean_cmd
from zyg_dashboard.agent_activity.sampler import _kind_of as _kind_of
from zyg_dashboard.agent_activity.sampler import _is_detached as _is_detached
from zyg_dashboard.agent_activity.sampler import _sample as _sample
from zyg_dashboard.agent_activity.sampler import _proc_is_busy as _proc_is_busy
from zyg_dashboard.agent_activity.sampler import _session_devices as _session_devices
from zyg_dashboard.agent_activity.sampler import _span_record as _span_record
from zyg_dashboard.agent_activity.sampler import _ledger_append as _ledger_append
from zyg_dashboard.agent_activity.sampler import _close_span as _close_span
from zyg_dashboard.agent_activity.sampler import _track_spans as _track_spans
from zyg_dashboard.agent_activity.sampler import _flush_open_spans as _flush_open_spans
from zyg_dashboard.agent_activity.sampler import _recover_open_spans as _recover_open_spans
from zyg_dashboard.agent_activity.sampler import ledger_spans as ledger_spans
from zyg_dashboard.agent_activity.sampler import _fmt_cores as _fmt_cores
from zyg_dashboard.agent_activity.sampler import _fmt_dur as _fmt_dur
from zyg_dashboard.agent_activity.sampler import _loop as _loop
from zyg_dashboard.agent_activity.sampler import start as start
from zyg_dashboard.agent_activity.transcripts import _transcript_path as _transcript_path
from zyg_dashboard.agent_activity.transcripts import _summarise_input as _summarise_input
from zyg_dashboard.agent_activity.transcripts import _parse_transcript_lines as _parse_transcript_lines
from zyg_dashboard.agent_activity.transcripts import _transcript_items as _transcript_items
from zyg_dashboard.agent_activity.api import snapshot as snapshot
from zyg_dashboard.agent_activity.api import session_tail as session_tail
