# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4, step 2: WAN animates every still, then 4b/4c/4d polish the clips.

Driver lines 381-1000 of `pipeline_video._run_video_pipeline` at d443b3b,
verbatim: the `_detect_emotion` / `_wan_log` helpers, the blank-FLUX-image
guard, the GPU lock, Step A (the continuous-mode FLUX img2img chain), Step B
(the `_wan_meta` build), Step C (the WAN animate call, chained or batched), the
prop-persistence sweep, and Stages 4b (object tracking), 4c (RIFE temporal
repair) and 4d (ESRGAN upscale).

`generate_wan_clips` is now the orchestrator only: the work lives in
`stage_04_wan_generate_steps` (metadata, blank guard, the animate calls) and
`stage_04_wan_generate_polish` (prop sweep, 4b/4c/4d), which keep every log
line, side effect and swallowed-failure path of the original 622-line function.

`_wan_svc` is a parameter because the VRAM gate in `prepare_vram_and_services`
may already have set it to `None`; the blank-image guard sets it to `None`
again here, which is a plain rebinding of the parameter and crosses nothing.
The GPU-lock flag is written as `ctx._wan_gpu_acq_v` exactly as it was, so the
driver's `except`/`finally` see it flip the moment it does.
"""

from zyg_workflows.runtime import _GPU_PIPELINE_LOCK
from zyg_workflows.video_stages import stage_04_wan_generate_polish as _polish
from zyg_workflows.video_stages import stage_04_wan_generate_steps as _steps


def generate_wan_clips(ctx, _wan_svc, _wan_n_chained, _wan_test_frames, _wan_test_steps):
    """Animate every scene still with WAN and polish the clips; {index: path}.

    Builds the WAN metadata, aborts on an all-blank FLUX set, takes the GPU
    lock, generates the clips (chained in `continuous` scene mode, one batch
    otherwise) and then runs the advisory prop sweep and stages 4b/4c/4d. A WAN
    failure is non-fatal: the mapping comes back as far as it got and the
    pipeline falls back to static images. The GPU lock is always released.
    """
    _complete_stage = ctx._complete_stage
    _log = ctx._log
    _set_stage = ctx._set_stage
    _sp_video = ctx._sp_video
    _vscfg = ctx._vscfg
    images_dir = ctx.images_dir
    job = ctx.job
    n_scenes = ctx.n_scenes
    out_dir = ctx.out_dir
    scene_duration = ctx.scene_duration
    scene_images = ctx.scene_images
    scene_mode = ctx.scene_mode
    scenes = ctx.scenes
    visual_style = ctx.visual_style
    wan_by_idx = {}
    if _wan_svc:
        # Build flux_image_meta compatible dicts from scenes
        _wan_meta = _steps.build_wan_meta(scenes, scene_images, scene_duration)
        # ── Blank-image guard: abort WAN if all FLUX images are near-black ──
        if _steps.apply_blank_image_guard(_wan_meta, _log):
            _wan_svc = None
        _log('INFO', 'Stage 4', 'Acquiring GPU lock for WAN…')
        ctx._wan_gpu_acq_v = _GPU_PIPELINE_LOCK.acquire(blocking=True, timeout=900)
        _log(
            'INFO',
            'Stage 4',
            f'GPU lock {"acquired" if ctx._wan_gpu_acq_v else "timeout — proceeding without lock"}',
        )
        run = _steps.WanClipRun(
            log=_log,
            set_stage=_set_stage,
            complete_stage=_complete_stage,
            sp_video=_sp_video,
            vscfg=_vscfg,
            images_dir=images_dir,
            job=job,
            n_scenes=n_scenes,
            out_dir=out_dir,
            scene_images=scene_images,
            scenes=scenes,
            visual_style=visual_style,
            wan_svc=_wan_svc,
            wan_n_chained=_wan_n_chained,
            wan_test_frames=_wan_test_frames,
            wan_test_steps=_wan_test_steps,
        )
        try:
            # Smart log_fn: route WAN messages containing failure keywords to WARNING/ERROR
            _wan_log = _steps.make_wan_log(_log)

            if _wan_svc is None:
                # Blank guard (or earlier failure) set _wan_svc to None — skip all WAN work.
                _steps.note_wan_unavailable(_log, job)
                _wan_results = []
            elif scene_mode == 'continuous':
                # ── Continuous chained mode: FLUX img2img ↔ WAN per scene ────────
                _wan_results = _steps.animate_scenes_chained(run, _wan_meta, _wan_log, wan_by_idx)
            else:
                # ── Independent mode (default): generate all clips at once ────────
                _wan_results = _steps.animate_scenes_batched(run, _wan_meta, _wan_log)
                wan_by_idx = {r['index']: r['path'] for r in _wan_results}

            # ── Prop-persistence advisory sweep (SAM3, non-fatal) ─────────
            _polish.sweep_prop_persistence(run, _wan_results)
            # ── Stage 4b: Object Tracking ─────────────────────────────────
            wan_by_idx = _polish.run_object_tracking(run, _wan_results, _wan_meta, wan_by_idx)
            # ── Stage 4c: Temporal Repair (RIFE 2× neural interpolation) ──────
            wan_by_idx = _polish.run_temporal_repair(run, _wan_results, wan_by_idx)
            # ── Stage 4d: ESRGAN upscale WAN clips (832p → 1080p sharpen) ───
            wan_by_idx = _polish.run_esrgan_upscale(run, _wan_results, wan_by_idx)

        except Exception as _wan_err:
            _log('WARNING', 'Stage 4', f'WAN generation error: {_wan_err} — falling back to static images')
        finally:
            if ctx._wan_gpu_acq_v:
                _GPU_PIPELINE_LOCK.release()
                ctx._wan_gpu_acq_v = False
                _log('INFO', 'Stage 4', 'GPU lock released after WAN')

    return wan_by_idx
