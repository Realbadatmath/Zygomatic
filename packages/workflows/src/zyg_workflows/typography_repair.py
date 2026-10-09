# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Region repair for readable lettering — inpaint the words out of a frame.

Why this exists
---------------
The retry ladder re-rolls a whole slot when the typography gate flags it: new
seed, then a suppression clause, then the written object dropped from the
prompt entirely. That works often enough (measured: most flagged slots clear at
the clause rung) but it is a blunt instrument — it throws away a composition
that was fine except for four square centimetres of gibberish, and when all
three rungs fail the frame ships flagged anyway.

The OCR judge already returns a BOX for every flag. Given the box, the cheap
correct move is to repaint just that region and leave the rest of the frame
alone.

Guarantees
----------
* **No repainted content leaves the flagged region.** The repaint is
  composited back through the mask, so where the mask is zero the output is the
  original pixel — by construction, not by hoping the model stayed in its box.

  The file is still re-encoded, and JPEG cannot re-encode one region in
  isolation: the 8x8 DCT blocks straddling the mask edge, and the chroma
  subsampling around them, requantize differently. Measured on real frames,
  beyond **mask + 16 px** the repaired file is identical to simply re-encoding
  the original at the same quality — max and mean per-pixel delta match the
  no-op control exactly (e.g. flux_023: repaired max 32 / mean 0.45, control
  max 32 / mean 0.45). So the honest claim is: nothing outside the flagged
  region changes beyond what saving the file again would have changed anyway.
* **Fail-closed.** A repair is accepted only if the OCR judge then reads
  nothing in the frame. If the lettering survives, or new lettering appears
  elsewhere, the original is kept and the caller still reports it flagged. A
  repair that cannot be verified is not a repair.

Hit rate, measured on the 12 labelled frames of run 85f0659c:

    classical only (what the unit test runs)   9/12, 0 leaks, 203 s
    FLUX first + classical fallback (production) 9/12, 0 leaks, 363 s

Both paths decline the same three, all correctly: two frames where the lettering
IS the shot (8% of frame, over the blemish cap) and one where the only available
fill came out solid. Note the unit test deliberately runs the CLASSICAL path
only — the suite runs on every change and cannot afford a 24 GB model load — so
its number is a floor, not the production figure.

An earlier version took the first strategy that helped, and that made ORDERING
decide the result: FLUX-first scored 8/12 against classical-only's 9/12, because
FLUX often leaves the lettering untouched and its partial edits can leave the
frame in a state where the fallback is then rejected. Every strategy is now
evaluated each round and the best kept.

Strategies, all evaluated per round, a diffusion repaint preferred on a tie:
  1. ``flux``  — FLUX.1-schnell inpainting through ``FluxInpaintPipeline
     .from_pipe()``, which REUSES the already-loaded weights (no second model,
     no extra VRAM). Positive phrasing only: schnell discards negative prompts
     and guidance (measured — see project-inert-levers-flux). Only when the
     caller hands over an in-process pipe.
  2. ``qwen_inpaint`` (2026-08-25, P-10) — Qwen-Image-2512 + InstantX
     ControlNet-Inpainting through ComfyUI, the same ``hand_fixer_qwen_inpaint``
     graph Stage 3.6 and era_gate.region_repair use. This is the diffusion
     strategy on the Qwen documentary path, where there is no in-process pipe
     and the sweep used to have only ``telea``. Qwen has a live negative, so
     the lettering ban goes there. Crops around the mask like ``flux`` does.
     ZYG_TYPO_QWEN_INPAINT=0 disables; unset/'auto' arms it when ComfyUI is
     enabled + reachable, the stack is on disk and no in-process pipe is
     loaded; '1' arms it even beside a loaded pipe.
  3. ``telea`` — classical cv2 inpainting. It cannot invent detail, but it
     reliably destroys letterforms, which is the actual objective.

Licence: everything here is Apache-2.0 (FLUX.1-schnell, Qwen-Image-2512,
InstantX inpaint ControlNet) or BSD (OpenCV). The FLUX Fill and LaMa
inpainting models were both rejected — their weights are non-commercial and
this channel is monetised.
"""

from __future__ import annotations

import os
import logging as _zyg_logging
from zyg_workflows import paths

_zyg_log = _zyg_logging.getLogger(__name__)


_EMB_CACHE: dict = {}

_DILATE_FRAC = float(os.environ.get('ZYG_TYPO_REPAIR_DILATE', '0.012'))
_FEATHER_PX = int(os.environ.get('ZYG_TYPO_REPAIR_FEATHER', '3'))
# Repair is for BLEMISHES. Past a few percent of the frame the lettering is not
# a defect on the shot, it IS the shot, and repainting it destroys structure the
# colour check cannot see: at 11.8% on flux_022 the classical strategy ate half
# a question mark while matching its surroundings perfectly. Above this the
# ladder's prompt rewrite is the honest tool, and a frame that survives that
# ships flagged rather than smudged.
_MAX_AREA_FRAC = float(os.environ.get('ZYG_TYPO_REPAIR_MAX_AREA', '0.05'))
# One region may not swallow a composition on its own either.
_MAX_BOX_FRAC = float(os.environ.get('ZYG_TYPO_REPAIR_MAX_BOX', '0.02'))
_MAX_LUMA_DELTA = float(os.environ.get('ZYG_TYPO_REPAIR_MAX_LUMA', '30'))
_MAX_CHROMA_DELTA = float(os.environ.get('ZYG_TYPO_REPAIR_MAX_CHROMA', '34'))
_MIN_PATCH_STD = float(os.environ.get('ZYG_TYPO_REPAIR_MIN_STD', '2.0'))
_JPEG_Q = int(os.environ.get('ZYG_TYPO_REPAIR_JPEG_Q', '95'))
_PROMPT = os.environ.get(
    'ZYG_TYPO_REPAIR_PROMPT',
    'the same material continuing uninterrupted, matching surface texture and '
    'grain, same colour and lighting as the surrounding area, photographic, '
    'seamless continuation',
)

# ``qwen_inpaint`` strategy (ComfyUI hand_fixer_qwen_inpaint graph). Qwen has a
# real negative, unlike schnell, so the lettering ban lives there.
_QWEN_PROMPT = os.environ.get(
    'ZYG_TYPO_QWEN_PROMPT',
    'plain surface, no lettering, the same material continuing uninterrupted, '
    'matching surface texture, grain, colour and lighting as the surrounding '
    'area, photographic, seamless continuation',
)
_QWEN_NEGATIVE = os.environ.get(
    'ZYG_TYPO_QWEN_NEGATIVE',
    'text, letters, lettering, writing, words, numbers, characters, signage, '
    'sign, logo, watermark, caption, label, inscription, calligraphy, blurry',
)
_QWEN_STEPS = int(os.environ.get('ZYG_TYPO_QWEN_STEPS', '20'))
_QWEN_MAX_SIDE = int(os.environ.get('ZYG_TYPO_QWEN_MAX_SIDE', '1024'))
_QWEN_TIMEOUT_S = float(os.environ.get('ZYG_TYPO_QWEN_TIMEOUT_S', '600'))
_QWEN_MODEL_FILES = (
    'controlnet/Qwen-Image-InstantX-ControlNet-Inpainting.safetensors',
    'diffusion_models/qwen_image_2512_fp8_e4m3fn.safetensors',
)
_COMFY_MODELS_ROOT = str(paths.ZYG_COMFY_MODELS_ROOT)


def build_mask(size, boxes, dilate_frac: float | None = None):
    """White where the lettering is. boxes are (x0,y0,x1,y1) in 0-1000 coords."""
    from PIL import Image, ImageDraw

    W, H = size
    df = _DILATE_FRAC if dilate_frac is None else dilate_frac
    dx, dy = df * W, df * H
    m = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(m)
    for b in boxes or []:
        try:
            x0, y0, x1, y1 = [float(v) for v in b]
        except Exception as _exc:
            _zyg_log.debug('mask box ignored, its bounds are not numeric: %s', _exc)
            continue
        x0 = max(0.0, x0 / 1000.0 * W - dx)
        y0 = max(0.0, y0 / 1000.0 * H - dy)
        x1 = min(float(W), x1 / 1000.0 * W + dx)
        y1 = min(float(H), y1 / 1000.0 * H + dy)
        if x1 > x0 and y1 > y0:
            d.rectangle([x0, y0, x1, y1], fill=255)
    return m


def mask_area_frac(mask) -> float:
    h = mask.histogram()
    on = sum(h[128:])
    return on / float(mask.size[0] * mask.size[1] or 1)


def _composite(original, repaired, mask, feather: int = _FEATHER_PX):
    """Masked pixels from `repaired`, everything else exactly `original`."""
    from PIL import Image, ImageFilter

    if repaired.size != original.size:
        repaired = repaired.resize(original.size, Image.LANCZOS)
    soft = mask.filter(ImageFilter.GaussianBlur(feather)) if feather > 0 else mask
    return Image.composite(repaired.convert('RGB'), original.convert('RGB'), soft)


def _flux_inpaint(original, mask, pipe, seed: int, steps: int = 4):
    """Repaint the masked region with the FLUX pipe already in memory.

    Works on a CROP around the mask, not the whole frame. Inpainting a
    1280x720 (or upscaled 5120x2880) still at full resolution runs the
    transformer over every latent in the image to fix a patch that is often
    ~1% of it — measured: CUDA OOM on every frame tried, even with 40 GB free.
    Cropping to the flagged region plus padding keeps the work proportional to
    the defect, which is the whole point of a region repair.
    """
    import torch
    from diffusers import FluxInpaintPipeline
    from PIL import Image

    W, H = original.size
    bb = mask.getbbox()
    if not bb:
        raise ValueError('empty mask')
    x0, y0, x1, y1 = bb
    pad = int(0.35 * max(x1 - x0, y1 - y0)) + 48
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
    cw, ch = cx1 - cx0, cy1 - cy0
    if cw < 16 or ch < 16:
        raise ValueError('crop too small')

    img_c = original.crop((cx0, cy0, cx1, cy1))
    msk_c = mask.crop((cx0, cy0, cx1, cy1))

    # Process at a bounded size — the repaint is a blank surface, so detail
    # lost on the way down and back is not detail anyone will miss.
    max_side = int(os.environ.get('ZYG_TYPO_REPAIR_MAX_SIDE', '768'))
    scale = min(1.0, max_side / float(max(cw, ch)))
    pw = max(16, int(round(cw * scale / 16)) * 16)
    ph = max(16, int(round(ch * scale / 16)) * 16)

    # NOT FluxInpaintPipeline.from_pipe(pipe): from_pipe unifies devices with a
    # .to(), which drags T5-XXL (~9 GB, deliberately kept in CPU RAM by the
    # production loader) onto the card. Measured: 18.2 GB free -> 0.1 GB and an
    # OOM inside torch's `convert`, on a crop that needs about 2 GB.
    # Constructing from the existing components wires references and moves
    # nothing.
    inp = FluxInpaintPipeline(**pipe.components)
    try:
        inp.enable_vae_tiling()
    except Exception as _exc:
        _zyg_log.debug('VAE tiling not enabled: %s', _exc)

    # Encode with the SOURCE pipe: production patches its _get_t5_prompt_embeds
    # to run T5 on the CPU and hand back only the embedding, so the text encoder
    # never has to be on the GPU at all. Passing embeds straight in keeps that
    # property instead of re-deriving it here.
    _dev = next(pipe.transformer.parameters()).device
    _t5_dev = next(pipe.text_encoder_2.parameters()).device
    _clip_dev = next(pipe.text_encoder.parameters()).device
    # The prompt never changes, and T5 lives in CPU RAM, so encoding it per
    # frame was most of the wall clock (measured ~20 s a frame, of which the
    # inpaint itself is under a second). Encode once per process.
    _ck = (str(_dev), str(pipe.transformer.dtype), _PROMPT)
    global _EMB_CACHE
    if _ck in _EMB_CACHE:
        _pe, _pooled = _EMB_CACHE[_ck]
    else:
        with torch.no_grad():
            if _t5_dev == _clip_dev == _dev:
                _pe, _pooled, *_rest = pipe.encode_prompt(
                    prompt=_PROMPT, prompt_2=_PROMPT, device=_dev, num_images_per_prompt=1, max_sequence_length=256
                )
            else:  # noqa: E301
                # Split devices: encode each tower where it actually lives, then
                # move the (tiny) embeddings to the transformer. encode_prompt takes
                # ONE device for both, so with T5 parked in CPU RAM it sends cuda
                # input ids to a cpu module and raises.
                _pe = pipe._get_t5_prompt_embeds(
                    prompt=_PROMPT, num_images_per_prompt=1, max_sequence_length=256, device=_t5_dev
                )
                _pooled = pipe._get_clip_prompt_embeds(prompt=_PROMPT, num_images_per_prompt=1, device=_clip_dev)
                _pe = _pe.to(_dev, dtype=pipe.transformer.dtype)
                _pooled = _pooled.to(_dev, dtype=pipe.transformer.dtype)
        _EMB_CACHE[_ck] = (_pe, _pooled)

    out = inp(
        prompt_embeds=_pe,
        pooled_prompt_embeds=_pooled,
        image=img_c.resize((pw, ph), Image.LANCZOS),
        mask_image=msk_c.resize((pw, ph), Image.NEAREST),
        height=ph,
        width=pw,
        strength=float(os.environ.get('ZYG_TYPO_REPAIR_STRENGTH', '0.65')),
        num_inference_steps=steps,
        guidance_scale=0.0,  # discarded by schnell anyway; stated for clarity
        generator=torch.Generator('cpu').manual_seed(int(seed)),
    ).images[0]

    painted = original.copy()
    painted.paste(out.resize((cw, ch), Image.LANCZOS), (cx0, cy0))
    return painted


def _telea_inpaint(original, mask):
    import numpy as np
    import cv2

    a = cv2.cvtColor(np.array(original.convert('RGB')), cv2.COLOR_RGB2BGR)
    m = (np.array(mask) > 127).astype('uint8') * 255
    rad = max(3, int(0.004 * max(original.size)))
    out = cv2.inpaint(a, m, rad, cv2.INPAINT_TELEA)
    from PIL import Image

    return Image.fromarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB))


def _qwen_inpaint_ready(pipe=None) -> bool:
    """Can the ``qwen_inpaint`` strategy run right now?

    ZYG_TYPO_QWEN_INPAINT: '0' disables. Unset/'auto' arms it when ComfyUI is
    enabled (ZYG_USE_COMFYUI) and reachable, the Qwen InstantX inpaint stack
    is on disk, the graph loads, and NO in-process FLUX pipe is loaded — a
    second ~20 GB model beside a resident pipe is an OOM, not a repair. '1'
    arms it even beside a loaded pipe (operator's call).
    """
    flag = os.environ.get('ZYG_TYPO_QWEN_INPAINT', 'auto').strip().lower()
    if flag in ('0', 'false', 'no', 'off'):
        return False
    if pipe is not None and flag not in ('1', 'true', 'yes', 'on', 'force'):
        return False
    try:
        from zyg_workflows import _comfy_client as _comfy
    except Exception:
        return False
    try:
        if not (_comfy.is_enabled() and _comfy.server_reachable()):
            return False
        if not all(os.path.isfile(os.path.join(_COMFY_MODELS_ROOT, f)) for f in _QWEN_MODEL_FILES):
            return False
        _comfy.load_workflow('hand_fixer_qwen_inpaint')
    except Exception:
        return False
    return True


def _qwen_inpaint(original, mask, seed: int, steps: int | None = None):
    """Repaint the masked region through the Qwen InstantX inpaint graph on ComfyUI.

    Same graph and the same override keys as
    ``flux_fill_service._repair_via_qwen_comfyui`` and ``era_gate.region_repair``
    (node 14 = source LoadImage, 46 = mask LoadImage → ImageToMask(red, white =
    repaint), 20/21 = positive/negative CLIPTextEncode, 31 = KSampler).

    Works on a CROP around the mask, exactly as ``_flux_inpaint`` does: by the
    time the sweep runs a still may be the 4x-upscaled 5120x2880 frame, and a
    full-frame Qwen inpaint for a 1% patch is wall-clock and VRAM for nothing.
    The crop is widened to >= 512 px a side where the frame allows (Qwen wants
    context) and resampled to ``ZYG_TYPO_QWEN_MAX_SIDE`` (default 1024). Returns
    a full-size image with the crop pasted back; the caller composites through
    the mask, so nothing outside it survives whatever the model did to the crop.
    """
    import tempfile
    from zyg_workflows import _comfy_client as _comfy
    from PIL import Image

    W, H = original.size
    bb = mask.getbbox()
    if not bb:
        raise ValueError('empty mask')
    x0, y0, x1, y1 = bb
    pad = int(0.35 * max(x1 - x0, y1 - y0)) + 48
    cx0, cy0 = max(0, x0 - pad), max(0, y0 - pad)
    cx1, cy1 = min(W, x1 + pad), min(H, y1 + pad)
    _min_side = 512
    if cx1 - cx0 < _min_side:
        _grow = (_min_side - (cx1 - cx0)) // 2 + 1
        cx0, cx1 = max(0, cx0 - _grow), min(W, cx1 + _grow)
    if cy1 - cy0 < _min_side:
        _grow = (_min_side - (cy1 - cy0)) // 2 + 1
        cy0, cy1 = max(0, cy0 - _grow), min(H, cy1 + _grow)
    cw, ch = cx1 - cx0, cy1 - cy0
    if cw < 16 or ch < 16:
        raise ValueError('crop too small')

    img_c = original.crop((cx0, cy0, cx1, cy1)).convert('RGB')
    msk_c = mask.crop((cx0, cy0, cx1, cy1))
    scale = _QWEN_MAX_SIDE / float(max(cw, ch))  # up OR down to max_side
    pw = max(16, int(round(cw * scale / 16)) * 16)
    ph = max(16, int(round(ch * scale / 16)) * 16)

    tmpd = tempfile.mkdtemp(prefix='typoqwen_')
    src_p = os.path.join(tmpd, 'source.png')
    msk_p = os.path.join(tmpd, 'mask.png')
    img_c.resize((pw, ph), Image.LANCZOS).save(src_p)
    msk_c.resize((pw, ph), Image.NEAREST).convert('RGB').save(msk_p)
    staged: list = []
    try:
        # Record each staged name IMMEDIATELY: a failure staging the mask must
        # still remove the source symlink from Comfy's input dir.
        src_name = _comfy.stage_input_image(src_p)
        staged.append(src_name)
        msk_name = _comfy.stage_input_image(msk_p)
        staged.append(msk_name)
        wf = _comfy.load_workflow('hand_fixer_qwen_inpaint')
        outs = _comfy.submit(
            wf,
            overrides={
                '14': {'image': src_name},
                '46': {'image': msk_name},
                '20': {'text': _QWEN_PROMPT},
                '21': {'text': _QWEN_NEGATIVE},
                '31': {'seed': int(seed) + 7919, 'steps': int(steps or _QWEN_STEPS), 'cfg': 2.5, 'denoise': 1.0},
            },
            timeout_s=_QWEN_TIMEOUT_S,
        )
        if not outs:
            raise RuntimeError('qwen inpaint produced no output')
        with Image.open(outs[0]) as o:
            out = o.convert('RGB').resize((cw, ch), Image.LANCZOS)
    finally:
        for p in (src_p, msk_p):
            try:
                os.remove(p)
            except OSError as _exc:
                _zyg_log.debug('temporary file cleanup skipped: %s', _exc)
        try:
            os.rmdir(tmpd)
        except OSError as _exc:
            _zyg_log.debug('temporary dir cleanup skipped: %s', _exc)
        for name in staged:  # stage_input_image leaves a symlink in Comfy's input dir
            try:
                os.remove(os.path.join(_comfy.COMFY_INPUT, name))
            except OSError as _exc:
                _zyg_log.debug('staged comfy input cleanup skipped: %s', _exc)

    painted = original.copy()
    painted.paste(out, (cx0, cy0))
    return painted


def _plausible(
    candidate,
    mask,
    max_luma_delta: float | None = None,
    max_chroma_delta: float | None = None,
    min_std: float | None = None,
):
    """Does the repainted region belong where it was put?

    The OCR judge only asks whether text is readable, and a flat white rectangle
    passes that trivially. Measured on flux_022: FLUX, told to paint a "plain
    blank unmarked surface", painted exactly that — white bars across the map
    and a hole through the question mark. Clean by the letter of the gate,
    ruined by any human standard.

    The first version of this check compared TEXTURE against a ring of untouched
    pixels, on the theory that a censorship bar is flat. Measured on six real
    frames, that theory is backwards:

        frame        telea ratio    white-bar ratio
        flux_012        0.11             0.74
        flux_020        0.12             0.78
        flux_023        0.68             4.46

    A bar has hard straight EDGES, and those spike the Laplacian far above the
    surrounding material — so the texture test scored vandalism as MORE
    plausible than an honest repair, while rejecting classical inpainting for
    the crime of being smooth.

    What actually separates them is colour. Over the same frames, mean-luma
    delta against the surrounding ring was 1.7-19.8 for inpainting and
    60.9-92.9 for white bars: no overlap, and a wide margin either side of 30.
    So the gate is a colour-match test, plus a floor on the patch's own
    variation to catch a solid fill that happens to match its surroundings.

    A slightly soft patch is an acceptable repair; a patch that does not belong
    is not. Returns (ok, reason).
    """
    import numpy as np
    from PIL import ImageFilter

    mx_l = _MAX_LUMA_DELTA if max_luma_delta is None else max_luma_delta
    mx_c = _MAX_CHROMA_DELTA if max_chroma_delta is None else max_chroma_delta
    mn_s = _MIN_PATCH_STD if min_std is None else min_std

    rgb = np.asarray(candidate.convert('RGB'), dtype=np.float32)
    lum = np.asarray(candidate.convert('L'), dtype=np.float32)
    m = np.asarray(mask, dtype=np.uint8) > 127
    if not m.any():
        return True, ''
    ring = (np.asarray(mask.filter(ImageFilter.MaxFilter(size=41)), dtype=np.uint8) > 127) & ~m
    if ring.sum() < 64:
        return True, ''

    d_luma = abs(float(lum[m].mean()) - float(lum[ring].mean()))
    if d_luma > mx_l:
        return False, (f'repaint does not match its surroundings: mean luma off by {d_luma:.0f} (max {mx_l:.0f})')

    d_chroma = max(abs(float(rgb[m][:, c].mean()) - float(rgb[ring][:, c].mean())) for c in range(3))
    if d_chroma > mx_c:
        return False, (
            f'repaint colour does not match its surroundings: channel off by {d_chroma:.0f} (max {mx_c:.0f})'
        )

    patch_std = float(lum[m].std())
    if patch_std < mn_s:
        return False, (f'repaint is a solid fill (std {patch_std:.1f} < {mn_s:.1f})')
    return True, ''


def repair(
    image_path: str, boxes=None, pipe=None, seed: int = 0, out_path: str | None = None, log=None, max_rounds: int = 3
) -> dict:
    """Remove readable lettering from a frame. Never worsens it.

    Iterates to convergence rather than repainting once, because one pass does
    not finish the job:

    * the caller's box list is a REPORT, capped at the largest few (the gate
      quotes at most eight). flux_022 had ten regions, so a single pass over
      the reported boxes could never clear it. This re-reads the frame itself.
    * repainting can leave an edge, or the new texture can itself read as a
      letterform. Measured: frames with one small region still came back dirty
      after a clean repaint.

    Each round re-reads the frame, masks EVERY region above threshold, repaints
    and re-verifies. A round is kept only if it strictly reduces the number of
    regions; the frame is committed only when it reads clean. Otherwise the
    original is left exactly as it was and the caller still reports it flagged.

    The working image is held in memory and encoded ONCE at the end, so
    iterating does not stack JPEG generations.

    Returns {'repaired', 'strategy', 'reason', 'rounds', 'mask_area_frac',
             'before', 'after'}.
    """

    def _l(m):
        try:
            if log:
                log(m)
        except Exception as _exc:
            _zyg_log.debug('log callback failed: %s', _exc)

    res = {
        'repaired': False,
        'strategy': '',
        'reason': '',
        'rounds': 0,
        'mask_area_frac': 0.0,
        'before': '',
        'after': '',
        # every region actually repainted, across all rounds — the caller
        # needs this to check what changed, not the reported subset
        'repaired_boxes': [],
        # per-round, per-strategy outcomes. Without this the final reason
        # overwrites the interesting one: "no strategy reduced the lettering"
        # hides whether the repaint was rejected as implausible or simply
        # failed to remove the text, and those need opposite fixes.
        'trail': [],
    }
    try:
        from zyg_workflows import typography_ocr as tocr
    except Exception as e:
        res['reason'] = f'OCR judge unavailable ({e!r}) — cannot verify a repair'
        return res
    if not tocr.available():
        res['reason'] = 'OCR judge unavailable — cannot verify a repair'
        return res

    from PIL import Image, ImageChops

    try:
        original = Image.open(image_path).convert('RGB')
    except Exception as e:
        res['reason'] = f'cannot open frame ({e!r})'
        return res

    target = out_path or image_path
    tmp = target + '.repair.jpg'
    cur = original.copy()
    union = Image.new('L', original.size, 0)
    # Diffusion strategies first, classical last: ``flux`` only with a resident
    # in-process pipe, ``qwen_inpaint`` (ComfyUI) when the server is reachable —
    # that is the diffusion option on the Qwen documentary path, where pipe is
    # None and this sweep used to have only ``telea`` (P-10).
    strategies = (
        (['flux'] if pipe is not None else []) + (['qwen_inpaint'] if _qwen_inpaint_ready(pipe) else []) + ['telea']
    )
    if 'qwen_inpaint' in strategies:
        _l('typography repair: qwen_inpaint strategy armed (ComfyUI InstantX inpaint)')
    used: list = []

    try:
        for rnd in range(max_rounds):
            cur.save(tmp, quality=_JPEG_Q)
            regs = tocr.read_lettering(tmp)
            if regs is None:
                res['reason'] = 'judge went unavailable mid-repair'
                return res
            if rnd == 0:
                res['before'] = ', '.join(repr(r['text'])[:20] for r in regs[:3])
            if not regs:
                # Clean. Commit the in-memory result with a single encode.
                os.replace(tmp, target)
                res.update(
                    {
                        'repaired': True,
                        'rounds': rnd,
                        'strategy': '+'.join(used) or 'none',
                        'mask_area_frac': round(mask_area_frac(union), 4),
                        'reason': 'verified clean by OCR',
                    }
                )
                _l(
                    f'typography repair: cleared after {rnd} round(s) '
                    f'via {res["strategy"]}, '
                    f'{res["mask_area_frac"] * 100:.1f}% of frame repainted'
                )
                return res

            # Drop any single region that is too big to be a blemish; the rest
            # of the frame can still be repaired around it, and the leftover
            # region keeps the slot honestly flagged.
            _small = [
                r for r in regs if (r['bbox'][2] - r['bbox'][0]) * (r['bbox'][3] - r['bbox'][1]) / 1e6 <= _MAX_BOX_FRAC
            ]
            if not _small:
                res['reason'] = (
                    f'every flagged region is larger than '
                    f'{_MAX_BOX_FRAC * 100:.0f}% of the frame — that is '
                    f'the subject, not a blemish'
                )
                res['after'] = ', '.join(repr(r['text'])[:20] for r in regs[:3])
                return res
            mask = build_mask(original.size, [r['bbox'] for r in _small])
            af = mask_area_frac(ImageChops.lighter(union, mask))
            if af > _MAX_AREA_FRAC:
                res['reason'] = (
                    f'flagged region would reach {af * 100:.0f}% of the '
                    f'frame (> {_MAX_AREA_FRAC * 100:.0f}%) — that is a '
                    f're-render, not a repair'
                )
                res['after'] = ', '.join(repr(r['text'])[:20] for r in regs[:3])
                return res

            # Evaluate EVERY strategy this round and keep the best result,
            # rather than accepting the first one that helps.
            #
            # Measured on 12 real frames, first-past-the-post made the ordering
            # decide the outcome: FLUX-first cleared 8/12 in 406 s, classical-
            # only cleared 9/12 in 206 s. FLUX frequently leaves the lettering
            # untouched (trails full of `3->3`, `2->2`, `1->1`), and its partial
            # edits can leave the frame in a state where the fallback is then
            # rejected as a solid fill — so trying the "better" model first
            # actively cost hit rate.
            #
            # Scored: clearing the frame outright beats reducing it, fewer
            # regions beats more, and FLUX wins ties because it reconstructs
            # texture where the classical fill smears.
            _rank = {'flux': 0, 'qwen_inpaint': 0, 'telea': 1}
            best = None
            for strat in strategies:
                try:
                    if strat == 'flux':
                        painted = _flux_inpaint(cur, mask, pipe, seed + rnd)
                    elif strat == 'qwen_inpaint':
                        painted = _qwen_inpaint(cur, mask, seed + rnd)
                    else:
                        painted = _telea_inpaint(cur, mask)
                    cand = _composite(cur, painted, mask)
                    _pl_ok, _pl_why = _plausible(cand, mask)
                    if not _pl_ok:
                        res['trail'].append(f'r{rnd + 1}:{strat}:implausible:{_pl_why[:60]}')
                        _l(f'typography repair: {strat} rejected — {_pl_why}')
                        continue
                    cand.save(tmp, quality=_JPEG_Q)
                    after = tocr.read_lettering(tmp)
                    if after is None:
                        continue
                    res['trail'].append(f'r{rnd + 1}:{strat}:{len(regs)}->{len(after)} regions')
                    if len(after) >= len(regs):
                        continue  # no improvement
                    key = (len(after) > 0, len(after), _rank.get(strat, 9))
                    if best is None or key < best[0]:
                        best = (key, cand, strat)
                    if len(after) == 0 and _rank.get(strat, 9) == 0:
                        break  # a diffusion repaint cleared it — cannot do better
                except Exception as e:
                    res['trail'].append(f'r{rnd + 1}:{strat}:error:{e!r}'[:90])
                    _l(f'typography repair: {strat} failed ({e!r})')

            progressed = best is not None
            if progressed:
                _, cur, _strat = best
                union = ImageChops.lighter(union, mask)
                used.append(_strat)
                res['repaired_boxes'].extend([r['bbox'] for r in _small])
            if not progressed:
                res['after'] = ', '.join(repr(r['text'])[:20] for r in regs[:3])
                res['reason'] = f'no strategy reduced the lettering ({len(regs)} region(s) left after round {rnd + 1})'
                res['rounds'] = rnd + 1
                res['mask_area_frac'] = round(mask_area_frac(union), 4)
                return res
            res['rounds'] = rnd + 1

        # Ran out of rounds with lettering still present.
        cur.save(tmp, quality=_JPEG_Q)
        left = tocr.read_lettering(tmp) or []
        if not left:
            os.replace(tmp, target)
            res.update(
                {
                    'repaired': True,
                    'strategy': '+'.join(used),
                    'mask_area_frac': round(mask_area_frac(union), 4),
                    'reason': 'verified clean by OCR',
                }
            )
            return res
        res['after'] = ', '.join(repr(r['text'])[:20] for r in left[:3])
        res['reason'] = f'{len(left)} region(s) still readable after {max_rounds} rounds — original kept'
        res['mask_area_frac'] = round(mask_area_frac(union), 4)
        return res
    finally:
        if os.path.exists(tmp):
            try:
                os.remove(tmp)
            except Exception as _exc:
                _zyg_log.debug('temporary file cleanup skipped: %s', _exc)
