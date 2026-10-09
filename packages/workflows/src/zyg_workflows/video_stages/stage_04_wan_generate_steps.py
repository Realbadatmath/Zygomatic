# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stage 4 step 2, part one: WAN metadata, the blank guard and the animate calls.

Extracted from `stage_04_wan_generate.generate_wan_clips`, which was 622 lines —
twice the 300-line cap — and therefore untestable as a whole. Every block moved
here keeps its log text, its side effects and their order, including the
deliberately swallowed failure paths; `generate_wan_clips` is now the
orchestrator that calls these in the same sequence.

`WanClipRun` carries the handful of `RunContext` attributes the extracted blocks
used to read as enclosing locals, so no helper needs a closure.
"""

from __future__ import annotations

import logging as _zyg_logging
import os
import random as _random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from zyg_workflows import paths

# The monolith's channel, so a run's log lines keep one name across the split.
_zyg_log = _zyg_logging.getLogger('zyg_workflows.pipeline_video')

# A genuine 1920×1080 FLUX output is always >100 KB; an OOM fallback is ~8 KB.
BLANK_THRESH = 100 * 1024

# WAN progress messages carrying one of these words are routed to WARNING.
WAN_ERR_WORDS = (
    'failed',
    'error',
    'exception',
    'oom',
    'out of memory',
    'cuda',
    'traceback',
    'killed',
    'crash',
    'abort',
)


@dataclass
class WanClipRun:
    """The `RunContext` slice the WAN clip helpers read, bound once per run.

    Built by `generate_wan_clips` from the locals it already unpacked from the
    context plus the four WAN call parameters, so the extracted helpers take one
    object instead of a dozen arguments.
    """

    log: Callable[[str, str, str], None]
    set_stage: Callable[[str], None]
    complete_stage: Callable[[str], None]
    sp_video: Any
    vscfg: Any
    images_dir: str
    job: dict
    n_scenes: int
    out_dir: str
    scene_images: list
    scenes: list
    visual_style: str
    wan_svc: Any
    wan_n_chained: Any
    wan_test_frames: Any
    wan_test_steps: Any


def detect_emotion(desc: str) -> str:
    """Infer WAN emotion tag from scene description keywords."""
    d = desc.lower()
    if any(k in d for k in ['fight', 'battle', 'combat', 'clash', 'charge', 'attack', 'blood', 'brutal']):
        return 'anger'
    if any(k in d for k in ['victori', 'triumph', 'raised', 'conquer', 'standing atop', 'standing victorious']):
        return 'triumph'
    if any(k in d for k in ['sunset', 'vast', 'sweeping', 'panoram', 'landscape', 'vista', 'mountain', 'coast']):
        return 'awe'
    if any(k in d for k in ['death', 'fallen', 'dead', 'grief', 'mour', 'despair', 'tragic']):
        return 'grief'
    if any(k in d for k in ['tense', 'siege', 'surround', 'standoff', 'face off']):
        return 'tension'
    return 'neutral'


def build_wan_meta(scenes, scene_images, scene_duration):
    """One `flux_image_meta`-compatible dict per scene, in scene order.

    Takes the planner's scenes, the stills FLUX produced and the per-scene
    duration; returns the list WAN's `generate()` consumes. Claude's
    `wan_prompt` is used verbatim but always carries a photorealism clause,
    which stops WAN drifting to a cartoon look on close-up animals and nature.
    """
    wan_meta = []
    for _wi, _sc in enumerate(scenes):
        _desc = _sc.get('description', f'cinematic scene {_wi}')
        # Use Claude's dedicated WAN animation prompt; fallback to description
        _wan_p = _sc.get('wan_prompt') or _desc
        # Enforce photorealism — prevents WAN from drifting to animated/cartoon style
        # especially when animating animals or nature elements close-up
        if 'photorealistic' not in _wan_p.lower():
            _wan_p = (
                _wan_p.rstrip('. ')
                + '. Photorealistic, not animated, not cartoon, not illustrated, wildlife photography quality.'
            )
        # Use Claude's scene-aware shot type; fallback to sensible defaults
        _shot = _sc.get('shot_type') or ('wide cinematic shot' if _wi % 3 == 0 else 'medium shot')
        # Use Claude's camera motion; fallback to emotion-derived motion in _build_prompt
        _cam_motion = _sc.get('camera_motion') or ''
        wan_meta.append(
            {
                'prompt': _desc,
                'wan_prompt': _wan_p,  # Claude-written animation prompt, used verbatim
                'subject': (_desc or '')[:60],
                'tag': 'neutral',
                'shot_type': _shot,
                'camera_motion': _cam_motion,
                'emotion': detect_emotion(_desc),
                'slot_seconds': float(_wi * scene_duration),
                'index': _wi,
                'path': scene_images[_wi] if _wi < len(scene_images) else '',
                'seed': _random.randint(0, 2**32 - 1),
                'scene_type': str(_sc.get('scene_type', '')).lower(),
            }
        )
    return wan_meta


def blank_flux_images(wan_meta):
    """Paths in `wan_meta` whose still exists on disk but is under BLANK_THRESH."""
    return [
        m['path']
        for m in wan_meta
        if m.get('path') and os.path.exists(m['path']) and os.path.getsize(m['path']) < BLANK_THRESH
    ]


def apply_blank_image_guard(wan_meta, log) -> bool:
    """Log the blank-FLUX verdict; True means WAN must be skipped entirely.

    FLUX OOM produces ~8 KB blank PNGs and animating them wastes 26+ minutes of
    GPU time, so an all-blank set aborts WAN (True); a partial set is a warning
    and the run continues (False).
    """
    _blank_imgs = blank_flux_images(wan_meta)
    if _blank_imgs and len(_blank_imgs) == len(wan_meta):
        log(
            'ERROR',
            'Stage 4',
            f'All {len(_blank_imgs)}/{len(wan_meta)} FLUX images are blank/OOM fallbacks '
            f'(<{BLANK_THRESH // 1024} KB). FLUX stage failed. '
            f'Aborting WAN to prevent wasting GPU time on blank frames.',
        )
        return True
    if _blank_imgs:
        log(
            'WARNING',
            'Stage 4',
            f'{len(_blank_imgs)}/{len(wan_meta)} FLUX images appear blank — '
            f'those scenes may produce static WAN output.',
        )
    return False


def make_wan_log(log):
    """Wrap the pipeline logger as WAN's single-string `log_fn`.

    Messages containing a failure keyword (`WAN_ERR_WORDS`) are raised to
    WARNING so an OOM inside the service is visible; everything else is INFO.
    """

    def _wan_log(m: str) -> None:
        _ml = m.lower()
        if any(w in _ml for w in WAN_ERR_WORDS):
            log('WARNING', 'Stage 4', m)
        else:
            log('INFO', 'Stage 4', m)

    return _wan_log


def note_wan_unavailable(log, job) -> None:
    """Record, once per job, that WAN was skipped and stills will be used.

    Appends the user-facing warning and sets `job['wan_fallback']`; a second
    call on the same job adds nothing.
    """
    log(
        'WARNING',
        'Stage 4',
        'WAN service unavailable — skipping video generation, pipeline will use static fallback clips.',
    )
    if not job.get('wan_fallback'):
        job.setdefault('warnings', []).append(
            '⚠️ WAN video generation skipped — service unavailable. '
            'Static image fallback used — video will show still frames.'
        )
        job['wan_fallback'] = True


def t5_prompt_embeds_on_cpu(
    self,
    prompt=None,
    num_images_per_prompt=1,
    max_sequence_length=512,
    device=None,
    dtype=None,
):
    """Drop-in `_get_t5_prompt_embeds` that tokenises on the encoder's own device.

    Bound onto the FLUX img2img pipeline so the T5 text encoder can stay on the
    CPU while the transformer and VAE hold the GPU; returns the embeddings on
    the pipeline's execution device, shaped as diffusers expects.
    """
    device = device or self._execution_device
    prompt = [prompt] if isinstance(prompt, str) else prompt
    batch_size = len(prompt)
    text_inputs = self.tokenizer_2(
        prompt,
        padding='max_length',
        max_length=max_sequence_length,
        truncation=True,
        return_length=False,
        return_overflowing_tokens=False,
        return_tensors='pt',
    )
    _t5_dev = next(self.text_encoder_2.parameters()).device
    _emb = self.text_encoder_2(text_inputs.input_ids.to(_t5_dev), output_hidden_states=False)[0].to(
        dtype=self.text_encoder_2.dtype, device=device
    )
    _, seq_len, _ = _emb.shape
    _emb = _emb.repeat(1, num_images_per_prompt, 1)
    return _emb.view(batch_size * num_images_per_prompt, seq_len, -1)


def build_chain_prompt(run, ci: int) -> str:
    """The img2img prompt for scene `ci`: style prefix, scene text, style suffix.

    Falls back through the scene's `flux_prompt`, its `description` and finally
    `'<visual_style> scene <ci>'` so a sparse plan still produces a prompt.
    """
    _sc_chain = run.scenes[ci] if ci < len(run.scenes) else {}
    _flux_p_chain = _sc_chain.get('flux_prompt') or _sc_chain.get('description') or f'{run.visual_style} scene {ci}'
    return (
        f'{run.vscfg.get("prefix", "cinematic photograph")}, '
        f'{_flux_p_chain}, '
        f'{run.vscfg.get("suffix", "photorealistic, dramatic lighting, 16:9 composition, film grain")}'
    )


def load_flux_img2img(torch_mod):
    """Load FLUX schnell as an img2img pipeline with the T5 encoder left on CPU.

    Takes the already-imported torch module (for the dtype and so the caller
    keeps one handle for its cache clears) and returns the pipeline with
    `t5_prompt_embeds_on_cpu` bound as `_get_t5_prompt_embeds`.
    """
    import types as _types_i2i

    from diffusers import FluxImg2ImgPipeline as _FluxI2I

    _i2i_pipe = _FluxI2I.from_pretrained(
        str(paths.ZYG_FLUX_ROOT / 'flux1-schnell'),
        torch_dtype=torch_mod.bfloat16,
    )
    _i2i_pipe.transformer.to('cuda')
    _i2i_pipe.text_encoder.to('cuda')
    _i2i_pipe.vae.to('cuda')
    _i2i_pipe._get_t5_prompt_embeds = _types_i2i.MethodType(t5_prompt_embeds_on_cpu, _i2i_pipe)
    return _i2i_pipe


def save_chained_image(run, ci: int, chained_img) -> None:
    """Write the chained still for scene `ci` and point `scene_images` at it.

    Saves `scene_<ci>.png` beside the other stills, then a 4× LANCZOS copy so
    WAN gets a high-res seed matching Stage 2's ESRGAN output; if the upscale
    fails the 1× PNG is used. `run.scene_images[ci]` is replaced in place (or
    appended when the list is short).
    """
    _chained_dest = os.path.join(run.images_dir, f'scene_{ci:04d}.png')
    chained_img.save(_chained_dest)
    # Upscale the chained frame 4× (LANCZOS) so WAN gets a
    # high-res seed image, matching Stage 2 ESRGAN output
    try:
        from PIL import Image as _PIL_chain

        _cw, _ch = chained_img.size
        _chain_4x = chained_img.resize(
            (_cw * 4, _ch * 4),
            _PIL_chain.LANCZOS,
        )
        _chained_4x_dest = _chained_dest.replace('.png', '_4x.png')
        _chain_4x.save(_chained_4x_dest)
        _chained_dest_final = _chained_4x_dest
    except Exception:
        _chained_dest_final = _chained_dest
    if ci < len(run.scene_images):
        run.scene_images[ci] = _chained_dest_final
    else:
        run.scene_images.append(_chained_dest_final)


def release_i2i_pipe(pipe) -> None:
    """Move the img2img pipeline off the GPU and empty the cache; never raises.

    The error path of `chain_scene_image`: a pipeline that was never built (or
    already gone) only writes a debug line, because failing to free VRAM must
    not replace the failure that got us here.
    """
    try:
        pipe.to('cpu')
        import gc as _gc_c_err

        _gc_c_err.collect()
        import torch as _tc_c_err

        _tc_c_err.cuda.empty_cache()
    except Exception as _exc:
        _zyg_log.debug('img2img pipeline VRAM release skipped: %s', _exc)


def chain_scene_image(run, ci: int, last_wan_frame) -> None:
    """Step A of continuous mode: img2img scene `ci` from the previous clip's end.

    Upscales `last_wan_frame` to the FLUX target, runs img2img at strength 0.35
    (65 % visual continuity, less hand drift than 0.40), stores the result as
    scene `ci`'s still and frees the pipeline's VRAM before WAN needs it. Any
    failure is logged and leaves the text-to-image still in place, so the caller
    never has to handle an exception. Ends on the 'Video Generation' stage.
    """
    run.set_stage('Scene Chaining')
    run.log(
        'INFO',
        'Scene Chaining',
        f'Scene {ci + 1}/{run.n_scenes}: FLUX img2img from WAN last frame…',
    )
    _i2i_pipe = None
    try:
        import gc as _gc_c

        import torch as _tc_c
        from PIL import Image as _PIL_c

        _tc_c.cuda.empty_cache()
        _gc_c.collect()

        # Upscale WAN last frame (832×480) → FLUX target (1360×768)
        _upscaled = last_wan_frame.resize((1360, 768), _PIL_c.LANCZOS)
        _prompt_chain = build_chain_prompt(run, ci)

        run.log('INFO', 'Scene Chaining', f'Scene {ci + 1}: loading FLUX img2img…')
        _i2i_pipe = load_flux_img2img(_tc_c)

        _chained_img = _i2i_pipe(
            prompt=_prompt_chain,
            image=_upscaled,
            strength=0.35,  # 65% visual continuity — reduces hand drift vs 0.40
            guidance_scale=0.0,
            num_inference_steps=4,
            width=1360,
            height=768,
            generator=_tc_c.Generator('cuda').manual_seed(_random.randint(0, 2**32 - 1)),
        ).images[0]

        # Replace the FLUX-generated scene image with the chained one
        save_chained_image(run, ci, _chained_img)

        # Unload FLUX img2img to free VRAM for WAN
        _i2i_pipe.to('cpu')
        _i2i_pipe = None
        del _chained_img, _upscaled
        _gc_c.collect()
        _tc_c.cuda.empty_cache()
        import time as _tc_sleep

        _tc_sleep.sleep(3)
        _tc_c.cuda.empty_cache()

        run.log(
            'INFO',
            'Scene Chaining',
            f'Scene {ci + 1}/{run.n_scenes}: img2img complete — visually continuous from scene {ci}',
        )

    except Exception as _chain_e:
        run.log(
            'WARNING',
            'Scene Chaining',
            f'Scene {ci + 1} img2img failed ({_chain_e}) — falling back to FLUX text-to-image result',
        )
        # Always free img2img VRAM even on error
        release_i2i_pipe(_i2i_pipe)
        _i2i_pipe = None

    run.set_stage('Video Generation')


def animate_scenes_chained(run, wan_meta, wan_log, wan_by_idx):
    """Continuous mode: chain each scene's still off the previous clip, then animate.

    Walks the scenes in order; from scene 2 on, `chain_scene_image` rewrites the
    still from the previous clip's last frame, then WAN animates that one scene.
    Fills `wan_by_idx` in place and returns the per-clip result dicts; a clip
    that fails is logged and skipped, so a bad scene costs one clip, not the run.
    """
    run.log('INFO', 'Stage 4', f'Scene mode: CONTINUOUS — {run.n_scenes} scenes chained visually')
    _last_wan_frame = None  # PIL Image captured from end of previous WAN clip
    _wan_results = []

    for _ci in range(run.n_scenes):
        # ── Step A: img2img chain (scene 1 onwards) ──────────────────
        if _ci > 0 and _last_wan_frame is not None:
            chain_scene_image(run, _ci, _last_wan_frame)

        # ── Step B: Update path in wan_meta for this scene ────────────
        if _ci < len(wan_meta) and _ci < len(run.scene_images):
            wan_meta[_ci]['path'] = run.scene_images[_ci]

        # ── Step C: WAN animate this scene ───────────────────────────
        run.log('INFO', 'Stage 4', f'WAN chained: animating scene {_ci + 1}/{run.n_scenes}…')
        _meta_single = [wan_meta[_ci]] if _ci < len(wan_meta) else []
        if _meta_single:
            try:
                _single_results = run.wan_svc.generate(
                    _meta_single,
                    run.out_dir,
                    n_clips=1,
                    n_chained=run.wan_n_chained,
                    log_fn=wan_log,
                    visual_style=run.visual_style,
                    frames=run.wan_test_frames,
                    steps=run.wan_test_steps,
                )
                if _single_results:
                    _r = _single_results[0]
                    wan_by_idx[_ci] = _r['path']
                    _last_wan_frame = _r.get('last_frame')
                    _wan_results.append(_r)
                    run.log('INFO', 'Stage 4', f'WAN chained: {len(wan_by_idx)}/{run.n_scenes} clips done')
            except Exception as _wc_e:
                run.log('WARNING', 'Stage 4', f'WAN chained clip {_ci} failed: {_wc_e}')

    run.log('INFO', 'Stage 4', f'WAN chained complete: {len(_wan_results)}/{run.n_scenes} clips generated')
    return _wan_results


def animate_scenes_batched(run, wan_meta, wan_log):
    """Independent mode (default): one WAN call animates every scene at once.

    Returns the result dicts exactly as the service produced them; the caller
    derives `wan_by_idx` from their `index`/`path`.
    """
    _wan_results = run.wan_svc.generate(
        wan_meta,
        run.out_dir,
        n_clips=run.n_scenes,
        n_chained=run.wan_n_chained,
        log_fn=wan_log,
        visual_style=run.visual_style,
        frames=run.wan_test_frames,
        steps=run.wan_test_steps,
    )
    run.log('INFO', 'Stage 4', f'WAN generated {len(_wan_results)}/{run.n_scenes} clips')
    return _wan_results
