# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import os
import subprocess
import sys
import tempfile
import time
from zyg_workflows.bin import exe

from zyg_workflows.vlm_inspector.base import (
    TIERS,
    TIER_ORDER,
    VLM_HOME,
    _VLM_PY,
    _VLM_WORKER,
    _enabled,
    _mklog,
    _questions_payload,
    _select_items,
    _skipped,
    available,
    load_checklist,
    model_for,
)
from zyg_workflows.vlm_inspector.judge_server import _aggregate, _run_worker

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger('zyg_workflows.vlm_inspector')


# ── tier selection ───────────────────────────────────────────────────────────


def _downshift(tier, free_gb, log):
    """boundary -> resident -> cpu until the tier fits in free_gb."""
    idx = TIER_ORDER.index(tier) if tier in TIER_ORDER else 0
    for i in range(idx, len(TIER_ORDER)):
        t = TIER_ORDER[i]
        if free_gb >= TIERS[t]['min_free_gb']:
            if i != idx:
                log(
                    f'DOWNSHIFT {tier} -> {t}: only {free_gb:.1f} GB free '
                    f'(tier {tier} needs {TIERS[tier]["min_free_gb"]} GB)'
                )
            return t
    log(f'DOWNSHIFT {tier} -> cpu: {free_gb:.1f} GB free fits no GPU tier')
    return 'cpu'


# ── the public API ───────────────────────────────────────────────────────────


def inspect_frames(
    frame_paths,
    checklist='scene20_binary',
    tier='boundary',
    offload=True,
    min_free_gb=None,
    ref_images=None,
    frame_kind='beats',
    k=None,
    log_fn=None,
    server=None,
    items=None,
    preamble=None,
):
    """Run a binary checklist over already-extracted frames.

    frame_paths : sharp decoded frames (or, for tier-0, one blurry preview).
    checklist   : name in config/vlm_checklists.json.
    tier        : 'boundary' (strongest, needs the GPU to itself), 'resident'
                  (small, GPU) or 'cpu' (small, CPU only — never touches VRAM).
    offload     : GPU tiers only — hand ComfyUI's VRAM over via
                  comfy_offload.gpu_exclusive first (ComfyUI reloads lazily on
                  its next job).  False = fit into whatever is free right now.
    min_free_gb : override the tier's VRAM requirement (None = tier default).
    ref_images  : reference portraits, PREPENDED to the images and announced to
                  the judge; identity questions are skipped without them.
    frame_kind  : 'beats' (sharp beat frames — ask everything) or 'all' (ask
                  only the questions marked frames='all', e.g. blurry previews).
    k           : k-ensemble repeats, majority vote (default ZYG_VLM_K or 1).
    items       : inline checklist items (same schema as the JSON file) — used
                  instead of `checklist` when given. Lets a caller build
                  per-frame, prompt-derived questions (era_gate) without
                  writing a checklist file. `preamble` pairs with it.

    Returns {'ok','skipped','verdicts','flags','criticals','majors','unknown',
    'bboxes','tier','model','frames','seconds', ...}.  EVERY failure path
    returns ok=True + skipped=True: this judge is a reject-only second opinion
    and must never break a render.  Refuses (skips) while ComfyUI is sampling
    whenever the chosen tier would touch the GPU.
    """
    log = _mklog(log_fn)
    t0 = time.time()
    if not _enabled():
        return _skipped('disabled')
    frames = [p for p in (frame_paths or []) if p and os.path.isfile(p)]
    if not frames:
        log('no frames to inspect')
        return _skipped('no_frames')
    if not available():
        log(f'judge venv/worker missing under {VLM_HOME} — SKIPPING inspection (expected {_VLM_PY} + {_VLM_WORKER})')
        return _skipped('worker_unavailable')

    if items:
        _inl = [i for i in items if isinstance(i, dict) and i.get('id') and i.get('question')]
        cl = (
            {'name': checklist or 'inline', 'description': 'inline items', 'preamble': preamble or '', 'items': _inl}
            if _inl
            else {}
        )
        checklist = cl.get('name', 'inline') if cl else checklist
    else:
        cl = load_checklist(checklist, log_fn=log_fn)
    if not cl:
        return _skipped('checklist_unavailable', checklist=checklist)
    refs = [p for p in (ref_images or []) if p and os.path.isfile(p)]
    items = _select_items(cl['items'], frame_kind, bool(refs))
    if not items:
        log(f'checklist {checklist}: no items apply to frame_kind={frame_kind}')
        return _skipped('no_items', checklist=checklist)

    tier = tier if tier in TIERS else 'boundary'
    cfg = TIERS[tier]
    need = float(cfg['min_free_gb'] if min_free_gb is None else min_free_gb)

    def _go(chosen_tier):
        return _execute(chosen_tier, items, cl, frames, refs, k, t0, checklist, frame_kind, log)

    if not cfg['needs_gpu']:
        return _go(tier)

    # ---- GPU tiers: never while ComfyUI samples --------------------------
    try:
        from zyg_workflows import comfy_offload as CO
    except Exception as e:
        log(f'comfy_offload unavailable ({e}) — running on CPU instead of risking VRAM')
        return _go('cpu')

    try:
        sampling = CO.comfy_is_sampling(server) if server else CO.comfy_is_sampling()
    except Exception as e:
        log(f'comfy_is_sampling failed ({e}) — assuming SAMPLING and refusing')
        sampling = True
    if sampling:
        if os.environ.get('ZYG_VLM_CPU_WHEN_BUSY', '0') == '1':
            log('ComfyUI is SAMPLING — downshifting to CPU (ZYG_VLM_CPU_WHEN_BUSY=1)')
            return _go('cpu')
        log(
            'ComfyUI is SAMPLING — REFUSING GPU inspection (a render is mid-sample); '
            'retry at the next pipeline pause point'
        )
        return _skipped('comfy_sampling', checklist=checklist, tier=tier)

    if not offload:
        free = 0.0
        try:
            free = CO.gpu_free_gb() or 0.0
        except Exception as e:
            log(f'gpu_free_gb failed ({e}) — assuming 0 GB free')
        return _go(_downshift(tier, float(free), log))

    try:
        with CO.gpu_exclusive(min_free_gb=need, log_fn=log_fn) as free_gb:
            return _go(_downshift(tier, float(free_gb or 0.0), log))
    except getattr(CO, 'ComfySamplingActiveError', RuntimeError) as e:
        log(f'gpu_exclusive refused ({e}) — skipping inspection')
        return _skipped('comfy_sampling', checklist=checklist, tier=tier)
    except Exception as e:
        log(f'gpu_exclusive failed ({e}) — falling back to CPU tier')
        return _go('cpu')


def _execute(tier, items, cl, frames, refs, k, t0, checklist, frame_kind, log):
    """Run the worker k times at a resolved tier and aggregate.  Fail-safe."""
    try:
        k = int(k if k is not None else os.environ.get('ZYG_VLM_K', '1'))
    except Exception:
        k = 1
    k = max(1, min(5, k))
    model_id = model_for(tier)
    images = refs + frames
    payload = _questions_payload(items, cl.get('preamble', ''), len(refs))
    runs = []
    for _i in range(k):
        r = _run_worker(model_id, images, payload, tier, log)
        if r is None:
            continue
        if r.get('ok') is False and not r.get('verdicts'):
            log(f'worker reported failure: {str(r.get("error"))[:300]}')
            continue
        runs.append(r)
    if not runs:
        return _skipped(
            'worker_failed',
            checklist=checklist,
            tier=tier,
            model=model_id,
            frames=frames,
            n_frames=len(frames),
            seconds=round(time.time() - t0, 1),
        )
    agg = _aggregate(items, runs, log)
    agg.update(
        {
            'skipped': False,
            'checklist': checklist,
            'tier': tier,
            'model': model_id,
            'device': TIERS[tier]['device'],
            'frames': frames,
            'n_frames': len(frames),
            'n_refs': len(refs),
            'frame_kind': frame_kind,
            'k': k,
            'runs': len(runs),
            'seconds': round(time.time() - t0, 1),
        }
    )
    log(summarize(agg))
    return agg


def _clip_duration_s(clip_path):
    """Clip duration via ffprobe; None when it cannot be read."""
    try:
        r = subprocess.run(
            [exe('ffprobe'), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=nw=1:nk=1', clip_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        return float((r.stdout or '').strip().splitlines()[0])
    except Exception:
        return None


def extract_frames(clip_path, times, out_dir, log_fn=None):
    """Pull one PNG per timestamp with ffmpeg.  Out-of-range times are dropped;
    returns [(t, path), ...] (possibly empty — fail-safe, never raises)."""
    log = _mklog(log_fn)
    got = []
    dur = _clip_duration_s(clip_path)
    for t in times or []:
        try:
            t = float(t)
        except (TypeError, ValueError) as _exc:
            _zyg_log.debug('non-numeric frame time ignored: %s', _exc)
            continue
        if t < 0 or (dur is not None and t > max(0.0, dur - 0.05)):
            log(f'skip t={t}s (clip is {dur if dur is not None else "?"}s)')
            continue
        p = os.path.join(out_dir, f'f_{t:07.3f}.png'.replace('.', '_', 1))
        try:
            subprocess.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-loglevel',
                    'error',
                    '-ss',
                    f'{t:.3f}',
                    '-i',
                    clip_path,
                    '-frames:v',
                    '1',
                    '-update',
                    '1',
                    p,
                ],
                check=True,
                timeout=120,
            )
            if os.path.isfile(p):
                got.append((t, p))
        except Exception as e:
            log(f'frame extract failed at t={t}s: {e}')
    if not got and dur:
        # Nothing landed (bad times) — fall back to three evenly spaced frames.
        for t in (dur * 0.15, dur * 0.5, dur * 0.85):
            p = os.path.join(out_dir, f'fb_{t:07.3f}.png'.replace('.', '_', 1))
            try:
                subprocess.run(
                    [
                        exe('ffmpeg'),
                        '-y',
                        '-loglevel',
                        'error',
                        '-ss',
                        f'{t:.3f}',
                        '-i',
                        clip_path,
                        '-frames:v',
                        '1',
                        '-update',
                        '1',
                        p,
                    ],
                    check=True,
                    timeout=120,
                )
                if os.path.isfile(p):
                    got.append((round(t, 2), p))
            except Exception as _exc:
                _zyg_log.warning('fallback frame extraction at t=%s failed: %s', t, _exc)
        if got:
            log(f'requested times were out of range — using fallback times {[t for t, _ in got]}')
    return got


def inspect_clip(clip_path, times, checklist='scene20_binary', log_fn=None, **kw):
    """Extract frames at `times` (seconds) and run inspect_frames on them.

    Times beyond the clip are dropped with a log (an 81-frame probe is ~4.8 s at
    17 fps, so full-clip beat times are expected to be out of range there).
    """
    log = _mklog(log_fn)
    if not _enabled():
        return _skipped('disabled')
    if not (clip_path and os.path.isfile(clip_path)):
        log(f'clip missing: {clip_path}')
        return _skipped('no_clip')
    tmpdir = tempfile.mkdtemp(prefix='vlmframes_')
    try:
        got = extract_frames(clip_path, times, tmpdir, log_fn=log_fn)
        if not got:
            log(f'no frames extracted from {os.path.basename(clip_path)}')
            return _skipped('no_frames', clip=clip_path)
        kw.setdefault('checklist', checklist)
        res = inspect_frames([p for _, p in got], log_fn=log_fn, **kw)
        res['clip'] = clip_path
        res['times'] = [t for t, _ in got]
        return res
    except Exception as e:
        log(f'inspect_clip error: {e}')
        return _skipped('error', clip=clip_path, error=str(e))
    finally:
        if os.environ.get('ZYG_VLM_KEEP_FRAMES', '0') != '1':
            try:
                import shutil

                shutil.rmtree(tmpdir, ignore_errors=True)
            except Exception as _exc:
                _zyg_log.debug('frame temp dir cleanup skipped: %s', _exc)


def summarize(res):
    """One-line human/log summary of an inspect_* result."""
    try:
        if not res:
            return 'vlm: no result'
        if res.get('skipped'):
            return f'vlm SKIPPED ({res.get("reason")})'
        return (
            f'vlm {res.get("checklist")} tier={res.get("tier")} '
            f'({res.get("device")}) {res.get("n_frames")}f/'
            f'{len(res.get("verdicts") or [])}q {res.get("seconds")}s '
            f'ok={res.get("ok")} critical={res.get("criticals") or []} '
            f'major={res.get("majors") or []}'
        )
    except Exception:
        return 'vlm: unsummarizable result'


if __name__ == '__main__':  # tiny manual smoke: python vlm_inspector.py a.png b.png
    _args = sys.argv[1:]
    _cl = os.environ.get('ZYG_VLM_CHECKLIST', 'scene20_binary')
    _tier = os.environ.get('ZYG_VLM_TIER', 'cpu')
