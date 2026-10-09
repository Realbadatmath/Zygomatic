"""Stage 3.5 Pre-generation (marker 11) of the scholarly pipeline, in three parts.

A pure move out of `_run_scholarly_pipeline` in `zyg_workflows.pipeline_scholarly`:
the statements, their order and their side effects are the ones the monolith ran.
Like `stages_19_36` — and unlike `stages_01_18`, which rewrote a crossing local to
`ctx.<name>` — these stages keep the body **byte-identical** and carry the
crossings in glue lines around it::

    def stage_nn_slug(ctx):
        job = ctx.job                 # what crosses in
        <the range, verbatim>
        ctx._flux_ready = _flux_ready # what crosses out

That style is not a preference here either: this block defines fifty-odd nested
`def`s and one enclosing-scope rebind, and a closure cannot capture an
attribute.

The one marker the earlier tasks left behind was 4,925 lines, far past any
sensible function, so it is cut at its two statement seams into:

* `stage_11_flux_prompt_batch` — `_batch_generate_flux_prompts` and the single
  Claude Sonnet batch call that fills `_prebuilt_prompts`. It and its five
  former closures now live in `stages_37_54_prompt_batch` and
  `stages_37_54_prompt_guards`, hoisted flat; this module re-exports the stage
  so `pipeline_scholarly` still imports it from here;
* `stage_11b_flux_preflight` — the pre-emptive record/replay exits, the pre-FLUX
  Murch self-eval, the "is the checkpoint downloaded" probe, the stills-backend
  choice (Qwen / FLUX / Comfy) and the persistent FluxWorker claim. Those six
  steps are flat and independent, so each is a function in
  `stages_37_54_preflight` and what is left here calls them in order;
* `stage_11c_flux_image_loop` — `if _flux_ready or _sch_comfy_only:`, i.e. the
  whole per-image generation loop, the upscales, the manifest and the GPU-lock
  release. It was one `if` statement of 3,541 lines with no flat seam, so task 9
  of the 2026-10 wave refactored rather than moved it: what is left here is the
  GPU-lock claim, four calls and the error path, and the body lives in

  - `stages_37_54_flux_setup` — `setup_flux_prelude` (torch import, GPU
    exclusivity, family label), `setup_flux_pipes` (the pipes, the FluxWorker
    hand-off, IP-Adapter, ControlNet and every loop-state init) and
    `setup_gates` (the two post-stage QA closures on `ctx`, then the gate
    fields);
  - `stages_37_54_flux_loop` — `run_slot_loop` (the per-slot loop, the reviews
    and `_gate_receipt`) and `finish_flux_stage` (the repair pass, the
    teardown, the upscales and the manifest).

  The names those blocks rebind travel on `FluxLoopState` (`fs`) instead of in
  one frame's locals, so the `except`/`finally`/`else` and the `ctx` tail —
  which stay here verbatim, because the lock-release order is the whole point of
  them — still see what the body reached. `stages_37_54_flux_setup` and
  `stages_37_54_flux_loop` are imported inside the function, never at module
  level: they import helpers from here, so a module-level import is a cycle.

`stage_11b_flux_preflight` is the only stage so far that can end the run: the
record and the replay-verify branches used to `return` out of the monolith, so
they return `StageExit()` and the call site re-raises that as its own return.

See SPLIT_LOG.md for the stage→marker map and the full list of non-mechanical spots.
"""

import logging as _zyg_logging

from zyg_workflows import gui_state
from zyg_workflows.scholarly.context import UNSET
from zyg_workflows.scholarly.stages_37_54_preflight import (
    choose_stills_backend,
    claim_flux_worker,
    preempt_record_exit,
    preempt_replay_exit,
    probe_flux_ready,
    run_pre_flux_self_eval,
)
from zyg_workflows.scholarly.stages_37_54_prompt_batch import (
    stage_11_flux_prompt_batch,  # noqa: F401  # re-export: pipeline_scholarly imports it from here
)

# The monolith's logger name, not `__name__`, so the `suppressed …` debug lines
# of one run all stay under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def stage_11b_flux_preflight(ctx):
    _log = ctx._log
    _pbank = ctx._pbank
    _preempt_dry = ctx._preempt_dry
    _preempt_mode = ctx._preempt_mode
    # ── A pre-emptive run ends here: every text Claude call is made, no image is
    # rendered. The exit snapshots and returns; the `finally` block of the call
    # site still runs the gate audit and the VRAM release.
    if _preempt_mode == 'replay' and _preempt_dry and _pbank is not None:
        # Verify run: the brain replayed from the bank up to this point; report and stop.
        return preempt_replay_exit(ctx)

    if _preempt_mode == 'record' and _pbank is not None:
        return preempt_record_exit(ctx)

    # ── Murch self-evaluation (Option A: before FLUX loads VRAM) ──────
    run_pre_flux_self_eval(ctx)

    # murch_engine extras pulled from pipeline state
    _murch_turning_points = ctx.pipeline_state.get('turning_points', [])
    _murch_image_debug: list = []  # accumulates per-image debug events
    _prev_focal_zone: str | None = None  # updated after each image generation

    # Check FLUX model is fully downloaded
    _flux_ready = probe_flux_ready(ctx._flux_model_path, _log)

    _flux_generated_paths = []
    _flux_image_meta = []  # always defined — populated only when FLUX runs

    from zyg_workflows import scholarly_stills_backend as _sch_backend

    _stills = choose_stills_backend(ctx, _sch_backend, _flux_ready, _log)

    _sch_gpu_lock_held = False
    _sch_fw, _sch_fw_active, _fw_claimed_start = claim_flux_worker(_sch_backend, _flux_ready, _stills.comfy_only, _log)
    ctx._flux_generated_paths = _flux_generated_paths
    ctx._flux_image_meta = _flux_image_meta
    ctx._flux_ready = _flux_ready
    ctx._fw_claimed_start = _fw_claimed_start
    ctx._murch_image_debug = _murch_image_debug
    ctx._murch_turning_points = _murch_turning_points
    ctx._prev_focal_zone = _prev_focal_zone
    ctx._sch_backend = _sch_backend
    ctx._sch_comfy_only = _stills.comfy_only
    ctx._sch_fw = _sch_fw
    ctx._sch_fw_active = _sch_fw_active
    ctx._sch_gpu_lock_held = _sch_gpu_lock_held
    ctx._sch_qwen_stills = _stills.qwen_stills
    ctx._sch_skip_local_flux = _stills.skip_local_flux
    ctx._sch_use_comfy_images = _stills.use_comfy_images


def stage_11c_flux_image_loop(ctx):
    _assert_not_stopped = ctx._assert_not_stopped
    _flux_generated_paths = ctx._flux_generated_paths
    _flux_image_meta = ctx._flux_image_meta
    _flux_ready = ctx._flux_ready
    _fw_claimed_start = ctx._fw_claimed_start
    _log = ctx._log
    _sch_backend = ctx._sch_backend
    _sch_comfy_only = ctx._sch_comfy_only
    _sch_family_label = ctx._sch_family_label
    _sch_fw = ctx._sch_fw
    _sch_fw_active = ctx._sch_fw_active
    _sch_gpu_lock_held = ctx._sch_gpu_lock_held
    _stop_event_scholarly = ctx._stop_event_scholarly
    pipeline_id = ctx.pipeline_id
    if _flux_ready or _sch_comfy_only:
        if not _sch_fw_active:
            try:
                _lock_id = '_flux_worker' if _fw_claimed_start else pipeline_id
                _sch_backend.acquire_scholarly_gpu_lock(
                    _lock_id,
                    log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
                    stop_check=lambda: (
                        gui_state._pipeline_stop_flag
                        or (_stop_event_scholarly is not None and _stop_event_scholarly.is_set())
                    ),
                )
                _sch_gpu_lock_held = ctx._sch_gpu_lock_held = True
            except _sch_backend.ScholarlyGpuLockStopped:
                if _fw_claimed_start and _sch_fw is not None:
                    _sch_fw.cancel_start()
                _log('INFO', 'Stage 3.5', 'Stopped while waiting for SCHOLARLY_GPU_LOCK')
                _assert_not_stopped('Stage 3.5')
        try:
            # Imported here, not at module level: the stage modules import helpers
            # from this module, so a module-level import would be a cycle.
            from zyg_workflows.scholarly import stages_37_54_flux_setup as _flux_setup

            # The prelude runs between the two `try:` statements the monolith had,
            # so a failed `import torch` or a refused GPU-exclusivity check is NOT
            # swallowed by `except Exception as _flux_err` below — it never was.
            _torch_flux, _sch_family_label, _FluxPipeline = _flux_setup.setup_flux_prelude(ctx)
            try:
                from zyg_workflows.scholarly import stages_37_54_flux_loop as _flux_loop
                from zyg_workflows.scholarly import stages_37_54_flux_state as _flux_state

                # Built here and not by `FluxLoopState.capture` at the end of the
                # setup, because the error path below reads it: a GPU lock handed
                # to the FluxWorker half-way through the setup must not then be
                # released a second time. `_flux_pipe=UNSET` is "never bound",
                # which is what `del _flux_pipe` tested with `except NameError`.
                fs = _flux_state.FluxLoopState(
                    _torch_flux=_torch_flux,
                    _flux_pipe=UNSET,
                    _flux_images_dir=ctx._flux_images_dir,
                    _flux_generated_paths=_flux_generated_paths,
                    _flux_image_meta=_flux_image_meta,
                    _sch_family_label=_sch_family_label,
                    _sch_fw_active=_sch_fw_active,
                    _prev_focal_zone=ctx._prev_focal_zone,
                )
                try:
                    _flux_setup.setup_flux_pipes(fs, ctx, _FluxPipeline)
                    _flux_setup.setup_gates(fs, ctx)
                    _flux_loop.run_slot_loop(fs, ctx)
                    _flux_loop.finish_flux_stage(fs, ctx)
                finally:
                    # The four calls above were one frame; these are the names it
                    # rebound that the error path, the `finally` and the `ctx` tail
                    # read. Refreshed in a `finally` so a failure part-way through
                    # leaves each where that frame had got to.
                    _flux_generated_paths = fs._flux_generated_paths
                    _flux_image_meta = fs._flux_image_meta
                    _sch_family_label = fs._sch_family_label
                    _sch_fw_active = fs._sch_fw_active
                    _sch_gpu_lock_held = ctx._sch_gpu_lock_held
                    if fs._flux_pipe is not UNSET:
                        _flux_pipe = fs._flux_pipe
            except Exception as _flux_err:
                _log('WARNING', 'Stage 3.5', f'FLUX generation failed: {_flux_err} — using Wikimedia images only')
                if not _sch_fw_active:
                    # Move tensors to CPU before releasing refs — see normal unload path above.
                    try:
                        import torch as _torch_flux_cleanup
                        import gc as _gc_cleanup

                        _flux_exc_target = gui_state._FLUX_PIPELINE_CACHE
                        gui_state._FLUX_PIPELINE_CACHE = None
                        gui_state._CN_PIPE_CACHE = None
                        for _exc_comp_attr in ('transformer', 'vae', 'text_encoder', 'text_encoder_2'):
                            _exc_comp = getattr(_flux_exc_target, _exc_comp_attr, None)
                            if _exc_comp is not None:
                                try:
                                    _exc_comp.to('cpu')
                                except Exception as _exc:  # noqa: BLE001 — torch raises its own hierarchy from .to()
                                    _zyg_log.debug(
                                        'FLUX %s not moved to CPU on the error path: %s',
                                        _exc_comp_attr,
                                        _exc,
                                    )
                        del _flux_exc_target
                    except Exception as _exc:  # noqa: BLE001 — torch and diffusers raise their own hierarchy
                        _zyg_log.debug('FLUX components not moved to CPU on the error path: %s', _exc)
                    try:
                        del _flux_pipe
                    except NameError as _exc:
                        _zyg_log.debug('_flux_pipe was never bound — nothing to drop: %s', _exc)
                    try:
                        import torch as _torch_flux_cleanup
                        import gc as _gc_cleanup

                        _gc_cleanup.collect()
                        _torch_flux_cleanup.cuda.empty_cache()
                        import time as _t_cleanup

                        _t_cleanup.sleep(3)
                        _gc_cleanup.collect()
                        _torch_flux_cleanup.cuda.empty_cache()
                        _free_gb = _torch_flux_cleanup.cuda.mem_get_info()[0] / 1024**3
                        _log('INFO', 'Stage 3.5', f'VRAM after FLUX cleanup: {_free_gb:.1f}GB free')
                    except Exception as _exc:  # noqa: BLE001 — torch raises its own RuntimeError tree from CUDA calls
                        _zyg_log.warning('post-FLUX VRAM reclaim incomplete: %s', _exc)
        finally:
            if _sch_fw_active and _sch_fw is not None:
                try:
                    _sch_fw.release_pipe_slot()
                except Exception as _exc:  # noqa: BLE001 — the worker client wraps socket, pickle and server-side errors
                    _zyg_log.warning(
                        'FLUX worker pipe slot not released — the next run may queue behind it: %s',
                        _exc,
                    )
            if _sch_gpu_lock_held:
                try:
                    from zyg_workflows import controlnet_service as _cns_lock_rel
                except ImportError:
                    _cns_lock_rel = None
                _rel_flux = gui_state._FLUX_PIPELINE_CACHE
                _rel_cn = gui_state._CN_PIPE_CACHE
                gui_state._FLUX_PIPELINE_CACHE = None
                gui_state._CN_PIPE_CACHE = None
                try:
                    _sch_backend.release_scholarly_gpu_lock(
                        pipeline_id,
                        pipe=_rel_flux,
                        cn_pipe=_rel_cn,
                        cn_service=_cns_lock_rel,
                        log_fn=lambda m: _log('INFO', 'Stage 3.5', m),
                        skip_vram_teardown=(_rel_flux is None and _rel_cn is None),
                    )
                except Exception as _lock_rel_e:
                    _log('WARNING', 'Stage 3.5', f'SCHOLARLY_GPU_LOCK release failed: {_lock_rel_e}')
    else:
        _log('INFO', 'Stage 3.5', 'FLUX model not yet fully downloaded — skipping AI image generation')
    ctx._flux_generated_paths = _flux_generated_paths
    ctx._flux_image_meta = _flux_image_meta
    ctx._sch_family_label = _sch_family_label
