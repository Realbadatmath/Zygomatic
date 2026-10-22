#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Smoke test for the skin-tone fix.

Run with the ComfyUI venv (has PIL/numpy/insightface + can reach ComfyUI):
    $ZYG_COMFY_ROOT/.venv/bin/python skin_tone_smoke.py [tones]

Two layers:
  1) STATIC (no GPU): the enriched descriptor + anti-lightening negative are in
     the prompt/negative for the selected tone.
  2) RENDER (GPU): generate the anchor cell for each tone exactly the way the
     pipeline does, detect the face, and measure mean skin luminance. Asserts
     that a dark selection actually renders darker than a light one — i.e. the
     skin-tone control has real effect on pixels, not just on the prompt.
"""

import os
import sys
import copy
import uuid
import shutil
import argparse
import logging as _zyg_logging

import numpy as np
from PIL import Image

from zyg_workflows import paths

os.environ.setdefault('ZYG_COMFY_PRIMARY', '1')
os.environ.setdefault('ZYG_USE_COMFYUI', '1')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# noqa: E402 below — the three services read ZYG_COMFY_PRIMARY/ZYG_USE_COMFYUI at import
# time and resolve their siblings off sys.path, so the setdefault/insert block above must run first.
from zyg_workflows import character_bible_service as cbs  # noqa: E402  needs the env set above
from zyg_workflows import comfy_generation_service as cgs  # noqa: E402  needs the env set above
from zyg_workflows import contact_sheet_pipeline as csp  # noqa: E402  needs the env set above

_zyg_log = _zyg_logging.getLogger(__name__)


def build_anchor_prompt(char_id, params):
    """Replicate the pipeline's cell_00 (anchor) prompt construction exactly."""
    pkg = csp._build_sheet_character_package(char_id, params, 'flux')
    gen_pkg = copy.deepcopy(pkg) if pkg else {}
    angle = csp.contact_sheet_angle_labels('extended')[0]
    _fr = csp._framing_clause(angle)
    style_extra = csp.caption_style_description((params or {}).get('style', 'photorealistic'))
    trigger = csp.trigger_token_for(char_id)
    skin_desc = cbs.describe_skin_tone((params or {}).get('skin_tone', ''))
    skin_clause = f'{skin_desc}, ' if skin_desc else ''
    scene = (
        f'{skin_clause}{angle}, single person, character reference portrait, '
        f'neutral studio background{_fr}, RAW candid photograph, natural uneven '
        f'skin with visible pores and fine texture, subtle film grain, '
        f'unretouched not airbrushed, {style_extra}, {trigger}'
    )
    prompt = cgs.build_locked_prompt(scene, pkg, studio_preview=True)
    negative = cgs.build_locked_negative_prompt(pkg, studio_preview=True)
    return pkg, gen_pkg, angle, prompt, negative


_FACE_APP = None


def _detect_face_bbox(path):
    global _FACE_APP
    try:
        if _FACE_APP is None:
            from insightface.app import FaceAnalysis

            _FACE_APP = FaceAnalysis(name='antelopev2', providers=['CPUExecutionProvider'])
            _FACE_APP.prepare(ctx_id=-1, det_size=(640, 640))
        import cv2

        bgr = cv2.imread(path)
        faces = _FACE_APP.get(bgr)
        if not faces:
            return None
        f = max(faces, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        return [float(v) for v in f.bbox]
    except Exception as e:
        _zyg_log.info(f'    face-detect fallback ({e})')
        return None


def measure_skin(path):
    """Median RGB + luminance of the cheek region (falls back to image centre)."""
    im = np.asarray(Image.open(path).convert('RGB'), dtype=np.float32)
    H, W = im.shape[:2]
    bb = _detect_face_bbox(path)
    if bb:
        x1, y1, x2, y2 = bb
        fw, fh = x2 - x1, y2 - y1
        cy = int(y1 + 0.62 * fh)  # cheek height (below the eyes)
        r = max(4, int(fw * 0.10))
        patches = []
        for fx in (0.30, 0.70):  # left + right cheeks
            cx = int(x1 + fx * fw)
            patch = im[max(0, cy - r) : cy + r, max(0, cx - r) : cx + r]
            if patch.size:
                patches.append(patch.reshape(-1, 3))
        pix = np.concatenate(patches, axis=0) if patches else im.reshape(-1, 3)
        region = 'cheeks'
    else:
        # Center portrait fallback
        pix = im[int(H * 0.30) : int(H * 0.55), int(W * 0.38) : int(W * 0.62)].reshape(-1, 3)
        region = 'center'
    rgb = np.median(pix, axis=0)
    lum = float(0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2])
    return {'region': region, 'rgb': [round(float(c), 1) for c in rgb], 'luminance': round(lum, 1)}


def static_check(tone):
    params = {
        'name': 'SkinTest',
        'gender': 'female',
        'hair_color': 'black',
        'eye_color': 'brown',
        'skin_tone': tone,
        'style': 'photorealistic',
    }
    cid = 'skn' + uuid.uuid4().hex[:9]
    _, _, _, prompt, negative = build_anchor_prompt(cid, params)
    desc = cbs.describe_skin_tone(tone)
    in_prompt = desc.split(',')[0] in prompt
    dark = tone in cbs._DARK_SKIN_TONES
    neg_ok = ('whitewashed skin' in negative) if dark else ('whitewashed skin' not in negative)
    for d in (csp.contact_sheet_dir(cid), csp.training_dataset_dir(cid)):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return {
        'tone': tone,
        'descriptor': desc,
        'in_prompt': in_prompt,
        'neg_defended': neg_ok,
        'dark': dark,
        'prompt_head': prompt[:90],
    }


def render_check(tone, outdir):
    params = {
        'name': 'SkinTest',
        'gender': 'female',
        'hair_color': 'black',
        'eye_color': 'brown',
        'skin_tone': tone,
        'style': 'photorealistic',
    }
    cid = 'skn' + uuid.uuid4().hex[:9]
    pkg, gen_pkg, angle, prompt, negative = build_anchor_prompt(cid, params)
    w, h = csp._cell_size_for_angle(angle)
    out = os.path.join(outdir, f'anchor_{tone}.png')
    cell_neg = (
        'blurry, low quality, 3d render, cartoon, doll, illustration, anime, cgi, '
        'airbrushed skin, smooth plastic skin, waxy skin, porcelain doll skin'
    )
    ok, backend = cgs.generate_still(
        out,
        prompt,
        width=w,
        height=h,
        steps=20,
        cfg=2.5,
        seed=1234567,
        character_package=gen_pkg,
        char_id=cid,
        model_family='qwen',
        skip_qa=True,
        studio_preview=True,
        prompt_finalized=True,
        extra_negative=cell_neg,
        force_workflow='qwen_txt2img',
        force_unet='qwen_image_2512_fp8_e4m3fn.safetensors',
    )
    result = {'tone': tone, 'ok': bool(ok and os.path.isfile(out)), 'backend': backend, 'path': out}
    if result['ok']:
        result.update(measure_skin(out))
    for d in (csp.contact_sheet_dir(cid), csp.training_dataset_dir(cid)):
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('tones', nargs='?', default='fair,deep', help='comma tones to render (default fair,deep)')
    ap.add_argument('--static-only', action='store_true')
    args = ap.parse_args()
    tones = [t.strip() for t in args.tones.split(',') if t.strip()]

    print('=== STATIC CHECK (prompt + negative) ===', flush=True)
    static_pass = True
    for t in ['fair', 'olive', 'tan', 'dark', 'deep']:
        r = static_check(t)
        ok = r['in_prompt'] and r['neg_defended']
        static_pass &= ok
        print(
            f"  [{'PASS' if ok else 'FAIL'}] {t:6} -> '{r['descriptor']}' "
            f'| in_prompt={r["in_prompt"]} neg_defended={r["neg_defended"]}',
            flush=True,
        )
    print(f'STATIC: {"PASS" if static_pass else "FAIL"}\n', flush=True)

    if args.static_only:
        print('RESULT:', 'PASS' if static_pass else 'FAIL')
        return

    outdir = str(paths.tmp_dir('skin_smoke_out'))
    os.makedirs(outdir, exist_ok=True)
    print(f'=== RENDER CHECK (real FLUX anchor per tone -> {outdir}) ===', flush=True)
    measured = {}
    for t in tones:
        print(f'  rendering {t} ...', flush=True)
        r = render_check(t, outdir)
        if r['ok']:
            measured[t] = r['luminance']
            print(
                f'    {t:6}: luminance={r["luminance"]} rgb={r["rgb"]} ({r["region"]}) [{r["backend"]}] -> {r["path"]}',
                flush=True,
            )
        else:
            print(f'    {t:6}: RENDER FAILED ({r["backend"]})', flush=True)

    print('\n=== VERDICT ===', flush=True)
    render_pass = True
    # Ordering assertion: any lighter tone must measure brighter than any darker
    # one, with a clear margin (skin luminance gap between fair and deep is large).
    order = ['fair', 'light', 'medium', 'olive', 'tan', 'dark', 'deep']
    present = [t for t in order if t in measured]
    for i in range(len(present) - 1):
        a, b = present[i], present[i + 1]  # a lighter than b
        gap = measured[a] - measured[b]
        ok = gap > 15  # b clearly darker than a
        render_pass &= ok
        print(
            f'  {a}({measured[a]}) darker-than {b}({measured[b]}) ? gap={gap:.0f} -> {"PASS" if ok else "FAIL"}',
            flush=True,
        )
    if len(present) < 2:
        print('  (need >=2 tones to compare ordering)', flush=True)
        render_pass = bool(measured)
    print(f'\nRENDER: {"PASS" if render_pass else "FAIL"}', flush=True)
    print('RESULT:', 'PASS' if (static_pass and render_pass) else 'FAIL', flush=True)


if __name__ == '__main__':
    main()
