# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Video Studio, job registry — the dict the client polls, and its lock.

Moved verbatim (lines 5131-5189 of the old single-file module). One render at
a time (_RENDER_GATE): Wan wants the whole GPU, the same discipline
voice_studio uses for TTS. The job records themselves are owned here; the
workers in presets.py and assembly.py write into them through _job_set /
_job_log.
"""

import threading
import time

from .spec import nondefault


# ──────────────────────────────────────────────────────────────── render jobs
# One render at a time — Wan wants the whole GPU, same discipline voice_studio
# uses for TTS.
_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()
_RENDER_GATE = threading.Semaphore(1)
_JOB_KEEP = 24


def _job_set(jid: str, **kw):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j.update(kw)


def _job_log(jid: str, msg: str):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j['log'].append(f'{time.strftime("%H:%M:%S")} {msg}')
            j['log'] = j['log'][-240:]


def job(jid: str) -> dict:
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        return dict(j) if j else {}


def jobs() -> list:
    """Recent jobs, newest first — the History icon's feed."""
    with _JOBS_LOCK:
        out = sorted(_JOBS.values(), key=lambda j: j['started'], reverse=True)
        return [
            {
                'id': j['id'],
                'label': j['char_name'],
                'state': j['state'],
                'url': j['url'],
                'urls': j.get('urls', []),
                'error': j['error'],
                'started': j['started'],
                'finished': j['finished'],
                'changed': nondefault(j['params']),
            }
            for j in out
        ]


def _prune_jobs():
    """Keep the last _JOB_KEEP jobs, never evicting one still in flight. Caller
    holds _JOBS_LOCK."""
    live = {k for k, j in _JOBS.items() if j.get('state') in ('queued', 'running')}
    finished = [k for k in sorted(_JOBS, key=lambda k: _JOBS[k]['started']) if k not in live]
    for old in finished[: max(0, len(finished) - _JOB_KEEP)]:
        _JOBS.pop(old, None)
