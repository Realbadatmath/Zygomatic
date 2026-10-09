# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets generated axe sprite + bark patch path and the textured scar composite."""

import os

from .tree_base import (
    OUT,
    _log_noop,
    build_tree_base,
)
from .candidates import (
    PROP_DIR,
    find_trunk,
)


# ═══════════════════════════════════════════════════════════════════════════
# SPRITE PATH (2026-08-03) — replaces the Blender-primitive axe and the
# synthesised-from-silhouette scars.
#
# WHY THE REWRITE. The primitive path gave rigidity and correct perspective, which is
# what I wanted, but rigidity is worthless if the thing held rigid looks like a signpost.
# Reviewed at full size, the Blender axe was visibly two rectangles — no blade curve, no
# bevel, no eye, flat cut-off haft — and the scars were one connected pale blob, because
# shading synthesised from a Gaussian-blurred silhouette produces soft blobs by
# construction and cannot produce a chipped edge.
#
# The perspective argument that justified Blender barely applies here: five LOCKED-OFF
# shots, one viewpoint each. So the axe and the strike marks only have to be right ONCE,
# which is exactly the case where a generated image beats authored primitives — it
# inherits real material, edge and micro-detail that boxes never will.
#
# Blender is NOT discarded: `prop_mesh/axe_render.py` still supplies the strike
# SILHOUETTES, which is the one thing generation cannot give us — deterministic, identical
# mark placement across all plates and all shots. The silhouettes now act as a MASK
# through which real chipped-bark texture is blended, so placement stays authored while
# the material becomes real.

_AXE_SPRITE_PROMPT = (
    'a single old iron hatchet lying flat, photographed straight on from the side, '
    'the whole tool visible end to end, forged steel head with a curved cutting edge and '
    'a visible eye where the haft passes through, worn hickory handle with visible wood '
    'grain, slightly rusted and pitted steel, 17th century tool, '
    'isolated on a plain pure white seamless background, studio product photograph, '
    'soft even lighting, sharp focus, high detail'
)
_AXE_SPRITE_NEG = (
    'background, forest, trees, grass, table, wood surface, shadow on background, '
    'hand, person, two axes, multiple tools, text, watermark, logo, ruler, '
    'blurry, lowres, cartoon, illustration, drawing'
)

# POLARITY, again. The first texture came back almost entirely cream — SDXL read
# "pale sapwood" as the SUBJECT and produced peeled birch-white material, so blending it
# through the strike masks painted white blobs on the tree. The frame has to be
# overwhelmingly DARK BARK, with the pale wood confined to a few narrow gashes: the ratio
# is stated explicitly and the pale-surface reading is negated.
_BARK_PATCH_PROMPT = (
    'extreme close-up of DARK grey-brown oak bark, rough and deeply ridged, filling '
    'almost the entire frame, '
    'a few narrow axe gashes have been chopped into it — each cut is a thin slot of '
    'bright pale yellow raw wood, no wider than a finger, with ragged splintered fibres '
    'along its edges and dark torn bark curling back at the rim, '
    'the cuts cover only a small part of the surface; MOST of the image is dark '
    'undamaged bark, '
    'flat straight-on view, photorealistic, sharp focus, high detail, overcast daylight'
)
_BARK_PATCH_NEG = (
    'pale bark, white bark, cream surface, birch bark, peeling bark, stripped bark, '
    'bare wood surface, sanded plank, mostly light coloured, overexposed, '
    'whole tree, trunk silhouette, forest, leaves, moss, lichen, smooth bark, '
    'tree rings, log cross-section, sawn end grain, carved letters, symbols, face, '
    'blurry, lowres, watermark, text'
)


def key_white(src, dst, thr=190, feather=1.6, log_fn=None):
    """Alpha-key an object shot on a plain white ground. -> dst (RGBA).

    Distance-from-white rather than a flat luminance cut: a rusted steel head has bright
    specular highlights that a luminance threshold would punch holes straight through.
    Keeping the largest connected component discards the stray specks SDXL leaves in the
    corners, which would otherwise composite as dirt on the tree.
    """
    import numpy as np
    from scipy import ndimage
    from PIL import Image

    log = log_fn or _log_noop
    im = Image.open(src).convert('RGB')
    a = np.asarray(im, dtype=np.float32)
    # SHADOWS, NOT BACKGROUND. The first key used distance-from-white and kept 25-57% of
    # the frame, because SDXL renders a soft DROP SHADOW on the white ground and a grey
    # shadow is far from white. A cast shadow is light AND colourless; the tool is either
    # dark (forged steel) or coloured (hickory). Keying on (dark OR saturated) separates
    # them, where distance-from-white cannot.
    lum = a.mean(axis=2)
    mx, mn = a.max(axis=2), a.min(axis=2)
    sat = (mx - mn) / (mx + 1e-6)
    fg = (lum < float(thr)) | (sat > 0.18)
    fg = ndimage.binary_closing(fg, np.ones((5, 5)))
    fg = ndimage.binary_fill_holes(fg)
    lab, n = ndimage.label(fg)
    if n > 1:  # keep only the tool itself
        sizes = ndimage.sum(fg, lab, range(1, n + 1))
        fg = lab == (int(np.argmax(sizes)) + 1)
    alpha = ndimage.gaussian_filter(fg.astype(np.float32), feather)
    out = np.dstack([a, np.clip(alpha * 255.0, 0, 255)]).astype('uint8')
    Image.fromarray(out, 'RGBA').save(dst)
    ys, xs = np.where(alpha > 0.5)
    if len(ys) == 0:
        raise RuntimeError(f'key_white: nothing survived the key in {src}')
    bbox = (int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max()))
    log(f'keyed {os.path.basename(src)}: {100 * (alpha > 0.5).mean():.1f}% fg, bbox {bbox}')
    return dst, bbox


def sweep_axe_sprites(seeds=(101, 102, 103, 104, 105, 106), log_fn=None):
    """Generate isolated axe candidates and key them. -> (sheet, [(seed, rgba, bbox)])

    The axe only has to be right ONCE for the whole scene, so this is the cheapest place
    in the pipeline to be picky — six samples cost about three minutes.
    """
    from PIL import Image

    log = log_fn or _log_noop
    d = os.path.join(OUT, 'sprites')
    os.makedirs(d, exist_ok=True)
    made = []
    for s in seeds:
        raw = os.path.join(d, f'axe_raw_{s}.png')
        if not os.path.isfile(raw):
            build_tree_base(
                raw,
                seed=s,
                log_fn=log,
                prompt=_AXE_SPRITE_PROMPT,
                negative=_AXE_SPRITE_NEG,
                w=1024,
                h=1024,
                steps=36,
                cfg=6.5,
            )
        rgba = os.path.join(d, f'axe_sprite_{s}.png')
        try:
            _, bbox = key_white(raw, rgba, log_fn=log)
            made.append((s, rgba, bbox))
        except Exception as e:
            log(f'seed {s}: key failed ({e})')
    cols, tw = 3, 420
    rows = (len(made) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (tw + 22)), (200, 200, 200))
    from PIL import ImageDraw

    dr = ImageDraw.Draw(sh)
    for i, (s, p, _b) in enumerate(made):
        x, y = (i % cols) * tw, (i // cols) * (tw + 22)
        im = Image.open(p).convert('RGBA').resize((tw, tw), Image.LANCZOS)
        bg = Image.new('RGBA', (tw, tw), (150, 140, 130, 255))
        sh.paste(Image.alpha_composite(bg, im).convert('RGB'), (x, y + 22))
        dr.text((x + 8, y + 5), f'seed {s}', fill=(20, 20, 20))
    out = os.path.join(OUT, 'axe_sprite_sweep.png')
    sh.save(out)
    log(f'axe sprite sweep: {out}')
    return out, made


AXE_SPRITE_SEED = 101  # chosen off axe_sprite_keyed.png: head up, blade right, haft
# hanging straight down — the pose of a tool struck into a trunk


def _match_colour(src_rgb, alpha, plate_rgb, amount=0.65):
    """Grade a cut-out toward the plate's local colour statistics.

    The sprite is a studio product shot: neutral, high-contrast, fully saturated. The
    plates are cold overcast fog. Pasting one into the other unmatched is the single most
    reliable way to make a composite look pasted, and it is what the previous version did.
    Matching per-channel mean and standard deviation is the standard fix; `amount` keeps
    it partial so the steel does not dissolve into the bark.
    """
    import numpy as np

    m = alpha > 0.35
    if m.sum() < 32:
        return src_rgb
    out = src_rgb.astype(np.float32).copy()
    for c in range(3):
        s_mu, s_sd = out[..., c][m].mean(), out[..., c][m].std() + 1e-6
        p_mu, p_sd = plate_rgb[..., c].mean(), plate_rgb[..., c].std() + 1e-6
        graded = (out[..., c] - s_mu) * (p_sd / s_sd) + p_mu
        out[..., c] = out[..., c] * (1 - amount) + graded * amount
    return np.clip(out, 0, 255)


def composite_axe(
    plate_path,
    out_path,
    centre_frac,
    target_w_frac=0.16,
    rotate=14.0,
    bite=0.34,
    shadow=0.62,
    sprite_seed=None,
    prop_dir=None,
    log_fn=None,
    mirror=True,
    wound=1.0,
):
    """Paste the axe sprite into a plate with contact shadow, colour match and a bite.

    Three things the Blender-primitive composite lacked, each of which alone reads as
    "pasted":
      * CONTACT SHADOW — a blurred, offset, darkened copy of the alpha laid down BEFORE
        the sprite. Without it the axe floats on the image instead of sitting in the tree.
      * COLOUR MATCH — see _match_colour.
      * THE BITE — see below. This is the one that decides whether the shot works.

    WHY EVERY EARLIER AXE LOOKED FLAT AGAINST THE TREE.
    The sprite is a whole tool photographed side-on in free air, so pasting it entire
    leaves the complete blade profile visible — and a blade you can see all of is a blade
    that is demonstrably NOT in the wood. v7-v9 tried to hide it by FEATHERING the leading
    22% to transparent, which does not read as occlusion at all: it reads as the axe
    fading out, a ghost laid on the bark.

    Wood in front of steel is a HARD edge, not a soft one. So the blade is now clipped on
    a hard, slightly ragged line (bark does not cut straight), a third of the head is
    simply gone behind the trunk surface, and a WOUND is painted at that line — a dark
    split where the bark has parted plus a few pale splinters thrown up along it. Without
    the wound the hard clip reads as the axe passing behind the tree rather than into it.

    `mirror` flips the sprite so the cutting edge faces INTO the trunk; seed 101 was shot
    with its edge to the right, and an unmirrored paste buries the poll instead of the bit.
    """
    import numpy as np
    from scipy import ndimage
    from PIL import Image

    log = log_fn or _log_noop
    pd = prop_dir or os.path.join(OUT, 'sprites')
    sp = os.path.join(pd, f'axe_sprite_{sprite_seed or AXE_SPRITE_SEED}.png')
    if not os.path.isfile(sp):
        raise SystemExit(f'missing {sp} — run sweep_axe_sprites() first')

    plate = Image.open(plate_path).convert('RGB')
    PW, PH = plate.size
    ax = Image.open(sp).convert('RGBA')
    ax = ax.crop(ax.split()[3].getbbox())  # tight crop
    if mirror:
        ax = ax.transpose(Image.FLIP_LEFT_RIGHT)  # cutting edge faces the wood
    ax = ax.rotate(rotate, expand=True, resample=Image.BICUBIC)

    tw = max(8, int(PW * target_w_frac))
    th = max(8, int(ax.height * tw / ax.width))
    ax = ax.resize((tw, th), Image.LANCZOS)
    arr = np.asarray(ax, dtype=np.float32)
    rgb, alpha = arr[..., :3], arr[..., 3] / 255.0

    # BITE: a HARD clip, not a feather. Everything left of the entry line is inside the
    # trunk and must simply not be drawn. The line is perturbed by a low-frequency noise
    # so it is not a suspiciously straight vertical.
    entry_col = 0.0
    if bite > 0:
        rng = np.random.default_rng(7)
        jag = ndimage.gaussian_filter1d(rng.normal(0, 1, th), 9.0)
        jag = jag / (np.abs(jag).max() + 1e-6) * (tw * 0.022)
        entry_col = tw * float(bite)
        xx = np.arange(tw)[None, :]
        keep = xx >= (entry_col + jag[:, None])
        alpha = alpha * keep

    cx, cy = int(PW * centre_frac[0]), int(PH * centre_frac[1])
    x0, y0 = cx - tw // 2, cy - th // 3  # head near the strike, haft hanging below
    region = np.asarray(plate, dtype=np.float32)[max(0, y0) : min(PH, y0 + th), max(0, x0) : min(PW, x0 + tw)]
    if region.size:
        rgb = _match_colour(rgb, alpha, region)

    base = np.asarray(plate, dtype=np.float32)

    def _blit(dst, src, a, ox, oy):
        h, w = a.shape
        sx0, sy0 = max(0, -ox), max(0, -oy)
        dx0, dy0 = max(0, ox), max(0, oy)
        ww, hh = min(w - sx0, PW - dx0), min(h - sy0, PH - dy0)
        if ww <= 0 or hh <= 0:
            return
        aa = a[sy0 : sy0 + hh, sx0 : sx0 + ww][..., None]
        dst[dy0 : dy0 + hh, dx0 : dx0 + ww] = (
            dst[dy0 : dy0 + hh, dx0 : dx0 + ww] * (1 - aa) + src[sy0 : sy0 + hh, sx0 : sx0 + ww] * aa
        )

    if shadow > 0:
        sh_a = ndimage.gaussian_filter(alpha, max(2.0, tw * 0.03)) * float(shadow)
        _blit(base, np.zeros_like(rgb), sh_a, x0 + int(tw * 0.05), y0 + int(th * 0.03))

    # THE WOUND. A hard clip alone reads as the axe passing BEHIND the trunk. What says
    # "into" is damage at the entry: bark parted in a dark split, and pale splinters
    # thrown up along the line where the steel went in.
    if wound > 0 and bite > 0:
        band = np.zeros((th, tw), dtype=np.float32)
        rows = np.where(alpha.max(axis=1) > 0.25)[0]
        if rows.size:
            for r in rows:
                c = int(entry_col + jag[r])
                lo, hi = max(0, c - int(tw * 0.030)), min(tw, c + int(tw * 0.012))
                band[r, lo:hi] = 1.0
            band = ndimage.gaussian_filter(band, max(1.2, tw * 0.006))
            band /= band.max() + 1e-6
            dark = np.zeros((th, tw, 3), dtype=np.float32)
            _blit(base, dark, band * 0.75 * float(wound), x0, y0)
            # splinters: short pale strokes straddling the entry line
            spl = np.zeros((th, tw), dtype=np.float32)
            rr = np.random.default_rng(11)
            for _ in range(max(4, int(th * 0.045))):
                r0 = int(rr.integers(rows.min(), rows.max() + 1))
                c0 = int(entry_col + jag[min(r0, th - 1)])
                ln = int(rr.integers(int(tw * 0.02), max(3, int(tw * 0.07))))
                dr = float(rr.normal(0, 0.35))
                for k in range(ln):
                    rk, ck = int(r0 + dr * k), c0 + k - ln // 3
                    if 0 <= rk < th and 0 <= ck < tw:
                        spl[rk, ck] = 1.0
            spl = ndimage.gaussian_filter(spl, 0.9)
            spl /= spl.max() + 1e-6
            pale = np.ones((th, tw, 3), dtype=np.float32) * np.array([205.0, 186.0, 148.0])
            _blit(base, pale, spl * 0.55 * float(wound), x0, y0)

    _blit(base, rgb, alpha, x0, y0)

    Image.fromarray(np.clip(base, 0, 255).astype('uint8')).save(out_path)
    log(f'axe: seed {sprite_seed or AXE_SPRITE_SEED} at {centre_frac} w={target_w_frac:.3f} rot={rotate} bite={bite}')
    return out_path


def apply_scars_textured(
    plate_path,
    out_path,
    bark_tex,
    centre_frac=None,
    scale=None,
    strength=0.9,
    prop_dir=None,
    log_fn=None,
    height_frac=0.38,
):
    """Blend a REAL chipped-bark texture through the Blender strike silhouettes.

    This is the division of labour the review forced. Generation supplies material —
    splintered fibre, torn bark, warm sapwood — which a blurred alpha silhouette can never
    fake. Blender supplies placement: the same 26 strikes in the same arrangement on every
    plate and in every shot, which is the continuity the scene is about and which
    generation cannot hold. Neither tool alone was enough; the previous two attempts each
    used one of them for both jobs.
    """
    import numpy as np
    from scipy import ndimage
    from PIL import Image

    log = log_fn or _log_noop
    pd = prop_dir or PROP_DIR
    sil_p = os.path.join(pd, 'scars_rgba.png')
    for p in (sil_p, bark_tex):
        if not os.path.isfile(p):
            raise SystemExit(f'missing {p}')

    plate = Image.open(plate_path).convert('RGB')
    PW, PH = plate.size
    if centre_frac is None or scale is None:
        tcx, tw_frac = find_trunk(plate_path)
        centre_frac = centre_frac or (tcx, height_frac)
        scale = scale or max(0.30, min(1.2, tw_frac / 0.45))

    sil = Image.open(sil_p).convert('RGBA').split()[3]
    sw, sh_ = int(sil.width * scale), int(sil.height * scale)
    sil = sil.resize((sw, sh_), Image.LANCZOS)
    m = np.asarray(sil, dtype=np.float32) / 255.0
    m = ndimage.grey_dilation(m, size=max(5, int(sw * 0.035)))
    m = ndimage.gaussian_filter(m, max(3.0, sw * 0.022))
    m = np.clip((m - 0.18) / 0.55, 0, 1) ** 0.85

    # TEXEL SCALE. Resizing the 1024px patch to fill the mask stretched it: a cut the
    # texture renders a finger wide came out a forearm wide on the trunk, which is why v8
    # read as cream swathes draped over the bark rather than as strikes. The patch is
    # instead sampled at its own scale — sized so one cut lands at `cut_px` on the plate —
    # and TILED to fill the region.
    cut_px = max(48, int(sw * 0.20))
    tex = Image.open(bark_tex).convert('RGB').resize((cut_px, cut_px), Image.LANCZOS)
    t1 = np.asarray(tex, dtype=np.float32)
    reps = (int(np.ceil(sh_ / cut_px)), int(np.ceil(sw / cut_px)), 1)
    t = np.tile(t1, reps)[:sh_, :sw]

    base = np.asarray(plate, dtype=np.float32)
    cx, cy = int(PW * centre_frac[0]), int(PH * centre_frac[1])
    x0, y0 = cx - sw // 2, cy - sh_ // 2
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww, hh = min(sw - sx0, PW - dx0), min(sh_ - sy0, PH - dy0)
    if ww > 0 and hh > 0:
        region = base[dy0 : dy0 + hh, dx0 : dx0 + ww]
        tt = _match_colour(t[sy0 : sy0 + hh, sx0 : sx0 + ww], m[sy0 : sy0 + hh, sx0 : sx0 + ww], region, amount=0.55)
        aa = (m[sy0 : sy0 + hh, sx0 : sx0 + ww] * float(strength))[..., None]
        base[dy0 : dy0 + hh, dx0 : dx0 + ww] = region * (1 - aa) + tt * aa
    Image.fromarray(np.clip(base, 0, 255).astype('uint8')).save(out_path)
    log(f'scars(tex): centre {centre_frac} scale {scale:.2f} strength {strength}')
    return out_path
