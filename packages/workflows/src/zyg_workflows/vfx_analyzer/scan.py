# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""The job board, the frame extractor and the scan itself — verbatim sections of the
former vfx_analyzer.py."""

import functools
import os
import subprocess
import threading
import time

from zyg_workflows.vfx_analyzer import _zyg_log
from zyg_workflows.vfx_analyzer.constants import (
    DEFAULT_WINDOW_S,
    FFMPEG,
    MAX_WINDOW_S,
    RUNS_DIR,
    _JOB_KEEP,
    _JOBS,
    _JOBS_LOCK,
    _ensure_dirs,
    taxonomy,
)
from zyg_workflows.vfx_analyzer.library import get_media, media_path


# ── jobs ─────────────────────────────────────────────────────────────────────


def _job_set(jid, **kw):
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j.update(kw)


def _job_log(jid, msg):
    line = f'[{time.strftime("%H:%M:%S")}] {msg}'
    with _JOBS_LOCK:
        j = _JOBS.get(jid)
        if j:
            j['log'].append(line)
            del j['log'][:-400]
            path = j.get('log_path')
    if path:
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(line + '\n')
        except OSError as _exc:
            _zyg_log.warning('job log line not written, it survives only on stdout: %s', _exc)
    _zyg_log.info(f'[VFX] {msg}')


def _prune_jobs():
    """Keep the last _JOB_KEEP jobs, but never evict a live one — the GUI polls
    by id and a job dropped mid-run would read as 'vanished', not 'finished'."""
    live = {k for k, j in _JOBS.items() if j.get('state') in ('queued', 'running')}
    done = [k for k in sorted(_JOBS, key=lambda k: _JOBS[k].get('started_ts', 0)) if k not in live]
    for old in done[: max(0, len(done) - _JOB_KEEP)]:
        _JOBS.pop(old, None)


def job(jid):
    with _JOBS_LOCK:
        j = _JOBS.get(str(jid))
        return dict(j) if j else None


def _cancel_requested(jid):
    """True when the board has been asked to cancel job `jid` (a missing job is not a cancel)."""
    j = job(jid)
    return bool(j and j.get('cancel'))


def jobs():
    with _JOBS_LOCK:
        return [dict(j) for j in sorted(_JOBS.values(), key=lambda j: -j.get('started_ts', 0))]


def cancel(jid):
    with _JOBS_LOCK:
        j = _JOBS.get(str(jid))
        if not j or j.get('state') not in ('queued', 'running'):
            return False
        j['cancel'] = True
        return True


def start_run(media_id, opts=None):
    """Queue a scan. opts: {start_s, duration_s, do_landmarks, do_vlm,
    do_curiosity, max_frames, thresholds:{}}"""
    _ensure_dirs()
    meta = get_media(media_id)
    if not meta:
        return {'error': 'unknown media'}
    src = media_path(media_id)
    if not src:
        return {'error': 'source file missing'}
    o = dict(opts or {})
    try:
        start_s = max(0.0, float(o.get('start_s', 0)))
    except (TypeError, ValueError):
        start_s = 0.0
    try:
        dur_s = float(o.get('duration_s', DEFAULT_WINDOW_S))
    except (TypeError, ValueError):
        dur_s = DEFAULT_WINDOW_S
    dur_s = max(0.1, min(dur_s, MAX_WINDOW_S))
    rid = f'{media_id}_{time.strftime("%Y%m%d_%H%M%S")}'
    rdir = os.path.join(RUNS_DIR, rid)
    os.makedirs(os.path.join(rdir, 'frames'), exist_ok=True)
    os.makedirs(os.path.join(rdir, 'crops'), exist_ok=True)
    jid = rid
    with _JOBS_LOCK:
        _JOBS[jid] = {
            'id': jid,
            'run_id': rid,
            'media_id': media_id,
            'media_name': meta.get('name', ''),
            'state': 'queued',
            'stage': 'queued',
            'pct': 0.0,
            'frame': 0,
            'frames_total': 0,
            'log': [],
            'log_path': os.path.join(rdir, 'run.log'),
            'started': time.strftime('%Y-%m-%d %H:%M:%S'),
            'started_ts': time.time(),
            'cancel': False,
            'error': '',
        }
        _prune_jobs()
    cfg = {
        'start_s': start_s,
        'duration_s': dur_s,
        'do_landmarks': bool(o.get('do_landmarks', True)),
        'do_vlm': bool(o.get('do_vlm', False)),
        'do_curiosity': bool(o.get('do_curiosity', True)),
        'max_frames': int(o.get('max_frames', 0) or 0),
        'do_probes': bool(o.get('do_probes', True)),
        'thresholds': dict(o.get('thresholds') or {}),
    }
    threading.Thread(target=_worker, args=(jid, rid, media_id, src, meta, cfg), daemon=True).start()
    return {'ok': True, 'job': jid, 'run_id': rid}


# ── frame extraction ─────────────────────────────────────────────────────────


def _extract(src, out_dir, start_s, dur_s, log):
    """Every frame in the window, no drops, no duplicates.

    -fps_mode passthrough is the whole point: ffmpeg's default CFR conversion
    would silently DUPLICATE frames to hit a target rate, and a duplicate that
    ffmpeg invented is indistinguishable downstream from a cel the animator
    actually held. The cadence map would then read invented twos."""
    cmd = [
        FFMPEG,
        '-nostdin',
        '-v',
        'error',
        '-ss',
        f'{start_s:.3f}',
        '-i',
        src,
        '-t',
        f'{dur_s:.3f}',
        '-fps_mode',
        'passthrough',
        '-q:v',
        '2',
        os.path.join(out_dir, 'f%06d.jpg'),
    ]
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    except subprocess.SubprocessError as e:
        return [], f'ffmpeg failed: {type(e).__name__}: {e}'
    if r.returncode != 0:
        return [], f'ffmpeg rc={r.returncode}: {(r.stderr or "")[:400]}'
    got = sorted(f for f in os.listdir(out_dir) if f.endswith('.jpg'))
    log(
        f'extract: {len(got)} frames in {time.time() - t0:.1f}s '
        f'(window {start_s:.2f}s +{dur_s:.2f}s, fps_mode=passthrough)'
    )
    return got, ''


# ── the scan ─────────────────────────────────────────────────────────────────


def _worker(jid, rid, media_id, src, meta, cfg):
    """Run one scan end to end: extract, measure, detect, write. Never raises.

    The stages live in `scan_stages` and share one `ScanRun`; this function owns the order
    they run in, the two callables they need from the job board (`log` and `cancelled`),
    and the promise that a failed run writes a report and marks the job rather than
    killing the server thread.
    """
    from zyg_workflows.vfx_analyzer import scan_stages as ST

    rdir = os.path.join(RUNS_DIR, rid)
    log = lambda m: _job_log(jid, m)  # noqa: E731
    cancelled = functools.partial(_cancel_requested, jid)
    run = ST._new_run(jid, rid, media_id, src, meta, cfg, rdir, log, cancelled)
    try:
        ST.open_run(run)
        ST.extract_frames(run)
        ST.measure_frames(run)
        ST.temporal_structure(run)
        ST.track_landmarks(run)
        ST.embed_frames(run)
        ST.run_detectors(run)
        ST.write_outputs(run)
    except Exception as e:  # noqa: BLE001 — a run must never kill the server
        ST._record_failure(run, e)


def _thin_landmarks(fr):
    """The per-frame log keeps DERIVED landmark scalars, not the 468-point face
    mesh — a full mesh per frame is ~40x the size of everything else in the
    record and nothing reads it back."""
    if not isinstance(fr, dict):
        return {}
    out = {}
    for kind in ('pose', 'face', 'hand'):
        blk = fr.get(kind) or {}
        items = []
        for it in blk.get('items') or []:
            thin = {k: v for k, v in it.items() if k not in ('pts', 'blendshapes')}
            items.append(thin)
        out[kind] = {
            'state': blk.get('state', 'unmeasurable'),
            'n_strict': blk.get('n_strict', 0),
            'n_weak': blk.get('n_weak', 0),
            'items': items,
        }
        if blk.get('reason'):
            out[kind]['reason'] = blk['reason']
    return out


def _segment_shots(per_frame, pair_by_frame, uidx, fps):
    """Cut detection on the unique-cel sequence.

    A cut is a pair where the picture changed globally: histogram correlation
    collapses AND the camera fit cannot explain the motion. Using both keeps a
    whip pan (huge motion, histogram survives) from reading as a cut."""
    cuts = []
    flat = [float((f or {}).get('luma_std', 99) or 0) < 8.0 for f in per_frame]
    for b, pm in sorted(pair_by_frame.items()):
        hist = pm.get('hist_corr', 1.0)
        moved = pm.get('diff_frac_moved', 0.0)
        camok = pm.get('cam_fit_ok', 0.0)
        score = (1.0 - hist) * 0.6 + moved * 0.4
        a = pm.get('from_frame', b - 1)
        if (0 <= a < len(flat) and flat[a]) or (0 <= b < len(flat) and flat[b]):
            continue  # flash / fade edge, not a cut between two pictures
        if (hist < 0.55 and moved > 0.55) or (hist < 0.35):
            cuts.append(
                {
                    'frame': b,
                    'score': round(float(score), 4),
                    'hist_corr': round(float(hist), 4),
                    'frac_moved': round(float(moved), 4),
                    'cam_fit_ok': float(camok),
                }
            )
    n = len(per_frame)
    bounds = [0] + [c['frame'] for c in cuts] + [n]
    shots = []
    for i in range(len(bounds) - 1):
        s, e = bounds[i], bounds[i + 1] - 1
        if e < s:
            continue
        seg_u = [u for u in uidx if s <= u <= e]
        shots.append(
            {
                'index': len(shots),
                'start': s,
                'end': e,
                'frames': e - s + 1,
                'seconds': round((e - s + 1) / fps, 3),
                'unique_cels': len(seg_u),
            }
        )
    for c, sh in zip(cuts, shots[1:]):
        sh['cut_in'] = c
    return shots


def _build_ledger(results, log):
    """Every taxonomy entry, sorted into the four states. An entry with no
    registered detector still appears — as a NAMED blind spot."""
    tax = taxonomy()
    by_id = tax.get('by_id') or {}
    seen = {}
    for r in results:
        seen[r['id']] = r
    found, not_found, unmeasurable, not_detectable = [], [], [], []
    for tid, ent in sorted(by_id.items()):
        r = seen.get(tid)
        base = {
            'id': tid,
            'label': ent.get('label', tid),
            'group': ent.get('group', ''),
            'domain': tid.split('.', 1)[0],
            'applies_to': ent.get('applies_to', 'both'),
            'declared_tier': ent.get('detector_tier', ''),
        }
        if r is None:
            base['reason'] = f'no detector implemented; taxonomy declares tier {ent.get("detector_tier", "?")!r}'
            not_detectable.append(base)
            continue
        base.update(
            {
                'threshold': r.get('threshold'),
                'unit': r.get('unit', ''),
                'best': r.get('best'),
                'note': r.get('note', ''),
            }
        )
        if r.get('state') == 'unmeasurable':
            base['reason'] = r.get('reason', 'precondition failed')
            unmeasurable.append(base)
        elif r.get('events'):
            base['n_events'] = len(r['events'])
            base['frames'] = sorted({e.get('frame') for e in r['events'] if e.get('frame') is not None})[:200]
            found.append(base)
        else:
            not_found.append(base)
    # A detector keyed to an id the taxonomy does not contain is a wiring bug,
    # not a finding — surface it loudly rather than dropping the result.
    orphans = sorted(set(seen) - set(by_id))
    if orphans:
        log(
            f'WARNING: {len(orphans)} detector(s) keyed to ids absent from the '
            f'taxonomy — {", ".join(orphans[:10])}'
            f'{" …" if len(orphans) > 10 else ""}'
        )
        for oid in orphans:
            r = seen[oid]
            evs = r.get('events') or []
            rec = {
                'id': oid,
                'label': oid,
                'group': '',
                'domain': oid.split('.', 1)[0],
                'applies_to': 'both',
                'declared_tier': '',
                'orphan': True,
                'best': r.get('best'),
                'threshold': r.get('threshold'),
                'unit': r.get('unit', ''),
                'note': r.get('note', ''),
                'n_events': len(evs),
                'frames': sorted({e.get('frame') for e in evs if e.get('frame') is not None})[:200],
            }
            (found if r.get('events') else not_found).append(rec)
    return {'found': found, 'not_found': not_found, 'unmeasurable': unmeasurable, 'not_detectable': not_detectable}
