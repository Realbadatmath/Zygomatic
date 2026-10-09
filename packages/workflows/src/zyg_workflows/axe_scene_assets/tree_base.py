# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets base trunk plate: prompts, framings and the arcane environment pass."""

import os
import shutil
import time

from zyg_workflows import paths

# The package directory, where axe_scene_assets.py used to live: every path below hangs
# off it, as it did when this code was one module up.
_DIR = str(paths.PKG_DIR)
OUT = os.path.join(_DIR, 'output', 'axe_forest')  # own folder, per dept separation
W_GEN, H_GEN = 1216, 704  # SDXL-friendly, 1.727 — close to the render's 832x480
W_REND, H_REND = 832, 480  # what VACE actually renders

_JUG = 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'

# No people in this plate. The negative has to say so in several ways: SDXL will happily
# put a woodsman next to an axe because that is what its training data does.
_NEG_PLATE = (
    'person, man, boy, woman, child, human, face, hand, arm, figure, silhouette, '
    'lumberjack, woodsman, portrait, '
    # the attempt-1 failure, negated explicitly: a horizontal mossy log, and the
    # axe-shaped-tree hybrid that concept fusion produced
    'fallen tree, felled log, log lying on the ground, horizontal trunk, cut log, stump, '
    'axe-shaped tree, hybrid object, tool made of wood, '
    'deformed, blurry, lowres, watermark, text, signature, cartoon, anime, cel shaded, '
    'flat vector, oversaturated, hdr, fisheye, tilted horizon'
)

# ATTEMPT 1 FAILED AND THE FAILURE IS INSTRUCTIVE (seed 11, 2026-08-03).
# Naming the axe and the trunk in one breath ("a hand-axe buried deep in the bark") made
# SDXL FUSE them: it rendered a single giant axe-shaped mossy log lying on the ground —
# an axe made of tree. It also never stood the trunk up, and it dropped the scars entirely.
# Three separate lessons:
#   * concept fusion — two objects in contact get merged unless one is left out;
#   * "trunk" alone does not imply VERTICAL. It has to be said, and the fallen reading
#     has to be negated;
#   * dozens of small repeated marks are exactly the class txt2img drops (same failure as
#     page text). They cannot be prompted in reliably at this scale.
# So the axe is NOT in this prompt at all — it gets added afterwards into a region we
# control. The scars are pushed with size words ("deep", "gouged", "pale") and verified
# by eye rather than assumed.
TREE_BASE_PROMPT = (
    'a single massive VERTICAL standing oak tree trunk rising straight up through the '
    'whole height of the frame, seen straight on at eye level, the trunk fills the centre '
    'of the image from the ground to the top edge, '
    'the bark at chest height is deeply GOUGED and CHOPPED — a dense cluster of hacked '
    'wedge-shaped cuts in the wood, some old and grey, several freshly cut showing bright '
    'pale yellow raw timber under the bark, the cuts overlap each other in a rough patch '
    'about the size of a dinner plate, '
    'pale wood chips and splinters scattered in the moss at the foot of the trunk, '
    'bare birches and pines receding into cold blue mist behind, '
    'low overcast morning light, damp air, ferns, moss, '
    'locked-off camera, eye level, no people, '
    'cinematic photograph, photorealistic, sharp focus'
)

TREE_SCENE_DESC = (
    'a scarred oak trunk with an axe buried in it, dozens of old hatchet marks and fresh '
    'splintered wounds in the bark, cold misty northern forest, overcast morning'
)


def _log_noop(_m):
    pass


def _free(log=_log_noop):
    try:
        from zyg_workflows import _comfy_client as CC

        CC.free_vram(unload_models=True, free_memory=True)
        time.sleep(3)
    except Exception as e:
        log(f'free skipped ({e})')


def build_tree_base(out_path, seed=11, log_fn=None, prompt=None, negative=None, w=W_GEN, h=H_GEN, steps=34, cfg=7.0):
    """SDXL txt2img, NO people — arcane_multichar._base_plate cannot do this.

    That helper is built around regional conditioning for N figures and requires a non-empty
    `descs`; an environment plate has none, so this is a plain full-frame txt2img on the same
    checkpoint. Deliberately photoreal: the arcane pass is a SECOND stage (see
    _arcane_full), exactly as in the multichar method — styling a photoreal plate gives a
    coherent painterly scene, while styling at txt2img time gives flat illustration.
    """
    from zyg_workflows import _comfy_client as CC

    log = log_fn or _log_noop
    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
        '20': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': prompt or TREE_BASE_PROMPT}},
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': negative or _NEG_PLATE}},
        '40': {'class_type': 'EmptyLatentImage', 'inputs': {'width': w, 'height': h, 'batch_size': 1}},
        '41': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['10', 0],
                'positive': ['20', 0],
                'negative': ['21', 0],
                'latent_image': ['40', 0],
                'seed': seed,
                'steps': steps,
                'cfg': cfg,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 1.0,
            },
        },
        '42': {'class_type': 'VAEDecode', 'inputs': {'samples': ['41', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['42', 0], 'filename_prefix': 'ZygAxeTreeBase'}},
    }
    log(f'tree base: {w}x{h} seed {seed}')
    outs = CC.submit(g, timeout_s=900)
    if not outs:
        raise RuntimeError('tree base plate produced no output')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    shutil.copy2(outs[0], out_path)
    return out_path


def sweep_tree_base(seeds=(21, 22, 23, 24, 25, 26), log_fn=None, sheet='tree_sweep.png'):
    """Render one base plate per seed and tile them into a contact sheet.

    Composition at txt2img is a lottery per seed — attempt 1 lost it on a single sample and
    cost a full style pass before that was visible. Six cheap samples reviewed side by side
    is the correct loop for a plate that the whole scene is then built on; it is also how
    we find out whether the scars appear AT ALL, which no amount of prompt reasoning can
    settle.
    """
    from PIL import Image

    log = log_fn or _log_noop
    os.makedirs(OUT, exist_ok=True)
    paths = []
    for s in seeds:
        p = os.path.join(OUT, f'sweep_base_{s}.png')
        if not os.path.isfile(p):
            build_tree_base(p, seed=s, log_fn=log)
        paths.append(p)
    cols = 3
    rows = (len(paths) + cols - 1) // cols
    tw, th = 608, 352  # half-size tiles
    sheet_img = Image.new('RGB', (cols * tw, rows * th), (16, 16, 16))
    for i, p in enumerate(paths):
        with Image.open(p) as im:
            sheet_img.paste(im.convert('RGB').resize((tw, th), Image.LANCZOS), ((i % cols) * tw, (i // cols) * th))
    out = os.path.join(OUT, sheet)
    sheet_img.save(out)
    log(f'sweep sheet: {out}  (seeds {list(seeds)})')
    return out, paths


# ── the 10 review candidates ────────────────────────────────────────────────
#
# THE SCARS ARE INPAINTED, NOT PROMPTED. A six-seed sweep of the txt2img prompt produced
# vertical trunks (the fallen-log fusion was fixed) but ZERO axe marks on any sample —
# two seeds substituted a natural rot-hollow, which is the model reaching for a
# tree-shaped concept instead of a man-made one. Dozens of small repeated marks are the
# same class as the page text that churns in the cabin scene: not reliably promptable.
# So every candidate below gets its scar cluster painted in as a REGION pass, which also
# means the marks land exactly where the shot needs them.
#
# AXE CONTINUITY ACROSS THE SHOT LIST — the plates are not interchangeable:
#   shots 1-2 (close)  the axe IS in the trunk; he has not pulled it out yet.
#   shots 3 & 5 (wide/med)  the axe is IN HIS HAND, so the trunk shows scars and one
#                           FRESH bright wound where it was just pulled from — no axe.
# Getting that backwards would put the axe in two places at once.

_TREE_COMMON = (
    'bare birches and pines receding into cold blue mist behind, low overcast morning '
    'light, damp air, ferns, moss, locked-off camera, eye level, no people, '
    'cinematic photograph, photorealistic, sharp focus'
)

FRAMINGS = {
    # shots 1-2: the trunk face fills the frame; scars big enough to read, axe seated
    'close': {
        'shots': '1-2 (axe in trunk, hand pulls it free)',
        # SMOKE TEST 2: the trunk came back sheathed in moss, so the scar pass had no
        # bark to cut into and produced nothing. "only a little moss" was ignored — the
        # dry, BARE, sunlit-bark reading has to be stated positively and moss negated
        # explicitly (see _NEG_CLOSE).
        # CALIBRATION, third pass. Attempt 1 came back sheathed in moss (nothing for the
        # scars to bite into); attempt 2 negated moss so hard it produced smooth grey
        # utility poles and one cut-off stump. The band between them has to be described
        # positively — a THICK old oak whose bark is bare and fissured at chest height,
        # with the moss allowed to stay low and to one side where it belongs.
        # MOSS, fourth calibration. Attempt 1 sheathed the trunk in moss; attempt 2
        # negated it so hard the trees became smooth grey utility poles; attempt 3 allowed
        # "patches of moss low down" and the model took that as licence to green the whole
        # base. The trunk's SURFACE is now described only as dry fissured bark, moss is not
        # mentioned positively at all, and the negative names every form it came back as.
        # Bark CHARACTER ("thick", "deeply fissured", "heavy ridges") is what keeps this
        # from collapsing back into a pole — that was the missing half of attempt 2.
        'prompt': (
            'a single enormous ancient oak tree, VERTICAL and standing, seen '
            'straight on and CLOSE at chest height, the massive trunk is wider '
            'than the frame and fills it edge to edge, '
            'thick DRY deeply fissured grey-brown oak bark with heavy vertical '
            'ridges and deep furrows, the bare bark surface is clearly readable '
            'across the whole trunk, '
            'shallow depth of field, the misty forest behind is soft and out of '
            'focus, ' + _TREE_COMMON
        ),
        'negative': (
            _NEG_PLATE + ', moss, mossy bark, moss on trunk, green moss, '
            'lichen, ivy, creepers, vines, ferns on the trunk, '
            'green growth on the tree, algae, moss at the base, mossy roots, '
            'overgrown, lush, verdant, '
            'thin tree, sapling, narrow trunk, pole, post, telephone pole, '
            'smooth trunk, smooth bark, birch bark, peeling white bark, '
            'cut stump, flat top, sawn top'
        ),
        'scar_box': (0.28, 0.26, 0.74, 0.66),
        'axe': True,
        'axe_box': (0.42, 0.36, 0.62, 0.56),
        'scene_desc': (
            'a scarred oak trunk with a small iron hatchet buried in the bark, '
            'a cluster of old hatchet cuts and fresh splintered pale wounds '
            'around it, cold misty northern forest, overcast morning'
        ),
        'seeds': (31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 61, 62),
    },
    # shot 3: he walks back; needs ground to walk on and the whole tree standing
    'wide': {
        'shots': '3 (walks back to his mark)',
        'prompt': (
            'a forest clearing with ONE tall standing oak tree exactly in the '
            'centre of the frame, the whole trunk visible from the mossy ground '
            'up out of the top of the frame, open flat mossy ground in the '
            'foreground with room to walk, wide establishing shot, ' + _TREE_COMMON
        ),
        'scar_box': (0.42, 0.40, 0.58, 0.56),
        'axe': False,
        'scene_desc': (
            'one tall standing oak in a misty clearing, a patch of old axe '
            'cuts and one fresh pale wound on its trunk, NO axe present, '
            'cold northern forest, overcast morning'
        ),
        'seeds': (41, 42, 43, 44, 45, 46, 47, 48, 49),
    },
    # shot 5: from the throwing mark — the tree is the target, foreground is his ground
    'med': {
        'shots': '5 (the throw, tree as target)',
        'prompt': (
            'a standing oak tree about ten metres away, exactly centred in the '
            'frame, seen from a low clearing with open mossy ground running away '
            'toward it in the foreground, medium shot, the trunk reads clearly '
            'against the misty forest behind, ' + _TREE_COMMON
        ),
        'scar_box': (0.44, 0.38, 0.57, 0.55),
        'axe': False,
        'scene_desc': (
            'a standing oak ten metres off across open mossy ground, a patch '
            'of old axe cuts on its trunk, NO axe present, cold misty '
            'northern forest, overcast morning'
        ),
        'seeds': (51, 52, 53, 54, 55, 56, 57, 58, 59),
    },
}

# SMOKE TEST 1 FAILED — a hard-edged RECTANGLE of sawn log end-grain, tree rings and all,
# pasted onto the trunk. Three separate causes, all fixed here and below:
#   1. denoise 0.85 through VAEEncodeForInpaint regenerates the box from scratch with no
#      regard for surrounding bark, so nothing tied the patch to the tree;
#   2. relock_region masks a RECTANGLE with a 6px blur — at high denoise the box edge is
#      plainly visible, so the region has to be an ellipse with a heavy feather instead;
#   3. "bright pale raw yellow timber" is SDXL's single strongest cue for a FELLED LOG'S
#      CUT FACE. Asking for raw timber on a standing trunk gets you a cross-section.
# The wording now stays inside the vocabulary of BARK being struck, never of timber being
# revealed, and the negative names the log-face reading explicitly.
_SCAR_PROMPT = (
    'the rough vertical bark of the standing tree is battered and HACKED where a hatchet '
    'has struck it many times: narrow slanted gashes chopped INTO the bark, overlapping '
    'each other at angles, the bark torn back in ragged splintered flaps along each cut, '
    'older gashes weathered dark grey, a few newer ones lighter and rougher, '
    'small torn wood fibres and loose bark fragments at the edges of the cuts, '
    'the bark texture continues normally around them, photorealistic, sharp focus'
)
_SCAR_NEG = (
    # the smoke-test failure, named directly
    'tree rings, growth rings, log cross-section, sawn end grain, cut log face, '
    'felled log, sawn plank, flat wooden panel, rectangle, square patch, hard edge, '
    'pasted cutout, smooth polished wood, '
    'smooth bark, natural hollow, rot hole, burl, animal den, '
    'face, carved letters, symbols, runes, graffiti, text'
)

_AXE_PROMPT = (
    'a single iron hatchet buried blade-first in the tree trunk, only the steel head is '
    'sunk into the wood and the short wooden handle juts out toward the viewer and '
    'slightly downward, weathered wooden haft, worn steel, '
    'photorealistic, sharp focus, correct scale — the hatchet is small against the trunk'
)
_AXE_NEG = (
    'giant axe, axe-shaped tree, tree made of wood tool, two axes, floating axe, '
    'axe lying on the ground, blurry, deformed'
)


# ── arcane styling, tuned for ENVIRONMENT rather than faces ─────────────────
#
# arcane_multichar._arcane_full is calibrated for CHARACTER plates: style_arcane at 1.15,
# denoise 0.60, depth ControlNet 0.5, prompt "League of Legends Arcane splash art, bold oil
# painting". Run on a forest it produced hard black outlines, posterised greens and blown
# reds — a cel/edge-filter look, not painterly oil. Faces survive that because a face is a
# large simple form; foliage is thousands of small high-frequency forms and the same
# settings shatter it.
#
# So this is a separate function rather than an argument to that one. Character styling
# stays exactly as calibrated; the environment gets its own numbers, swept below.
_ARC_ENV_NEG = (
    'flat vector, cel shaded, hard black outlines, thick ink outlines, posterised, '
    'high contrast, neon, oversaturated, garish green, comic book, screen print, '
    'photograph, photorealistic, dslr, 3d render, cgi, blurry, lowres, watermark, text'
)


def _arcane_env(
    src_path,
    out_path,
    scene_desc,
    seed=7,
    lora_scale=0.85,
    denoise=0.50,
    cn_strength=0.75,
    cn_end=0.9,
    steps=30,
    cfg=6.0,
    style_word='oil',
    log_fn=None,
):
    """Depth-guided arcane restyle tuned for landscape plates. Returns out_path.

    cn_strength defaults HIGHER than the character pass (0.75 vs 0.5) and denoise LOWER
    (0.50 vs 0.60): an environment has no identity to reinvent, only structure to keep, so
    the depth map should hold the composition hard while the LoRA does surface treatment.
    Depth annotator is vits (Apache-2.0) via arcane_multichar._DEPTH_CKPT.
    """
    from PIL import Image
    from zyg_workflows import _comfy_client as CC
    from zyg_workflows import arcane_multichar as AM

    with Image.open(src_path) as im:
        w, h = im.size
    st = CC.stage_input_image(src_path)
    styles = {
        'oil': (
            'a hand-painted PAINTERLY OIL PAINTING in the concept-art style of Riot '
            'Arcane, thick visible oil brush strokes, soft painterly rendering, muted '
            'desaturated earthy palette, soft cinematic light'
        ),
        'splash': ('League of Legends Arcane splash art, bold oil painting, painterly, cinematic'),
    }
    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
        '11': {
            'class_type': 'LoraLoader',
            'inputs': {
                'model': ['10', 0],
                'clip': ['10', 1],
                'lora_name': 'style_arcane.safetensors',
                'strength_model': float(lora_scale),
                'strength_clip': float(lora_scale),
            },
        },
        '14': {'class_type': 'LoadImage', 'inputs': {'image': st}},
        '15': {
            'class_type': 'DepthAnythingV2Preprocessor',
            'inputs': {'image': ['14', 0], 'ckpt_name': AM._DEPTH_CKPT, 'resolution': 1024},
        },
        '16': {'class_type': 'VAEEncode', 'inputs': {'pixels': ['14', 0], 'vae': ['10', 2]}},
        '18': {'class_type': 'ControlNetLoader', 'inputs': {'control_net_name': 'controlnet-depth-sdxl.safetensors'}},
        '20': {
            'class_type': 'CLIPTextEncode',
            'inputs': {'clip': ['11', 1], 'text': f'{styles.get(style_word, styles["oil"])}, {scene_desc}'},
        },
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['11', 1], 'text': _ARC_ENV_NEG}},
        '19': {
            'class_type': 'ControlNetApplyAdvanced',
            'inputs': {
                'positive': ['20', 0],
                'negative': ['21', 0],
                'control_net': ['18', 0],
                'image': ['15', 0],
                'strength': float(cn_strength),
                'start_percent': 0.0,
                'end_percent': float(cn_end),
            },
        },
        '31': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['11', 0],
                'positive': ['19', 0],
                'negative': ['19', 1],
                'latent_image': ['16', 0],
                'seed': int(seed),
                'steps': int(steps),
                'cfg': float(cfg),
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': float(denoise),
            },
        },
        '40': {'class_type': 'VAEDecode', 'inputs': {'samples': ['31', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['40', 0], 'filename_prefix': 'ZygAxeArcEnv'}},
    }
    outs = CC.submit(g, timeout_s=900)
    if not outs:
        raise RuntimeError('arcane env pass produced no output')
    res = Image.open(outs[0]).convert('RGB')
    if res.size != (w, h):
        res = res.resize((w, h), Image.LANCZOS)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    res.save(out_path)
    return out_path


# (lora, denoise, cn_strength, style_word) — brackets the failed character setting
# (1.15, 0.60, 0.50, 'splash') from several directions at once.
ARC_ENV_SWEEP = [
    (0.60, 0.45, 0.80, 'oil'),
    (0.85, 0.45, 0.80, 'oil'),
    (0.85, 0.55, 0.70, 'oil'),
    (1.10, 0.55, 0.70, 'oil'),
    (0.85, 0.55, 0.70, 'splash'),
    (1.15, 0.60, 0.50, 'splash'),  # the known-bad character setting, as the control
]


def sweep_arcane_env(src_path=None, log_fn=None, sheet='arcane_env_sweep.png'):
    """Style-parameter sweep on ONE plate, tiled with its settings burned in."""
    from PIL import Image, ImageDraw

    log = log_fn or _log_noop
    src = src_path or os.path.join(OUT, 'candidates', '01_close_s31_base.png')
    if not os.path.isfile(src):
        raise SystemExit(f'need a base plate first: {src}')
    outs = []
    for i, (lo, dn, cn, sw) in enumerate(ARC_ENV_SWEEP, 1):
        p = os.path.join(OUT, f'arcsweep_{i}_l{lo}_d{dn}_c{cn}_{sw}.png')
        if not os.path.isfile(p):
            log(f'arc sweep {i}: lora {lo} denoise {dn} cn {cn} {sw}')
            _arcane_env(
                src, p, TREE_SCENE_DESC, seed=7, lora_scale=lo, denoise=dn, cn_strength=cn, style_word=sw, log_fn=log
            )
        outs.append((f'lora {lo} / den {dn} / cn {cn} / {sw}', p))
    cols, tw, th = 3, 600, 348
    rows = (len(outs) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw, rows * (th + 24)), (14, 14, 16))
    d = ImageDraw.Draw(sh)
    for i, (lbl, p) in enumerate(outs):
        x, y = (i % cols) * tw, (i // cols) * (th + 24)
        with Image.open(p) as im:
            sh.paste(im.convert('RGB').resize((tw, th), Image.LANCZOS), (x, y + 24))
        d.text((x + 8, y + 6), f'{i + 1}. {lbl}', fill=(235, 235, 235))
    out = os.path.join(OUT, sheet)
    sh.save(out)
    log(f'arcane env sweep: {out}')
    return out


# Chosen off the 6-way sweep (arcane_env_sweep.png): painterly, structure held, and
# WITHOUT the red/rust bark artifacting that the style LoRA starts throwing above
# denoise ~0.5. The character setting (1.15 / 0.60 / 0.50 / splash) was the visibly
# worst tile in that sweep, which is the diagnosis confirmed rather than assumed.
ARC_ENV = dict(lora_scale=0.85, denoise=0.45, cn_strength=0.80, style_word='oil')
