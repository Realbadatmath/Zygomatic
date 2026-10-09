# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""kids_series_common.py — pictures and motion (lines 804-1094 of the pre-split file, verbatim)."""

from __future__ import annotations

import logging as _zyg_logging
from .constants import (
    os,
    shutil,
    W,
    H,
    FPS,
    KID_STYLE,
    KID_NEGATIVE,
    FFMPEG,
    _COMFY_ROOT,
    _KLEIN_DISTILLED,
    _KLEIN_BASE,
    _log_noop,
)
from .ffmpeg import _run, _NORM_VF

# channel kept from the pre-split module
_zyg_log = _zyg_logging.getLogger('zyg_workflows.kids_series_common')


# ── pictures and motion ──────────────────────────────────────────────────────


def _attest(wf, log_fn=None, run_id='', tag=''):
    """Classify every weight this graph references, through the existing gate.

    A monetised children's channel is exactly the case the licence gate was
    written for; a submit that skips it is the whole point of having it.
    """
    try:
        from zyg_workflows import licence_provenance as _lp

        return _lp.attest_licences(wf, log_fn=log_fn, run_id=run_id, tag=tag)
    except Exception as e:  # noqa: BLE001
        return {
            'ok': None,
            'error': f'{type(e).__name__}: {e}'[:200],
            'artifacts': [],
            'violations': [],
            'unknowns': [],
        }


def klein_settings():
    """(unet_name, steps, cfg) — ONE decision, taken from the disk.

    The checkpoint and the sampler settings must never come apart: a distilled
    model at cfg 4 and a base model at 4 steps are the same mistake in opposite
    directions, and both are silent — the pictures just quietly get worse.
    """
    distilled = os.path.join(_COMFY_ROOT, 'models', 'diffusion_models', _KLEIN_DISTILLED)
    if os.path.isfile(distilled):
        return _KLEIN_DISTILLED, 4, 1.0
    return _KLEIN_BASE, 18, 4.0


def _ltx_hidream(log_fn):
    """The second ComfyUI (:8189) with HiDream-O1 + LTX-2.5, or None.

    Env ``ZYG_KIDS_HIDREAM_LTX=0`` forces the klein/Wan path (the 2026-09 bench
    baseline); the default since 2026-10-02 is the new pair, because a 5 s clip
    costs 25 s there against 609 s on Wan 2.2 (measured, same box).
    """
    if os.environ.get('ZYG_KIDS_HIDREAM_LTX', '1').strip().lower() in ('0', 'false', 'no', 'off'):
        return None
    try:
        from zyg_workflows import ltx_hidream_service as LH
    except Exception as e:  # noqa: BLE001
        log_fn(f'ltx: service unavailable ({type(e).__name__}: {e}) — klein/Wan path')
        return None
    return LH if LH.ensure_up(log_fn=log_fn) else None


def render_still(prompt, out_png, *, w=W, h=H, seed=0, log_fn=None):
    """One picture.  HiDream-O1 on :8189 first (MIT, ~5 s), FLUX.2 klein as the
    fallback.  KID_STYLE in, KID_NEGATIVE out, either way."""
    log_fn = log_fn or _log_noop
    LH = _ltx_hidream(log_fn)
    if LH is not None:
        try:
            with LH.gpu_lease(lambda: False, log_fn=log_fn):
                ok = LH.hidream_still(
                    f'{prompt}, {KID_STYLE}',
                    out_png,
                    width=int(w),
                    height=int(h),
                    seed=int(seed),
                    negative=KID_NEGATIVE,
                    log_fn=log_fn,
                )
            if ok:
                return True
            log_fn('still: HiDream produced nothing — falling back to klein')
        except Exception as e:  # noqa: BLE001
            log_fn(f'still: HiDream path raised {type(e).__name__}: {e} — falling back to klein')
    try:
        from zyg_workflows import _comfy_client as _cc
    except Exception as e:  # noqa: BLE001
        log_fn(f'still: ComfyUI client unavailable ({type(e).__name__}: {e})')
        return False
    unet, steps, cfg = klein_settings()
    try:
        wf = _cc.load_workflow('klein_txt2img')
    except Exception as e:  # noqa: BLE001
        log_fn(f'still: workflow missing ({type(e).__name__}: {e})')
        return False
    att = _attest(wf, log_fn=log_fn, run_id=str(seed), tag='kids_series_still')
    if att.get('ok') is False:
        log_fn('still: REFUSED — licence attestation failed for klein_txt2img')
        return False
    overrides = {
        '10': {'unet_name': unet},
        '20': {'text': f'{prompt}, {KID_STYLE}'},
        '21': {'text': KID_NEGATIVE},
        '30': {'width': int(w), 'height': int(h)},
        '32': {'noise_seed': int(seed)},
        # Node 33 MUST see the same width/height as node 30 — the scheduler
        # shifts sigmas by resolution, and a mismatch is a wrong noise schedule
        # rather than an error.
        '33': {'steps': int(steps), 'width': int(w), 'height': int(h)},
        '34': {'cfg': float(cfg)},
    }
    try:
        paths = _cc.submit(wf, overrides=overrides, timeout_s=600, should_abort=lambda: False)
    except Exception as e:  # noqa: BLE001
        log_fn(f'still: submit failed ({type(e).__name__}: {e})')
        return False
    if not paths:
        log_fn('still: ComfyUI returned no output path')
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_png)) or '.', exist_ok=True)
    shutil.copy(paths[0], out_png)
    return os.path.isfile(out_png)


_LIGHTNING_HIGH = 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors'
_LIGHTNING_LOW = 'wan_lightning/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors'


def lightning_default():
    """Is the 4-step Lightning distill on for this process?  Env-gated,
    ``ZYG_KIDS_WAN_LIGHTNING``; a caller's explicit ``lightning=`` wins."""
    return os.environ.get('ZYG_KIDS_WAN_LIGHTNING', '').strip().lower() in ('1', 'true', 'yes', 'on')


def render_i2v(png, prompt, out_mp4, *, seconds=4.8, seed=0, test_mode=False, log_fn=None, lightning=None):
    """A still -> gentle motion through Wan2.2 I2V, scaled to 1280x720@24.

    Wan renders 832x480 at 17 fps; the delivery format is 1280x720 at 24, and
    the scale happens here rather than in ten runners.

    ``lightning`` (None = ``lightning_default()``) swaps the 20-step cfg-5
    schedule for the Apache-2.0 Wan2.2-Lightning 4-step distill pair, one LoRA
    per expert, cfg 1.0.  The LoRA files go through the same licence
    attestation as the experts.

    MEASURED 2026-09-06 on the tractor still (81 frames, same seed):
      plain 8 steps   126 s   barn ghosts inside a second (LOW expert's last
                              step jumps sigma 0.42 -> 0)
      Lightning 4     157 s   tractor holds, but the MOTION is wrong: the
                              camera pans instead of the tractor driving,
                              a second barn appears mid-clip
      plain 20        609 s   correct drive left->right, background stable,
                              smoke a black scribble; 27 s/step, 94 s of the
                              wall in every regime is expert loading
    So Lightning is a speed lever that costs the prompt's motion on flat
    cartoon plates — default OFF, opt in per run for shots where a pan is fine.
    """
    log_fn = log_fn or _log_noop
    if lightning is None:
        lightning = lightning_default()
    if not os.path.isfile(png):
        log_fn('i2v: source still missing')
        return False
    LH = _ltx_hidream(log_fn)
    if LH is not None:
        try:
            raw = out_mp4 + '.ltx_raw.mp4'
            with LH.gpu_lease(lambda: False, log_fn=log_fn):
                ok = LH.ltx_i2v(
                    png,
                    f'{prompt}. Flat 2D children cartoon, keep the exact style, '
                    f'colours and outlines of the first frame. No text.',
                    raw,
                    seconds=max(2, int(round(float(seconds)))),
                    seed=int(seed),
                    log_fn=log_fn,
                )
            if ok:
                os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
                done = _run(
                    [
                        FFMPEG,
                        '-y',
                        '-i',
                        raw,
                        '-vf',
                        _NORM_VF,
                        '-r',
                        str(FPS),
                        '-c:v',
                        'libx264',
                        '-preset',
                        'veryfast',
                        '-crf',
                        '20',
                        '-pix_fmt',
                        'yuv420p',
                        '-an',
                        out_mp4,
                    ]
                )
                try:
                    os.remove(raw)
                except OSError as _exc:
                    _zyg_log.debug('LTX raw clip %s removal skipped: %s', raw, _exc)
                if done:
                    return True
            log_fn('i2v: LTX produced nothing — falling back to Wan2.2')
        except Exception as e:  # noqa: BLE001
            log_fn(f'i2v: LTX path raised {type(e).__name__}: {e} — falling back to Wan2.2')
    try:
        from zyg_workflows import _comfy_client as _cc
    except Exception as e:  # noqa: BLE001
        log_fn(f'i2v: ComfyUI client unavailable ({type(e).__name__}: {e})')
        return False
    try:
        wf = _cc.load_workflow('wan22_i2v')
    except Exception as e:  # noqa: BLE001
        log_fn(f'i2v: workflow missing ({type(e).__name__}: {e})')
        return False
    att = _attest(wf, log_fn=log_fn, run_id=str(seed), tag='kids_series_i2v')
    if att.get('ok') is False:
        log_fn('i2v: REFUSED — licence attestation failed for wan22_i2v')
        return False
    if lightning:
        steps, cfg = 4, 1.0
        # One LoRA per expert; node ids 8/9 are free in wan22_i2v.json.
        wf['8'] = {
            'class_type': 'WanVideoLoraSelect',
            'inputs': {'lora': _LIGHTNING_HIGH, 'strength': 1.0, 'low_mem_load': False},
        }
        wf['9'] = {
            'class_type': 'WanVideoLoraSelect',
            'inputs': {'lora': _LIGHTNING_LOW, 'strength': 1.0, 'low_mem_load': False},
        }
        wf['1']['inputs']['lora'] = ['8', 0]
        wf['7']['inputs']['lora'] = ['9', 0]
        att = _attest(wf, log_fn=log_fn, run_id=str(seed), tag='kids_series_i2v_lightning')
        if att.get('ok') is False:
            log_fn('i2v: REFUSED — licence attestation failed for the Lightning LoRA pair')
            return False
    else:
        steps, cfg = (8 if test_mode else 20), 5.0
    if test_mode:
        frames = 33
    else:
        # 4n+1 or the temporal VAE cannot pack the latent.
        frames = max(9, int(round(float(seconds) * 17.0)))
        frames = frames - ((frames - 1) % 4)
    log_fn(f'i2v: {frames} frames, {steps} steps, cfg {cfg}{" (Lightning distill)" if lightning else ""}')
    try:
        name = _cc.stage_input_image(png)
    except Exception as e:  # noqa: BLE001
        log_fn(f'i2v: could not stage the still ({type(e).__name__}: {e})')
        return False
    half = max(1, steps // 2)
    overrides = {
        '10': {'image': name},
        '11': {'width': 832, 'height': 480, 'num_frames': int(frames)},
        '20': {
            'positive_prompt': f'{prompt}, gentle smooth motion, flat cartoon, bright and friendly',
            'negative_prompt': f'{KID_NEGATIVE}, static, frozen, no motion',
        },
        '30': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg), 'start_step': 0, 'end_step': half},
        '31': {'seed': int(seed), 'steps': int(steps), 'cfg': float(cfg), 'start_step': half, 'end_step': int(steps)},
        '45': {'fps': 17},
    }
    try:
        paths = _cc.submit(wf, overrides=overrides, timeout_s=1800, should_abort=lambda: False)
    except Exception as e:  # noqa: BLE001
        log_fn(f'i2v: submit failed ({type(e).__name__}: {e})')
        return False
    if not paths:
        log_fn('i2v: ComfyUI returned no output path')
        return False
    os.makedirs(os.path.dirname(os.path.abspath(out_mp4)) or '.', exist_ok=True)
    return _run(
        [
            FFMPEG,
            '-y',
            '-i',
            paths[0],
            '-vf',
            _NORM_VF,
            '-r',
            str(FPS),
            '-c:v',
            'libx264',
            '-preset',
            'veryfast',
            '-crf',
            '20',
            '-pix_fmt',
            'yuv420p',
            '-an',
            out_mp4,
        ]
    )
