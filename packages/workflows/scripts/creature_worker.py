#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""
creature_worker.py — run a creature job OUTSIDE the GUI process.

    .venv/bin/python scripts/creature_worker.py --ref REF.png [--ref …] --name "Zygo AI Pufferball" [--angles standard|compact] [--no-review]
    .venv/bin/python scripts/creature_worker.py --scratch "text brief" [--name …]
    .venv/bin/python scripts/creature_worker.py --resume <creature_id> [--phase full|sheet|train]

Why (2026-08-25): the GUI-hosted worker is a thread inside crewai-gui, so ANY
GUI restart kills it — another session restarted the GUI 79 s into the first
pufferball run. This runner executes the identical creature_training_service
flow in its own process and writes the same data/runtime/creature_gen_<id>.json
(with worker.pid) that the dashboard, kanban board and status API read, so the
board still lights up and approve/reject still work. Sheet checkpoints make
--resume cheap after any interruption.

Stop a run: create data/runtime/creature_stop_<id> (or Ctrl-C).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

_CREWS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _CREWS)
os.chdir(_CREWS)
RUNTIME = os.path.join(_CREWS, 'data', 'runtime')
_AMS = ZoneInfo('Europe/Amsterdam')


def _ams_iso() -> str:
    return datetime.now(_AMS).isoformat()


def state_path(cid: str) -> str:
    return os.path.join(RUNTIME, f'creature_gen_{cid}.json')


def stop_path(cid: str) -> str:
    return os.path.join(RUNTIME, f'creature_stop_{cid}')


def load_state(cid: str) -> dict | None:
    try:
        with open(state_path(cid), encoding='utf-8') as fh:
            return json.load(fh)
    except Exception:
        return None


def save_state(job: dict) -> None:
    snap = {k: v for k, v in job.items() if k != 'stop_event'}
    evs = snap.get('debug_events') or []
    if len(evs) > 50:
        snap['debug_events'] = evs[-50:]
    os.makedirs(RUNTIME, exist_ok=True)
    tmp = state_path(job['creature_id']) + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(snap, fh, default=str)
    os.replace(tmp, state_path(job['creature_id']))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--ref', action='append', default=[])
    ap.add_argument('--scratch', default='')
    ap.add_argument('--name', default='')
    ap.add_argument('--angles', default='standard', choices=('standard', 'compact'))
    ap.add_argument('--no-review', action='store_true')
    ap.add_argument('--resume', default='')
    ap.add_argument('--phase', default='full', choices=('full', 'sheet', 'train'))
    a = ap.parse_args()

    os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
    os.environ.setdefault('ZYG_USE_COMFYUI', '1')
    from zyg_workflows import creature_training_service as cts

    if a.resume:
        job = load_state(a.resume)
        if not job:
            print(f'no state for creature {a.resume}')
            return 2
        w = job.get('worker') or {}
        if w.get('pid'):
            try:
                os.kill(int(w['pid']), 0)
                print(f'creature {a.resume} already has a live worker pid {w["pid"]}')
                return 3
            except OSError:
                pass
        if a.phase == 'train' and job.get('status') != 'awaiting_review':
            print(f'phase train needs awaiting_review, job is {job.get("status")}')
            return 2
        cid = a.resume
        directive = job.get('directive') or ''
        image_paths = job.get('image_paths') or []
        _was = job.get('status')
        job['status'] = 'running'
        job['error'] = None
        job['resumed'] = _ams_iso()
        # Flag the idle span this resume is ending. The pipeline runtime
        # excludes it, so it has to be recorded and logged, or the wall clock
        # would silently exceed the runtime with nothing to point at.
        try:
            from zyg_workflows.pipeline_runtime import pause_log_line, record_pause

            _reason = (
                'operator gate — sheet review' if _was == 'awaiting_review' else f'worker not running (job was {_was})'
            )
            _pause = record_pause(job, resumed_at=job['resumed'], reason=_reason)
            if _pause:
                _line = pause_log_line(job, _pause)
                job.setdefault('debug_events', []).append(
                    {'ts': job['resumed'], 'level': 'WARN', 'stage': 'Runtime', 'msg': _line}
                )
                print(f'[{job["resumed"][11:19]}][WARN][Runtime] {_line}', flush=True)
        except Exception as _e:
            print(f'pause record failed (non-fatal): {_e}', flush=True)
    else:
        refs = [os.path.abspath(p) for p in a.ref]
        for p in refs:
            if not os.path.isfile(p):
                print(f'reference not found: {p}')
                return 2
        if not refs and not a.scratch:
            print('give --ref IMAGE or --scratch "brief"')
            return 2
        cid = uuid.uuid4().hex[:12]
        directive = a.name or a.scratch
        image_paths = refs
        job = {
            'creature_id': cid,
            'status': 'running',
            'stage': 'creature_brief',
            'current_stage': cts.STAGE_BRIEF,
            'started': _ams_iso(),
            'directive': directive,
            'image_paths': image_paths,
            'model_family': 'klein',
            'pipeline_options': {},
            'creature_options': cts.normalize_options(
                {
                    'source': 'scratch' if a.scratch and not refs else 'reference',
                    'angles': a.angles,
                    'review_gate': not a.no_review,
                }
            ),
            'phase': a.phase,
            'error': None,
            'debug_events': [],
            'stage_timeline': [],
            'department': 'creature',
        }
    job['worker'] = {'pid': os.getpid(), 'mode': 'standalone', 'started': _ams_iso(), 'phase': a.phase}
    save_state(job)
    print(f'creature {cid} — {"resume" if a.resume else "new"} phase={a.phase} pid={os.getpid()}', flush=True)

    def _halt():
        if os.path.isfile(stop_path(cid)):
            raise RuntimeError('Creature training stopped by user')
        try:
            from zyg_workflows import pipeline_control as _pc

            if _pc.halt_requested():
                raise RuntimeError('Creature training stopped by user')
        except ImportError:
            pass

    def _log(level, stage, msg):
        ev = {'ts': _ams_iso(), 'level': level, 'stage': stage, 'msg': msg}
        job.setdefault('debug_events', []).append(ev)
        if len(job['debug_events']) > 500:
            job['debug_events'] = job['debug_events'][-300:]
        print(f'[{ev["ts"][11:19]}][{level}][{stage}] {str(msg)[:220]}', flush=True)
        if level != 'INFO' or 'cell ' in str(msg) or 'judge' in str(msg):
            save_state(job)

    # char_state_service imports Flask — replicate its pure stage-key mapper
    def _stage_key(name: str) -> str:
        sl = (name or '').lower()
        for needle, key in (
            ('brief', 'creature_brief'),
            ('anchor', 'anchor'),
            ('preview', 'preview_render'),
            ('review', 'sheet_review'),
            ('qc', 'sheet_qc'),
            ('sheet', 'sheet'),
            ('caption', 'captions'),
            ('lora', 'lora_training'),
            ('training', 'lora_training'),
        ):
            if needle in sl:
                return key
        return sl.replace(' ', '_')[:40] or 'creature_brief'

    def _set_stage(name, status='running'):
        _halt()
        job['current_stage'] = name
        job['stage'] = _stage_key(name)
        tl = job.setdefault('stage_timeline', [])
        now = _ams_iso()
        # A worker is in exactly one stage at a time.  Rows a previous stage
        # left open used to stay 'running' forever, so the Kanban card dialog
        # showed a second card still ticking: on 2026-08-26 both 'Sheet Review'
        # and 'Multi-Angle Sheet' claimed to be running, the review gate having
        # been left open when its sheet was sent back for another pass.
        for entry in tl:
            if entry.get('name') != name and entry.get('status') == 'running':
                entry['status'] = 'completed'
                if not entry.get('ended_at'):
                    entry['ended_at'] = now
        # Newest row for this stage wins.  Re-running a stage that had already
        # finished appends a fresh row instead of reopening the old one: reusing
        # it left the previous attempt's 'started_at' AND 'ended_at' in place, so
        # the card clock dated the abandoned pass — that same run reported
        # 'Multi-Angle Sheet' as running for 20h22m when its live attempt had
        # started 4h earlier that evening.  Appending also keeps the finished
        # span visible to pipeline_runtime's activity intervals.
        for entry in reversed(tl):
            if entry.get('name') != name:
                continue
            if status == 'running' and entry.get('ended_at'):
                break  # finished earlier → fresh row below
            entry['status'] = status
            if status != 'running' and not entry.get('ended_at'):
                entry['ended_at'] = now
            save_state(job)
            return
        tl.append(
            {
                'name': name,
                'status': status,
                'ts': now,
                'started_at': now,
                'ended_at': now if status != 'running' else None,
            }
        )
        save_state(job)

    def _complete(name):
        _set_stage(name, 'completed')

    def _fail(name, err):
        _set_stage(name, 'failed')
        job['status'] = 'failed'
        job['error'] = err
        job['ended'] = _ams_iso()
        save_state(job)
        _log('ERROR', name, err)

    def _sig(*_):
        open(stop_path(cid), 'w').close()

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    t0 = time.time()
    try:
        cts.run_creature_training(
            job,
            cid,
            directive,
            image_paths=image_paths,
            model_family='klein',
            set_stage=_set_stage,
            complete_stage=_complete,
            fail_stage=_fail,
            log_fn=_log,
            halt_check=_halt,
            phase=a.phase,
        )
    except RuntimeError as exc:
        if 'stopped by user' in str(exc).lower():
            job['status'] = 'stopped'
            job['error'] = str(exc)
            job['ended'] = _ams_iso()
    finally:
        try:
            os.remove(stop_path(cid))
        except OSError:
            pass
        job['worker'] = {**job.get('worker', {}), 'pid': None, 'ended': _ams_iso()}
        if job.get('status') == 'running':
            job['status'] = 'failed'
            job['error'] = job.get('error') or 'worker exited without a terminal status'
        if job.get('status') == 'completed':
            job['stage'] = 'done'
            job['current_stage'] = 'done'
        save_state(job)
    print(
        f'creature {cid}: {job.get("status")} in {time.time() - t0:.0f}s'
        + (f' — sheet {job.get("sheet_path")}' if job.get('sheet_path') else '')
        + (f' — {job.get("error")}' if job.get('error') else ''),
        flush=True,
    )
    return 0 if job.get('status') in ('awaiting_review', 'completed') else 1


if __name__ == '__main__':
    sys.exit(main())
