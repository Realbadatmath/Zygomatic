# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets harmonise pass, hero frame generation and the tight close-up sweep."""

import os
import shutil

from .tree_base import (
    FRAMINGS,
    OUT,
    _arcane_env,
    _log_noop,
    build_tree_base,
)
from .candidates import (
    find_trunk,
    paint_region,
)


# ═══════════════════════════════════════════════════════════════════════════
# HARMONISE (2026-08-04) — stop hand-painting integration, let diffusion do it.
#
# WHAT THE REVIEW SHOWED. The v10 composite carried, in one frame: a hard-edged dark
# RECTANGLE where apply_scars_textured pasted its tile (the mask normalisation
# clip((m-0.18)/0.55) saturates to 1.0 across the region, so the texture fully replaced
# the bark and the region border became a seam); two cream origami-like flags where the
# splinter painter over-drew; a blade that read as CUT OFF rather than buried; and a haft
# ending in mid-air. Every one of those is me hand-authoring an effect in numpy that the
# eye judges against a photograph.
#
# THE DIVISION OF LABOUR THAT ACTUALLY HOLDS:
#   compositing  -> PLACEMENT and IDENTITY  (which axe, exactly where, same every plate)
#   diffusion    -> INTEGRATION             (contact, split bark, splinters, light)
# So the composite now lays down ONLY the clean sprite — no painted wound, no texture
# tile — and a masked inpaint pass over the blade entry is asked for the damage. The
# model has seen ten thousand axes in wood; it knows what the bark does at the entry, and
# it renders it consistent with THIS plate's light because it can see this plate.
#
# paint_region already does the right thing here: SetLatentNoiseMask keeps the original
# latent under the mask, so the axe survives while its surroundings are re-rendered.

_ENTRY_PROMPT = (
    'the steel head of a hatchet is buried deep in the tree trunk, driven into the wood, '
    'the bark is split and crushed where the blade entered, a dark cracked gash follows '
    'the steel into the trunk, pale raw wood shows in the split, small torn splinters and '
    'loose bark fragments at the entry, the wood closes tightly around the buried blade, '
    'photorealistic, sharp focus, overcast forest light'
)
_ENTRY_NEG = (
    'floating axe, axe leaning on the tree, axe in front of the tree, gap between axe and '
    'tree, pasted cutout, hard rectangular edge, rectangle, flag, banner, paper, cloth, '
    'sawn plank, tree rings, log cross-section, blurry, deformed, watermark, text'
)


def harmonise_entry(plate_path, out_path, centre_frac, box_w=0.20, box_h=0.26, denoise=0.52, seed=31, log_fn=None):
    """Re-render a box around the blade entry so the axe joins the wood.

    Deliberately a SMALL region: large inpaints at this denoise start redrawing the trunk
    (the style pass at 0.45 previously invented a rot hole). The box is sized to the head
    and the bark immediately around it, which is the only place the eye checks for contact.
    """
    log = log_fn or _log_noop
    cx, cy = centre_frac
    bbox = (max(0.0, cx - box_w / 2), max(0.0, cy - box_h / 2), min(1.0, cx + box_w / 2), min(1.0, cy + box_h / 2))
    shutil.copy2(plate_path, out_path)
    paint_region(out_path, bbox, _ENTRY_PROMPT, negative=_ENTRY_NEG, denoise=denoise, seed=seed, feather=34, log_fn=log)
    log(f'harmonised entry at {centre_frac} box {box_w}x{box_h} denoise {denoise}')
    return out_path


# ═══════════════════════════════════════════════════════════════════════════
# HERO FRAME — generate the axe-in-tree directly, instead of assembling it (2026-08-04).
#
# Compositing was chosen to guarantee the SAME axe in every shot. That requirement turns
# out to be much smaller than the machinery built for it: the axe is only IN THE TREE for
# shots 1 and 2, which share a framing. Shots 3 and 5 have it in his hand. So cross-shot
# identity costs one reused plate, not a sprite pipeline.
#
# Meanwhile every composite pass traded one artifact for another — pasted rectangle,
# painted flags, a blade that reads as merged rather than driven in — because a 2D element
# laid on a photograph is judged by the eye against everything around it.
#
# The one thing we have now that we did not have at the start is a precise catalogue of how
# THIS generation fails. Each entry in the negative below is a defect that was actually
# observed and diagnosed today, not a guess:
#   fallen log / axe-shaped tree   attempt 1: "axe buried in trunk" fused into ONE object
#   rot hole / natural hollow      seed sweep: model substitutes a tree-shaped concept
#   tree rings / sawn end grain    inpaint 0.85: "pale raw timber" -> felled log cut face
#   leaning / floating / gap       v7-v11: the axe never read as driven in
#   rectangle / pasted cutout      v10: the texture tile's own border
# Negating an observed failure is a far stronger prior than describing a success.
_HERO_PROMPT = (
    'a small iron hatchet DRIVEN DEEP into the trunk of a great oak at chest height, '
    'the steel head is half BURIED in the wood and the bark is split and crushed where it '
    'went in, pale raw wood showing in the split, torn splinters at the entry, '
    'the short wooden haft juts out of the trunk toward the viewer and angles down, '
    'the bark around it is covered with many older hatchet gashes from previous throws, '
    'narrow slanted cuts overlapping each other, some weathered grey, a few pale and fresh, '
    'the tool is SMALL against the huge trunk, '
    'cold misty northern forest, overcast morning light, '
    'photorealistic, sharp focus, high detail'
)
_HERO_NEG = (
    # every clause below is a defect observed and diagnosed on this scene today
    'fallen tree, felled log, log lying down, stump, axe-shaped tree, hybrid object, '
    'natural hollow, rot hole, burl, animal den, knot hole, '
    'tree rings, growth rings, log cross-section, sawn end grain, cut log face, plank, '
    'axe leaning against the tree, axe in front of the tree, floating axe, '
    'gap between the axe and the trunk, axe resting on the ground, '
    'rectangle, square patch, hard edge, pasted cutout, sticker, collage, '
    'two axes, giant axe, oversized axe, hand, person, arm, '
    'blurry, lowres, deformed, watermark, text, cartoon, anime'
)


def hero_sweep(
    bases=('v3_base_71.png', 'v3_base_72.png', 'v3_base_73.png'),
    seeds=(201, 202, 203),
    denoise=0.88,
    box=(0.19, 0.24),
    log_fn=None,
    sheet='hero_sweep.png',
    styled=True,
):
    """img2img the axe + scars straight into each plate's trunk, several seeds.

    High denoise ON PURPOSE — this region has to be INVENTED, not preserved, which is the
    opposite of the harmonise pass. The soft elliptical mask keeps the surrounding bark and
    the trunk silhouette, so the model is only free where we want new content.
    """
    from PIL import Image, ImageDraw

    log = log_fn or _log_noop
    d = os.path.join(OUT, 'hero')
    os.makedirs(d, exist_ok=True)
    spec = FRAMINGS['close']
    made = []
    for bn in bases:
        bp = os.path.join(OUT, bn)
        if not os.path.isfile(bp):
            log(f'skip missing {bn}')
            continue
        tcx, twf = find_trunk(bp)
        for s in seeds:
            tag = f'{bn.replace(".png", "")}_s{s}'
            out = os.path.join(d, f'hero_{tag}.png')
            if not os.path.isfile(out):
                shutil.copy2(bp, out)
                bw = max(0.13, min(0.34, twf * 0.62))
                bbox = (tcx - bw / 2, 0.40 - box[1] / 2, tcx + bw / 2, 0.40 + box[1] / 2)
                log(f'{tag}: hero region {tuple(round(v, 3) for v in bbox)}')
                paint_region(
                    out, bbox, _HERO_PROMPT, negative=_HERO_NEG, denoise=denoise, seed=s, feather=30, log_fn=log
                )
                if styled:
                    _arcane_env(
                        out,
                        out,
                        spec['scene_desc'],
                        seed=s + 400,
                        log_fn=log,
                        lora_scale=0.85,
                        denoise=0.30,
                        cn_strength=0.90,
                        style_word='oil',
                    )
            made.append((tag, out))
    cols, tw, th = 3, 600, 348
    rows = (len(made) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (th + 22)), (14, 14, 16))
    dr = ImageDraw.Draw(sh)
    for i, (tag, p) in enumerate(made):
        x, y = (i % cols) * tw, (i // cols) * (th + 22)
        with Image.open(p) as im:
            sh.paste(im.convert('RGB').resize((tw, th), Image.LANCZOS), (x, y + 22))
        dr.text((x + 8, y + 5), tag, fill=(235, 235, 235))
    out = os.path.join(OUT, sheet)
    sh.save(out)
    log(f'hero sweep: {out}')
    return out, made


# ── shot 1 as a TIGHT CLOSE-UP, generated whole ────────────────────────────
#
# WHY THE REGION-INPAINT HERO FAILED (hero_sweep, 2026-08-04): six of nine samples
# contained no axe at all and the other three were rust-coloured smears. The inpaint box
# was ~267x169 px of a 1216x704 frame, and SDXL cannot resolve a recognisable tool at that
# size. The sprite path worked for exactly the complementary reason — it generated the axe
# at 1024x1024, where there were pixels to spend on a blade.
#
# So give the axe the pixels. Shot 1 is written as a CLOSE anyway ("an axe buried in a
# tree; old scars and fresh wounds all around it"); framing it tight makes the tool the
# SUBJECT rather than a detail, and at that scale the model renders steel, split bark and
# individual gashes without help. The wide/medium plates already work and are unaffected —
# this is one shot's framing, not a change of approach for the scene.
_CLOSEUP_PROMPT = (
    'CLOSE-UP of a small iron hatchet driven deep into the bark of a huge oak tree, '
    'the tree fills the entire frame, the hatchet is in the middle of the frame, '
    'the steel head is half buried in the wood, the bark is split and crushed around the '
    'blade with pale raw wood showing in the split and torn splinters at the entry, '
    'the short weathered wooden haft juts out toward the viewer and angles downward, '
    'the surrounding bark is covered with MANY older hatchet gashes from earlier throws, '
    'narrow slanted overlapping cuts, most weathered dark grey, a few pale and recent, '
    'deeply fissured oak bark, damp, cold overcast forest light, misty forest far behind '
    'and out of focus, '
    'photorealistic, sharp focus, high detail, shallow depth of field'
)


def closeup_sweep(seeds=(301, 302, 303, 304, 305, 306), log_fn=None, sheet='closeup_sweep.png', styled=True):
    """Full-frame tight close-up of the axe in the tree — txt2img, not inpaint."""
    from PIL import Image, ImageDraw

    log = log_fn or _log_noop
    d = os.path.join(OUT, 'closeup')
    os.makedirs(d, exist_ok=True)
    spec = FRAMINGS['close']
    made = []
    for s in seeds:
        p = os.path.join(d, f'closeup_{s}.png')
        if not os.path.isfile(p):
            build_tree_base(p, seed=s, log_fn=log, prompt=_CLOSEUP_PROMPT, negative=_HERO_NEG, steps=36, cfg=7.0)
            if styled:
                _arcane_env(
                    p,
                    p,
                    spec['scene_desc'],
                    seed=s + 500,
                    log_fn=log,
                    lora_scale=0.85,
                    denoise=0.32,
                    cn_strength=0.88,
                    style_word='oil',
                )
        made.append((s, p))
    cols, tw, th = 3, 600, 348
    rows = (len(made) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (th + 22)), (14, 14, 16))
    dr = ImageDraw.Draw(sh)
    for i, (s, p) in enumerate(made):
        x, y = (i % cols) * tw, (i // cols) * (th + 22)
        with Image.open(p) as im:
            sh.paste(im.convert('RGB').resize((tw, th), Image.LANCZOS), (x, y + 22))
        dr.text((x + 8, y + 5), f'closeup seed {s}', fill=(235, 235, 235))
    out = os.path.join(OUT, sheet)
    sh.save(out)
    log(f'closeup sweep: {out}')
    return out, made
