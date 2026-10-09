# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

# Generated 2026-07-17 by the GUI modularization (split out of zero_public_server.py).
# Source line refs: crews_modularization_backups_20260717/originals/zero_public_server.py

import json
import os
import threading
from zyg_zero.zpub_config import JOB_TTL, REDIS_URL, _ams_iso
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


# ── User activity log ─────────────────────────────────────────────────────────
_LOG_DIR = os.path.join(os.path.dirname(__file__), 'data', 'runtime')
ZPUB_LOG_PATH = os.environ.get('ZPUB_LOG_PATH', os.path.join(_LOG_DIR, 'zpub_user_log.jsonl'))
_log_lock = threading.Lock()

# ── Manual-permission pending queue (shared with crewai_web_gui via disk) ─────
_ZPUB_PENDING_PATH = os.path.join(_LOG_DIR, 'zpub_pending.json')
_pending_lock = threading.Lock()


def _pending_load() -> list:
    try:
        with open(_ZPUB_PENDING_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, ValueError):
        return []


def _pending_save(data: list) -> None:
    os.makedirs(_LOG_DIR, exist_ok=True)
    tmp = _ZPUB_PENDING_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, _ZPUB_PENDING_PATH)


def _pending_store(req: dict) -> str:
    """Add a pending request and return its id."""
    with _pending_lock:
        data = _pending_load()
        data.append(req)
        _pending_save(data)
    return req['id']


# ── Job disk persistence ────────────────────────────────────────────────────────
_JOB_PERSIST_DIR = os.path.join(_LOG_DIR, 'zpub_jobs')


def _persist_job(job: dict) -> None:
    """Write a single job to disk as <job_id>.json (survives server restarts)."""
    try:
        os.makedirs(_JOB_PERSIST_DIR, exist_ok=True)
        fpath = os.path.join(_JOB_PERSIST_DIR, f'{job["job_id"]}.json')
        with open(fpath, 'w', encoding='utf-8') as _jf:
            json.dump(job, _jf, ensure_ascii=False)
    except Exception as _je:
        _zyg_log.info(f'[ZeroPub] job persist error: {_je}')


def _load_job_from_disk(job_id: str) -> dict | None:
    """Load a persisted job from disk. Returns None if not found."""
    try:
        fpath = os.path.join(_JOB_PERSIST_DIR, f'{job_id}.json')
        if os.path.isfile(fpath):
            with open(fpath, 'r', encoding='utf-8') as _jf:
                return json.load(_jf)
    except Exception as _exc:
        _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return None


def _zpub_log(event: str, **kwargs) -> None:
    """Append one JSON-lines entry to the user-activity log (thread-safe)."""
    entry = {
        'ts': _ams_iso(timespec='seconds'),
        'event': event,
    }
    entry.update(kwargs)
    try:
        os.makedirs(os.path.dirname(ZPUB_LOG_PATH), exist_ok=True)
        with _log_lock:
            with open(ZPUB_LOG_PATH, 'a', encoding='utf-8') as _f:
                _f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception as _e:
        _zyg_log.info(f'[ZeroPub] log write error: {_e}')


# ── Redis ─────────────────────────────────────────────────────────────────────
_redis = None


def _get_redis():
    """Return a live Redis client, or None if unavailable."""
    global _redis
    if _redis is not None:
        try:
            _redis.ping()
            return _redis
        except Exception:
            _redis = None
    try:
        import redis

        r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=3)
        r.ping()
        _redis = r
        return r
    except Exception as e:
        _zyg_log.info(f'[ZeroPub] Redis unavailable: {e}')
        return None


# ── Redis key helpers ──────────────────────────────────────────────────────────
_QUEUE_KEY = 'zpub:queue'
_RUNNING_KEY = 'zpub:running'
_HALT_KEY = 'zpub:halted'  # set by main-app halt; persists across Flask restarts


def _jk(job_id: str) -> str:
    return f'zpub:job:{job_id}'


def _sk(sess_id: str) -> str:
    return f'zpub:sess:{sess_id}'


def _rk(ip: str) -> str:
    return f'zpub:rate:{ip}'


def _tk(token: str) -> str:
    return f'zpub:token:{token}'


# ── In-memory fallback (when Redis is unavailable) ────────────────────────────
_mem_queue: list = []
_mem_jobs: dict = {}
_mem_running: str | None = None
_mem_lock = threading.Lock()
_tok_lock = threading.Lock()  # guards on-disk token→job index writes


# ── Job persistence helpers ────────────────────────────────────────────────────


def _save_job(job: dict) -> None:
    r = _get_redis()
    if r:
        try:
            r.setex(_jk(job['job_id']), JOB_TTL, json.dumps(job))
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        _mem_jobs[job['job_id']] = job
    _persist_job(job)  # always write to disk so data survives restarts


def _load_job(job_id: str) -> dict | None:
    r = _get_redis()
    if r:
        try:
            raw = r.get(_jk(job_id))
            if raw:
                return json.loads(raw)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        job = _mem_jobs.get(job_id)
    if job:
        return job
    # Fall back to disk — warms up memory cache too
    job = _load_job_from_disk(job_id)
    if job:
        with _mem_lock:
            _mem_jobs[job_id] = job
    return job


def _enqueue(job_id: str) -> None:
    r = _get_redis()
    if r:
        try:
            r.rpush(_QUEUE_KEY, job_id)
            return
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        _mem_queue.append(job_id)


def _queue_length() -> int:
    r = _get_redis()
    if r:
        try:
            return r.llen(_QUEUE_KEY)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        return len(_mem_queue)


def _queue_position(job_id: str) -> int:
    """1-based position in the queue. 0 means the job is not queued."""
    r = _get_redis()
    if r:
        try:
            items = r.lrange(_QUEUE_KEY, 0, -1)
            return (items.index(job_id) + 1) if job_id in items else 0
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        try:
            return _mem_queue.index(job_id) + 1
        except ValueError:
            return 0


def _get_running() -> str | None:
    r = _get_redis()
    if r:
        try:
            return r.get(_RUNNING_KEY) or None
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        return _mem_running


def _set_running(job_id: str | None) -> None:
    global _mem_running
    r = _get_redis()
    if r:
        try:
            if job_id:
                r.setex(_RUNNING_KEY, JOB_TTL, job_id)
            else:
                r.delete(_RUNNING_KEY)
            return
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    with _mem_lock:
        _mem_running = job_id


def _persist_session_index(sess_id: str, job_id: str) -> None:
    """Append job_id to the on-disk session→jobs index so a browser's library
    survives Redis loss (mirrors _persist_token_index)."""
    try:
        os.makedirs(_JOB_PERSIST_DIR, exist_ok=True)
        idx = os.path.join(_JOB_PERSIST_DIR, f'_sess_{sess_id}.json')
        with _tok_lock:
            ids: list = []
            if os.path.isfile(idx):
                try:
                    with open(idx) as _f:
                        ids = json.load(_f)
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            if job_id not in ids:
                ids.append(job_id)
            with open(idx, 'w') as _f:
                json.dump(ids, _f)
    except Exception as _e:
        _zyg_log.info(f'[ZeroPub] session index persist error: {_e}')


def _link_session_job(sess_id: str, job_id: str) -> None:
    r = _get_redis()
    if r:
        try:
            r.rpush(_sk(sess_id), job_id)
            r.expire(_sk(sess_id), JOB_TTL)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    _persist_session_index(sess_id, job_id)


def _session_jobs(sess_id: str) -> list[str]:
    r = _get_redis()
    if r:
        try:
            ids = r.lrange(_sk(sess_id), 0, -1)
            if ids:
                return ids
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    # Disk fallback — used after Redis restart/eviction, or once JOB_TTL
    # expires the Redis list. The disk index has no expiry, so this is what
    # keeps a browser's library alive across invite-token rotation.
    idx = os.path.join(_JOB_PERSIST_DIR, f'_sess_{sess_id}.json')
    if os.path.isfile(idx):
        try:
            with open(idx) as _f:
                return json.load(_f)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    return []


def _persist_token_index(token: str, job_id: str) -> None:
    """Append job_id to the on-disk token→jobs index so it survives Redis loss."""
    try:
        os.makedirs(_JOB_PERSIST_DIR, exist_ok=True)
        idx = os.path.join(_JOB_PERSIST_DIR, f'_tok_{token}.json')
        with _tok_lock:
            ids: list = []
            if os.path.isfile(idx):
                try:
                    with open(idx) as _f:
                        ids = json.load(_f)
                except Exception as _exc:
                    _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
            if job_id not in ids:
                ids.append(job_id)
            with open(idx, 'w') as _f:
                json.dump(ids, _f)
    except Exception as _e:
        _zyg_log.info(f'[ZeroPub] token index persist error: {_e}')


def _link_token_job(token: str, job_id: str) -> None:
    """Index job_id under invite token in Redis + disk (drives the persistent sidebar)."""
    r = _get_redis()
    if r:
        try:
            r.rpush(_tk(token), job_id)
            r.expire(_tk(token), JOB_TTL)
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    _persist_token_index(token, job_id)


def _jobs_for_token(token: str) -> list[dict]:
    """Return all jobs for an invite token, newest first (max 50)."""
    job_ids: list[str] = []
    r = _get_redis()
    if r:
        try:
            job_ids = r.lrange(_tk(token), 0, -1) or []
        except Exception as _exc:
            _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    if not job_ids:
        # Disk fallback — used after Redis restart or memory loss
        idx = os.path.join(_JOB_PERSIST_DIR, f'_tok_{token}.json')
        if os.path.isfile(idx):
            try:
                with open(idx) as _f:
                    job_ids = json.load(_f)
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
    jobs = []
    for jid in reversed(job_ids[-50:]):  # newest first, cap at 50
        j = _load_job(jid)
        if j:
            jobs.append(j)
    return jobs


def _jobs_for_library(token: str, sess_id: str) -> list[dict]:
    """Return the persistent "Library" sidebar contents for one browser.

    Keyed primarily off the stable per-browser session id (a long-lived
    cookie), so history survives invite-link rotation/expiry — invite tokens
    are 7-day and single-use-family, so a token-only lookup orphans every
    past generation the moment the visitor gets issued a new link. Jobs
    linked to the *current* token are merged in too, covering jobs submitted
    before this session cookie existed. Deduped by job_id, newest first.
    """
    by_id: dict[str, dict] = {}
    for jid in _session_jobs(sess_id):
        j = _load_job(jid)
        if j:
            by_id[j['job_id']] = j
    if token and token != '__admin__':  # noqa: S105  '__admin__' is the public sentinel for an admin session, not a secret
        for j in _jobs_for_token(token):
            by_id[j['job_id']] = j
    jobs = sorted(by_id.values(), key=lambda j: j.get('created_at', ''), reverse=True)
    return jobs[:50]


def _check_rate_limit(ip: str) -> bool:
    """Rate limiting is handled per-token by the invite system (max_requests).
    This IP-level check is disabled to avoid blocking the owner using multiple sessions."""
    return True
