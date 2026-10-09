# SPDX-FileCopyrightText: 2026 Zygomatic
# SPDX-License-Identifier: AGPL-3.0-or-later
"""The Stage 3.5 slot loop and everything after it: reviews, repair, upscale, manifest.

The two halves of `stage_11c_flux_image_loop` that follow the setup, in source
order and with their statements unchanged:

* `run_slot_loop` — `for _fi in range(_n_flux_images):` with its two stop
  checks and its `generate_one` call, the throughput estimate, the VLM QC and
  typography completion reports, the per-slot gate outcomes
  (`pipeline_state['slot_gate_outcomes']`) and the era / retry-ladder receipts;
* `finish_flux_stage` — Stage 3.6 FLUX Fill repair, the IPAdapter/ControlNet
  teardown, the FluxWorker boundary release, the Stage 3.5 Real-ESRGAN upscale,
  the image manifest and the `if not _sch_fw_active:` FLUX unload.

Both read their frame off `fs`, the `FluxLoopState` the skeleton built and
`stages_37_54_flux_setup` filled. `run_slot_loop` rebinds nothing that crosses
out — it appends to `fs._flux_generated_paths` in place, as the loop always did.
`finish_flux_stage` rebinds three names the `ctx` tail of the stage reads, and
writes each onto `fs` in the same statement:

    _flux_image_meta = fs._flux_image_meta = _ffs.repair_batch(...)

`_gc_flux` is the module-level alias of `gc` (it was `import gc as _gc_flux` in
the middle of the setup block; `gc` is interpreter state, not per-import state).
`_torch_flux` is `fs._torch_flux`, imported by `setup_flux_prelude`.

See `SPLIT_LOG.md` for the full list of spots where this was not a pure move.

2026-10-09: `run_slot_loop` was 315 lines, over the 300-line cap. Its six stages
— the render loop, the throughput estimate, the VLM render-gate and typography
reports, the per-slot outcomes and the era / retry-ladder receipts — now live in
`stages_37_54_flux_loop_reports`, which this module imports; the loop itself is
the call order. `finish_flux_stage` is unchanged.
"""

import gc as _gc_flux
import json
import logging as _zyg_logging
import os

from zyg_workflows import gui_state
from zyg_workflows import paths
from zyg_workflows.pipeline_config import (
    _FLUX_LORA_PATH,
)
from zyg_workflows.pipeline_scholarly import (
    _smoke_cap,
)
from zyg_workflows.runtime import (
    _ams_iso,
)
from zyg_workflows.scholarly import stages_37_54_flux_loop_reports as _reports

# The monolith's logger name, not `__name__`, so the `suppressed …` debug lines
# of one run all stay under `zyg_workflows.pipeline_scholarly`.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_scholarly')


def run_slot_loop(fs, ctx):
    """Render every slot, then report what each gate did to it.

    Six stages, in the order the loop always ran them; every one of them is a
    function of `stages_37_54_flux_loop_reports`.
    """
    _elapsed_s = _reports.render_slots(fs, ctx)
    _reports.report_throughput(fs, ctx, _elapsed_s)
    _reports.report_vlm_gate(fs, ctx)
    _reports.report_typography(fs, ctx)
    # ── Gate outcomes, BY SLOT NUMBER ──────────────────────
    _so = _reports.slot_outcomes(
        fs._slot_review,
        fs._shipped_flagged,
        qc_enabled=fs._VLM_QC_ENABLED,
        era_enabled=fs._VLM_ERA_ENABLED,
    )
    _reports.report_slot_outcomes(fs, ctx, _so)
    _reports.report_era_and_ladder(fs, ctx, _so)


def finish_flux_stage(fs, ctx):
    """Repair, tear down, upscale, write the manifest and unload FLUX."""
    _cn_pipe = fs._cn_pipe
    _cns = fs._cns
    _debug = ctx._debug
    _done = ctx._done
    _essay_title_for_prompt = ctx._essay_title_for_prompt
    _flux_generated_paths = fs._flux_generated_paths
    _flux_image_meta = fs._flux_image_meta
    _flux_images_dir = fs._flux_images_dir
    _flux_pipe = fs._flux_pipe
    _ipa = fs._ipa
    _ipa_ready = fs._ipa_ready
    _log = ctx._log
    _sch_family_label = fs._sch_family_label
    _sch_fw_active = fs._sch_fw_active
    _sch_skip_local_flux = ctx._sch_skip_local_flux
    _stage_start = ctx._stage_start
    _torch_flux = fs._torch_flux
    pipeline_id = ctx.pipeline_id
    topic = ctx.topic
    # Hand QC no longer reports here: it moved to Stage 3.7,
    # after FLUX unloads, because inside this stage the card is
    # full and the judge could never run. See that block.

    # ── Stage 3.6: FLUX Fill repair pass ────────────────────────────────
    # Run inpainting on images that still have anatomy defects after
    # the QA retry loop.  Uses MediaPipe masks + FluxFillPipeline (Tier 2)
    # or cv2 TELEA (Tier 1 fallback).
    # Runs BEFORE FLUX unload so Fill can share the VRAM budget.
    # The Comfy/Qwen path used to raise ImportError here before the
    # service was even imported (P-10) — which blocked exactly the
    # licence-clean tier (Apache-2.0 Qwen InstantX inpaint via
    # ComfyUI, hand_fixer_qwen_inpaint.json). Now only the
    # in-process FLUX-Fill tier is suppressed on that path; the
    # Qwen inpaint tier runs, with TELEA as the fallback.
    try:
        _stage_start('Stage 3.6: Anatomy Repair')
        from zyg_workflows import flux_fill_service as _ffs

        _flux_image_meta = fs._flux_image_meta = _ffs.repair_batch(
            _flux_image_meta,
            qa_threshold=0.72,
            use_flux_fill=not _sch_skip_local_flux,
            log_fn=lambda m: _log('INFO', 'Stage 3.6', m),
        )
        # Rebuild generated paths from updated meta (paths may have changed)
        _flux_generated_paths = fs._flux_generated_paths = [
            m['path'] for m in _flux_image_meta if os.path.exists(m.get('path', ''))
        ]
        _n_repaired = sum(1 for m in _flux_image_meta if m.get('repair_pass'))
        _done('Stage 3.6: Anatomy Repair', {'repaired': _n_repaired, 'total': len(_flux_image_meta)})
        _debug('Stage 3.5', f'Stage 3.6 complete: {_n_repaired} image(s) repaired')
    except ImportError as _ffs_ie:
        _log(
            'WARNING',
            'Stage 3.6',
            f'flux_fill_service not importable — Stage 3.6 anatomy repair skipped ({_ffs_ie})',
        )
        # _stage_start already ran: close the timeline entry so
        # the stage never shows as "running" forever.
        _done('Stage 3.6: Anatomy Repair', {'skipped': True, 'reason': 'import'})
    except Exception as _ffs_e:
        _log('WARNING', 'Stage 3.5', f'Stage 3.6 repair pass failed (non-fatal): {_ffs_e}')
        _done('Stage 3.6: Anatomy Repair', {'skipped': True, 'reason': str(_ffs_e)[:120]})

    # ── Tear down IPAdapter + ControlNet before FLUX unload ─────────────
    if _ipa_ready and _ipa is not None and _flux_pipe is not None:
        try:
            _ipa.teardown(_flux_pipe, log_fn=lambda m: _log('INFO', 'Stage 3.5', m))
        except Exception as _ipa_td_e:
            _debug('Stage 3.5', f'IPAdapter teardown warning: {_ipa_td_e}', level='WARN')

    if _cn_pipe is not None and _cns is not None:
        try:
            _cns.teardown(_cn_pipe, log_fn=lambda m: _log('INFO', 'Stage 3.5', m))
            _cn_pipe = fs._cn_pipe = None
        except Exception as _cns_td_e:
            _debug('Stage 3.5', f'ControlNet teardown warning: {_cns_td_e}', level='WARN')

    # ── RAM peak fix: release the FLUX worker at this stage boundary ────
    # Idling through ESRGAN + Ken Burns kept the FLUX stack resident and
    # stacked its heap under the 16-thread frame buffers — the pattern
    # behind both 2026-07-05 OOM kills (09:51 and 11:11). No later stage
    # of this pipeline uses FLUX; the next batch item reloads on demand.
    try:
        from zyg_workflows import scholarly_stills_backend as _ssb_rel35

        _fw_rel35 = _ssb_rel35.ScholarlyFluxWorker.get()
        if _fw_rel35.is_running():
            _fw_rel35.emergency_stop(log_fn=lambda m: _log('INFO', 'Stage 3.5', m))
            _log('INFO', 'Stage 3.5', 'FluxWorker released at stage boundary (RAM peak fix)')
        import gc as _gc_rel35

        _gc_rel35.collect()
        import ctypes as _ct_rel35

        _ct_rel35.CDLL('libc.so.6').malloc_trim(0)
    except Exception as _fw_rel_e35:
        _log('WARNING', 'Stage 3.5', f'FluxWorker boundary release skipped: {_fw_rel_e35}')

    # ── Stage 3.5 post-processing: Real-ESRGAN upscale ─────────────────
    # ESRGAN only needs ~200 MB, so it runs in smoke too (S-01): the
    # smoke stills used to reach Stage 6 unscaled and the Ken Burns
    # renderer bicubic-upsampled them 3.75× without a word.
    # The scale follows the SOURCE width, i.e. the still family:
    #   qwen  1664×928  → 2× → 3328×1856   (RealESRGAN_x2.pth)
    #   flux  1280×720  → 4× → 5120×2880   (RealESRGAN_x4plus.pth)
    # Either way the 1920×1080 Ken Burns crop is a downscale of the
    # upscaled frame — but the detail ceiling is what the renderer
    # painted, not what ESRGAN invents: 2× on a 1664-wide source
    # keeps more real detail than 4× on a 1280-wide one (P-05).
    if _flux_generated_paths:
        try:
            import cv2 as _cv2_esr35
            import realesrgan as _realesrgan35
            from basicsr.archs.rrdbnet_arch import RRDBNet as _RRDBNet35

            # Probe the first surviving still for its size.
            _esr_src_w35, _esr_src_h35 = 0, 0
            for _im35p in _flux_image_meta:
                _p35p = _im35p.get('path', '')
                if _p35p and os.path.exists(_p35p):
                    _probe35 = _cv2_esr35.imread(_p35p, _cv2_esr35.IMREAD_COLOR)
                    if _probe35 is not None:
                        _esr_src_h35, _esr_src_w35 = _probe35.shape[:2]
                        break
            _esr_scale35 = 2 if _esr_src_w35 >= 1664 else 4
            _esr_weights35 = str(
                paths.ZYG_REALESRGAN_ROOT / ('RealESRGAN_x2.pth' if _esr_scale35 == 2 else 'RealESRGAN_x4plus.pth')
            )
            _esr_mdl35 = _RRDBNet35(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=_esr_scale35,
            )
            _esrgan35 = _realesrgan35.RealESRGANer(
                scale=_esr_scale35,
                model_path=_esr_weights35,
                model=_esr_mdl35,
                half=True,
            )
            _log(
                'INFO',
                'Stage 3.5',
                f'Real-ESRGAN {_esr_scale35}× loaded — source '
                f'{_esr_src_w35}×{_esr_src_h35} ({_sch_family_label}) → '
                f'{_esr_src_w35 * _esr_scale35}×{_esr_src_h35 * _esr_scale35}'
                f'{" [smoke]" if _smoke_cap() else ""}',
            )
            _esr_upgraded = 0
            for _im35 in _flux_image_meta:
                _src35 = _im35.get('path', '')
                if not _src35 or not os.path.exists(_src35):
                    continue
                try:
                    _esr_in35 = _cv2_esr35.imread(_src35, _cv2_esr35.IMREAD_COLOR)
                    _esr_out35, _ = _esrgan35.enhance(_esr_in35, outscale=_esr_scale35)
                    _base35, _ext35 = os.path.splitext(_src35)
                    _esr_p35 = _base35 + f'_{_esr_scale35}x' + _ext35
                    _cv2_esr35.imwrite(
                        _esr_p35,
                        _esr_out35,
                        [_cv2_esr35.IMWRITE_JPEG_QUALITY, 95],
                    )
                    _im35['path'] = _esr_p35
                    _esr_upgraded += 1
                except Exception as _esr_img35_e:
                    _log(
                        'WARNING',
                        'Stage 3.5',
                        f'ESRGAN failed for {os.path.basename(_src35)}: {_esr_img35_e}',
                    )
            # Rebuild paths so Stage 6 gets the upscaled sources
            _flux_generated_paths = fs._flux_generated_paths = [
                m['path'] for m in _flux_image_meta if os.path.exists(m.get('path', ''))
            ]
            _log(
                'INFO',
                'Stage 3.5',
                f'Real-ESRGAN {_esr_scale35}× complete: {_esr_upgraded}/{len(_flux_image_meta)} '
                f'images upscaled to {_esr_src_w35 * _esr_scale35}×{_esr_src_h35 * _esr_scale35}',
            )
            # Unload ESRGAN to free VRAM before TTS
            try:
                _esrgan35.model.cpu()
            except Exception as _exc:  # noqa: BLE001 — Real-ESRGAN and torch raise their own hierarchy
                _zyg_log.warning(
                    'Real-ESRGAN not moved off the GPU — its VRAM stays held through TTS: %s',
                    _exc,
                )
            del _esrgan35, _esr_mdl35
            _torch_flux.cuda.empty_cache()
        except ImportError as _esr35_ie:
            _log('WARNING', 'Stage 3.5', f'Real-ESRGAN not available — skipping upscale: {_esr35_ie}')
        except Exception as _esr35_e:
            _log('WARNING', 'Stage 3.5', f'Real-ESRGAN upscale failed (non-fatal): {_esr35_e}')

    # Write image manifest JSON to output dir for asset manager browsing
    _manifest_path = os.path.join(_flux_images_dir, 'flux_manifest.json')
    try:
        with open(_manifest_path, 'w') as _mf:
            json.dump(
                {
                    'pipeline_id': pipeline_id,
                    'topic': topic,
                    'essay_title': _essay_title_for_prompt,
                    'generated_at': _ams_iso(),
                    'model': _sch_family_label,
                    'image_count': len(_flux_image_meta),
                    'images': _flux_image_meta,
                },
                _mf,
                indent=2,
            )
        _log('INFO', 'Stage 3.5', f'Image manifest written: {_manifest_path}')
    except Exception as _me:
        _log('WARNING', 'Stage 3.5', f'Could not write manifest: {_me}')

    if not _sch_fw_active:
        # Fully unload FLUX to free ~24 GB for TTS.
        # CRITICAL order: move tensors to CPU first, THEN release Python refs,
        # THEN gc.collect(), THEN empty_cache(). Calling empty_cache() before gc
        # is ineffective because PyTorch's reserved pool still holds pages for
        # live tensor refs. Moving to CPU first ensures the CUDA allocator sees
        # the pages freed even when GC lags (e.g. exception tracebacks holding refs).
        try:
            if gui_state._FLUX_PIPELINE_CACHE is not None and _FLUX_LORA_PATH:
                gui_state._FLUX_PIPELINE_CACHE.unload_lora_weights()
        except Exception as _exc:  # noqa: BLE001 — diffusers raises its own hierarchy
            _zyg_log.debug(
                'FLUX LoRA weights not unloaded — the whole pipeline is dropped next: %s',
                _exc,
            )
        _flux_unload_target = gui_state._FLUX_PIPELINE_CACHE
        _had_local_flux_unload = _flux_unload_target is not None
        gui_state._FLUX_PIPELINE_CACHE = None
        gui_state._CN_PIPE_CACHE = None
        try:
            if _flux_unload_target is None:
                raise ValueError('no in-process FLUX loaded')
            for _flux_comp_attr in ('transformer', 'vae', 'text_encoder', 'text_encoder_2'):
                _flux_comp = getattr(_flux_unload_target, _flux_comp_attr, None)
                if _flux_comp is not None:
                    try:
                        _flux_comp.to('cpu')
                    except Exception as _exc:  # noqa: BLE001 — torch raises its own hierarchy from .to()
                        _zyg_log.debug(
                            'FLUX %s not moved to CPU — the allocator may keep its pages: %s',
                            _flux_comp_attr,
                            _exc,
                        )
            del _flux_unload_target
        except Exception as _exc:  # noqa: BLE001 — the deliberate ValueError plus any diffusers error
            _zyg_log.debug(
                'no in-process FLUX to move to CPU before the drop: %s',
                _exc,
            )
        try:
            del _flux_pipe
        except NameError as _exc:
            _zyg_log.debug('_flux_pipe was never bound — nothing to drop: %s', _exc)
        try:
            del _cn_pipe
        except NameError as _exc:
            _zyg_log.debug('_cn_pipe was never bound — nothing to drop: %s', _exc)
        _gc_flux.collect()
        _torch_flux.cuda.empty_cache()
        import time as _t_flux_unload

        _t_flux_unload.sleep(3)
        _gc_flux.collect()
        _torch_flux.cuda.empty_cache()  # second pass after GC settles
        # P-13: this said "FLUX unloaded" on Qwen runs where no
        # in-process FLUX was ever loaded (the smoke harness's A8
        # then "passed" on it).
        _log(
            'INFO',
            'Stage 3.5',
            'FLUX unloaded — VRAM freed for TTS'
            if _had_local_flux_unload
            else f'No in-process FLUX to unload ({_sch_family_label} via Comfy) — torch cache cleared for TTS',
        )
        _debug(
            'Stage 3.5',
            f'VRAM after FLUX unload: {_torch_flux.cuda.mem_get_info()[0] / 1024**3:.1f}GB free',
        )
