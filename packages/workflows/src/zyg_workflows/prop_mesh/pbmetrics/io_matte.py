# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import numpy as np
from PIL import Image
from scipy import ndimage

from zyg_workflows.prop_mesh.pbmetrics.constants import MATTE_DC, MATTE_DL, MATTE_EDGE_COLS


# ═════════════════════════════════════════════════════════════════════════════
# IO + matte
# ═════════════════════════════════════════════════════════════════════════════
def load_rgb(path):
    """RGB float64 in [0,1]. Alpha, if present, is DROPPED — a render's alpha is a
    different matte from the anchor's estimated one, and phase 1 proved that comparing
    the two is meaningless."""
    im = Image.open(path)
    if im.mode not in ('RGB', 'RGBA'):
        im = im.convert('RGB')
    a = np.asarray(im.convert('RGB')).astype(np.float64) / 255.0
    return a


def load_mask(path, thresh=0.5):
    """Bool mask from a single-channel or RGB image (any non-black is subject)."""
    a = np.asarray(Image.open(path).convert('L')).astype(np.float64) / 255.0
    return a > thresh


def _luma(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _chroma(rgb):
    """Max-minus-min over the COLOUR axis, which is the last one. Written as -1 rather
    than 2 because estimate_matte calls this on its (h,3) per-row backdrop as well as on
    the (h,w,3) image."""
    return rgb.max(axis=-1) - rgb.min(axis=-1)


def largest_component(mask):
    """Keep only the biggest 8-connected blob.

    This is what makes estimate_matte safe. The floor glow, the bokeh motes and the
    vignette corners all pass a loose threshold; none of them touch the creature, so a
    component pass removes them without any hand-tuned geometric rule like phase 1's
    "trim below the lowest GREEN pixel" (which silently ate the feet on any view where
    the feet were the lowest green thing)."""
    lab, n = ndimage.label(mask, structure=np.ones((3, 3), bool))
    if n == 0:
        return mask
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


def _backdrop(rgb):
    """Bilinear backdrop model: per-row, and linear ACROSS the row.

    A per-row median of the outer columns is not enough. Both the anchor and our renders
    light the floor from one side, so the backdrop has a strong horizontal gradient; a
    single per-row value sits between the dark left edge and the lit right edge, and the
    middle of the floor then differs from it by more than MATTE_DL and joins the matte.
    That is exactly what happened on the first run of this file — the dumped matte showed
    the entire floor welded to the creature and `ink` read 0.577 against a true ~0.39.

    Sampling left and right separately and interpolating between them removes the whole
    class of error, and costs nothing.
    """
    h, w, _ = rgb.shape
    k = max(4, int(round(w * MATTE_EDGE_COLS)))
    left = np.median(rgb[:, :k], axis=1)  # (h,3)
    right = np.median(rgb[:, -k:], axis=1)  # (h,3)
    t = np.linspace(0.0, 1.0, w)[None, :, None]
    return left[:, None, :] * (1.0 - t) + right[:, None, :] * t


def find_horizon(m, min_jump=0.10, win=20):
    """Row index where the ground plane starts, from the mask's OWN row-width profile.

    The creature stands ON the floor, so the two are one connected blob and morphology
    cannot separate them. But a creature narrows towards its feet and a floor does not:
    scanning DOWN from the creature's widest row, the first row where the width starts
    growing again by more than `min_jump` of the frame is the horizon.

    Scanning down from the widest row rather than up from the bottom matters. Up from the
    bottom finds whichever reflection blob happens to end lowest, which on the anchor is a
    specular pool 200 px to the right of the feet.

    Returns None when no widening is found (a subject that does not touch a floor).
    """
    h, w = m.shape
    if not m.any():
        return None
    width = ndimage.uniform_filter1d(m.sum(axis=1).astype(float) / w, 5)
    rows = np.nonzero(m.any(axis=1))[0]
    y_top, y_bot = int(rows.min()), int(rows.max())
    # The widest row must be searched for in the UPPER part of the blob only. A lit floor
    # is WIDER than the creature standing on it (anchor: floor 0.70 of frame, creature
    # 0.63), so a global argmax lands inside the floor, the downward scan then finds
    # nothing, and the cut silently never fires — which is exactly what the first version
    # of this function did, leaving `ink` 34% too high with no error raised.
    y_lim = y_top + int(0.65 * (y_bot - y_top))
    y_wide = int(y_top + np.argmax(width[y_top : max(y_lim, y_top + 2)]))
    # Rise measured over a WINDOW, not between adjacent rows. On the anchor the floor
    # edge is soft: the width climbs 0.24 -> 0.65 over about 30 rows, so the largest
    # single-row step is 0.044 and a per-row threshold of 0.06 never fires — the first
    # version of this function returned None on every image and the cut was dead code
    # that raised nothing. Measured over 20 rows the same transition is +0.41.
    for y in range(y_wide + 1, max(y_bot - win, y_wide + 2)):
        if width[y + win] - width[y] > min_jump:
            # The window says a rise BEGINS somewhere in [y, y+win]; y itself is up to
            # `win` rows too early and cutting there clips the bottom of the creature.
            # The horizon is the TROUGH — the narrowest row before the widening, i.e. the
            # contact line where the feet meet the ground.
            return int(y + np.argmin(width[y : y + win + 1]))
    return None


def _cut_floor(rgb, m, bd, strict_l=2.5, strict_c=1.8):
    """Remove the ground plane while KEEPING the feet.

    Two rules below the horizon, both physical rather than asserted:
      1. x-span: the floor extends sideways past the creature; the creature does not
         suddenly get wider below its own feet. Clip to the span measured in the 40 rows
         above the horizon.
      2. chroma, not brightness. A reflection on a dark floor is dimmer AND desaturated;
         the feet are dim (they sit in the body's shadow) but strongly saturated green.
         Raising BOTH thresholds equally therefore deletes the feet along with the floor
         — the first version of this function did exactly that on the anchor while the
         render, whose floor is darker and never triggered the cut at all, kept its feet.
         Two mattes made by different rules is the phase-1 mistake in a new costume. So
         luminance is raised hard (x2.5) and chroma moderately (x1.8): grey reflections lose,
         green feet survive, and the rule is the same rule on both images.

    Phase 1 of the look-dev did this with "trim below the lowest GREEN pixel", which
    silently ate the feet on every view where the feet were the lowest green thing.
    """
    y_h = find_horizon(m)
    if y_h is None:
        return m
    band = m[max(y_h - 40, 0) : y_h]
    if not band.any():
        return m
    cols = np.nonzero(band.any(axis=0))[0]
    x0, x1 = int(cols.min()), int(cols.max())
    d_l = np.abs(_luma(rgb) - _luma(bd)) * 255.0
    d_c = np.abs(_chroma(rgb) - _chroma(bd)) * 255.0
    hard = (d_l > MATTE_DL * strict_l) | (d_c > MATTE_DC * strict_c)
    out = m.copy()
    out[y_h:] &= hard[y_h:]
    out[y_h:, :x0] = False
    out[y_h:, x1 + 1 :] = False
    return out


def estimate_matte(rgb, close_px=3, cut_floor=True):
    """Subject matte for an image with NO alpha — i.e. the anchor.

    Bilinear backdrop (see _backdrop) -> luminance OR chroma difference -> floor cut ->
    largest connected component -> a small binary closing to bridge the gaps BETWEEN fur
    strands (without it the matte is a sieve and every area term is wrong by ~10%).

    Luminance OR chroma because the anchor's white crown differs from the backdrop in L
    only while its green feet differ mostly in chroma; a single channel loses one of them.

    Returns (mask, backdrop).
    """
    bd = _backdrop(rgb)
    d_l = np.abs(_luma(rgb) - _luma(bd)) * 255.0
    d_c = np.abs(_chroma(rgb) - _chroma(bd)) * 255.0
    m = (d_l > MATTE_DL) | (d_c > MATTE_DC)
    if cut_floor:
        m = _cut_floor(rgb, m, bd)
    # Largest component by GEODESIC RECONSTRUCTION, not directly. What survives the floor
    # cut still includes the specular pool on the floor, joined to the feet by a line a
    # few pixels wide; a plain component pass keeps it because it is genuinely connected.
    # Eroding first snaps those hairline bridges, the component pass then picks the body,
    # and binary_propagation regrows it to the ORIGINAL mask boundary — so individual fur
    # spikes, which the erosion also removed, come back exactly as they were.
    seed = largest_component(ndimage.binary_erosion(m, np.ones((5, 5), bool)))
    if seed.any():
        m = ndimage.binary_propagation(seed, mask=m)
    else:
        m = largest_component(m)
    if close_px > 0:
        st = np.ones((close_px * 2 + 1, close_px * 2 + 1), bool)
        m = ndimage.binary_closing(m, structure=st)
        m = ndimage.binary_fill_holes(m)
    return m, bd
