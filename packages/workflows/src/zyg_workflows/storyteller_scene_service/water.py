# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.water — the water, reveal-light and title-card effects of the video-helpers section (lines 2749-3056).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    Image,
    ImageDraw,
    ImageFilter,
    ImageFont,
    _FONT_PATH,
    _FPS,
    math,
    np,
)

_WATER_MASKS: dict = {}


def _water_mask(size: tuple, cfg: dict) -> 'Image.Image':
    """Soft plate-resolution mask of the water, cached per (size, polygon).

    Authored in NORMALISED plate coordinates so the same polygon fits the 1344
    delivery and the 2688 hires plate the frames are actually cut from, and so
    it survives an upscale of the still.

    The edge is feathered rather than hard for the reason `_flame_bend` decays
    its own profile: a displacement that is cut off at a boundary is a shear
    laid across that boundary, and the boundaries here are the quay edge and
    the ship's waterline — the two lines in the picture a viewer is most likely
    to be looking at. Feathering means the warp is already ~0 by the time the
    mask ends.
    """
    poly = tuple((float(x), float(y)) for x, y in cfg['poly'])
    feather = float(cfg.get('feather', 0.010))
    key = (tuple(size), poly, feather)
    m = _WATER_MASKS.get(key)
    if m is None:
        W, H = size
        m = Image.new('L', (W, H), 0)
        ImageDraw.Draw(m).polygon([(x * W, y * H) for x, y in poly], fill=255)
        r = max(1.0, feather * H)
        m = m.filter(ImageFilter.GaussianBlur(r))
        # A gaussian never reaches zero, and its tail is what puts a fraction
        # of a pixel of displacement on the quay edge and the ship's waterline
        # — small, but it is exactly the thing this must not do. Rebasing the
        # blur so everything under `lo` is HARD zero keeps the soft ramp and
        # gives the mask a real outer boundary, a few pixels inside the drawn
        # polygon, that a leak check can be written against.
        lo = 0.10
        a = np.asarray(m, dtype=np.float32) / 255.0
        a = np.clip((a - lo) / (1.0 - lo), 0.0, 1.0)
        m = Image.fromarray((a * a * (3.0 - 2.0 * a) * 255.0 + 0.5).astype(np.uint8))
        _WATER_MASKS[key] = m
    return m


_WATER_TRAINS = (
    # w      lam    f      deg    psi     — three incommensurate swells
    (0.52, 1.35, 0.29, 0.0, 0.00),
    (0.30, 0.66, 0.51, 17.0, 1.93),
    (0.18, 0.33, 0.83, -26.0, 0.61),
)


def _water_field(cfg: dict, D, u, t: float, kdD, kdu):
    """The water surface at depth `D`, lateral world offset `u`, time `t`.

    Returns (eta, sD, su) — elevation, the ALONG-VIEW slope and the LATERAL
    slope. The slopes are what the light responds to and the elevation is what
    the warp responds to, so all three come out of one evaluation. Arrays throughout; `D` and `u` are the perspective
    un-projection of the delivered pixel grid, which is what makes this read as
    water rather than as a corrugated sheet: a wave of fixed WORLD wavelength
    travelling at fixed WORLD speed projects to crests that are widely spaced
    and slow at the bottom of frame and tight and fast near the far bank, all
    of it falling out of the 1/(v − horizon) depth term for free.

    `kdD`/`kdu` are d(D)/d(pixel) and d(u)/d(pixel) — how fast the two world
    coordinates run under the delivered grid. They are not used to displace
    anything; they are used to KILL each train wherever it has compressed below
    `min_px` pixels per cycle. Without that the far water aliases into a
    crawling moiré, because the projection genuinely does put a hundred crests
    into the last twenty pixels above the horizon. Damping per TRAIN rather
    than globally means the long swell keeps running out to the far bank after
    the short chop has been switched off, which is also what a real canal does.
    """
    ph = 2.0 * math.pi
    min_px = float(cfg.get('min_px', 9.0))
    k_max = ph / max(2.0, min_px)
    eta = np.zeros(D.shape, dtype=np.float32)
    sD = np.zeros(D.shape, dtype=np.float32)
    su = np.zeros(D.shape, dtype=np.float32)
    trains = cfg.get('trains') or _WATER_TRAINS
    lam0 = float(trains[0][1])
    for w, lam, f, deg, psi in trains:
        w, lam, f = float(w), float(lam), float(f)
        c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
        k = ph / lam
        arg = k * (D * np.float32(c) + u * np.float32(s)) - np.float32(ph * f * t) + np.float32(psi)
        # screen-space wavenumber of THIS train, along both delivered axes
        kx = np.abs(k * (kdD[0] * c + kdu[0] * s))
        ky = np.abs(k * (kdD[1] * c + kdu[1] * s))
        kk = np.hypot(kx, ky) / np.float32(k_max)
        damp = (1.0 / (1.0 + kk * kk)).astype(np.float32)
        cs = np.cos(arg).astype(np.float32) * damp
        eta += np.float32(w) * np.sin(arg).astype(np.float32) * damp
        # Slopes, normalised by the longest train's wavenumber so both come out
        # O(1) whatever the wavelengths are: a shorter train of the same height
        # is a STEEPER train, and it is the steepness the light responds to.
        sD += np.float32(w * c * lam0 / lam) * cs
        su += np.float32(w * s * lam0 / lam) * cs
    return eta, sD, su


def _water_apply(img: 'Image.Image', cfg: dict, box: tuple, base_size: tuple, z: float, t_abs: float) -> 'Image.Image':
    """Make the painted water in a delivered frame behave like water.

    Same principle as `_flame_apply`, for the same reason: the water on screen
    is PAINTED, and a brightness cycle over paint is a lamp on a dimmer. What
    moves here is the plate — the reflections rise, fall, stretch and slide
    because the pixels carrying them are remapped by a travelling surface — so
    the motion arrives in the illustration's own style with nothing drawn over
    it.

    Two layers:

      * a WARP. Vertical dominates, because that is what a rippled surface does
        to a reflection: tilt the surface by θ and the reflected ray swings by
        2θ, which on a near-mirror canal is overwhelmingly an up-down waver of
        the reflected masts and house-fronts. A smaller lateral term comes off
        the same surface's lateral slope, so the two never disagree about which
        way the water just went.
      * a GLINT. The sun path is the one part of this plate a warp cannot sell
        on its own: it is already near-white, so displacing it moves nothing a
        viewer can see. The glitter is the specular condition — a narrow band
        around zero surface slope, which for a low dawn sun near the view axis
        is where the mirror points at it — and it is GATED BY THE PLATE'S OWN
        LUMINANCE, so it can only appear where the painting already put light
        on the water. It cannot light up the shadowed water under the quay, and
        it needs no mask of the sun path: the painting is that mask.

    Registered to the plate through `box` (the same `_zoom_box` the picture is
    cut with), so the waves ride the camera move instead of crawling across it,
    and sized in fractions of the frame at z == 1 so they grow with it.
    """
    import cv2

    W, H = img.size
    BW, BH = base_size
    x0, y0, x1, y1 = box

    mask_full = _water_mask(base_size, cfg)
    mk = mask_full.crop(box)
    if mk.size != (W, H):
        mk = mk.resize((W, H), Image.BILINEAR)
    mask = np.asarray(mk, dtype=np.float32) / 255.0
    rows = np.where(mask.max(axis=1) > 1e-3)[0]
    cols = np.where(mask.max(axis=0) > 1e-3)[0]
    if not len(rows) or not len(cols):
        return img  # water is off-frame
    ry0, ry1 = int(rows[0]), int(rows[-1]) + 1
    rx0, rx1 = int(cols[0]), int(cols[-1]) + 1

    a = np.asarray(img, dtype=np.float32)
    mask = mask[ry0:ry1, rx0:rx1]

    # ── delivered pixel grid → normalised plate coords → world (D, u) ───────
    yy, xx = np.mgrid[ry0:ry1, rx0:rx1]
    xx = xx.astype(np.float32)
    yy = yy.astype(np.float32)
    dvdy = np.float32((y1 - y0) / BH / H)
    dudx = np.float32((x1 - x0) / BW / W)
    v = np.float32(y0 / BH) + (yy + np.float32(0.5)) * dvdy
    h = np.float32(x0 / BW) + (xx + np.float32(0.5)) * dudx

    v_h = np.float32(cfg.get('horizon', 0.62))
    ar = np.float32(BW / max(1, BH))
    # Depth of a flat plane under a pinhole: 1/(v − horizon). Floored at the
    # horizon so the term stays finite; everything that near is damped to
    # nothing by min_px long before the floor is reached.
    dv = np.maximum(v - v_h, np.float32(0.004))
    D = 1.0 / dv
    u = (h - np.float32(cfg.get('vp_x', 0.5))) * D * ar
    # how fast D and u run under the delivered grid, for the anti-alias damp
    dDdy = -dvdy / (dv * dv)
    kdD = (np.zeros_like(D), dDdy)
    kdu = ((D * dudx * ar).astype(np.float32), ((h - np.float32(cfg.get('vp_x', 0.5))) * ar * dDdy).astype(np.float32))

    eta, sD, su = _water_field(cfg, D, u, t_abs, kdD, kdu)

    # Amplitude in delivered pixels: zero at the far bank, full at the bottom
    # of the plate, growing with the zoom exactly as the picture does.
    q = np.clip((v - v_h) / np.float32(max(1e-3, 1.0 - float(cfg.get('horizon', 0.62)))), 0.0, 1.0)
    amp = np.float32(float(cfg.get('amp_frac', 0.0052)) * H * z) * q ** np.float32(cfg.get('profile', 1.5))
    dy = amp * eta * mask
    dx = amp * np.float32(cfg.get('lateral', 0.35)) * su * mask

    # ── 1. warp ─────────────────────────────────────────────────────────────
    map_x = (xx - dx).astype(np.float32)
    map_y = (yy - dy).astype(np.float32)
    # INTER_CUBIC, not INTER_LINEAR. The painted ripple striations in the
    # mid-distance are a one-to-two pixel texture, and bilinear resampling of a
    # sub-pixel shift is a box blur over exactly that scale — measured on the
    # first cut of this, the middle of the canal came back visibly softer than
    # the plate, i.e. the effect was trading detail for motion. Cubic keeps it.
    a[ry0:ry1, rx0:rx1] = cv2.remap(a, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    # ── 2. shade: the photometric half, which the first cut did not have ────
    # `_flame_apply` moves the painted fire AND multiplies the light around it,
    # and the multiplier is bidirectional so a dip genuinely darkens. The water
    # shipped with only the geometric half, and that is most of why it read as
    # nothing: a 5-px displacement of a smooth low-contrast surface, under a
    # camera that was displacing the whole frame by more, gives the eye no
    # signal at all. This is the same construction as the flame's, on the same
    # reasoning, and it is also just true — a facet tilted toward the sky
    # reflects the sky and one tilted the other way reflects the dark quay, so
    # a rippled surface modulates its own luminance with SLOPE.
    sh = cfg.get('shade')
    if sh:
        amt = np.float32(sh.get('amount', 0.18))
        reg = a[ry0:ry1, rx0:rx1]
        mult = np.maximum(np.float32(0.0), 1.0 + amt * sD * mask * q)
        a[ry0:ry1, rx0:rx1] = reg * mult[..., None]

    # ── 3. glint ────────────────────────────────────────────────────────────
    g = cfg.get('glint')
    if g:
        reg = a[ry0:ry1, rx0:rx1]
        lum = (reg[..., 0] * 0.30 + reg[..., 1] * 0.59 + reg[..., 2] * 0.11) / 255.0
        gate = np.clip(
            (lum - np.float32(g.get('lum0', 0.58))) / np.float32(g.get('lum_w', 0.26)), 0.0, 1.0
        ) ** np.float32(1.6)
        # The specular band is on the SLOPE, not on the height: the mirror
        # condition is about which way the facet points. The first cut banded
        # on `eta`, which put the glitter on the crest LINES instead of on the
        # faces between them.
        sn = sD / np.float32(g.get('width', 0.34))
        spec = np.exp(-sn * sn).astype(np.float32)
        # Far water gets no glitter it could not resolve — the same q profile
        # the warp uses, so glints appear where the waves are actually visible.
        gl = (spec * gate * mask * q ** np.float32(0.7) * np.float32(g.get('gain', 0.55))).astype(np.float32)
        rgb = np.asarray(g.get('rgb', (255, 214, 150)), dtype=np.float32)
        ov = np.minimum(gl[..., None] * rgb[None, None, :], 255.0)
        a[ry0:ry1, rx0:rx1] = 255.0 - (255.0 - reg) * (255.0 - ov) / 255.0

    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


_REVEAL_GRIDS: dict = {}


def _reveal_light(W: int, H: int, src_xy: tuple, R: float) -> np.ndarray:
    """One candle's light on the delivery frame: an (H, W) float32 multiplier
    that is 1.0 within R of the flame and falls off as (R/d)² beyond it.

    Inverse-square from a point ON THE PLATE, with R the radius out to which
    the room is fully lit. Growing R is what "the candle slowly illuminates the
    entire picture" means: the table lights first, then the man, then the far
    bulkhead, each pixel rising over the last stretch of its wait rather than
    switching on — at R = d/2 it is at a quarter, at R = d it is full. A plain
    disc with a feathered edge was rejected on the same frames: it reads as an
    iris wipe, not as light spreading from a source. Distances are in units of
    W so the numbers mean the same thing at any delivery size.
    """
    key = (int(W), int(H))
    grid = _REVEAL_GRIDS.get(key)
    if grid is None:
        yy, xx = np.mgrid[0 : int(H), 0 : int(W)]
        grid = (xx.astype(np.float32), yy.astype(np.float32))
        _REVEAL_GRIDS[key] = grid
    xx, yy = grid
    d = np.hypot(xx - np.float32(src_xy[0]), yy - np.float32(src_xy[1])) / np.float32(W)
    d = np.maximum(d, np.float32(1e-4))
    return np.minimum(np.float32(1.0), (np.float32(max(1e-4, R)) / d) ** 2)


def _reveal_at(cfg: dict, t_abs: float, d_max: float) -> tuple | None:
    """(R, gain) of the candle light at t_abs, or None once the reveal is over.

    Three phases, all in timeline seconds:
      0            → flame_in_s   the flame itself arrives out of black (gain)
      flame_in_s   → delay_s      only the flame and its halo (R = flame_r_frac)
      delay_s      → +dur_s       R grows to d_max — the far corner — so the
                                  last frame of the reveal IS the picture

    R grows as u**ease (default 2.0). A smoothstep was tried first and measured
    on the frames: because every pixel lights over the LAST stretch of its wait
    ((R/d)² goes 0.25 → 1 as R goes d/2 → d) a curve that moves fast through the
    middle had the man fully lit 1.5 s into a 5 s spread, leaving 3.5 s that
    only finished the far corner. u² spends the time where the eye is — the
    near field first, slowly, and the bulkhead last.
    """
    delay = float(cfg.get('delay_s', 3.0))
    dur = max(0.05, float(cfg.get('dur_s', 5.0)))
    if t_abs >= delay + dur:
        return None
    r0 = float(cfg.get('flame_r_frac', 0.03))
    flame_in = float(cfg.get('flame_in_s', 1.0))
    gain = 1.0 if flame_in <= 0 else max(0.0, min(1.0, t_abs / flame_in))
    if t_abs < delay:
        return r0, gain
    # Sampled at the END of the frame's interval, not its start: the frame
    # shown at t covers [t, t + 1/fps), so the last frame inside the window
    # then evaluates at u = 1.0 and is exactly the ungated picture — at the
    # start it would sit at u ≈ 0.99 and the far corner at 0.98 for one frame.
    u = max(0.0, min(1.0, (t_abs + 1.0 / _FPS - delay) / dur))
    ease = max(0.1, float(cfg.get('ease', 2.0)))
    return r0 + (max(d_max, r0) - r0) * (u**ease), gain


def _title_card(W: int, H: int, text: str, alpha: float) -> Image.Image:
    img = Image.new('RGB', (W, H), (0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(_FONT_PATH, size=int(H * 0.14))
    except OSError:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    c = int(228 * max(0.0, min(1.0, alpha)))
    d.text(((W - tw) / 2 - bbox[0], (H - th) / 2 - bbox[1]), text, fill=(c, c, c), font=font)
    return img
