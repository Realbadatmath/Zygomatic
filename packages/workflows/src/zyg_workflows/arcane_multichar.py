# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""arcane_multichar.py — compose 2-3 trained-LoRA characters into ONE arcane scene.

Proven method (2026-07-28):
  1. BASE PLATE  — SDXL txt2img + native regional conditioning (ConditioningSetArea) positions
     N people; region prompts are gender/age-locked and clothing is sanitized (the word "dress"
     in a bible reads as a woman's dress to SDXL).
  2. FULL ARCANE — style_arcane + depth img2img over the whole plate (bodies + background), NO
     character LoRA → a coherent arcane scene with generic faces.
  3. IDENTITY    — per character: a tight head crop → depth_controlnet_arcane_restyle(char_id)
     (each char's own bible recipe, e.g. Abel r4 / Cornelis default) → strong arcane identity →
     feather-composite back onto the plate.

ArcFace can NOT validate painterly faces (scores ~0.11 even when perfect) — identity here comes
from the depth-ControlNet pass, which is visually verified. Single-character rendering is
unaffected: this module is only invoked when >1 char_id is requested.
"""

import os
import time
import shutil
import re
import numpy as np
from PIL import Image, ImageFilter, ImageDraw

from zyg_workflows.paths import tmp_dir

# ── QC block signal (fail-safe import) ───────────────────────────────────────
# qc_contract.QCBlocked derives from BaseException on purpose so that the
# fail-safe `except Exception` handlers in this file cannot silently convert a
# deliberate mode=block stop into a shrug. The fallback below is a private class
# that nothing raises, so behaviour is unchanged if qc_contract is unavailable.
try:
    from zyg_workflows.qc_contract import QCBlocked as _QCBlocked
except Exception:  # pragma: no cover

    class _QCBlocked(BaseException):
        pass


import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)


_JUG = 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'

# LICENCE (2026-08-03) — this stack ships COMMERCIALLY, so Apache-2.0/MIT/BSD/CC0 only.
# Depth-Anything-V2 is split-licensed by size: **Small (vits) is Apache-2.0; Base (vitb),
# Large (vitl) and Giant (vitg) are CC-BY-NC-4.0**. This module and arcane_restyle.py both
# ran `depth_anything_v2_vitb.pth`, and Base is the only variant on disk
# (custom_nodes/comfyui_controlnet_aux/ckpts/depth-anything/Depth-Anything-V2-Base/).
#
# This is NOT the Blender case. Blender's GPL is a tool licence that explicitly does not
# encumber rendered output; CC-BY-NC-4.0 restricts the USE, so running that checkpoint to
# produce assets intended for commercial release is the thing it forbids. The depth map is
# an input the diffusion is conditioned on, not an incidental tool artefact.
#
# vits is the same family and node (the preprocessor already offers it) — depth maps are a
# little coarser, which for a style/structure guide at strength 0.5 is immaterial. Override
# with ZYG_DEPTH_CKPT only if you have verified the replacement's licence yourself.
# NOTE: assets restyled BEFORE this date were produced with vitb and should be regenerated
# before they are published.
_DEPTH_CKPT = os.environ.get('ZYG_DEPTH_CKPT', 'depth_anything_v2_vits.pth')
_NEG_BASE = (
    'deformed, extra limbs, fused bodies, merged people, two heads, blurry, lowres, cartoon, '
    'anime, cloned face, disfigured, watermark, text, bad anatomy, woman, female, girl, '
    'dress, gown, feminine, makeup'
)
_NEG_STYLE = 'photograph, photorealistic, dslr, smooth airbrushed, flat anime, cel shaded, lowres, watermark, text'


def _log_noop(_m):
    pass


def _free(log=None):
    """Evict ComfyUI models between heavy passes — 4 back-to-back SDXL+depth submits
    otherwise exhaust VRAM and crash the server (observed 2026-07-28)."""
    try:
        from zyg_workflows import _comfy_client as CC

        CC.free_vram(unload_models=True, free_memory=True)
    except Exception as e:
        if log:
            log(f'[multichar] free_vram skipped ({e})')


def _sanitize_clothing(cloth: str) -> str:
    """The word 'dress' (period sense) makes SDXL render a woman — strip/replace it."""
    c = cloth or ''
    c = re.sub(r"\b(merchant'?s[- ]son'?s?|merchant'?s)\s+dress\b", 'attire', c, flags=re.I)
    c = re.sub(r'\bdress\b', 'attire', c, flags=re.I)
    c = re.sub(r'\bgown\b', 'coat', c, flags=re.I)
    return c.strip()


# Per-character framing phrase appended to each region prompt.
_FRAMING = {
    'waist-up': 'waist up',
    'three-quarter': 'three-quarter length, from the knees up, standing',
    'full-body': 'full body, head to toe, standing, feet visible',
}


def _char_desc(char_id: str, shot: str = 'waist-up') -> dict:
    from zyg_workflows import character_bible_service as CBS

    p = CBS.load(char_id) or {}
    ident = p.get('identity') or {}
    dp = p.get('default_presentation') or {}
    sp = p.get('style_profile') or {}
    sex = ident.get('sex') or ident.get('gender') or 'male'
    age = ident.get('age')
    cloth = _sanitize_clothing(dp.get('default_clothing') or sp.get('default_clothing') or '')
    noun = 'man' if str(sex).lower().startswith('m') else 'woman'
    try:
        if age and int(age) < 18:
            noun = 'teenage boy' if noun == 'man' else 'teenage girl'
    except (TypeError, ValueError) as _exc:
        _zyg_log.debug('unparsable age %r, keeping the adult noun: %s', age, _exc)
    frame = _FRAMING.get(shot, _FRAMING['waist-up'])
    # CANON-FIRST (2026-07-29 identity-drift fix): when a pixel-derived canon appearance
    # exists it REPLACES the free-text bible description — text can no longer contradict
    # how the character actually looks in the LoRA data (the drift's root cause).
    canon_neg = ''
    try:
        from zyg_workflows import canon_service as CS

        cp = CS.canon_phrase(char_id)
        if cp:
            region_prompt = f'{cp[:240]}, {frame}'.strip(', ')
            canon_neg = CS.canon_negative(char_id)
        else:
            region_prompt = f'a {age} year old {sex} {noun}, {cloth[:170]}, {frame}'.strip(', ')
    except Exception:
        region_prompt = f'a {age} year old {sex} {noun}, {cloth[:170]}, {frame}'.strip(', ')
    return {
        'cid': char_id,
        'sex': sex,
        'age': age,
        'cloth': cloth,
        'noun': noun,
        'region_prompt': region_prompt,
        'canon_negative': canon_neg,
        'lora': ((p.get('conditioning') or {}).get('sdxl_lora_path') or ''),
    }


def _feather(bw, bh, ins=0.13):
    m = Image.new('L', (bw, bh), 0)
    ImageDraw.Draw(m).ellipse([int(bw * ins), int(bh * ins), int(bw * (1 - ins)), int(bh * (1 - ins))], fill=255)
    return m.filter(ImageFilter.GaussianBlur(radius=max(bw, bh) * 0.11))


_BG_FRAMING = {
    'waist-up': 'waist-up medium shot',
    'three-quarter': 'three-quarter wide shot, from the knees up, standing on the floor',
    'full-body': 'full body wide shot, entire bodies and feet visible, standing on the floor',
}


def _base_plate(
    descs,
    scene_desc,
    out_path,
    seed,
    W,
    H,
    log,
    shot='waist-up',
    bg_prompt=None,
    region_prompts=None,
    region_negatives=None,
    region_strength=1.15,
    bg_strength=1.0,
):
    """SDXL regional txt2img — positions len(descs) people across equal columns.

    bg_prompt        : override the full-frame background/composition prompt (e.g. a seated
                       two-people-at-a-table scene) instead of the default 'standing side by side'.
    region_prompts   : per-person positive overrides so each figure gets a distinct pose/action.
    region_negatives : per-person NEGATIVE prompts, area-masked to that person's column, so the
                       father's region actively repels 'quill/writing' and the son's repels 'pipe'.
                       This kills the cross-prop bleed (father-with-a-quill) at its source.
    region_strength  : ConditioningSetArea strength per person column. 1.0 = clean; >1.0 over-drives
                       the columns and worsens bleed (default 1.15 kept for back-compat).
    bg_strength      : strength of the full-frame background conditioning. <1.0 stops the shared
                       scene prompt from leaking its tokens (a stray 'quill'/'pipe') into the columns.
    """
    from zyg_workflows import _comfy_client as CC

    n = len(descs)
    col = ((W // n) // 8) * 8
    g = {'10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}}}
    _framing = _BG_FRAMING.get(shot, _BG_FRAMING['waist-up'])
    bg = bg_prompt or (
        f'{n} men standing together side by side, {_framing}, all facing the camera, '
        f'faces clearly visible and detailed, {scene_desc}, cinematic photograph, photorealistic, sharp focus'
    )
    g['90'] = {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': bg}}
    if bg_strength != 1.0:  # weaken the full-frame scene cond so it stops leaking into columns
        g['91'] = {
            'class_type': 'ConditioningSetArea',
            'inputs': {'conditioning': ['90', 0], 'width': W, 'height': H, 'x': 0, 'y': 0, 'strength': bg_strength},
        }
        bg_ref = ['91', 0]
    else:
        bg_ref = ['90', 0]
    g['95'] = {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': _NEG_BASE}}
    combine_from = None
    neg_from = ['95', 0]  # start from the global full-frame negative
    for i, d in enumerate(descs):
        te = f'2{i}'
        area = f'3{i}'
        _rp = (
            region_prompts[i]
            if (region_prompts and i < len(region_prompts) and region_prompts[i])
            else d['region_prompt']
        )
        g[te] = {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': _rp}}
        x = min(W - col, i * col)
        g[area] = {
            'class_type': 'ConditioningSetArea',
            'inputs': {'conditioning': [te, 0], 'width': col, 'height': H, 'x': x, 'y': 0, 'strength': region_strength},
        }
        if combine_from is None:
            combine_from = [area, 0]
        else:
            cnode = f'6{i}'  # 61/62 — MUST NOT collide with 40/41/42 (latent/ksampler/decode)
            g[cnode] = {
                'class_type': 'ConditioningCombine',
                'inputs': {'conditioning_1': combine_from, 'conditioning_2': [area, 0]},
            }
            combine_from = [cnode, 0]
        # per-region masked NEGATIVE — repels the other person's prop from this column
        rn = region_negatives[i] if (region_negatives and i < len(region_negatives) and region_negatives[i]) else None
        if rn:
            nte = f'7{i}'  # 70/71 — negative text encodes
            narea = f'8{i}'  # 80/81 — negative areas
            ncomb = f'9{6 + i}'  # 96/97/98 — negative combines (90/91/95 already used)
            g[nte] = {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': rn}}
            g[narea] = {
                'class_type': 'ConditioningSetArea',
                'inputs': {'conditioning': [nte, 0], 'width': col, 'height': H, 'x': x, 'y': 0, 'strength': 1.0},
            }
            g[ncomb] = {
                'class_type': 'ConditioningCombine',
                'inputs': {'conditioning_1': neg_from, 'conditioning_2': [narea, 0]},
            }
            neg_from = [ncomb, 0]
    # fold in the full-frame background conditioning last
    g['68'] = {
        'class_type': 'ConditioningCombine',
        'inputs': {'conditioning_1': combine_from, 'conditioning_2': bg_ref},
    }
    g['40'] = {'class_type': 'EmptyLatentImage', 'inputs': {'width': W, 'height': H, 'batch_size': 1}}
    g['41'] = {
        'class_type': 'KSampler',
        'inputs': {
            'model': ['10', 0],
            'positive': ['68', 0],
            'negative': neg_from,
            'latent_image': ['40', 0],
            'seed': seed,
            'steps': 32,
            'cfg': 7.0,
            'sampler_name': 'dpmpp_2m',
            'scheduler': 'karras',
            'denoise': 1.0,
        },
    }
    g['42'] = {'class_type': 'VAEDecode', 'inputs': {'samples': ['41', 0], 'vae': ['10', 2]}}
    g['50'] = {'class_type': 'SaveImage', 'inputs': {'images': ['42', 0], 'filename_prefix': 'ZygMCBase'}}
    outs = CC.submit(g, timeout_s=600)
    shutil.copy2(outs[0], out_path)
    return out_path


def _repair_hands(src_path, out_path, seed, log, denoise=0.45, steps=25):
    """Detect each hand (hand_yolov8s) and re-diffuse it UPSCALED via Impact Pack DetailerForEach:
    crops each hand, upscales to guide_size so SDXL has the pixels it needs for fingers, re-renders
    correct anatomy, stitches back. Runs on the PHOTOREAL base plate BEFORE the arcane restyle so the
    depth-ControlNet restyle then locks in the corrected geometry. Fail-safe: any error keeps the
    original plate. Returns out_path."""
    from zyg_workflows import _comfy_client as CC

    try:
        st = CC.stage_input_image(src_path)
        # exposure-neutral wording (2026-07-29): the earlier 'detailed skin, sharp focus'
        # prompt re-lit repaired hands into clipped highlights that then propagated to video
        pos = (
            'a single well-formed human hand, exactly five fingers, correct natural hand anatomy, '
            'lit softly by the ambient scene light, natural shading matching the surroundings, '
            'holding the object naturally'
        )
        neg = (
            'extra hand, second hand, extra fingers, sixth finger, fused fingers, missing fingers, '
            'deformed hand, mutated hand, malformed, blurry, low detail, '
            'overexposed, glowing skin, bright highlight, spotlight'
        )
        g = {
            '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
            '2': {'class_type': 'LoadImage', 'inputs': {'image': st}},
            '3': {'class_type': 'UltralyticsDetectorProvider', 'inputs': {'model_name': 'bbox/hand_yolov8s.pt'}},
            '4': {
                'class_type': 'BboxDetectorSEGS',
                'inputs': {
                    'bbox_detector': ['3', 0],
                    'image': ['2', 0],
                    'threshold': 0.40,
                    'dilation': 16,
                    'crop_factor': 3.0,
                    'drop_size': 10,
                    'labels': 'all',
                },
            },
            '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': pos}},
            '6': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': neg}},
            '7': {
                'class_type': 'DetailerForEach',
                'inputs': {
                    'image': ['2', 0],
                    'segs': ['4', 0],
                    'model': ['1', 0],
                    'clip': ['1', 1],
                    'vae': ['1', 2],
                    'guide_size': 512.0,
                    'guide_size_for': True,
                    'max_size': 1024.0,
                    'seed': seed,
                    'steps': steps,
                    'cfg': 6.5,
                    'sampler_name': 'dpmpp_2m',
                    'scheduler': 'karras',
                    'positive': ['5', 0],
                    'negative': ['6', 0],
                    'denoise': denoise,
                    'feather': 12,
                    'noise_mask': True,
                    'force_inpaint': True,
                    'wildcard': '',
                    'cycle': 1,
                },
            },
            '8': {'class_type': 'SaveImage', 'inputs': {'images': ['7', 0], 'filename_prefix': 'ZygHandFix'}},
        }
        outs = CC.submit(g, timeout_s=600)
        if outs and os.path.isfile(outs[0]):
            shutil.copy2(outs[0], out_path)
            log('[multichar] hand-repair pass done')
            return out_path
        log('[multichar] hand-repair produced no output — keeping unrepaired plate')
    except Exception as e:
        log(f'[multichar] hand-repair failed ({e}) — keeping unrepaired plate')
    if os.path.abspath(src_path) != os.path.abspath(out_path):
        shutil.copy2(src_path, out_path)
    return out_path


def soften_highlights(src_path, out_path=None, knee=215.0, strength=0.65, log_fn=None):
    """Deterministic exposure fix: compress luma above `knee` with a soft rolloff, blended
    only where highlights actually clip (feathered cluster mask). Diffusion prompts cannot
    reliably darken scene-lit hot spots (2026-07-29 measured) — this can, without touching
    anything else. Returns out_path."""
    log = log_fn or _log_noop

    out_path = out_path or src_path
    im = Image.open(src_path).convert('RGB')
    arr = np.asarray(im, dtype=np.float32)
    luma = arr.max(axis=2)
    hot = (luma > 240).astype(np.uint8) * 255
    if hot.mean() < 0.2:  # nothing meaningfully clipped
        if out_path != src_path:
            im.save(out_path)
        return out_path
    m = Image.fromarray(hot, 'L').filter(ImageFilter.MaxFilter(9)).filter(ImageFilter.GaussianBlur(14))
    mask = np.asarray(m, dtype=np.float32)[:, :, None] / 255.0 * strength
    # soft-knee compression of everything above the knee
    over = np.clip(luma - knee, 0, None)
    scale = np.where(luma > 0, (knee + over * 0.45) / np.maximum(luma, 1e-4), 1.0)[:, :, None]
    toned = arr * scale
    outa = arr * (1.0 - mask) + toned * mask
    Image.fromarray(np.clip(outa, 0, 255).astype('uint8')).save(out_path)
    log(f'[highlights] rolled off {float((hot > 0).mean() * 100):.1f}% clipped px')
    return out_path


def _arcane_full(src_path, out_path, scene_desc, seed, log):
    """Style-only arcane restyle of the whole plate (no character LoRA)."""
    from zyg_workflows import _comfy_client as CC

    with Image.open(src_path) as im:
        w, h = im.size
    st = CC.stage_input_image(src_path)
    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
        '11': {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': ['10', 0],
                'clip': ['10', 1],
                'lora_name': 'style_arcane.safetensors',
                'strength_model': 1.15,
                'strength_clip': 1.15,
            },
        },
        '14': {'class_type': 'LoadImage', 'inputs': {'image': st}},
        '15': {
            'class_type': 'DepthAnythingV2Preprocessor',
            'inputs': {'image': ['14', 0], 'ckpt_name': _DEPTH_CKPT, 'resolution': 1024},
        },
        '16': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['14', 0], 'vae': ['10', 2]}},
        '18': {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': 'controlnet-depth-sdxl.safetensors'}},
        '20': {
            'class_type': 'CLIPTextEncode',
            'inputs': {
                'clip': ['11', 1],
                'text': f'League of Legends Arcane splash art, bold oil painting, {scene_desc}, painterly, cinematic',
            },
        },
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['11', 1], 'text': _NEG_STYLE}},
        '19': {
            'class_type': 'ControlNetApplyAdvanced',
            'inputs': {
                'positive': ['20', 0],
                'negative': ['21', 0],
                'control_net': ['18', 0],
                'image': ['15', 0],
                'strength': 0.5,
                'start_percent': 0.0,
                'end_percent': 0.8,
            },
        },
        '31': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['11', 0],
                'positive': ['19', 0],
                'negative': ['19', 1],
                'latent_image': ['16', 0],
                'seed': seed,
                'steps': 30,
                'cfg': 6.5,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 0.6,
            },
        },
        '40': {'class_type': 'VAEDecode', 'inputs': {'samples': ['31', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['40', 0], 'filename_prefix': 'ZygMCPlate'}},
    }
    outs = CC.submit(g, timeout_s=600)
    res = Image.open(outs[0]).convert('RGB')
    if res.size != (w, h):
        res = res.resize((w, h), Image.LANCZOS)
    res.save(out_path)
    return out_path


def _face_boxes(base_img, n, log):
    """Detect one face per equal column (leftmost column → descs[0], etc.)."""
    from zyg_workflows import identity_qc_service as IQ

    W, H = base_img.size
    boxes = []
    tmpd = os.path.dirname(base_img.filename) if getattr(base_img, 'filename', None) else str(tmp_dir())
    for i in range(n):
        x0f = (W // n) * i
        x1f = W if i == n - 1 else (W // n) * (i + 1)
        reg = base_img.crop((x0f, 0, x1f, H))
        rp = os.path.join(tmpd, f'_mcreg_{i}.png')
        reg.save(rp)
        v = IQ.embed_images([rp], log_fn=_log_noop).get(rp) or {}
        if not v.get('face_detected') or not v.get('bbox'):
            boxes.append(None)
            continue
        bx0, by0, bx1, by1 = v['bbox']
        iw = v.get('img_w') or 1
        ih = v.get('img_h') or 1
        sx = (x1f - x0f) / iw
        sy = H / ih
        cx = x0f + (bx0 + bx1) / 2 * sx
        cy = (by0 + by1) / 2 * sy
        fw = (bx1 - bx0) * sx
        fh = (by1 - by0) * sy
        side = max(fw, fh) * 1.7
        X0 = max(0, int(cx - side / 2))
        Y0 = max(0, int(cy - side * 0.60))
        X1 = min(W, int(cx + side / 2))
        Y1 = min(H, int(cy + side * 0.52))
        boxes.append((X0, Y0, X1, Y1))
    return boxes


def _identity_pass(base_photoreal_path, plate_path, bbox, char_id, prof, workdir, log):
    from zyg_workflows import _comfy_client as CC  # noqa: F401  (arcane_restyle uses it internally)
    from zyg_workflows import arcane_restyle as AR

    src = Image.open(base_photoreal_path).convert('RGB')
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    crop = src.crop(bbox)
    up = 1024
    crop_up = crop.resize((up, max(1, int(up * bh / bw))), Image.LANCZOS)
    ctmp = os.path.join(workdir, f'_mccrop_{char_id[:8]}.png')
    crop_up.save(ctmp)
    otmp = os.path.join(workdir, f'_mcface_{char_id[:8]}.png')
    ok = AR.depth_controlnet_arcane_restyle(char_id, prof, ctmp, otmp, seed=101, log_fn=_log_noop)
    if not ok or not os.path.isfile(otmp):
        log(f'[multichar] identity pass FAILED for {char_id[:8]} — leaving generic arcane face')
        return plate_path
    face = Image.open(otmp).convert('RGB').resize((bw, bh), Image.LANCZOS)
    plate = Image.open(plate_path).convert('RGB')
    plate.paste(face, (x0, y0), _feather(bw, bh))
    plate.save(plate_path)
    return plate_path


def generate_multichar_still(
    char_ids,
    scene_desc,
    out_path,
    seed=7,
    W=1152,
    H=832,
    log_fn=None,
    shot='waist-up',
    bg_prompt=None,
    region_prompts=None,
    region_negatives=None,
    region_strength=1.15,
    bg_strength=1.0,
    repair_hands=False,
):
    """Compose 2-3 trained-LoRA characters into one arcane scene. Returns out_path or None.

    char_ids   : list of 2-3 character ids (each must have conditioning.sdxl_lora_path)
    scene_desc : short setting phrase, e.g. "in a 1672 Dutch Golden Age interior, window light"
    shot       : 'waist-up' (default) | 'three-quarter' | 'full-body' — framing of the figures.
    bg_prompt / region_prompts : optional composition overrides (see _base_plate) — used for
                 non-standing scenes such as two characters seated at a table with distinct actions.
    region_negatives / region_strength / bg_strength : anti-bleed controls (see _base_plate) —
                 kill cross-prop leakage (father-with-a-quill) and the duplicated-action extra hand.
    repair_hands : run a hand-detailer pass on the photoreal plate (before restyle) to fix
                 small/malformed/extra-finger hands. Fail-safe.
    """
    log = log_fn or _log_noop
    char_ids = [c for c in (char_ids or []) if c]
    if len(char_ids) < 2:
        log('[multichar] need >=2 char_ids — abort')
        return None
    if len(char_ids) > 3:
        log(f'[multichar] capping {len(char_ids)} → 3 characters (identity degrades beyond 3)')
        char_ids = char_ids[:3]
    from zyg_workflows import arcane_restyle as AR

    prof = dict((AR.load_profile('arcane_animation') or {}).get('restyle') or {})
    descs = [_char_desc(c, shot=shot) for c in char_ids]
    for d in descs:
        if not d['lora'] or not os.path.isfile(d['lora']):
            log(f'[multichar] {d["cid"][:8]} has no SDXL LoRA — abort')
            return None
    workdir = os.path.dirname(os.path.abspath(out_path)) or '.'
    os.makedirs(workdir, exist_ok=True)
    t0 = time.time()

    if not region_negatives:
        # canon-first: per-character anti-drift negatives derived from the pixel canon
        _cn = [d.get('canon_negative') or '' for d in descs]
        region_negatives = _cn if any(_cn) else None
    base = os.path.join(workdir, '_mc_base.png')
    _base_plate(
        descs,
        scene_desc,
        base,
        seed,
        W,
        H,
        log,
        shot=shot,
        bg_prompt=bg_prompt,
        region_prompts=region_prompts,
        region_negatives=region_negatives,
        region_strength=region_strength,
        bg_strength=bg_strength,
    )
    log(f'[multichar] base plate ({time.time() - t0:.0f}s)')
    _free(log)

    if repair_hands:
        _repair_hands(base, base, seed, log)  # fix hands on the photoreal plate before restyle
        _free(log)

    plate = out_path
    _arcane_full(base, plate, scene_desc, seed, log)
    log('[multichar] full-plate arcane restyle done')
    _free(log)

    base_img = Image.open(base)
    base_img.filename = base
    boxes = _face_boxes(base_img, len(descs), log)
    for d, bbox in zip(descs, boxes):
        if bbox is None:
            log(f'[multichar] no face found for {d["cid"][:8]} — skipping its identity pass')
            continue
        try:
            _identity_pass(base, plate, bbox, d['cid'], prof, workdir, log)
            log(f'[multichar] identity locked: {d["cid"][:8]}')
        except Exception as e:
            log(f'[multichar] identity pass errored for {d["cid"][:8]} ({e}) — keeping generic arcane face')
        _free(log)
    log(f'[multichar] DONE → {out_path} ({time.time() - t0:.0f}s total)')
    return out_path


def relock_identity(plate_path, char_ids, log_fn=None):
    """IDENTITY RE-LOCK AS THE LAST IMAGE OP (2026-07-29 drift fix): after ANY edit chain
    (hand repair, prop insert, relight...) re-assert each character's canonical face via the
    proven SDXL char-LoRA + depth-ControlNet face pass. Detects one face per column on the
    CURRENT plate and re-renders it in place. Fail-safe per face. Returns plate_path."""
    log = log_fn or _log_noop
    from zyg_workflows import arcane_restyle as AR

    prof = dict((AR.load_profile('arcane_animation') or {}).get('restyle') or {})
    char_ids = [c for c in (char_ids or []) if c]
    if not char_ids:
        return plate_path
    workdir = os.path.dirname(os.path.abspath(plate_path)) or '.'
    img = Image.open(plate_path)
    img.filename = plate_path
    boxes = _face_boxes(img, len(char_ids), log)
    for cid, bbox in zip(char_ids, boxes):
        if bbox is None:
            log(f'[relock] no face found for {cid[:8]} — skipped')
            continue
        try:
            _identity_pass(plate_path, plate_path, bbox, cid, prof, workdir, log)
            log(f'[relock] identity re-locked: {cid[:8]}')
        except Exception as e:
            log(f'[relock] failed for {cid[:8]} ({e}) — keeping current face')
        _free(log)
    return plate_path


def relock_region(plate_path, bbox_frac, prompt, negative='', denoise=0.55, seed=17, log_fn=None):
    """PROP RE-LOCK (2026-07-30): SDXL-inpaint a fixed region of a plate toward a described
    canon look (e.g. the clay pipe that chained video segments keep re-inventing). The
    region-mask sibling of relock_identity. bbox_frac: (fx0, fy0, fx1, fy1). Fail-safe."""
    log = log_fn or _log_noop
    from zyg_workflows import _comfy_client as CC

    try:
        im = Image.open(plate_path).convert('RGB')
        W, H = im.size
        fx0, fy0, fx1, fy1 = bbox_frac
        mask = Image.new('L', (W, H), 0)
        ImageDraw.Draw(mask).rectangle([int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)], fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(6))
        mpath = plate_path + '.relock_mask.png'
        mask.save(mpath)
        st_img = CC.stage_input_image(plate_path)
        st_mask = CC.stage_input_image(mpath)
        g = {
            '1': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
            '2': {'class_type': 'LoadImage', 'inputs': {'image': st_img}},
            '3': {'class_type': 'LoadImage', 'inputs': {'image': st_mask}},
            '4': {'class_type': 'ImageToMask', 'inputs': {'image': ['3', 0], 'channel': 'red'}},
            '5': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['1', 1], 'text': prompt}},
            '6': {
                'class_type': 'CLIPTextEncode',
                'inputs': {'clip': ['1', 1], 'text': (negative + ', deformed, blurry, text, watermark').strip(', ')},
            },
            '7': {
                'class_type': 'VAEEncodeForInpaint',
                'inputs': {'pixels': ['2', 0], 'vae': ['1', 2], 'mask': ['4', 0], 'grow_mask_by': 10},
            },
            '8': {
                'class_type': 'KSampler',
                'inputs': {
                    'model': ['1', 0],
                    'positive': ['5', 0],
                    'negative': ['6', 0],
                    'latent_image': ['7', 0],
                    'seed': int(seed),
                    'steps': 26,
                    'cfg': 6.5,
                    'sampler_name': 'dpmpp_2m',
                    'scheduler': 'karras',
                    'denoise': float(denoise),
                },
            },
            '9': {'class_type': 'VAEDecode', 'inputs': {'samples': ['8', 0], 'vae': ['1', 2]}},
            '10': {'class_type': 'SaveImage', 'inputs': {'images': ['9', 0], 'filename_prefix': 'ZygRegionLock'}},
        }
        outs = CC.submit(g, timeout_s=600)
        if outs and os.path.isfile(outs[0]):
            res = Image.open(outs[0]).convert('RGB')
            if res.size != (W, H):
                res = res.resize((W, H), Image.LANCZOS)
            res.save(plate_path)
            log('[region-lock] done')
            os.remove(mpath)
            return plate_path
    except Exception as e:
        log(f'[region-lock] failed ({e}) — plate unchanged')
    return plate_path


def generate_multichar_clip(
    char_ids,
    scene_desc,
    out_dir,
    motion='subtle movement, gentle head turns',
    seconds=5,
    seed=7,
    test_mode=True,
    still_path=None,
    log_fn=None,
    shot='waist-up',
    wan_prompt=None,
    flow_shift=1.5,
    steps=None,
    bg_prompt=None,
    region_prompts=None,
    region_negatives=None,
    region_strength=1.15,
    bg_strength=1.0,
    repair_hands=False,
    lock_set=False,
):
    """Compose a multi-character arcane STILL then animate it via Wan I2V. Returns clip path or None.

    still_path : reuse an already-composed still instead of re-rendering it.
    test_mode  : True → one native ~5s sub-clip (Phase-1 test mode) for fast inspection.
    shot       : framing for a freshly-composed still ('waist-up'|'three-quarter'|'full-body').
    wan_prompt : verbatim WAN motion prompt override. When set it is used as-is (identity/style
                 clauses should be included by the caller) instead of the default steady-shot text —
                 this is how locomotion ("walking around") is requested.
    flow_shift : scheduler flow-shift. Higher → more motion (walking) but more drift; lower → steadier.
    steps      : sampler-steps override for the test sub-clip (None → 12 in test mode).
    """
    log = log_fn or _log_noop
    os.makedirs(out_dir, exist_ok=True)
    # full-run debug trace: params, prompts, graphs, snapshots, QC verdicts → out_dir/debug/
    try:
        from zyg_workflows import pipeline_debug as DBG

        dbg = DBG.DebugRun(out_dir, name='multichar_clip')
        DBG.set_active(dbg)
        dbg.stage(
            'setup',
            params={
                'char_ids': char_ids,
                'scene_desc': scene_desc,
                'shot': shot,
                'seed': seed,
                'flow_shift': flow_shift,
                'steps': steps,
                'lock_set': lock_set,
                'repair_hands': repair_hands,
                'wan_prompt': (wan_prompt or '')[:400],
            },
        )
    except Exception:
        dbg = None
    still = still_path
    if not (still and os.path.isfile(still)):
        still = os.path.join(out_dir, 'multichar_still.png')
        if not generate_multichar_still(
            char_ids,
            scene_desc,
            still,
            seed=seed,
            log_fn=log,
            shot=shot,
            bg_prompt=bg_prompt,
            region_prompts=region_prompts,
            region_negatives=region_negatives,
            region_strength=region_strength,
            bg_strength=bg_strength,
            repair_hands=repair_hands,
        ):
            return None
    # still QC gate: exposure per character column + hand count. Failures are LOGGED loudly
    # (not yet blocking — flip to hard-block once thresholds are field-calibrated).
    if dbg:
        try:
            n = max(1, len([c for c in (char_ids or []) if c]))
            regs = [(f'char{i}', i / n, 0.30, (i + 1) / n, 0.95) for i in range(n)]
            dbg.stage('still_qc')
            dbg.snapshot('final_still', still)
            q = dbg.qc_still('final_still', still, char_regions=regs, n_people=n)
            for c in q.get('checks', []):
                if not c.get('ok'):
                    log(f'[multichar][QC-STILL FAIL] {c.get("check")}: {c.get("note")}')
        except Exception as _exc:
            _zyg_log.debug('still QC debug pass skipped: %s', _exc)
    try:
        from zyg_workflows import wan_video_service as WAN
    except Exception as e:
        log(f'[multichar-clip] wan import failed: {e}')
        return None
    m = {
        'subject': 'characters',
        'tag': 'multichar',
        'slot_seconds': seconds,
        'index': 0,
        'path': still,
        'emotion': 'neutral',
        'shot_type': 'medium',
        'seed': seed,
        # multichar scenes are locked-camera by design → curated static negative
        # (no anti-static tokens), trained static-shot grammar, no cinematic suffix
        'static_shot': True,
    }
    if wan_prompt:
        # Used verbatim by _build_prompt (+ cinematic suffix). Full motion control for walking.
        m['wan_prompt'] = wan_prompt
    else:
        m['prompt'] = (
            f'{scene_desc}. The characters stand mostly still with only subtle natural motion '
            f'({motion}) — gentle breathing, a slight head turn, soft blinking. Faces stay perfectly '
            f'stable, consistent and undistorted; each keeps their exact appearance. No new people '
            f'appear. Cinematic arcane oil painting style, steady shot.'
        )
    res = WAN.generate(
        [m],
        out_dir,
        n_clips=1,
        n_chained=1 if test_mode else None,
        frames=81 if test_mode else None,
        steps=(steps if steps is not None else (12 if test_mode else None)),
        flow_shift=flow_shift,
        log_fn=log,
        visual_style='cinematic',
    )
    if not res:
        log('[multichar-clip] wan produced no clip')
        return None
    clip = res[0].get('path')
    if lock_set and clip:
        # set-lock composite: pin walls/furniture/props to the original still, keep only
        # genuinely-moving regions from the video (fail-safe: raw clip kept on any failure)
        try:
            from zyg_workflows import wan_setlock as SL

            locked = SL.lock_background(clip, still, clip.replace('.mp4', '_setlocked.mp4'), log_fn=log)
            if locked:
                clip = locked
        except Exception as e:
            log(f'[multichar-clip] set-lock skipped ({e})')
    # clip QC: HONEST per-region motion (characters must move, set must not) + drift checks
    if dbg and clip:
        try:
            ids = [c for c in (char_ids or []) if c]
            n = max(1, len(ids))
            regs = [(f'char{i}', i / n, 0.30, (i + 1) / n, 0.95) for i in range(n)]
            # Identity gets the FULL-HEIGHT column, not the body region above: the
            # motion regions start at 0.30 and in a medium shot the head sits above
            # that line, so reusing them would hand the face tracker a chin.
            id_chars = [
                {'char_id': c, 'style': 'arcane', 'roi': [i / n, 0.0, (i + 1) / n, 1.0] if n > 1 else None}
                for i, c in enumerate(ids)
            ]
            dbg.stage('clip_qc')
            q = dbg.qc_clip('final_clip', clip, char_regions=regs, still_path=still, identity_chars=id_chars or None)
            for c in q.get('checks', []):
                if not c.get('ok'):
                    log(f'[multichar][QC-CLIP FAIL] {c.get("check")}: {c.get("note")}')
            # ADVISORY: who was actually in the clip. Never fails the run — this
            # instrument was benched for the first time on 2026-09-02 and has not
            # earned a vote in the pass/fail ledger.
            idn = q.get('identity') or {}
            for cid, r in (idn.get('per_char') or {}).items():
                led = r.get('ledger') or {}
                log(
                    f'[multichar][identity] {cid}: cos={r.get("cosine")} '
                    f'p10={r.get("cosine_p10")} spread={r.get("spread")} '
                    f'pass_frac={r.get("pass_frac")} '
                    f'found={led.get("found")} not_found={led.get("not_found")} '
                    f'not_detectable={led.get("not_detectable")} '
                    f'unmeasurable={led.get("unmeasurable")} -> {r.get("reason")}'
                )
            if idn.get('sidecar'):
                log(f'[multichar][identity] -> {idn["sidecar"]}')
            elif idn.get('measured') is False:
                log(f'[multichar][identity] not measured: {idn.get("reason")}')
            v = dbg.finish()
            log(
                f'[multichar][debug] report → {os.path.join(out_dir, "debug", "report.html")} '
                f'(verdict {"PASS" if v and v.get("ok") else "FAIL"})'
            )
        except _QCBlocked as e:
            # Deliberate stop from a mode=block gate — must not be swallowed by
            # the generic handler below, which is here for broken measurement.
            log(f'[multichar][QC BLOCKED] {e}')
            raise
        except Exception as _exc:
            _zyg_log.debug('debug report generation skipped: %s', _exc)
    log(f'[multichar-clip] → {clip}')
    return clip
