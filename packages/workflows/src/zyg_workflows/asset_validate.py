# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""asset_validate.py — PREFLIGHT GEOMETRY GATE for prop reference assets (2026-07-31).

WHY THIS EXISTS
---------------
The scene20_v8b video shipped with a pipe that "morphs and is too big", a phantom
"metal band" round the stem and a "thin black line from the hand to the pipe". None of
those were sampler defects. They were the reference asset being faithfully reproduced:
`assetlib_items/_previews/clay_pipe.png` — the image handed to VACE as the canonical
"clay pipe" — is a VASE with a short bent spout, a dark painted ring where the spout
meets the body, and a grey GRADIENT backdrop. Measured: elongation 2.21 where a
17th-century Gouda pipe needs 10-18, and a bowl 45% as wide as the whole object where
the period maximum is ~10%. The gradient backdrop is not cosmetic either: it leaks into
the white-blob segmentation (the bright floor merges with the object), so every
downstream geometric measurement of that asset was also wrong.

Nothing in the pipeline ever looked at the asset. A wrong input passed silently through
a 4.5-hour render and was only caught by the operator watching the finished film.

This module is that missing look. It is deliberately FAIL-CLOSED (per the v9 plan's C6):
an exception, an unreadable file or a segmentation that finds nothing all return
ok=False with a reason. An asset gate that passes when it breaks is not a gate.

    from zyg_workflows.asset_validate import measure_prop, validate_prop_ref
    m = measure_prop('data/assets/refs/gouda_pipe_ref.png')
    v = validate_prop_ref('data/assets/refs/gouda_pipe_ref.png')   # -> {'ok': bool, ...}

CLI:
    python asset_validate.py <image> [<image> ...] [--min-elong 10] [--max-bowl 0.12]
    python asset_validate.py --json <image>

MEASUREMENT DEFINITIONS (all on the plan's white-blob segmentation)
------------------------------------------------------------------
segmentation : HSV V>185 & S<70 -> MORPH_OPEN 5x5 -> largest connected component.
               This is the same segmentation the v8b diagnosis used; keeping it
               identical is the point, so historical numbers stay comparable
               (it reproduces the old asset's published elongation of 2.21 exactly).
elongation   : long/short side of the MIN-AREA RECT around the blob's outer contour.
               A Gouda pipe lying in profile is 10-18. A vase is ~2. (fitEllipse — what
               the v8b diagnosis used — is reported alongside as `elongation_ellipse`
               but is NOT gated on: it is numerically degenerate for thin shapes, and
               returned a 7349px major axis on a 1536px-wide correct pipe. The two agree
               to ~3% on compact blobs: the old asset reads 2.15 rect / 2.21 ellipse.)
bowl_to_stem : bowl width / stem width. Guards the hole in the two headline gates — a
               featureless white STRIP scores elongation 26 / bowl_frac 0.04 and passes
               both while being useless as a pipe reference. A pipe's bowl is several
               times wider than its stem; a rod's is not.
blob_share   : largest white component / all white pixels. Every other number describes
               the largest component only, so if a shadow SEVERS the prop the gate would
               otherwise certify a measurement of the bare stem.
bowl_frac    : bowl width / object length, both measured perpendicular/parallel to the
               fitted major axis. The stem is removed by a width-profile split (columns
               whose perpendicular width exceeds `_BOWL_W_MULT` x the stem width are the
               bowl); when no distinct thin stem exists — i.e. the object is one fat
               blob, which is the vase failure mode — the whole object counts as bowl.
               This is a LINEAR ratio, not an area ratio: a real Gouda pipe's bowl is
               ~25% of the silhouette AREA (bowl 35mm tall on a 7mm stem), so an area
               ratio can never sit under a 0.12 gate. The period constraint that
               actually discriminates is how WIDE the bowl is relative to the pipe's
               LENGTH — ~0.05-0.10 for a period pipe, 0.45 for the vase.
backdrop_flat: is the backdrop a single flat tone? Measured on the frame border ring
               outside the object bbox: per-channel std and corner-patch spread. A
               gradient scores False and is a hard fail, because it breaks the very
               segmentation every other number here depends on.
dark_ring_frac: fraction of DARK pixels (V < `_DARK_V`) inside the object silhouette.
               This is the "metal band" / "thin black line" detector — a white clay
               pipe has no dark pixels on it at all, so anything above a few percent is
               a painted band, a ferrule, or a bent-briar-style dark stem.

The measured values are returned so the caller can persist them into the asset-library
record (plan item C2: "store asserted values so a swapped preview re-triggers the
check").
"""

import os

import logging as _zyg_logging

_zyg_log = _zyg_logging.getLogger(__name__)

# Gate constants. Sourced from the v9 fix plan (measured, not guessed):
#   old asset scored elongation 2.21 / bowl_frac 0.446 and would have been blocked here.
MIN_ELONGATION = 10.0  # period Gouda pipe in profile: 10-18
MAX_BOWL_FRAC = 0.12  # period max ~0.10; the vase scored 0.446
MAX_DARK_RING_FRAC = 0.06  # a white clay pipe carries no dark pixels; bands/ferrules do
MIN_BLOB_SHARE = 0.75  # largest component / all white pixels; below this the prop is severed
MIN_BOWL_TO_STEM = 2.0  # bowl width / stem width; below this it is a rod with no bowl

_BOWL_W_MULT = 2.2  # bowl column := perpendicular width > this x stem width
_STEM_PCTL = 40  # stem width := this percentile of the width profile
_DARK_V = 90  # HSV V below this counts as "dark" inside the silhouette
_BACKDROP_STD_MAX = 4.0  # per-channel std of the border ring for "flat"
_BACKDROP_RANGE_MAX = 12  # max-min across corner patch means for "flat"


def _log_noop(_msg):
    pass


def _fail(reason, **extra):
    """Fail-closed skeleton. Every early return goes through here so the shape of the
    dict never depends on which branch failed."""
    out = {
        'elongation': 0.0,
        'bowl_frac': 1.0,
        'backdrop_flat': False,
        'dark_ring_frac': 1.0,
        'ok': False,
        'reasons': [reason],
    }
    out.update(extra)
    return out


def _segment(img, log=_log_noop):
    """The plan's white-blob segmentation.

    Returns (blob uint8 0/1 = largest component, all uint8 0/1 = every white pixel, hsv).
    `all` matters for the backdrop check: if a dark band SEVERS the prop, the largest
    component is only half of it, and measuring the backdrop outside that half's bbox
    would sample the other half of the prop as if it were backdrop.
    """
    import cv2
    import numpy as np

    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    raw = ((hsv[:, :, 2] > 185) & (hsv[:, :, 1] < 70)).astype('uint8') * 255
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(raw, 8)
    if n < 2:
        log('[asset_validate] segmentation found no white blob')
        return None, None, hsv
    idx = int(np.argmax(stats[1:, cv2.CC_STAT_AREA])) + 1
    return (lab == idx).astype('uint8'), (raw > 0).astype('uint8'), hsv


def _width_profile(blob):
    """Rotate the blob so its fitted major axis is horizontal, then return the
    per-column pixel count (= perpendicular width) over the object's extent, plus the
    fitted ellipse. Rotating is what makes 'width' and 'length' meaningful for a pipe
    photographed at any angle."""
    import cv2

    cnts, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cnts:
        return None, None, None
    c = max(cnts, key=cv2.contourArea)
    if len(c) < 5:
        return None, None, None

    # MIN-AREA RECT, not fitEllipse. fitEllipse is what the v8b diagnosis used and it
    # reproduces that report's 2.21 on the old (compact, blobby) asset — but it is
    # numerically degenerate on exactly the shape class this gate exists to certify: on a
    # correct 1536px-wide Gouda pipe guide it returned a major axis of 7349px, i.e. five
    # times the image width, and a bogus bowl reading with it. The rotated rect is stable
    # for thin shapes, agrees with fitEllipse to ~3% where fitEllipse is well-conditioned
    # (vase: 2.15 vs 2.21), and the plan sanctions it explicitly.
    (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
    major, minor = (float(max(rw, rh)), float(min(rw, rh)))
    rot_ang = float(ang) if rw >= rh else float(ang) + 90.0  # bring the LONG side horizontal

    # fitEllipse kept as a diagnostic, guarded against its own blow-up
    ell = None
    try:
        _, (emi, ema), _ = cv2.fitEllipse(c)
        if 0 < emi <= ema and ema < 4.0 * max(blob.shape):
            ell = float(ema) / float(max(emi, 1e-6))
    except Exception:
        ell = None

    M = cv2.getRotationMatrix2D((float(cx), float(cy)), rot_ang, 1.0)
    h, w = blob.shape
    # translate into a double-size canvas so nothing rotates off the edge
    M[0, 2] += w * 0.5
    M[1, 2] += h * 0.5
    rot = cv2.warpAffine(blob, M, (w * 2, h * 2), flags=cv2.INTER_NEAREST)
    prof = rot.sum(axis=0).astype('float64')
    prof = prof[prof > 0]
    return prof, (minor, major), ell


def _bowl_frac(prof, major, log=_log_noop):
    """bowl width / object length. Returns (frac, stem_w, bowl_w, distinct_bowl)."""
    import numpy as np

    if prof is None or prof.size < 8 or major <= 0:
        return 1.0, 0.0, 0.0, False
    stem_w = float(np.percentile(prof, _STEM_PCTL))
    thr = stem_w * _BOWL_W_MULT
    sel = prof > thr
    if sel.any():
        bowl_w = float(prof[sel].max())
        distinct = True
    else:
        # No column is meaningfully fatter than the stem width => there IS no stem.
        # The object is one undifferentiated blob (the vase failure mode): all of it
        # is bowl. Reading 0.0 here would silently pass the exact defect we are
        # gating against.
        bowl_w = float(prof.max())
        distinct = False
        log('[asset_validate] no distinct stem/bowl split — whole object counts as bowl')
    return bowl_w / float(major), stem_w, bowl_w, distinct


def _backdrop_flat(img, blob, log=_log_noop):
    """Flatness of the backdrop, measured on the frame border ring outside the object
    bbox. Returns (is_flat, std_max, corner_range, mean_bgr)."""
    import cv2
    import numpy as np

    h, w = img.shape[:2]
    ring = np.ones((h, w), bool)
    ys, xs = np.where(blob > 0)
    if ys.size:
        pad = max(6, int(0.02 * max(h, w)))
        y0 = max(0, int(ys.min()) - pad)
        y1 = min(h, int(ys.max()) + pad + 1)
        x0 = max(0, int(xs.min()) - pad)
        x1 = min(w, int(xs.max()) + pad + 1)
        ring[y0:y1, x0:x1] = False
    if ring.sum() < 64:
        # object fills the frame — fall back to a thin frame border
        ring[:] = False
        b = max(3, int(0.02 * min(h, w)))
        ring[:b, :] = ring[-b:, :] = ring[:, :b] = ring[:, -b:] = True
    px = img[ring]
    std_max = float(px.reshape(-1, 3).std(axis=0).max())
    # corner patches catch a smooth gradient that a global std can under-report
    k = max(4, int(0.03 * min(h, w)))
    corners = [img[:k, :k], img[:k, -k:], img[-k:, :k], img[-k:, -k:]]
    means = [float(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).mean()) for c in corners]
    crange = float(max(means) - min(means))
    flat = bool(std_max <= _BACKDROP_STD_MAX and crange <= _BACKDROP_RANGE_MAX)
    if not flat:
        log(f'[asset_validate] backdrop NOT flat: std {std_max:.1f} corner-range {crange:.1f}')
    return flat, std_max, crange, [round(float(v), 1) for v in px.reshape(-1, 3).mean(axis=0)]


def measure_prop(image_path, log_fn=None):
    """Measure a prop reference image.

    Returns a dict with keys: elongation, bowl_frac, backdrop_flat, dark_ring_frac,
    ok, reasons — plus diagnostic extras (area_px, stem_w_px, bowl_w_px, major_px,
    minor_px, distinct_bowl, backdrop_std, backdrop_corner_range, backdrop_bgr, path).

    `ok` here is the geometry verdict at the module defaults; use validate_prop_ref for
    an explicit-threshold gate. Fail-closed: anything unmeasurable returns ok=False.
    """
    log = log_fn or _log_noop
    path = str(image_path)
    if not path or not os.path.isfile(path):
        return _fail(f'file not found: {path}', path=path)
    try:
        import cv2
        import numpy as np
    except Exception as e:  # pragma: no cover
        return _fail(f'opencv unavailable: {e}', path=path)

    try:
        img = cv2.imread(path, cv2.IMREAD_COLOR)
        if img is None:
            return _fail(f'unreadable image: {path}', path=path)

        blob, allwhite, hsv = _segment(img, log=log)
        if blob is None or int(blob.sum()) < 64:
            return _fail('no white object found (V>185 & S<70)', path=path)

        # FRAGMENTATION GUARD. Every number below describes the LARGEST component only.
        # If a shadow at the bowl/stem junction severs the prop, the largest component is
        # the bare stem — which measures as elongation 36 and bowl_frac 0.02 and sails
        # through the gate while the actual prop has a fat bowl. That false PASS is the
        # same class of error as the vase itself: a confident number about the wrong
        # object. Refuse to certify a measurement taken on a fragment.
        white_total = int(allwhite.sum()) or 1
        blob_share = float(int(blob.sum())) / float(white_total)

        prof, axes, ell = _width_profile(blob)
        if prof is None or axes is None:
            return _fail('contour too small to measure', path=path)
        minor, major = axes
        elong = float(major / minor) if minor > 1e-6 else 0.0

        bowl_frac, stem_w, bowl_w, distinct = _bowl_frac(prof, major, log=log)
        # bowl-to-stem width ratio. A featureless white STRIP scores elongation 26 and
        # bowl_frac 0.04 and sails through both headline gates while being no use at all
        # as a pipe reference (round-2 sweep produced seven of them). A pipe has a bowl
        # several times wider than its stem; a rod does not.
        bowl_to_stem = float(bowl_w) / float(stem_w) if stem_w > 1e-6 else 0.0
        flat, bstd, brange, bmean = _backdrop_flat(img, allwhite, log=log)

        # Dark pixels ON the object: a white clay pipe has none.
        # Measure inside the FILLED silhouette, not the raw blob. A painted band or a
        # ferrule is dark, so the V>185 segmentation carves it out as a HOLE — counting
        # dark pixels inside `blob` would therefore score the very defect we are hunting
        # as 0.000. Filling the outer contour puts the band back inside the object.
        # Erode afterwards so the anti-aliased rim against the backdrop is not counted.
        # Then DILATE slightly: on the v8 asset the dark rim of the bore and the painted
        # band sit just OUTSIDE the V>185 contour (they are dark, so the segmentation
        # walks around them), which scored the defect as 0.000. A few pixels of headroom
        # puts them back in. Safe against false positives because the required backdrop
        # is flat mid-grey (V=128), well above the dark threshold.
        sil = np.zeros_like(blob)
        cnts2, _ = cv2.findContours(blob, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(sil, cnts2, -1, 1, thickness=-1)
        # Backdrop pixels are excluded by colour-matching the measured backdrop mean, so
        # a legitimately DARK flat backdrop cannot masquerade as a band on the prop.
        band = cv2.dilate(sil, np.ones((7, 7), np.uint8), iterations=1)
        bg_ref = np.array(bmean, dtype='float32').reshape(1, 1, 3)
        is_bg = (np.abs(img.astype('float32') - bg_ref) <= 18.0).all(axis=2)
        dark_px = (hsv[:, :, 2] < _DARK_V) & (band > 0) & (~is_bg)
        area = int(sil.sum()) or int(blob.sum())
        dark_frac = float(int(dark_px.sum())) / float(area)
        # A thin dark RIDGE is the "metal band" / "thin black line" signature — a few
        # hundred pixels arranged in a line, which an area fraction alone under-reports.
        dn, _dl, dstats, _dc = cv2.connectedComponentsWithStats(dark_px.astype('uint8'), 8)
        dark_ridges = 0
        for i in range(1, dn):
            aw, ah, aa = int(dstats[i, 2]), int(dstats[i, 3]), int(dstats[i, 4])
            if aa > 30 and max(aw, ah) / float(max(min(aw, ah), 1)) > 4.0:
                dark_ridges += 1

        reasons = []
        if blob_share < MIN_BLOB_SHARE:
            reasons.append(
                f'silhouette fragmented: largest white component is only '
                f'{blob_share:.0%} of the white pixels — every metric below '
                f'describes a FRAGMENT, not the prop'
            )
        if elong < MIN_ELONGATION:
            reasons.append(
                f'elongation {elong:.2f} < {MIN_ELONGATION} (not a long thin pipe — this is the vase failure mode)'
            )
        if bowl_frac > MAX_BOWL_FRAC:
            reasons.append(
                f'bowl_frac {bowl_frac:.3f} > {MAX_BOWL_FRAC} (bowl too wide relative to pipe length; period max ~0.10)'
            )
        if bowl_to_stem < MIN_BOWL_TO_STEM:
            reasons.append(
                f'bowl_to_stem {bowl_to_stem:.2f} < {MIN_BOWL_TO_STEM} (no distinct bowl — this is a rod, not a pipe)'
            )
        if not flat:
            reasons.append(
                f'backdrop not flat (std {bstd:.1f}, corner range {brange:.1f}) '
                f'— a gradient leaks into the white-blob segmentation'
            )
        if dark_frac > MAX_DARK_RING_FRAC:
            reasons.append(
                f'dark_ring_frac {dark_frac:.3f} > {MAX_DARK_RING_FRAC} (dark band/ferrule/stem on a white clay prop)'
            )

        out = {
            'elongation': round(elong, 3),
            'bowl_frac': round(bowl_frac, 4),
            'backdrop_flat': bool(flat),
            'dark_ring_frac': round(dark_frac, 4),
            'ok': not reasons,
            'reasons': reasons,
            'path': path,
            'area_px': int(blob.sum()),
            'major_px': round(major, 1),
            'minor_px': round(minor, 1),
            'stem_w_px': round(stem_w, 1),
            'bowl_w_px': round(bowl_w, 1),
            'distinct_bowl': bool(distinct),
            'bowl_to_stem': round(bowl_to_stem, 2),
            'elongation_ellipse': (round(ell, 3) if ell else None),
            'dark_ridges': int(dark_ridges),
            'blob_share': round(blob_share, 3),
            'backdrop_std': round(bstd, 2),
            'backdrop_corner_range': round(brange, 2),
            'backdrop_bgr': bmean,
            'size': [int(img.shape[1]), int(img.shape[0])],
        }
        log(
            f'[asset_validate] {os.path.basename(path)}: elong {elong:.2f} '
            f'bowl_frac {bowl_frac:.3f} flat {flat} dark {dark_frac:.3f} '
            f'-> {"PASS" if out["ok"] else "FAIL"}'
        )
        return out
    except Exception as e:
        # FAIL-CLOSED (plan C6): a broken gate must block, never wave through.
        return _fail(f'measurement error: {type(e).__name__}: {str(e)[:160]}', path=path)


def validate_prop_ref(
    path,
    min_elong=MIN_ELONGATION,
    max_bowl_frac=MAX_BOWL_FRAC,
    max_dark_ring=MAX_DARK_RING_FRAC,
    require_flat_backdrop=True,
    log_fn=None,
):
    """Ingest gate. Fail-closed dict:
        {'ok', 'reasons', 'metrics', 'thresholds', 'path'}

    Call this before any asset is written into the library or handed to a render.
    Store `metrics` on the asset record so a swapped preview re-triggers the check.
    """
    log = log_fn or _log_noop
    m = measure_prop(path, log_fn=log_fn)
    reasons = []
    try:
        if m.get('reasons') and not m.get('area_px'):
            # measurement itself failed — propagate verbatim, do not re-derive
            reasons = list(m['reasons'])
        else:
            if float(m['elongation']) < float(min_elong):
                reasons.append(f'elongation {m["elongation"]} < {min_elong}')
            if float(m['bowl_frac']) > float(max_bowl_frac):
                reasons.append(f'bowl_frac {m["bowl_frac"]} > {max_bowl_frac}')
            if float(m['dark_ring_frac']) > float(max_dark_ring):
                reasons.append(f'dark_ring_frac {m["dark_ring_frac"]} > {max_dark_ring}')
            if require_flat_backdrop and not m.get('backdrop_flat'):
                reasons.append('backdrop is not a flat single tone')
            if float(m.get('bowl_to_stem', 0.0)) < MIN_BOWL_TO_STEM:
                reasons.append(f'bowl_to_stem {m.get("bowl_to_stem")} < {MIN_BOWL_TO_STEM}')
            if float(m.get('blob_share', 1.0)) < MIN_BLOB_SHARE:
                reasons.append(
                    f'silhouette fragmented (blob_share {m.get("blob_share")} '
                    f'< {MIN_BLOB_SHARE}) — metrics describe a fragment'
                )
    except Exception as e:
        reasons = [f'gate error: {type(e).__name__}: {str(e)[:160]}']
    ok = not reasons
    log(f'[asset_validate] GATE {os.path.basename(str(path))}: {"PASS" if ok else "FAIL — " + "; ".join(reasons)}')
    return {
        'ok': bool(ok),
        'reasons': reasons,
        'metrics': m,
        'thresholds': {
            'min_elong': float(min_elong),
            'max_bowl_frac': float(max_bowl_frac),
            'max_dark_ring': float(max_dark_ring),
            'require_flat_backdrop': bool(require_flat_backdrop),
        },
        'path': str(path),
    }


if __name__ == '__main__':  # the CLI lives in asset_validate_cli
    from zyg_workflows.asset_validate_cli import main as _cli_main

    raise SystemExit(_cli_main())
