# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""vfx_metrics.py — the deterministic measurement battery for the VFX Analyzer.

Every number here is computed from pixels alone: one frame, or one adjacent PAIR
of frames. No model, no network, no GPU. These are the readings the analyzer can
always take, on every frame of every clip, and they are what the taxonomy's
higher tiers key off.

Two rules this module exists to enforce:

  1. A metric that cannot fail is not a measurement. Every function returns a
     real number with a documented range so a run can be CALIBRATED against
     frames a human has eyeballed — never a bare boolean verdict.

  2. Anime is animated ON 2s AND 3s. A 24fps file carries 8-12 unique drawings
     per second; the rest are byte-identical repeats. Optical flow between two
     duplicate frames is exactly 0.0, and that zero is an ARTEFACT of the
     shooting cadence, not a measurement of stillness. Nothing in this module
     computes a temporal metric across a duplicate pair — cadence_map() finds
     the unique-cel indices first and pair metrics are only ever taken between
     consecutive UNIQUE cels. Everything downstream inherits that contract.

Working resolution: expensive spatial ops run on a WORK copy capped at
WORK_MAX_W px wide (default 640). Cheap intensity statistics run at full res.
Both scales are reported so a threshold tuned on one clip transfers to another.
"""

import math

import cv2
import numpy as np

WORK_MAX_W = 640  # expensive ops downscale to this width
_EPS = 1e-8


# ── small helpers ────────────────────────────────────────────────────────────


def work_copy(bgr, max_w=WORK_MAX_W):
    """Downscale for the expensive operators. Returns (img, scale) where a
    coordinate in the work image maps to full res by dividing by scale."""
    h, w = bgr.shape[:2]
    if w <= max_w:
        return bgr, 1.0
    s = max_w / float(w)
    return cv2.resize(bgr, (max_w, max(1, int(round(h * s)))), interpolation=cv2.INTER_AREA), s


def _f(x):
    """Everything that leaves this module must be JSON-safe: numpy scalars and
    NaN/inf both break json.dump, and a run log that will not serialise is a
    run that reports nothing."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    return v if math.isfinite(v) else 0.0


def _luma(bgr):
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)


# ── per-frame: intensity, exposure, contrast ─────────────────────────────────


def intensity(bgr):
    """Exposure and contrast. luma_* are 0-255. black_clip/white_clip are the
    FRACTION of pixels crushed/blown (0-1) — an impact frame or a fade lands
    here first, before any effect detector sees it."""
    g = _luma(bgr).astype(np.float32)
    flat = g.ravel()
    p = np.percentile(flat, [1, 5, 25, 50, 75, 95, 99])
    mean, std = float(flat.mean()), float(flat.std())
    lo, hi = float(flat.min()), float(flat.max())
    hist = cv2.calcHist([g.astype(np.uint8)], [0], None, [256], [0, 256]).ravel()
    pr = hist / max(_EPS, hist.sum())
    nz = pr[pr > 0]
    return {
        'luma_mean': _f(mean),
        'luma_std': _f(std),
        'luma_min': _f(lo),
        'luma_max': _f(hi),
        'luma_p1': _f(p[0]),
        'luma_p5': _f(p[1]),
        'luma_p25': _f(p[2]),
        'luma_p50': _f(p[3]),
        'luma_p75': _f(p[4]),
        'luma_p95': _f(p[5]),
        'luma_p99': _f(p[6]),
        'black_clip_frac': _f((flat <= 2).mean()),
        'white_clip_frac': _f((flat >= 253).mean()),
        'rms_contrast': _f(std / 255.0),
        'michelson_contrast': _f((hi - lo) / max(_EPS, hi + lo)),
        'dynamic_range': _f(p[6] - p[0]),
        'entropy_bits': _f(-(nz * np.log2(nz)).sum()),
        'is_near_black': _f(1.0 if mean < 6.0 else 0.0),
        'is_near_white': _f(1.0 if mean > 249.0 else 0.0),
    }


# ── per-frame: colour ────────────────────────────────────────────────────────


def colour(bgr, k_dominant=5):
    """Saturation, hue distribution, Hasler-Susstrunk colourfulness, a warm/cool
    estimate and the k dominant colours. hue_* are in OpenCV degrees (0-179)."""
    img, _ = work_copy(bgr)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0].astype(np.float32), hsv[..., 1].astype(np.float32), hsv[..., 2].astype(np.float32)
    b, g, r = (img[..., i].astype(np.float32) for i in range(3))

    # Hasler-Susstrunk colourfulness (2003): sigma+0.3*mu over the opponent axes.
    rg, yb = r - g, 0.5 * (r + g) - b
    colourfulness = math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)

    # Hue is circular: a plain mean of 179 and 1 is 90 (cyan) which is wrong on
    # a red frame. Weight each pixel's angle by its own saturation so a grey
    # background cannot vote on the hue of a small saturated subject.
    ang = h * (2.0 * math.pi / 180.0)
    w = s / 255.0
    wsum = max(_EPS, float(w.sum()))
    cx, cy = float((np.cos(ang) * w).sum()) / wsum, float((np.sin(ang) * w).sum()) / wsum
    hue_mean = (math.degrees(math.atan2(cy, cx)) % 360.0) / 2.0
    hue_conc = math.hypot(cx, cy)  # 0 = hue is everywhere, 1 = monochrome

    hh = cv2.calcHist([hsv], [0], None, [12], [0, 180]).ravel()
    hh = (hh / max(_EPS, hh.sum())).tolist()

    dom = []
    try:
        px = img.reshape(-1, 3).astype(np.float32)
        if px.shape[0] > 20000:
            px = px[np.random.default_rng(0).choice(px.shape[0], 20000, replace=False)]
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 10, 1.0)
        _, lab, cen = cv2.kmeans(px, int(k_dominant), None, crit, 2, cv2.KMEANS_PP_CENTERS)
        counts = np.bincount(lab.ravel(), minlength=int(k_dominant)).astype(np.float32)
        order = np.argsort(-counts)
        for i in order:
            bb, gg, rr = (int(round(c)) for c in cen[i])
            dom.append(
                {
                    'hex': '#%02x%02x%02x' % (max(0, min(255, rr)), max(0, min(255, gg)), max(0, min(255, bb))),
                    'frac': _f(counts[i] / max(_EPS, counts.sum())),
                }
            )
    except cv2.error:
        dom = []

    return {
        'sat_mean': _f(s.mean()),
        'sat_std': _f(s.std()),
        'sat_p95': _f(np.percentile(s, 95)),
        'val_mean': _f(v.mean()),
        'hue_circmean_deg': _f(hue_mean),
        'hue_concentration': _f(hue_conc),
        'hue_hist12': [_f(x) for x in hh],
        'colourfulness': _f(colourfulness),
        'chan_mean_b': _f(b.mean()),
        'chan_mean_g': _f(g.mean()),
        'chan_mean_r': _f(r.mean()),
        # >1 warm (red-dominant), <1 cool (blue-dominant). Not a Kelvin figure.
        'warm_cool_ratio': _f(r.mean() / max(_EPS, b.mean())),
        'grey_frac': _f((s < 20).mean()),
        'dominant_colours': dom,
    }


# ── per-frame: detail, edges, texture ────────────────────────────────────────


def detail(bgr):
    """Sharpness, edge structure and texture. edge_orient_hist8 is the Sobel
    orientation histogram — parallel speedlines spike one bin, a radial burst
    spreads flat but with high edge_density."""
    img, _ = work_copy(bgr)
    g = _luma(img)
    gf = g.astype(np.float32)

    lap = cv2.Laplacian(gf, cv2.CV_32F)
    gx = cv2.Sobel(gf, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(gf, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(gx, gy)

    med = float(np.median(g))
    canny = cv2.Canny(g, int(max(0, 0.66 * med)), int(min(255, 1.33 * med)))
    edge_density = float((canny > 0).mean())

    ori = np.degrees(np.arctan2(gy, gx)) % 180.0
    strong = mag > max(_EPS, np.percentile(mag, 90))
    if strong.any():
        oh, _e = np.histogram(ori[strong], bins=8, range=(0, 180))
        oh = (oh / max(_EPS, oh.sum())).astype(np.float32)
    else:
        oh = np.zeros(8, np.float32)

    try:
        corners = cv2.goodFeaturesToTrack(g, maxCorners=500, qualityLevel=0.01, minDistance=6)
        n_corner = 0 if corners is None else int(len(corners))
    except cv2.error:
        n_corner = 0

    return {
        'lap_var': _f(lap.var()),  # classic blur score; higher = sharper
        'tenengrad': _f((mag**2).mean()),
        'grad_mean': _f(mag.mean()),
        'grad_p95': _f(np.percentile(mag, 95)),
        'edge_density': _f(edge_density),  # 0-1 fraction of Canny pixels
        'edge_orient_hist8': [_f(x) for x in oh],
        'edge_orient_peak': _f(float(oh.max()) if oh.size else 0.0),
        'edge_orient_entropy': _f(-sum(float(x) * math.log2(float(x)) for x in oh if x > 0)),
        'corner_count': _f(n_corner),
        'texture_energy': _f(float(np.abs(lap).mean())),
    }


def noise_sigma(bgr):
    """Immerkaer (1996) fast noise variance: convolve with a Laplacian-like mask
    whose response to a smooth image is ~0, so what is left is the noise floor.
    Reads film grain, sensor noise and render/denoiser residue alike."""
    img, _ = work_copy(bgr)
    g = _luma(img).astype(np.float32)
    h, w = g.shape
    if h < 3 or w < 3:
        return {'noise_sigma': 0.0}
    m = np.array([[1, -2, 1], [-2, 4, -2], [1, -2, 1]], np.float32)
    conv = cv2.filter2D(g, cv2.CV_32F, m)
    sigma = float(np.abs(conv).sum() * math.sqrt(0.5 * math.pi) / (6.0 * (w - 2) * (h - 2)))
    return {'noise_sigma': _f(sigma)}


def spectrum(bgr):
    """Radial power spectrum slope and a banding score. A heavily denoised or
    upscaled frame loses high-frequency power (slope steepens); posterised
    gradients raise banding_score."""
    img, _ = work_copy(bgr, 512)
    g = _luma(img).astype(np.float32)
    g = g - g.mean()
    h, w = g.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    F = np.fft.fftshift(np.fft.fft2(g * win))
    P = F.real**2 + F.imag**2
    cy, cx = h // 2, w // 2
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2).astype(np.int32)
    rmax = int(min(cy, cx))
    if rmax < 8:
        return {'spectrum_slope': 0.0, 'hf_energy_frac': 0.0, 'banding_score': 0.0}
    prof = np.bincount(r.ravel(), P.ravel(), minlength=rmax + 1)[1:rmax]
    cnt = np.bincount(r.ravel(), minlength=rmax + 1)[1:rmax]
    prof = prof / np.maximum(1, cnt)
    lg = np.log10(np.maximum(prof, _EPS))
    lr = np.log10(np.arange(1, rmax, dtype=np.float32))
    slope = float(np.polyfit(lr, lg, 1)[0]) if lr.size > 4 else 0.0
    hf = float(prof[rmax // 2 :].sum() / max(_EPS, prof.sum()))

    # Banding: a posterised gradient has long runs of one value then a step.
    # Count how much of a blurred frame sits on a small number of exact levels.
    sm = cv2.GaussianBlur(_luma(img), (0, 0), 2.0)
    levels = np.bincount(sm.ravel(), minlength=256).astype(np.float32)
    levels /= max(_EPS, levels.sum())
    top = np.sort(levels)[::-1][:16].sum()
    return {'spectrum_slope': _f(slope), 'hf_energy_frac': _f(hf), 'banding_score': _f(top)}


# ── per-frame: composition and framing ───────────────────────────────────────


def composition(bgr):
    """Where the picture's weight sits. Saliency is the spectral-residual map
    (Hou & Zhang 2007) — no model, and good enough to say WHERE, not WHAT."""
    img, s = work_copy(bgr, 256)
    g = _luma(img).astype(np.float32)
    h, w = g.shape
    F = np.fft.fft2(g)
    logamp = np.log(np.abs(F) + _EPS)
    phase = np.angle(F)
    resid = logamp - cv2.blur(logamp, (3, 3))
    sal = np.abs(np.fft.ifft2(np.exp(resid + 1j * phase))) ** 2
    sal = cv2.GaussianBlur(sal, (0, 0), 3.0)
    tot = max(_EPS, float(sal.sum()))
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = float((sal * xx).sum()) / tot / w, float((sal * yy).sum()) / tot / h

    # thirds mass: fraction of salient energy inside a band around each third line
    band = 0.08
    tx = (np.abs(xx / w - 1 / 3) < band) | (np.abs(xx / w - 2 / 3) < band)
    ty = (np.abs(yy / h - 1 / 3) < band) | (np.abs(yy / h - 2 / 3) < band)
    thirds = float(sal[tx | ty].sum()) / tot

    gsm = cv2.resize(g, (64, 64), interpolation=cv2.INTER_AREA)
    sym_h = 1.0 - float(np.abs(gsm - gsm[:, ::-1]).mean()) / 255.0
    sym_v = 1.0 - float(np.abs(gsm - gsm[::-1, :]).mean()) / 255.0

    return {
        'saliency_cx': _f(cx),
        'saliency_cy': _f(cy),  # 0-1, frame-relative
        'saliency_spread': _f(float(sal.std()) / max(_EPS, float(sal.mean()))),
        'thirds_mass': _f(thirds),
        'symmetry_h': _f(sym_h),
        'symmetry_v': _f(sym_v),
        'centre_bias': _f(1.0 - 2.0 * math.hypot(cx - 0.5, cy - 0.5)),
    }


def letterbox(bgr, thresh=12):
    """Detect matte bars. A shot inside bars has a different EFFECTIVE aspect,
    and every framing metric above must be read against that, not the file's."""
    g = _luma(bgr)
    h, w = g.shape
    rows = g.mean(axis=1)
    cols = g.mean(axis=0)
    top = int(np.argmax(rows > thresh)) if (rows > thresh).any() else 0
    bot = int(np.argmax(rows[::-1] > thresh)) if (rows > thresh).any() else 0
    left = int(np.argmax(cols > thresh)) if (cols > thresh).any() else 0
    right = int(np.argmax(cols[::-1] > thresh)) if (cols > thresh).any() else 0
    ih, iw = max(1, h - top - bot), max(1, w - left - right)
    return {
        'bar_top': _f(top),
        'bar_bottom': _f(bot),
        'bar_left': _f(left),
        'bar_right': _f(right),
        'letterboxed': _f(1.0 if (top + bot) > 0.02 * h else 0.0),
        'pillarboxed': _f(1.0 if (left + right) > 0.02 * w else 0.0),
        'active_aspect': _f(iw / float(ih)),
        'file_aspect': _f(w / float(h)),
    }


# ── per-frame: post-process / optical signatures ─────────────────────────────


def postfx(bgr):
    """Signatures of the COMPOSITING stage, measured on the finished frame:
    bloom, chromatic aberration, vignette, halation. These are the numbers that
    can be read off a reference and fed straight back into a render as
    parameters — the one part of 'copy that look' that is honestly invertible."""
    img, _ = work_copy(bgr)
    h, w = img.shape[:2]
    g = _luma(img).astype(np.float32)

    # Bloom: how much light spills OUT of blown highlights into their surround.
    hi = (g > 235).astype(np.float32)
    if hi.sum() > 8:
        near = cv2.GaussianBlur(hi, (0, 0), 6.0)
        ring = ((near > 0.02) & (hi < 0.5)).astype(np.float32)
        base = float(g[(near <= 0.001)].mean()) if (near <= 0.001).any() else float(g.mean())
        halo = float((g * ring).sum() / max(_EPS, ring.sum())) if ring.sum() > 0 else base
        bloom = max(0.0, (halo - base) / 255.0)
        # radius: distance at which the halo falls to half, probed in rings
        rad = 0.0
        for rr in (2, 4, 6, 8, 12, 16, 24):
            nb = cv2.GaussianBlur(hi, (0, 0), float(rr))
            rg = ((nb > 0.02) & (hi < 0.5)).astype(np.float32)
            if rg.sum() < 8:
                continue
            lift = float((g * rg).sum() / max(_EPS, rg.sum())) - base
            if lift > 0.5 * (halo - base):
                rad = float(rr)
    else:
        bloom, rad = 0.0, 0.0
        hi_frac = 0.0
    hi_frac = float(hi.mean())

    # Chromatic aberration: R and B scaled about the centre relative to G.
    # Search the scale that best aligns each channel's edge map with green's.
    b, gc, r = (img[..., i].astype(np.float32) for i in range(3))

    def _edges(x):
        return cv2.Sobel(cv2.GaussianBlur(x, (0, 0), 1.0), cv2.CV_32F, 1, 1, ksize=3)

    eg = _edges(gc)

    def _best_scale(chan):
        ec, best, bs = _edges(chan), -1.0, 1.0
        for sc in (0.997, 0.998, 0.999, 1.0, 1.001, 1.002, 1.003):
            M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), 0.0, sc)
            wp = cv2.warpAffine(ec, M, (w, h), flags=cv2.INTER_LINEAR)
            v = float((wp * eg).sum())
            if v > best:
                best, bs = v, sc
        return bs

    try:
        sr, sb = _best_scale(r), _best_scale(b)
    except cv2.error:
        sr = sb = 1.0
    ca_px = 0.5 * (abs(sr - 1.0) + abs(sb - 1.0)) * 0.5 * math.hypot(w, h)

    # Vignette: radial luminance falloff, centre ring vs corner ring.
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    rr = np.sqrt(((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2)
    inner = g[rr < 0.35]
    outer = g[rr > 0.90]
    vig = 0.0
    if inner.size > 16 and outer.size > 16:
        vig = max(0.0, 1.0 - float(outer.mean()) / max(_EPS, float(inner.mean())))

    # Halation: red channel spilling further than green around highlights.
    hal = 0.0
    if hi.sum() > 8:
        ring = (cv2.GaussianBlur(hi, (0, 0), 8.0) > 0.02) & (hi < 0.5)
        if ring.any():
            hal = _f((r[ring].mean() - gc[ring].mean()) / 255.0)

    return {
        'bloom_lift': _f(bloom),  # 0-1 luminance lift in the halo
        'bloom_radius_px': _f(rad),  # work-scale px; multiply by 1/scale for full res
        'highlight_frac': _f(hi_frac),
        'ca_scale_r': _f(sr),
        'ca_scale_b': _f(sb),
        'ca_px': _f(ca_px),  # estimated max radial channel offset
        'vignette_strength': _f(vig),  # 0 = flat, 0.4 = heavy
        'halation_red_lift': _f(hal),
    }


# ── per-frame: perceptual hash (the cadence primitive) ───────────────────────


def phash(bgr, size=8):
    """64-bit DCT perceptual hash. Cadence detection lives or dies on this: an
    exact byte compare misses a re-encoded duplicate cel (a lossy codec makes
    every repeat slightly different), and a raw pixel diff cannot tell a repeat
    from a very small move. The hash tolerates codec noise and not motion."""
    g = cv2.resize(_luma(bgr), (size * 4, size * 4), interpolation=cv2.INTER_AREA).astype(np.float32)
    d = cv2.dct(g)[:size, :size]
    flat = d.ravel()[1:]  # drop DC: it only encodes brightness
    med = float(np.median(flat))
    bits = (flat > med).astype(np.uint8)
    v = 0
    for b in bits:
        v = (v << 1) | int(b)
    return v


def hamming(a, b):
    return int(bin(a ^ b).count('1'))


# ── per-pair: motion ─────────────────────────────────────────────────────────


def pair_basic(prev_bgr, cur_bgr):
    """Cheap frame-to-frame difference: how much changed, and did the whole
    picture change at once (a cut) or part of it (a move)."""
    a, _ = work_copy(prev_bgr)
    b, _ = work_copy(cur_bgr)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    ga, gb = _luma(a).astype(np.float32), _luma(b).astype(np.float32)
    diff = np.abs(gb - ga)
    ha = cv2.calcHist([_luma(a)], [0], None, [64], [0, 256]).ravel()
    hb = cv2.calcHist([_luma(b)], [0], None, [64], [0, 256]).ravel()
    ha /= max(_EPS, ha.sum())
    hb /= max(_EPS, hb.sum())
    return {
        'diff_mean': _f(diff.mean()),
        'diff_p95': _f(np.percentile(diff, 95)),
        'diff_frac_moved': _f((diff > 12).mean()),
        'hist_corr': _f(float(cv2.compareHist(ha.astype(np.float32), hb.astype(np.float32), cv2.HISTCMP_CORREL))),
        'luma_delta': _f(float(gb.mean() - ga.mean())),
    }


def global_motion(prev_bgr, cur_bgr):
    """Estimate the CAMERA, then subtract it. A partial-affine fit over tracked
    features decomposes into pan/tilt (dx,dy), zoom (scale) and roll (rotation);
    what the fit does NOT explain is subject motion. Every action detector reads
    residual_* — otherwise a fast pan reads as 'everything in frame is moving'."""
    a, sc = work_copy(prev_bgr)
    b, _ = work_copy(cur_bgr)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    ga, gb = _luma(a), _luma(b)
    h, w = ga.shape
    out = {
        'cam_dx': 0.0,
        'cam_dy': 0.0,
        'cam_zoom': 1.0,
        'cam_roll_deg': 0.0,
        'cam_inliers': 0.0,
        'cam_fit_ok': 0.0,
        'cam_pan_norm': 0.0,
        'cam_tilt_norm': 0.0,
    }
    try:
        p0 = cv2.goodFeaturesToTrack(ga, maxCorners=400, qualityLevel=0.01, minDistance=7)
        if p0 is None or len(p0) < 12:
            return out
        p1, st, _err = cv2.calcOpticalFlowPyrLK(ga, gb, p0, None, winSize=(21, 21), maxLevel=3)
        if p1 is None:
            return out
        st = st.ravel().astype(bool)
        if st.sum() < 12:
            return out
        src, dst = p0[st].reshape(-1, 2), p1[st].reshape(-1, 2)
        M, inl = cv2.estimateAffinePartial2D(src, dst, method=cv2.RANSAC, ransacReprojThreshold=3.0)
        if M is None:
            return out
        scale = math.hypot(M[0, 0], M[1, 0])
        roll = math.degrees(math.atan2(M[1, 0], M[0, 0]))
        n_in = int(inl.sum()) if inl is not None else 0
        out.update(
            {
                'cam_dx': _f(M[0, 2] / max(_EPS, sc)),  # full-res px
                'cam_dy': _f(M[1, 2] / max(_EPS, sc)),
                'cam_zoom': _f(scale),
                'cam_roll_deg': _f(roll),
                'cam_inliers': _f(n_in),
                'cam_fit_ok': _f(1.0 if n_in >= 12 else 0.0),
                'cam_pan_norm': _f(M[0, 2] / float(w)),  # frame-widths per pair
                'cam_tilt_norm': _f(M[1, 2] / float(h)),
            }
        )
        return out
    except cv2.error:
        return out


def flow(prev_bgr, cur_bgr, cam=None):
    """Dense Farneback flow, reported RAW and CAMERA-COMPENSATED.

    residual_* is raw flow minus the global affine field. On a locked-off shot
    the two agree; on a whip pan raw magnitude is enormous and residual is what
    the subject actually did. Detectors must read residual_*."""
    a, sc = work_copy(prev_bgr)
    b, _ = work_copy(cur_bgr)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    ga, gb = _luma(a), _luma(b)
    h, w = ga.shape
    try:
        fl = cv2.calcOpticalFlowFarneback(ga, gb, None, 0.5, 3, 21, 3, 5, 1.2, 0)
    except cv2.error:
        return {'flow_ok': 0.0}
    fx, fy = fl[..., 0], fl[..., 1]
    mag, ang = cv2.cartToPolar(fx, fy, angleInDegrees=True)

    res_fx, res_fy = fx, fy
    if cam and cam.get('cam_fit_ok'):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        s, rot = float(cam['cam_zoom']), math.radians(float(cam['cam_roll_deg']))
        cxw, cyw = w / 2.0, h / 2.0
        dx = float(cam['cam_dx']) * sc
        dy = float(cam['cam_dy']) * sc
        gx = (s * math.cos(rot) * (xx - cxw) - s * math.sin(rot) * (yy - cyw) + cxw + dx) - xx
        gy = (s * math.sin(rot) * (xx - cxw) + s * math.cos(rot) * (yy - cyw) + cyw + dy) - yy
        res_fx, res_fy = fx - gx, fy - gy
    rmag = cv2.magnitude(res_fx, res_fy)

    # direction histogram, weighted by magnitude, on the moving pixels only
    moving = mag > max(0.5, float(np.percentile(mag, 75)))
    if moving.any():
        dh, _e = np.histogram(ang[moving], bins=8, range=(0, 360), weights=mag[moving])
        dh = (dh / max(_EPS, dh.sum())).astype(np.float32)
    else:
        dh = np.zeros(8, np.float32)

    # divergence and curl: a zoom/explosion diverges, a vortex curls
    dfx_dx = cv2.Sobel(res_fx, cv2.CV_32F, 1, 0, ksize=3)
    dfy_dy = cv2.Sobel(res_fy, cv2.CV_32F, 0, 1, ksize=3)
    dfy_dx = cv2.Sobel(res_fy, cv2.CV_32F, 1, 0, ksize=3)
    dfx_dy = cv2.Sobel(res_fx, cv2.CV_32F, 0, 1, ksize=3)

    inv = 1.0 / max(_EPS, sc)
    return {
        'flow_ok': 1.0,
        'flow_mag_mean': _f(mag.mean() * inv),
        'flow_mag_max': _f(mag.max() * inv),
        'flow_mag_std': _f(mag.std() * inv),
        'flow_mag_p95': _f(np.percentile(mag, 95) * inv),
        'flow_moving_frac': _f((mag > 1.0).mean()),
        'flow_dir_hist8': [_f(x) for x in dh],
        'flow_dir_peak': _f(float(dh.max()) if dh.size else 0.0),
        'residual_mag_mean': _f(rmag.mean() * inv),
        'residual_mag_max': _f(rmag.max() * inv),
        'residual_mag_p95': _f(np.percentile(rmag, 95) * inv),
        'residual_moving_frac': _f((rmag > 1.0).mean()),
        'flow_divergence': _f(float((dfx_dx + dfy_dy).mean())),
        'flow_curl': _f(float((dfy_dx - dfx_dy).mean())),
        '_residual_field': (res_fx, res_fy),  # popped before serialisation
    }


def motion_blobs(res_fx, res_fy, shape_hw, min_area_frac=0.0008, thresh=1.5):
    """Connected regions of residual (non-camera) motion — the raw material for
    both the action detectors and the CURIOSITY channel. A blob nothing claims
    is exactly what the analyzer is supposed to notice and ask about.

    Boxes come back frame-relative (0-1) so they survive any rescale."""
    h, w = shape_hw
    rmag = cv2.magnitude(res_fx, res_fy)
    m = (rmag > thresh).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, connectivity=8)
    fh, fw = m.shape
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area_frac * fw * fh:
            continue
        sel = lab == i
        out.append(
            {
                'x': _f(x / fw),
                'y': _f(y / fh),
                'w': _f(bw / fw),
                'h': _f(bh / fh),
                'area_frac': _f(area / float(fw * fh)),
                'cx': _f(float(cent[i][0]) / fw),
                'cy': _f(float(cent[i][1]) / fh),
                'mag_mean': _f(float(rmag[sel].mean())),
                'mag_max': _f(float(rmag[sel].max())),
                'dx': _f(float(res_fx[sel].mean())),
                'dy': _f(float(res_fy[sel].mean())),
            }
        )
    out.sort(key=lambda b: -b['area_frac'])
    return out[:24]


def change_blobs(prev_bgr, cur_bgr, cam=None, thresh=14, min_area_frac=0.0008):
    """Camera-compensated COLOUR change regions — the second motion channel.

    Dense optical flow has two blind spots that matter constantly in animation:

      * the aperture problem — a uniform patch translating across a uniform
        background has no interior gradient, so there is nothing for flow to
        solve for and it returns ~zero. Measured on the fixture: a 40px square
        moving 20px per cel produced max flow 1.16 and ZERO blobs.
      * appearance — an object that pops into frame has no correspondence in
        the previous frame, so flow cannot represent it at all.

    Differencing catches both, and differencing ACROSS CHANNELS also catches the
    constant-luminance hue change that greyscale differencing misses. The camera
    is warped out first, so a pan does not light up the whole frame."""
    a, sc = work_copy(prev_bgr)
    b, _ = work_copy(cur_bgr)
    if a.shape != b.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    h, w = a.shape[:2]
    warped = a
    if cam and cam.get('cam_fit_ok'):
        s_, rot = float(cam['cam_zoom']), math.radians(float(cam['cam_roll_deg']))
        M = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), -math.degrees(rot), s_)
        M[0, 2] += float(cam['cam_dx']) * sc
        M[1, 2] += float(cam['cam_dy']) * sc
        warped = cv2.warpAffine(a, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    d = cv2.absdiff(warped, b).max(axis=2)
    d = cv2.GaussianBlur(d, (0, 0), 1.2)
    m = (d > thresh).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    n, lab, stats, cent = cv2.connectedComponentsWithStats(m, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if area < min_area_frac * w * h:
            continue
        sel = lab == i
        out.append(
            {
                'x': _f(x / w),
                'y': _f(y / h),
                'w': _f(bw / w),
                'h': _f(bh / h),
                'area_frac': _f(area / float(w * h)),
                'cx': _f(float(cent[i][0]) / w),
                'cy': _f(float(cent[i][1]) / h),
                'mag_mean': _f(float(d[sel].mean()) / 32.0),
                'mag_max': _f(float(d[sel].max()) / 32.0),
                'dx': 0.0,
                'dy': 0.0,
                'src': 'change',
            }
        )
    out.sort(key=lambda b: -b['area_frac'])
    return out[:24]


# ── cadence: the unique-cel contract ─────────────────────────────────────────


def thumb(bgr, w=128):
    """Tiny COLOUR thumbnail — the second opinion in the duplicate test.

    Colour, not greyscale, and the reason is measured: a region that changes hue
    at constant luminance is invisible to every greyscale comparison. Flat-colour
    animation is full of exactly that — on the test fixture a red object on a blue
    ground differed by 1.8 luminance levels and 130 chroma levels, so a greyscale
    duplicate test declared 40 frames of motion to be one held cel."""
    h = max(1, int(round(bgr.shape[0] * w / float(bgr.shape[1]))))
    return cv2.resize(bgr, (w, h), interpolation=cv2.INTER_AREA).astype(np.float32)


def cadence_map(hashes, thumbs=None, dup_bits=4, dup_frac=0.002, dup_delta=10.0):
    """Turn a per-frame hash list into the shooting cadence.

    Returns unique[] (indices of the first frame of each held cel), hold[] (how
    many file frames each cel is held for) and the cadence class. This is the
    single most important preprocessing step for animation: without it every
    temporal metric is diluted by 2-3x with structural zeros, and 'ones' would
    read as motion stopping and starting 12 times a second.

    TWO signals decide a duplicate, and both must agree:

      * the 64-bit DCT hash, which tolerates codec noise, and
      * the FRACTION of thumbnail pixels that changed meaningfully against the
        held cel's ANCHOR frame.

    The hash alone is not enough and the failure is not hypothetical: a 64-bit
    global hash is blind to a small moving object, so a static background with
    one moving element hashed identical and read as a HELD CEL. Every pair
    metric across that stretch then vanished — the analyzer would report a
    still frame while something moved through it.

    The second signal has to be a CHANGED-PIXEL FRACTION, not a mean difference.
    A mean is an average over the whole frame, so a small object moving across a
    large static background averages away to nothing — measured at 0.15 against
    a 1.2 threshold, i.e. invisible. A true held cel changes almost no pixels
    anywhere; a held background with a mover changes few pixels but changes them
    a LOT. Counting them separates the two; averaging them does not."""
    if not hashes:
        return {
            'unique_idx': [],
            'holds': [],
            'cadence': 'unknown',
            'unique_ratio': 0.0,
            'mean_hold': 0.0,
            'hold_hist': {},
        }

    def _same(i, anchor):
        if hamming(hashes[i], hashes[anchor]) > dup_bits:
            return False
        if thumbs is None:
            return True
        ta, tb = thumbs[anchor], thumbs[i]
        if ta is None or tb is None or ta.shape != tb.shape:
            return True
        d = np.abs(tb - ta)
        if d.ndim == 3:
            d = d.max(axis=2)  # worst channel, never the average
        return float((d > dup_delta).mean()) <= dup_frac

    uniq, holds = [0], [1]
    for i in range(1, len(hashes)):
        if _same(i, uniq[-1]):
            holds[-1] += 1
        else:
            uniq.append(i)
            holds.append(1)
    hist = {}
    for hcount in holds:
        hist[str(hcount)] = hist.get(str(hcount), 0) + 1
    mean_hold = sum(holds) / float(len(holds))
    # classify on the MODE, not the mean: a mix of 2s and 3s averages to 2.5,
    # which is a cadence nothing is ever shot on.
    mode = max(hist.items(), key=lambda kv: kv[1])[0] if hist else '1'
    cad = {'1': 'ones', '2': 'twos', '3': 'threes'}.get(mode, 'mixed')
    if len(hist) > 1:
        top = max(hist.values()) / float(len(holds))
        if top < 0.6:
            cad = 'mixed'
    return {
        'unique_idx': uniq,
        'holds': holds,
        'cadence': cad,
        'unique_ratio': _f(len(uniq) / float(len(hashes))),
        'mean_hold': _f(mean_hold),
        'hold_hist': hist,
    }


# ── the full per-frame battery ───────────────────────────────────────────────


def frame_battery(bgr):
    """Every per-frame number, in one dict. This runs on EVERY frame."""
    out = {}
    out.update(intensity(bgr))
    out.update(colour(bgr))
    out.update(detail(bgr))
    out.update(noise_sigma(bgr))
    out.update(spectrum(bgr))
    out.update(composition(bgr))
    out.update(letterbox(bgr))
    out.update(postfx(bgr))
    h, w = bgr.shape[:2]
    out['width'] = _f(w)
    out['height'] = _f(h)
    return out


def pair_battery(prev_bgr, cur_bgr):
    """Every per-pair number. Only ever called between consecutive UNIQUE cels."""
    out = {}
    out.update(pair_basic(prev_bgr, cur_bgr))
    cam = global_motion(prev_bgr, cur_bgr)
    out.update(cam)
    fl = flow(prev_bgr, cur_bgr, cam)
    field = fl.pop('_residual_field', None)
    out.update(fl)
    blobs = []
    if field is not None:
        blobs = motion_blobs(field[0], field[1], prev_bgr.shape[:2])
    for b in blobs:
        b['src'] = 'flow'
    # Union with the change channel: whatever either sees is real motion. An
    # overlapping pair is one region seen twice, tagged 'both'.
    for cb in change_blobs(prev_bgr, cur_bgr, cam):
        hit = None
        for b in blobs:
            ix = max(0.0, min(b['x'] + b['w'], cb['x'] + cb['w']) - max(b['x'], cb['x']))
            iy = max(0.0, min(b['y'] + b['h'], cb['y'] + cb['h']) - max(b['y'], cb['y']))
            inter = ix * iy
            union = b['w'] * b['h'] + cb['w'] * cb['h'] - inter
            if union > _EPS and inter / union >= 0.3:
                hit = b
                break
        if hit is not None:
            hit['src'] = 'both'
        else:
            blobs.append(cb)
    blobs.sort(key=lambda b: -b['area_frac'])
    out['motion_blobs'] = blobs[:24]
    out['motion_blob_count'] = _f(len(blobs))
    out['change_blob_count'] = _f(sum(1 for b in blobs if b.get('src') in ('change', 'both')))
    return out


METRIC_NAMES = None  # filled on first describe() call


def describe():
    """The metric dictionary: every key this module can emit, so the report can
    list what was measured even on a run where a stage failed."""
    global METRIC_NAMES
    if METRIC_NAMES is None:
        blank = np.zeros((64, 96, 3), np.uint8)
        blank[16:32, 16:48] = 200
        f = frame_battery(blank)
        p = pair_battery(blank, blank)
        METRIC_NAMES = {'frame': sorted(f.keys()), 'pair': sorted(p.keys())}
    return METRIC_NAMES
