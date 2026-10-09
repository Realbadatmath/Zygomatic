# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

import math
import numpy as np
from scipy import ndimage

from zyg_workflows.prop_mesh.pbmetrics.constants import (
    COHERENCE_FLOOR,
    LOCK_K_MAX,
    LOCK_K_MIN,
    N_AZIMUTH_BINS,
    SIGMA_D,
    SIGMA_I,
    SIL_SCALES,
)
from zyg_workflows.prop_mesh.pbmetrics.io_matte import _luma


# ═════════════════════════════════════════════════════════════════════════════
# orientation — the term the old harness never had
# ═════════════════════════════════════════════════════════════════════════════
def orientation_field(rgb, sigma_d=SIGMA_D, sigma_i=SIGMA_I):
    """Structure tensor -> (theta, coherence).

    `theta` is the direction the STRUCTURE runs, i.e. along a fur lock, in [0, pi). It is
    the minor eigenvector of the tensor: the major eigenvector points ACROSS the lock (up
    the gradient), so the lock direction is that plus 90 degrees.

    `coherence` is (l1-l2)/(l1+l2) in [0,1]: 1 where the neighbourhood is a clean set of
    parallel strands, 0 on flat skin or isotropic noise.

    Both are returned at full resolution; callers mask them.
    """
    g = _luma(rgb)
    gs = ndimage.gaussian_filter(g, sigma_d)
    gy, gx = np.gradient(gs)
    jxx = ndimage.gaussian_filter(gx * gx, sigma_i)
    jyy = ndimage.gaussian_filter(gy * gy, sigma_i)
    jxy = ndimage.gaussian_filter(gx * gy, sigma_i)
    # major-gradient direction; +pi/2 gives the along-structure direction
    theta_grad = 0.5 * np.arctan2(2.0 * jxy, jxx - jyy)
    theta = np.mod(theta_grad + 0.5 * np.pi, np.pi)
    tr = jxx + jyy
    disc = np.sqrt(np.maximum((jxx - jyy) ** 2 + 4.0 * jxy**2, 0.0))
    with np.errstate(divide='ignore', invalid='ignore'):
        coh = np.where(tr > 1e-12, disc / tr, 0.0)
    return theta, np.clip(coh, 0.0, 1.0)


def _radial_theta(mask):
    """Per-pixel angle of the outward radial direction from the matte centroid, in [0,pi)
    as a director. This is the reference against which fur direction is judged, and it
    needs no correspondence between the two images — which is the whole reason the
    comparison works on subjects of different shapes."""
    ys, xs = np.nonzero(mask)
    cy, cx = ys.mean(), xs.mean()
    yy, xx = np.mgrid[0 : mask.shape[0], 0 : mask.shape[1]]
    return np.mod(np.arctan2(yy - cy, xx - cx), np.pi), (cy, cx)


def radial_deviation_profile(rgb, mask, n_bins=N_AZIMUTH_BINS, coherence_floor=COHERENCE_FLOOR):
    """THE coat metric. Registration-free.

    For every confident fur pixel, the angle between the local lock direction and the
    outward radial direction from the body centroid, folded to [0, 90] degrees because
    both are directors. Then averaged in `n_bins` bins of azimuth around the centroid, so
    the result is a signature of HOW THE COAT IS COMBED, per region of the body:

        radial needles off a sphere  -> every bin near 0 deg
        locks laid down over the body -> bins vary, 25-60 deg, and the pattern differs
                                         between crown, flank and belly

    Returns dict with:
        bins        (n_bins,) mean deviation in degrees, nan where a bin has no support
        weight      (n_bins,) summed coherence per bin — the support behind each mean
        mean        support-weighted mean deviation over the whole subject
        kept        fraction of subject pixels that cleared the coherence floor
    """
    theta, coh = orientation_field(rgb)
    rad, (cy, cx) = _radial_theta(mask)
    use = mask & (coh >= coherence_floor)
    if use.sum() < 64:
        return {'bins': [float('nan')] * n_bins, 'weight': [0.0] * n_bins, 'mean': float('nan'), 'kept': 0.0}
    d = np.abs(np.mod(theta[use] - rad[use] + 0.5 * np.pi, np.pi) - 0.5 * np.pi)
    d = np.degrees(d)  # 0..90, director-safe
    w = coh[use]
    ys, xs = np.nonzero(use)
    az = np.mod(np.arctan2(ys - cy, xs - cx), 2 * np.pi)
    idx = np.minimum((az / (2 * np.pi) * n_bins).astype(int), n_bins - 1)
    bins, wt = [], []
    for b in range(n_bins):
        sel = idx == b
        sw = float(w[sel].sum())
        wt.append(sw)
        bins.append(float((d[sel] * w[sel]).sum() / sw) if sw > 1e-9 else float('nan'))
    return {
        'bins': bins,
        'weight': wt,
        'mean': float((d * w).sum() / w.sum()),
        'kept': float(use.sum()) / float(max(mask.sum(), 1)),
    }


def orientation_distance(prof_a, prof_b):
    """Distance between two radial-deviation profiles, in degrees.

    Support-weighted RMS over the bins both profiles actually populate. Bins where either
    side has no support are SKIPPED rather than zero-filled — zero-filling would reward a
    render for having no fur in a region where the anchor has plenty.
    """
    a, b = np.array(prof_a['bins']), np.array(prof_b['bins'])
    wa, wb = np.array(prof_a['weight']), np.array(prof_b['weight'])
    ok = np.isfinite(a) & np.isfinite(b) & (wa > 0) & (wb > 0)
    if not ok.any():
        return float('nan')
    w = np.sqrt(wa[ok] * wb[ok])
    return float(np.sqrt((w * (a[ok] - b[ok]) ** 2).sum() / w.sum()))


# ═════════════════════════════════════════════════════════════════════════════
# lock scale — needles vs shingles, as a number
# ═════════════════════════════════════════════════════════════════════════════
def lock_scale(rgb, mask, k_min=LOCK_K_MIN, k_max=LOCK_K_MAX):
    """Characteristic cross-lock wavenumber, in cycles per SUBJECT WIDTH.

    The subject is cropped to its bbox, high-passed (so body shading does not dominate),
    windowed (so the crop edge does not ring), and transformed. The radially averaged
    power spectrum P(k) is weighted by k so the reported peak is the energy-per-octave
    peak rather than the DC shoulder every natural image has.

    Normalising by subject WIDTH rather than by pixels is what makes the anchor and a
    differently-framed render comparable: it answers "how many locks fit across this
    creature", which is a property of the creature, not of the camera.

    Returns dict: k_peak, k_centroid (energy-weighted mean over the band), slope
    (log-log spectral slope over the band; a coat of fine needles is shallower than a coat
    of broad locks).
    """
    ys, xs = np.nonzero(mask)
    if len(ys) < 256:
        return {'k_peak': float('nan'), 'k_centroid': float('nan'), 'slope': float('nan')}
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    sub_w = float(x1 - x0)
    g = _luma(rgb)[y0:y1, x0:x1]
    m = mask[y0:y1, x0:x1]
    g = np.where(m, g, 0.0)
    # high-pass: remove everything coarser than a fifth of the subject, which is form
    g = g - ndimage.gaussian_filter(g, sub_w / 20.0)
    g = np.where(m, g, 0.0)
    h, w = g.shape
    win = np.outer(np.hanning(h), np.hanning(w))
    F = np.fft.fftshift(np.fft.fft2(g * win))
    P = F.real**2 + F.imag**2
    fy = np.fft.fftshift(np.fft.fftfreq(h)) * h
    fx = np.fft.fftshift(np.fft.fftfreq(w)) * w
    KY, KX = np.meshgrid(fy, fx, indexing='ij')
    # cycles per subject width (x is already in cycles per crop width; scale y to match)
    K = np.sqrt((KX) ** 2 + (KY * (w / max(h, 1))) ** 2)
    kbin = K.astype(int)
    nb = int(min(kbin.max(), math.ceil(k_max) + 2))
    if nb <= int(k_min) + 2:
        return {'k_peak': float('nan'), 'k_centroid': float('nan'), 'slope': float('nan')}
    prof = np.array([P[kbin == i].mean() if (kbin == i).any() else 0.0 for i in range(nb)])
    ks = np.arange(nb, dtype=float)
    band = (ks >= k_min) & (ks <= min(k_max, nb - 1)) & (prof > 0)
    if band.sum() < 4:
        return {'k_peak': float('nan'), 'k_centroid': float('nan'), 'slope': float('nan')}
    energy = prof[band] * ks[band]
    k_peak = float(ks[band][int(np.argmax(energy))])
    k_cent = float((ks[band] * energy).sum() / energy.sum())
    slope = float(np.polyfit(np.log(ks[band]), np.log(prof[band]), 1)[0])
    return {'k_peak': k_peak, 'k_centroid': k_cent, 'slope': slope}


# ═════════════════════════════════════════════════════════════════════════════
# silhouette + framing
# ═════════════════════════════════════════════════════════════════════════════
def silhouette_stats(mask, scales=SIL_SCALES):
    """Multi-scale outline roughness.

    Both the anchor and the render are spiky, so a single isoperimetric number cannot tell
    them apart — the question is spiky at WHICH scale. The mask is blurred by a fraction of
    the subject width and re-thresholded; the isoperimetric quotient P/(2*sqrt(pi*A)) of
    each smoothed mask is reported. A coat of fine needles loses its roughness quickly as
    the blur grows; a coat of broad locks holds it.

    1.0 is a circle. Larger is rougher.
    """
    ys, xs = np.nonzero(mask)
    if len(ys) < 64:
        return {'iso': {}, 'area_px': 0}
    sub_w = float(xs.max() - xs.min() + 1)
    out = {}
    for s in scales:
        sig = max(sub_w * s, 0.5)
        b = ndimage.gaussian_filter(mask.astype(np.float64), sig) > 0.5
        a = float(b.sum())
        if a < 16:
            out['%.3f' % s] = float('nan')
            continue
        # perimeter by counting boundary pixels of the eroded/dilated difference
        er = ndimage.binary_erosion(b, np.ones((3, 3), bool))
        p = float((b & ~er).sum())
        out['%.3f' % s] = p / (2.0 * math.sqrt(math.pi * a))
    return {'iso': out, 'area_px': int(mask.sum())}


def framing_stats(mask):
    """How much of the frame the subject occupies, and where it sits.

    The current render is 25-29% short of the anchor on ink and floats 14% off the bottom
    on the side view. Nothing in the old loop measured this, and it is a one-line camera
    fix, so it gets its own term.
    """
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if len(ys) < 16:
        return {
            'ink': 0.0,
            'w_frac': 0.0,
            'h_frac': 0.0,
            'aspect_hw': float('nan'),
            'top': float('nan'),
            'bottom': float('nan'),
            'fill_bbox': float('nan'),
        }
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    bw, bh = float(x1 - x0 + 1), float(y1 - y0 + 1)
    return {
        'ink': float(mask.sum()) / float(h * w),
        'w_frac': bw / w,
        'h_frac': bh / h,
        'aspect_hw': bh / bw,
        'top': float(y0) / h,
        'bottom': float(h - 1 - y1) / h,
        'fill_bbox': float(mask.sum()) / (bw * bh),
    }
