# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.fire — the smoke and flame effects of the video-helpers section (lines 1245-1568).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    Image,
    ImageDraw,
    ImageFilter,
    math,
    np,
)


def _smoke_box(base_size: tuple, cfg: dict) -> tuple:
    """Base-pixel rectangle the plume can occupy. Kept tight — the tile is
    rebuilt every frame, so its area is the per-frame cost of the effect."""
    BW, BH = base_size
    ax, ay = float(cfg.get('anchor', (0.5, 0.5))[0]), float(cfg.get('anchor', (0.5, 0.5))[1])
    rise = float(cfg.get('rise_frac', 0.30)) * BH
    drift = float(cfg.get('drift_frac', 0.10)) * BW
    r1 = float(cfg.get('r1_frac', 0.055)) * BW
    pad = r1 * 2.2
    x0 = int(max(0, ax * BW - drift - pad))
    x1 = int(min(BW, ax * BW + drift + pad))
    y0 = int(max(0, ay * BH - rise - pad))
    y1 = int(min(BH, ay * BH + pad * 0.6))
    return (x0, y0, x1, y1)


def _draw_smoke(base_size: tuple, cfg: dict, t_abs: float):
    """One frame of pipe smoke, as a base-space RGBA tile.

    Deliberately NOT pipeline_effects' `_draw_particles`: that layer is a
    full-frame screen-blend with no anchor, which is right for dust hanging in a
    room and wrong for smoke leaving a pipe bowl. Smoke has a source, and the
    source is a point ON THE PLATE — so the plume is drawn in base coordinates
    and cut by the same window as the picture. Tie it to the delivery frame
    instead and it slides off the pipe the moment the camera moves.

    Each puff is a soft disc on its own phase of one shared cycle, so the column
    is continuous rather than pulsing: it leaves small and dense at the bowl,
    expands and thins as it rises, drifts sideways with a slow shear, and dies
    out before the top of the tile. Alpha follows sin(pi·u), which is what stops
    puffs from popping into existence at the bowl and vanishing at the ceiling.
    """
    x0, y0, x1, y1 = _smoke_box(base_size, cfg)
    tw, th = max(1, x1 - x0), max(1, y1 - y0)
    tile = Image.new('RGBA', (tw, th), (0, 0, 0, 0))
    BW, BH = base_size
    ax, ay = cfg.get('anchor', (0.5, 0.5))
    sx, sy = float(ax) * BW - x0, float(ay) * BH - y0
    n = int(cfg.get('puffs', 34))
    rise = float(cfg.get('rise_frac', 0.30)) * BH
    drift = float(cfg.get('drift_frac', 0.10)) * BW
    r0 = float(cfg.get('r0_frac', 0.006)) * BW
    r1 = float(cfg.get('r1_frac', 0.055)) * BW
    period = max(0.5, float(cfg.get('period_s', 6.0)))
    op = float(cfg.get('opacity', 0.34))
    mouth = min(0.45, max(0.0, float(cfg.get('mouth_frac', 0.0))))
    col = tuple(cfg.get('colour', (208, 196, 176)))
    rng = np.random.RandomState(int(cfg.get('seed', 11)))
    # Phases: random by default (the pipe shipped that way), STRATIFIED when
    # asked. Purely random phases leave instants with no puff anywhere near the
    # source — measured on the chimneys, the plume detached from its own pot by
    # up to 12 px at some frames and sat back on it at others, which is a
    # flicker, not a plume. One puff per 1/n slice with jitter inside it keeps
    # the column continuous at the mouth without making it regular.
    if cfg.get('stratify'):
        ph = (np.arange(n) + rng.rand(n)) / float(n)
    else:
        ph = rng.rand(n)
    jitter = rng.uniform(-1.0, 1.0, n)
    swirl = rng.uniform(0.6, 1.8, n)
    scale = rng.uniform(0.72, 1.35, n)
    d = ImageDraw.Draw(tile)
    for i in range(n):
        u = ((t_abs / period) + ph[i]) % 1.0
        # ease the climb: smoke leaves the bowl briskly and slows as it cools
        h = u**0.72
        # Two incommensurate sines, not one. A single sine moves every puff the
        # same way at the same height, so the column SWAYS as a unit — which
        # reads as a hanging curtain of haze rather than as smoke. The second,
        # faster term breaks that up into a curl, and its amplitude grows with
        # height because a plume is laminar at the bowl and turbulent above it.
        px = sx + drift * h * (
            0.30 * jitter[i]
            + 0.55 * math.sin(swirl[i] * (u * 3.1 + ph[i] * 6.28))
            + 0.45 * h * math.sin(swirl[i] * 2.7 * (u * 5.3 + ph[i] * 3.14))
        )
        py = sy - rise * h
        r = (r0 + (r1 - r0) * h) * scale[i]
        # `mouth_frac` starts the alpha profile part-way into the sine, so the
        # plume is already dense where it leaves the source instead of fading
        # in above it. A pipe bowl wants 0 — you do not see smoke inside the
        # bowl — but a CHIMNEY is a mouth, and at 0 the plume measured a 13 px
        # gap between the pot and its own smoke, which reads as a cloud parked
        # over a roof rather than as a chimney alight.
        ua = mouth + (1.0 - mouth) * u
        a = op * math.sin(math.pi * ua) ** 0.8 * scale[i]
        # thicker and more opaque in the first third, where the column is a column
        a *= 1.0 + 0.55 * max(0.0, 1.0 - u * 3.0)
        av = int(max(0, min(255, a * 255)))
        if av <= 1 or r < 0.5:
            continue
        d.ellipse([px - r, py - r, px + r, py + r], fill=col + (av,))
    # Blur is its OWN knob, not a fraction of the puff radius. Tying the two
    # together means the only way to get a plume that climbs a long way is to
    # make it so soft it reads as room haze rather than as smoke leaving a bowl.
    blur = float(cfg.get('blur_frac', 0.0)) * BW
    tile = tile.filter(ImageFilter.GaussianBlur(max(1.5, blur or r1 * 0.34)))
    return (x0, y0), tile


def _flicker_factor(t_abs: float, strength: float, seed: int = 7) -> float:
    """Candle flicker: two incommensurate sines + deterministic per-window jitter."""
    if strength <= 0:
        return 1.0
    j = np.random.RandomState(seed + int(t_abs * 10)).uniform(-0.5, 0.5)
    v = 0.6 * math.sin(2 * math.pi * 6.3 * t_abs) + 0.3 * math.sin(2 * math.pi * 11.7 * t_abs + 1.3) + 0.4 * j
    return 1.0 + strength * v


def _flame_at(cfg: dict, t_abs: float) -> tuple:
    """(intensity, height_scale) of a live flame at t_abs.

    `intensity` is a MULTIPLIER around 1.0, not an amount of added light: fire
    goes down as well as up, and an effect that can only add reads as a lamp
    being nudged rather than as a flame guttering. It is driven by the SAME
    `_flicker_factor` the plate's room brightness uses, at the same seed, so the
    flame and the room it lights never disagree about which way the light just
    went — the discipline the reveal halo is held to for the same reason.

    On top of the fast term sits a slow breath (~0.37 Hz). The fast term alone
    measured as electrical noise on the pull-out frames: a real candle also
    swells and settles over a second or two, and that is the timescale the eye
    reads as *fire* rather than as flicker.

    Height tracks intensity because they are the same physical thing — more
    fuel burning is both brighter and taller. It is applied as a real
    geometric stretch of the painted flame (see `_flame_apply`), not just to
    the light mask, so the flame actually grows and shrinks.
    """
    fl = _flicker_factor(t_abs, float(cfg.get('amount', 0.55)), seed=int(cfg.get('seed', 7)))
    breath = 1.0 + float(cfg.get('breath', 0.18)) * math.sin(2 * math.pi * 0.37 * t_abs + 0.7)
    inten = max(0.05, fl * breath)
    hs = 1.0 + float(cfg.get('height_amount', 0.45)) * (inten - 1.0)
    return inten, max(0.35, hs)


def _flame_bend(cfg: dict, t_abs: float, u):
    """Lateral offset of the flame at height `u` along it, in units of the tip
    displacement. `u` may be a scalar or an array (0 = wick, 1 = tip).

    Three incommensurate waves that TRAVEL UP the flame — the phase term is
    `-k*u`, not a constant — because that is the thing a candle actually does:
    a kink starts at the base and runs out through the tip. Bending the whole
    body by one angle instead (the first cut) reads as a flag on a pole, and no
    amount of speed fixes it, because the shape never changes along its length.

    `u ** 1.4` pins the base: wax and wick do not move, so a flame whose foot
    slides sideways detaches from its own candle. The exponent puts most of the
    travel in the top third, which is where a real flame carries it.

    Above the tip the profile DECAYS to nothing by u ≈ 1.8, and that matters
    more than it looks. The alternative is to let the mask cut it off instead —
    which is what the first cut did, and a mask that removes 8 px of
    displacement over 30 px of picture is a 26% shear laid across exactly the
    strip of wall the plate paints its smoke wisp on. It put a visible kink in
    the wisp on every strong lean. Decaying the displacement itself means the
    mask never has anything left to cut.
    """
    ph = 2.0 * math.pi
    w = (
        0.55 * np.sin(ph * 0.83 * t_abs - 2.1 * u)
        + 0.30 * np.sin(ph * 1.47 * t_abs - 3.4 * u + 1.7)
        + 0.15 * np.sin(ph * 2.60 * t_abs - 5.2 * u + 0.4)
    )
    uc = np.clip(u, 0.0, None)
    prof = np.minimum(uc, 1.0) ** 1.4 * np.exp(-((np.clip(uc - 1.0, 0.0, None) / 0.40) ** 2))
    return w * prof


def _flame_apply(img: 'Image.Image', cfg: dict, sx: float, sy: float, z: float, t_abs: float) -> 'Image.Image':
    """Light the delivered frame with one guttering flame at (sx, sy).

    (sx, sy) is the WICK in delivered pixels — the caller maps the shot's
    base-normalised `anchor` through the same `_zoom_box` the plate was cut
    with, so the flame stays registered to the painted candle for the whole
    camera move and grows with it instead of crawling across it. Sizes are
    authored as fractions of the FRAME at z == 1 and scale by z for the same
    reason.

    Three layers, because none of them can do the job alone:

      * a WARP of the plate itself. The flame the viewer is looking at is
        PAINTED, and paint does not move: modulating its brightness makes it a
        lamp on a dimmer, which is what the first cut of this shipped. So the
        pixels are remapped — the body bends along a wave travelling up it
        (`_flame_bend`) and stretches about the wick with `hs` — and the thing
        that actually moves on screen is the painted fire, in the plate's own
        style. Nothing is drawn over it, so there is no cartoon flame to
        mismatch the illustration.
      * a MULTIPLIER (flame body + the pool of light it throws). Bidirectional,
        so a dip actually darkens the table and the wall. It is also why the
        pool does not turn the dark cabin grey — multiplying near-black by 1.3
        is still near-black, which is exactly what a candle does to a dark wall.
      * a warm SCREEN bloom on the body only, on swells. The painted flame core
        is already ~250/255, so a multiplier alone has no headroom left there
        and the brightest part of the fire would be the one part that never
        moved. The bloom is what gives a swell somewhere to go.

    The light follows the warp: the multiplier's axis is bent by the SAME
    `_flame_bend`, so the glow leans with the flame instead of staying upright
    behind a fire that has leaned out of it.

    Everything is computed on a tile bounded by the halo, not the frame: this
    runs on every one of ~1000 frames, and the lit pool is a sixth of the
    picture. A tile that falls entirely outside the frame — the whole dialogue
    section, where the pull-out has not yet brought the candle on screen — is
    skipped without touching the image at all.
    """
    W, H = img.size
    inten, hs = _flame_at(cfg, t_abs)
    wpx = max(1.0, float(cfg.get('w_frac', 0.0052)) * W * z)
    hpx = max(1.0, float(cfg.get('h_frac', 0.087)) * H * z)  # UNstretched
    halo_r = max(2.0, float(cfg.get('halo_r_frac', 0.115)) * W * z)
    bend_px = float(cfg.get('bend_frac', 0.0052)) * W * z

    a = np.asarray(img, dtype=np.float32)

    # ── 1. warp the painted flame ───────────────────────────────────────────
    # The warp gets its OWN tile, much tighter than the halo's. It has to: the
    # stretch displacement grows with distance from the wick, so a warp tile
    # sized to the light pool would drag wall 150 px above the candle by
    # ~45 px and smear the planks across a sixth of the frame. Bounded here to
    # 1.65 flame-heights, which is the painted flame (1.0) plus the headroom
    # the stretch and the bend actually need.
    up = hpx * float(cfg.get('warp_span', 1.65))
    side = wpx * 2.6 + abs(bend_px) * 1.7
    wx0 = int(max(0, math.floor(sx - side)))
    wx1 = int(min(W, math.ceil(sx + side)))
    wy0 = int(max(0, math.floor(sy - up)))
    wy1 = int(min(H, math.ceil(sy + wpx * 1.5)))
    if wx1 > wx0 and wy1 > wy0 and (bend_px != 0.0 or hs != 1.0):
        import cv2

        wyy, wxx = np.mgrid[wy0:wy1, wx0:wx1]
        wxx = wxx.astype(np.float32)
        wyy = wyy.astype(np.float32)
        # u is height above the wick in UNSTRETCHED flame lengths, so u == 1 is
        # the painted tip whatever the flame is currently doing.
        u = (np.float32(sy) - wyy) / np.float32(hpx)
        # Lateral mask, and it is a PLATEAU, not a bell. A gaussian peaked on
        # the flame axis gives every column a different displacement, so the
        # body is sheared against itself as it leans and the paint smears into
        # a grey streak down its windward edge (measured on the first cut of
        # this — the lean was right, the flame was ruined). A flat top over the
        # painted width means each horizontal slice TRANSLATES rigidly: the
        # flame keeps its own edges and only the glow around it is sheared,
        # where a smooth gradient hides it. The plateau follows the flame's own
        # taper, so the thin tip gets a thin plateau.
        wl = np.float32(wpx) * np.float32(1.15) * np.maximum(
            np.float32(0.30), (1.0 - np.clip(u, 0.0, 1.0) ** np.float32(1.9)) ** np.float32(0.5)
        ) + np.float32(1.0)
        rr = np.abs(wxx - np.float32(sx)) / wl
        ss = np.clip((np.float32(1.9) - rr) / np.float32(0.9), 0.0, 1.0)
        body = ss * ss * (3.0 - 2.0 * ss)  # smoothstep skirt
        # Vertical window. Both displacements are already ~0 well before it
        # closes, so this only guarantees the tile edge is clean — it is not
        # doing the shaping, which is the whole point (see _flame_bend).
        body *= np.clip((np.float32(2.15) - u) / np.float32(0.35), 0.0, 1.0) ** 2
        # Nothing at or below the wick moves: that is wax and brass.
        body *= np.clip(u / np.float32(0.10), 0.0, 1.0)
        body = np.where(u > 0.0, body, np.float32(0.0)).astype(np.float32)
        # dx: the travelling bend.
        dx = np.float32(bend_px) * _flame_bend(cfg, t_abs, u).astype(np.float32)
        # dy: stretch about the wick, SATURATING at the tip. Inside the flame
        # source height is u/hs, so the body scales by hs. Above it the source
        # is u-(hs-1) — a rigid translation by however far the tip moved, which
        # is continuous with the stretch at u == hs and has zero shear. Letting
        # the stretch keep growing instead (dy ∝ distance from the wick) put
        # 15 px of travel on wall two flame-heights up, where nothing should be
        # moving at all. It then decays out over the next half height, because
        # hot air above a flame does drift with it but the bulkhead does not.
        us = np.clip(u, 0.0, None)
        hsf = np.float32(max(hs, 1e-3))
        u_src = np.where(us <= hsf, us / hsf, us - (hsf - 1.0))
        dy = (us - u_src) * np.float32(hpx)
        dy *= np.clip((np.float32(2.0) - us) / np.float32(0.8), 0.0, 1.0) ** 2
        map_x = (wxx - dx * body).astype(np.float32)
        map_y = (wyy - dy * body).astype(np.float32)
        a[wy0:wy1, wx0:wx1] = cv2.remap(a, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)

    # ── 2. light it, on the wider halo tile ─────────────────────────────────
    pad = 3.0
    tx0 = int(max(0, math.floor(sx - halo_r - pad)))
    tx1 = int(min(W, math.ceil(sx + halo_r + pad)))
    ty0 = int(max(0, math.floor(sy - max(halo_r, up) - pad)))
    ty1 = int(min(H, math.ceil(sy + halo_r + pad)))
    if tx1 <= tx0 or ty1 <= ty0:
        return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))

    yy, xx = np.mgrid[ty0:ty1, tx0:tx1]
    xx = xx.astype(np.float32)
    yy = yy.astype(np.float32)
    reg = a[ty0:ty1, tx0:tx1]

    d = np.hypot(xx - np.float32(sx), yy - np.float32(sy)) / np.float32(halo_r)
    halo = np.exp(-np.float32(1.6) * d * d)

    # The body mask for the LIGHT tracks the warped flame: same bend, same
    # stretch, so a leaning flame is lit along its lean.
    hsp = np.float32(hpx * hs)
    us = (np.float32(sy) - yy) / hsp
    uc = np.clip(us, 0.0, 1.0)
    ax = np.float32(sx) + np.float32(bend_px) * _flame_bend(cfg, t_abs, uc).astype(np.float32)
    hw = np.float32(wpx) * np.maximum(np.float32(0.08), (1.0 - uc ** np.float32(1.9)) ** np.float32(0.5))
    r = (xx - ax) / hw
    core = np.exp(-np.float32(1.9) * r * r) * (1.0 - uc) ** np.float32(0.45)
    below = np.clip(-us / np.float32(0.12), 0.0, 1.0)
    core *= np.exp(-np.float32(2.5) * below * below)
    core = np.where((us > -0.12) & (us < 1.02), core, np.float32(0.0)).astype(np.float32)

    m = core * np.float32(cfg.get('core', 1.0)) + halo * np.float32(cfg.get('halo', 0.55))
    mult = np.maximum(np.float32(0.0), 1.0 + (np.float32(inten) - 1.0) * m)
    reg = reg * mult[..., None]

    swell = max(0.0, inten - 1.0) * float(cfg.get('bloom', 0.55))
    if swell > 0:
        rgb = np.asarray(cfg.get('bloom_rgb', (255, 196, 96)), dtype=np.float32)
        ov = core[..., None] * (rgb[None, None, :] * np.float32(swell))
        reg = 255.0 - (255.0 - reg) * (255.0 - np.minimum(ov, 255.0)) / 255.0

    a[ty0:ty1, tx0:tx1] = reg
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
