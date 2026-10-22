# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""wound_library.py — a reusable library of TREE WOUND decals (2026-08-04).

WHY THIS EXISTS. Every attempt to put axe scars on a tree in this project failed the same
way, and the failures are worth stating because they define what the library has to supply:

    cut solids rendered in Blender  -> geometry protrudes; matchsticks lying on the bark
    boolean difference (joined)     -> 97%-black trunk (one cutter of 26 disjoint shells)
    silhouette + gaussian blur      -> an alpha carries no depth, so no normal, so no light
    generated texture blended in    -> real material, but flat and stretched
    txt2img / inpaint, 5 ways       -> zero marks, or a sawn-log face, or a rot hollow

The common thread: I kept SYNTHESISING damage. A real axe cut has torn fibre, a lifted bark
lip, a colour gradient from rim to floor and splinters at the exit — none of which comes out
of a Gaussian. The one thing in this scene that worked immediately was the AXE, and it
worked because it was real generated material at 1024px rather than something I built from
primitives. This library puts wounds in that same category.

THE TAXONOMY IS PHYSICAL, NOT COSMETIC.
  cut     a sharp edge severs fibre: V cross-section, crisp rim, pale sapwood along the line
  bruise  a blunt face crushes it: compressed bark, ragged margin, often no clean exposure
  gouge   the edge bit deep and levered: a chunk gone, torn walls
and orthogonally, fresh (pale, sharp, splinters intact) vs weathered (greyed, rim rounded,
callus swelling). A cluster of identical clean cuts reads as decoration; a MIX reads as a
record of many throws over time, which is the whole point of the shot.

FOUR MAPS PER ASSET, NOT ONE IMAGE:
  rgb     the material
  alpha   the mark's extent, for placement
  depth   so the mark can be RELIT to any plate's key and warped onto a curved trunk
  meta    kind / age / angle / source
Without depth an asset is locked to the lighting it was generated under, and that mismatch
is exactly what made every earlier composite look pasted.

LICENCE: assets are GENERATED here (SDXL/Juggernaut) rather than sourced, so the output is
ours and carries no third-party restriction — the same reasoning that settled the axe
sprite. Depth comes from Depth-Anything-V2 **Small** (vits, Apache-2.0); Base/Large/Giant
are CC-BY-NC and are refused project-wide (see arcane_multichar._DEPTH_CKPT).
"""

import json
import os
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(_HERE, 'data', 'assets', 'wounds')
INDEX = os.path.join(ROOT, 'index.json')
_JUG = 'Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors'

# Every wound is generated CENTRED in a square patch of bark, because the alpha is derived
# by asking how far each pixel departs from the surrounding bark — which needs surrounding
# bark to measure against. Generating the mark in isolation on white would give a cleaner
# key but would lose the rim, and the rim is most of what reads as damage.
_BASE = (
    'extreme macro close-up photograph of dark grey-brown oak tree bark filling the '
    'whole frame, rough deeply fissured bark, '
)
_TAIL = (
    'the damage is CENTRED in the frame and undamaged bark surrounds it on all sides, '
    'flat straight-on view, overcast daylight from the upper left, '
    'photorealistic, extremely sharp focus, high detail, macro lens'
)

_NEG = (
    'whole tree, trunk silhouette, forest, landscape, leaves, moss, lichen, '
    'tree rings, growth rings, log cross-section, sawn end grain, cut plank, '
    'carved letters, initials, symbols, runes, graffiti, face, animal, '
    'axe, tool, hand, person, '
    'smooth bark, clean bark, undamaged, blurry, lowres, watermark, text, '
    'illustration, painting, cartoon'
)

SPECS = [
    (
        'cut_fresh_steep',
        'cut',
        'fresh',
        62,
        'ONE fresh axe cut chopped steeply into the bark, a narrow V-shaped slot, the severed '
        'fibres show bright pale cream sapwood along the whole cut, the bark lip is lifted and '
        'splintered at the rim, small torn splinters, ',
    ),
    (
        'cut_fresh_shallow',
        'cut',
        'fresh',
        18,
        'ONE fresh shallow axe cut sliced into the bark at a low angle, a long narrow slice, '
        'pale cream wood exposed in a thin line, the bark peeled back slightly along one edge, ',
    ),
    (
        'cut_fresh_deep',
        'cut',
        'fresh',
        45,
        'ONE deep axe bite chopped into the bark, the blade went in hard, a wide V slot with '
        'bright pale sapwood exposed across its whole floor, torn fibres bridging the gap, ',
    ),
    (
        'cut_weathered_a',
        'cut',
        'weathered',
        70,
        'ONE OLD axe cut in the bark, healed and weathered dark grey, the exposed wood has '
        'greyed and dulled, the rim is rounded and swollen with callus growth, no pale wood, ',
    ),
    (
        'cut_weathered_b',
        'cut',
        'weathered',
        30,
        'ONE OLD weathered hatchet scar in the bark, long since healed, darkened and cracked, '
        'the edges have closed and rolled over with scar tissue, ',
    ),
    (
        'gouge_deep',
        'gouge',
        'fresh',
        52,
        'ONE deep gouge torn out of the bark where an axe bit and levered a chunk away, a '
        'ragged crater with pale raw wood at the bottom and torn walls, loose splinters, ',
    ),
    (
        'gouge_old',
        'gouge',
        'weathered',
        40,
        'ONE OLD gouge in the bark where a chunk was torn out long ago, the crater is dark and '
        'weathered, the edges rounded and overgrown with bark callus, ',
    ),
    (
        'bruise_blunt_a',
        'bruise',
        'fresh',
        0,
        'ONE blunt impact bruise on the bark where a heavy metal object struck flat and CRUSHED '
        'it, the bark is compressed and shattered inward, no clean cut, ragged irregular margin, '
        'crushed fibres, only a hint of pale wood through the cracks, ',
    ),
    (
        'bruise_blunt_b',
        'bruise',
        'weathered',
        0,
        'ONE OLD blunt impact bruise on the bark, the crushed area has weathered dark and the '
        'shattered bark has partly healed over, irregular flattened patch, no clean cut, ',
    ),
    (
        'cut_glancing',
        'cut',
        'fresh',
        8,
        'ONE long glancing axe scrape across the bark where the blade skidded sideways, a '
        'shallow tapering scar, pale wood showing where it bit and fading where it slid off, ',
    ),
]


def _log_noop(_m):
    pass


def _index():
    try:
        with open(INDEX, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {'assets': []}


def _save_index(ix):
    os.makedirs(ROOT, exist_ok=True)
    with open(INDEX, 'w', encoding='utf-8') as f:
        json.dump(ix, f, indent=1)


def list_assets(kind=None, age=None):
    """-> [record]; filter by kind ('cut'|'bruise'|'gouge') and/or age."""
    out = []
    for a in _index().get('assets', []):
        if kind and a.get('kind') != kind:
            continue
        if age and a.get('age') != age:
            continue
        out.append(a)
    return out


def asset_maps(rec):
    """-> (rgb_path, alpha_path, depth_path) for a record."""
    d = os.path.join(ROOT, rec['id'])
    return (os.path.join(d, 'rgb.png'), os.path.join(d, 'alpha.png'), os.path.join(d, 'depth.png'))


def _generate_rgb(prompt, out_path, seed, size=1024, log_fn=None):
    import shutil
    from zyg_workflows import _comfy_client as CC

    g = {
        '10': {'class_type': 'CheckpointLoaderSimple', 'inputs': {'ckpt_name': _JUG}},
        '20': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': prompt}},
        '21': {'class_type': 'CLIPTextEncode', 'inputs': {'clip': ['10', 1], 'text': _NEG}},
        '40': {'class_type': 'EmptyLatentImage', 'inputs': {'width': size, 'height': size, 'batch_size': 1}},
        '41': {
            'class_type': 'KSampler',
            'inputs': {
                'model': ['10', 0],
                'positive': ['20', 0],
                'negative': ['21', 0],
                'latent_image': ['40', 0],
                'seed': int(seed),
                'steps': 38,
                'cfg': 7.0,
                'sampler_name': 'dpmpp_2m',
                'scheduler': 'karras',
                'denoise': 1.0,
            },
        },
        '42': {'class_type': 'VAEDecode', 'inputs': {'samples': ['41', 0], 'vae': ['10', 2]}},
        '50': {'class_type': 'SaveImage', 'inputs': {'images': ['42', 0], 'filename_prefix': 'ZygWound'}},
    }
    outs = CC.submit(g, timeout_s=900)
    if not outs:
        raise RuntimeError('wound rgb: no output')
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    shutil.copy2(outs[0], out_path)
    return out_path


def _generate_depth(src, out_path, log_fn=None):
    """Depth via Depth-Anything-V2 SMALL (vits, Apache-2.0). Never Base/Large — CC-BY-NC."""
    import shutil
    from zyg_workflows import _comfy_client as CC
    from zyg_workflows import arcane_multichar as AM

    st = CC.stage_input_image(src)
    g = {
        '1': {'class_type': 'LoadImage', 'inputs': {'image': st}},
        '2': {
            'class_type': 'DepthAnythingV2Preprocessor',
            'inputs': {'image': ['1', 0], 'ckpt_name': AM._DEPTH_CKPT, 'resolution': 1024},
        },
        '3': {'class_type': 'SaveImage', 'inputs': {'images': ['2', 0], 'filename_prefix': 'ZygWoundDepth'}},
    }
    outs = CC.submit(g, timeout_s=600)
    if not outs:
        raise RuntimeError('wound depth: no output')
    shutil.copy2(outs[0], out_path)
    return out_path


def _derive_alpha(rgb_path, depth_path, out_path, log_fn=None):
    """Alpha = where this patch departs from its own surrounding bark.

    Measured against the OUTER RING's median colour and texture rather than a fixed
    threshold, because every generated patch has its own bark tone. Combined with a centred
    radial prior (the prompt puts the damage in the middle) and with the depth map, which
    independently sees a recess. Largest connected component only — otherwise scattered
    bark speckle keys in as damage.
    """
    import numpy as np
    from scipy import ndimage
    from PIL import Image

    log = log_fn or _log_noop
    a = np.asarray(Image.open(rgb_path).convert('RGB'), dtype=np.float32)
    H, W = a.shape[:2]
    ring = np.ones((H, W), dtype=bool)
    m = int(min(H, W) * 0.22)
    ring[m : H - m, m : W - m] = False
    med = np.median(a[ring], axis=0)
    dev = np.linalg.norm(a - med[None, None, :], axis=2)
    dev /= dev.max() + 1e-6

    d = np.asarray(Image.open(depth_path).convert('L').resize((W, H)), dtype=np.float32) / 255.0
    dmed = float(np.median(d[ring]))
    recess = np.clip((dmed - d) / 0.30, 0, 1)  # darker than bark == further == recessed

    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    r = np.sqrt(((xx - W / 2) / (W / 2)) ** 2 + ((yy - H / 2) / (H / 2)) ** 2)
    prior = np.clip(1.35 - r, 0, 1)

    score = (0.55 * dev + 0.45 * recess) * prior
    thr = float(np.percentile(score, 88))
    fg = score > thr
    fg = ndimage.binary_closing(fg, np.ones((9, 9)))
    fg = ndimage.binary_fill_holes(fg)
    lab, n = ndimage.label(fg)
    if n > 1:
        sizes = ndimage.sum(fg, lab, range(1, n + 1))
        fg = lab == (int(np.argmax(sizes)) + 1)
    alpha = ndimage.gaussian_filter(fg.astype(np.float32), 2.5)
    Image.fromarray((np.clip(alpha, 0, 1) * 255).astype('uint8')).save(out_path)
    log(f'  alpha: {100 * (alpha > 0.5).mean():.1f}% of patch')
    return out_path, float((alpha > 0.5).mean())


def build(specs=None, seed0=900, log_fn=None, force=False):
    """Generate every wound asset and write the index. -> [record]"""
    log = log_fn or _log_noop
    os.makedirs(ROOT, exist_ok=True)
    ix = _index()
    have = {a['id'] for a in ix.get('assets', [])}
    recs = []
    for i, (aid, kind, age, angle, desc) in enumerate(specs or SPECS):
        d = os.path.join(ROOT, aid)
        rgb, alpha, depth = (os.path.join(d, 'rgb.png'), os.path.join(d, 'alpha.png'), os.path.join(d, 'depth.png'))
        if aid in have and os.path.isfile(alpha) and not force:
            log(f'{aid}: exists, skipping')
            recs.append(next(a for a in ix['assets'] if a['id'] == aid))
            continue
        os.makedirs(d, exist_ok=True)
        prompt = _BASE + desc + _TAIL
        log(f'{aid}: generating ({kind}/{age})')
        _generate_rgb(prompt, rgb, seed0 + i * 7, log_fn=log)
        _generate_depth(rgb, depth, log_fn=log)
        _, frac = _derive_alpha(rgb, depth, alpha, log_fn=log)
        rec = {
            'id': aid,
            'kind': kind,
            'age': age,
            'angle_deg': angle,
            'seed': seed0 + i * 7,
            'alpha_frac': round(frac, 4),
            'light': 'upper-left',
            'size': 1024,
            'prompt': prompt,
            'created': time.strftime('%Y-%m-%dT%H:%M:%S'),
        }
        recs.append(rec)
    ix['assets'] = recs
    ix['updated'] = time.strftime('%Y-%m-%dT%H:%M:%S')
    _save_index(ix)
    log(f'library: {len(recs)} assets -> {INDEX}')
    return recs


def contact_sheet(out_path=None, log_fn=None):
    """Tile every asset as rgb / alpha-over-rgb, labelled, for review."""
    from PIL import Image, ImageDraw

    log = log_fn or _log_noop
    recs = list_assets()
    if not recs:
        raise SystemExit('library is empty — run build() first')
    tw = 300
    cols = 5
    rows = (len(recs) + cols - 1) // cols
    sh = Image.new('RGB', (cols * tw * 2, rows * (tw + 22)), (14, 14, 16))
    dr = ImageDraw.Draw(sh)
    for i, r in enumerate(recs):
        rgb, alpha, _ = asset_maps(r)
        x, y = (i % cols) * tw * 2, (i // cols) * (tw + 22)
        im = Image.open(rgb).convert('RGB').resize((tw, tw), Image.LANCZOS)
        sh.paste(im, (x, y + 22))
        al = Image.open(alpha).convert('L').resize((tw, tw), Image.LANCZOS)
        tint = Image.new('RGB', (tw, tw), (255, 60, 60))
        sh.paste(Image.composite(tint, im, al.point(lambda v: int(v * 0.55))), (x + tw, y + 22))
        dr.text((x + 6, y + 5), f'{r["id"]}  {r["kind"]}/{r["age"]}', fill=(235, 235, 235))
    out = out_path or os.path.join(ROOT, 'contact_sheet.png')
    sh.save(out)
    log(f'contact sheet: {out}')
    return out


if __name__ == '__main__':

    def _lg(m):
        print(f'[{time.strftime("%H:%M:%S")}] {m}', flush=True)

    build(log_fn=_lg)
    contact_sheet(log_fn=_lg)
