# SPDX-FileCopyrightText: 2026 Zygomatic
#
# SPDX-License-Identifier: AGPL-3.0-or-later

"""storyteller_scene_service.bird_flight — the bird pose, camera and 3D flight path of the video-helpers section (lines 1818-2253).

Moved verbatim out of the old single-file storyteller_scene_service.py.
"""

from __future__ import annotations

from zyg_workflows.storyteller_scene_service.constants import (
    math,
)
from zyg_workflows.storyteller_scene_service.frame import (
    _smoothstep,
)
from zyg_workflows.storyteller_scene_service.bird_wing import (
    _bez,
    _bird_tables,
    _bird_wing,
    _catmull,
    _lerp_table,
    _table_lookup,
)


def _bird_pose(cfg: dict, t_rel: float) -> dict | None:
    """Everything about the bird at `t_rel` seconds after it enters. None once
    it has gone, which is how a bird that has left the scene costs nothing.

    The shape of the motion is BOUNDING FLIGHT, and it is the single thing that
    makes a small bird read as a small bird. Finches and canaries do not fly
    like gulls: they beat in a burst of five or six, then close the wings
    completely and fall ballistically, so the path is a chain of shallow
    scallops and the silhouette collapses to a dart once per cycle. Drawn with
    a steady flap on a smooth path — the first cut — a canary reads as a gull
    at the wrong scale, and no amount of flap speed fixes it, because what is
    wrong is that the wings never stop.
    """
    dur = float(cfg.get('dur_s', 5.0))
    if t_rel < 0.0 or t_rel > dur:
        return None
    if cfg.get('path3d'):
        px, py, sc, s_arc, tx, ty, bank, yaw = _bird_fly3d(cfg, t_rel)
    else:
        us, arc, tt = _bird_tables(cfg)
        s_arc = _table_lookup(tt, arc, t_rel / dur)
        u = _table_lookup(arc, us, s_arc)
        (px, py), (tx, ty) = _catmull(cfg['path'], u)
        sc = _lerp_table(cfg.get('scale') or [(0.0, 1.0), (1.0, 1.0)], s_arc)
        bank = None
        yaw = None

    flap, tuck, climb = _bird_wing(cfg, t_rel)

    # Vertical scallop: height gained through the beat burst, lost through the
    # closed-wing glide. Zero-mean, so it modulates the authored path rather
    # than dragging the bird off it.
    bob = -(climb - 0.5) * float(cfg.get('bound_frac', 0.9))
    # ...and the body pitches with it, nose up out of a glide, nose down into
    # one. Without this the bird slides along the path like a decal.
    pitch = float(cfg.get('pitch_gain', 0.30)) * -(climb - 0.5) * 2.0

    return {
        'pos': (px, py),
        'bob': bob,
        'head': math.atan2(ty, tx),
        'pitch': pitch,
        'flap': flap,
        'tuck': tuck,
        'scale': sc,
        's': s_arc,
        'bank': bank,
        'yaw': yaw,
    }


def _bird_cam(cfg: dict) -> tuple:
    """(f_px, cx_px, cy_px, W, H) — the plate's camera, in plate pixels.

    Not a new fit. The harbour's water effect already carries a measured
    pinhole for this plate — `fx.water` has horizon 0.648 and vp_x 0.470, and
    `_water_field` reads a ground point's depth off it as 1/(v − horizon) —
    so the bird is flown through the SAME camera the canal is rippled under
    rather than through one of its own. Focal is the one free parameter
    (a generated plate has no lens to look up); the default is the same
    0.85·width `prop_camera` uses for the book.
    """
    cam = cfg.get('cam') or {}
    W = float(cam.get('plate_w', 2688.0))
    H = float(cam.get('plate_h', 1536.0))
    return (
        float(cam.get('f_px', 0.85 * W)),
        float(cam.get('vp_x', 0.470)) * W,
        float(cam.get('horizon', 0.648)) * H,
        W,
        H,
    )


def _bird_world(cfg: dict, s: float) -> tuple:
    """World point (metres) at spline parameter s along the 3D flight."""
    p = _catmull3(cfg['path3d'], s)
    return p


def _catmull3(pts, u: float) -> tuple:
    """Catmull-Rom through 3-vectors — the 2D one only carries x and y."""
    n = len(pts)
    if n < 2:
        return tuple(pts[0])
    seg = min(int(u * (n - 1)), n - 2)
    f = u * (n - 1) - seg
    p0 = pts[max(0, seg - 1)]
    p1, p2 = pts[seg], pts[seg + 1]
    p3 = pts[min(n - 1, seg + 2)]
    f2, f3 = f * f, f * f * f
    return tuple(
        0.5 * ((2 * b) + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f2 + (-a + 3 * b - 3 * c + d) * f3)
        for a, b, c, d in zip(p0, p1, p2, p3)
    )


_BIRD_ARC3: dict = {}
_BIRD_BANK3: dict = {}


def _bird_bank_table(cfg: dict) -> list:
    """Bank angle in degrees, sampled at 129 points of equal arc along the path.

    A COORDINATED TURN, tan(bank) = v²·κ/g, computed in WORLD space and then
    smoothed — not read off the image path, and not read off two samples either
    side of the current point. Both of those were tried: differencing the
    projected path picks up the projection's own nonlinearity near the lens and
    the spline's curvature jitter everywhere else, and the raw signal came back
    spanning -2292° to +12397° with the endpoints spiking where the ±ds
    neighbours collapse. A bank angle is a slowly varying thing; the table is
    built once, over a wide baseline, and blurred.

    κ is the magnitude of the FULL 3D bend of the flight — |dT/ds| of the unit
    tangent — not just its horizontal-plane component. The first cut measured
    heading with atan2(dx, dz) alone, which answers "is the bird turning
    left or right" but is blind to a path that bends mostly in the vertical
    plane, which this one does: it recedes 6.8x while dropping 4m, and that
    drop is most of the curve. A path bending only vertically (a straight
    dive) does not need a bank in a real coordinated turn — that is pitch, not
    roll — but a flight that both recedes AND swings sideways, the way this
    one does, is bending in a plane that is not level, and a bank driven by
    the horizontal projection alone was seeing a small fraction of that bend.
    The heading used to SIGN the roll — left turn banks left, right turn
    banks right — is the PROJECTED SCREEN heading, not the world-plane one
    (`atan2(dX, dZ)`), because a bend that lives mostly out of the horizontal
    plane still has to roll one way or the other, and the only version of
    "one way or the other" a viewer can check is the one visible on screen.
    The two used to disagree in this function: v26's re-authored approach/
    swing-away curve scored bank-vs-apparent-turn correlation -0.38 (wrong
    SIGN, not just weak) using the old world-plane `th`, and +0.55 once `th`
    was rebuilt from the same projected positions `_bird_fly3d` actually
    draws through — measured directly, not assumed, the same way v22 found
    that a curvature-only signal (no sign check at all) had scored a
    plausible-looking correlation while banking through a stretch where the
    apparent turn was near zero. A world-space signal and a screen-space one
    can each be internally consistent and still point opposite ways for a
    path whose horizontal (X,Z) trend and its on-screen projection trend
    diverge — which any path with real vertical motion does to some degree,
    this one included, over the mid-flight bend around the moored ship.
    """
    key = (
        tuple(tuple(p) for p in cfg['path3d']),
        float(cfg.get('bank_gain', 1.0)),
        float(cfg.get('bank_max_deg', 26.0)),
        cfg.get('speed_mps'),
        float(cfg.get('dur_s', 5.0)),
    )
    got = _BIRD_BANK3.get(key)
    if got is not None:
        return got
    us, arc, total = _bird_arc3(cfg)
    n = 129
    ds_m = total / (n - 1.0)
    P = [_catmull3(cfg['path3d'], _table_lookup(arc, us, k / (n - 1.0))) for k in range(n)]
    # heading of the PROJECTED SCREEN position — kept only to sign the roll,
    # via the same pinhole `_bird_fly3d` projects through, so the sign can
    # never disagree with the direction the bird actually appears to turn.
    f_px, cx_px, cy_px, cam_w, cam_h = _bird_cam(cfg)
    z_floor = float(cfg.get('z_min', 0.6))

    def _scr(pt):
        X, Y, Z = pt
        Z = max(z_floor, Z)
        return ((cx_px + f_px * X / Z) / cam_w, (cy_px + f_px * Y / Z) / cam_h)

    Pscr = [_scr(p) for p in P]
    th = []
    for k in range(n):
        a, b = Pscr[max(0, k - 1)], Pscr[min(n - 1, k + 1)]
        # same fix as `_bird_fly3d`'s `head`: scale the fractional (x/W, y/H)
        # delta back to real pixel units before the angle is taken, so this
        # heading is the actual on-screen direction, not one stretched by the
        # plate's 1.75:1 aspect ratio.
        th.append(math.atan2((b[1] - a[1]) * cam_h, (b[0] - a[0]) * cam_w))
    for k in range(1, n):  # unwrap
        while th[k] - th[k - 1] > math.pi:
            th[k] -= 2 * math.pi
        while th[k] - th[k - 1] < -math.pi:
            th[k] += 2 * math.pi
    # unit tangent of the FULL 3D path, so the curvature below sees a path
    # that bends in the vertical plane as well as the horizontal one
    T = []
    for k in range(n):
        a, b = P[max(0, k - 1)], P[min(n - 1, k + 1)]
        d = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        m = math.sqrt(d[0] * d[0] + d[1] * d[1] + d[2] * d[2]) or 1.0
        T.append((d[0] / m, d[1] / m, d[2] / m))
    v = float(cfg.get('speed_mps') or (total / max(1e-6, float(cfg.get('dur_s', 5.0)))))
    # The spline's control points bunch up at the entry — that is where a
    # hand-authored path is hardest to space evenly — and tan(bank)=v²κ/g
    # answers with a curvature no real bird would fly: uncapped, gain=2.5
    # sent this signal to +82°, and gain=6.0 sent it to +197°, growing
    # exactly as fast as the gain meant to make the CRUISE bank visible. So
    # the modeled angle is capped at `bank_raw_cap_deg` — a plausible ceiling
    # for how tight an actual turn gets — BEFORE the cinematic gain, not
    # after: capping after just clips the top off a signal that still spans
    # the same absurd range underneath, which is what was pinning the
    # correlation-with-the-visible-turn check to a flat plateau at the entry
    # instead of letting it track the turn there like everywhere else.
    raw_cap = float(cfg.get('bank_raw_cap_deg', 1e9))
    # The spline's control points bunch up at the ENTRY worse than anywhere
    # else on a hand-authored path (measured on v24's: a ~70 deg direction
    # change over about 1m of arc, between points a real bird could not turn
    # that tight in) — that is a spline artifact, not a turn, and it survives
    # `raw_cap` because raising the cap to let a genuine hard swing-away
    # through (v23->v24) raises this ceiling too. Measured directly against
    # the delivered v24 file: real on-screen curvature during the first
    # ~0.6s is modest and DECREASING, while the modeled bank sat pinned flat
    # at the clamp the whole time — bank decoupled from the turn it claims,
    # the same failure class the v23->v24 fix closed for the exit, still
    # open at the entry. `bank_entry_settle_frac` (0.0 = off, matches every
    # cfg before this one bit-for-bit) tapers the raw curvature signal up
    # from zero over the first fraction of arc-length, so the settle-in
    # itself has no bank rather than an artificial hard one.
    settle = float(cfg.get('bank_entry_settle_frac', 0.0))
    raw = []
    for k in range(n):
        a, b = T[max(0, k - 2)], T[min(n - 1, k + 2)]
        d_theta = math.dist(a, b)  # |Δunit tangent|: curvature, any plane
        kappa = d_theta / (4.0 * ds_m)  # rad per metre of path
        sign = 1.0 if th[min(n - 1, k + 2)] >= th[max(0, k - 2)] else -1.0
        deg = sign * math.degrees(math.atan(v * v * kappa / 9.81))
        deg = max(-raw_cap, min(raw_cap, deg))
        if settle > 1e-9:
            deg *= _smoothstep(min(1.0, (k / (n - 1.0)) / settle))
        raw.append(deg)
    # blur, because a bird rolls into a turn over a wingbeat or two
    w = 21
    ker = [math.exp(-0.5 * ((i - w // 2) / 5.2) ** 2) for i in range(w)]
    tot = sum(ker)
    out = []
    lim = float(cfg.get('bank_max_deg', 26.0))
    g = float(cfg.get('bank_gain', 1.0))
    for k in range(n):
        s = sum(raw[min(n - 1, max(0, k + i - w // 2))] * ker[i] for i in range(w)) / tot
        out.append(max(-lim, min(lim, s * g)))
    _BIRD_BANK3[key] = out
    return out


_BIRD_YAW3: dict = {}


def _bird_yaw_table(cfg: dict) -> list:
    """Heading relative to the camera's own boresight (world +Z), in degrees,
    sampled at 129 points of equal arc, smoothed the same way
    `_bird_bank_table` smooths bank.

    This is `_bird_bank_table`'s own `th` (horizontal heading, computed there
    only to SIGN the roll) exposed as a signal in its own right: 0 deg is
    flying straight along the lens axis — dead away from, or dead toward,
    the camera, which is the one orientation a REAR-view sprite draws
    correctly — and +-90 deg is broadside to it, which a rear view cannot
    draw at all (see `_draw_bird_sprite`'s docstring: roll of a rear view
    reads as roll, never as yaw). Measured on this shot's own path: ~5-9 deg
    through the cruise (genuinely near-boresight, rear view is right there)
    but ~35-59 deg through the turn and ~58-80 deg at the entry and the
    swing-away exit — most of the flight's runtime, the bird is actually
    closer to side-on to the camera than dead-away from it. Exposed so the
    renderer can cross-fade toward a SIDE sprite set there instead of only
    ever rolling the rear one.
    """
    key = tuple(tuple(p) for p in cfg['path3d'])
    got = _BIRD_YAW3.get(key)
    if got is not None:
        return got
    us, arc, total = _bird_arc3(cfg)
    n = 129
    P = [_catmull3(cfg['path3d'], _table_lookup(arc, us, k / (n - 1.0))) for k in range(n)]
    th = []
    for k in range(n):
        a, b = P[max(0, k - 1)], P[min(n - 1, k + 1)]
        th.append(math.degrees(math.atan2(b[0] - a[0], b[2] - a[2])))
    for k in range(1, n):
        while th[k] - th[k - 1] > 180.0:
            th[k] -= 360.0
        while th[k] - th[k - 1] < -180.0:
            th[k] += 360.0
    w = 21
    ker = [math.exp(-0.5 * ((i - w // 2) / 5.2) ** 2) for i in range(w)]
    tot = sum(ker)
    out = [sum(th[min(n - 1, max(0, k + i - w // 2))] * ker[i] for i in range(w)) / tot for k in range(n)]
    _BIRD_YAW3[key] = out
    return out


def _bird_arc3(cfg: dict) -> tuple:
    """Arc-length table for the 3D path, so `speed_mps` means metres per second
    along the flight and not spline-parameter per second."""
    key = (tuple(tuple(p) for p in cfg['path3d']), int(cfg.get('arc_n', 192)))
    tab = _BIRD_ARC3.get(key)
    if tab is not None:
        return tab
    n = int(cfg.get('arc_n', 192))
    us = [k / (n - 1.0) for k in range(n)]
    ps = [_catmull3(cfg['path3d'], u) for u in us]
    cum = [0.0]
    for a, b in zip(ps, ps[1:]):
        cum.append(cum[-1] + math.dist(a, b))
    total = cum[-1] or 1.0
    tab = (us, [c / total for c in cum], total)
    _BIRD_ARC3[key] = tab
    return tab


def _bird_fly3d(cfg: dict, t_rel: float) -> tuple:
    """(x_frac, y_frac, scale, s_arc, tx, ty, bank_deg, yaw_deg) from the 3D flight.

    THIS IS THE CHANGE THAT MATTERS. The 2D flight was two hand-drawn curves —
    a path in image space and a size table indexed off it — with nothing
    connecting them, so the perspective was a thing I tuned by eye and every
    edit to one needed a matching edit to the other. Run the plate's own camera
    over a path in METRES and there is one curve: image position, apparent
    size, image speed and bank all fall out of it, and they cannot disagree
    with each other because they are the same number projected different ways.

    Measured against the hand-tuned version this is not a cosmetic change but
    it is a small one — 4 m to 27 m is a 6.8x recession where I had authored
    5x — which is the useful result: the eye had got the perspective roughly
    right, and now it is right for a reason.

    Bank comes from the TURN, which is what a bank is. The old model rolled the
    bird off its wingbeat phase and correlated +0.275 with where the path
    actually turned.
    """
    dur = float(cfg.get('dur_s', 5.0))
    f_px, cx_px, cy_px, W, H = _bird_cam(cfg)
    us, arc, total_m = _bird_arc3(cfg)
    speed = cfg.get('speed_mps')
    if speed is None:
        s_arc = t_rel / dur  # constant along the path
    else:
        s_arc = min(1.0, max(0.0, float(speed) * t_rel / max(total_m, 1e-6)))

    def project(sa):
        u = _table_lookup(arc, us, sa)
        X, Y, Z = _catmull3(cfg['path3d'], u)
        Z = max(float(cfg.get('z_min', 0.6)), Z)
        return ((cx_px + f_px * X / Z) / W, (cy_px + f_px * Y / Z) / H), Z

    (x, y), Z = project(s_arc)
    ds = 0.004
    (xa, ya), _ = project(max(0.0, s_arc - ds))
    (xb, yb), _ = project(min(1.0, s_arc + ds))
    # (xb-xa, yb-ya) are in IMAGE-FRACTION units — x divided by W, y by H
    # separately. This plate is 2688x1536 (1.75:1), so atan2 on the raw
    # fractions answers a question about a SQUARE image that does not exist:
    # tan(angle_computed) = tan(angle_on_screen) * (W/H). Scale back to real
    # pixel units before the angle is taken, so `head` is the actual on-screen
    # tangent direction and not a version of it stretched by the aspect ratio.
    tx, ty = (xb - xa) * W, (yb - ya) * H
    m = math.hypot(tx, ty) or 1.0
    tx, ty = tx / m, ty / m

    tab = _bird_bank_table(cfg)
    fk = min(1.0, max(0.0, s_arc)) * (len(tab) - 1)
    k0 = int(fk)
    k1 = min(len(tab) - 1, k0 + 1)
    bank = tab[k0] + (tab[k1] - tab[k0]) * (fk - k0)

    ytab = _bird_yaw_table(cfg)
    fky = min(1.0, max(0.0, s_arc)) * (len(ytab) - 1)
    ky0 = int(fky)
    ky1 = min(len(ytab) - 1, ky0 + 1)
    yaw = ytab[ky0] + (ytab[ky1] - ytab[ky0]) * (fky - ky0)

    _, Z0 = project(0.0)
    return x, y, Z0 / Z, s_arc, tx, ty, bank, yaw


def _closed_spline(pts, n: int = 96):
    """A smooth closed loop through `pts` — Catmull-Rom with wrapped ends.

    The first bird was an ELLIPSE with a wedge stuck on the back, and at rest
    that silhouette is a fish. A bird's body is a teardrop: full at the breast,
    tapering to the tail, with the back arched and the belly flat-ish. That
    shape cannot be had from a primitive, and it is most of what makes the
    difference at 40 px.
    """
    m = len(pts)
    out = []
    for i in range(m):
        p0, p1, p2, p3 = pts[(i - 1) % m], pts[i], pts[(i + 1) % m], pts[(i + 2) % m]
        for k in range(max(2, n // m)):
            f = k / float(max(2, n // m))
            f2, f3 = f * f, f * f * f
            out.append(
                tuple(
                    0.5 * ((2 * b) + (-a + c) * f + (2 * a - 5 * b + 4 * c - d) * f2 + (-a + 3 * b - 3 * c + d) * f3)
                    for a, b, c, d in zip(p0, p1, p2, p3)
                )
            )
    return out


def _bird_wing_polys(sh: tuple, L: float, theta: float, chord: float):
    """The wing as ARM + HAND, plus the wrist and tip.

    Two segments, not one blade. A finch's wing bends at the wrist and the hand
    is swept much further back than the arm, and that kink is the whole reason a
    small bird's wing reads as a wing rather than as a paddle. The first cut had
    one straight blade from shoulder to tip and it looked like a paper aeroplane.

    Both segments are FORESHORTENED along the body axis by cos(theta), because
    the camera watches from the side: a wing held horizontal points at or away
    from the lens and is nearly edge-on, so its vertical extent collapses at
    mid-stroke while its sweep stays.
    """
    st, ct = math.sin(theta), math.cos(theta)
    wr = (sh[0] - L * 0.55 * (0.20 + 0.17 * ct), sh[1] - L * 0.55 * 1.06 * st)
    tip = (wr[0] - L * 0.45 * (0.62 + 0.22 * ct), wr[1] - L * 0.45 * 1.02 * st)

    def blade(a, b, c0, c1, bow_f, hollow):
        mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
        nx, ny = -(b[1] - a[1]), (b[0] - a[0])
        m = math.hypot(nx, ny) or 1.0
        nx, ny = nx / m, ny / m
        lead = _bez([a, (mx + nx * c0 * bow_f, my + ny * c0 * bow_f), b], 8)
        trail = _bez([b, (mx - nx * c1 * hollow, my - ny * c1 * hollow), (a[0] - c0 * 0.45, a[1] + c0 * 0.12)], 8)
        return lead + trail

    arm = blade(sh, wr, chord, chord * 0.72, 0.85, 0.30)
    hand = blade(wr, tip, chord * 0.72, chord * 0.16, 0.55, 0.55)
    return arm, hand, wr, tip


def _bird_box(base_size: tuple, cfg: dict, pose: dict) -> tuple:
    BW, BH = base_size
    L = float(cfg.get('size_frac', 0.030)) * BW * pose['scale']
    cx = pose['pos'][0] * BW
    cy = pose['pos'][1] * BH + pose['bob'] * L
    r = L * 2.0
    return (int(math.floor(cx - r)), int(math.floor(cy - r)), int(math.ceil(cx + r)), int(math.ceil(cy + r)))
