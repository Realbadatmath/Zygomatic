# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common.py — the manifest, discovery, job plumbing and the shared CLI (lines 1095-1483 of the pre-split file, verbatim)."""

from __future__ import annotations

import logging as _zyg_logging
from .constants import (
    argparse,
    glob,
    importlib,
    json,
    os,
    sys,
    threading,
    time,
    traceback,
    uuid,
    _paths,
    _runtime,
    _ams_iso,
    _workflow_jobs,
    CREWS,
    OUT_BASE,
)
from ..devreload import maybe_reload

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.kids_series_common')


# ── the manifest ─────────────────────────────────────────────────────────────

_PAID_SDKS = ('anthropic', 'openai', 'google.generativeai', 'azure.cognitiveservices.speech', 'litellm')


def write_manifest(out_dir, manifest):
    """Stamp the cost record onto a manifest and write it.

    The four cost fields are not decoration: scripts/kids_series_check.py reads
    them back and fails the task if any of them says a paid call happened.
    ``paid_sdk_imported`` is measured from sys.modules at write time, so it
    catches a paid SDK that arrived through somebody else's import as well as a
    deliberate one.
    """
    m = dict(manifest or {})
    m['api_cost_usd'] = 0.0
    m['paid_api_calls'] = 0
    m['paid_sdk_imported'] = any(mod in sys.modules for mod in _PAID_SDKS)
    m['local_only'] = True
    m['written'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, 'manifest.json')
    with open(path, 'w') as fh:
        json.dump(m, fh, indent=1, default=str)
    return path


# ── discovery ────────────────────────────────────────────────────────────────

_DISCOVER_ERRORS = []


def discover():
    """{slug: module} for every pipeline_kids_*.py that honours the contract.

    Re-globbed on EVERY call, deliberately: a new series file must show up on
    the board without restarting the GUI.  A module that will not import is
    recorded in discover_errors() and skipped — one broken runner must not take
    the other nine off the board.
    """
    global _DISCOVER_ERRORS
    errs, out = [], {}
    for path in sorted(glob.glob(os.path.join(CREWS, 'pipeline_kids_*.py'))):
        name = os.path.splitext(os.path.basename(path))[0]
        try:
            mod = importlib.import_module(name)
            mod = maybe_reload(mod) if name in sys.modules else mod
        except Exception as e:  # noqa: BLE001
            errs.append({'file': os.path.basename(path), 'error': f'{type(e).__name__}: {e}'[:300]})
            continue
        series = getattr(mod, 'SERIES', None)
        if not (
            isinstance(series, dict)
            and series.get('slug')
            and getattr(mod, 'STAGES', None)
            and callable(getattr(mod, 'run_episode', None))
        ):
            errs.append({'file': os.path.basename(path), 'error': 'missing SERIES / STAGES / run_episode'})
            continue
        out[str(series['slug'])] = mod
    _DISCOVER_ERRORS = errs
    return out


def discover_errors():
    """What discover() could not load, last time it ran."""
    return list(_DISCOVER_ERRORS)


# ── job plumbing ─────────────────────────────────────────────────────────────
#
# Generalised from pipeline_kidsmusic.py: the same registry, the same in-flight
# flag contract, the same debug_events shape.  Every one of those details is
# load-bearing and the comments say why.

# $ZYG_INFLIGHT_DIR overrides it; the default lives under the package scratch root
# (paths.ZYG_TMP_DIR, 0o700) rather than a world-writable fixed /var/tmp path.
INFLIGHT_DIR = os.environ.get('ZYG_INFLIGHT_DIR', '').strip() or str(_paths.ZYG_TMP_DIR / 'inflight')


def _jobs():
    """The shared registry. runtime owns it, so a standalone run gets it too."""
    return _workflow_jobs


def _now_iso():
    return _ams_iso()


def _inflight_path(dept, pid):
    return os.path.join(INFLIGHT_DIR, f'{dept}-{pid}.flag')


def _inflight_begin(dept, pid):
    try:
        os.makedirs(INFLIGHT_DIR, exist_ok=True)
        with open(_inflight_path(dept, pid), 'w') as fh:
            fh.write(f'{{"pid": "{pid}", "started": {time.time():.0f}, "dept": "{dept}"}}\n')
    except OSError as _exc:
        _zyg_log.warning('inflight flag write failed, job %s will look stale to the watchdog: %s', pid, _exc)


def _inflight_beat(dept, pid):
    try:
        p = _inflight_path(dept, pid)
        if os.path.isfile(p):
            os.utime(p, None)
    except OSError as _exc:
        _zyg_log.debug('inflight heartbeat refresh skipped: %s', _exc)


def _inflight_end(dept, pid):
    try:
        os.remove(_inflight_path(dept, pid))
    except OSError as _exc:
        _zyg_log.debug('inflight flag removal skipped: %s', _exc)


def _inflight_ticker(dept, pid, stop_flag):
    """Refresh the flag on a timer, not only when something is logged.

    A render stage is minutes of silence; at 300 s the flag goes stale and the
    health probe is free to restart the GUI underneath the run — the exact
    failure the flag exists to prevent.
    """
    while not stop_flag.wait(60.0):
        if not os.path.isfile(_inflight_path(dept, pid)):
            return
        _inflight_beat(dept, pid)


_WARN_WORDS = (
    'fail',
    'unavailable',
    'error',
    'could not',
    'missing',
    'no audio',
    'silent',
    'skipped',
    'not verified',
    'halt',
    'refused',
    'truncated',
    'no frames',
    'fell back',
    'not built',
    'produced nothing',
    'no plan',
)


def _log_for(dept, pid):
    """Append one Live-Tail event.

    Entries MUST be dicts {level, ts, stage, msg}: bp_pipeline_api.kanban_status
    reads ev.get('level') off every event of the active job, so appending a bare
    string 500s /api/kanban/status for the WHOLE dashboard.
    """

    def _l(m):
        j = _jobs().get(pid)
        if j is None:
            return
        _inflight_beat(dept, pid)
        txt = str(m)[:200]
        low = txt.lower()
        lvl = 'WARN' if any(k in low for k in _WARN_WORDS) else 'INFO'
        j.setdefault('debug_events', []).append(
            {
                'level': lvl,
                'ts': time.strftime('%H:%M:%S'),
                'stage': j.get('current_stage') or '',
                'msg': txt,
            }
        )

    return _l


def _set_stage(dept, pid, stage):
    """Advance the card and close the previous timeline row."""
    j = _jobs().get(pid)
    if j is None:
        return
    _inflight_beat(dept, pid)
    j['current_stage'] = stage
    now = time.time()
    tl = j.setdefault('stage_timeline', [])
    for entry in tl:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'completed'
            entry['ended_at'] = now
    tl.append({'name': stage, 'status': 'running', 'ts': now, 'started_at': now, 'ended_at': None})


def _mk_job(dept, directive, first_stage, options):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': dept,
        'stop_event': threading.Event(),
        'stage': dept,
        'current_stage': first_stage,
        'started': _now_iso(),
        'directive': (directive or '').strip(),
        'model_family': 'flux',  # unused here; the poll expects one
        'pipeline_options': options or {},
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'debug_events': [],
    }
    return pid


def _finish(pid, ok, result=None, error=None):
    """Close a job out.  THE STOP EVENT IS READ FIRST.

    A halted run is 'stopped', not 'completed', and whatever error the stop path
    recorded is preserved rather than overwritten with a green card.  `ok` is
    always derived from manifest['ok'] by the caller — never from 'run()
    returned'.
    """
    j = _jobs().get(pid)
    if not j:
        return
    ev = j.get('stop_event')
    stopped = bool(ev is not None and ev.is_set())
    if stopped:
        j['status'] = 'stopped'
        j['current_stage'] = 'Stopped'
        j['error'] = j.get('error') or error or 'halted by operator'
    else:
        j['status'] = 'completed' if ok else 'failed'
        j['current_stage'] = 'Deliver' if ok else 'Error'
        j['error'] = error
    j['result'] = result
    j['ended'] = _now_iso()
    now = time.time()
    for entry in j.get('stage_timeline') or []:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'stopped' if stopped else 'completed' if ok else 'failed'
            entry['ended_at'] = now


def start_series(slug, episode=None, pipeline_options=None, test_mode=False):
    """Start one episode of one series on a daemon thread.

    Returns immediately with the job dict the board polls.  The verdict comes
    from the manifest the runner writes, never from 'the thread returned'.
    """
    series = discover().get(str(slug))
    if series is None:
        return {
            'error': f'unknown series: {slug}',
            'known': sorted(discover().keys()),
            'discover_errors': discover_errors(),
        }
    meta = series.SERIES
    dept = f'kids_{slug}'
    stages = list(series.STAGES)
    ep = int(episode or 1)
    opts = dict(pipeline_options or {})

    # CLEAR THE LATCHED HALT.  After an emergency stop the latch stays set, and
    # a run that never clears it silently skips every GPU stage while reporting
    # a reason indistinguishable from a deliberate choice.
    try:
        _runtime.clear_pipeline_halt()
    except Exception as _exc:  # noqa: BLE001 — standalone runs
        _zyg_log.debug('pipeline halt clear skipped (standalone run): %s', _exc)

    pid = _mk_job(dept, f'{meta.get("title", slug)} — episode {ep}', stages[0] if stages else 'Start', opts)
    out_dir = os.path.join(OUT_BASE, dept, pid)
    os.makedirs(out_dir, exist_ok=True)
    stop = _jobs()[pid]['stop_event']
    _inflight_begin(dept, pid)
    beat_stop = threading.Event()
    threading.Thread(
        target=_inflight_ticker, args=(dept, pid, beat_stop), name=f'{dept}-beat-{pid}', daemon=True
    ).start()

    def _run_job():
        try:
            log = _log_for(dept, pid)
            manifest = (
                series.run_episode(
                    out_dir,
                    ep,
                    test_mode=bool(test_mode),
                    log_fn=log,
                    stage_fn=lambda s: _set_stage(dept, pid, s),
                    should_abort=stop.is_set,
                )
                or {}
            )
            j = _jobs().get(pid)
            if j is not None:
                j['kids_series'] = {
                    'slug': slug,
                    'title': manifest.get('title') or meta.get('title'),
                    'episode': manifest.get('episode', ep),
                    'test_mode': bool(manifest.get('test_mode', test_mode)),
                    'ok': bool(manifest.get('ok')),
                    'reason': manifest.get('reason') or '',
                    'duration_s': manifest.get('duration_s'),
                    'stages_completed': manifest.get('stages_completed'),
                    'voice': manifest.get('voice'),
                    'out_dir': out_dir,
                }
            _finish(
                pid,
                bool(manifest.get('ok')),
                result=manifest,
                error=(None if manifest.get('ok') else (manifest.get('reason') or 'the episode produced no video')),
            )
        except Exception as e:  # noqa: BLE001 — a failed episode
            _finish(
                pid,
                False,  # must not take the GUI with it
                error=f'{e}\n{traceback.format_exc()[:900]}',
            )
        finally:
            # ALWAYS released, including on the exception path: a flag left by a
            # crashed run defers health-probe restarts until it goes stale.
            beat_stop.set()
            _inflight_end(dept, pid)

    threading.Thread(target=_run_job, name=f'{dept}-{pid}', daemon=True).start()
    return {
        'job_id': pid,
        'status': 'running',
        'department': dept,
        'slug': slug,
        'episode': ep,
        'test_mode': bool(test_mode),
        'out_dir': out_dir,
    }


# ── the shared CLI ───────────────────────────────────────────────────────────


def run_cli(module):
    """`python pipeline_kids_<slug>.py --test --episode N --out DIR`.

    Synchronous, one JSON line on stdout, exit 0 only if the MANIFEST says the
    episode is ok — which is what the checker and the tree's verify step both
    read.
    """
    meta = getattr(module, 'SERIES', {}) or {}
    slug = meta.get('slug') or 'series'
    ap = argparse.ArgumentParser(description=meta.get('title') or slug)
    ap.add_argument('--test', action='store_true', help='one unit only (>= 5 s), everything else identical')
    ap.add_argument('--episode', type=int, default=1)
    ap.add_argument('--out', default=None)
    args = ap.parse_args()

    out_dir = args.out or os.path.join(OUT_BASE, f'kids_{slug}', 'cli_' + time.strftime('%Y%m%d_%H%M%S'))
    os.makedirs(out_dir, exist_ok=True)

    manifest = (
        module.run_episode(
            out_dir,
            int(args.episode),
            test_mode=bool(args.test),
            log_fn=print,
            stage_fn=print,
            should_abort=lambda: False,
        )
        or {}
    )
    ok = bool(manifest.get('ok'))
    print(
        json.dumps(
            {
                'out': out_dir,
                'ok': ok,
                'reason': manifest.get('reason') or '',
                'duration_s': manifest.get('duration_s'),
                'engine': (manifest.get('voice') or {}).get('engine') or '',
            }
        )
    )
    return 0 if ok else 1
