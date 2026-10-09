# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4 step 2, part two: the prop sweep and the 4b/4c/4d clip polish passes.

Extracted from `stage_04_wan_generate.generate_wan_clips` (622 lines, twice the
300-line cap). Each pass keeps its own log channel ('Stage 4b', 'Stage 4c',
'Stage 4d'), its `_set_stage`/`_complete_stage` pair and its non-fatal
error handling exactly as the monolith had them: nothing in this file may fail a
run, only degrade the clips.

Every pass takes the `WanClipRun` built by `generate_wan_clips`, mutates
`wan_results` in place where the original did (`_wan_results[:] = …`) and
returns the rebuilt `wan_by_idx`, which is what the stage finally returns.
"""

from __future__ import annotations

import logging as _zyg_logging
import os
import time

from zyg_workflows import paths
from zyg_workflows.bin import exe

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')


def record_prop_verdict(run, sam3, pp_state, result) -> None:
    """Measure one WAN clip's prop persistence and record the verdict in `pp_state`.

    `result` is one WAN result dict; its `index` selects the scene whose `props`
    must stay visible. A clip with no index, no scene or no props is skipped
    silently. The verdict is ADVISORY: a SAM3 failure records 'unverified' and a
    measurement records 'measured' with a per-prop presence fraction — neither
    is ever fatal.
    """
    try:
        _pi = int(result.get('index', -1))
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('WAN result with a non-numeric index skipped: %s', _exc)
        return
    if not (0 <= _pi < len(run.scenes)):
        return
    _pprops = [str(_p).strip() for _p in (run.scenes[_pi].get('props') or []) if str(_p).strip()]
    if not _pprops:
        return
    _pclip = result.get('path') or ''
    _pp_t0 = time.time()
    _pp_rep = None
    try:
        _pp_rep = sam3.prop_persistence(
            _pclip,
            _pprops,
            log_fn=lambda m: run.log('INFO', 'Stage 4', m),
        )
    except Exception as _pp_call_e:
        run.log(
            'WARNING',
            'Stage 4',
            f'prop_persistence failed for scene {_pi + 1}: {_pp_call_e}',
        )
    _pp_el = time.time() - _pp_t0
    if _pp_rep is None:
        # None = unverified — never a pass, never a fail
        pp_state[_pi] = {'status': 'unverified', 'props': _pprops}
        run.log(
            'INFO',
            'Stage 4',
            f'Prop persistence scene {_pi + 1} ({os.path.basename(_pclip) or "no clip"}): unverified ({_pp_el:.1f}s)',
        )
        return
    _pv = {
        _ph: {
            'presence_frac': _pd.get('presence_frac'),
            'persistent': bool(_pd.get('persistent')),
        }
        for _ph, _pd in _pp_rep.items()
        if _ph != '_frames'
    }
    pp_state[_pi] = {'status': 'measured', 'verdicts': _pv}
    _pp_miss = [_ph for _ph, _pd in _pv.items() if not _pd['persistent']]
    run.log(
        'INFO',
        'Stage 4',
        f'Prop persistence scene {_pi + 1} ({os.path.basename(_pclip)}): '
        + ', '.join(f'{_ph}={_pd["presence_frac"]}' for _ph, _pd in _pv.items())
        + (f' — NOT persistent: {", ".join(_pp_miss)}' if _pp_miss else ' — all persistent')
        + f' ({_pp_el:.1f}s)',
    )


def sweep_prop_persistence(run, wan_results) -> None:
    """Advisory SAM3 sweep: do the scenes' props stay on screen in their clip?

    The single insertion point for every WAN completion path (skip, chained,
    independent, and both `wan_video_service` internal routes, which return the
    same dicts written to wan_clips/wan_manifest.json). Verdicts land in
    `run.job['_prop_persistence']` keyed by scene index and are logged; they are
    never fatal. `ZYG_PROP_GATE=0` skips the sweep, and an unavailable SAM3
    records every prop scene as 'unverified'.
    """
    try:
        _pp_gate_on = os.environ.get('ZYG_PROP_GATE', '1').strip().lower() not in (
            '0',
            'false',
            'no',
            'off',
        )
        _pp_scene_idxs = [_si for _si, _sc in enumerate(run.scenes) if (_sc.get('props') or [])]
        if not _pp_gate_on:
            if _pp_scene_idxs:
                run.log(
                    'INFO',
                    'Stage 4',
                    'Prop-persistence gate disabled (ZYG_PROP_GATE=0) — sweep skipped',
                )
        elif _pp_scene_idxs and wan_results:
            _sam3_pp = None
            _sam3_ok, _sam3_why = False, 'not checked'
            try:
                from zyg_workflows import sam3_service as _sam3_pp

                # available() first — cheap file checks, no worker spawn
                _sam3_ok, _sam3_why = _sam3_pp.available()
            except Exception as _sam3_imp_e:
                _sam3_ok, _sam3_why = False, f'import failed: {_sam3_imp_e}'
            _pp_state = run.job.setdefault('_prop_persistence', {})
            if not _sam3_ok:
                # No run_ledger/run_logbook in this file — log-only fallback note.
                run.log(
                    'WARNING',
                    'Stage 4',
                    f'Prop-persistence gate: SAM3 unavailable ({_sam3_why}) — '
                    f'{len(_pp_scene_idxs)} scene(s) with props recorded as unverified',
                )
                for _si in _pp_scene_idxs:
                    _pp_state[_si] = {
                        'status': 'unverified',
                        'props': list(run.scenes[_si].get('props') or []),
                    }
            else:
                for _pr in wan_results:
                    record_prop_verdict(run, _sam3_pp, _pp_state, _pr)
    except Exception as _pp_sweep_e:
        run.log('WARNING', 'Stage 4', f'Prop-persistence sweep failed (non-fatal): {_pp_sweep_e}')


def run_object_tracking(run, wan_results, wan_meta, wan_by_idx):
    """Stage 4b: hand the clips to `object_track_service`, in place.

    Replaces the contents of `wan_results` with the service's output and returns
    the rebuilt `wan_by_idx`; a missing service or any failure is a warning and
    returns `wan_by_idx` untouched.
    """
    run.set_stage('Object Tracking')
    try:
        from zyg_workflows import object_track_service as _ots_v

        _ots_result = _ots_v.process_clips(
            wan_results,
            wan_meta,
            run.out_dir,
            log_fn=lambda m: run.log('INFO', 'Stage 4b', m),
        )
        wan_results[:] = _ots_result
        wan_by_idx = {r['index']: r['path'] for r in wan_results}
        _n_ot = sum(1 for r in wan_results if r.get('tracked'))
        run.log('INFO', 'Stage 4b', f'Object tracking: {_n_ot}/{len(wan_results)} clip(s) processed')
    except ImportError as _ots_imp:
        run.log('WARNING', 'Stage 4b', f'object_track_service unavailable ({_ots_imp}) — skipped')
    except Exception as _ot_e:
        run.log('WARNING', 'Stage 4b', f'Object tracking failed (non-fatal): {_ot_e}')
    run.complete_stage('Object Tracking')
    return wan_by_idx


def run_temporal_repair(run, wan_results, wan_by_idx):
    """Stage 4c: RIFE 2× neural interpolation over the clips, in place.

    Replaces the contents of `wan_results` with the interpolated clips and
    returns the rebuilt `wan_by_idx`; a missing service or any failure is a
    warning and returns `wan_by_idx` untouched.
    """
    run.set_stage('Temporal Repair')
    try:
        from zyg_workflows import rife_service as _rs_v

        _n_rife_in = len(wan_results)
        wan_results[:] = _rs_v.interpolate_clips(
            wan_results,
            run.out_dir,
            log_fn=lambda m: run.log('INFO', 'Stage 4c', m),
        )
        wan_by_idx = {r['index']: r['path'] for r in wan_results}
        _n_rife = sum(1 for r in wan_results if r.get('rife_pass') not in (None, 'skipped'))
        run.log('INFO', 'Stage 4c', f'Temporal repair: {_n_rife}/{_n_rife_in} clip(s) interpolated')
    except ImportError as _rs_imp:
        run.log('WARNING', 'Stage 4c', f'rife_service unavailable ({_rs_imp}) — temporal repair skipped')
    except Exception as _rs_e:
        run.log('WARNING', 'Stage 4c', f'Temporal repair failed (non-fatal): {_rs_e}')
    run.complete_stage('Temporal Repair')
    return wan_by_idx


def extract_clip_frames(run, wclip, frames_dir) -> None:
    """ffmpeg-extract every frame of `wclip` into `frames_dir` as frame_%05d.png.

    Raises RuntimeError when ffmpeg exits non-zero, which the caller turns into
    a per-clip warning.
    """
    _ex = run.sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-i',
            wclip,
            os.path.join(frames_dir, 'frame_%05d.png'),
        ],
        capture_output=True,
        timeout=120,
    )
    if _ex.returncode != 0:
        raise RuntimeError('frame extraction failed')


def enhance_frames(upscaler, frames_dir, out_dir) -> int:
    """ESRGAN every frame in `frames_dir` 4× and write it to `out_dir` at 1080p.

    832×480 → ~3328×1920 through the upscaler, then LANCZOS down to 1920×1080
    under the same basename. Returns how many frames were written.
    """
    import glob as _gglob

    _frames = sorted(_gglob.glob(os.path.join(frames_dir, 'frame_*.png')))
    import cv2 as _cv2_esr

    for _fp in _frames:
        _img_cv = _cv2_esr.imread(_fp, _cv2_esr.IMREAD_COLOR)
        _out_img, _ = upscaler.enhance(_img_cv, outscale=4)
        # Scale down to 1920×1080 (LANCZOS)
        _out_1080 = _cv2_esr.resize(_out_img, (1920, 1080), interpolation=_cv2_esr.INTER_LANCZOS4)
        _cv2_esr.imwrite(os.path.join(out_dir, os.path.basename(_fp)), _out_1080)
    return len(_frames)


def reencode_frames(run, frames_dir, dest):
    """Re-encode the upscaled frames in `frames_dir` to x264 MP4 at `dest`.

    Returns the completed ffmpeg process so the caller can check the rc and the
    output size before replacing anything.
    """
    return run.sp_video.run(
        [
            exe('ffmpeg'),
            '-y',
            '-framerate',
            '24',
            '-i',
            os.path.join(frames_dir, 'frame_%05d.png'),
            '-c:v',
            'libx264',
            '-preset',
            'slow',
            '-crf',
            '17',
            '-pix_fmt',
            'yuv420p',
            dest,
        ],
        capture_output=True,
        timeout=300,
    )


def upscale_one_clip(run, upscaler, wclip) -> bool:
    """Upscale one WAN clip to 1080p in place; True when the clip was replaced.

    Extract → enhance → re-encode, and only a non-empty re-encode that exited 0
    replaces the original. Both scratch directories are always removed, and any
    failure is a 'Stage 4d' warning rather than an exception, so one bad clip
    never stops the pass.
    """
    _esr_tmp_dir = wclip + '_esr_frames'
    _esr_out_dir = wclip + '_esr_out'
    os.makedirs(_esr_tmp_dir, exist_ok=True)
    os.makedirs(_esr_out_dir, exist_ok=True)
    try:
        extract_clip_frames(run, wclip, _esr_tmp_dir)
        enhance_frames(upscaler, _esr_tmp_dir, _esr_out_dir)
        _esr_reenc = wclip + '_esr.mp4'
        _re = reencode_frames(run, _esr_out_dir, _esr_reenc)
        if _re.returncode == 0 and os.path.exists(_esr_reenc) and os.path.getsize(_esr_reenc) > 1000:
            os.replace(_esr_reenc, wclip)
            return True
        run.log(
            'WARNING',
            'Stage 4d',
            f'ESRGAN re-encode failed for {os.path.basename(wclip)}',
        )
    except Exception as _esr_clip_e:
        run.log(
            'WARNING',
            'Stage 4d',
            f'ESRGAN failed for clip {os.path.basename(wclip)}: {_esr_clip_e}',
        )
    finally:
        import shutil as _sh_esr

        _sh_esr.rmtree(_esr_tmp_dir, ignore_errors=True)
        _sh_esr.rmtree(_esr_out_dir, ignore_errors=True)
    return False


def run_esrgan_upscale(run, wan_results, wan_by_idx):
    """Stage 4d: ESRGAN-sharpen every WAN clip from 832p to 1080p.

    Loads RealESRGAN x4plus once, upscales each clip in place and returns the
    re-synced `wan_by_idx`. A missing model file, a missing dependency or any
    failure is a warning: the clips are then left as WAN produced them.
    """
    run.set_stage('ESRGAN Upscale')
    _esrgan_model = str(paths.ZYG_REALESRGAN_ROOT / 'RealESRGAN_x4plus.pth')
    _esrgan_ok = os.path.exists(_esrgan_model)
    if not _esrgan_ok:
        run.log('WARNING', 'Stage 4d', f'ESRGAN model not found at {_esrgan_model} — upscale skipped')
    else:
        try:
            import torch as _esr_torch
            from basicsr.archs.rrdbnet_arch import RRDBNet as _RRDBNet
            from realesrgan import RealESRGANer as _RealESRGANer

            _esr_model_obj = _RRDBNet(
                num_in_ch=3,
                num_out_ch=3,
                num_feat=64,
                num_block=23,
                num_grow_ch=32,
                scale=4,
            )
            _upscaler = _RealESRGANer(
                scale=4,
                model_path=_esrgan_model,
                model=_esr_model_obj,
                tile=512,
                tile_pad=10,
                pre_pad=0,
                half=True,
            )
            _n_esr = 0
            for _wr in wan_results:
                _wclip = _wr.get('path', '')
                if not (_wclip and os.path.exists(_wclip)):
                    continue
                if upscale_one_clip(run, _upscaler, _wclip):
                    _n_esr += 1

            # Rebuild index after upscale (paths unchanged, but re-sync)
            wan_by_idx = {r['index']: r['path'] for r in wan_results}
            run.log(
                'INFO',
                'Stage 4d',
                f'ESRGAN: {_n_esr}/{len(wan_results)} WAN clip(s) upscaled to 1080p',
            )

            # Free ESRGAN from VRAM
            del _upscaler, _esr_model_obj
            import gc as _gc_esr

            _gc_esr.collect()
            _esr_torch.cuda.empty_cache()
        except ImportError as _esr_imp:
            run.log('WARNING', 'Stage 4d', f'ESRGAN dependencies unavailable ({_esr_imp}) — upscale skipped')
        except Exception as _esr_e:
            run.log('WARNING', 'Stage 4d', f'ESRGAN stage failed (non-fatal): {_esr_e}')
    run.complete_stage('ESRGAN Upscale')
    return wan_by_idx
