# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 2 of the video pipeline: stills in, stills generated, stills gated.

Three functions, lines 467-1114 of `pipeline_video._run_video_pipeline` at
770c30a, verbatim:

* `stage_02_image_prep` (467-993) — copy the uploaded images in, then generate
  every missing scene still: ComfyUI submit or local FLUX (style LoRA,
  ControlNet, IP-Adapter, Real-ESRGAN upscale), and the GPU-lock dance around
  it. This is the one stage that takes `_GPU_PIPELINE_LOCK` for FLUX, so it
  reads and writes `ctx._flux_gpu_acq_v` instead of a local: the driver's
  `except`/`finally` release the lock off that field. The image work itself —
  the copy, the Comfy batch, the FLUX load, the services, the per-scene render
  and the teardown — moved to `stage_02_images_flux.py` when the function went
  over the 300-line cap; what is left here is the control flow, the GPU lock and
  the `ZYG_FORCE_FLUX_LOCAL` read whose settings entry names this file.
* `stage_02c_still_gate` (995-1031) — the blank/QA gate that aborts the run
  before WAN ever loads.
* `stage_02b_anatomy_repair` (1033-1114) — the MediaPipe anatomy QA pass.
"""

import os

from zyg_workflows import paths
from zyg_workflows.runtime import _GPU_PIPELINE_LOCK
from zyg_workflows.vram_manager import _deep_unload_flux_pipeline_cache, _release_pipeline_vram

from zyg_workflows.video_stages import stage_02_images_flux as _st2_flux
from zyg_workflows.video_stages.context import StageExit

import logging as _zyg_logging

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


def stage_02_image_prep(ctx):
    _fail_stage = ctx._fail_stage
    _log = ctx._log
    _set_stage = ctx._set_stage
    _vscfg = ctx._vscfg
    directive = ctx.directive
    image_paths = ctx.image_paths
    job = ctx.job
    n_scenes = ctx.n_scenes
    out_dir = ctx.out_dir
    scenes = ctx.scenes
    visual_style = ctx.visual_style
    # ── Stage 2: Image Prep ──────────────────────────────────────────────
    _set_stage('AI Image Generation')
    _log('INFO', 'Stage 2', f'Preparing images: {len(image_paths)} uploaded, need {n_scenes}')

    images_dir = os.path.join(out_dir, 'images')
    os.makedirs(images_dir, exist_ok=True)

    # Copy/normalise uploaded images
    scene_images = _st2_flux.copy_uploaded_stills(image_paths, n_scenes, images_dir)
    run = _st2_flux.FluxStillRun(
        log=_log,
        images_dir=images_dir,
        out_dir=out_dir,
        scenes=scenes,
        directive=directive,
        visual_style=visual_style,
        vscfg=_vscfg,
        job=job,
        n_scenes=n_scenes,
        scene_images=scene_images,
    )

    # FLUX-generate missing scenes
    n_missing = n_scenes - len(scene_images)
    if n_missing > 0:
        _log('INFO', 'Stage 2', f'Generating {n_missing} images with FLUX Dev (hero stills) — style: {visual_style}')
        _flux_model_path = str(paths.ZYG_FLUX_ROOT / 'flux1-schnell')
        _flux_ok = os.path.isdir(_flux_model_path)

        # ComfyUI primary: generate stills on the Comfy server so we do not load a
        # second in-process FLUX stack while ComfyUI already holds ~35 GB VRAM.
        try:
            _st2_flux.comfy_still_batch(run, n_missing)
        except Exception as _cgs_st2_e:
            _log('WARNING', 'Stage 2', f'ComfyUI still path failed — diffusers fallback: {_cgs_st2_e}')

        n_missing = n_scenes - len(scene_images)

        _force_flux_local = os.environ.get('ZYG_FORCE_FLUX_LOCAL', '').strip().lower() in ('1', 'true', 'yes', 'on')
        _skip_local_flux = False
        try:
            from zyg_workflows import comfy_generation_service as _cgs_skip_flux

            if _cgs_skip_flux.is_available() and not _force_flux_local:
                _skip_local_flux = True
        except ImportError as _exc:
            _zyg_log.debug('comfy_generation_service unavailable, keeping the local FLUX path: %s', _exc)

        if n_missing > 0 and _flux_ok and _skip_local_flux:
            _log(
                'WARNING',
                'Stage 2',
                f'{n_missing} still(s) missing but ComfyUI primary is active — '
                'skipping in-process FLUX load (set ZYG_FORCE_FLUX_LOCAL=1 to override); '
                'blank fallback will fill gaps',
            )

        if n_missing > 0 and _flux_ok and not _skip_local_flux:
            _release_pipeline_vram('pre-FLUX', lambda m: _log('INFO', 'Stage 2', m))
            _st2_flux.wait_for_flux_vram(_log)
            _log('INFO', 'Stage 2', 'Acquiring GPU lock for FLUX…')
            ctx._flux_gpu_acq_v = _GPU_PIPELINE_LOCK.acquire(blocking=True, timeout=600)
            _log(
                'INFO',
                'Stage 2',
                f'GPU lock {"acquired" if ctx._flux_gpu_acq_v else "timeout — proceeding without lock"}',
            )
            try:
                import torch as _torch_v
                import gc as _gc_v
                from diffusers import FluxPipeline as _FluxPipeline_v

                run.torch = _torch_v
                run.gc = _gc_v
                _st2_flux.load_flux_pipeline(run, _flux_model_path, _FluxPipeline_v)
                _st2_flux.setup_quality_services(run)

                from zyg_workflows import video_flux_still_service as _vfs_local

                start_idx = len(scene_images)
                for _fi in range(n_missing):
                    scene_idx = start_idx + _fi
                    _sc_data = scenes[scene_idx] if scene_idx < len(scenes) else {}
                    _plan = _st2_flux.scene_render_plan(run, _vfs_local, _sc_data, scene_idx)
                    try:
                        _st2_flux.render_one_scene(run, _plan, scene_idx)
                    except Exception as _fe:
                        _log('WARNING', 'Stage 2', f'FLUX scene {scene_idx} failed: {_fe}')

                _st2_flux.teardown_image_services(run)
                # ── Unload FLUX to free ~20GB VRAM before WAN loads ──────
                _deep_unload_flux_pipeline_cache(log_fn=lambda m: _log('INFO', 'Stage 2', m))
                _log('INFO', 'Stage 2', 'FLUX unloaded — VRAM freed for WAN')
                if ctx._flux_gpu_acq_v:
                    _GPU_PIPELINE_LOCK.release()
                    ctx._flux_gpu_acq_v = False
                    _log('INFO', 'Stage 2', 'GPU lock released')

            except Exception as _flux_err:
                _log('WARNING', 'Stage 2', f'FLUX pipeline failed ({_flux_err}) — using blank frames')
                _flux_ok = False
                # Always free FLUX VRAM even on error to prevent bleed into next stage
                try:
                    _deep_unload_flux_pipeline_cache(log_fn=lambda m: _log('INFO', 'Stage 2', m))
                    _log('INFO', 'Stage 2', 'FLUX cleaned up after error')
                    if ctx._flux_gpu_acq_v:
                        _GPU_PIPELINE_LOCK.release()
                        ctx._flux_gpu_acq_v = False
                except Exception as _exc:
                    _zyg_log.warning('FLUX cleanup after the error failed, VRAM may bleed into Stage 4: %s', _exc)

        if len(scene_images) < n_scenes:
            _fail_stage(
                'AI Image Generation',
                f'Only {len(scene_images)}/{n_scenes} still(s) generated — Comfy/FLUX failed; blank fallback disabled.',
            )
            job['status'] = 'failed'
            job['error'] = f'Image generation incomplete ({len(scene_images)}/{n_scenes} scenes)'
            return StageExit()
    ctx.images_dir = images_dir
    ctx.scene_images = scene_images


def stage_02c_still_gate(ctx):
    _complete_stage = ctx._complete_stage
    _fail_stage = ctx._fail_stage
    _log = ctx._log
    directive = ctx.directive
    job = ctx.job
    scene_images = ctx.scene_images
    scenes = ctx.scenes
    # ── Stage 2c: Final still gate before WAN ─────────────────────────────
    try:
        from zyg_workflows import video_still_qa_service as _vsqa

        _qa_failed: list[int] = []
        for _qi, _qp in enumerate(scene_images):
            _sc_q = scenes[_qi] if _qi < len(scenes) else {}
            _flux_hint = _sc_q.get('flux_prompt') or _sc_q.get('description') or directive
            _ok_q, _score_q, _reason_q = _vsqa.check_still_complete(
                _qp,
                directive,
                _flux_hint,
                _sc_q,
                log_fn=lambda m: _log('INFO', 'Stage 2c', m),
            )
            if _ok_q:
                _log('INFO', 'Stage 2c', f'Scene {_qi + 1}: still gate pass ({_reason_q})')
            else:
                _log('WARNING', 'Stage 2c', f'Scene {_qi + 1}: still gate fail — {_reason_q}')
                _qa_failed.append(_qi + 1)

        _blank_all = all(_vsqa.is_blank_still(p) for p in scene_images if p)
        if _blank_all or _qa_failed:
            _detail = 'all stills blank' if _blank_all else f'still QA failed for scene(s): {_qa_failed}'
            _fail_stage('AI Image Generation', f'FLUX still gate failed — {_detail}. WAN aborted.')
            job['status'] = 'failed'
            job['error'] = f'Image generation QA failed: {_detail}'
            return StageExit()
    except Exception as _vsqa_e:
        _log('WARNING', 'Stage 2c', f'Still gate error: {_vsqa_e}')
        job['status'] = 'failed'
        job['error'] = f'Still QA gate error: {_vsqa_e}'
        return StageExit()

    _complete_stage('AI Image Generation')
    job['scene_images'] = scene_images
    _log('INFO', 'Stage 2', f'Image prep complete: {len(scene_images)} images ready')


def stage_02b_anatomy_repair(ctx):
    _complete_stage = ctx._complete_stage
    _log = ctx._log
    _set_stage = ctx._set_stage
    scene_images = ctx.scene_images
    scenes = ctx.scenes
    # ── Stage 2b: Anatomy Repair ──────────────────────────────────────────
    _set_stage('Anatomy Repair')
    _log('INFO', 'Stage 2b', 'Running MediaPipe anatomy QA on FLUX images…')
    try:
        import mediapipe as _mp_anat
        import cv2 as _cv2_anat

        def _quick_anatomy_qa(img_path: str):
            """Return (qa_score, issues_list) via MediaPipe hand/pose landmarks."""
            try:
                _img_bgr = _cv2_anat.imread(img_path)
                if _img_bgr is None:
                    return 1.0, []
                _img_rgb = _cv2_anat.cvtColor(_img_bgr, _cv2_anat.COLOR_BGR2RGB)
                _issues: list = []
                _penalty = 0.0
                _mph = _mp_anat.solutions.holistic
                with _mph.Holistic(static_image_mode=True, model_complexity=1, min_detection_confidence=0.5) as _hol:
                    _res = _hol.process(_img_rgb)
                    for _side, _hand_lms in (
                        ('left', _res.left_hand_landmarks),
                        ('right', _res.right_hand_landmarks),
                    ):
                        if _hand_lms is None:
                            continue
                        _lm = _hand_lms.landmark
                        _tips = [4, 8, 12, 16, 20]
                        _mcps = [2, 5, 9, 13, 17]
                        _n_ext = sum(1 for t, k in zip(_tips, _mcps) if _lm[t].y < _lm[k].y)
                        if _n_ext > 5:
                            _issues.append(f'{_side} hand: {_n_ext} extended (>5 — extra finger)')
                            _penalty += 0.35
                        _xs = [_lm[i].x for i in range(21)]
                        _ys = [_lm[i].y for i in range(21)]
                        _spread = (max(_xs) - min(_xs)) + (max(_ys) - min(_ys))
                        if _spread < 0.05:
                            _issues.append(f'{_side} hand: landmarks clustered (fused hand)')
                            _penalty += 0.30
                return max(0.0, 1.0 - _penalty), _issues
            except Exception:
                return 1.0, []

        _anat_meta: list = []
        for _ai, _ip in enumerate(scene_images):
            _qa_s, _qa_iss = _quick_anatomy_qa(_ip)
            _anat_meta.append(
                {
                    'path': _ip,
                    'index': _ai,
                    'qa_score': round(_qa_s, 3),
                    'qa_issues': _qa_iss,
                    'subject': (scenes[_ai].get('description', '') if _ai < len(scenes) else '')[:60],
                    'prompt': scenes[_ai].get('description', '') if _ai < len(scenes) else '',
                }
            )
            if _qa_iss:
                _log('INFO', 'Stage 2b', f'Scene {_ai}: QA={_qa_s:.2f} issues={_qa_iss}')
            else:
                _log('INFO', 'Stage 2b', f'Scene {_ai}: QA={_qa_s:.2f} ✓')

        from zyg_workflows import flux_fill_service as _ffs_v

        _anat_meta = _ffs_v.repair_batch(
            _anat_meta,
            qa_threshold=0.65,
            use_flux_fill=True,
            log_fn=lambda m: _log('INFO', 'Stage 2b', m),
        )
        _n_repaired = 0
        for _am in _anat_meta:
            _idx = _am.get('index', -1)
            if 0 <= _idx < len(scene_images) and _am.get('repair_pass'):
                scene_images[_idx] = _am['path']
                _n_repaired += 1
        _log('INFO', 'Stage 2b', f'Anatomy repair complete: {_n_repaired}/{len(scene_images)} image(s) repaired')
    except ImportError as _anat_imp:
        _log('WARNING', 'Stage 2b', f'Anatomy repair unavailable ({_anat_imp}) — skipped')
    except Exception as _anat_e:
        _log('WARNING', 'Stage 2b', f'Anatomy repair failed (non-fatal): {_anat_e}')
    _complete_stage('Anatomy Repair')
