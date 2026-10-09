# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character job state file: path, save, stage timeline start/end.

Moved verbatim out of the old single-file char_state_service.py (lines 53-152).
"""

import json
import os
from zyg_workflows.pipeline_config import (
    _CHAR_STATE_FILENAME_FMT,
)
from zyg_workflows.runtime import (
    _ams_iso,
    _char_gen_jobs,
    _parse_iso_to_ams,
    _runtime_path,
)
from zyg_workflows.char_state_service._common import (
    _zyg_log,
)


def _char_state_path(char_id: str) -> str:
    """Return the on-disk path for a character generation state file."""
    safe_id = ''.join(c for c in (char_id or '') if c.isalnum() or c in '-_')
    return _runtime_path(_CHAR_STATE_FILENAME_FMT.format(char_id=safe_id or 'unknown'))


def _char_save_state(char_id: str) -> None:
    """Persist the current _char_gen_jobs[char_id] dict to disk (non-fatal)."""
    try:
        job = _char_gen_jobs.get(char_id)
        if not job:
            return
        # Strip live-tail events to keep the file small — keep only the last 50
        snapshot = dict(job)
        evs = snapshot.get('debug_events') or []
        if len(evs) > 50:
            snapshot['debug_events'] = evs[-50:]
        os.makedirs(os.path.dirname(_char_state_path(char_id)), exist_ok=True)
        tmp_path = _char_state_path(char_id) + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as _fh:
            json.dump(snapshot, _fh, default=str)
        os.replace(tmp_path, _char_state_path(char_id))
    except Exception as _e:
        try:
            _zyg_log.info(f'[CHAR-STATE] save failed for {char_id}: {_e}')
        except Exception as _exc:
            _zyg_log.debug('console echo of the save failure skipped: %s', _exc)


def _char_stage_start(char_id: str, name: str) -> None:
    """Begin a stage: record started_at in the stage_timeline and persist."""
    job = _char_gen_jobs.get(char_id)
    if not job:
        return
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('name') == name:
            # Already started — leave existing started_at intact, just reopen
            entry['status'] = 'running'
            if not entry.get('started_at'):
                entry['started_at'] = now
            entry['ended_at'] = None
            entry['elapsed_s'] = None
            _char_save_state(char_id)
            return
    tl.append(
        {
            'name': name,
            'status': 'running',
            'started_at': now,
            'ended_at': None,
            'elapsed_s': None,
            'extra': {},
        }
    )
    job['current_stage'] = name
    _char_save_state(char_id)


def _char_stage_end(char_id: str, name: str, status: str = 'completed', extra: dict | None = None) -> None:
    """Close a stage: compute elapsed_s, set ended_at, persist. status='completed'|'failed'|'skipped'."""
    job = _char_gen_jobs.get(char_id)
    if not job:
        return
    tl = job.setdefault('stage_timeline', [])
    now = _ams_iso()
    for entry in tl:
        if entry.get('name') == name:
            entry['status'] = status
            entry['ended_at'] = now
            if entry.get('started_at'):
                try:
                    _end_dt = _parse_iso_to_ams(now)
                    _start_dt = _parse_iso_to_ams(entry['started_at'])
                    if _end_dt and _start_dt:
                        entry['elapsed_s'] = round((_end_dt - _start_dt).total_seconds(), 1)
                    else:
                        entry['elapsed_s'] = None
                except Exception:
                    entry['elapsed_s'] = None
            if extra:
                entry.setdefault('extra', {}).update(
                    {k: v for k, v in extra.items() if isinstance(v, (str, int, float, bool)) or v is None}
                )
            _char_save_state(char_id)
            return
    # Closing a stage that was never started: record a zero-length entry
    tl.append(
        {
            'name': name,
            'status': status,
            'started_at': now,
            'ended_at': now,
            'elapsed_s': 0.0,
            'extra': {k: v for k, v in (extra or {}).items() if isinstance(v, (str, int, float, bool)) or v is None},
        }
    )
    _char_save_state(char_id)
