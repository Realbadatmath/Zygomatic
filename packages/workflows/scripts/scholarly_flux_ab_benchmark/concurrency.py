# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Mode 3 (realistic concurrent pipelines) and mode 4 (single persistent worker)."""

from __future__ import annotations

from .bench_assets import Any, BENCH_SLOTS, Path, _gpu_exclusivity_sweep, _log, time
from .slots import _load_diffusers_stack, _run_diffusers_slot, _teardown_diffusers, _vram_free_gb
from . import bench_assets as _bench_assets

# Bound by ASSIGNMENT, not `from ... import`: an import-originated global compiles
# `_zyg_log.debug(...)` to a different (non method-form) call sequence.
_zyg_log = _bench_assets._zyg_log


def _run_realistic_concurrent(
    n_pipelines: int,
    stagger_s: float,
    images_per_pipeline: int,
    pre_flux_s: float,
    char_id: str,
    pose_ref: str | None,
    pose_skeleton: str | None,
    run_dir: Path,
    pkg: dict | None,
) -> dict[str, Any]:
    """
    Mode 3: Realistic Concurrent.

    N threads each simulate one documentary pipeline against the real
    SCHOLARLY_GPU_LOCK.  Timeline per thread:

      sleep(index * stagger_s)           ← launch stagger (matches Zero batch)
      sleep(pre_flux_s)                  ← research + script + tagging + emotion
      acquire scholarly_gpu_lock         ← real fcntl.flock, same as production
      measure VRAM before model load
      load FLUX (diffusers, same as production)
      generate images_per_pipeline images
      release lock + aggressive_release_flux_pipeline_vram
      measure VRAM after teardown        ← fragmentation shows up here

    Key outputs:
      lock_wait_s per pipeline  — how long each queued behind the previous
      vram_after_teardown_progression — GB free after each cycle; drop = fragmentation
      pipelines_ok / pipelines_fail — whether FLUX load succeeded at all
    """
    import threading
    from zyg_workflows import scholarly_stills_backend as ssb

    results: list[dict[str, Any] | None] = [None] * n_pipelines
    vram_log: list[dict[str, Any]] = []
    vram_log_lock = threading.Lock()
    t_batch_start = time.time()

    def _vsnap(event: str, idx: int) -> float:
        v = _vram_free_gb()
        with vram_log_lock:
            vram_log.append(
                {
                    'event': event,
                    'pipeline': idx,
                    'vram_free_gb': v,
                    'elapsed_s': round(time.time() - t_batch_start, 1),
                }
            )
        _log(f'[pipeline-{idx}] {event}: VRAM free={v:.1f} GB')
        return v

    def _pipeline_worker(idx: int) -> None:
        pipeline_id = f'bench_realistic_{idx:02d}'
        pr: dict[str, Any] = {
            'pipeline': idx,
            'ok': False,
            'images_ok': 0,
            'images_fail': 0,
            'stagger_wait_s': round(idx * stagger_s, 1),
            'pre_flux_s': pre_flux_s,
            'lock_wait_s': 0.0,
            'load_s': 0.0,
            'per_image_s': [],
            'teardown_s': 0.0,
            'vram_before_load_gb': -1.0,
            'vram_after_teardown_gb': -1.0,
            'error': '',
        }
        try:
            time.sleep(idx * stagger_s)
            _log(f'[pipeline-{idx}] stagger done — simulating {pre_flux_s}s of pre-FLUX stages...')
            time.sleep(pre_flux_s)

            _vsnap('pre_lock_acquire', idx)
            t_lock = time.time()
            try:
                ssb.acquire_scholarly_gpu_lock(pipeline_id, log_fn=_log)
            except Exception as exc:
                pr['error'] = f'lock_acquire_failed: {exc}'[:200]
                results[idx] = pr
                return
            pr['lock_wait_s'] = round(time.time() - t_lock, 1)
            _log(f'[pipeline-{idx}] GPU lock acquired after {pr["lock_wait_s"]}s queue wait')

            pr['vram_before_load_gb'] = _vsnap('pre_load', idx)

            # Load FLUX exactly as production does
            t_load = time.time()
            try:
                stack = _load_diffusers_stack(pose_ref, char_id)
                pipe, cn_pipe, cns, neg, cn_scale, anat_suffix, _, pkg_d = stack
                pr['load_s'] = round(time.time() - t_load, 1)
                _vsnap('post_load', idx)
            except Exception as exc:
                pr['error'] = f'flux_load_failed: {str(exc)[:200]}'
                ssb.release_scholarly_gpu_lock(pipeline_id, log_fn=_log, skip_vram_teardown=True)
                results[idx] = pr
                return

            # Generate images
            img_dir = run_dir / f'realistic_p{idx:02d}'
            img_dir.mkdir(exist_ok=True)
            for img_i in range(images_per_pipeline):
                out_p = str(img_dir / f'img_{img_i:03d}.jpg')
                scene = BENCH_SLOTS[img_i % len(BENCH_SLOTS)][1]
                seed = 50_000 + idx * 1000 + img_i
                t_img = time.time()
                row = _run_diffusers_slot(
                    pipe,
                    cn_pipe,
                    cns,
                    neg,
                    cn_scale,
                    anat_suffix,
                    pose_ref,
                    pkg_d,
                    f'img_{img_i:03d}',
                    scene,
                    seed,
                    out_p,
                    pose_skeleton=pose_skeleton,
                )
                img_elapsed = round(time.time() - t_img, 2)
                pr['per_image_s'].append(
                    {
                        'img': img_i,
                        'ok': row.get('ok', False),
                        'elapsed_s': img_elapsed,
                        'error': row.get('error', ''),
                    }
                )
                if row.get('ok'):
                    pr['images_ok'] += 1
                else:
                    pr['images_fail'] += 1

            _vsnap('post_generate', idx)

            # Release + teardown (same as production release path)
            t_tear = time.time()
            ssb.release_scholarly_gpu_lock(
                pipeline_id,
                pipe=pipe,
                cn_pipe=cn_pipe,
                cn_service=cns,
                log_fn=_log,
            )
            pr['teardown_s'] = round(time.time() - t_tear, 1)
            pr['vram_after_teardown_gb'] = _vsnap('post_teardown', idx)
            pr['ok'] = pr['images_fail'] == 0

        except Exception as exc:
            pr['error'] = str(exc)[:300]
            try:
                ssb.release_scholarly_gpu_lock(pipeline_id, log_fn=_log, skip_vram_teardown=True)
            except Exception as _exc:
                _zyg_log.debug('suppressed %s: %s', type(_exc).__name__, _exc)
        results[idx] = pr

    threads = [
        threading.Thread(target=_pipeline_worker, args=(i,), daemon=True, name=f'bench-rc-{i}')
        for i in range(n_pipelines)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    batch_total_s = round(time.time() - t_batch_start, 1)

    teardown_vrams = [e['vram_free_gb'] for e in vram_log if e['event'] == 'post_teardown']
    pre_load_vrams = [e['vram_free_gb'] for e in vram_log if e['event'] == 'pre_load']
    ok_count = sum(1 for r in results if r and r.get('ok'))
    lock_waits = [r['lock_wait_s'] for r in results if r]

    # Fragmentation = VRAM free before first load minus VRAM free before last load.
    # A negative number means successive teardowns are not fully recovering VRAM.
    vram_fragmentation_gb = round(
        (pre_load_vrams[0] - pre_load_vrams[-1]) if len(pre_load_vrams) >= 2 else 0.0,
        2,
    )

    return {
        'mode': 'realistic_concurrent',
        'n_pipelines': n_pipelines,
        'stagger_s': stagger_s,
        'images_per_pipeline': images_per_pipeline,
        'pre_flux_s_simulated': pre_flux_s,
        'batch_total_s': batch_total_s,
        'pipelines_ok': ok_count,
        'pipelines_fail': n_pipelines - ok_count,
        'lock_wait_s': {
            'min': round(min(lock_waits), 1) if lock_waits else None,
            'max': round(max(lock_waits), 1) if lock_waits else None,
            'mean': round(sum(lock_waits) / len(lock_waits), 1) if lock_waits else None,
        },
        'vram_after_teardown_progression_gb': teardown_vrams,
        'vram_fragmentation_gb': vram_fragmentation_gb,
        'vram_log': vram_log,
        'per_pipeline': results,
        'interpretation': {
            'pipelines_failed_flux_load': [
                r['pipeline'] for r in results if r and 'flux_load_failed' in r.get('error', '')
            ],
            'pipelines_failed_images': [r['pipeline'] for r in results if r and r.get('images_fail', 0) > 0],
            'fragmentation_detected': vram_fragmentation_gb > 1.0,
        },
    }


def _run_persistent_worker(
    n_pipelines: int,
    stagger_s: float,
    images_per_pipeline: int,
    pre_flux_s: float,
    char_id: str,
    pose_ref: str | None,
    pose_skeleton: str | None,
    run_dir: Path,
    pkg: dict | None,
) -> dict[str, Any]:
    """
    Mode 4: Persistent Worker (proposed fix).

    Single FLUX load → shared image queue → single worker generates all
    N * images_per_pipeline images sequentially → single VRAM teardown.

    Pipeline threads still stagger and simulate pre-FLUX stages, then
    submit their image jobs to the queue and wait for results.  The model
    never reloads between pipelines — VRAM stays constant throughout.

    Compare batch_total_s and per_image_s mean against Mode 3 to quantify
    the tradeoff: single load amortised over the full batch vs repeated cycles.
    """
    import queue as _q
    import threading

    t_batch_start = time.time()
    job_queue: _q.Queue[Any] = _q.Queue()
    result_queues: list[_q.Queue[Any]] = [_q.Queue() for _ in range(n_pipelines)]
    results: list[dict[str, Any] | None] = [None] * n_pipelines
    vram_log: list[dict[str, Any]] = []

    def _vsnap(event: str) -> float:
        v = _vram_free_gb()
        vram_log.append(
            {
                'event': event,
                'vram_free_gb': v,
                'elapsed_s': round(time.time() - t_batch_start, 1),
            }
        )
        _log(f'[persistent] {event}: VRAM free={v:.1f} GB')
        return v

    _gpu_exclusivity_sweep()

    # Load FLUX once for the entire batch
    vram_before_load = _vsnap('pre_load')
    _log(f'[persistent] Loading FLUX once for {n_pipelines}-pipeline batch...')
    t_load = time.time()
    try:
        stack = _load_diffusers_stack(pose_ref, char_id)
        pipe, cn_pipe, cns, neg, cn_scale, anat_suffix, _, pkg_d = stack
        load_s = round(time.time() - t_load, 1)
        vram_after_load = _vsnap('post_load')
        _log(f'[persistent] FLUX loaded in {load_s}s — VRAM in use: {vram_before_load - vram_after_load:.1f} GB')
    except Exception as exc:
        return {
            'mode': 'persistent_worker',
            'ok': False,
            'error': f'flux_load_failed: {str(exc)[:300]}',
        }

    images_generated_count = [0]
    worker_errors: list[str] = []

    def _image_worker() -> None:
        while True:
            item = job_queue.get()
            if item is None:
                break
            idx, img_i, out_p, scene, seed, rq = item
            t_img = time.time()
            try:
                row = _run_diffusers_slot(
                    pipe,
                    cn_pipe,
                    cns,
                    neg,
                    cn_scale,
                    anat_suffix,
                    pose_ref,
                    pkg_d,
                    f'img_{img_i:03d}',
                    scene,
                    seed,
                    out_p,
                    pose_skeleton=pose_skeleton,
                )
                row['elapsed_s'] = round(time.time() - t_img, 2)
            except Exception as exc:
                row = {'ok': False, 'elapsed_s': round(time.time() - t_img, 2), 'error': str(exc)[:200]}
                worker_errors.append(row['error'])
            images_generated_count[0] += 1
            rq.put(row)

    worker_thread = threading.Thread(
        target=_image_worker,
        daemon=True,
        name='bench-persistent-worker',
    )
    worker_thread.start()

    def _pipeline_thread(idx: int) -> None:
        pr: dict[str, Any] = {
            'pipeline': idx,
            'ok': True,
            'images_ok': 0,
            'images_fail': 0,
            'stagger_wait_s': round(idx * stagger_s, 1),
            'queue_submit_s': 0.0,
            'queue_wait_s': 0.0,
            'per_image_s': [],
            'error': '',
        }
        time.sleep(idx * stagger_s)
        _log(f'[persistent/pipeline-{idx}] simulating {pre_flux_s}s pre-FLUX stages...')
        time.sleep(pre_flux_s)

        img_dir = run_dir / f'persistent_p{idx:02d}'
        img_dir.mkdir(exist_ok=True)
        rq = result_queues[idx]

        t_submit = time.time()
        for img_i in range(images_per_pipeline):
            out_p = str(img_dir / f'img_{img_i:03d}.jpg')
            scene = BENCH_SLOTS[img_i % len(BENCH_SLOTS)][1]
            seed = 60_000 + idx * 1000 + img_i
            job_queue.put((idx, img_i, out_p, scene, seed, rq))
        pr['queue_submit_s'] = round(time.time() - t_submit, 2)
        _log(f'[persistent/pipeline-{idx}] submitted {images_per_pipeline} jobs — waiting for results...')

        t_wait = time.time()
        for img_i in range(images_per_pipeline):
            row = rq.get()
            pr['per_image_s'].append(
                {
                    'img': img_i,
                    'ok': row.get('ok', False),
                    'elapsed_s': row.get('elapsed_s', 0),
                }
            )
            if row.get('ok'):
                pr['images_ok'] += 1
            else:
                pr['images_fail'] += 1
                pr['ok'] = False
        pr['queue_wait_s'] = round(time.time() - t_wait, 1)
        results[idx] = pr

    p_threads = [
        threading.Thread(target=_pipeline_thread, args=(i,), daemon=True, name=f'bench-pw-{i}')
        for i in range(n_pipelines)
    ]
    for t in p_threads:
        t.start()
    for t in p_threads:
        t.join()

    # Shut down worker and teardown FLUX
    job_queue.put(None)
    worker_thread.join()

    _vsnap('pre_teardown')
    t_tear = time.time()
    _teardown_diffusers(pipe, cn_pipe, cns)
    teardown_s = round(time.time() - t_tear, 1)
    vram_after_teardown = _vsnap('post_teardown')

    batch_total_s = round(time.time() - t_batch_start, 1)
    ok_count = sum(1 for r in results if r and r.get('ok'))

    all_img_times = [e['elapsed_s'] for r in results if r for e in r.get('per_image_s', []) if e.get('ok')]

    return {
        'mode': 'persistent_worker',
        'n_pipelines': n_pipelines,
        'stagger_s': stagger_s,
        'images_per_pipeline': images_per_pipeline,
        'pre_flux_s_simulated': pre_flux_s,
        'batch_total_s': batch_total_s,
        'total_images_generated': images_generated_count[0],
        'load_s': load_s,
        'teardown_s': teardown_s,
        'pipelines_ok': ok_count,
        'pipelines_fail': n_pipelines - ok_count,
        'vram_before_load_gb': vram_before_load,
        'vram_after_load_gb': vram_after_load,
        'vram_after_teardown_gb': vram_after_teardown,
        'vram_used_by_model_gb': round(vram_before_load - vram_after_load, 2),
        'per_image_s': {
            'mean': round(sum(all_img_times) / len(all_img_times), 2) if all_img_times else None,
            'min': round(min(all_img_times), 2) if all_img_times else None,
            'max': round(max(all_img_times), 2) if all_img_times else None,
        },
        'worker_errors': worker_errors,
        'vram_log': vram_log,
        'per_pipeline': results,
    }
