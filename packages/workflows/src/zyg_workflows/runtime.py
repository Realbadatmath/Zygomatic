# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""runtime.py — the runtime hook registry that decouples pipelines from the GUI.

Pipelines used to reach up into ``zyg_dashboard.crewai_web_gui`` for the job
registry, the audit log, the CSRF helper, the benchmark recorders and so on —
the forbidden direction: the base library importing the application on top of
it. This module is the seam. It owns the shared objects outright
(:data:`workflow_jobs`, :data:`NVENC_SEM`) and exposes every GUI-provided
behaviour as a module-level hook with a safe, headless default.

At boot the dashboard calls :func:`register` with its real implementations, so
a running GUI behaves exactly as before and ``workflow_jobs`` stays the single
shared dict both sides mutate. Run a pipeline without the dashboard — from a
cron job, a test, a CLI — and the defaults apply: the audit log still records,
and the GUI-only hooks are no-ops instead of ImportErrors.

Always call through the module (``runtime.bm_record(...)``), never
``from zyg_workflows.runtime import bm_record``: a from-import binds the
default and goes stale the moment the dashboard registers.
"""

import json
import logging as _zyg_logging
import os
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)

# ── the shared objects (owned here, not by the GUI) ────────────────────────────

# The single workflow-job registry: pipeline_id → job dict. The dashboard binds
# its `_workflow_jobs` to THIS object so both sides see the same jobs.
workflow_jobs: dict = {}

# Limit concurrent NVENC sessions — RTX consumer GPUs cap at 5 by default;
# holding 1 slot in reserve avoids "cannot allocate memory" under parallel load.
NVENC_SEM = threading.Semaphore(4)

# Set by register() once the dashboard exists; None when running headless.
app = None
limiter = None

# 2026-10-05 layering: the registries, locks and semaphores below were module
# globals in crewai_web_gui.py that the pipelines from-imported. They are owned
# here now and the GUI imports them back, so there is still exactly one of each.

# char_id → job dict, one registry per generation surface.
char_gen_jobs: dict = {}
creature_gen_jobs: dict = {}
contact_sheet_jobs: dict = {}

# At most two concurrent Ollama calls — 2 × ~5 GB fits beside a render.
ollama_semaphore = threading.Semaphore(2)

# Serialises writes to the narrator voice library / channel assignment files.
VOICE_LOCK = threading.Lock()

# Serialises appends to the agent logbook (one JSON file, many pipeline threads).
AGENT_LOG_LOCK = threading.Lock()


# Only ONE large-model (>20 GB VRAM) Ollama call at a time.
# llama3:70b = ~40 GB, qwen2.5:72b = ~47 GB — two of those = OOM.
# When a large model runs it ALSO drains both ollama_semaphore slots so no
# small model can run concurrently (41 GB + 2x5 GB = 51 GB > 49 GB GPU → VRAM critical).
class _LargeModelLock:
    """Acquires large_llm_semaphore AND both slots of ollama_semaphore so that
    a large model has exclusive GPU access while it is running."""

    def __enter__(self):
        ollama_semaphore.acquire()  # drain slot 1
        ollama_semaphore.acquire()  # drain slot 2 — no small model can run now
        return self

    def __exit__(self, *_):
        ollama_semaphore.release()
        ollama_semaphore.release()


large_llm_semaphore = _LargeModelLock()

try:
    _AMS_TZ = ZoneInfo('Europe/Amsterdam')
except (KeyError, OSError) as _exc:  # tzdata missing — ams_now() falls back to UTC
    _zyg_log.debug('Europe/Amsterdam tzdata unavailable, ams_now() falls back to UTC: %s', _exc)
    _AMS_TZ = None


# ── pure helpers (no GUI involved, so no hook needed) ──────────────────────────
def ams_now() -> datetime:
    """Timezone-aware now() in Europe/Amsterdam.

    Falls back to tz-aware UTC if tzdata is missing (still safe for arithmetic;
    it just displays in UTC). Never returns a naive datetime.
    """
    if _AMS_TZ is not None:
        try:
            return datetime.now(_AMS_TZ)
        except Exception as _exc:
            _zyg_log.debug('ams_now() fell back to UTC: %s', _exc)
    return datetime.now(timezone.utc)


def ams_iso(timespec: str = 'milliseconds') -> str:
    """ISO timestamp in Europe/Amsterdam including offset (e.g. ``+02:00``)."""
    try:
        return ams_now().isoformat(timespec=timespec)
    except TypeError:
        return ams_now().isoformat()


def runtime_dir() -> str:
    """The runtime scratch directory pipelines write transient state into."""
    return str(paths.ZYG_DATA_ROOT / 'runtime')


def runtime_path(filename: str) -> str:
    """Absolute path to a file in the runtime scratch directory.

    Only the basename of *filename* is used, so a caller that passes a
    ``/tmp/...`` path still writes inside the runtime directory.
    """
    return os.path.join(runtime_dir(), os.path.basename(filename))


ZERO_AUDIT_PATH = str(paths.ZYG_DATA_ROOT / 'zero_audit.jsonl')


def parse_iso_to_ams(s) -> 'datetime | None':
    """Parse any ISO-8601 string into a tz-aware Amsterdam ``datetime``.

    Tolerates the legacy formats this codebase has written over time:

    * ``2026-05-28T05:14:30.123`` (naive — assumed UTC)
    * ``2026-05-28T05:14:30.123Z`` (UTC marker)
    * ``2026-05-28T05:14:30.123+00:00`` (offset)
    * ``2026-05-28T05:14:30.123+02:00`` (Amsterdam summer offset)
    * ``2026-05-28 05:14:30`` (space separator)

    Returns ``None`` if the input is empty / unparseable. The result is
    always tz-aware and converted to Europe/Amsterdam so wall-clock
    arithmetic against :func:`ams_now` is well-defined.
    """
    if not s:
        return None
    if isinstance(s, datetime):
        dt = s
    else:
        text = str(s).strip()
        if not text:
            return None
        # Normalise: accept both 'T' and ' ' separators, strip trailing 'Z'.
        norm = text.replace(' ', 'T', 1)
        if norm.endswith('Z'):
            norm = norm[:-1] + '+00:00'
        try:
            dt = datetime.fromisoformat(norm)
        except Exception:
            return None
    if dt.tzinfo is None:
        # Legacy naive timestamps were written by ``datetime.utcnow()`` so
        # treat them as UTC, not local time.
        dt = dt.replace(tzinfo=timezone.utc)
    if _AMS_TZ is not None:
        try:
            return dt.astimezone(_AMS_TZ)
        except Exception:
            return dt
    return dt


def workflow_pipeline_worker_alive(pipeline_id: str) -> bool:
    """True when a live ``*-pipeline-<id8>`` daemon thread is running this job.
    Also recognizes the envfx-runner thread names (env-/fx-/wardrobe-/assetlib-<pid>) —
    without these, kanban_status stamped their RUNNING jobs 'Stale after restart' mid-run
    and the single-GPU busy gate stopped seeing them (2026-07-29 review fix)."""
    pid = (pipeline_id or '').strip()
    if not pid:
        return False
    prefix = pid[:8]
    needles = (
        f'scholarly-pipeline-{prefix}',
        f'crime-pipeline-{prefix}',
        f'video-pipeline-{prefix}',
        f'manga-pipeline-{prefix}',
        f'storyteller-pipeline-{prefix}',
        # pipeline_envfx_runner threads use the FULL 12-hex pid, no '-pipeline-'
        f'env-{pid}',
        f'fx-{pid}',
        f'wardrobe-{pid}',
        f'assetlib-{pid}',
        # pipeline_remix (2026-08-05) — same full-pid shape
        f'remix-{pid}',
        # briefing departments (2026-08-06) — pipeline_market / pipeline_sports,
        # thread name is always '<department>-<pid>' (briefing_jobs.mk_job)
        f'stocks-{pid}',
        f'crypto-{pid}',
        f'tokitoki-{pid}',
        f'arena-{pid}',
        # Children's Music (2026-08-29) — pipeline_kidsmusic, same full-pid shape.
        # Without this the job reported 'stopped' for its whole run, and the
        # board's idle branch forces every card back to QUEUED when it sees that.
        f'kidsmusic-{pid}',
        # Remix Ai (2026-08-29) — pipeline_remixai, same full-pid shape.
        f'remixai-{pid}',
        # 2D Character Basics I (2026-09-16) — pipeline_char2d, thread 'char2d-<pid>'.
        # Without it the first live run (8cdabf49a3b6) reported 'stopped' while
        # rendering, and the board never auto-followed the run.
        f'char2d-{pid}',
    )
    return any(t.name in needles and t.is_alive() for t in threading.enumerate())


# ── hooks: defaults that keep a headless pipeline correct ──────────────────────
def ensure_csrf_token() -> str:
    """Default: no Flask session to protect, so there is no token."""
    return ''


def zero_audit_log(action: str, payload: dict) -> None:
    """Append a Zero decision/action to the audit trail. Append-only, fail-safe."""
    try:
        entry = {
            'timestamp': ams_iso(),
            'actor': 'Agent Zero',
            'action': action,
            'payload': payload,
        }
        os.makedirs(os.path.dirname(ZERO_AUDIT_PATH), exist_ok=True)
        with open(ZERO_AUDIT_PATH, 'a', encoding='utf-8') as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as _exc:
        _zyg_log.warning('zero audit append failed, action %s was not recorded: %s', action, _exc)


def clear_pipeline_halt() -> None:
    """Clear the manual stop so a new pipeline run can proceed."""
    from zyg_workflows import gui_state, pipeline_control

    gui_state._pipeline_stop_flag = False
    try:
        pipeline_control.clear_halt()
    except Exception as _exc:
        _zyg_log.warning('pipeline_control.clear_halt failed, the halt may still be set: %s', _exc)


def gpu_work_active() -> bool:
    """Default: nothing else is on the GPU when no dashboard tracks it."""
    return False


def record_token_usage(*_args, **_kwargs) -> None:
    """Default: Claude token accounting is a dashboard feature; drop it."""
    return None


def bm_record(*_args, **_kwargs) -> None:
    """Default: benchmark timing is a dashboard feature; drop it."""
    return None


def bm_record_pipeline(*_args, **_kwargs) -> None:
    """Default: pipeline benchmark rows are a dashboard feature; drop it."""
    return None


def bench_replay_get(*_args, **_kwargs) -> None:
    """Default: no replay cache without the dashboard, so always a miss."""
    return None


def download_assets_background(*_args, **_kwargs) -> None:
    """Default: the background asset downloader lives in the dashboard."""
    return None


def agent_log(level: str, agent_id: str, pipeline_id: str, stage_name: str, message: str, extra: dict = None) -> None:
    """Write a single logbook entry. Thread-safe: a lock prevents concurrent write races.
    WARNING and ERROR entries are never rotated out — INFO entries cap at 1500."""
    try:
        with AGENT_LOG_LOCK:
            log_path = runtime_path('clipfarm_processing_log.json')
            entry = {
                'level': level,
                'agent': agent_id,
                'stage': stage_name,
                'pipeline_id': pipeline_id,
                'message': message,
                'timestamp': ams_iso(timespec='seconds'),
            }
            if extra:
                entry.update(extra)
            entries = []
            if os.path.exists(log_path):
                try:
                    with open(log_path) as _lf:
                        entries = json.load(_lf)
                except Exception:
                    entries = []
            entries.append(entry)
            # Keep all WARNING/ERROR; rotate INFO to last 1500
            if len(entries) > 3000:
                important = [e for e in entries if e.get('level') in ('WARNING', 'ERROR')]
                info_only = [e for e in entries if e.get('level') not in ('WARNING', 'ERROR')]
                entries = important + info_only[-1500:]
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, 'w') as _lf:
                json.dump(entries, _lf, indent=2)
        _zyg_log.info(f'[AGENT LOG] [{level}] {stage_name} | {agent_id} — {message}')
    except Exception as _le:
        _zyg_log.info(f'[AGENT LOG FAILED] {agent_id}: {_le}')


def push_error_log(level: str, stage: str, msg: str, pipeline_id: str = '') -> None:
    """Default: the dashboard Error Logs tab does not exist, so log and move on."""
    if level in ('ERROR', 'WARNING'):
        _zyg_log.error('[%s][%s] %s %s', level, stage, msg, pipeline_id)


def contact_sheet_push_review_pending(_char_id: str) -> None:
    """Default: the Agent Zero pending store is a dashboard feature; drop it."""
    return None


# The dashboard's CrewAI controller (agents, crews, LLM wiring). None headless;
# read it through the module so the dashboard's register() is seen.
controller = None


# The pre-emptive generation bank (zyg_dashboard.preempt_bank). None headless;
# callers must treat a None bank as "no brief available".
preempt_bank = None


_HOOK_NAMES = frozenset(
    {
        'app',
        'limiter',
        'preempt_bank',
        'workflow_jobs',
        'ensure_csrf_token',
        'zero_audit_log',
        'clear_pipeline_halt',
        'gpu_work_active',
        'record_token_usage',
        'bm_record',
        'bm_record_pipeline',
        'bench_replay_get',
        'download_assets_background',
        'agent_log',
        'push_error_log',
        'contact_sheet_push_review_pending',
        'controller',
    }
)


# ── legacy underscore aliases ─────────────────────────────────────────────────
# The pipelines spell these names with a leading underscore because that is how
# they were spelled in crewai_web_gui.py. Objects and pure functions are plain
# aliases; the overridable hooks are thin wrappers, so a from-import of the
# alias still reaches the implementation the dashboard registered later.
_char_gen_jobs = char_gen_jobs
_creature_gen_jobs = creature_gen_jobs
_contact_sheet_jobs = contact_sheet_jobs
_ollama_semaphore = ollama_semaphore
_large_llm_semaphore = large_llm_semaphore
_VOICE_LOCK = VOICE_LOCK
_AGENT_LOG_LOCK = AGENT_LOG_LOCK
_ams_now = ams_now
_ams_iso = ams_iso
_parse_iso_to_ams = parse_iso_to_ams
_runtime_path = runtime_path
_workflow_pipeline_worker_alive = workflow_pipeline_worker_alive


def _agent_log(*args, **kwargs):
    """Alias of the :func:`agent_log` hook, safe to from-import."""
    return agent_log(*args, **kwargs)


def _push_error_log(*args, **kwargs):
    """Alias of the :func:`push_error_log` hook, safe to from-import."""
    return push_error_log(*args, **kwargs)


def _contact_sheet_push_review_pending(*args, **kwargs):
    """Alias of the :func:`contact_sheet_push_review_pending` hook, safe to from-import."""
    return contact_sheet_push_review_pending(*args, **kwargs)


def register(**hooks) -> None:
    """Override hooks with the dashboard's real implementations.

    Called once from ``crewai_web_gui`` at boot (and again from the bottom
    import block, once the blueprints that own some of the hooks exist).
    Unknown names raise, so a typo is a boot failure and not a silently
    headless dashboard.
    """
    unknown = set(hooks) - _HOOK_NAMES
    if unknown:
        raise KeyError(f'runtime.register: unknown hook(s) {sorted(unknown)}')
    globals().update(hooks)


# ── second batch: the objects the stage/TTS/VRAM/video pipelines share ─────────
# Same ownership rule as the block at the top of this module: each of these was a
# module global in crewai_web_gui.py that pipelines from-imported, so it is owned
# here now and the dashboard imports it back. One object, two users.

# Cap concurrent post-process passes (outro overlay + bleep + loudnorm) — each is
# a ffmpeg process that can use GPU memory. 2 at a time keeps VRAM safe alongside
# the NVENC encodes.
POSTPROC_SEM = threading.Semaphore(2)

# Serializes GPU-heavy model stages across concurrent pipelines: two threads
# loading FLUX (~35 GB) + WAN (~28 GB) at once do not fit on a 48 GB card.
GPU_PIPELINE_LOCK = threading.Lock()

# ── subprocess registry — every ffmpeg/worker PID, so a stop can kill them ─────
SUBPROC_REGISTRY: dict = {}  # pid -> {label, started, status, pipeline_id}
SUBPROC_LOCK = threading.Lock()
SUBPROC_SYNTHETIC_COUNTER = [10_000_000]  # fake PIDs for pipeline markers (>OS range)

# Background telemetry sampler cache. The sampler reads the hardware every 2 s on
# its own daemon thread so a request never blocks on psutil or pynvml.
TELEMETRY_CACHE: dict = {}


def reconcile_stale_workflow_jobs() -> int:
    """Mark in-memory ``running`` workflow jobs without a live worker as stopped.

    The GUI spelled the liveness test ``not _workflow_job_gpu_active(job)``; with
    ``status == 'running'`` already required that reduces to "no live worker
    thread for this pipeline id", which is what is asked here directly.
    """
    n = 0
    for pid, job in list(workflow_jobs.items()):
        if job.get('status') != 'running':
            continue
        job_pid = (job.get('pipeline_id') or '').strip()
        if job_pid and workflow_pipeline_worker_alive(job_pid):
            continue
        job = dict(job)
        job['status'] = 'stopped'
        job['error'] = job.get('error') or 'Stale after restart (no live worker)'
        job['current_stage'] = None
        ev = job.get('stop_event')
        if ev is not None:
            ev.set()
        workflow_jobs[pid] = job
        n += 1
    if n:
        _zyg_log.info(f'[WORKFLOW] Reconciled {n} stale running workflow job(s) (no live worker)')
    return n


def backend_debug(msg) -> None:
    """Default: the GUI's CREWAI_BACKEND_DEBUG print goes to the logger instead."""
    _zyg_log.debug('%s', msg)


_HOOK_NAMES = _HOOK_NAMES | {'backend_debug'}

_POSTPROC_SEM = POSTPROC_SEM
_GPU_PIPELINE_LOCK = GPU_PIPELINE_LOCK
_SUBPROC_REGISTRY = SUBPROC_REGISTRY
_SUBPROC_LOCK = SUBPROC_LOCK
_SUBPROC_SYNTHETIC_COUNTER = SUBPROC_SYNTHETIC_COUNTER
_TELEMETRY_CACHE = TELEMETRY_CACHE
_NVENC_SEM = NVENC_SEM
_reconcile_stale_workflow_jobs = reconcile_stale_workflow_jobs


def _backend_debug(*args, **kwargs):
    """Alias of the :func:`backend_debug` hook, safe to from-import."""
    return backend_debug(*args, **kwargs)


def _record_token_usage(*args, **kwargs):
    """Alias of the :func:`record_token_usage` hook, safe to from-import."""
    return record_token_usage(*args, **kwargs)


def _bm_record(*args, **kwargs):
    """Alias of the :func:`bm_record` hook, safe to from-import."""
    return bm_record(*args, **kwargs)


def _bm_record_pipeline(*args, **kwargs):
    """Alias of the :func:`bm_record_pipeline` hook, safe to from-import."""
    return bm_record_pipeline(*args, **kwargs)


def _bench_replay_get(*args, **kwargs):
    """Alias of the :func:`bench_replay_get` hook, safe to from-import."""
    return bench_replay_get(*args, **kwargs)
