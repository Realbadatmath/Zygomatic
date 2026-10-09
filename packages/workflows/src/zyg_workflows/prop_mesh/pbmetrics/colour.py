# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import numpy as np
from scipy import ndimage

from zyg_workflows.prop_mesh.pbmetrics.constants import BALD_BLUR, BALD_TAU
from zyg_workflows.prop_mesh.pbmetrics.io_matte import _luma, largest_component


# ═════════════════════════════════════════════════════════════════════════════
# colour
# ═════════════════════════════════════════════════════════════════════════════
def _srgb_to_lab(rgb):
    """sRGB [0,1] -> CIELAB (D65). Written out rather than pulled from skimage so the
    module keeps its numpy+scipy+PIL-only dependency set and stays testable in .venv-test."""
    a = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    m = np.array(
        [[0.4124564, 0.3575761, 0.1804375], [0.2126729, 0.7151522, 0.0721750], [0.0193339, 0.1191920, 0.9503041]]
    )
    xyz = a @ m.T
    wp = np.array([0.95047, 1.00000, 1.08883])
    t = xyz / wp
    d = 6.0 / 29.0
    f = np.where(t > d**3, np.cbrt(t), t / (3 * d * d) + 4.0 / 29.0)
    L = 116.0 * f[..., 1] - 16.0
    A = 500.0 * (f[..., 0] - f[..., 1])
    B = 200.0 * (f[..., 1] - f[..., 2])
    return np.stack([L, A, B], axis=-1)


def plate_region(rgb, mask, min_px=400):
    """The bare skin plate: teal pixels inside the matte.

    Found by colour rather than by position because the plate moves as the head shape and
    the hairline change, and a fixed box would drift off it exactly when a search starts
    altering the fur coverage. Teal is `g` above `r` and `b` above `r`, which separates the
    aqua plate from the white crown, the cream belly, the amber eyes and the olive feet.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    teal = mask & (g > r + 0.04) & (b > r + 0.02)
    if teal.sum() < min_px:
        return None
    teal = largest_component(teal)
    if teal.sum() < min_px:
        return None
    return teal


def surface_detail(rgb, mask, size=192):
    """High-frequency relief ON THE PLATE, scale-normalised.

    WHY THIS EXISTS. The first CMA run drove MICRO['height'] and MICRO['bump_keep'] both to
    zero — it deleted the plate's entire surface relief. That was not a finding about
    displacement, it was a hole in the objective: no term measured plate micro-detail, and
    the two scored views are whole-body framings where the plate is ~120 px across. A
    parameter the loss cannot see costs nothing to zero, and zeroing it reads afterwards as
    evidence that it never mattered. This is the same failure as a critic rubric whose
    "major" bar nothing can fail.

    The plate is cropped to its own bounding box and resampled to a fixed size before
    measuring, so a creature that is larger in frame does not automatically score as more
    detailed — the question is detail PER UNIT OF PLATE, not per pixel. The result is
    normalised by local mean luminance, so it does not move with exposure.
    """
    reg = plate_region(rgb, mask)
    if reg is None:
        return float('nan')
    ys, xs = np.nonzero(reg)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    g = _luma(rgb)[y0:y1, x0:x1]
    m = reg[y0:y1, x0:x1]
    if g.shape[0] < 8 or g.shape[1] < 8:
        return float('nan')
    zoom = (size / g.shape[0], size / g.shape[1])
    gz = ndimage.zoom(g, zoom, order=1)
    mz = ndimage.zoom(m.astype(float), zoom, order=1) > 0.5
    if mz.sum() < 64:
        return float('nan')
    hp = gz - ndimage.gaussian_filter(gz, size / 24.0)
    base = float(np.mean(gz[mz]))
    if base <= 1e-6:
        return float('nan')
    return float(np.std(hp[mz]) / base)


def largest_smooth_patch(rgb, mask, tau=BALD_TAU):
    """THE COAT-PRESENCE TERM: the biggest CONTIGUOUS low-texture patch inside the subject,
    as a fraction of subject area. Small when the creature is furred all over, large when
    a region of it is bare.

    WHY THIS EXISTS. On 2026-08-29 a 20-parameter CMA-ES fit drove the coat BALD — the
    undercoat grew longer than the locks it sits under and swallowed them — and the search
    was rewarded for it: measured on the front view, ALL NINE existing terms ranked the
    bald render BETTER than the furry production render. `fill` (coverage inside the
    subject's own bbox) was the loudest, because a bald body has no gaps between locks and
    therefore maximises it; the v1 sphere's fill is 0.6469 against the anchor's 0.6755
    while production sits at 0.6311, so the KNOWN-BAD NULL SCORED BETTER THAN THE RENDER
    and `fill` was normalised by a denominator of 0.0286 into a term worth 1.55.

    TWO PROPERTIES DO THE WORK, and each replaces a design that was measured and failed:

    RELATIVE, not absolute. The threshold is a fraction of the subject's own median local
    contrast. The anchors are generated images and the candidates are Cycles renders; on
    absolute texture energy the render/anchor domain gap dwarfs the fur/no-fur difference
    and points the wrong way. A per-azimuth absolute fur-energy profile was built and
    scored the bald render 1.032 against furry production 0.992 — no useful separation.

    AN EXTREMUM, not a mean. Baldness is REGIONAL — one flank goes bare while the crown
    stays furred — and every other term in this file is a whole-subject scalar that
    averages the defect away against the fur elsewhere. A whole-subject "fringe softness"
    mean was built and ranked the BALD render BETTER than furry production (0.385 vs
    0.493). Taking the largest CONNECTED COMPONENT is what makes a local failure legible.

    ITS NULL IS NOT THE v1 SPHERE. Measured selectivity against the sphere is 48.9 on the
    front view and 1.0 on the side — the sphere is uniformly smooth, so relative to its OWN
    median it has no smooth PATCH and scores like a furred creature. Against a bald-but-
    correctly-framed render the selectivity is 189.5 / 100.6. A coat term's known-bad is a
    bald render; see pbopt.BALD_NULL_DIR and usable_terms(nulls=...).
    """
    g = _luma(rgb)
    xs = np.nonzero(mask)[1]
    if xs.size < 64:
        return float('nan')
    sub_w = float(xs.max() - xs.min() + 1)
    s = max(sub_w * BALD_BLUR, 1.0)
    e = ndimage.gaussian_filter(np.abs(g - ndimage.gaussian_filter(g, s)), s * 2.0)
    med = float(np.median(e[mask]))
    if med <= 1e-9:
        return 1.0  # featureless subject: entirely "smooth"
    smooth = mask & (e < tau * med)
    lab, n = ndimage.label(smooth)
    if n == 0:
        return 0.0
    return float(ndimage.sum(smooth, lab, range(1, n + 1)).max()) / float(mask.sum())


def lab_stats(rgb, mask):
    """Median L, a, b inside the mask. Median, not mean: the bokeh motes and the specular
    hits on the eyes are outliers that drag a mean and leave a median alone."""
    if mask.sum() < 16:
        return {'L': float('nan'), 'a': float('nan'), 'b': float('nan')}
    lab = _srgb_to_lab(rgb[mask])
    return {'L': float(np.median(lab[:, 0])), 'a': float(np.median(lab[:, 1])), 'b': float(np.median(lab[:, 2]))}
