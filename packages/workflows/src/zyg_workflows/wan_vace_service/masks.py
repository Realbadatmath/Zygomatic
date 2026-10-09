# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""Character mask, A3 motion-envelope mask and the C3 mask preflight gates (original lines 321-830).

Split out of wan_vace_service.py; the code below is unchanged.
"""

import logging as _zyg_logging
from zyg_workflows.wan_vace_service.base import Image, ImageDraw, ImageFilter, _log_noop, exe, math, os

_zyg_log = _zyg_logging.getLogger('zyg_workflows.wan_vace_service')


def build_char_mask(still_path, out_path, n_regions=2, boxes=None, log_fn=None):
    """Build the VACE generation mask: WHITE = characters (generate), BLACK = set (pin).
    Default: detect one face per equal-width column (same layout contract as
    arcane_multichar) and grow each into a generous body envelope. `boxes` overrides with
    explicit [(x0,y0,x1,y1), ...] regions.

    SUPERSEDED for locked-camera shots by build_motion_envelope_mask (A3) — two blurred
    rectangles measure 0.795 white on scene20 and put the whole period wall inside the
    generate region. Kept as the no-motion-record fallback; its output does NOT pass the
    C3 preflight gates."""
    log = log_fn or _log_noop
    im = Image.open(still_path).convert('RGB')
    W, H = im.size
    mask = Image.new('L', (W, H), 0)
    d = ImageDraw.Draw(mask)
    regions = list(boxes or [])
    if not regions:
        try:
            from zyg_workflows import identity_qc_service as IQ
            import tempfile

            for i in range(n_regions):
                x0 = (W // n_regions) * i
                x1 = W if i == n_regions - 1 else (W // n_regions) * (i + 1)
                crop = im.crop((x0, 0, x1, H))
                with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tf:
                    crop.save(tf.name)
                    v = IQ.embed_images([tf.name], log_fn=_log_noop).get(tf.name) or {}
                os.unlink(tf.name)
                if v.get('face_detected') and v.get('bbox'):
                    bx0, by0, bx1, by1 = v['bbox']
                    sx = (x1 - x0) / (v.get('img_w') or 1)
                    sy = H / (v.get('img_h') or 1)
                    fw = (bx1 - bx0) * sx
                    cx = x0 + (bx0 + bx1) / 2 * sx
                    cy = (by0 + by1) / 2 * sy
                    # TIGHT body envelope (2026-07-29 frozen-clip fix: the old 4.2x-wide
                    # to-frame-bottom boxes made the mask ~90% white — no set left to pin)
                    bw = fw * 2.8
                    regions.append(
                        (int(cx - bw / 2), int(max(0, cy - fw * 1.4)), int(cx + bw / 2), int(min(H, cy + fw * 5.5)))
                    )
                    log(f'[vace-mask] region {i}: face-derived body envelope')
                else:
                    # fail-open: whole column becomes generatable (safe, just less locking)
                    regions.append((x0, int(H * 0.08), x1, H))
                    log(f'[vace-mask] region {i}: no face — whole column')
        except Exception as e:
            log(f'[vace-mask] detector unavailable ({e}) — using columns')
            for i in range(n_regions):
                x0 = (W // n_regions) * i
                x1 = W if i == n_regions - 1 else (W // n_regions) * (i + 1)
                regions.append((x0, int(H * 0.08), x1, H))
    for x0, y0, x1, y1 in regions:
        d.rectangle([max(0, x0), max(0, y0), min(W, x1), min(H, y1)], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(10))
    mask.save(out_path)
    import numpy as _np

    cov = float((_np.asarray(mask) > 127).mean() * 100)
    log(f'[vace-mask] → {os.path.basename(out_path)} ({len(regions)} region(s), {cov:.0f}% white)')
    if cov > 60:
        log(f'[vace-mask] WARNING: mask covers {cov:.0f}% of frame — little set left to pin')
    return out_path


# ---------------------------------------------------------------------------
# A3 (2026-07-31) — MOTION-ENVELOPE MASK.
#
# WHY: build_char_mask paints two axis-aligned rectangles and blurs sigma=10. Measured on
# scene20_v8's mask_v8.png that gives white_frac 0.795, and the UPPER 30% OF FRAME is 80.9%
# white — so the planking, the carved detail and the brass lantern (all correct in the
# anchor) sit inside the generate region, get handed neutral grey as their only per-frame
# guidance, and the model invents them. That is the anachronistic-neon-pole defect.
# Two further pathologies confirmed on the same file: a 22.1% soft band (a MID-GREY mask
# value is not "half-strength guidance" — VACE splits inactive=i*(1-m) / reactive=i*m at
# ComfyUI-WanVideoWrapper/nodes.py:1830-1831, so grey hands BOTH branches a half-brightness
# copy: that is the cyan/teal edge glow), and a blur ramp that runs off the frame (top and
# bottom rows literally 255 = the right-edge vertical seam).
#
# The replacement derives the generate region from where the shot ACTUALLY MOVED — per-pixel
# temporal std of the rendered clip — instead of from a guessed rectangle. Pinning a static
# wall under a locked-off camera is VACE's intended use; freezing was never caused by keeping
# real pixels in `inactive`, it was caused by keeping real pixels OVER THE SUBJECTS.
#
# THE SELF-REFERENCE TRAP: measuring the envelope on v8 partly measures v8's own
# hallucination — the flickering neon wall registers as motion and would re-open exactly the
# region being pinned. The wall_top_frac hard-zero runs AFTER the temporal-std step and
# overrides it. It is NOT optional.
# ---------------------------------------------------------------------------


def _mask_stats(arr, border_px=3):
    """Mask health metrics on a uint8 L array.

    soft_band counts pixels STRICTLY between 0 and 255 — the definition the v9 research
    measured v8 at (0.2213), so before/after numbers stay comparable."""
    import numpy as _np

    a = _np.asarray(arr)
    H, W = a.shape[:2]
    b = int(max(1, border_px))
    border = _np.concatenate([a[:b].ravel(), a[-b:].ravel(), a[:, :b].ravel(), a[:, -b:].ravel()])
    return {
        'white_frac': float((a > 127).mean()),
        'soft_band': float(((a > 0) & (a < 255)).mean()),
        'border_max': int(border.max()),
        'upper30_white': float((a[: int(H * 0.30)] > 127).mean()),
        'size': (W, H),
    }


def _disk(radius):
    """uint8 disk structuring element (cv2 morphologyEx / scipy structure)."""
    import numpy as _np

    r = int(max(1, radius))
    y, x = _np.ogrid[-r : r + 1, -r : r + 1]
    return ((x * x + y * y) <= r * r).astype('uint8')


def _binmorph(b, kind, radius):
    """Binary open/close/dilate with a disk. cv2 when importable (instant at r=28),
    scipy.ndimage otherwise. Fail-safe: returns the input unchanged if neither is present."""
    k = _disk(radius)
    try:
        import cv2

        op = {'open': cv2.MORPH_OPEN, 'close': cv2.MORPH_CLOSE, 'dilate': cv2.MORPH_DILATE}[kind]
        return cv2.morphologyEx((b.astype('uint8') * 255), op, k) > 127
    except Exception as _exc:
        _zyg_log.debug('cv2 %s unavailable, trying scipy.ndimage: %s', kind, _exc)
    try:
        from scipy import ndimage as _nd

        fn = {'open': _nd.binary_opening, 'close': _nd.binary_closing, 'dilate': _nd.binary_dilation}[kind]
        return fn(b, structure=k.astype(bool))
    except Exception:
        return b


def _components(b):
    """-> (label image, n) with labels 1..n. cv2 then scipy; (zeros, 0) if neither."""
    try:
        import cv2

        n, lab = cv2.connectedComponents((b.astype('uint8') * 255), connectivity=8)
        return lab, int(n) - 1
    except Exception as _exc:
        _zyg_log.debug('cv2 connected components unavailable, trying scipy.ndimage: %s', _exc)
    try:
        from scipy import ndimage as _nd

        lab, n = _nd.label(b)
        return lab, int(n)
    except Exception:
        import numpy as _np

        return _np.zeros(b.shape, dtype='int32'), 0


def _clip_temporal_std(clip_path, max_frames=None, log=None):
    """Per-pixel temporal std of a clip's luma, STREAMED as sum/sumsq.

    341f at 832x480 costs ~6MB of float64 accumulators instead of the 545MB a frame stack
    would take. Returns (std float32 HxW, n_frames) or (None, 0)."""
    import numpy as _np

    log = log or _log_noop
    s = s2 = None
    n = 0

    def _acc(gray):
        nonlocal s, s2, n
        g = gray.astype(_np.float64)
        if s is None:
            s = _np.zeros(g.shape, dtype=_np.float64)
            s2 = _np.zeros(g.shape, dtype=_np.float64)
        if g.shape != s.shape:
            return
        s += g
        s2 += g * g
        n += 1

    try:
        import cv2

        cap = cv2.VideoCapture(clip_path)
        try:
            while True:
                ok, fr = cap.read()
                if not ok:
                    break
                _acc(cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY))
                if max_frames and n >= int(max_frames):
                    break
        finally:
            cap.release()
    except Exception as e:
        log(f'[motion-mask] cv2 decode unavailable ({e}) — ffmpeg fallback')
    if n < 2:
        # fallback: ffmpeg -> temp PNGs -> PIL (same house pattern as paste_back_keep_regions)
        import glob as _glob
        import subprocess
        import tempfile

        tmp = tempfile.mkdtemp(prefix='motionmask_')
        try:
            r = subprocess.run(
                [
                    exe('ffmpeg'),
                    '-y',
                    '-loglevel',
                    'error',
                    '-i',
                    clip_path,
                    '-vsync',
                    '0',
                    os.path.join(tmp, 'f_%05d.png'),
                ],
                capture_output=True,
                text=True,
            )
            if r.returncode == 0:
                s = s2 = None
                n = 0
                for fp in sorted(_glob.glob(os.path.join(tmp, 'f_*.png'))):
                    _acc(_np.asarray(Image.open(fp).convert('L')))
                    if max_frames and n >= int(max_frames):
                        break
        except Exception as e:
            log(f'[motion-mask] ffmpeg fallback failed ({e})')
        finally:
            import shutil as _sh

            _sh.rmtree(tmp, ignore_errors=True)
    if n < 2 or s is None:
        return None, 0
    var = _np.maximum(s2 / n - (s / n) ** 2, 0.0)
    return _np.sqrt(var).astype(_np.float32), n


def _envelope_from_std(std, thresh, wall_top_frac, dilate_px, head_halo_frac, halo_area_frac=0.10, log=None):
    """std map -> boolean generate-envelope, with the wall hard-zeroed above wall_top_frac
    except small head halos. Split out from the builder so auto-tuning the threshold does
    not re-decode the clip.

    The halos are SHAPE-FOLLOWING, not boxes: a halo is a connected component of the measured
    motion inside the band directly above the shoulder line that (a) touches the line — so it
    belongs to a subject, not to the wall — and (b) is under an area cap. A box centred on a
    below-wall component would be mis-centred whenever an arm widens that component (Cornelis
    raises the pipe), and would then pin the face it was supposed to free. The area cap is
    what keeps a wall-wide hallucination blob out; every halo pixel is still measured motion."""
    import numpy as _np

    log = log or _log_noop
    H, W = std.shape
    b = std > float(thresh)
    b = _binmorph(b, 'open', 2)  # kill per-pixel codec speckle
    b = _binmorph(b, 'close', 7)  # close the holes inside a moving body
    dil = _binmorph(b, 'dilate', int(dilate_px))  # headroom so motion cannot hit the edge
    y_wall = int(round(H * float(wall_top_frac)))
    below = dil.copy()
    below[:y_wall] = False  # THE HARD-ZERO — overrides the temporal-std step
    halo_h = int(round(float(head_halo_frac) * H))
    top = max(0, y_wall - halo_h)
    above = _np.zeros(dil.shape, dtype=bool)
    if y_wall >= 1:
        above[top:y_wall] = dil[top:y_wall]
    lab, ncomp = _components(above)
    halo = _np.zeros(dil.shape, dtype=bool)
    cap = int(float(halo_area_frac) * W * H)
    kept = rejected = 0
    for i in range(1, ncomp + 1 if y_wall >= 1 else 1):
        comp = lab == i
        if not comp[y_wall - 1].any():
            continue  # not attached to a body crossing the shoulder line
        a = int(comp.sum())
        if a > cap:
            rejected += 1  # wall-wide blob — this is the hallucination, not a head
            continue
        halo |= comp
        kept += 1
    if rejected:
        log(f'[motion-mask] {rejected} above-wall blob(s) over the {cap}px halo cap rejected (wall flicker, not heads)')
    if not kept:
        log(
            '[motion-mask] WARNING: no head halo survived — heads may be pinned; '
            'raise head_halo_frac or lower sigma_thresh'
        )
    return (below | halo), y_wall, kept


def _feather_and_crush(env, feather_px, border_px, lo=24, hi=231):
    """Feather the envelope then CRUSH THE TAILS.

    A mid-grey mask value is a luminance split, not half-strength guidance (see the A3
    header) — so the ramp is kept as narrow as a 6px feather allows (sigma = feather/3 ~ 2)
    and everything below `lo` / above `hi` is snapped to 0 / 255. Target soft_band <= 0.06.
    The frame border is pre-zeroed WIDE ENOUGH that the blur cannot reach it (the v8 mask's
    ramp ran off the frame: top/bottom rows were literally 255)."""
    import numpy as _np

    sigma = max(0.5, float(feather_px) / 3.0)
    m = env.astype('uint8') * 255
    guard = int(border_px) + int(math.ceil(3.0 * sigma))
    if guard > 0:
        m[:guard] = 0
        m[-guard:] = 0
        m[:, :guard] = 0
        m[:, -guard:] = 0
    try:
        import cv2

        m = cv2.GaussianBlur(m, (0, 0), sigma)
    except Exception:
        m = _np.asarray(Image.fromarray(m).filter(ImageFilter.GaussianBlur(sigma)))
    m = _np.array(m, dtype='uint8', copy=True)
    m[m < lo] = 0
    m[m > hi] = 255
    b = int(border_px)
    if b > 0:
        m[:b] = 0
        m[-b:] = 0
        m[:, :b] = 0
        m[:, -b:] = 0
    return m


def build_motion_envelope_mask(
    motion_clip,
    out_path,
    wall_top_frac=0.34,
    sigma_thresh=8.0,
    dilate_px=28,
    feather_px=6,
    log_fn=None,
    size=None,
    head_halo_frac=0.24,
    halo_area_frac=0.10,
    border_px=3,
    target_white=(0.33, 0.40),
    auto_tune=True,
    max_frames=None,
):
    """A3 — build the VACE generate-mask from a clip's MEASURED MOTION (see header above).

    motion_clip : the true motion record of this shot (for v9: scene20_v8/vace_static.mp4).
    wall_top_frac : everything above this fraction of frame height is hard-zeroed (pinned)
            except small head halos. MANDATORY — it is what stops v8's hallucinated wall
            from re-opening itself through its own flicker.
    sigma_thresh : per-pixel temporal std above which a pixel counts as "moved".
    dilate_px : envelope headroom, so anything that moved in v8 stays generatable.
    feather_px : 6px feather -> sigma ~2, then tails crushed (<24->0, >231->255).
    head_halo_frac : height of the band above the shoulder line in which subject-attached
            motion blobs stay generatable. 0.24 (115px at 480) is sized so the FACES clear
            the line — the tripwire region a_head measured 0.215 on v8 and must not regress;
            pinning a skull top while generating the jaw tears at the boundary on a head turn.
    halo_area_frac : per-blob area cap in that band. Above it the blob is the hallucinating
            wall, not a head, and is rejected.
    size : (W,H) to author the mask at; defaults to the clip's own size.
    auto_tune : if the first pass lands outside target_white, re-threshold (the std map is
            cached, so this is free) and keep the pass closest to the band. NOTE: on
            scene20_v8 the specified sigma_thresh=8.0 yields white_frac 0.665 — v8's
            generative boil and its own flickering wall register as motion almost everywhere,
            and that mask would itself fail C3 — so the target band, which is what C3 actually
            gates, wins and the threshold is raised until it lands (35.87 on v8, ~p90 of the
            std map). Every step of the sweep is logged; do not silently trust the number.

    Returns out_path, or None on failure (fail-safe — callers fall back to build_char_mask)."""
    log = log_fn or _log_noop
    try:
        import numpy as _np

        if not (motion_clip and os.path.isfile(motion_clip)):
            log(f'[motion-mask] no motion clip at {motion_clip}')
            return None
        std, nfr = _clip_temporal_std(motion_clip, max_frames=max_frames, log=log)
        if std is None:
            log('[motion-mask] could not decode the motion clip')
            return None
        H, W = std.shape
        log(
            f'[motion-mask] {nfr} frames {W}x{H}, temporal std p50={float(_np.median(std)):.2f} '
            f'p99={float(_np.percentile(std, 99)):.2f}'
        )
        lo_t, hi_t = float(target_white[0]), float(target_white[1])
        mid_t = (lo_t + hi_t) / 2.0
        thr = float(sigma_thresh)
        best = None
        tried = []
        for _attempt in range(6 if auto_tune else 1):
            env, y_wall, n_halo = _envelope_from_std(
                std, thr, wall_top_frac, dilate_px, head_halo_frac, halo_area_frac, log=log
            )
            m = _feather_and_crush(env, feather_px, border_px)
            st = _mask_stats(m, border_px=border_px)
            tried.append((thr, st['white_frac']))
            if best is None or abs(st['white_frac'] - mid_t) < abs(best[2]['white_frac'] - mid_t):
                best = (thr, m, st, y_wall, n_halo)
            if lo_t <= st['white_frac'] <= hi_t or not auto_tune:
                break
            # only the threshold is tuned — dilate/wall geometry stay as specified
            thr = thr * (1.35 if st['white_frac'] > hi_t else (1.0 / 1.35))
            if thr < 0.5 or thr > 120.0:
                break
        thr, m, st, y_wall, n_halo = best
        if len(tried) > 1:
            log('[motion-mask] threshold sweep: ' + ', '.join(f'{t:.2f}->{w:.3f}' for t, w in tried))
        if size and tuple(size) != (W, H):
            m = _np.asarray(Image.fromarray(m).resize((int(size[0]), int(size[1])), Image.LANCZOS))
            m = _np.array(m, dtype='uint8', copy=True)
            m[m < 24] = 0  # LANCZOS re-introduces a soft band — re-crush
            m[m > 231] = 255
            b = int(border_px)
            if b > 0:
                m[:b] = 0
                m[-b:] = 0
                m[:, :b] = 0
                m[:, -b:] = 0
            st = _mask_stats(m, border_px=border_px)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)) or '.', exist_ok=True)
        Image.fromarray(m, mode='L').save(out_path)
        log(
            f'[motion-mask] → {os.path.basename(out_path)} sigma_thresh={thr:.2f} '
            f'wall_y={y_wall} head_halos={n_halo} white_frac={st["white_frac"]:.4f} '
            f'soft_band={st["soft_band"]:.4f} border_max={st["border_max"]} '
            f'upper30_white={st["upper30_white"]:.4f}'
        )
        if not (lo_t <= st['white_frac'] <= hi_t):
            log(
                f'[motion-mask] WARNING: white_frac {st["white_frac"]:.4f} outside target '
                f'{lo_t:.2f}-{hi_t:.2f} — inspect before committing GPU time'
            )
        return out_path
    except Exception as e:
        log(f'[motion-mask] FAILED ({e})')
        return None


def _default_max_white():
    """2026-07-31 — the 0.50 cap was an INVENTED target, never a measured requirement, and
    enforcing it FROZE two 30-minute probe runs: squeezing the envelope to 0.336 white left
    Abel's hand 13.8% and his head 31.9% generatable (v8, which moved fine: 26.4% / 84.9%),
    so the mask itself pinned the characters. The global white fraction is the wrong
    statistic — WHERE the white sits is what matters. The v9 silhouette mask measures 0.816
    white yet pins the pole zone above the wall line at 0.0% open (v8: 76.4%). Override with
    ZYG_MASK_MAX_WHITE; soft_band and border stay strict because those were MEASURED faults
    (the teal edge glow and the right-edge seam)."""
    try:
        return float(os.environ.get('ZYG_MASK_MAX_WHITE', '0.86'))
    except ValueError:
        return 0.86


def preflight_mask_gates(
    mask_path, max_white_frac=None, max_soft_band=0.06, border_px=3, expect_size=None, log_fn=None
):
    """C3 (2026-07-31) — refuse to spend 4.5h of GPU on a mask that cannot work.

    v8's mask would have been blocked on all three counts: white_frac 0.795 (> 0.50),
    soft_band 0.221 (> 0.06), border max 255 (must be 0 — a ramp that runs off the frame
    IS the right-edge vertical seam). Also asserts the transport contract: the mask travels
    LoadImage -> ImageToMask(channel='red'), so a paletted PNG quantises the feather away and
    a size mismatch gets nearest-exact upscaled (nodes.py:1763), destroying it either way.

    FAIL-CLOSED by design (C6): an unreadable or unmeasurable mask is a FAIL, not a pass —
    the old geometry gates set ok=True on exception, so a broken gate silently passed.
    Returns (ok, reason)."""
    log = log_fn or _log_noop
    reasons = []
    try:
        import numpy as _np

        im = Image.open(mask_path)
        mode, sz = im.mode, im.size
        if mode == 'P':
            reasons.append('paletted PNG (P) — quantisation destroys the feather; save as 8-bit L or RGB')
        arr = _np.asarray(im.convert('RGB'))
        if not (_np.array_equal(arr[:, :, 0], arr[:, :, 1]) and _np.array_equal(arr[:, :, 1], arr[:, :, 2])):
            reasons.append('channels differ (R!=G!=B) — ImageToMask reads the RED channel only')
        a = _np.asarray(im.convert('L'))
        st = _mask_stats(a, border_px=border_px)
        if expect_size and tuple(expect_size) != tuple(sz):
            reasons.append(
                f'size {sz} != render size {tuple(expect_size)} (nearest-exact upscale would destroy the feather)'
            )
        _cap = _default_max_white() if max_white_frac is None else float(max_white_frac)
        if st['white_frac'] > _cap:
            reasons.append(f'white_frac {st["white_frac"]:.4f} > {_cap:.2f} — too little set left to pin')
        if st['soft_band'] > float(max_soft_band):
            reasons.append(
                f'soft_band {st["soft_band"]:.4f} > {float(max_soft_band):.2f} '
                '— mid-grey is a luminance split, not half-strength guidance'
            )
        if st['border_max'] > 0:
            reasons.append(
                f'border max {st["border_max"]} > 0 — the feather runs off the '
                f'frame ({border_px}px border must be pure black)'
            )
        if reasons:
            return False, '; '.join(reasons)
        log(
            f'[mask-gate] PASS white_frac={st["white_frac"]:.4f} '
            f'soft_band={st["soft_band"]:.4f} border_max=0 mode={mode} size={sz}'
        )
        return True, 'ok'
    except Exception as e:
        return False, f'mask preflight could not read {mask_path} ({e}) — fail-closed'
