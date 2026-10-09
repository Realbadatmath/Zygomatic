# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later


"""Assembly, the mux, and what is measured on the deliverable.

Moved verbatim out of the old single-file kids_video_service.py (lines 3771-4067).
"""

from __future__ import annotations

import os
import subprocess
import time
from zyg_workflows import provenance_seal as _seal
from zyg_workflows.bin import exe

from zyg_workflows.kids_video_service.constants import (
    FPS,
    MIN_SLOT_S,
    _log_noop,
    _zyg_log,
)
from zyg_workflows.kids_video_service.motion import (
    _render_motion,
    _x264_args,
    motion_clip_for,
    run_ffmpeg,
)
from zyg_workflows.kids_video_service.transitions import (
    _xfade_graph,
    transitions_for,
)


def build_video(slots, paths, audio_path, out_dir, *, seed=0, log_fn=None, grid=None, should_abort=None):
    """Motion clips → one xfade chain → mux with the delivered master."""
    log_fn = log_fn or _log_noop
    abort = should_abort or (lambda: False)
    work = os.path.join(out_dir, '_clips')
    os.makedirs(work, exist_ok=True)
    info = {
        'clips': 0,
        'static': 0,
        'transitions': [],
        'ok': False,
        'reason': '',
        'pulses': 0,
        # 'motion_clips' = slots whose clip came from LTX-2.5; 'kenburns' = slots
        # that shipped as a still with a move. The channel contract since
        # 2026-10-02 is kenburns == 0 — reported, never hidden.
        'motion_clips': 0,
        'kenburns': 0,
        'motion_coverage': 0.0,
    }
    mpaths = [motion_clip_for(s, out_dir) for s in slots]

    # Bar downbeats, approximated as every bar_beats-th measured beat. Used for
    # the zoom pulse only — a wrong phase costs a slightly early breath, not a
    # wrong cut.
    pulses = []
    if grid and grid.get('beats'):
        step = max(1, int(round(grid.get('bar_beats') or 4)))
        pulses = [float(b) for k, b in enumerate(grid['beats']) if k % step == 0]
    info['pulses'] = len(pulses)

    trans = transitions_for(slots, seed=seed)
    info['transitions'] = trans

    usable = [(s, p, m) for s, p, m in zip(slots, paths, mpaths) if p and os.path.isfile(p)]
    if not usable:
        info['reason'] = 'no frames to assemble'
        return None, info
    if len(usable) != len(slots):
        log_fn(
            f'assembly: {len(slots) - len(usable)} slot(s) had no frame — their time is absorbed by their neighbours'
        )
        # Re-derive the slot list and its transitions from what actually exists,
        # so the timeline stays continuous instead of leaving a gap.
        slots = []
        for k, (s, _p, _m) in enumerate(usable):
            s = dict(s)
            s['i'] = k
            slots.append(s)
        for k in range(len(slots) - 1):
            slots[k]['end'] = slots[k + 1]['start']
            slots[k]['dur'] = round(max(MIN_SLOT_S, slots[k]['end'] - slots[k]['start']), 4)
        trans = transitions_for(slots, seed=seed)
        info['transitions'] = trans
        paths = [p for _s, p, _m in usable]
        mpaths = [m for _s, _p, m in usable]

    graph, lens = _xfade_graph(slots, trans, len(slots))

    # 1. motion clips, in parallel — the encode is the slow part and it is
    #    embarrassingly parallel. Bounded by the box's collective core ceiling.
    try:
        from zyg_workflows import cpu_cap

        cores = max(2, len(cpu_cap.cores()))
    except Exception:  # noqa: BLE001
        cores = 8
    workers = max(1, min(6, cores // 3))
    import concurrent.futures as _cf

    clips = [None] * len(slots)

    def _one(k):
        if abort():  # a halted run must not keep encoding
            return k, None
        cp = os.path.join(work, f'c{k:03d}.mp4')
        s = dict(slots[k])
        s['dur'] = lens[k]  # encode the COMPENSATED length
        how = _render_motion(paths[k], cp, s, pulses, clip_path=mpaths[k])
        return k, (cp if how else None), how

    t0 = time.time()
    with _cf.ThreadPoolExecutor(max_workers=workers) as pool:
        for k, cp, how in pool.map(_one, range(len(slots))):
            clips[k] = cp
            if how == 'ltx':
                info['motion_clips'] += 1
            elif how == 'kenburns':
                info['kenburns'] += 1
    info['motion_coverage'] = round(info['motion_clips'] / max(1, len(slots)), 3)
    if info['kenburns']:
        log_fn(
            f'assembly: {info["kenburns"]} slot(s) shipped as a STILL with a Ken Burns '
            f'move — the no-stills contract is not met for them'
        )
    log_fn(
        f'assembly: {sum(1 for c in clips if c)}/{len(slots)} motion clips '
        f'in {time.time() - t0:.0f}s on {workers} thread(s)'
    )
    if abort():
        info['reason'] = 'halted by operator'
        return None, info

    # 2. any clip that failed falls back to a still of the right length, so one
    #    bad encode costs its motion, not the video.
    inputs = []
    for k, cp in enumerate(clips):
        if cp and os.path.isfile(cp):
            inputs += ['-t', f'{lens[k]:.3f}', '-i', cp]
            info['clips'] += 1
        else:
            inputs += ['-loop', '1', '-t', f'{lens[k]:.3f}', '-i', paths[k]]
            info['static'] += 1
    if info['static']:
        log_fn(f'assembly: {info["static"]} slot(s) fell back to a static frame')

    silent = os.path.join(out_dir, '_silent.mp4')
    cmd = (
        [exe('ffmpeg'), '-y']
        + inputs
        + ['-filter_complex', graph, '-map', '[vout]']
        + _x264_args()
        + ['-r', str(FPS), silent]
    )
    try:
        rc, err = run_ffmpeg(cmd, 1800, should_abort=should_abort)
        if rc != 0:
            info['reason'] = 'ffmpeg slideshow failed: ' + (err or b'').decode('utf-8', 'replace')[-400:]
            log_fn(f'assembly: {info["reason"]}')
            return None, info
    except Exception as e:  # noqa: BLE001
        info['reason'] = f'ffmpeg slideshow raised {type(e).__name__}: {e}'
        log_fn(f'assembly: {info["reason"]}')
        return None, info

    # 3. mux the DELIVERED master in, re-encoding nothing on the video side.
    out = os.path.join(out_dir, 'video.mp4')
    mux = [
        exe('ffmpeg'),
        '-y',
        '-i',
        silent,
        '-i',
        audio_path,
        '-c:v',
        'copy',
        '-c:a',
        'aac',
        '-b:a',
        '192k',
        '-map',
        '0:v:0',
        '-map',
        '1:a:0',
        '-shortest',
        '-movflags',
        '+faststart',
        out,
    ]
    try:
        rc, err = run_ffmpeg(mux, 900, should_abort=should_abort)
        if rc != 0:
            info['reason'] = 'ffmpeg mux failed: ' + (err or b'').decode('utf-8', 'replace')[-400:]
            log_fn(f'assembly: {info["reason"]}')
            return None, info
    except Exception as e:  # noqa: BLE001
        info['reason'] = f'ffmpeg mux raised {type(e).__name__}: {e}'
        return None, info
    _seal.seal(out, pipeline='kids_video', log_fn=log_fn)

    # 4. poster + cleanup
    poster = os.path.join(out_dir, 'poster.jpg')
    try:
        subprocess.run(
            [exe('ffmpeg'), '-y', '-i', out, '-frames:v', '1', '-q:v', '3', poster],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=120,
        )
    except Exception as _exc:  # noqa: BLE001
        _zyg_log.warning('poster frame extraction failed, the video ships without a poster: %s', _exc)
    if os.path.isfile(poster):
        # The poster ships on its own (feeds, thumbnails), so it is sealed on its own.
        _seal.seal_derived(poster, out, pipeline='kids_video', log_fn=log_fn)
    for f in os.listdir(work):
        try:
            os.remove(os.path.join(work, f))
        except OSError as _exc:
            _zyg_log.debug('work file %s removal skipped: %s', f, _exc)
    try:
        os.rmdir(work)
        os.remove(silent)
    except OSError as _exc:
        _zyg_log.debug('work directory cleanup skipped: %s', _exc)
    info['ok'] = True
    return out, info


# ── Measured on the deliverable ──────────────────────────────────────────────


def verify_cuts(video_path, slots, trans, log_fn=None, fps=12, w=96, h=54):
    """Does the picture ACTUALLY change where the storyboard says it does?

    Every other measurement in this module is taken on the plan or on the loose
    frames.  This one is taken on the mp4 a person would watch, because those are
    different claims: a filter graph that silently drops half its inputs, an
    xfade chain that terminates early, a slot whose frame never reached ffmpeg —
    all of them leave the plan and the frames perfectly intact.  (The house rule
    this follows: a frozen-camera check proves an effect exists, never that it is
    visible.)

    Method: decode the finished video at 12 fps into 96x54 greyscale, take the
    mean absolute difference between consecutive frames, and ask of each planned
    cut whether the difference around it rises clearly above the video's own
    baseline.  The baseline is the median difference over the whole video — which
    is the gentle Ken Burns drift — so the threshold is derived from this video
    rather than being a number someone picked.
    """
    log_fn = log_fn or _log_noop
    out = {'ran': False, 'reason': ''}
    if not video_path or not os.path.isfile(video_path) or len(slots) < 2:
        out['reason'] = 'nothing to verify'
        return out
    try:
        p = subprocess.run(
            [
                exe('ffmpeg'),
                '-v',
                'error',
                '-i',
                video_path,
                '-vf',
                f'fps={fps},scale={w}:{h},format=gray',
                '-f',
                'rawvideo',
                '-',
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=900,
        )
        buf = p.stdout or b''
    except Exception as e:  # noqa: BLE001
        out['reason'] = f'{type(e).__name__}: {e}'
        return out
    step = w * h
    n = len(buf) // step
    if n < 4:
        out['reason'] = f'only {n} sampled frame(s)'
        return out
    try:
        import numpy as np

        a = np.frombuffer(buf[: n * step], dtype=np.uint8).reshape(n, step).astype(np.int16)
        d = np.abs(np.diff(a, axis=0)).mean(axis=1)
        base = float(np.median(d))
    except Exception as e:  # noqa: BLE001
        out['reason'] = f'numpy unavailable ({type(e).__name__})'
        return out

    thr = max(2.5 * base, 1.5)
    confirmed, misses = 0, []
    for j in range(1, len(slots)):
        b = float(slots[j]['start'])
        half = (trans[j - 1]['duration'] if j - 1 < len(trans) else 0.3) / 2.0
        lo = int(max(0, (b - half - 0.25) * fps))
        hi = int(min(len(d), (b + half + 0.25) * fps) + 1)
        peak = float(d[lo:hi].max()) if hi > lo else 0.0
        if peak >= thr:
            confirmed += 1
        else:
            misses.append({'slot': slots[j]['i'], 'at_s': round(b, 2), 'peak': round(peak, 2)})
    total = len(slots) - 1
    out.update(
        {
            'ran': True,
            'sampled_fps': fps,
            'frames': n,
            'baseline_diff': round(base, 3),
            'threshold': round(thr, 3),
            'cuts_planned': total,
            'cuts_visible': confirmed,
            'visible_pct': round(100.0 * confirmed / max(1, total), 1),
            'ok': confirmed >= total,
            'missed': misses[:8],
        }
    )
    log_fn(
        f'verify: {confirmed}/{total} planned cuts are visible in the finished '
        f'file (baseline drift {base:.2f}, threshold {thr:.2f})'
    )
    if misses:
        log_fn(f'verify: {len(misses)} cut(s) show no visible change — first at {misses[0]["at_s"]}s')
    return out
