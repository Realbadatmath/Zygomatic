# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets trunk finding, scar/axe inpainting and the review candidate sweep."""

import os
import shutil

from .tree_base import (
    ARC_ENV,
    FRAMINGS,
    H_REND,
    OUT,
    TREE_SCENE_DESC,
    W_REND,
    _AXE_NEG,
    _AXE_PROMPT,
    _JUG,
    _SCAR_NEG,
    _SCAR_PROMPT,
    _arcane_env,
    _free,
    _log_noop,
    build_tree_base,
)


PROP_DIR = os.path.join(OUT, 'prop')


def find_trunk(plate_path, band=(0.30, 0.70)):
    """-> (cx_frac, width_frac) of the trunk in this plate.

    The trunk's horizontal position is a property of the SEED, not of the prompt — across
    the v3 sweep it wandered from left-of-centre to centre. Hardcoding frame centre hung
    the axe off the trunk's edge into the mist on a third of the plates, so placement has
    to be measured per plate.

    The trunk is the dark, low-saturation, high-texture vertical mass; the misty
    background is bright and flat. Scoring columns on (darkness x local contrast) over a
    mid-height band separates them without needing a segmentation model.
    """
    import numpy as np
    from PIL import Image

    im = Image.open(plate_path).convert('RGB')
    W, H = im.size
    a = np.asarray(im, dtype=np.float32)
    y0, y1 = int(H * band[0]), int(H * band[1])
    strip = a[y0:y1]
    lum = strip.mean(axis=2)
    dark = 1.0 - (lum / 255.0)
    contrast = np.abs(np.diff(lum, axis=0)).mean(axis=0)
    contrast = contrast / (contrast.max() + 1e-6)
    score = dark.mean(axis=0) * 0.6 + contrast * 0.4
    k = max(9, W // 60)  # smooth out bark noise
    score = np.convolve(score, np.ones(k) / k, mode='same')
    thr = score.mean() + 0.35 * score.std()
    on = score > thr
    # widest contiguous run of "trunk-like" columns
    best_i = best_n = cur_i = cur_n = 0
    for i, v in enumerate(on):
        if v:
            if cur_n == 0:
                cur_i = i
            cur_n += 1
            if cur_n > best_n:
                best_n, best_i = cur_n, cur_i
        else:
            cur_n = 0
    if best_n < W * 0.10:  # nothing convincing — centre it
        return 0.5, 0.45
    return (best_i + best_n / 2.0) / W, best_n / W


def apply_scars(
    plate_path,
    out_path,
    centre_frac=None,
    scale=None,
    strength=1.0,
    with_axe=False,
    prop_dir=None,
    log_fn=None,
    axe_scale=0.85,
    height_frac=0.38,
):
    """Carve the Blender scar cluster into a plate as a SHADING RATIO.

    ratio = trunk_cut / trunk_plain, computed from two renders of the same neutral
    surface that differ only by the boolean subtraction. It is 1.0 on untouched bark,
    <1 in a recess, >1 on a lit cut wall — so multiplying the plate by it darkens and
    highlights exactly where the geometry says, while the plate keeps its own bark colour
    and texture. A pasted RGBA decal cannot do this: it would replace the bark with a
    foreign surface, which is what the first Blender attempt looked like (matchsticks
    lying on the trunk rather than gouges cut into it).

    `strength` blends the ratio toward 1.0, so the marks can be dialled back without
    re-rendering. `with_axe` alpha-composites the hatchet on top afterwards — that one IS
    an object sitting in front of the bark, so a decal is correct for it.
    """
    import numpy as np
    from PIL import Image

    log = log_fn or _log_noop
    pd = prop_dir or PROP_DIR
    # Placement and scale are DERIVED from the plate unless the caller overrides. The
    # scar cluster spans ~29% of the Blender frame; sizing it to a fixed fraction of the
    # measured trunk width keeps the marks the same physical size on a trunk that fills
    # the frame and on one that is half as wide.
    if centre_frac is None or scale is None:
        tcx, tw = find_trunk(plate_path)
        if centre_frac is None:
            centre_frac = (tcx, height_frac)
        if scale is None:
            scale = max(0.25, min(1.0, tw / 0.55))
        log(f'trunk at x={tcx:.3f} width={tw:.3f} -> scale {scale:.2f}')
    sil_p = os.path.join(pd, 'scars_rgba.png')
    if not os.path.isfile(sil_p):
        raise SystemExit(f'missing {sil_p} — run prop_mesh/axe_render.py first')

    # SHADING IS SYNTHESISED FROM THE SILHOUETTE, not rendered. Blender supplies the one
    # thing only it can — each strike's correct perspective outline on a curved trunk —
    # and the recess lighting is built here, where it is fully determined rather than
    # hostage to boolean/normals hygiene (the DIFFERENCE route returned a 97%-black trunk
    # and survived both a winding fix and normals_make_consistent).
    #
    # A gouge reads as a gouge because of TWO cues, not one:
    #   * the interior is occluded, so it darkens;
    #   * the wall facing the key light catches a bright rim along one edge only.
    # A uniformly dark mark reads as paint — which is exactly how the first attempt looked.
    from scipy import ndimage

    alpha = np.asarray(Image.open(sil_p).convert('RGBA').split()[3], dtype=np.float32) / 255.0
    soft = ndimage.gaussian_filter(alpha, 2.2)
    gy, gx = np.gradient(soft)
    # key light sits upper-camera-left, matching the Blender sun and the plates' overcast
    # morning; the lit rim therefore falls on the upper-left lip of every cut.
    lx, ly = -0.62, -0.78
    facing = gx * lx + gy * ly
    rim_lit = np.clip(facing, 0, None)
    rim_lit /= rim_lit.max() + 1e-6
    interior = ndimage.grey_erosion(alpha, size=3)

    # POLARITY — v5 darkened the cut interiors and the marks VANISHED against dark oak
    # bark. Physically that was backwards: a hatchet strike removes bark and exposes pale
    # sapwood, so a fresh cut is LIGHTER than its surroundings, not darker. Only the thin
    # shadow line where the bark lifts at the rim is dark. Inverted here, which is both
    # correct and the reason the marks now read at all.
    shadow_rim = np.clip(-(gx * lx + gy * ly), 0, None)
    shadow_rim /= shadow_rim.max() + 1e-6
    ratio = (
        1.0
        + 1.45 * interior  # exposed pale sapwood: the bright core
        + 0.55 * (alpha - interior)  # softer shoulder of the bite
        - 0.45 * shadow_rim * (alpha > 0.02)
    )  # bark lifting on the shadow side
    ratio = np.clip(ratio, 0.35, 3.2)
    ratio[alpha < 0.01] = 1.0  # nothing outside a strike is touched
    ratio = np.repeat(ratio[:, :, None], 3, axis=2)
    if strength != 1.0:
        ratio = 1.0 + (ratio - 1.0) * float(strength)

    rim = Image.fromarray(np.clip(ratio * 127.5, 0, 255).astype('uint8'))
    plate = Image.open(plate_path).convert('RGB')
    PW, PH = plate.size
    rw, rh = int(rim.width * scale), int(rim.height * scale)
    rim = rim.resize((rw, rh), Image.LANCZOS)
    r = np.asarray(rim, dtype=np.float32) / 127.5

    # paste the (mostly-1.0) ratio into a full-plate neutral canvas at the chosen centre
    canvas = np.ones((PH, PW, 3), dtype=np.float32)
    cx, cy = int(PW * centre_frac[0]), int(PH * centre_frac[1])
    x0, y0 = cx - rw // 2, cy - rh // 2
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww = min(rw - sx0, PW - dx0)
    hh = min(rh - sy0, PH - dy0)
    if ww > 0 and hh > 0:
        canvas[dy0 : dy0 + hh, dx0 : dx0 + ww] = r[sy0 : sy0 + hh, sx0 : sx0 + ww]

    out = np.asarray(plate, dtype=np.float32) * canvas
    res = Image.fromarray(np.clip(out, 0, 255).astype('uint8'))

    if with_axe:
        # v3 pasted the axe at the scar scale and it read as a cartoon hatchet a third
        # as wide as the trunk. A real hand axe against a tree this size is small.
        asc = scale * float(axe_scale)
        ax = Image.open(os.path.join(pd, 'axe_rgba.png')).convert('RGBA')
        ax = ax.resize((max(1, int(ax.width * asc)), max(1, int(ax.height * asc))), Image.LANCZOS)
        lay = Image.new('RGBA', (PW, PH), (0, 0, 0, 0))
        lay.paste(ax, (cx - ax.width // 2, cy - ax.height // 2), ax)
        res = Image.alpha_composite(res.convert('RGBA'), lay).convert('RGB')

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    res.save(out_path)
    touched = float((np.abs(canvas - 1.0) > 0.02).any(axis=2).mean())
    log(f'scars: {100 * touched:.2f}% of frame carved (scale {scale}, strength {strength}, axe={with_axe})')
    return out_path


def paint_region(
    plate_path, bbox_frac, prompt, negative='', denoise=0.55, seed=17, feather=48, ellipse=True, log_fn=None
):
    """Feathered ELLIPTICAL region inpaint — the sibling relock_region should have been.

    arcane_multichar.relock_region masks a rectangle with a 6px blur, which is fine for
    re-locking a prop that already fills its box (a pipe, a face) but leaves a visible
    rectangular seam when the new content has to MERGE into surrounding texture. Axe cuts
    in bark are exactly that case, and the smoke test showed the box edge plainly.

    An ellipse with a wide feather makes the model blend outward into real bark, and the
    lower default denoise keeps the trunk's own shading and vertical fissures alive
    underneath instead of inventing a flat new surface.
    """
    from PIL import Image, ImageDraw, ImageFilter
    from zyg_workflows import _comfy_client as CC

    log = log_fn or _log_noop
    try:
        im = Image.open(plate_path).convert('RGB')
        W, H = im.size
        fx0, fy0, fx1, fy1 = bbox_frac
        box = [int(W * fx0), int(H * fy0), int(W * fx1), int(H * fy1)]
        mask = Image.new('L', (W, H), 0)
        d = ImageDraw.Draw(mask)
        (d.ellipse if ellipse else d.rectangle)(box, fill=255)
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
        mpath = plate_path + '.paint_mask.png'
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
            # SetLatentNoiseMask, not VAEEncodeForInpaint: the latter blanks the masked
            # pixels before sampling, which is why the smoke test ignored the bark it was
            # supposed to be cutting into. This keeps the original latent underneath and
            # lets `denoise` decide how much of it survives.
            '7': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['2', 0], 'vae': ['1', 2]}},
            '8': {'class_type': 'SetLatentNoiseMask', 'inputs': {'samples': ['7', 0], 'mask': ['4', 0]}},
            '9': {
                'class_type': 'KSampler',
                'inputs': {
                    'model': ['1', 0],
                    'positive': ['5', 0],
                    'negative': ['6', 0],
                    'latent_image': ['8', 0],
                    'seed': int(seed),
                    'steps': 28,
                    'cfg': 6.5,
                    'sampler_name': 'dpmpp_2m',
                    'scheduler': 'karras',
                    'denoise': float(denoise),
                },
            },
            '10': {'class_type': 'VAEDecode', 'inputs': {'samples': ['9', 0], 'vae': ['1', 2]}},
            '11': {'class_type': 'SaveImage', 'inputs': {'images': ['10', 0], 'filename_prefix': 'ZygAxePaint'}},
        }
        outs = CC.submit(g, timeout_s=600)
        if outs and os.path.isfile(outs[0]):
            res = Image.open(outs[0]).convert('RGB')
            if res.size != (W, H):
                res = res.resize((W, H), Image.LANCZOS)
            res.save(plate_path)
            os.remove(mpath)
            return plate_path
    except Exception as e:
        log(f'[paint-region] failed ({e}) — plate unchanged')
    return plate_path


def build_candidates(log_fn=None, sheet='axe_tree_candidates.png', styled=True, only=None):
    """Reviewable plates across all three framings — scarred, axed where the story wants
    an axe, and finished in the environment-tuned arcane style.

    only : restrict to one framing key ('close'|'wide'|'med') for a cheap smoke test
           before committing to the full batch.
    """
    from PIL import Image, ImageDraw

    log = log_fn or _log_noop
    os.makedirs(OUT, exist_ok=True)
    cand_dir = os.path.join(OUT, 'candidates')
    os.makedirs(cand_dir, exist_ok=True)

    made = []
    idx = 0
    for fname, spec in FRAMINGS.items():
        for s in spec['seeds']:
            idx += 1
            if only and fname != only:
                continue
            tag = f'{idx:02d}_{fname}_s{s}'
            base = os.path.join(cand_dir, f'{tag}_base.png')
            cand = os.path.join(cand_dir, f'{tag}.png')
            if not os.path.isfile(cand):
                if not os.path.isfile(base):
                    build_tree_base(base, seed=s, log_fn=log, prompt=spec['prompt'], negative=spec.get('negative'))
                shutil.copy2(base, cand)
                log(f'{tag}: scars -> {spec["scar_box"]}')
                paint_region(
                    cand,
                    spec['scar_box'],
                    _SCAR_PROMPT,
                    negative=_SCAR_NEG,
                    denoise=0.58,
                    seed=s + 700,
                    feather=52,
                    log_fn=log,
                )
                if spec['axe']:
                    log(f'{tag}: axe -> {spec["axe_box"]}')
                    paint_region(
                        cand,
                        spec['axe_box'],
                        _AXE_PROMPT,
                        negative=_AXE_NEG,
                        denoise=0.72,
                        seed=s + 900,
                        feather=26,
                        log_fn=log,
                    )
                if styled:
                    # scene_desc must describe what is ACTUALLY on this plate. The style
                    # sweep was run with a desc mentioning an embedded axe and the pass
                    # duly HALLUCINATED small axes onto a plate that had none — at
                    # denoise 0.45 this stage can still add objects, so the description
                    # is a control input, not a label.
                    log(f'{tag}: arcane env pass')
                    _arcane_env(cand, cand, spec['scene_desc'], seed=s + 300, log_fn=log, **ARC_ENV)
            made.append((idx, fname, s, spec['shots'], cand))

    cols, tw, th = 3, 600, 348
    rows = (len(made) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (th + 26)), (14, 14, 16))
    d = ImageDraw.Draw(sh)
    for i, (n, fname, s, shots, p) in enumerate(made):
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        with Image.open(p) as im:
            sh.paste(im.convert('RGB').resize((tw, th), Image.LANCZOS), (x, y + 26))
        d.text((x + 8, y + 7), f'#{n}  {fname.upper()}  seed {s}   shots {shots}', fill=(235, 235, 235))
    out = os.path.join(OUT, sheet)
    sh.save(out)
    log(f'candidate sheet: {out}')
    return out, made


def build_tree_plate(seed=11, log_fn=None, keep_gen_res=True):
    """base txt2img -> arcane style pass -> the scene's anchor still.

    Returns (arcane_full_res, anchor_832x480). The full-res copy is kept because the post
    pan/zoom crops into the DELIVERED frame, and starting from more pixels than 832x480
    keeps that move from turning into a blur.
    """
    from PIL import Image
    from zyg_workflows import arcane_multichar as AM

    log = log_fn or _log_noop
    os.makedirs(OUT, exist_ok=True)

    base = os.path.join(OUT, 'tree_base_photoreal.png')
    if not os.path.isfile(base):
        build_tree_base(base, seed=seed, log_fn=log)
        _free(log)
    else:
        log(f'tree base exists — reusing {os.path.basename(base)}')

    styled = os.path.join(OUT, 'tree_arcane.png')
    if not os.path.isfile(styled):
        log('tree plate: arcane style pass (depth-guided, vits/Apache-2.0)')
        AM._arcane_full(base, styled, TREE_SCENE_DESC, seed, log)
        _free(log)
    else:
        log(f'arcane plate exists — reusing {os.path.basename(styled)}')

    anchor = os.path.join(OUT, 'anchor_shot1_tree_832x480.png')
    with Image.open(styled) as im:
        im.convert('RGB').resize((W_REND, H_REND), Image.LANCZOS).save(anchor)
    log(f'anchor: {anchor}')
    return (styled if keep_gen_res else None), anchor


if __name__ == '__main__':  # the CLI lives in candidates_cli
    from zyg_workflows.axe_scene_assets.candidates_cli import main as _cli_main

    raise SystemExit(_cli_main())
