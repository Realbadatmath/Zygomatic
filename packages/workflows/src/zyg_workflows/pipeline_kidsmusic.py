# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""pipeline_kidsmusic.py — dispatch runner for the Children's Music workflow.

Additive, in the shape pipeline_envfx_runner already established: register a job
in the shared `_workflow_jobs` registry (so the busy-check, the Kanban poll and
the Live Tail all see it), run the work on a daemon thread, update status.  A new
pipeline_type only — it cannot affect an existing pipeline.

Output tree: output/kidsmusic/<job_id>/ — its own folder, per the house rule that
every workflow owns its output directory.
"""

from __future__ import annotations

import os
import threading
import time
import traceback
import uuid
import logging as _zyg_logging

from zyg_workflows import runtime

_zyg_log = _zyg_logging.getLogger(__name__)


_HERE = os.path.dirname(os.path.abspath(__file__))
_OUT_ROOT = os.path.join(_HERE, 'output', 'kidsmusic')

# One runner, two output trees — the house rule is that every workflow owns its
# own folder, and a cinematic cue is a different workflow from a children's
# song (no lyrics, no pictures, its own board). What it is NOT is a different
# DEPARTMENT: the busy-check, the Live Tail, `_workflow_pipeline_worker_alive`'s
# `kidsmusic-{pid}` needle and the inflight flag all key on 'kidsmusic', and
# renaming it here would silently unhook every one of them.
_OUT_ROOTS = {'children': _OUT_ROOT, 'cinematic': os.path.join(_HERE, 'output', 'cinematic')}

# Card titles the Kanban board matches against. Keep in step with the stage
# strings passed to `_set_stage` below and with the `kidsmusic` board in
# kanban_assets/kanban_main.js — a card whose title no card-stage ever equals
# sits at 'queued' forever, which is how the Second Ledger board once looked
# permanently stalled.
STAGES = [
    'Song Brief',
    'Lyrics',
    'Compose & Score',
    'Score Render',
    'Measure Score Render',
    'Produced Track (ACE-Step)',
    'Measure Produced Track',
    'Master & Deliver',
    # The picture leg (2026-08-29). It runs AFTER the audio is mastered, because
    # it illustrates whatever the run actually delivered — and because the two
    # legs share one GPU and one ComfyUI submit lock.
    'Storyboard',
    'Illustrate',
    'Measure Frames',
    # 2026-10-02: every picture becomes an LTX-2.5 motion clip before assembly —
    # the channel ships no stills. Column 'Pictures' on the board.
    'Animate',
    'Assemble Video',
]


# ── In-flight interlock ──────────────────────────────────────────────────────
#
# The health probe restarts crewai-gui when :5000 stops answering, and a song
# render is exactly the kind of long CPU+GPU stage that can make it stop
# answering for a while. 30 such restarts since 8 July, one at 19:32 on
# 2026-08-29 — and a killed run leaves a manifest-less folder the UI then
# refuses to delete.
#
# The contract, mirroring the maintenance flag the probe already honours:
#   * a run writes a flag and REFRESHES it as it works (a heartbeat, not a latch);
#   * the probe defers restarts while a flag is fresh;
#   * a flag that stops being refreshed goes stale and stops protecting anything,
#     so a crashed or hung run cannot silence monitoring indefinitely.
#
# It is a heartbeat rather than a latch for the same reason the maintenance flag
# has a 15-minute ceiling: an interlock that can be left on by a crash is a way
# to turn monitoring off by accident.
# The path is part of the contract: scripts/zygomatic-health-probe.sh and kids_series_common.py read
# this very directory, so it cannot move without them.
INFLIGHT_DIR = '/var/tmp/zygomatic-inflight'  # nosec B108  # noqa: S108  interlock dir the probe reads, not a temp file
INFLIGHT_STALE_S = 300  # a flag older than this protects nothing
INFLIGHT_MAX_S = 2700  # 45 min: a run this long IS the problem


def _inflight_path(pid):
    return os.path.join(INFLIGHT_DIR, f'kidsmusic-{pid}.flag')


def _inflight_begin(pid):
    try:
        os.makedirs(INFLIGHT_DIR, exist_ok=True)
        with open(_inflight_path(pid), 'w') as fh:
            fh.write(f'{{"pid": "{pid}", "started": {time.time():.0f}, "dept": "kidsmusic"}}\n')
    except OSError as _exc:
        _zyg_log.warning('inflight flag write failed, continuing without the health-probe interlock: %s', _exc)


def _inflight_beat(pid):
    """Touch the flag. Cheap enough to call from every log line."""
    try:
        p = _inflight_path(pid)
        if os.path.isfile(p):
            os.utime(p, None)
    except OSError as _exc:
        _zyg_log.debug('inflight heartbeat touch skipped: %s', _exc)


def _inflight_end(pid):
    try:
        os.remove(_inflight_path(pid))
    except OSError as _exc:
        _zyg_log.debug('inflight flag removal skipped: %s', _exc)


def _inflight_ticker(pid, stop_flag):
    """Refresh the flag on a timer, not only when something is logged.

    The heartbeat used to depend entirely on `_log_for` and `_set_stage`, which
    was fine while every stage was chatty. The picture leg is not: assembling
    ~47 clips and running one 47-input ffmpeg xfade chain is several minutes
    inside a single stage with nothing to say, and at 300 s the flag goes stale
    and the health probe is free to restart the GUI underneath the run — the
    exact failure the flag exists to prevent, with a longer stage to hit it.

    A ticker does NOT weaken the two bounds: the probe reads the flag's own
    "started" field for the 45-minute total cap, and this thread dies with the
    run (daemon + an explicit stop), so a crash still lets the flag go stale.
    """
    while not stop_flag.wait(60.0):
        if not os.path.isfile(_inflight_path(pid)):
            return
        _inflight_beat(pid)


def _now_iso():
    return runtime.ams_iso()


def _jobs():
    return runtime.workflow_jobs


def _mk_job(directive, options, song=None, family='children'):
    pid = uuid.uuid4().hex[:12]
    _jobs()[pid] = {
        'job_id': pid,
        'pipeline_id': pid,
        'status': 'running',
        'department': 'kidsmusic',
        # Which of the two boards this card belongs on. Recorded at creation for
        # the same reason `song` is: a card that only learns its family when the
        # run finishes is a card on the wrong board for the whole render.
        'family': family,
        'stop_event': threading.Event(),
        'stage': 'kidsmusic_brief',
        'current_stage': 'Song Brief',
        'started': _now_iso(),
        'directive': (directive or '').strip(),
        'model_family': 'sdxl',  # unused here; the poll expects a value
        'pipeline_options': options or {},
        # The RAW brief, style included, recorded at creation rather than at the
        # end: bp_pipeline_api.kanban_status reads job['song']['style'] to pick
        # which board a running card belongs on, and a card that only learns its
        # style when the run finishes is a card on the wrong board for the whole
        # render.
        'song': dict(song or {}),
        'stages': {},
        'stage_timeline': [],
        'result': None,
        'error': None,
        'debug_events': [],
    }
    return pid


def _finish(pid, ok, result=None, error=None):
    """Close a job out.

    THE STOP EVENT IS READ FIRST. The stop path writes status='stopped' plus an
    error, and this function used to overwrite both — so an emergency stop ended
    as a green card with no error on it. A halted run is 'stopped', not
    'completed', and whatever error the stop path recorded is preserved.

    `ok` is the CALLER's verdict and the caller derives it from
    manifest['ok'] — i.e. from whether audio actually exists — rather than from
    'run() did not raise'. A run where both legs failed used to return normally
    and paint the card green.
    """
    j = _jobs().get(pid)
    if not j:
        return
    ev = j.get('stop_event')
    stopped = bool(ev is not None and ev.is_set())
    if stopped:
        j['status'] = 'stopped'
        j['current_stage'] = 'Stopped'
        # Keep the reason the stop path wrote; only fill in if it left none.
        j['error'] = j.get('error') or error or 'halted by operator'
    else:
        j['status'] = 'completed' if ok else 'failed'
        j['current_stage'] = 'Deliver' if ok else 'Error'
        j['error'] = error
    j['result'] = result
    j['ended'] = _now_iso()
    # Close the last open timeline row. Leaving it 'running' left the final card
    # spinning on a finished job, and gave the card dialog no end to time the
    # stage against.
    now = time.time()
    for entry in j.get('stage_timeline') or []:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'stopped' if stopped else 'completed' if ok else 'failed'
            entry['ended_at'] = now


def _log_for(pid):
    """Append one Live-Tail event.

    Entries MUST be dicts {level, ts, stage, msg}: `bp_pipeline_api.kanban_status`
    reads `ev.get('level')` off every event of the active job, so appending a
    bare string 500s /api/kanban/status for the WHOLE dashboard, not just this
    board. (pipeline_envfx_runner appends strings here and carries the same
    latent fault — reported, not touched.)
    """

    def _l(m):
        j = _jobs().get(pid)
        if j is None:
            return
        _inflight_beat(pid)
        txt = str(m)[:200]
        low = txt.lower()
        # 'no shippable leg' and 'produced no audio' used to be classified INFO,
        # so the ONE line explaining an empty run sat in the info stream while
        # the panel showed only the last 14 events — and the card was green.
        lvl = (
            'WARN'
            if any(
                k in low
                for k in (
                    'fail',
                    'unavailable',
                    'error',
                    'could not',
                    'missing',
                    'no audio',
                    'no shippable',
                    'silent',
                    'skipped',
                    'not verified',
                    'halt',
                    'buried',
                    'diagnostic only',
                    'truncated',
                    'refused',
                    # The picture leg's own warnings. Classified by prose, like every
                    # other line here — so a new stage that says something worth seeing
                    # has to be added, or its one explanatory line sits in the info
                    # stream while the panel shows fourteen events and a green card.
                    'below the',
                    'no visible change',
                    'not built',
                    'fell back',
                    'contract is broken',
                    'not trusted',
                    'reuse',
                    'drawn, not generated',
                    'no frames',
                )
            )
            else 'INFO'
        )
        j.setdefault('debug_events', []).append(
            {
                'level': lvl,
                'ts': time.strftime('%H:%M:%S'),
                'stage': j.get('current_stage') or 'Song Brief',
                'msg': txt,
            }
        )

    return _l


def _set_stage(pid, stage):
    """Advance the card and close the previous timeline row.

    Rows are closed rather than appended-only so the Kanban card dialog has an
    end to time each stage against — the same fix pipeline_envfx_runner carries.
    """
    j = _jobs().get(pid)
    if j is None:
        return
    _inflight_beat(pid)
    j['current_stage'] = stage
    now = time.time()
    tl = j.setdefault('stage_timeline', [])
    for entry in tl:
        if entry.get('status') == 'running' and not entry.get('ended_at'):
            entry['status'] = 'completed'
            entry['ended_at'] = now
    tl.append({'name': stage, 'status': 'running', 'ts': now, 'started_at': now, 'ended_at': None})


def start_kidsmusic(directive='', pipeline_options=None, song=None, **_kw):
    """Start one children's-music run.

    `song` carries the structured brief from the composer panel (age band, mood,
    meter, form, key, tempo, duration, sung/instrumental).  `directive` is the
    theme in plain language and is the only field that is really required —
    everything else has a musically coherent default.
    """
    song = dict(song or {})
    opts = dict(pipeline_options or {})
    theme = (song.get('theme') or directive or '').strip()
    if not theme:
        return {'error': 'a theme is required'}
    song['theme'] = theme
    # Unknown families are not an error here — km_start rejects them at the door
    # — they simply run as the children's workflow, which is what every brief
    # that predates the cinematic family is.
    family = song.get('family') if song.get('family') in _OUT_ROOTS else 'children'
    song['family'] = family

    # CLEAR THE LATCHED HALT. Every other GPU-submitting starter calls this and
    # start_kidsmusic was the only one that did not — so after an emergency stop
    # the ACE leg was silently skipped on every subsequent song, and the run
    # reported a reason string identical to a deliberate instrumental. A halt
    # nobody cleared is not a decision about this song.
    try:
        runtime.clear_pipeline_halt()
    except Exception as _exc:  # noqa: BLE001 — a halt nobody can clear is not fatal
        _zyg_log.warning('clearing the latched pipeline halt failed, the ACE leg may be skipped: %s', _exc)

    pid = _mk_job(theme, opts, song=song, family=family)
    out_dir = os.path.join(_OUT_ROOTS[family], pid)
    os.makedirs(out_dir, exist_ok=True)
    stop = _jobs()[pid]['stop_event']
    _inflight_begin(pid)
    _beat_stop = threading.Event()
    threading.Thread(target=_inflight_ticker, args=(pid, _beat_stop), name=f'kidsmusic-beat-{pid}', daemon=True).start()

    def _run():
        try:
            from zyg_workflows import kids_music_service as KM

            log = _log_for(pid)
            manifest = KM.run(
                song,
                out_dir,
                log_fn=log,
                stage_fn=lambda s: _set_stage(pid, s),
                candidates=song.get('candidates'),
                want_ace=bool(song.get('want_ace', True)),
                should_abort=stop.is_set,
                job_id=pid,
            )
            j = _jobs().get(pid)
            if j is not None:
                # Surfaced on the card so the board shows the verdict without a
                # round trip to the manifest.
                j['kidsmusic'] = {
                    'title': manifest.get('title'),
                    'score': manifest.get('score', {}).get('total'),
                    'score_ok': manifest.get('score', {}).get('ok'),
                    'picked': manifest.get('delivery', {}).get('picked'),
                    'produced_status': manifest.get('delivery', {}).get('produced_status'),
                    'singer': (manifest.get('gates', {}).get('singer') or {}).get('status'),
                    # From the MANIFEST, not from the brief: an unknown style is
                    # dropped during normalisation, so the brief can say one
                    # thing and the song be another.
                    'style': manifest.get('style'),
                    'shelf': manifest.get('shelf'),
                    'family': manifest.get('family'),
                    'ok': bool(manifest.get('ok')),
                    'out_dir': out_dir,
                }
            # The verdict comes from the MANIFEST, not from "run() returned".
            _finish(
                pid,
                bool(manifest.get('ok')),
                result=manifest,
                error=(
                    None
                    if manifest.get('ok')
                    else (manifest.get('delivery', {}).get('reason') or 'run produced no audio')
                ),
            )
        except Exception as e:  # noqa: BLE001 — a failed song must
            _finish(
                pid,
                False,  # not take the GUI process with it
                error=f'{e}\n{traceback.format_exc()[:900]}',
            )
        finally:
            # ALWAYS released, including on the exception path — a flag left
            # behind by a crashed run would defer restarts until it went stale.
            _beat_stop.set()
            _inflight_end(pid)

    threading.Thread(target=_run, name=f'kidsmusic-{pid}', daemon=True).start()
    return {'job_id': pid, 'status': 'running', 'department': 'kidsmusic', 'family': family, 'out_dir': out_dir}
