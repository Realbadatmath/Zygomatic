# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""axe_scene_assets height-field scar decal: height, Sobel normals, Lambert shading and AO."""

import os

from .tree_base import (
    OUT,
    _log_noop,
)
from .candidates import (
    find_trunk,
)


# ═══════════════════════════════════════════════════════════════════════════
# HEIGHT-FIELD SCAR DECAL (2026-08-04) — the ingredient every earlier attempt lacked.
#
# External research (DECALmachine, mesh-decal workflows, Blender baking docs) says damage
# detail is authored ONCE and baked to a map set — normal, height, AO, alpha, colour — and
# that a decal can be built straight from a greyscale HEIGHT image, because height is what
# a normal map is derived from.
#
# Every failed attempt here lacked exactly that:
#   cut solids rendered        -> geometry PROTRUDES; reads as matchsticks on the bark
#   boolean difference         -> broken (see axe_render.py); 97%-black trunk
#   silhouette + gaussian blur -> an alpha mask carries NO DEPTH, so there is no normal to
#                                 compute and therefore no correct lighting
#   texture blended in         -> real material but flat; sits on the surface
# A gouge reads as a gouge because its two walls face different directions and therefore
# catch different amounts of light. That needs surface normals. Normals need height. No
# height field was ever built — this is it.
#
# Implemented in numpy rather than Blender because the output is a 2D plate, so the
# game-engine baking step is unnecessary: height -> Sobel normals -> Lambert shading -> AO
# is the same chain the decal tools run internally, minus the bake.


def build_scar_height(w=512, h=512, n_cuts=26, seed=5, cluster=0.34, depth=1.0, log_fn=None):
    """Deterministic height field of a hatchet-strike cluster. 0 = bark, 1 = deepest.

    Each strike is a V-TROUGH: triangular across its width so the two walls face opposite
    ways, tapered along its length so it starts and ends in the bark rather than stopping
    dead. Overlaps take the MAXIMUM depth, so crossing strikes cut into one another the
    way real repeated blows do instead of averaging into a smooth dish.
    """
    import numpy as np

    log = log_fn or _log_noop
    rng = np.random.default_rng(seed)
    H = np.zeros((h, w), dtype=np.float32)
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = w / 2.0, h / 2.0
    for _i in range(n_cuts):
        ang = rng.uniform(0, 2 * np.pi)
        rad = cluster * min(w, h) * 0.5 * np.sqrt(rng.uniform(0.02, 1.0))
        ox, oy = cx + rad * np.cos(ang), cy + rad * np.sin(ang) * 0.9
        th = rng.uniform(-1.15, 1.15)  # strike angle
        ln = rng.uniform(0.055, 0.135) * w  # length
        wd = rng.uniform(0.012, 0.030) * w  # half-width
        dp = rng.uniform(0.55, 1.0) * float(depth)
        ct, st = np.cos(th), np.sin(th)
        u = (xx - ox) * ct + (yy - oy) * st  # along the strike
        v = -(xx - ox) * st + (yy - oy) * ct  # across it
        across = np.clip(1.0 - np.abs(v) / wd, 0, 1)  # V cross-section
        along = np.clip(1.0 - (np.abs(u) / ln) ** 2.2, 0, 1)  # tapered ends
        H = np.maximum(H, dp * across * along)
    log(f'height field: {n_cuts} cuts, max depth {H.max():.2f}, {100 * (H > 0.02).mean():.1f}% of patch cut')
    return H


def height_to_shading(Hf, light=(-0.55, -0.68, 0.48), ao_radius=9, ambient=0.42):
    """Height -> (shading, ao, depth) via Sobel normals. Standard height->normal chain.

    Returns multiplicative maps: `shading` is 1.0 on untouched bark, <1 on walls turned
    away from the key and >1 on walls turned into it. Because it MULTIPLIES, the plate's
    own bark colour and texture survive underneath — a pasted RGBA decal would replace them.
    """
    import numpy as np
    from scipy import ndimage

    gy = ndimage.sobel(Hf, axis=0, mode='nearest')
    gx = ndimage.sobel(Hf, axis=1, mode='nearest')
    # height increases INTO the surface, so the normal tilts against the gradient
    nz = np.ones_like(Hf)
    n = np.dstack([-gx, -gy, nz])
    n /= np.linalg.norm(n, axis=2, keepdims=True) + 1e-6
    L = np.array(light, dtype=np.float32)
    L /= np.linalg.norm(L)
    lam = np.clip((n * L).sum(axis=2), 0, 1)
    flat = float(np.clip(L[2], 0, 1))  # response of untouched bark
    shading = ambient + (1.0 - ambient) * lam
    shading /= ambient + (1.0 - ambient) * flat + 1e-6  # normalise so bark == 1.0
    # crevice occlusion: a point is dark if its neighbourhood is deeper than it is
    blur = ndimage.uniform_filter(Hf, ao_radius)
    ao = 1.0 - np.clip((blur - Hf * 0.35) * 1.5, 0, 0.65)
    return shading.astype(np.float32), ao.astype(np.float32), Hf


def apply_scars_height(
    plate_path,
    out_path,
    centre_frac=None,
    scale=None,
    seed=5,
    n_cuts=26,
    strength=1.0,
    sapwood=(196, 176, 132),
    sap_amt=0.72,
    light=(-0.55, -0.68, 0.48),
    height_frac=0.38,
    log_fn=None,
):
    """Carve the strike cluster into a plate using the height-field decal.

    Two channels, which is what separates this from every earlier attempt:
      SHADING  multiplies -> the recess darkens on one wall, brightens on the other, and
               the bark's own texture reads THROUGH it;
      SAPWOOD  blends in by DEPTH -> only the trough floors go pale, so the fresh-wood
               colour appears where wood is actually exposed rather than over a whole blob.
    """
    import numpy as np
    from PIL import Image

    log = log_fn or _log_noop
    plate = Image.open(plate_path).convert('RGB')
    PW, PH = plate.size
    if centre_frac is None or scale is None:
        tcx, twf = find_trunk(plate_path)
        centre_frac = centre_frac or (tcx, height_frac)
        scale = scale or max(0.18, min(0.55, twf * 0.62))

    side = max(24, int(PW * scale))
    Hf = build_scar_height(side, side, n_cuts=n_cuts, seed=seed, log_fn=log)
    shading, ao, depth = height_to_shading(Hf, light=light)
    shade = np.clip(1.0 + (shading * ao - 1.0) * float(strength), 0.05, 2.4)

    base = np.asarray(plate, dtype=np.float32)
    cx, cy = int(PW * centre_frac[0]), int(PH * centre_frac[1])
    x0, y0 = cx - side // 2, cy - side // 2
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww, hh = min(side - sx0, PW - dx0), min(side - sy0, PH - dy0)
    if ww > 0 and hh > 0:
        reg = base[dy0 : dy0 + hh, dx0 : dx0 + ww]
        sh = shade[sy0 : sy0 + hh, sx0 : sx0 + ww][..., None]
        dp = depth[sy0 : sy0 + hh, sx0 : sx0 + ww][..., None]
        out = reg * sh
        # exposed wood only where the trough is genuinely deep
        wood = np.array(sapwood, dtype=np.float32)[None, None, :]
        wood = wood * (0.55 + 0.45 * reg.mean(axis=2, keepdims=True) / 160.0)  # sit in-scene
        a = np.clip((dp - 0.35) / 0.65, 0, 1) * float(sap_amt)
        base[dy0 : dy0 + hh, dx0 : dx0 + ww] = out * (1 - a) + wood * a
    Image.fromarray(np.clip(base, 0, 255).astype('uint8')).save(out_path)
    log(f'scars(height): centre {tuple(round(v, 3) for v in centre_frac)} side {side}px strength {strength}')
    return out_path


def apply_scars_ratio3d(
    plate_path,
    out_path,
    centre_frac=None,
    scale=None,
    strength=1.0,
    sapwood=(212, 198, 166),
    sap_amt=0.48,
    prop_dir=None,
    height_frac=0.38,
    log_fn=None,
):
    """The 3D route: carve using Blender's boolean ratio trunk_cut / trunk_plain.

    Now that one Boolean modifier per cut actually subtracts (cut mean 105.0 vs plain
    107.7, 3.76% of frame differing), the ratio is what it was always meant to be: 1.0 on
    untouched bark, <1 in a recess, >1 on a lit wall — carved with REAL geometry on a REAL
    cylinder, so the marks foreshorten toward the trunk's edges. That curvature is the one
    thing the flat numpy height field cannot give.
    """
    import numpy as np
    from PIL import Image

    log = log_fn or _log_noop
    pd = prop_dir or os.path.join(OUT, 'prop3d')
    cut_p, plain_p = os.path.join(pd, 'trunk_cut.png'), os.path.join(pd, 'trunk_plain.png')
    for p in (cut_p, plain_p):
        if not os.path.isfile(p):
            raise SystemExit(f'missing {p} — run prop_mesh/axe_render.py')
    cut = np.asarray(Image.open(cut_p).convert('RGB'), dtype=np.float32)
    plain = np.asarray(Image.open(plain_p).convert('RGB'), dtype=np.float32)
    ratio = np.clip((cut + 1.0) / (plain + 1.0), 0.12, 2.4)
    ratio[np.abs(ratio - 1.0) < 0.02] = 1.0  # kill render noise outside the cuts
    depth = np.clip(1.0 - ratio.mean(axis=2), 0, 1)

    plate = Image.open(plate_path).convert('RGB')
    PW, PH = plate.size
    if centre_frac is None or scale is None:
        tcx, twf = find_trunk(plate_path)
        centre_frac = centre_frac or (tcx, height_frac)
        scale = scale or max(0.25, min(1.0, twf / 0.45))
    rw, rh = int(ratio.shape[1] * scale), int(ratio.shape[0] * scale)
    r = (
        np.asarray(
            Image.fromarray(np.clip(ratio * 127.5, 0, 255).astype('uint8')).resize((rw, rh), Image.LANCZOS),
            dtype=np.float32,
        )
        / 127.5
    )
    d = (
        np.asarray(Image.fromarray((depth * 255).astype('uint8')).resize((rw, rh), Image.LANCZOS), dtype=np.float32)
        / 255.0
    )

    base = np.asarray(plate, dtype=np.float32)
    cx, cy = int(PW * centre_frac[0]), int(PH * centre_frac[1])
    x0, y0 = cx - rw // 2, cy - rh // 2
    sx0, sy0 = max(0, -x0), max(0, -y0)
    dx0, dy0 = max(0, x0), max(0, y0)
    ww, hh = min(rw - sx0, PW - dx0), min(rh - sy0, PH - dy0)
    if ww > 0 and hh > 0:
        reg = base[dy0 : dy0 + hh, dx0 : dx0 + ww]
        rr = 1.0 + (r[sy0 : sy0 + hh, sx0 : sx0 + ww] - 1.0) * float(strength)
        dd = d[sy0 : sy0 + hh, sx0 : sx0 + ww][..., None]
        out = reg * rr
        wood = np.array(sapwood, dtype=np.float32)[None, None, :]
        wood = wood * (0.55 + 0.45 * reg.mean(axis=2, keepdims=True) / 160.0)
        a = np.clip((dd - 0.30) / 0.70, 0, 1) * float(sap_amt)
        base[dy0 : dy0 + hh, dx0 : dx0 + ww] = out * (1 - a) + wood * a
    Image.fromarray(np.clip(base, 0, 255).astype('uint8')).save(out_path)
    log(f'scars(3d ratio): centre {tuple(round(v, 3) for v in centre_frac)} scale {scale:.2f}')
    return out_path
