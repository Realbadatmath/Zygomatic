# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kanban_video_status.py — live Kanban state for STANDALONE VACE video runs (2026-08-01).

WHY THIS EXISTS — "I never see an actual workflow active in the kanban boards".

/api/kanban/status (bp_pipeline_api.py:592) builds its card map from
``_workflow_jobs``, an IN-PROCESS dict that is only ever populated by pipelines
launched THROUGH the GUI (POST /api/internal/pipeline/start). The Second Ledger
scene renders (scene20_v11/v12/v13) are standalone scripts driven from a shell,
so they never enter that dict. Measured 2026-08-01 09:35, while scene20_v13 was
actively sampling on the GPU:

    GET /api/kanban/status  ->  {"template":"documentary","pipeline":null,"cards":{}}

and kanban_main.js:2628 forces EVERY card to 'queued' whenever the pipeline is
not running. So the board was never wrong — it was never told. Nothing about the
render was broken; the reporting path simply did not exist.

THE SOURCE OF TRUTH IS THE RUN LOGBOOK, NOT THE PROCESS.
run_logbook.py already appends one JSONL record per stage to
    data/runtime/logbook/<run_key>.jsonl
Reading that gives live state with NO coupling to the running script:
  - a GUI restart cannot lose it (the process holds no state we need),
  - a crashed render stops advancing instead of lying "running" forever,
  - a finished run replays exactly, so the board is also a history view,
  - and the CURRENTLY RUNNING render needed no modification to be seen.

LIVENESS IS A PROCESS CHECK, NOT A TIMEOUT — THIS IS THE SUBTLE PART.
The 'probe_and_render' stage runs ~90 minutes and emits NO intermediate logbook
event. Any "stale if idle for N minutes" rule marks a perfectly healthy render
dead exactly when the operator is most likely to be watching it. So liveness is:

    1. the driver process is alive   (scan /proc for the recorded driver path)   -> RUNNING
    2. else recent event activity    (< STALE_AFTER_S)                           -> RUNNING
    3. else                                                                      -> STALE

Rule 1 is what carries the 90-minute render; rule 2 only covers the gap where a
driver path was not recorded. A run whose process died mid-render goes STALE and
the board stops claiming it is working, which is the honest failure mode.

CARD NAMES ARE THE DRIVER'S REAL STAGE NAMES.
STAGE_CARDS below is a 1:1 map of the eleven stages scene20_v13.py actually
emits (verified by grepping its stage() call sites, not by guessing). The old
KANBAN_STAGE_MAP_VIDEO described a completely different pipeline (FLUX keyframe
-> WAN2.1-I2V -> ffmpeg loop) and never matched a single VACE stage name.
"""

import json
import os
import time
from datetime import datetime
import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


CREWS_DIR = os.path.dirname(os.path.abspath(__file__))
LOGBOOK_DIR = os.path.join(CREWS_DIR, 'data', 'runtime', 'logbook')

# A run with no driver process AND no event this recent is treated as stale.
# Only used when the driver path is unknown — see the liveness note above.
STALE_AFTER_S = int(os.environ.get('ZYG_KANBAN_VIDEO_STALE_S', '1800'))

# Runs older than this are never surfaced as "active", even if the file lingers.
MAX_RUN_AGE_S = int(os.environ.get('ZYG_KANBAN_VIDEO_MAX_AGE_S', '86400'))

# ── THE BOARD ────────────────────────────────────────────────────────────────
# (stage name emitted by the driver, card title shown on the board, column id).
# Keep this in the SAME order the driver runs them: the status mapper uses index
# order to decide what is already done.
STAGE_CARDS = [
    ('resolve', 'Resolve Run Config', 'setup'),
    ('candle_pin', 'Candle Graded Pin', 'setup'),
    ('preflight_gates', 'Preflight Gates', 'preflight'),
    ('probe_and_render', 'VACE Render', 'render'),
    ('ink_writeon_quad', 'Ink Write-On Quad', 'fx'),
    ('smoke_two_layer', 'Pipe Smoke (2-layer)', 'fx'),
    ('vlm_final_checklist', 'VLM Inspection', 'qa'),
    ('upscale', 'Upscale + Interpolate', 'finish'),
    ('qc', 'QC Gates', 'qa'),
    ('ambience_audio', 'Ambience + Audio Mix', 'finish'),
    ('report', 'Report + Logbook', 'finish'),
]
STAGE_ORDER = {s: i for i, (s, _c, _col) in enumerate(STAGE_CARDS)}
CARD_FOR_STAGE = {s: c for (s, c, _col) in STAGE_CARDS}
CARD_TITLES = [c for (_s, c, _col) in STAGE_CARDS]

# Checkpoints that mean "this run ended badly" (run_logbook records these as
# checkpoint stages, not as stage events).
FAIL_CHECKPOINTS = {'render_failed', 'blocked'}

# Which series a run belongs to. Keyed by a path fragment of the run_dir so a new
# scene under the same series needs no code change. id matches the ids served by
# kanban_server /kanban/api/series (data/runtime/storyteller_templates.json).
SERIES_BY_PATH = [
    ('output/multichar_seated', 'st_second_ledger', 'The Second Ledger'),
]
DEFAULT_SERIES = (None, 'Video')


def _log_noop(_m):
    pass


def _driver_process_alive(driver_path):
    """True when a python process is running that exact driver file.

    Deliberately NOT a substring match on the whole cmdline: the shell wrapper
    that launched the run, and any grep looking for it, both contain the path
    too. Requiring argv[0] to be a python interpreter excludes them.
    """
    if not driver_path:
        return False
    try:
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                with open(f'/proc/{pid}/cmdline', 'rb') as fh:
                    parts = fh.read().split(b'\0')
            except (OSError, IOError) as _exc:
                _zyg_log.debug('pid %s vanished while reading its cmdline: %s', pid, _exc)
                continue
            if len(parts) < 2:
                continue
            argv0 = os.path.basename((parts[0] or b'').decode('utf-8', 'replace'))
            if not argv0.startswith('python'):
                continue
            for a in parts[1:]:
                if a and a.decode('utf-8', 'replace') == driver_path:
                    return True
    except Exception:
        return False
    return False


def _read_session(path):
    """Parse the LAST run session out of an append-only logbook jsonl.

    A logbook file accumulates every session for that run_key, including dry
    runs (scene20_v13.jsonl held six start/finish pairs from validation before
    the live run). Only records after the final 'start' describe the run the
    operator is watching. Torn last lines are skipped, not fatal.
    """
    recs = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            for ln in fh:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    recs.append(json.loads(ln))
                except json.JSONDecodeError as _exc:
                    _zyg_log.debug('torn jsonl record skipped: %s', _exc)
                    continue
    except (OSError, IOError):
        return None
    if not recs:
        return None
    starts = [i for i, d in enumerate(recs) if (d.get('event') or d.get('type')) == 'start']
    if not starts:
        return None
    return recs[starts[-1] :]


def _series_for(run_dir):
    rd = (run_dir or '').replace('\\', '/')
    for frag, sid, title in SERIES_BY_PATH:
        if frag in rd:
            return sid, title
    return DEFAULT_SERIES


def read_run(path, now=None):
    """-> dict describing one logbook file's latest session, or None."""
    now = now or time.time()
    sess = _read_session(path)
    if not sess:
        return None
    head = sess[0]
    run_key = head.get('run_key') or os.path.splitext(os.path.basename(path))[0]
    run_dir = head.get('run_dir') or ''
    version = head.get('version') or ''
    driver = (head.get('driver') or {}).get('abs') or (head.get('driver') or {}).get('path')
    started = float(head.get('ts') or 0.0)
    dry_run = 'dry_run=True' in (head.get('notes') or '')

    stages_seen = []
    stage_ts = {}  # stage name -> epoch of its first 'stage' event
    fail_stage = None
    finished = False
    verdict = None
    last_ts = started
    for d in sess:
        ev = d.get('event') or d.get('type')
        ts = d.get('ts')
        if isinstance(ts, (int, float)):
            last_ts = max(last_ts, float(ts))
        if ev == 'stage':
            nm = d.get('stage') or d.get('name')
            if nm and nm not in stages_seen:
                stages_seen.append(nm)
                if isinstance(ts, (int, float)):
                    stage_ts[nm] = float(ts)
            if str(d.get('status') or '').lower() in ('error', 'fail', 'failed'):
                fail_stage = nm
        elif ev == 'checkpoint':
            nm = d.get('stage') or d.get('name')
            if nm in FAIL_CHECKPOINTS:
                fail_stage = fail_stage or (stages_seen[-1] if stages_seen else None)
        elif ev == 'finish':
            finished = True
            verdict = d.get('verdict') or d.get('status')

    known = [s for s in stages_seen if s in STAGE_ORDER]
    current = None
    if known:
        current = max(known, key=lambda s: STAGE_ORDER[s])

    alive = _driver_process_alive(driver)
    age = now - last_ts
    if finished:
        state = 'done'
    elif fail_stage:
        state = 'error'
    elif alive:
        state = 'running'
    elif age < STALE_AFTER_S:
        state = 'running'
    else:
        state = 'stale'

    return {
        'run_key': run_key,
        'run_dir': run_dir,
        'version': version,
        'driver': driver,
        'driver_alive': alive,
        'started': started,
        'started_iso': head.get('ts_iso') or head.get('started') or '',
        'last_event_ts': last_ts,
        'last_event_age_s': round(age, 1),
        'stages_seen': stages_seen,
        'stage_ts': stage_ts,
        'unknown_stages': [s for s in stages_seen if s not in STAGE_ORDER],
        'current_stage': current,
        'fail_stage': fail_stage,
        'state': state,
        'finished': finished,
        'verdict': verdict,
        'dry_run': dry_run,
        'logbook': path,
    }


def active_video_run(now=None, include_done=False, log_fn=None):
    """The most recent live standalone video run, or None.

    Dry runs are never surfaced — they complete in under a second and would
    flash a fully-green board that no GPU work backs.
    """
    log = log_fn or _log_noop
    now = now or time.time()
    best = None
    try:
        names = os.listdir(LOGBOOK_DIR)
    except (OSError, IOError):
        return None
    for nm in names:
        if not nm.endswith('.jsonl') or nm == 'index.jsonl':
            continue
        path = os.path.join(LOGBOOK_DIR, nm)
        try:
            r = read_run(path, now=now)
        except Exception as e:
            log(f'[kanban-video] unreadable {nm}: {e}')
            continue
        if not r or r.get('dry_run'):
            continue
        if now - (r.get('started') or 0) > MAX_RUN_AGE_S:
            continue
        if r['state'] in ('running', 'error') or (include_done and r['state'] == 'done'):
            if best is None or (r.get('started') or 0) > (best.get('started') or 0):
                best = r
    return best


def card_status(run):
    """-> {card title: 'done'|'running'|'error'|'queued'} for every board card."""
    out = {c: 'queued' for c in CARD_TITLES}
    if not run:
        return out
    cur = run.get('current_stage')
    cur_i = STAGE_ORDER.get(cur, -1)
    state = run.get('state')
    fail = run.get('fail_stage')
    for stage, card, _col in STAGE_CARDS:
        i = STAGE_ORDER[stage]
        if state == 'done':
            # A completed run marks everything it actually reached as done.
            out[card] = 'done' if stage in (run.get('stages_seen') or []) else 'queued'
        elif i < cur_i:
            out[card] = 'done'
        elif i == cur_i:
            out[card] = 'error' if (state == 'error' or stage == fail) else 'running'
        else:
            out[card] = 'queued'
    return out


def _iso(epoch):
    """Epoch -> local ISO-8601 with offset, the format every other board ships."""
    try:
        return datetime.fromtimestamp(float(epoch)).astimezone().isoformat()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def card_times(run, now=None):
    """-> {card title: {started_at, elapsed_s, since_s, running}} for the dialog.

    This run is driven by a shell script and keeps no ``stage_timeline``, so the
    per-card clock comes from the logbook's own ``stage`` events: a stage starts
    when its event is written and ends when the next stage's is.  Without this
    the card dialog fell back to the browser's zero placeholders and reported
    "0s ago / 0s" for every card (2026-08-26).
    """
    out = {}
    if not run:
        return out
    stage_ts = run.get('stage_ts') or {}
    if not stage_ts:
        return out
    as_of = float(now) if now is not None else time.time()
    running = run.get('state') == 'running'
    # Stage boundaries in the order the run actually reached them.
    seen = [s for s in (run.get('stages_seen') or []) if s in stage_ts]
    last_ts = float(run.get('last_event_ts') or as_of)
    for stage, card, _col in STAGE_CARDS:
        if stage not in stage_ts:
            continue
        start = stage_ts[stage]
        idx = seen.index(stage)
        nxt = seen[idx + 1] if idx + 1 < len(seen) else None
        if nxt is not None:
            end, is_open = stage_ts[nxt], False
        elif running:
            end, is_open = as_of, True
        else:
            # Final stage of a finished/dead run: freeze at the last thing the
            # run recorded, never at now.
            end, is_open = last_ts, False
        out[card] = {
            'started_at': _iso(start),
            'ended_at': None if is_open else _iso(end),
            'elapsed_s': round(max(0.0, end - start), 1),
            'since_s': round(max(0.0, as_of - start), 1),
            'running': is_open,
        }
    return out


def kanban_payload(now=None, log_fn=None):
    """Payload to merge into /api/kanban/status, or None when nothing is live.

    Shaped exactly like the existing endpoint's contract so kanban_main.js needs
    no special case: template + pipeline{status,...} + cards{title: state}.
    """
    run = active_video_run(now=now, log_fn=log_fn)
    if not run:
        return None
    sid, stitle = _series_for(run.get('run_dir'))
    cards = card_status(run)
    running = run['state'] == 'running'
    # Live Tail ⏱ clock. This branch used to ship no ``started`` at all, so the
    # panel read "No active pipeline" for every standalone VACE render. The run
    # is driven by a shell script and has no stage_timeline, so runtime is the
    # span from the first logbook entry to the last one (frozen there once the
    # driver is gone — never counted against now).
    _rt_start = float(run.get('started') or 0.0)
    _rt_now = float(now) if now is not None else time.time()
    _rt_end = _rt_now if running else float(run.get('last_event_ts') or _rt_start)
    _rt_secs = round(max(0.0, _rt_end - _rt_start), 1) if _rt_start > 0 else None
    return {
        'template': 'second_ledger',
        'model_family': 'wan',
        'pipeline': {
            'status': 'running' if running else run['state'],
            'department': 'video',
            'job_id': run['run_key'],
            'user_name': stitle,
            'topic': f'{stitle} — {run.get("run_key")}',
            'series_id': sid,
            'model_family': 'wan',
            'started': run.get('started_iso') or None,
            'runtime_seconds': _rt_secs,
            'runtime_running': running,
            'runtime_wall_seconds': _rt_secs,
        },
        'cards': cards,
        'card_times': card_times(run, now=_rt_now),
        'video_run': {
            'run_key': run['run_key'],
            'version': run['version'],
            'run_dir': run['run_dir'],
            'current_stage': run['current_stage'],
            'state': run['state'],
            'started_iso': run['started_iso'],
            'driver_alive': run['driver_alive'],
            'last_event_age_s': run['last_event_age_s'],
            'series_id': sid,
            'series_title': stitle,
        },
    }


if __name__ == '__main__':  # the CLI lives in kanban_video_status_cli
    from zyg_dashboard.kanban_video_status_cli import main as _cli_main

    raise SystemExit(_cli_main())
